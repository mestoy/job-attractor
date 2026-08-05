#!/usr/bin/env python3
"""check_tripwires.py — are any armed TRIPWIRE dates due or overdue?

WHY THIS EXISTS. A tripwire is a decision you want to make LATER, on evidence you do not have YET:
*"if no recruiter contact by 2026-07-30, the offer was politeness and my read on that hiring manager
downgrades."* It is a dated, conditional re-read of a live thread, and you write one precisely
because you cannot judge the thread today.

In the pipeline this was ported from, EIGHT tripwire mentions existed across four files and NOTHING
read any of them. `check_followups.py` is the closest reader and it opens only `outreach_log.md` and
matches only `FOLLOWUP-DUE:`, so seven of the eight sat in files it never opens and the eighth was
prose it cannot parse. Two were days from firing when this script first ran.

That is the same shape as the standing rule *"a ruling recorded somewhere the code does not read is
not a ruling,"* applied to a DATE. A tripwire that nothing checks is not a tripwire, it is a note.
The whole value is being reminded ON THE DAY, because the day it fires is exactly the day the thread
has gone quiet and nothing else prompts you to re-read it.

WHAT IT DOES NOT DO. It cannot tell whether a tripwire was already handled. There is no resolution
marker in the logs, and inventing a workflow was not in scope, so a fired tripwire keeps reporting
until the line says `CLEARED` or `RESOLVED`. That is deliberate: for a handful of live tripwires,
nagging is cheaper than a silent miss. If your count grows past that, the signal is to give tripwires
a real store, not to widen this heuristic.

Usage:  scripts/check_tripwires.py [--quiet] [--today YYYY-MM-DD]
Exit:   0 = nothing due · 1 = one or more DUE/OVERDUE · 3 = usage error
"""
import csv
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)

# The stores that carry tripwires. Session-state and plan documents are deliberately NOT read: they
# are narrative snapshots that quote tripwires as history, so parsing them would resurrect every
# tripwire ever written and bury the live ones.
#
# KIT PATH NOTE: the changelog ships under docs/ here, not documents/. Missing files read as empty,
# which is the correct behaviour on a fresh install where none of these exist yet.
MD_SOURCES = ("outreach_log.md",
              "documents/correspondence-log.md",
              "docs/JOB-ATTRACTOR-CHANGELOG.md")
CSV_SOURCE = "job_search_tracker.csv"

# ⚠️ THE DATE IS NOT ALWAYS ADJACENT TO THE TOKEN. The obvious rule — parse `TRIPWIRE <date>` — misses
# the most common real spelling, which reads `TRIPWIRE: if no recruiter contact by 2026-07-30`. So:
# find the token, then take the first ISO date at or after it ON THE SAME LINE. Every live spelling
# resolves under that rule; the adjacency rule resolved barely half.
_TRIPWIRE = re.compile(r"TRIPWIRE")
_ISO = re.compile(r"(\d{4}-\d{2}-\d{2})")
_CLEARED = re.compile(r"\b(CLEARED|RESOLVED)\b", re.I)

LOOKBACK = 40          # lines to walk back for a company; the widest observed gap is 34
_STOPWORDS = {"tripwire", "outbound", "inbound", "application", "submitted", "rejection"}


