#!/usr/bin/env python3
"""Append-only registry of every person weighed as a potential boss or hiring authority.

WHY THIS EXISTS. Three failures, all the same shape: research happened, nothing recorded it, and the
gap was invisible because no gate ever asked.

  1. A person judged the likelier direct boss, with that judgement living nowhere. Weighing a person
     now produces a row AT THE MOMENT OF WEIGHING (the capture-as-you-go pattern).
  2. Send-log rows carrying no recipient identity at all, so the sends cannot be attributed to a
     person and the research behind them is unrecoverable. `--boss` becomes required on cold-boss
     sends, in BOTH writers.
  3. A finalist recorded on press-release evidence, which turned out to be wrong. A `finalist`
     verdict is REFUSED unless verification is `linkedin-live` or `company-page`.

⛔ THIS IS NOT AN AUTHORIZATION LEDGER, AND MUST NOT BE HARDENED INTO ONE. The rows are deliberately
unsigned. `documents/decision-ledger.jsonl` is MAC-signed because it records THE OWNER'S CONSENT, which
an agent could otherwise forge. A registry row records the AGENT'S OWN RESEARCH — there is no
authorization in it to forge, and signing it would imply one. BUILD still carries consent; this gate
enforces PROCESS (the research was recorded before the send), never permission.

Storage: `documents/state/boss.jsonl` via scripts/state.py's fifth kind. Append-only — corrections
are NEW rows, and the latest `ts` per key wins, the same read rule the rest of the store uses.

Usage:
    boss_registry.py add --person "Dana Fake" --company "Acme" \
        --verdict candidate --boss-read likely-boss --verified linkedin-live \
        --role-status current --linkedin danafake --title "Principal PM, Core Platform"
    boss_registry.py add ... --verdict finalist --why "owns the half of the product you'd hire into"
    boss_registry.py show --company "Acme"
    boss_registry.py check --company "Acme" --person "Dana Fake"
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import state  # noqa: E402  (path must be set first)

# ── vocabularies. An unknown value is REFUSED loudly, never coerced to a default ──────────────
VERDICTS = ("candidate", "finalist", "ruled-out", "contacted")
BOSS_READS = ("direct-boss", "likely-boss", "founder-fallback", "hiring-authority", "not-the-boss")
VERIFIED = ("linkedin-live", "company-page", "press-release", "secondhand", "unverified")
ROLE_STATUS = ("current", "departed", "unverified")

# A verdict that carries weight must say WHY, in the person's own record, at the time it was made.
WHY_REQUIRED = ("finalist", "ruled-out")

# THE FIRSTHAND-ONLY RULE. A finalist is a claim about a real person's real job. Press coverage and
# aggregators are secondhand and have been wrong here before, so they cannot mint one.
FINALIST_VERIFICATION = ("linkedin-live", "company-page")

# Verdicts that do NOT satisfy the send gate: ruled-out means the research concluded "not this one".
GATE_OK_VERDICTS = ("candidate", "finalist", "contacted")

# Freshness window, in days. Tune it to how fast your targets change jobs.
BOSS_FRESH_DAYS = 30

# Any RETROSPECTIVE sweep (checking historical send-log rows against this registry) must require
# coverage only for cold-boss rows dated on or after this date. The send gate itself is prospective
# and never reads history, so it needs no exemption; a backward-looking report would otherwise fire
# on 96 identity-less rows that can never gain a record.
REGISTRY_EPOCH = "2026-07-27"


def _today():
    return datetime.date.today().isoformat()


def _rows():
    """Every registry row, oldest first. Missing store is empty, never an error."""
    path = state.store_path("boss")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue  # a corrupt line must not blind the gate to the good ones
    return out


def _latest_by_key(rows):
    """Latest row per key. Same precedence rule as state.current(): newest ts wins."""
    best = {}
    for r in rows:
        k = r.get("key") or ""
        if not k:
            continue
        if k not in best or (r.get("ts") or "") >= (best[k].get("ts") or ""):
            best[k] = r
    return best


def _company_matches(want, got):
    """Company equality on canonical keys, with the word-boundary rule.

    Straight substring matching is how "ZZ" would authorize a send to "ZZNorthwind". The BUILD gate
    learned this the same way (mail-draft.sh's `_bounded`); reuse the reasoning, not a copy of the
    regex, since the inputs here are already canonicalized.
    """
    a, b = state.key_for("company", want or ""), state.key_for("company", got or "")
    if not a or not b:
        return False
    if a == b:
        return True
    return re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", b) is not None


def cmd_add(a):
    for field, vocab in (("verdict", VERDICTS), ("boss_read", BOSS_READS),
                         ("verified", VERIFIED), ("role_status", ROLE_STATUS)):
        val = getattr(a, field)
        if val not in vocab:
            print(f"⛔ BLOCKED: --{field.replace('_', '-')} {val!r} is not one of: {', '.join(vocab)}",
                  file=sys.stderr)
            return 4

    if a.verdict in WHY_REQUIRED and not (a.why or "").strip():
        print(f"⛔ BLOCKED: --why is REQUIRED for verdict '{a.verdict}'.", file=sys.stderr)
        print("   A finalist or a ruled-out with no reason is the failure this registry exists to", file=sys.stderr)
        print("   stop: the judgement survives, the reasoning does not, and nobody can re-check it.", file=sys.stderr)
        return 4

    if a.verdict == "finalist" and a.verified not in FINALIST_VERIFICATION:
        print(f"⛔ BLOCKED: a finalist cannot rest on --verified {a.verified!r} (secondhand evidence).",
              file=sys.stderr)
        print(f"   Finalists require one of: {', '.join(FINALIST_VERIFICATION)}.", file=sys.stderr)
        print("   Press coverage and aggregators are secondhand and have been wrong here before.", file=sys.stderr)
        print("   Record this person as 'candidate' instead, then verify and re-add.", file=sys.stderr)
        return 4

    raw_key = a.linkedin or f"{a.company}/{a.person}"
    row = {
        "ts": datetime.datetime.now().astimezone().isoformat(),
        "date": a.date or _today(),
        "kind": "boss",
        "key": state.key_for("boss", raw_key),
        "person": a.person,
        "linkedin": a.linkedin or "",
        "company": a.company,
        "title": a.title or "",
        "verdict": a.verdict,
        "why": (a.why or "").strip(),
        "boss_read": a.boss_read,
        "verified": a.verified,
        "role_status": a.role_status,
        "source_urls": [u for u in (a.source_url or []) if u],
    }
    if a.dry_run:
        print(json.dumps(row, indent=2, ensure_ascii=False))
        return 0

    path = state.store_path("boss")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"✅ recorded {a.person} @ {a.company} — {a.verdict} / {a.boss_read} / {a.verified}")
    if a.verdict == "finalist":
        print(f"   why: {row['why']}")
    return 0


def cmd_show(a):
    rows = [r for r in _rows() if not a.company or _company_matches(a.company, r.get("company"))]
    if not rows:
        print(f"(no registry rows{' for ' + a.company if a.company else ''})")
        return 0
    for r in sorted(_latest_by_key(rows).values(), key=lambda r: r.get("person", "")):
        stale = ""
        if r.get("date", "") < (datetime.date.today()
                                - datetime.timedelta(days=BOSS_FRESH_DAYS)).isoformat():
            stale = "  ⏳ STALE"
        print(f"  {r.get('verdict','?'):10} {r.get('person','?'):26} @ {r.get('company','?')}")
        print(f"     {r.get('boss_read','?')} · verified:{r.get('verified','?')} · "
              f"role:{r.get('role_status','?')} · {r.get('date','?')}{stale}")
        if r.get("why"):
            print(f"     why: {r['why']}")
    return 0


def cmd_check(a):
    max_age = a.max_age if a.max_age is not None else BOSS_FRESH_DAYS
    cutoff = (datetime.date.today() - datetime.timedelta(days=max_age)).isoformat()
    want_key = state.key_for("boss", a.person)

    rows = [r for r in _rows() if _company_matches(a.company, r.get("company"))]
    latest = _latest_by_key(rows)
    hit = latest.get(want_key)
    if hit is None:
        # fall back to the composite key, for a person recorded without a LinkedIn slug
        hit = latest.get(state.key_for("boss", f"{a.company}/{a.person}"))

    def block(reason, fix):
        print(f"⛔ BOSS REGISTRY: {reason}", file=sys.stderr)
        print(f"   {fix}", file=sys.stderr)
        print(f"   Freshness window is {max_age} days "
              f"(BOSS_FRESH_DAYS = {BOSS_FRESH_DAYS}).",
              file=sys.stderr)
        return 1

    if hit is None:
        return block(
            f"no record for {a.person!r} at {a.company!r}.",
            "Record the research first:  scripts/boss_registry.py add --person ... --company ... "
            "--verdict candidate --boss-read likely-boss --verified linkedin-live --role-status current")
    if hit.get("verdict") not in GATE_OK_VERDICTS:
        return block(f"{a.person} is recorded {hit.get('verdict')!r} at {a.company}.",
                     "A ruled-out person is not a send target. Pick someone else, or re-add with a why.")
    if hit.get("boss_read") == "not-the-boss":
        return block(f"{a.person} is recorded 'not-the-boss'.",
                     "Andy p.10: target the recruitment team, HR or a teammate instead, then the ATS.")
    if hit.get("role_status") == "departed":
        return block(f"{a.person} is recorded as DEPARTED from {a.company}.",
                     "Verify the seat on LinkedIn and re-add with --role-status current.")
    if (hit.get("date") or "") < cutoff:
        return block(f"the record for {a.person} is from {hit.get('date')}, older than {max_age} days.",
                     "Re-verify the seat and re-add. A stale seat is how a send reaches someone who left.")
    print(f"🟢 boss registry OK — {a.person} @ {a.company} "
          f"({hit.get('verdict')} / {hit.get('boss_read')} / verified:{hit.get('verified')}, "
          f"{hit.get('date')})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="record a person weighed as a potential boss")
    p.add_argument("--person", required=True)
    p.add_argument("--company", required=True)
    p.add_argument("--verdict", required=True, help=" | ".join(VERDICTS))
    p.add_argument("--boss-read", required=True, dest="boss_read", help=" | ".join(BOSS_READS))
    p.add_argument("--verified", required=True, help=" | ".join(VERIFIED))
    p.add_argument("--role-status", required=True, dest="role_status", help=" | ".join(ROLE_STATUS))
    p.add_argument("--why", default="", help="REQUIRED for finalist / ruled-out")
    p.add_argument("--linkedin", default="", help="slug or profile URL; the strong key")
    p.add_argument("--title", default="")
    p.add_argument("--source-url", action="append", default=[])
    p.add_argument("--date", default="")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("show", help="latest row per person, with provenance")
    p.add_argument("--company", default="")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("check", help="exit 0 iff a fresh qualifying record exists")
    p.add_argument("--company", required=True)
    p.add_argument("--person", required=True)
    p.add_argument("--max-age", type=int, default=None)
    p.set_defaults(fn=cmd_check)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
