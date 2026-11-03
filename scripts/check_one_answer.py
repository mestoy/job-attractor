#!/usr/bin/env python3
"""check_one_answer.py — refuse when two producers of the same quantity disagree.

WHY THIS EXISTS (BUG-270, 2026-09-12). `board.py` and `rung_ladder.py` both compute
delivered-send and reply counts from the same `documents/send-log.jsonl`, by two independently
maintained aggregation functions (`board.ladder()` and `rung_ladder.tally()`). They share one
rule for WHICH rows count (`board.counts_as_send()`, imported by both) since a status-based
divergence between them once ran undetected for 53 days, but the two functions themselves remain
separate code, and a future fix to one that never reaches the other is exactly this bug again,
one layer up. `kit_parity_check.py` cannot see this class — it diffs two COPIES of one file; this
checks two DIFFERENT files answering one question, wherever they both happen to live.

⛔ CALLS THE PRODUCERS, NEVER REIMPLEMENTS THEM. A checker with its own copy of the counting logic
is a third producer and a new instance of this bug. Every quantity below is read by importing the
real module and calling its real function against the real file.

THREE OUTCOMES, never collapsed to two:
  AGREE          — every producer returned the same value.
  DISAGREE       — producers ran clean and returned DIFFERENT values. Both values and both
                   producer names are printed; a number nobody can spot-check is worthless here.
  CANNOT COMPARE — a producer could not be imported or run. This is NOT agreement (a broken
                   producer that returns nothing is not "0 problems") and is reported and exited
                   distinctly from both, matching pii_gate's "GATE BROKEN" precedent.

Exit: 0 all AGREE · 1 any DISAGREE · 2 any CANNOT COMPARE (checked first: a broken comparison is
worse than a clean disagreement, since a broken one might be hiding either answer).

Usage:
    scripts/check_one_answer.py            # full report
    scripts/check_one_answer.py --quiet    # exit code only, one line on failure
"""
import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)


def _load(name, path):
    """Load a producer module by its EXPLICIT file path, never via sys.path.

    kit#(BUG-270 self-instance, 2026-09-12): this file used to `sys.path.insert(0, ...)` both
    `HERE` and the cross-tree `partner-starter/scripts/` at import time and never restored the
    list. Any LATER `import check_style` / `import verify_resume` in the same process then
    resolved to whichever copy's directory landed first — a checker built to catch two producers
    silently disagreeing was making a THIRD, unrelated producer win for everything imported after
    it. `spec_from_file_location` reads the named file directly and never touches `sys.path`, so
    a later bare `import check_style` elsewhere in the process is unaffected by this file having
    run at all."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _board_path():
    """In the main repo, board.py lives cross-tree in partner-starter/scripts/. In a
    single-tree install (this file deployed there), board.py is already a sibling via HERE.
    Prefer the cross-tree location when it exists, matching this file's own prior tolerance for
    a repo that may or may not have that second tree."""
    cross_tree = os.path.join(REPO, "partner-starter", "scripts", "board.py")
    return cross_tree if os.path.exists(cross_tree) else os.path.join(HERE, "board.py")


# ── the two live producers of "delivered sends / replies" ─────────────────────────────────────

def via_rung_ladder(repo):
    """(sent, replied) as rung_ladder.py itself computes them — imported, not re-derived."""
    rung_ladder = _load("rung_ladder", os.path.join(HERE, "rung_ladder.py"))
    path = os.path.join(repo, "documents", "send-log.jsonl")
    rows = rung_ladder.load(path)
    agg, _dropped = rung_ladder.tally(rows)
    return sum(v[0] for v in agg.values()), sum(v[1] for v in agg.values())


def via_board(repo):
    """(reached, replied) as board.py itself computes them — imported, not re-derived."""
    board = _load("board", _board_path())
    d = board.ladder(repo)
    return d["reached"], d["replied"]


# name, index into the (sent, replied) tuple, producers
QUANTITIES = [
    ("delivered sends", 0, [("rung_ladder.tally", via_rung_ladder), ("board.ladder", via_board)]),
    ("replies", 1, [("rung_ladder.tally", via_rung_ladder), ("board.ladder", via_board)]),
]


def check_quantity(name, idx, producers, repo):
    """One of AGREE / DISAGREE / BROKEN, plus the values and errors that back the verdict."""
    values, errors = {}, {}
    for label, fn in producers:
        try:
            values[label] = fn(repo)[idx]
        except Exception as e:  # noqa: BLE001 — any producer failure is CANNOT COMPARE, not 0
            errors[label] = f"{e.__class__.__name__}: {e}"
    if errors:
        return "BROKEN", values, errors
    if len(set(values.values())) > 1:
        return "DISAGREE", values, errors
    return "AGREE", values, errors


def run(repo, quiet=False):
    worst = 0  # 0 agree, 1 disagree, 2 broken
    lines = []
    for name, idx, producers in QUANTITIES:
        status, values, errors = check_quantity(name, idx, producers, repo)
        if status == "BROKEN":
            worst = max(worst, 2)
            detail = "; ".join(f"{label} CANNOT RUN ({err})" for label, err in errors.items())
            lines.append(f"🔴 CANNOT COMPARE '{name}': {detail}")
        elif status == "DISAGREE":
            worst = max(worst, 1)
            detail = " vs. ".join(f"{label}={v}" for label, v in values.items())
            lines.append(f"🔴 DISAGREE on '{name}': {detail}")
        else:
            if not quiet:
                detail = ", ".join(f"{label}={v}" for label, v in values.items())
                lines.append(f"🟢 '{name}' agrees: {detail}")
    if worst == 0 and quiet:
        lines = ["🟢 check_one_answer: all multi-producer quantities agree"]
    return worst, lines


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    code, lines = run(args.repo, quiet=args.quiet)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