def _read(rel):
    try:
        return open(os.path.join(REPO, rel), encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""


def company_registry():
    """Real company names, from the stores that already hold them.

    Attribution is grounded in a REGISTRY rather than parsed out of prose. Guessing a company from
    surrounding sentences is how a tripwire gets pinned on the wrong thread, and a tripwire pinned on
    the wrong company is worse than one with no company at all: it sends you to re-read a thread that
    was never at risk.
    """
    names = set()
    try:
        with open(os.path.join(REPO, CSV_SOURCE), encoding="utf-8", errors="ignore") as fh:
            for i, cells in enumerate(csv.reader(fh)):
                # Column 1 is `company`. Read it positionally, NOT via DictReader: rows with
                # unquoted commas overflow their header (one live row parsed as 61 fields) and
                # DictReader silently drops the overflow. Column 1 survives that.
                if i and len(cells) > 1 and cells[1].strip():
                    names.add(cells[1].strip())
    except Exception:
        pass
    # ⚠️ READ THE COMPANY CELL, NOT EVERY BOLD SPAN. The first cut of this scraped `**...**` out of
    # green-board.md and built a 414-entry "registry" of arbitrary prose ("Senior Product Manager",
    # "rung 3", the name of an ATS, a whole sentence of rationale). Those then won the longest-match
    # race and pinned live tripwires on things that are not companies. green-board.md holds TWO
    # tables with different column counts, so use the same offset rule as consistency-check [11]:
    # the numbered board leads with a '#' digit cell, the radar table does not.
    for line in _read("documents/green-board.md").splitlines():
        if not line.strip().startswith("|") or line.count("|") < 8:
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 3:
            continue
        off = 1 if cells[1].strip().isdigit() else 0
        co = cells[1 + off].strip().strip("*").strip()
        if co and not co.startswith(("-", ":")) and co.lower() not in _STOPWORDS:
            names.add(co)
    # DURABLE STORE, ADDED ALONGSIDE. The walk above assumes the board holds two layouts; a mature
    # board holds more, and its `cells[1].isdigit()` offset test is defeated by a struck-through row
    # number (`~~1~~` is not a digit), which shifts that row's columns by one. The store is
    # header-driven and immune to both.
    #
    # ⚠️ ADDED, NOT SUBSTITUTED. This registry exists to RECOGNIZE a company named in tripwire prose,
    # so a missing name means a live tripwire silently pins to nothing. Union can only help; a
    # substitution that dropped one spelling would lose a tripwire quietly.
    try:
        import state as _state
        for _rec in _state.from_source("company", "green-board"):
            _name = (_rec.get("payload") or {}).get("name", "").strip()
            if _name and _name.lower() not in _STOPWORDS:
                names.add(_name)
    except Exception:
        pass
    # Longest first so a full legal name wins over the bare first word of it.
    return sorted({n for n in names if len(n) >= 3 and len(n) <= 60}, key=len, reverse=True)


def find_company(lines, idx, registry):
    """Nearest registry company at `idx`, else walking back up to LOOKBACK lines. None if unknown.

    ⚠️ CASE-SENSITIVE, on purpose. Ordinary English words are real company names — one tracked
    company is literally a common verb — and a case-insensitive word match pins a tripwire on it from
    any sentence that happens to use the word. Same hazard class as the lowercase-brand and
    short-name collisions the dedup matchers already had to fix. A missed attribution degrades to
    "company unknown" plus a file:line, which is actionable; a WRONG attribution is not.
    """
    for j in range(idx, max(-1, idx - LOOKBACK) - 1, -1):
        line = lines[j]
        for name in registry:
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", line):
                return name
    return None


def scan(today=None):
    """Pure scan. Returns (due, upcoming, undated, cleared_n). Prints nothing."""
    today = today or date.today()
    registry = company_registry()
    seen, due, upcoming, undated = {}, [], [], []
    cleared_n = 0

    def record(company, dd, src, text):
        # DEDUPE BY (company, date). A single tripwire is routinely written in three places across
        # two files; it is ONE decision. Three rows would read as three obligations.
        key = (company or src, dd)
        if key in seen:
            seen[key]["sources"].append(src)
            return
        row = {"company": company, "date": dd, "sources": [src], "text": text}
        seen[key] = row
        (due if dd and dd <= today else upcoming).append(row)

    for rel in MD_SOURCES:
        text = _read(rel)
        if not text:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = _TRIPWIRE.search(line)
            if not m:
                continue
            if _CLEARED.search(line):
                cleared_n += 1
                continue
            dm = _ISO.search(line, m.end())
            src = f"{rel}:{i + 1}"
            company = find_company(lines, i, registry)
            if not dm:
                undated.append({"company": company, "date": None, "sources": [src],
                                "text": line.strip()})
                continue
            try:
                dd = date.fromisoformat(dm.group(1))
            except ValueError:
                continue
            record(company, dd, src, line.strip())

    # The tracker: company comes from its own column, so no prose attribution is needed.
    try:
        with open(os.path.join(REPO, CSV_SOURCE), encoding="utf-8", errors="ignore") as fh:
            for i, cells in enumerate(csv.reader(fh)):
                if not i or len(cells) < 2:
                    continue
                blob = " ".join(cells)
                m = _TRIPWIRE.search(blob)
                if not m:
                    continue
                if _CLEARED.search(blob):
                    cleared_n += 1
                    continue
                dm = _ISO.search(blob, m.end())
                if not dm:
                    continue
                try:
                    record(cells[1].strip(), date.fromisoformat(dm.group(1)),
                           f"{CSV_SOURCE}:{i + 1}", blob[m.start():m.start() + 160])
                except ValueError:
                    continue
    except Exception:
        pass

    due.sort(key=lambda r: r["date"])
    upcoming.sort(key=lambda r: r["date"])
    return due, upcoming, undated, cleared_n


def main():
    args = sys.argv[1:]
    today = None
    if "--today" in args:
        i = args.index("--today")
        try:
            today = date.fromisoformat(args[i + 1])
        except (IndexError, ValueError):
            print("usage: check_tripwires.py [--today YYYY-MM-DD] [--quiet]")
            return 3
    quiet = "--quiet" in args
    today = today or date.today()
    due, upcoming, undated, cleared_n = scan(today)

    if not quiet:
        if due:
            print(f"🔴 {len(due)} TRIPWIRE(s) DUE/OVERDUE (as of {today}):")
            for r in due:
                who = r["company"] or "company unknown"
                age = (today - r["date"]).days
                when = "due today" if age == 0 else f"{age}d overdue"
                print(f"   • {r['date']}  {who}  ({when})")
                print(f"     {r['text'][:150]}")
                print(f"     source: {', '.join(r['sources'])}")
        else:
            print(f"🟢 no tripwires due (as of {today})")
        if upcoming:
            print(f"   ⏳ {len(upcoming)} upcoming: " + ", ".join(
                f"{r['company'] or 'unknown'} ({r['date']}, in {(r['date'] - today).days}d)"
                for r in upcoming[:8]))
            if len(upcoming) > 8:
                print(f"      (+{len(upcoming) - 8} more)")
        if undated:
            # ADVISORY, never exit-affecting. An undated tripwire cannot be "due", and promoting it
            # would make this check permanently red for a condition no script can clear — the same
            # reasoning that keeps step [18]'s re-parse case out of hard drift.
            print(f"   🟠 {len(undated)} tripwire(s) with NO parseable date — invisible to this check:")
            for r in undated[:6]:
                print(f"      • {r['sources'][0]}  {r['text'][:110]}")
        if cleared_n:
            print(f"   ✅ {cleared_n} tripwire(s) already marked CLEARED/RESOLVED, skipped")
    return 1 if due else 0


if __name__ == "__main__":
    sys.exit(main())
