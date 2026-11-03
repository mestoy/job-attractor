#!/usr/bin/env python3
"""check_inbound.py — intake pass over the raw message archive: what's genuinely unanswered.

WHY THIS EXISTS. `pair_brief.open_inbound()` only ever reads `documents/correspondence-log.md`,
which is written by hand. Nothing enters it unless a human types it in, so a message that arrived
and was never logged reads as ANSWERED — the dangerous direction, because "what do I still owe an
answer to" is the row that decides whether the day opens on an owed reply.

`parse_messages.py` already reads `messages.csv` (the complete inbox record LinkedIn ships) and
already resolves the account owner. This is the intake pass built on top of it: report anyone the
raw archive shows wrote in without a LATER reply from the owner, for a human to triage.

RULED MECHANISM (build to this, do not invent a different one):
  · Dismissal is a small command, own file. `--close "<Person>" --reason "<why>"` appends to a
    NEW append-only store, `documents/state/inbound-intake-closed.jsonl`. REJECTED: an
    `INTAKE: closed` marker written inside correspondence-log.md — that file can be a send-gate
    store elsewhere in a pipeline, and a marker landing there risks silently granting an
    unrelated build-gate exemption to whoever it names.
  · The briefing row is AGE-GATED, not permanent. It renders only when the newest unanswered
    inbound is older than ~2 days, so the row stays a real signal instead of becoming wallpaper.
    Deliberately SHORTER than, and independent of, `pair_brief.INBOUND_OPEN_DAYS` (14), which
    governs a different, already-logged signal — the two windows are not the same knob.
  · REJECTED: an emission rule keyed on an "unread thread count" integer — nothing in this
    pipeline writes that number, so the row would be permanently red from the day it shipped.

⛔ NEVER WRITES A CORRESPONDENCE ENTRY, and never will. This script only ever reports and, on
`--close`, records that a human looked and decided nothing is owed — it does not decide that
itself.

Usage:
  scripts/check_inbound.py                                 # report unanswered inbound
  scripts/check_inbound.py --close "<Person>" --reason "<why nothing is owed>"
  scripts/check_inbound.py --export <path>                  # explicit messages.csv, else newest export
  scripts/check_inbound.py --age-days N                     # override the 2-day default for --aged

Exit: 0 = ok (report may be empty) · 2 = no export/messages.csv found · 3 = usage
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
INTAKE_STORE = os.path.join(REPO, "documents", "state", "inbound-intake-closed.jsonl")

sys.path.insert(0, HERE)

DEFAULT_AGE_DAYS = 2  # "~2 days" — deliberately separate from pair_brief's 14-day window


def _intake_store_path(repo=None):
    """Resolved at CALL time: REPO is computed at import, so a test harness that redirects
    CLAUDE_PROJECT_DIR after import must not read the frozen module constant."""
    r = repo or os.environ.get("CLAUDE_PROJECT_DIR") or REPO
    return os.path.join(r, "documents", "state", "inbound-intake-closed.jsonl")


def closed_names(repo=None):
    """{normalized name} for everyone dismissed via `--close`. Empty on a fresh install."""
    import pair_brief
    path = _intake_store_path(repo)
    out = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue          # a corrupt line must not blind the whole store
                name = row.get("name")
                if name:
                    out.add(pair_brief._norm_name(name))
    except OSError:
        return set()
    return out


def close(name, reason, repo=None, now=None):
    """Append a dismissal row. APPEND-ONLY, never rewrites or removes a prior row — the same
    durability discipline as every other state store in this repo (a correction is a NEW row,
    not an edit)."""
    if not (name or "").strip():
        raise ValueError("close() needs a name")
    if not (reason or "").strip():
        raise ValueError("close() needs a --reason — an unreasoned dismissal is a silent one")
    path = _intake_store_path(repo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = {
        "name": name.strip(),
        "reason": reason.strip(),
        "closed_at": (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(),
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _repo_scoped_messages_csv(repo):
    """The newest messages.csv under `{repo}/documents/linkedin-exports/` ONLY, or None.

    ⛔ DELIBERATELY NOT `parse_network.find_export()`'s full resolution chain. That function's
    repo-scoped glob is safe, but it then falls back to the MACHINE's own `~/Downloads` and
    `~/Desktop` — unscoped by any `repo` argument, because its own `REPO` is a module-level
    constant frozen at import. A caller here always passes an explicit `repo` (a sandbox in
    tests, the real repo in production), and that fallback would silently widen a sandboxed
    call out to the real machine's home directory. Scoped strictly to the given repo, so a test
    with no export planted in it gets exactly what it asked for: nothing.
    """
    import glob
    base = os.path.join(repo, "documents", "linkedin-exports")
    for c in sorted(glob.glob(os.path.join(base, "**", "messages.csv"), recursive=True)):
        return c
    return None


def _find_messages_safe(repo=None, export=None):
    """(path, rows) for the messages archive, never raising, never reaching outside `repo` when
    one is given. `export` (an explicit path) always wins when supplied — same as
    `parse_messages.find_messages`'s own `--export` contract."""
    import parse_messages
    try:
        if export:
            return parse_messages.find_messages(export)
        if repo:
            path = _repo_scoped_messages_csv(repo)
            if not path:
                return None, []
            return parse_messages.find_messages(path)
        # No repo, no explicit export: the real production path, free to use
        # parse_network's full resolution (Downloads/Desktop fallback included).
        return parse_messages.find_messages(None)
    except Exception:
        return None, []


