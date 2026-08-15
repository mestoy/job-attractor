#!/usr/bin/env python3
"""Append-only registry of every person weighed as a potential boss or hiring authority.

WHY THIS EXISTS. Three failures, all the same shape: research happened, nothing recorded it, and the
gap was invisible because no gate ever asked.

  1. The Nucleus VP was judged the likelier direct boss and that judgement lives nowhere. Weighing a
     person now produces a row AT THE MOMENT OF WEIGHING (the capture-as-you-go pattern).
  2. 96 send-log rows carry no recipient identity at all, so 96 cold-boss sends cannot be attributed
     to a person. `--boss` becomes required on cold-boss sends, in BOTH writers.
  3. The Pindrop incident: a finalist recorded on press-release evidence. A `finalist` verdict is
     REFUSED unless verification is `linkedin-live` or `company-page`.

⛔ THIS IS NOT AN AUTHORIZATION LEDGER, AND MUST NOT BE HARDENED INTO ONE. The rows are deliberately
unsigned. `documents/decision-ledger.jsonl` is MAC-signed because it records THE OWNER'S CONSENT, which
an agent could otherwise forge. A registry row records the AGENT'S OWN RESEARCH — there is no
authorization in it to forge, and signing it would imply one. BUILD still carries consent; this gate
enforces PROCESS (the research was recorded before the send), never permission.

Storage: `documents/state/boss.jsonl` via scripts/state.py's fifth kind. Append-only — corrections
are NEW rows, and the latest `ts` per key wins, the same read rule the rest of the store uses.

Usage:
    boss_registry.py add --person "Jake Cornelius" --company "Nucleus Security" \
        --verdict candidate --boss-read likely-boss --verified linkedin-live \
        --role-status current --linkedin jakecornelius --title "Principal PM, Core Platform"
    boss_registry.py add ... --verdict finalist --why "owns the half of the product he'd hire into"
    boss_registry.py show --company "Nucleus Security"
    boss_registry.py check --company "Nucleus Security" --person "Jake Cornelius"
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

# ⛔ AN AGGREGATOR IS ALWAYS `secondhand`, WHATEVER THE CALLER CLAIMS (added 2026-08-11).
# 📊 THREE WRONG BOSS NAMES IN ONE EVENING, all from aggregators, all confidently stated:
#   · One company     two aggregators gave two different names for the same role, and the
#                     employer's OWN leadership page named a THIRD. One wrong name was a step
#                     from entering a real message. Two other companies did the same thing that night.
# ⚖️ These sites are not lying, they are STALE and unaccountable: they scrape, they keep a departed
# exec for months, and nobody corrects them. That makes them fine for FINDING a name to check and
# unfit for BELIEVING one. The whole point of a rung 3-4 note is that it names the right human.
# 🎯 So the source TYPE is not the caller's to assert when the URL says otherwise. A name from one
# of these domains is `secondhand` by construction, and a `secondhand` boss must be confirmed
# against the employer's own materials before it reaches a message.
AGGREGATOR_DOMAINS = ("theorg.com", "zoominfo.com", "rocketreach.co", "apollo.io", "signalhire.com",
                      "adapt.io", "lusha.com", "crunchbase.com", "pitchbook.com", "tracxn.com",
                      "leadiq.com", "contactout.com", "seamless.ai", "clearbit.com", "owler.com",
                      "datanyze.com", "equilar.com", "people.equilar.com", "wiza.co")


def is_aggregator(source):
    """True when a source string points at a scraped directory rather than the employer itself."""
    low = (source or "").lower()
    return any(d in low for d in AGGREGATOR_DOMAINS)


def demote_if_aggregator(source, source_type):
    """(source_type, note_or_None). Forces `secondhand` when the source is an aggregator.

    Returns the type unchanged when the source is the employer's own site, a press release, or a
    live profile read. Never UPGRADES anything: this can only ever make a claim weaker.
    """
    if source_type in ("secondhand", "unverified") or not is_aggregator(source):
        return source_type, None
    return "secondhand", (f"source-type demoted to secondhand: {source!r} is an aggregator, which "
                          f"is fine for FINDING a name and unfit for believing one. Confirm against "
                          f"the employer's own materials before this name reaches a message.")
ROLE_STATUS = ("current", "departed", "unverified")

# A verdict that carries weight must say WHY, in the person's own record, at the time it was made.
WHY_REQUIRED = ("finalist", "ruled-out")

# THE PINDROP RULE. A finalist is a claim about a real person's real job. Press coverage and
# aggregators are secondhand and have been wrong here before, so they cannot mint one.
FINALIST_VERIFICATION = ("linkedin-live", "company-page")

# Verdicts that do NOT satisfy the send gate: ruled-out means the research concluded "not this one".
GATE_OK_VERDICTS = ("candidate", "finalist", "contacted")

# ⚠️ PROPOSAL, NOT A RULING (2026-07-27). A proposed number, never set by the owner. The block message
# prints this provenance so nobody mistakes it for a decision he made.
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
        print(f"⛔ BLOCKED: a finalist cannot rest on --verified {a.verified!r} (the Pindrop rule).",
              file=sys.stderr)
        print(f"   Finalists require one of: {', '.join(FINALIST_VERIFICATION)}.", file=sys.stderr)
        print("   Press coverage and aggregators are secondhand and have been wrong here before.", file=sys.stderr)
        print("   Record this person as 'candidate' instead, then verify and re-add.", file=sys.stderr)
        return 4

    # ⛔ KEY ON THE PERSON, because that is what the READER looks up (2026-07-30).
    # This used to be `a.linkedin or f"{a.company}/{a.person}"`, while `check()` has always used
    # `state.key_for("boss", a.person)`. The two disagreed, so a row written with a LinkedIn slug
    # that was not exactly the person's name landed where the reader would never look: 14 of 15
    # recorded bosses were UNFINDABLE, and the cold-boss send gate blocked people whose research
    # had been done and recorded. It only ever appeared to work when a slug happened to equal the
    # name. Same defect class as the known_companies gap the same day: the producer and the
    # consumer derived the key differently, and only the producer was ever tested.
    # The LinkedIn URL is still recorded in its own `linkedin` field; it is identity, not the key.
    raw_key = a.person
    # ── PROVENANCE, IN THE VOCABULARY `state.py` ACTUALLY RECOGNIZES (BUG-023, fixed 2026-08-08) ──
    #
    # 🔴 THE DEFECT. This writer emitted `ts` and `date` and stopped there. `state.py` reads
    # `as_of` for recency and `as_of_source` for provenance, and `_source_family()` recognizes
    # exactly four families: live, authored, export, git. A row with neither field is UNDATED to
    # every reader in that module and its provenance counts as **invalid**, which is what
    # `LiveStoreShapeTests` had been reporting for all 24 rows.
    #
    # ⚖️ THE FAMILY IS DERIVED FROM HOW THE SEAT WAS VERIFIED, not stamped as a constant. A seat
    # confirmed against a live LinkedIn profile is `live:` evidence and outranks one a human simply
    # asserted, which is the whole point of `SOURCE_PRECEDENCE`. Flattening every row to `authored`
    # would have made the check green while throwing away the distinction it exists to carry.
    # ⛔ An unrecognized or absent `--verified` falls to `authored`, never to a `live:` family. The
    # error that matters here is claiming verification that did not happen.
    _VERIFIED_FAMILY = {"linkedin-live": "live:linkedin",
                        "company-page": "live:company-page",
                        "press-release": "live:press-release"}
    _as_of = a.date or _today()
    _as_of_source = _VERIFIED_FAMILY.get(a.verified or "", "authored")
    row = {
        "ts": datetime.datetime.now().astimezone().isoformat(),
        "date": _as_of,
        # ⚠️ `as_of` DUPLICATES `date` ON PURPOSE. `date` is this file's own field and other readers
        # use it; `as_of` is the name `state.py` looks for. Writing one and hoping the other is
        # inferred is how these rows became invisible in the first place.
        "as_of": _as_of,
        "as_of_source": _as_of_source,
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
              f"(BOSS_FRESH_DAYS = {BOSS_FRESH_DAYS}, a PROPOSAL not yet ruled by the owner).",
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
