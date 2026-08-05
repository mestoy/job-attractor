#!/usr/bin/env python3
"""log_linkedin_send.py — write a send-log row for a LinkedIn message.

WHY THIS EXISTS (2026-07-24)
----------------------------
`mail-draft.sh` is the ONLY writer of `documents/send-log.jsonl`, and LinkedIn outreach is
deliberately paste-and-send (browser prefill is RETIRED, WORKFLOW-RULES §8). So **every LinkedIn
message silently skips the log**, and that log is the source of truth for FOUR mechanisms:

  1. `replied`            → every reply-rate number, including the per-rung ladder
  2. the 3-3-3 counter    → consistency-check [13]
  3. the segment hot-zone → consistency-check [15]
  4. `targets`            → `rank_criteria.burned_targets()`, the guard that stops one company
                            being named in two different warm trios

It bit twice in one day on 2026-07-24:

  • Three real replies (three warm contacts) sat flagged `False`, so the
    ladder reported the WARM rung at **0%** when it was in fact running at 13.6% — the best rung
    on the board, and the one the strategy had just pivoted to.
  • A rung-7 trio named to one contact never burned, so the ranker
    would have re-offered those same three companies to the next contact the following morning. That is the exact
    convergence Andy forbids (Boss Hunting Bible p.3: *"No. Pick the one you think is most likely
    the 'direct' boss and try that person first."*).

Three rows had to be hand-written that day. This script is the fix.

PARITY WITH mail-draft.sh IS THE POINT
--------------------------------------
mail-draft.sh carries the warm-only follow-up rule (see its FOLLOW-UP ARMING block) with this comment: *"Both paths must agree
or the rule is decorative."* The same applies here. `_followup_for()` below mirrors that case
statement exactly, and `tests/test_groupD_send.py` asserts the two stay in sync.

USAGE
-----
    python3 scripts/log_linkedin_send.py --rung warm --to linkedin.com/in/example \
        --company ExampleCo --targets "AlphaCo,BetaCo,GammaCo" --segment payments \
        --note "rung-7 trio ask"

    python3 scripts/log_linkedin_send.py --rung reply --to linkedin.com/in/example2 \
        --company "ExampleCo2" --no-targets --followup-due 2026-07-31

    python3 scripts/log_linkedin_send.py --mark-replied --to linkedin.com/in/example
"""
import argparse
import datetime
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENDLOG = os.path.join(REPO, "documents", "send-log.jsonl")
OUTREACH_LOG = os.path.join(REPO, "outreach_log.md")

# Rungs mail-draft.sh accepts, plus the LinkedIn-only ones. `followup` (no hyphen) is a LEGACY
# spelling that exists in historical rows; we normalize to `follow-up` on write but still accept it
# so a user copying an old row does not get a spurious error.
RUNGS = {
    "cold-boss", "cold-stranger", "warm", "referred", "event", "off-ladder",
    "reply", "thank-you", "follow-up", "reunion", "application",
}
LEGACY_RUNG = {"followup": "follow-up"}

# Statuses meaning NOTHING REACHED THE PERSON, so the row must not count as a send.
# ⚠️ HAND-MIRRORED from consistency-check.sh's NOT_DELIVERED, the same way _followup_for below
# mirrors mail-draft.sh. It cannot be imported: that copy lives inside a shell heredoc. Two counters
# disagreeing about what a send IS is a real defect — a daily-send check that excludes bounces while
# a reply-rate table counts them puts rows in the denominator that never arrived.
# If you edit one copy, edit both; a test pins them together.
NOT_DELIVERED = {"bounced", "drafted", "staged", "failed", "blocked"}

# WARM-ONLY FOLLOW-UPS. Mirrors mail-draft.sh:394-399 exactly. A cold boss who
# does not answer gets NO second touch; the next action is a NEW target (Bible p.9, p.10).
ARMS_FOLLOWUP = {"warm", "referred", "event", "off-ladder"}

