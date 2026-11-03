#!/usr/bin/env python3
"""balancer.py -- steer the picker default toward your target outreach mix.

Outreach reallocates by rung (a target split across warm / equipped cold-stranger /
equipped cold-boss) and, within tagged sends, by segment. A one-time plan for "the next
batch" is not enough on its own — this is a BALANCER that keeps adjusting the picker
default as sends accumulate.

This module reads a RECENT window of delivered initial-contact sends, computes the
actual share by rung and by segment, compares each to its target (from kit_config.py),
and recommends the next contact's rung and segment as the one most UNDER its target. As
sends accumulate the recommendation self-corrects back toward the target mix.

It is deliberately a READER over documents/send-log.jsonl (classification borrowed from
rung_ladder so the two never disagree). It never writes the log. Another script can import
recommend() to drive a picker's default; run standalone it prints the recommendation so you
can watch it work before wiring it into anything.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rung_ladder  # noqa: E402  (load / normalize_rung / NOT_DELIVERED)
try:  # noqa: E402
    from kit_config import (
        TARGET_RUNG_MIX,
        TARGET_SEGMENT_MIX,
        DEFAULT_BALANCER_WINDOW,
    )
except Exception:
    # A recipient's kit_config.py is copy-if-absent, so an older one may predate these
    # constants. Fall back to the shipped defaults rather than ImportError at module load.
    TARGET_RUNG_MIX = {"warm": 0.50, "cold-stranger": 0.30, "cold-boss": 0.20}
    TARGET_SEGMENT_MIX = {"segment-a": 0.34, "segment-b": 0.33, "segment-c": 0.33}
    DEFAULT_BALANCER_WINDOW = 25

INITIAL_CONTACT_RUNGS = ("warm", "cold-stranger", "cold-boss")


def _classify_rung(r):
    """The rung of one row, using rung_ladder's own equipped/unequipped split verbatim."""
    k = rung_ladder.normalize_rung(r.get("rung"))
    if k == "cold-boss" and not str(r.get("boss") or "").strip() \
            and str(r.get("praise_tier") or "none").lower() in ("", "none"):
        k = "cold-boss-unequipped"
    return k


def _window_rows(rows, window):
    """The most recent `window` DELIVERED initial-contact rows, oldest-to-newest order kept.

    Delivered = not in rung_ladder.NOT_DELIVERED. Initial contact = one of the three rungs
    the target mix balances (reply/follow-up/thank-you/application are inbound-bound or
    off-ladder and are not levers, so they never enter the window)."""
    kept = []
    for r in rows:
        if str(r.get("status", "")).lower() in rung_ladder.NOT_DELIVERED:
            continue
        k = _classify_rung(r)
        base = "cold-boss" if k == "cold-boss-unequipped" else k
        if base in INITIAL_CONTACT_RUNGS:
            kept.append((k, r))
    return kept[-window:] if window else kept


def _shares(counts):
    total = sum(counts.values()) or 1
    return {k: v / total for k, v in counts.items()}


def _deficits(actual_share, target):
    """target - actual per key, only for keys with a positive target. Largest = most owed."""
    return {k: round(target[k] - actual_share.get(k, 0.0), 4) for k in target}


