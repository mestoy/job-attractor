#!/usr/bin/env python3
"""rung_ladder.py — the reply rate per LaCivita rung, computed instead of remembered.

WHY THIS EXISTS. The ladder is the number you read to decide where to spend the day, and it is easy
to leave uncomputed, re-deriving it by hand into a handoff doc each time. Three errors survive that
way, and all three have been observed:

  1. `follow-up` and `followup` are SEPARATE keys in the raw data. A hand-built ladder merges them
     silently, so the merge may be right but is unrepeatable and unverifiable.
  2. Rows that never reached a human (bounced, drafted, staged) sat in the denominator. The 3-3-3
     check already excluded them, so the two counters disagreed about what a send IS.
  3. A handoff can call the total "a floor, not a measurement." It is a CEILING: every known gap is
     a missing SEND, and sends are the denominator, so closing the gap pushes the rate DOWN.

A number that is recomputed by hand drifts toward whatever the writer expects. This script is the
fix for that class of error, not for any one of the three.

⛔ READ-ONLY.

WHAT IT DELIBERATELY DOES NOT DO. It does not correct for the sends that are missing from the log
entirely (`scripts/reconcile_linkedin.py` measures those). So every rate here is
an UPPER BOUND on the truth, and the script says so in its own output rather than leaving the
reader to remember it.

Usage:
    scripts/rung_ladder.py                 # the ladder
    scripts/rung_ladder.py --all-rows      # include undelivered rows, to see what they cost
    scripts/rung_ladder.py --quiet         # totals only
Exit: 0 always (a report, not a gate)
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
SENDLOG = os.path.join(REPO, "documents", "send-log.jsonl")
sys.path.insert(0, HERE)

# Reuse BY IMPORT, never by copy. The rung vocabulary and the legacy-spelling map belong to the
# writer, and a second copy here would drift the moment a rung is added.
from log_linkedin_send import LEGACY_RUNG, NOT_DELIVERED, RUNGS  # noqa: E402

# Display order = LaCivita's ladder, cold at the bottom to warm at the top, then the off-ladder
# kinds. Sorting by volume instead would bury the rungs that matter under cold-boss every time.
LADDER_ORDER = [
    "cold-stranger", "cold-boss", "cold-boss-unequipped", "warm", "referred", "event",
    "follow-up", "reply", "thank-you", "reunion", "off-ladder", "application",
]
RUNG_LABEL = {
    "cold-stranger": "1-2  cold stranger",
    "cold-boss": "3-4  cold boss",
    "cold-boss-unequipped": "3-4  cold boss (no boss named, no praise)",
    "warm": "5-7  warm 1st-degree",
    "referred": "8-9  referred",
    "event": "     event",
    "follow-up": "     follow-up",
    "reply": "     reply",
    "thank-you": "     thank-you",
    "reunion": "     reunion (no ask)",
    "off-ladder": "     off-ladder",
    "application": "     application",
}


def load(path=SENDLOG):
    # A MISSING SEND LOG IS THE NORMAL DAY-ONE STATE, NOT AN ERROR (fix 2026-08-03). This used to
    # be an unguarded open(), so `python3 scripts/rung_ladder.py` on a fresh install died with
    # FileNotFoundError — and the PAIR gate is built on this ladder, so the very first thing a new
    # partner is told to run crashed. No sends yet simply means an empty ladder; say so by
    # returning no rows. OSError also covers a permissions/directory case, which is likewise not
    # something a briefing tool should traceback over.
    rows = []
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return rows
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def normalize_rung(raw):
    """Canonical rung for a row. Unknown spellings pass through so they stay VISIBLE.

    Swallowing an unrecognized rung into an 'other' bucket would hide exactly the drift this script
    exists to catch, so an unknown key is reported under its own name.
    """
    r = (raw or "?").strip()
    return LEGACY_RUNG.get(r, r)


# BACKFILL PROVENANCE, coalesced on READ. Two spellings of one concept accumulate in a send log
# that has been appended to by more than one generation of importer: `backfill` and `backfilled`.
# In a mature log neither is rare, and no row carries both. The VALUES differ because the
# provenances differ (which importer produced the row), so this coalesces the KEY and hands back the
# value; flattening both to a bool would throw away which import a row came from.
#
# Why this is not cosmetic: the marker's whole job is that a future ruling can FIND these rows and
# re-file them. A search for one spelling misses every row carrying the other, so the reversibility
# the marker promises holds for neither half. Any later un-backfill that reads one key silently
# spares the other import.
#
# ⛔ NORMALIZE ON READ, NEVER REWRITE THE LOG. The send log is the record of what happened; a row's
# spelling is part of that record. The readers adapt, the log does not.
BACKFILL_KEYS = ("backfill", "backfilled")


def backfill_source(row):
    """Provenance string for a reconstructed row, or None if it was logged at send time.

    Reads both spellings and returns the value under whichever is present, so the source survives
    the normalization. Callers wanting a yes/no use `is_backfilled`.
    """
    for k in BACKFILL_KEYS:
        v = row.get(k)
        if v not in (None, ""):
            return str(v)
    return None


def is_backfilled(row):
    """True when the row was reconstructed after the fact rather than logged at send time."""
    return backfill_source(row) is not None


ACCEPTANCE_RUNGS = frozenset({"cold-stranger"})


def _connections_slugs():
    """Every current 1st-degree connection's slug, from the newest export — or None (never an
    empty set) when no export is available, so a caller can tell "unmeasurable" from "measured zero".
    """
    try:
        from parse_network import find_export, parse_rows
        from reconcile_linkedin import slug_of
    except Exception:
        return None
    try:
        path, text = find_export()
    except Exception:
        return None
    if not path or not text:
        return None
    try:
        rows = parse_rows(text)
    except Exception:
        return None
    slugs = set()
    for r in rows:
        s = slug_of(r.get("URL"))
        if s:
            slugs.add(s)
    return slugs


def _row_slug(row):
    try:
        from reconcile_linkedin import slug_of
    except Exception:
        return None
    return slug_of(row.get("to"))


def acceptance_tally(rows, connections_slugs, include_undelivered=False):
    """{rung: [checked, accepted]} for the ACCEPTANCE_RUNGS only.

    An invitation note (rung 1-2) is scored on ACCEPTANCE, not on a written reply — the ask was to
    connect. `connections_slugs=None` means no export was available to check against, and the caller
    must render that as "not checked", never as a real 0%.
    """
    if connections_slugs is None:
        return {}
    agg = {}
    for r in rows:
        if not include_undelivered and str(r.get("status", "")).lower() in NOT_DELIVERED:
            continue
        k = normalize_rung(r.get("rung"))
        if k not in ACCEPTANCE_RUNGS:
            continue
        s = _row_slug(r)
        if not s:
            continue
        slot = agg.setdefault(k, [0, 0])
        slot[0] += 1
        if s in connections_slugs:
            slot[1] += 1
    return agg


def tally(rows, include_undelivered=False):
    """{rung: [sent, replied]} plus the count excluded as undelivered."""
    agg, dropped = {}, 0
    for r in rows:
        if not include_undelivered and str(r.get("status", "")).lower() in NOT_DELIVERED:
            dropped += 1
            continue
        k = normalize_rung(r.get("rung"))
        # ⛔ SPLIT THE UNEQUIPPED COLD-BOSS SENDS ONTO THEIR OWN LINE.
        # Rungs 3-4 mean writing directly to a NAMED boss, and the template is built on a SOURCED
        # praise hook: `log_linkedin_send.py` marks `--boss` REQUIRED on this rung, and the
        # invitation-note evidence measured 0 accepts on mail-merged openers against a healthy rate
        # on personalized ones. A cold-boss row with neither a boss nor a praise beat is the rung
        # fired without either of the two things that make it the rung.
        # ⚖️ THE POINT IS NOT TO FLATTER THE NUMBER. On the install where this was found, one burst
        # of unpersonalized volume dominated the rung and its low rate was being read as "cold boss
        # does not work". It could not support that: the properly equipped sample was n=1. Splitting
        # lets an equipped send be measured against its own record instead of inheriting a verdict.
        # ⛔ DEFINED BY THE MISSING FIELDS, NEVER BY A DATE, so a well-built cold-boss send lands on
        # the real line automatically and this cohort can only ever shrink.
        # The log is never rewritten; this is a READER's split.
        if k == "cold-boss" and not str(r.get("boss") or "").strip() \
                and str(r.get("praise_tier") or "none").lower() in ("", "none"):
            k = "cold-boss-unequipped"
        slot = agg.setdefault(k, [0, 0])
        slot[0] += 1
        if r.get("replied"):
            slot[1] += 1
    return agg, dropped


# ⛔ THE FIVE CORE RUNGS ALWAYS RENDER, ZEROS INCLUDED (2026-08-10, reported by a partner install).
# `render()` only emitted a line for a rung that had at least one send, so at low volume the ladder
# printed a nearly blank table and a brand-new log printed an empty body. The zeros ARE the signal:
# "referred still 0" is the entire point of the 8-9 nudge, and it vanished exactly when it mattered
# most, which is early. The off-ladder kinds (follow-up, reply, thank-you, reunion, application)
# stay conditional, because a zero there is noise rather than a nudge.
CORE_RUNGS = ["cold-stranger", "cold-boss", "warm", "referred", "event"]


def _order(agg):
    known = [k for k in LADDER_ORDER if k in agg or k in CORE_RUNGS]
    unknown = sorted(k for k in agg if k not in LADDER_ORDER)
    return known + unknown


def render(agg, dropped, quiet=False, acceptance=None, acceptance_available=True):
    sent = sum(v[0] for v in agg.values())
    replied = sum(v[1] for v in agg.values())
    acceptance = acceptance or {}
    out = []
    if not quiet:
        out.append(f"{'rung':24} {'sent':>5} {'replied':>8} {'rate':>7}  {'accepted':>14}")
        out.append("─" * 64)
        for k in _order(agg):
            s, rp = agg.get(k, (0, 0))
            label = RUNG_LABEL.get(k, f"     {k}")
            # `cold-boss-unequipped` is a READER-side split of a real rung, not a
            # value any writer emits, so it is known here and absent from `RUNGS`.
            flag = "" if k in RUNGS or k in ("?", "cold-boss-unequipped") \
                else "  ⚠️ unknown rung"
            if k in ACCEPTANCE_RUNGS:
                replied_cell, rate_cell = f"{'-':>8}", f"{'-':>7}"
            else:
                replied_cell, rate_cell = f"{rp:8}", f"{(100 * rp / s if s else 0):6.1f}%"
            if k in acceptance:
                chk, acc = acceptance[k]
                acc_cell = f"{acc}/{chk} ({100 * acc / chk if chk else 0:.1f}%)"
            elif k in ACCEPTANCE_RUNGS:
                acc_cell = "n/a" if acceptance_available else "not checked (no export)"
            else:
                acc_cell = ""
            out.append(f"{label:24} {s:5} {replied_cell} {rate_cell}  {acc_cell:>14}{flag}")
        out.append("─" * 64)
    out.append(f"{'TOTAL':24} {sent:5} {replied:8} {(100 * replied / sent if sent else 0):6.1f}%")
    if dropped:
        out.append(f"\n  {dropped} row(s) excluded as undelivered "
                   f"({', '.join(sorted(NOT_DELIVERED))})")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Reply rate per LaCivita rung")
    ap.add_argument("--all-rows", action="store_true",
                    help="include undelivered rows, to see what they cost")
    ap.add_argument("--quiet", action="store_true", help="totals only")
    ap.add_argument("--path", default=SENDLOG, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    rows = load(a.path)
    agg, dropped = tally(rows, include_undelivered=a.all_rows)
    connections_slugs = _connections_slugs()
    acceptance = acceptance_tally(rows, connections_slugs, include_undelivered=a.all_rows)
    print(render(agg, dropped, quiet=a.quiet, acceptance=acceptance,
                 acceptance_available=connections_slugs is not None))

    if not a.quiet:
        if not agg.get("referred", [0, 0])[0]:
            warm = agg.get("warm", [0, 0])[0]
            print(f"\n  🔴 rung 8-9 (referred) has NEVER been used, on {warm} warm sends. "
                  f"Rung 5-7 is what produces it.")
        print("\n  ⚠️ Every rate above is an UPPER BOUND. Sends missing from this log shrink the "
              "denominator\n     and inflate the rate; run scripts/reconcile_linkedin.py for the "
              "size of that gap.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
