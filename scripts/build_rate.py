#!/usr/bin/env python3
"""Two separate build-throughput metrics, deliberately NOT conflated.

This module answers two different questions that get collapsed into one
number when reported carelessly, producing inverted results:

  1. notes_built()          -- how many outreach notes were actually BUILT
                               (staged) on a given day. Source: the send log.
  2. transitions_from_git() -- how many cards ENTERED the BUILD queue
                               (queue inflow). Source: git history of the
                               state cards.

They measure different stages and will not agree. Report them separately.

Why not the obvious sources
---------------------------
* The decision ledger cannot answer either question. Keyword matching over
  ledger prose treats "BUILD gate", "build the send" and "BUILD floor" as
  verdicts, so a company can read as ever-ruled-BUILD against a BUILD queue
  that holds a couple of cards and empties daily. Ledger prose is never
  counted here.
* Card headers cannot answer inflow either. A card header records CURRENT
  STATE, not when the card entered that state; only a handful of cards carry
  a dated "ruled BUILD <date>" at all.
* documents/state/ is git-tracked and `git log --follow` works per card file.
  That history is the only uncontaminated record of when a card entered BUILD.

KNOWN LIMITATION -- DAY GRANULARITY ONLY
----------------------------------------
If your install commits documents/state/ in bulk backup snapshots with
generic messages, many cards move inside a single snapshot commit, and the
snapshot is written some time after the ruling it records. A transition is
therefore attributable to a DATE, never to a moment, and never to an ordering
within a date. Any use of these transitions at sub-day resolution is invalid.
Every method string returned by this module repeats that limitation.

REQUIRES GIT HISTORY OF documents/state/. A fresh install with no commit
history over its cards yet will see every card as `cards_never_build` and an
empty `transitions` list, not an error -- there is nothing dishonest about
that report, but it means transitions_from_git has nothing useful to say
until enough history accumulates. notes_built has no such dependency; it
reads documents/send-log.jsonl directly and works from day one.

stdlib only; Python 3.9 compatible.
"""

import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time

SEND_LOG = os.path.join("documents", "send-log.jsonl")
CARD_GLOB = os.path.join("documents", "state", "*-card-*.md")

# A note counts as built if a row exists for it at all. These statuses mean the
# note reached a real recipient, so a sibling "drafted" row for the same company
# is the stale pre-send duplicate, not a second note.
DELIVERED_STATUSES = frozenset(["sent", "replied"])

# Uppercase BUILD as a standalone token. Case matters: it is what separates the
# verdict token from prose like "card-build" or "build the send".
_BUILD_TOKEN = re.compile(r"(?<![A-Za-z])BUILD(?![A-Za-z])")

# BUILD followed by one of these is a noun phrase ABOUT the build stage, not a
# verdict that this card is in it. "BUILD gate" / "BUILD floor" are exactly the
# kind of ledger contamination that inflates a naive keyword count.
_NON_VERDICT_NEXT = frozenset([
    "gate", "gates", "floor", "floors", "row", "rows", "queue", "queues",
    "candidate", "candidates", "checklist", "checklists", "rule", "rules",
    "bug", "bugs", "draft", "drafts", "step", "steps", "phase", "phases",
    "mode", "path", "criteria", "threshold", "list", "lane", "slot",
])

# A negation before BUILD inverts it: "no BUILD row", "not BUILD", "never BUILD".
_NEGATION_PREV = frozenset(["no", "not", "never", "without", "non", "pre", "un"])

_WORD = re.compile(r"[A-Za-z]+")

# Advisory only: the date the header PROSE claims the ruling happened. It is not
# used to count anything -- the commit date is the measurement -- but the gap
# between the two is the commit lag, and reporting it keeps the day-granularity
# caveat concrete instead of abstract. (Example: a card header says "ruled
# BUILD 2026-09-10" but the commit carrying that header is dated 2026-09-11 --
# the commit lag on that card is 1 day.)
_STATED_RULING = re.compile(r"ruled(?:\s+BUILD)?\s+(\d{4}-\d{2}-\d{2})")

