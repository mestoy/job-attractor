#!/bin/bash
# watch_send_log.sh — react the moment a send lands: re-check the log's integrity, recompute the
# ladder, and snapshot it. READ-ONLY against every store the pipeline owns.
#
# WHY THIS EXISTS. documents/send-log.jsonl is the single source for every number on the ladder, for
# check_pair's staleness test, and for the contacted-filter that decides who gets offered as the
# next initial contact. Nothing watched it. Two costs, both already paid:
#
#   1. 🔴 THE HALF-CORRUPT LOG. HARD-INVARIANTS records this as an ACCEPTED RESIDUAL of the
#      2026-08-02 pair-gate flip: "a HALF-corrupt send log (some parseable rows plus garbage) still
#      reads as healthy and would present partial totals as live." A reader that skips a bad line
#      and carries on cannot tell a 377-row log from a 400-row log with 23 unreadable rows. This
#      watcher counts the unreadable ones and says so, at the moment they appear, which is the only
#      time the cause is still recoverable.
#   2. 🕰 BUG-154's SHAPE. A row the readers could not parse was invisible for 19% of the log, and
#      the symptom surfaced as a SCORING problem days later. An integrity count at write time turns
#      that class from a week-long misdiagnosis into a line in a log.
#
# ⛔ READ-ONLY, DELIBERATELY, AND IT DOES NOT RUN check_followups.py. That script REWRITES
# outreach_log.md when it arms a row (its ARMS_FOLLOWUP set is empty today, so in practice it writes
# nothing, but "empty today" is a constant somebody can change in one line). A background job that
# becomes a writer the moment a constant changes is exactly [[never-measure-a-tree-with-two-writers]].
# The dedup and follow-up checks stay where they are, on the paths a human is watching.
#
# ⚠️ IT DOES NOT NOTIFY ON A NORMAL SEND, and that is intentional. A send is something the owner just
# did; telling him about it is noise. It shouts on INTEGRITY failures only.
#
# Fires from launchd WatchPaths on the log itself, with an interval fallback: the log is appended to
# rather than atomically replaced, so WatchPaths sees it, but a watcher whose only trigger is a
# kqueue registration has no way to notice it stopped being registered.
#
# Exit: 0 always.
set -uo pipefail

REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
# Both overridable so the integrity path can be PROVEN RED against a corrupted COPY. ⛔ Never point
# a test at the live log: HARD-INVARIANTS §NEVER TEST A HOOK AGAINST LIVE STORES, written after a
# synthetic hook input minted a real MAC-signed BUILD row.
SENDLOG="${WATCH_SEND_LOG_FILE:-$REPO/documents/send-log.jsonl}"
STATE_DIR="${WATCH_STATE_DIR:-$HOME/Library/Application Support/jobsearch-watchers}"
SEEN="$STATE_DIR/send-log-seen.txt"
LADDER="$STATE_DIR/ladder-history.log"
LOCK="$STATE_DIR/.watch-send-log.lock"
# 📏 LITERAL first, so check_job_liveness.py's `^LOG="([^"]+)"` can resolve it (an unexpanded
# "$STATE_DIR/…" made it fall back to a 0-byte /tmp file and call that a witness). The override
# below keeps a test run's log out of the live directory.
LOG="${JOBKIT_WATCHER_LOG_DIR:-$HOME/Library/Application Support/jobsearch-watchers}/watch-send-log.log"
[ -n "${WATCH_STATE_DIR:-}" ] && LOG="$WATCH_STATE_DIR/watch-send-log.log"

mkdir -p "$STATE_DIR" || exit 0
cd "$REPO" || exit 0
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

# ── LOCK. WatchPaths and the interval fallback can fire together, and both would append a row to
# ladder-history.log for one send, which makes the history unreadable as a history. ──────────────
if ! mkdir "$LOCK" 2>/dev/null; then
  _owner="$(cat "$LOCK/pid" 2>/dev/null)"
  _age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || echo 0) ))
  if { [ -n "$_owner" ] && ! kill -0 "$_owner" 2>/dev/null; } || [ "$_age" -gt 600 ]; then
    log "[ok] clearing a stale lock (owner '${_owner:-?}', age ${_age}s)"
    rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null || exit 0
  else
    exit 0
  fi
fi
echo "$$" > "$LOCK/pid"
trap '[ "$(cat "$LOCK/pid" 2>/dev/null)" = "$$" ] && rm -rf "$LOCK"' EXIT

[ -f "$SENDLOG" ] || { log "🔴 send-log.jsonl is MISSING"; exit 0; }

# Only work when the file actually moved. WatchPaths fires on load and can fire more than once for
# one write; the interval fallback fires regardless. Without this the ladder history would fill with
# identical rows and stop being readable as a history.
SIG="$(stat -f "%m %z" "$SENDLOG" 2>/dev/null)"
[ "$SIG" = "$(cat "$SEEN" 2>/dev/null)" ] && exit 0
printf '%s' "$SIG" > "$SEEN"

# ── INTEGRITY. Count what the readers CAN and CANNOT parse. ──────────────────────────────────────
REPORT="$(python3 - "$SENDLOG" <<'PY'
import json, sys
good = 0
bad = []
with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    for n, line in enumerate(fh, 1):
        if not line.strip():
            continue
        try:
            json.loads(line)
            good += 1
        except Exception:
            bad.append(n)
print(f"{good}\t{len(bad)}\t{','.join(str(b) for b in bad[:20])}")
PY
)"
GOOD="$(printf '%s' "$REPORT" | cut -f1)"
BAD="$(printf '%s' "$REPORT" | cut -f2)"
BADLINES="$(printf '%s' "$REPORT" | cut -f3)"

if [ "${BAD:-0}" -gt 0 ]; then
  log "🔴 send-log INTEGRITY: ${BAD} unparseable row(s) alongside ${GOOD} good — line(s): ${BADLINES}"
  log "     Every ladder number and the contacted-filter read this file. Partial totals will"
  log "     present as live until these rows are fixed."
  osascript -e "display notification \"${BAD} unparseable row(s) at line(s) ${BADLINES}\" with title \"send-log.jsonl integrity\" subtitle \"Ladder totals are partial\"" >/dev/null 2>&1
fi

# ── LADDER. Recompute through pair_brief.stamp(), the ONE producer of that line. ─────────────────
# Never re-formatted here: a second formatter is a second answer, which this repo has paid for three
# times (check_pair.py:60-62 says the same thing about itself).
STAMP="$(python3 - <<'PY'
import os, sys
repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(repo, "scripts"))
os.environ.setdefault("CLAUDE_PROJECT_DIR", repo)
try:
    import pair_brief
    print(pair_brief.stamp())
except Exception as e:
    print(f"UNAVAILABLE: {e.__class__.__name__}: {e}")
PY
)"

case "$STAMP" in
  UNAVAILABLE*)
    log "⚪ ladder recompute failed — ${STAMP}"
    ;;
  *)
    echo "$(date '+%F %T')  rows=${GOOD} bad=${BAD}  ${STAMP}" >> "$LADDER"
    log "[ok] ${GOOD} row(s), ${BAD} bad · ${STAMP}"
    ;;
esac
exit 0
