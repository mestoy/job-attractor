#!/usr/bin/env python3
"""Wall-clock section timer for a take-home work sample (honest time reporting against a stated cap).

Usage:
  python3 scripts/sample_timer.py start "Part 1"    # start a section (auto-stops a running one)
  python3 scripts/sample_timer.py stop              # stop the running section
  python3 scripts/sample_timer.py status            # running section, its elapsed, total vs cap
  python3 scripts/sample_timer.py report             # per-section totals + stint counts vs budgets
  python3 scripts/sample_timer.py log                # every stint: date, start-end, duration, section

A section can be worked in any number of stints across sessions and days; each
start adds to its total. The log file persists on disk between sessions.

Many take-home work samples state an honesty cap ("finish within N hours") and ask you to report
your actual time. This script measures it instead of you estimating it after the fact.

Events are appended to kit_config.WORK_SAMPLE_DIR / timelog.jsonl (override the whole path with
--log). Timestamps are recorded in UTC and displayed in local time.

Section budgets and the overall cap are generic defaults — edit CAP_MIN and BUDGETS_MIN below (or
pass a different --log per sample and keep a separate copy) to match the sample you're actually
doing.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
try:
    from kit_config import WORK_SAMPLE_DIR  # noqa: E402
except ImportError:
    WORK_SAMPLE_DIR = "documents/applications/work-sample"

DEFAULT_LOG = REPO / WORK_SAMPLE_DIR / "timelog.jsonl"

CAP_MIN = 240
BUDGETS_MIN = {
    "Part 1": 45,
    "Part 2": 60,
    "Part 3": 45,
    "Part 4": 30,
}


def read_events(log: Path):
    if not log.exists():
        return []
    events = []
    for line in log.read_text().splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def append_event(log: Path, event: str, section=None):
    log.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event}
    if section:
        row["section"] = section
    with log.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def intervals(events):
    """Yield (section, start_dt, end_dt_or_None) from the event stream."""
    open_section = None
    open_start = None
    for e in events:
        ts = datetime.fromisoformat(e["ts"])
        if e["event"] == "start":
            if open_section is not None:
                yield (open_section, open_start, ts)
            open_section, open_start = e["section"], ts
        elif e["event"] == "stop" and open_section is not None:
            yield (open_section, open_start, ts)
            open_section = open_start = None
    if open_section is not None:
        yield (open_section, open_start, None)


def totals(events, now):
    per_section = {}
    running = None
    for section, start, end in intervals(events):
        effective_end = end or now
        per_section[section] = per_section.get(section, 0.0) + (effective_end - start).total_seconds()
        if end is None:
            running = (section, start)
    return per_section, running


def fmt_min(seconds: float) -> str:
    m = seconds / 60
    if m >= 60:
        return f"{int(m // 60)}h {int(m % 60):02d}m"
    return f"{m:.0f}m"


def local(dt: datetime) -> str:
    return dt.astimezone().strftime("%H:%M:%S")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["start", "stop", "status", "report", "log"])
    p.add_argument("section", nargs="?", help="section name, required for start (e.g. \"Part 1\")")
    p.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    events = read_events(args.log)
    per_section, running = totals(events, now)
    total = sum(per_section.values())

    if args.command == "start":
        if not args.section:
            sys.exit("start needs a section name, e.g.: sample_timer.py start \"Part 1\"")
        if running:
            append_event(args.log, "stop", None)
            print(f"⏹  stopped {running[0]} at {local(now)} ({fmt_min((now - running[1]).total_seconds())} this stint)")
        append_event(args.log, "start", args.section)
        prior = per_section.get(args.section, 0.0)
        note = f" (prior time on it: {fmt_min(prior)})" if prior else ""
        print(f"▶️  {args.section} started at {local(now)}{note}")

    elif args.command == "stop":
        if not running:
            sys.exit("nothing is running")
        append_event(args.log, "stop", None)
        stint = (now - running[1]).total_seconds()
        print(f"⏹  {running[0]} stopped at {local(now)} · this stint {fmt_min(stint)} · section total {fmt_min(per_section[running[0]])}")
        print(f"    overall: {fmt_min(sum(totals(read_events(args.log), now)[0].values()))} of the {CAP_MIN // 60}h cap")

    elif args.command == "status":
        if running:
            stint = (now - running[1]).total_seconds()
            print(f"▶️  RUNNING: {running[0]} · started {local(running[1])} · this stint {fmt_min(stint)} · section total {fmt_min(per_section[running[0]])}")
        else:
            print("⏸  nothing running")
        print(f"    overall: {fmt_min(total)} used · {fmt_min(max(CAP_MIN * 60 - total, 0))} left of the {CAP_MIN // 60}h cap")

    elif args.command == "log":
        rows = list(intervals(events))
        if not rows:
            sys.exit("no time logged yet")
        for section, start, end in rows:
            eff = end or now
            when = start.astimezone().strftime("%a %m-%d %H:%M")
            until = end.astimezone().strftime("%H:%M") if end else "now ▶️"
            print(f"{when}–{until:<7} {fmt_min((eff - start).total_seconds()):>7}  {section}")

    else:  # report
        if not per_section:
            sys.exit("no time logged yet")
        stints = {}
        for section, _start, _end in intervals(events):
            stints[section] = stints.get(section, 0) + 1
        print(f"{'section':<12} {'spent':>8} {'stints':>7} {'budget':>8}  vs budget")
        print("─" * 52)
        for section in sorted(per_section, key=lambda s: (s not in BUDGETS_MIN, s)):
            spent = per_section[section]
            budget = BUDGETS_MIN.get(section)
            if budget is not None:
                delta = spent - budget * 60
                sign = "+" if delta > 0 else "-"
                vs = f"{sign}{fmt_min(abs(delta))}"
                print(f"{section:<12} {fmt_min(spent):>8} {stints[section]:>7} {budget:>6}m   {vs}")
            else:
                print(f"{section:<12} {fmt_min(spent):>8} {stints[section]:>7} {'—':>8}")
        print("─" * 52)
        flag = "  ⚠️ OVER CAP" if total > CAP_MIN * 60 else ""
        print(f"{'TOTAL':<12} {fmt_min(total):>8} {CAP_MIN // 60:>5}h 0m{flag}")
        if running:
            print(f"(includes the running {running[0]} stint, started {local(running[1])})")


if __name__ == "__main__":
    main()