def recommend(repo=None, window=DEFAULT_BALANCER_WINDOW):
    """Return the balancer's read: the next rung and segment most under target, plus tables.

    Shape: {rung, segment, rung_reason, segment_reason, window_n, untagged_frac,
            unequipped_n, rung_table, segment_table}. Safe on an empty/missing log."""
    repo = repo or os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(repo, "documents", "send-log.jsonl")
    try:
        rows = rung_ladder.load(path)
    except FileNotFoundError:
        rows = []

    win = _window_rows(rows, window)
    n = len(win)

    rung_counts = {k: 0 for k in TARGET_RUNG_MIX}
    unequipped_n = 0
    seg_counts = {}
    untagged = 0
    for k, r in win:
        if k == "cold-boss-unequipped":
            unequipped_n += 1
            rung_counts["cold-boss"] += 0  # a violation, not credited toward the equipped target
        elif k in rung_counts:
            rung_counts[k] += 1
        seg = str(r.get("segment") or "").strip().lower()
        if seg in TARGET_SEGMENT_MIX:
            seg_counts[seg] = seg_counts.get(seg, 0) + 1
        else:
            untagged += 1

    rung_share = _shares(rung_counts) if sum(rung_counts.values()) else {k: 0.0 for k in TARGET_RUNG_MIX}
    rung_def = _deficits(rung_share, TARGET_RUNG_MIX)
    rec_rung = max(rung_def, key=rung_def.get) if rung_def else next(iter(TARGET_RUNG_MIX), "warm")

    seg_share = _shares(seg_counts) if seg_counts else {k: 0.0 for k in TARGET_SEGMENT_MIX}
    seg_def = _deficits(seg_share, TARGET_SEGMENT_MIX)
    rec_seg = max(seg_def, key=seg_def.get) if seg_def else next(iter(TARGET_SEGMENT_MIX), "")

    untagged_frac = round(untagged / n, 3) if n else 0.0

    rung_reason = (f"{rec_rung} is {round(rung_share.get(rec_rung, 0)*100)}% of the last {n} "
                   f"vs a {round(TARGET_RUNG_MIX[rec_rung]*100)}% target, the biggest gap")
    seg_reason = (f"{rec_seg} is {round(seg_share.get(rec_seg, 0)*100)}% of tagged sends "
                  f"vs a {round(TARGET_SEGMENT_MIX[rec_seg]*100)}% target" if rec_seg else
                  "no segment targets configured in kit_config.py")

    return {
        "rung": rec_rung,
        "segment": rec_seg,
        "rung_reason": rung_reason,
        "segment_reason": seg_reason,
        "window_n": n,
        "untagged_frac": untagged_frac,
        "unequipped_n": unequipped_n,
        "rung_table": {k: (rung_counts[k], round(rung_share.get(k, 0), 3), TARGET_RUNG_MIX[k])
                       for k in TARGET_RUNG_MIX},
        "segment_table": {k: (seg_counts.get(k, 0), round(seg_share.get(k, 0), 3), TARGET_SEGMENT_MIX[k])
                          for k in TARGET_SEGMENT_MIX},
    }


def render(rec):
    """Human-readable block. Used by main() and available for another script to print."""
    out = []
    out.append("── BALANCER ──")
    out.append(f"  window: last {rec['window_n']} delivered initial contacts")
    out.append("")
    out.append("  RUNG            now   share   target")
    for k, (c, s, t) in rec["rung_table"].items():
        out.append(f"  {k:14} {c:>3}   {round(s*100):>4}%   {round(t*100):>4}%")
    if rec["unequipped_n"]:
        out.append(f"  ⚠️  {rec['unequipped_n']} unequipped cold-boss in window (not a lever, target 0)")
    out.append("")
    out.append("  SEGMENT              now   share   target")
    for k, (c, s, t) in rec["segment_table"].items():
        out.append(f"  {k:18} {c:>3}   {round(s*100):>4}%   {round(t*100):>4}%")
    if rec["untagged_frac"]:
        out.append(f"  ⚠️  {round(rec['untagged_frac']*100)}% of the window is untagged/off-segment")
    out.append("")
    out.append(f"  ➡️  NEXT: a {rec['rung']} contact in {rec['segment'] or '(no segment target configured)'}")
    out.append(f"      rung:    {rec['rung_reason']}")
    out.append(f"      segment: {rec['segment_reason']}")
    return "\n".join(out)


if __name__ == "__main__":
    win = DEFAULT_BALANCER_WINDOW
    if "--window" in sys.argv:
        try:
            win = int(sys.argv[sys.argv.index("--window") + 1])
        except (ValueError, IndexError):
            pass
    rec = recommend(window=win)
    if "--json" in sys.argv:
        print(json.dumps(rec, indent=2))
    else:
        print(render(rec))