# A header that has reached SENT. Used only to quantify what this metric CANNOT
# see: a card that went straight from LIVE to SENT inside one backup snapshot
# never shows a BUILD header, so its BUILD entry is unobservable here.
_SENT_MARKER = re.compile(r"(?<![A-Za-z])SENT(?![A-Za-z])")


def _run(args, cwd, text=True):
    return subprocess.run(
        args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text
    )


# --------------------------------------------------------------------------
# BUILD verdict detection
# --------------------------------------------------------------------------

def is_build_verdict(line):
    """True if a card's FIRST LINE asserts the card is/was in BUILD.

    Accepts verdict forms observed in card corpora built on this kit:
        "STATUS: BUILD (...)", "STATUS: 🟢 BUILD", "· BUILD (Owner, ...)",
        "ruled BUILD 2026-09-10", "was BUILD"
    Rejects, by construction:
        lowercase prose ("Dedup-at-card-build bug draft", "build the send"),
        modified noun phrases ("BUILD gate", "BUILD floor", "BUILD candidate"),
        and negated mentions ("no BUILD row", "not BUILD").
    """
    if not line:
        return False
    for m in _BUILD_TOKEN.finditer(line):
        nxt = _WORD.search(line[m.end():m.end() + 40])
        if nxt is not None and nxt.group(0).lower() in _NON_VERDICT_NEXT:
            continue
        prev_words = _WORD.findall(line[max(0, m.start() - 40):m.start()])
        if prev_words and prev_words[-1].lower() in _NEGATION_PREV:
            continue
        return True
    return False


# --------------------------------------------------------------------------
# Metric 1 -- notes actually built (send log)
# --------------------------------------------------------------------------

def _load_send_log(repo):
    path = os.path.join(repo, SEND_LOG)
    rows = []
    malformed = 0
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                malformed += 1
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                malformed += 1
    return rows, malformed


def _duplicate_draft_keys(rows):
    """Indices of 'drafted' rows whose company also has a delivered row.

    A drafted row that sits beside its own later 'sent' row for the same
    company, same recipient, same subject, is the stale pre-send duplicate.
    Counting both double-counts one note.
    """
    delivered = set()
    for row in rows:
        company = (row.get("company") or "").strip().lower()
        if company and row.get("status") in DELIVERED_STATUSES:
            delivered.add(company)
    dups = []
    for idx, row in enumerate(rows):
        company = (row.get("company") or "").strip().lower()
        if row.get("status") == "drafted" and company and company in delivered:
            dups.append(idx)
    return dups


def notes_built(repo, start, end):
    """Notes actually built (staged), counted from documents/send-log.jsonl.

    Every staged note writes a row, so rows-by-`date` is the count. The only
    correction applied is the duplicate-draft exclusion above.

    `start` and `end` are inclusive 'YYYY-MM-DD' strings.

    Returns a dict carrying BOTH the raw and the deduplicated counts, so the
    arithmetic stays inspectable and neither number has to be taken on trust.
    """
    rows, malformed = _load_send_log(repo)
    dup_idx = set(_duplicate_draft_keys(rows))

    raw_by_day = {}
    by_day = {}
    excluded = []
    for idx, row in enumerate(rows):
        day = row.get("date")
        if not day or day < start or day > end:
            continue
        raw_by_day[day] = raw_by_day.get(day, 0) + 1
        if idx in dup_idx:
            excluded.append({
                "date": day,
                "company": row.get("company"),
                "status": row.get("status"),
                "reason": "drafted row duplicating a delivered row for the same company",
            })
            continue
        by_day[day] = by_day.get(day, 0) + 1

    span_days = _inclusive_days(start, end)
    total = sum(by_day.values())
    return {
        "metric": "notes_built",
        "start": start,
        "end": end,
        "window_days": span_days,
        "by_day": by_day,
        "raw_by_day": raw_by_day,
        "total": total,
        "raw_total": sum(raw_by_day.values()),
        "excluded_duplicate_drafts": excluded,
        "excluded_count": len(excluded),
        "active_days": len(by_day),
        "per_day": round(total / span_days, 2) if span_days else 0.0,
        "per_active_day": (
            round(total / len(by_day), 2) if by_day else 0.0
        ),
        "malformed_rows_skipped": malformed,
        "method": (
            "Counted one row per staged note in documents/send-log.jsonl, "
            "bucketed by the row's `date` field. Excluded `drafted` rows whose "
            "company also has a row with status in {sent, replied} (stale "
            "pre-send duplicates). Ledger prose is NOT consulted. Granularity: "
            "day. This is notes BUILT, not cards entering the BUILD queue -- "
            "do not conflate it with transitions_from_git."
        ),
    }