def _days_since(iso_date, today=None):
    try:
        then = datetime.date.fromisoformat(iso_date)
    except (ValueError, TypeError):
        return None
    ref = datetime.date.fromisoformat(today) if today else datetime.date.today()
    return (ref - then).days


def unanswered(repo=None, export=None):
    """Every correspondent the RAW ARCHIVE shows wrote in with no later reply from the owner,
    not already closed via `--close` or via an existing correspondence_log/outreach_log
    completion signal. Returns [] (never raises) when no export/messages.csv is found — same
    fail-open shape as every other degraded-store path in this pipeline; report_only(), not this
    function, is what should announce degradation to a human.

    Shape: [{"name", "last_inbound", "days_open"}], newest-first.
    """
    import pair_brief
    import parse_messages
    _path, rows = _find_messages_safe(repo=repo, export=export)
    if not rows:
        return []
    counts, _owner = parse_messages.tally(rows)
    closed_corr = pair_brief.closed_threads(repo)
    closed_intake = closed_names(repo)
    out = []
    for name, m in counts.items():
        li = m.get("last_inbound")
        if not li:
            continue                                   # they never actually wrote
        lo = m.get("last_outbound")
        if lo and lo >= li:
            continue                                   # a reply exists AFTER their last message
        key = pair_brief._norm_name(name)
        if not key or key in closed_corr or key in closed_intake:
            continue
        out.append({"name": name, "last_inbound": li, "days_open": _days_since(li) or 0})
    out.sort(key=lambda r: r["last_inbound"], reverse=True)
    return out


def unanswered_aged(repo=None, today=None, age_days=DEFAULT_AGE_DAYS, export=None):
    """The BRIEFING-ROW view: `unanswered()`, filtered to the age gate. This is what a
    session-start briefing should call, never the unfiltered list — a same-day inbound is not
    yet urgent, it is a normal inbox."""
    rows = unanswered(repo=repo, export=export)
    keep = []
    for r in rows:
        d = _days_since(r["last_inbound"], today)
        if d is not None and d >= age_days:
            keep.append(r)
    return keep


def main():
    args = sys.argv[1:]
    if "--close" in args:
        i = args.index("--close")
        if i + 1 >= len(args):
            print("usage: check_inbound.py --close \"<Person>\" --reason \"<why>\"")
            return 3
        name = args[i + 1]
        reason = ""
        if "--reason" in args:
            j = args.index("--reason")
            if j + 1 < len(args):
                reason = args[j + 1]
        try:
            row = close(name, reason)
        except ValueError as e:
            print(f"❌ {e}")
            return 3
        print(f"✅ closed intake for {row['name']!r}: {row['reason']}")
        return 0

    export = None
    if "--export" in args:
        i = args.index("--export")
        if i + 1 >= len(args):
            print("usage: check_inbound.py --export <path>")
            return 3
        export = args[i + 1]

    age_days = DEFAULT_AGE_DAYS
    if "--age-days" in args:
        i = args.index("--age-days")
        if i + 1 < len(args):
            try:
                age_days = int(args[i + 1])
            except ValueError:
                pass

    rows = unanswered(export=export)
    if not rows:
        # Distinguish "found the archive, genuinely nothing owed" from "could not read the
        # archive at all" — a silent zero here is the failure mode this script exists to catch.
        _path, probe_rows = _find_messages_safe(export=export)
        if not probe_rows:
            print("⚠️  no messages.csv found — cannot report on unanswered inbound at all. "
                  "Treat this as UNKNOWN, never as zero.")
            return 2
        print("✅ no unanswered inbound in the raw archive.")
        return 0

    print(f"{len(rows)} unanswered inbound message(s) in the raw archive:")
    for r in rows:
        aged = " (AGED)" if r["days_open"] >= age_days else ""
        print(f"  · {r['name']} — last wrote {r['last_inbound']}, {r['days_open']}d ago{aged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
