#!/usr/bin/env python3
"""seat_liveness.py — passive fleet stamps, from his retro beat 2 (2026-09-13).

WHY THIS EXISTS
----------------
The orchestrator session (ba388951) died silently at 14:36 ET. Nothing on disk said which
session held which seat, or when a seat last did anything. Finding out took ps, socket mtimes,
and a ledger tail, by hand. See documents/plan-seat-liveness-2026-09-13.md.

This script is the passive, always-on stamp: every wired hook event overwrites one row in
documents/state/seat-liveness.json keyed by session id. `report` reads that file and flags a
seat stale per the defaults the owner approved 2026-09-13: 20 minutes quiet for a seat holding a
role, 60 for an unassigned one. `claim` and `assign` both write the same file; assign wins on a
conflicting role for the same session (last write wins, and assign is meant to be the
orchestrator's correction over a self-claim).

⛔ OBSERVATION ONLY. `--hook <event>` always exits 0, even on a totally unreadable payload or a
corrupt state file — a hook that can block a session is the exact failure class this plan
guards against re-introducing (see check_pair.py's own stop_hook_active guard).

Usage:
    scripts/seat_liveness.py --hook <event>      # stdin: hook payload JSON, always exits 0
    scripts/seat_liveness.py claim <role>        # this session (or newest match) claims a role
    scripts/seat_liveness.py assign <session-prefix> <role>   # orchestrator assigns; wins
    scripts/seat_liveness.py report [--history]  # print the fleet
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
STATE_PATH = os.path.join(REPO, "documents", "state", "seat-liveness.json")

ROLE_STALE_SECONDS = 20 * 60      # a seat holding a role
UNASSIGNED_STALE_SECONDS = 60 * 60  # no role claimed


def now_iso(now=None):
    dt = now or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_ts(ts):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def load_state(path=STATE_PATH):
    """Read the state file. A missing or corrupt file returns {} rather than crashing — the
    corrupt case is replaced on the next write, never left to break a reader."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def save_state(data, path=STATE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def stamp_event(payload, event, path=STATE_PATH, now=None):
    """Stamp one hook event for the session named in the payload. Returns the session id
    stamped, or None if the payload carried none (never raises)."""
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not session_id:
        return None
    state = load_state(path)
    row = state.get(session_id, {})
    row["last_event"] = event
    row["last_ts"] = now_iso(now)
    if isinstance(payload, dict) and payload.get("cwd"):
        row["cwd"] = payload["cwd"]
    state[session_id] = row
    save_state(state, path)
    return session_id


def _newest_session_for_cwd(state, cwd):
    """Fall back for `claim` when CLAUDE_SESSION_ID isn't set: the most recently stamped
    session whose cwd matches ours."""
    best_id, best_ts = None, None
    for sid, row in state.items():
        if cwd and row.get("cwd") and row.get("cwd") != cwd:
            continue
        ts = _parse_ts(row.get("last_ts", ""))
        if ts is None:
            continue
        if best_ts is None or ts > best_ts:
            best_ts, best_id = ts, sid
    return best_id


def claim(role, path=STATE_PATH, session_id=None, cwd=None, now=None):
    """A seat claims its own role. Uses CLAUDE_SESSION_ID if set; else the most recently
    stamped session for this cwd. Returns (session_id, how) where how is "env" or "cwd-match"."""
    how = None
    sid = session_id or os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        how = "env"
    else:
        state = load_state(path)
        sid = _newest_session_for_cwd(state, cwd or os.getcwd())
        how = "cwd-match"
    if not sid:
        return None, "no-session-found"
    state = load_state(path)
    row = state.get(sid, {})
    row["role"] = role
    row["claimed_by"] = "claim"
    row["last_ts"] = now_iso(now)
    row.setdefault("last_event", "claim")
    state[sid] = row
    save_state(state, path)
    return sid, how


def assign(session_prefix, role, path=STATE_PATH, now=None):
    """The orchestrator assigns a role to a session by prefix match. Wins over a prior claim on
    conflict — this write is always applied last-write-wins, same file, same shape."""
    state = load_state(path)
    matches = [sid for sid in state if sid.startswith(session_prefix)]
    if not matches:
        # no existing row yet -- create one keyed by the prefix itself so an assign before any
        # hook event still lands somewhere findable.
        sid = session_prefix
    else:
        # prefer the most recently stamped match
        matches.sort(key=lambda s: state[s].get("last_ts", ""), reverse=True)
        sid = matches[0]
    row = state.get(sid, {})
    row["role"] = role
    row["claimed_by"] = "assign"
    row["last_ts"] = now_iso(now)
    row.setdefault("last_event", "assign")
    state[sid] = row
    save_state(state, path)
    return sid


def _quiet_seconds(row, now):
    ts = _parse_ts(row.get("last_ts", ""))
    if ts is None:
        return None
    return (now - ts).total_seconds()


def stale_threshold(row):
    return ROLE_STALE_SECONDS if row.get("role") else UNASSIGNED_STALE_SECONDS


def fleet_rows(path=STATE_PATH, now=None):
    """Return a list of dicts: session_id, role, minutes_quiet, stale (bool). Sessions quiet
    over 24h are dropped, same rule the pair-brief block applies."""
    now = now or datetime.now(timezone.utc)
    state = load_state(path)
    out = []
    for sid, row in state.items():
        quiet = _quiet_seconds(row, now)
        if quiet is None:
            continue
        if quiet > 24 * 3600:
            continue
        stale = quiet > stale_threshold(row)
        out.append({
            "session_id": sid,
            "role": row.get("role") or "(unassigned)",
            "minutes_quiet": round(quiet / 60.0, 1),
            "stale": stale,
            "claimed_by": row.get("claimed_by"),
            "last_event": row.get("last_event"),
        })
    out.sort(key=lambda r: r["minutes_quiet"])
    return out


def report(path=STATE_PATH, now=None, history=False):
    rows = fleet_rows(path, now)
    lines = []
    for r in rows:
        flag = "🔴" if r["stale"] else "🟢"
        lines.append(
            f"{flag} {r['session_id'][:8]} · {r['role']} · {r['minutes_quiet']}m quiet"
        )
    if not lines:
        lines = ["(no seats stamped yet)"]
    if history:
        stale_count = sum(1 for r in rows if r["stale"])
        lines.append(f"-- stale episodes this read: {stale_count}")
    return "\n".join(lines)


def _hook_main(event):
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        stamp_event(payload, event)
    except Exception:
        pass
    sys.exit(0)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "--hook":
        event = argv[1] if len(argv) > 1 else "unknown"
        _hook_main(event)
        return 0
    if argv[0] == "claim":
        role = argv[1] if len(argv) > 1 else "unassigned"
        sid, how = claim(role)
        if sid is None:
            print(f"could not claim {role!r}: {how}")
            return 1
        print(f"claimed {role!r} for session {sid} (via {how})")
        return 0
    if argv[0] == "assign":
        if len(argv) < 3:
            print("usage: seat_liveness.py assign <session-prefix> <role>")
            return 1
        sid = assign(argv[1], argv[2])
        print(f"assigned {argv[2]!r} to session {sid}")
        return 0
    if argv[0] == "report":
        history = "--history" in argv[1:]
        print(report(history=history))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