# --------------------------------------------------------------------------
# Metric 2 -- cards entering BUILD (git history)
# --------------------------------------------------------------------------

class _BlobReader(object):
    """One long-lived `git cat-file --batch` instead of a `git show` per blob.

    A card corpus times hundreds of commits is enough subprocess churn to
    matter; batching keeps a full sweep in a couple of seconds.
    """

    def __init__(self, repo):
        self.proc = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.cache = {}

    def first_line(self, sha, path):
        key = sha + ":" + path
        if key in self.cache:
            return self.cache[key]
        self.proc.stdin.write((key + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().decode("utf-8", "replace").strip()
        parts = header.split()
        if len(parts) < 3 or parts[1] == "missing":
            self.cache[key] = None
            return None
        size = int(parts[2])
        payload = self.proc.stdout.read(size)
        self.proc.stdout.read(1)  # trailing newline
        text = payload.decode("utf-8", "replace")
        line = text.split("\n", 1)[0]
        self.cache[key] = line
        return line

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.stdout.close()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def _card_history(repo, path):
    """[(sha, 'YYYY-MM-DD', path_at_that_commit)] oldest-first for one card.

    The third element matters. `git log --follow` walks through renames, but the
    blob at an older commit lives under the card's OLD path -- asking
    `git cat-file` for the CURRENT path at that commit returns "missing" and the
    card's pre-rename history silently vanishes, dating its BUILD entry to the
    rename instead of to the ruling. So `--name-only` is parsed alongside each
    commit and the path recorded there is the one used to fetch the blob.
    """
    res = _run(
        ["git", "log", "--follow", "--format=%x01%H %ad", "--date=short",
         "--name-only", "--", path],
        cwd=repo,
    )
    if res.returncode != 0:
        return None
    out = []
    for chunk in res.stdout.split("\x01"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        lines = [ln for ln in chunk.split("\n") if ln.strip()]
        head = lines[0].split()
        if len(head) < 2:
            continue
        sha, day = head[0], head[1]
        # --name-only under --follow lists the path as of this commit (the new
        # name at a rename commit, the old name before it).
        at_path = lines[1] if len(lines) > 1 else path
        out.append((sha, day, at_path))
    out.reverse()  # git log is newest-first
    return out


def transitions_from_git(repo, since, until=None, time_budget_s=180.0,
                         card_glob=CARD_GLOB):
    """Cards ENTERING BUILD -- queue inflow -- from git history.

    For each documents/state/*-card-*.md, walk its commits oldest-first and
    take the FIRST commit whose version of the file's first line carries a
    BUILD verdict (see is_build_verdict). That commit's author date is the
    transition date.

    `since` and `until` are inclusive 'YYYY-MM-DD' bounds on the transition
    date (`until` defaults to today). Cards whose first BUILD commit falls
    outside the window are reported separately as `before_window` /
    `after_window` rather than dropped, so nothing disappears silently, and the
    denominator here matches the one notes_built uses.

    If `time_budget_s` is exhausted the sweep stops and the unprocessed cards
    are returned in `skipped` with a reason. Results are never truncated
    silently.

    An install with no card history yet (a fresh checkout, or one that has
    never committed documents/state/) returns an honest empty report --
    cards_total may be 0, or every card may land in cards_never_build -- never
    a crash and never a fabricated count.
    """
    started = time.time()
    end = until or datetime.date.today().isoformat()
    paths = sorted(glob.glob(os.path.join(repo, card_glob)))
    rel_paths = [os.path.relpath(p, repo) for p in paths]

    reader = _BlobReader(repo)
    by_day = {}
    transitions = []
    before_window = []
    after_window = []
    never_build = 0
    sent_without_observed_build = 0
    skipped = []
    no_history = []
    try:
        for i, rel in enumerate(rel_paths):
            if time.time() - started > time_budget_s:
                for remaining in rel_paths[i:]:
                    skipped.append({
                        "card": remaining,
                        "reason": "time budget exhausted before this card was walked",
                    })
                break
            history = _card_history(repo, rel)
            if history is None:
                no_history.append(rel)
                continue
            hit = None
            ever_sent = False
            for sha, day, at_path in history:
                line = reader.first_line(sha, at_path)
                if line is None:
                    continue
                if _SENT_MARKER.search(line):
                    ever_sent = True
                if hit is None and is_build_verdict(line):
                    hit = (sha, day, line)
                    if ever_sent:
                        break
            if hit is None and ever_sent:
                sent_without_observed_build += 1
            if hit is None:
                never_build += 1
                continue
            sha, day, line = hit
            stated = _STATED_RULING.search(line)
            stated_date = stated.group(1) if stated else None
            record = {
                "card": rel, "date": day, "commit": sha, "first_line": line,
                "stated_ruling_date": stated_date,
                "commit_lag_days": (
                    _inclusive_days(stated_date, day) - 1
                    if stated_date and stated_date <= day else None
                ),
            }
            if day < since:
                before_window.append(record)
                continue
            if day > end:
                after_window.append(record)
                continue
            transitions.append(record)
            by_day[day] = by_day.get(day, 0) + 1
    finally:
        reader.close()

    span_days = _inclusive_days(since, end)
    total = len(transitions)
    return {
        "metric": "transitions_from_git",
        "since": since,
        "as_of": end,
        "window_days": span_days,
        "by_day": by_day,
        "total": total,
        "transitions": sorted(transitions, key=lambda r: (r["date"], r["card"])),
        "before_window_count": len(before_window),
        "before_window": sorted(before_window, key=lambda r: r["date"]),
        "after_window_count": len(after_window),
        "after_window": sorted(after_window, key=lambda r: r["date"]),
        "cards_examined": len(rel_paths) - len(skipped),
        "cards_total": len(rel_paths),
        "cards_never_build": never_build,
        "sent_without_observed_build": sent_without_observed_build,
        "coverage_note": (
            "%d card(s) reached a SENT header without ever showing a BUILD "
            "header in any commit. Those cards passed through BUILD but did so "
            "inside a single backup snapshot, so their entry is UNOBSERVABLE "
            "here. This metric is therefore a FLOOR on queue inflow, not a "
            "complete count." % sent_without_observed_build
        ),
        "cards_without_history": no_history,
        "skipped": skipped,
        "skipped_count": len(skipped),
        "per_day": round(total / span_days, 2) if span_days else 0.0,
        "elapsed_s": round(time.time() - started, 2),
        "method": (
            "For each documents/state/*-card-*.md, walked `git log --follow "
            "--format='%H %ad' --date=short` oldest-first and took the first "
            "commit whose `git cat-file` version of the file's FIRST LINE "
            "carries a BUILD verdict. Verdict detection requires the uppercase "
            "token BUILD, rejects modified noun phrases (BUILD gate, BUILD "
            "floor, BUILD row, BUILD candidate) and negated mentions (no BUILD "
            "row), and never reads the decision ledger. GRANULARITY: DAY ONLY "
            "-- commits touching documents/state/ are bulk backup snapshots "
            "with generic messages, so a transition is attributable to a DATE, "
            "not to a moment and not to an order within that date. This is "
            "queue INFLOW, not notes built -- do not conflate it with "
            "notes_built."
        ),
    }


# --------------------------------------------------------------------------
# Combined report
# --------------------------------------------------------------------------

def _inclusive_days(start, end):
    s = datetime.date(*[int(x) for x in start.split("-")])
    e = datetime.date(*[int(x) for x in end.split("-")])
    return (e - s).days + 1


def _latest_send_date(repo):
    rows, _ = _load_send_log(repo)
    days = [r.get("date") for r in rows if r.get("date")]
    return max(days) if days else datetime.date.today().isoformat()


def rate_report(repo, window_days, anchor=None, time_budget_s=180.0):
    """Both rates, side by side, each labeled with its own source and method.

    The two numbers measure DIFFERENT stages and are expected to differ. They
    are returned under separate keys and are never summed or averaged.

    The notes window is anchored on the most recent date present in the send
    log (or `anchor`, if given) so that a partially elapsed today does not
    depress the rate; `anchor` is echoed back in the result.
    """
    if window_days < 1:
        raise ValueError("window_days must be >= 1")
    end = anchor or _latest_send_date(repo)
    e = datetime.date(*[int(x) for x in end.split("-")])
    start = (e - datetime.timedelta(days=window_days - 1)).isoformat()

    notes = notes_built(repo, start, end)
    # Same window bounds for both metrics: two rates with different
    # denominators are the sort of near-miss that gets read as one number.
    trans = transitions_from_git(repo, start, until=end,
                                 time_budget_s=time_budget_s)

    return {
        "repo": os.path.abspath(repo),
        "window_days": window_days,
        "window_start": start,
        "window_end": end,
        "anchor_note": (
            "Window anchored on the most recent date in the send log (%s), not "
            "on today, so a partially elapsed day does not depress the rate."
            % end
        ),
        "notes_built": notes,
        "transitions_from_git": trans,
        "conflation_warning": (
            "notes_built and transitions_from_git measure different stages "
            "(notes staged vs. cards entering the BUILD queue). They are "
            "reported separately on purpose. Do not sum, average, or present "
            "either as the other."
        ),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--anchor", default=None,
                    help="YYYY-MM-DD end of window; defaults to the send log's latest date")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--time-budget", type=float, default=180.0)
    args = ap.parse_args(argv)

    rep = rate_report(args.repo, args.window_days, anchor=args.anchor,
                      time_budget_s=args.time_budget)
    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True))
        return 0

    n = rep["notes_built"]
    t = rep["transitions_from_git"]
    print("window: %s .. %s (%d days)" % (rep["window_start"], rep["window_end"],
                                          rep["window_days"]))
    print("")
    print("1. NOTES BUILT (send log)")
    print("   total %d over %d days = %.2f/day (%.2f per active day, %d active days)"
          % (n["total"], n["window_days"], n["per_day"], n["per_active_day"],
             n["active_days"]))
    print("   raw rows %d, duplicate drafts excluded %d"
          % (n["raw_total"], n["excluded_count"]))
    for day in sorted(n["raw_by_day"]):
        print("     %s  raw %2d  counted %2d" % (day, n["raw_by_day"][day],
                                                 n["by_day"].get(day, 0)))
    print("   method: %s" % n["method"])
    print("")
    print("2. CARDS ENTERING BUILD (git history of documents/state)")
    print("   total %d over %d days = %.2f/day"
          % (t["total"], t["window_days"], t["per_day"]))
    print("   cards examined %d of %d; never BUILD %d; entered before window %d; skipped %d"
          % (t["cards_examined"], t["cards_total"], t["cards_never_build"],
             t["before_window_count"], t["skipped_count"]))
    for day in sorted(t["by_day"]):
        print("     %s  %2d" % (day, t["by_day"][day]))
    for row in t["skipped"]:
        print("     SKIPPED %s: %s" % (row["card"], row["reason"]))
    print("   method: %s" % t["method"])
    print("")
    print(rep["conflation_warning"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
