#!/usr/bin/env python3
"""backup_hold.py — a review-hold that pauses ONLY the auto-backup PUBLISH, never the local snapshot.

WHY (BUG-218 timer sub-fix, #91 Layer 1). The launchd backup timer ends in an ungated
`git add -A` + commit + `git push` of the whole workspace (and a partner-starter change then flows to
the kit). During active gate/security/panel work, that timer has published unreviewed work three times
in one day. This is the mechanical hold: a terminal doing reviewed-before-publish work sets the hold at
the start, and backup.sh then still COMMITS locally (work is never at risk) but WITHHOLDS the push and
the kit sync until the hold is cleared.

FAIL-SAFE, like the prove_check sentinel it generalizes — but TTL-based, NOT pid-based. A review hold
is set by a terminal that then keeps working, so there is no long-lived holder process to test for
liveness (that model would mark the hold stale the instant the setter returned). Instead the hold
AUTO-EXPIRES after HOLD_TTL_SECONDS, so a forgotten hold can never wedge backups forever, and `off`
clears it as soon as the review has Michael's go. A repo that stops backing itself up is a worse
failure than a late publish.

  backup_hold.py on --reason "landing the P0 batch"   # set the hold
  backup_hold.py off                                   # clear it (after Michael's go)
  backup_hold.py status                                # human-readable state
  backup_hold.py check                                 # exit 0 = HOLD ACTIVE (skip publish) · 1 = none

Stdlib only. Kit-portable.
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
HOLD = os.path.join(REPO, "documents", "state", ".backup-hold")
HOLD_TTL_SECONDS = 4 * 60 * 60   # 4h: longer than a panel+report cycle, short enough to self-clear


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _age_seconds(ts_iso):
    try:
        ts = datetime.datetime.fromisoformat(ts_iso)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        return (_now() - ts).total_seconds()
    except Exception:
        return None


def read():
    """The current hold dict, or None. A malformed file is treated as a (stale) hold to be voided."""
    if not os.path.exists(HOLD):
        return None
    try:
        return json.load(open(HOLD, encoding="utf-8"))
    except Exception:
        return {"reason": "(unreadable hold file)", "ts": "1970-01-01T00:00:00+00:00", "pid": None}


def active():
    """(True, reason) if a LIVE hold exists; else (False, "").

    Voids and deletes a stale hold (age >= TTL, or an unreadable/undateable file) so it can never
    wedge backups. This is the ONE place staleness is decided, so `check` and any importer agree."""
    h = read()
    if not h:
        return False, ""
    age = _age_seconds(h.get("ts", ""))
    if age is None or age >= HOLD_TTL_SECONDS:
        try:
            os.remove(HOLD)
        except OSError:
            pass
        return False, ""
    return True, h.get("reason") or "(no reason given)"


def _set(reason):
    os.makedirs(os.path.dirname(HOLD), exist_ok=True)
    row = {"reason": reason or "(no reason given)", "ts": _now().isoformat(),
           "pid": os.getppid()}     # ppid = the shell/terminal that set it, for the human reading status
    with open(HOLD, "w", encoding="utf-8") as fh:
        json.dump(row, fh)
    return row


def main():
    ap = argparse.ArgumentParser(description="pause ONLY the auto-backup publish during reviewed work")
    sub = ap.add_subparsers(dest="cmd")
    on = sub.add_parser("on")
    on.add_argument("--reason", default="")
    sub.add_parser("off")
    sub.add_parser("status")
    sub.add_parser("check")
    a = ap.parse_args()

    if a.cmd == "on":
        row = _set(a.reason)
        print(f"🔒 backup PUBLISH held (local commits continue). reason: {row['reason']} · "
              f"auto-expires in {HOLD_TTL_SECONDS // 3600}h. Clear with: backup_hold.py off")
        return 0
    if a.cmd == "off":
        existed = os.path.exists(HOLD)
        try:
            os.remove(HOLD)
        except OSError:
            existed = False
        print("🔓 backup hold cleared; publish resumes." if existed else "(no hold was set)")
        return 0
    if a.cmd == "status":
        ok, reason = active()
        if ok:
            h = read() or {}
            age = _age_seconds(h.get("ts", "")) or 0
            print(f"🔒 HELD · reason: {reason} · age {int(age // 60)}m · "
                  f"expires in {int((HOLD_TTL_SECONDS - age) // 60)}m")
        else:
            print("🔓 no active hold; publish is enabled.")
        return 0
    if a.cmd == "check":
        ok, _ = active()
        return 0 if ok else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
