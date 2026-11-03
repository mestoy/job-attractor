#!/usr/bin/env python3
"""chain_depth.py — the causal chain's three queues, depth over denominator.

Same output shape as scripts/depth_report.py: one table, stage -> depth over denominator,
gaps against floors. documents/plan-design-ube-2026-09-12.md Section 2 is the spec.

FLOORS. None yet, deliberately. His words on CARD_FLOOR/BUILD_FLOOR (kit issue #115):
a floor over a PASS-THROUGH stage is unreachable by construction, so a floor is set only
after a week of readings lets each queue be classified stock (holds inventory, a floor
makes sense) or pass-through (consumed the same day it is entered, a floor never can be
met). FLOORS below ships empty on purpose; filling it before that classification repeats
the BUILD_FLOOR mistake.

LINKS BROKEN. chain.py validates every link at import time and raises before this script
can even see the data. If import fails, this script prints why and refuses to print any
depth line — a broken link is worse than no report, never a report with a silent gap.

Usage:
    python3 scripts/chain_depth.py
    python3 scripts/chain_depth.py --print
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "app", "design"))

FLOORS = {}


def _import_chain():
    try:
        import chain  # noqa: E402  (path inserted above)
        return chain, None
    except Exception as exc:  # the whole point: a broken link must not crash silently elsewhere
        return None, exc


def render():
    chain, err = _import_chain()
    if err is not None:
        return (
            "# Chain depth\n\n"
            f"🔴 links broken: {err}\n\n"
            "No depth line printed. A chain with a broken link is not a chain with a gap in "
            "it, it is a chain that has not been proven to hang together, so nothing below "
            "this line is trustworthy enough to show.\n"
        ), 1

    d_p = chain.depth(chain.PROBLEMS)
    d_h = chain.depth(chain.HYPOTHESES)
    d_e = chain.depth(chain.EXPERIMENTS)

    ruled_p = sum(v for k, v in d_p.items() if k not in ("_total", "FRAMED"))
    # RETIRED is excluded from both the numerator and the denominator of "prioritized" /
    # "running" -- a retired row is neither progress nor backlog, so folding it into either
    # denominator would understate how close the real queue is to done. It gets its own
    # line instead, over the TRUE total, so retirement is visible rather than absorbed.
    retired_h = d_h.get("RETIRED", 0)
    prioritized_h = sum(v for k, v in d_h.items() if k not in ("_total", "DRAFTED", "RETIRED"))
    hyp_denominator = d_h["_total"] - retired_h
    retired_e = d_e.get("RETIRED", 0)
    running_e = d_e.get("RUNNING", 0)
    exp_denominator = d_e["_total"] - retired_e

    lines = [
        "# Chain depth",
        "",
        "| Stage | Depth | Denominator |",
        "|---|---|---|",
        f"| Problems ruled | {ruled_p} | {d_p['_total']} |",
        f"| Hypotheses prioritized | {prioritized_h} | {hyp_denominator} |",
        f"| Hypotheses retired | {retired_h} | {d_h['_total']} |",
        f"| Experiments running | {running_e} | {exp_denominator} |",
        f"| Experiments retired | {retired_e} | {d_e['_total']} |",
        "",
    ]
    if FLOORS:
        for stage, floor in FLOORS.items():
            lines.append(f"Floor: {stage} at {floor}.")
    else:
        lines.append(
            "No floors set. Reported with denominators only until a week of readings "
            "classifies each queue as a stock or a pass-through (the BUILD_FLOOR lesson: "
            "a floor over a pass-through is unreachable by construction)."
        )
    return "\n".join(lines) + "\n", 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="print only (default behavior)")
    ap.parse_args(argv)
    text, code = render()
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