# Rungs where the ask NAMES target companies, so an empty `targets` is almost certainly a mistake
# that silently defeats the burn guard. Requires an explicit --no-targets to proceed.
TARGETS_EXPECTED = {"warm", "referred"}


def _followup_for(rung, override=None, suppress=False):
    """Return the follow-up date string. Parity with mail-draft.sh:394."""
    if suppress:
        return ""
    if override:
        return override
    if rung in ARMS_FOLLOWUP:
        return (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    return ""


def _load(path=SENDLOG):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                # A malformed historical line must not stop a send from being logged. Skipping is
                # correct here: this file is append-mostly and we rewrite it whole below.
                pass
    return rows


def _write(rows, path=SENDLOG):
    rows.sort(key=lambda r: (r.get("date", ""), r.get("ts", "")))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _slug(value):
    """LinkedIn slug for a `to` value, else None. Imported, never reimplemented.

    sync_contacted already parses every shape this field comes in (`linkedin:handle`, a full
    profile URL, trailing slashes, query strings). Reuse BY IMPORT, never by copy.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from sync_contacted import _slug_from_to
        return _slug_from_to(value or "")
    except ImportError:
        return None


def same_recipient(a, b):
    """Do two `to` values name the same person?

    THE DEFECT THIS FIXES. `--to` accepts BOTH `linkedin.com/in/<handle>` and `linkedin:handle` and
    normalizes neither, so a row stored one way is invisible to a lookup phrased the other way. The
    two spellings tend to partition a log rather than overlap, because whichever form you used the
    first time is the form you keep using. Marking a reply then fails silently, or files the reply
    under a second key for a person who already has a row, breaking the send-to-reply pairing that
    every reply-rate number is computed from.

    Falls back to exact equality for anything that is not a LinkedIn identity (emails, SMS rows,
    group threads), which must keep comparing as opaque strings.
    """
    if a == b:
        return True
    sa, sb = _slug(a), _slug(b)
    return bool(sa and sb and sa.lower() == sb.lower())


def _compress(slug):
    """Alphabetic-only form of a slug, dropping hyphens and any trailing numeric id.

    Lossy ON PURPOSE and used only to SUGGEST, never to assert a match: it collapses
    `first-last`, `firstlast` and `first-last-8412` onto each other, which is the family of near
    misses a hand-typed handle produces.
    """
    return "".join(t for t in re.split(r"[^A-Za-z0-9]+", (slug or "")) if t.isalpha()).lower()


def _near_misses(to, rows, limit=3):
    """Rows whose handle compresses to the same string as `to`. Suggestions only."""
    target = _compress(_slug(to) or to)
    if not target:
        return []
    out = []
    for r in rows:
        raw = r.get("to")
        if not raw or same_recipient(raw, to):
            continue
        if _compress(_slug(raw) or raw) == target:
            out.append(r)
    return sorted(out, key=lambda r: (r.get("date", ""), r.get("ts", "")), reverse=True)[:limit]


def mark_replied(to, path=SENDLOG, when=None):
    """Set replied=True on the most recent row for `to`. Returns the row or None.

    Backfilling replies by hand is what produced the 0%-warm-reply-rate defect, so this is a
    first-class command rather than something to do in an ad-hoc heredoc.
    """
    rows = _load(path)
    hits = [r for r in rows if same_recipient(r.get("to"), to)]
    if not hits:
        return None
    target = max(hits, key=lambda r: (r.get("date", ""), r.get("ts", "")))
    target["replied"] = True
    target["replied_note"] = f"marked replied {when or datetime.date.today().isoformat()}"
    _write(rows, path)
    return target



def _append_narrative(row, a, rung):
    """Append a `## <date>` entry to outreach_log.md so BOTH daily counters move on one send.

    There are two counters for one number and they read different stores: `## <date>` headers in
    outreach_log.md (the narrative log, one per write-up) and rows in send-log.jsonl (the machine
    log, one per send). When only the machine log is written, every hand-sent message leaves the
    two disagreeing, and a number nobody trusts stops being useful.

    This writes the HEADER and the facts it can prove. The verbatim body is written when --body is
    supplied; without it the entry says so plainly rather than implying a write-up that does not
    exist. A store that is not written is a store that lies.
    """
    body = a.body
    if body and os.path.exists(body):
        body = open(body, encoding="utf-8").read().strip()

    who = getattr(a, "boss", None) or a.to
    company = a.company or "no company named"
    chan = row.get("channel", "LinkedIn")
    bits = [f"## {row['date']} · {company} · {who} — ✅ SENT [{chan} · rung {rung}]"]
    bits.append(f"**Status:** ✅ SENT {row['date']} on {chan}. You typed and sent it.")
    bits.append(f"**Rung:** {rung} (kind:{a.kind}) | channel:{chan} | status:{a.status}")
    if a.targets:
        bits.append(f"**Targets named (now burned):** {a.targets}")
    if getattr(a, "referred_by", None):
        bits.append(f"**Referred by:** {a.referred_by}")
    if a.praise_tier:
        bits.append(f"**Praise tier:** {a.praise_tier}")
    if a.note:
        bits.append(f"**Note:** {a.note}")
    if body:
        bits.append("**Verbatim as sent:**")
        bits.extend("> " + ln if ln.strip() else ">" for ln in body.splitlines())
    else:
        bits.append("**Verbatim as sent:** ⚠️ not captured at log time (no --body). "
                    "Paste it in; the send-log row is already correct.")
    with open(OUTREACH_LOG, "a", encoding="utf-8") as fh:
        fh.write("\n" + "\n".join(bits) + "\n\n")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Log a LinkedIn send to documents/send-log.jsonl")
    ap.add_argument("--rung", help="one of: " + ", ".join(sorted(RUNGS)))
    ap.add_argument("--to", required=True, help="linkedin.com/in/<handle> or linkedin:<handle>")
    ap.add_argument("--company", default="")
    ap.add_argument("--targets", default="", help="comma-separated companies NAMED in the ask; these BURN")
    ap.add_argument("--no-targets", action="store_true", help="acknowledge a warm send that names no companies")
    ap.add_argument("--segment", default="")
    ap.add_argument("--kind", default="initial", choices=["initial", "reply"])
    ap.add_argument("--status", default="sent", choices=["sent", "bounced", "drafted"])
    ap.add_argument("--note", default="", help="sent_note: what it was and why")
    ap.add_argument("--praise-tier", choices=["A", "B", "none"], default=None,
                    help="A=primary-sourced artifact, B=specifics about their background, "
                         "none=no praise beat. Recorded so the reply rates of A vs B can be "
                         "compared before you loosen or tighten the rule.")
    ap.add_argument("--body", default="", help="path to the message text, or the text itself; "
                                               "written verbatim into outreach_log.md")
    ap.add_argument("--no-narrative", action="store_true",
                    help="skip the outreach_log.md entry (use only when writing it up by hand)")
    ap.add_argument("--followup-due", default=None, help="YYYY-MM-DD; overrides the rung default")
    ap.add_argument("--no-followup", action="store_true", help="deliberately arm nothing")
    ap.add_argument("--mark-replied", action="store_true", help="flip the latest row for --to to replied")
    ap.add_argument("--boss", default="", help="REQUIRED on --rung cold-boss: the person, "
                                              "checked against documents/state/boss.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--path", default=SENDLOG, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    if a.mark_replied:
        row = mark_replied(a.to, a.path)
        if not row:
            print(f"🔴 no send-log row found for {a.to}", file=sys.stderr)
            # A bare miss sends the reader hunting through the whole log. A handle typed or
            # guessed rather than copied from the profile is common, so "no row" usually means
            # "the row is there under a wrong handle". Naming the near miss surfaces that at the
            # one moment a person is looking at it.
            for cand in _near_misses(a.to, _load(a.path)):
                print(f"   ↳ did you mean {cand['to']!r}? "
                      f"({cand.get('date')} · rung={cand.get('rung')})", file=sys.stderr)
            return 1
        print(f"✅ marked replied: {row.get('date')} · rung={row.get('rung')} · {a.to}")
        return 0

    if not a.rung:
        print("🔴 --rung is required (or use --mark-replied)", file=sys.stderr)
        return 2
    rung = LEGACY_RUNG.get(a.rung, a.rung)
    if rung not in RUNGS:
        print(f"🔴 unknown rung {a.rung!r}. One of: {', '.join(sorted(RUNGS))}", file=sys.stderr)
        return 2

    # THE BURN GUARD. A warm ask that names companies must record them, or rank_criteria will
    # re-offer the same companies to the next contact. Fail loudly rather than log a row that
    # looks complete and silently defeats the guard.
    if rung in TARGETS_EXPECTED and not a.targets and not a.no_targets:
        print(f"🔴 rung {rung!r} usually NAMES target companies, and --targets is empty.\n"
              "   Those companies BURN on naming (Bible p.3), and rank_criteria.burned_targets()\n"
              "   reads this field. Pass --targets \"A,B,C\", or --no-targets if the message named none.",
              file=sys.stderr)
        return 2


    # BOSS REGISTRY, cold-boss only. Parity with mail-draft.sh: both paths must agree or the rule is
    # decorative. Scoped to cold-boss ALONE — cold-stranger has no boss, and a gate written for one
    # rung binds every rung that falls through to it.
    if rung == "cold-boss":
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import boss_registry
            if not a.boss:
                print("⛔ BLOCKED: missing --boss on a cold-boss send. Name the person you researched.")
                return 4
            if boss_registry.main(["check", "--company", a.company or "", "--person", a.boss]) != 0:
                return 4
        except ImportError:
            pass  # registry absent on a fresh install: degrade rather than block every send
    rows = _load(a.path)
    today = datetime.date.today().isoformat()
    dupes = [r for r in rows
             if same_recipient(r.get("to"), a.to) and r.get("date") == today and r.get("rung") == rung]
    if dupes:
        print(f"⚠️  {len(dupes)} row(s) already logged today for {a.to} at rung {rung} — check for a double-log.")

    row = {
        "ts": datetime.datetime.now().astimezone().isoformat(),
        "date": today,
        "rung": rung,
        "to": a.to,
        "company": a.company,
        "targets": a.targets,
        "subject": "(LinkedIn, in-thread)" if a.kind == "reply" else "(LinkedIn)",
        "segment": a.segment,
        "kind": a.kind,
        "followup_due": _followup_for(rung, a.followup_due, a.no_followup),
        "status": a.status,
        "replied": False,
        "sent_note": a.note or "logged via log_linkedin_send.py (LinkedIn paste-and-send)",
    }

    if a.praise_tier:
        # Two-tier praise beat: A=artifact, B=specifics about their background. Stored so the
        # reply rates can be compared; a two-tier rule nobody measures is just a looser rule.
        row["praise_tier"] = a.praise_tier

    if a.dry_run:
        print(json.dumps(row, ensure_ascii=False, indent=1))
        return 0

    rows.append(row)
    _write(rows, a.path)

    print(f"✅ logged: rung={rung} · {a.to} · status={a.status}")
    if a.no_narrative:
        print("   📝 outreach_log.md SKIPPED (--no-narrative) — the two daily counters will disagree")
    else:
        try:
            _append_narrative(row, a, rung)
            print("   📝 outreach_log.md entry appended (both daily counters now agree)")
        except Exception as exc:
            print(f"   ⚠️  outreach_log.md NOT written ({exc}) — counters will disagree, fix by hand")
    if row["followup_due"]:
        print(f"   📒 follow-up armed {row['followup_due']}")
    else:
        print("   📒 NO follow-up armed"
              + ("  (deliberate, --no-followup)" if a.no_followup
                 else "  (cold or post-contact rung — warm-only policy 2026-07-23)"))
    if a.targets:
        burned = [t.strip() for t in a.targets.split(",") if t.strip()]
        print(f"   🔥 BURNED {len(burned)}: {', '.join(burned)}  (rank_criteria will now exclude them)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
