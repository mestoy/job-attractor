#!/usr/bin/env python3
"""mac_time_rollup.py — minutes per pipeline phase per day, from the passive sampler's files.

WHY. mac_time_sampler.py writes one row a minute, outside the repo. This script turns a
day's rows into one honest summary line and writes it into the repo, so the value stream
map's "PT Mac" column reads from a log instead of from a guess. Gaps are counted, never
attributed: a stretch between two samples longer than GAP_FACTOR intervals (sleep, idle,
agent not running) goes into gap_minutes.

OUTPUT. One JSON line per day appended to documents/state/mac-time-summary.jsonl:
    {"date": "2026-09-10", "minutes": {"find": 0, "screen": 42, "card_and_rule": 18,
     "build_and_send": 6, "other": 9}, "gap_minutes": 25, "samples": 75}
Re-running for the same date replaces that date's line.

Usage:
    python3 scripts/mac_time_rollup.py                     # today
    python3 scripts/mac_time_rollup.py --date 2026-09-10
    python3 scripts/mac_time_rollup.py --data-dir DIR --out FILE   # tests and other Macs
    python3 scripts/mac_time_rollup.py --print             # print, do not write
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)
from phase_map import PHASES  # noqa: E402

INTERVAL = 60
GAP_FACTOR = 3
DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "jobkit")
DEFAULT_OUT = os.path.join(REPO, "documents", "state", "mac-time-summary.jsonl")


def read_rows(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                r["_t"] = datetime.datetime.fromisoformat(r["ts"])
                rows.append(r)
            except Exception:
                continue
    rows.sort(key=lambda r: r["_t"])
    return rows


def rollup(rows, interval=INTERVAL, gap_factor=GAP_FACTOR):
    """Each sample is credited `interval` seconds to its phase; a longer stretch to the next
    sample is a gap. The last sample of the day gets one interval."""
    minutes = {p: 0.0 for p in PHASES}
    gap = 0.0
    for i, r in enumerate(rows):
        phase = r.get("phase") if r.get("phase") in PHASES else "other"
        if i + 1 < len(rows):
            delta = (rows[i + 1]["_t"] - r["_t"]).total_seconds()
        else:
            delta = interval
        if delta <= interval * gap_factor:
            minutes[phase] += min(delta, interval * gap_factor) / 60
        else:
            minutes[phase] += interval / 60
            gap += (delta - interval) / 60
    return {p: round(v) for p, v in minutes.items()}, round(gap), len(rows)


def summarize(date, data_dir):
    rows = read_rows(os.path.join(data_dir, f"mac-time-{date}.jsonl"))
    minutes, gap, n = rollup(rows)
    return {"date": date, "minutes": minutes, "gap_minutes": gap, "samples": n}


def write_summary(summary, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    kept = []
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            for line in f:
                try:
                    if json.loads(line).get("date") != summary["date"]:
                        kept.append(line.rstrip("\n"))
                except Exception:
                    continue
    kept.append(json.dumps(summary))
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(kept) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--print", action="store_true", dest="only_print")
    a = ap.parse_args(argv)
    s = summarize(a.date, a.data_dir)
    print(json.dumps(s))
    if not a.only_print:
        write_summary(s, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
