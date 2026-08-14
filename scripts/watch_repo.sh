#!/bin/bash
# watch_repo.sh — auto-backup watcher. Commits and pushes the repo once writes go QUIET.
#
# WHY THIS EXISTS. HARD-INVARIANTS says PUSH ALWAYS, "after every meaningful change, as soon as you
# can". The mechanism behind that rule was one launchd job at 21:00. So a crash, a closed laptop or
# a dead battery at 20:00 loses a full day of screening verdicts, sends, rule edits and bug fixes,
# and the rule reads as satisfied the whole time because the job is loaded and green.
#
# 🕰 IT POLLS, AND THE NAME "WATCHER" SHOULD NOT HIDE THAT. launchd's WatchPaths fires on DIRECTORY
# content changes (a file added, removed or renamed), not on an edit to a file that already exists,
# and almost every write in this repo is an edit. A WatchPaths job on the repo root would therefore
# look like a watcher and miss the ordinary case. Polling on a short interval with a quiescence test
# is the honest mechanism. fswatch would give true events; it is not installed, and a watcher that
# needs Homebrew to survive a machine rebuild is a worse trade.
#
# ⏳ QUIESCENCE, NOT EVERY-CHANGE. Committing on every write would mint a commit per keystroke-burst
# mid-session and race a build that is halfway through writing a set of files. This fires only when
# the working tree looks IDENTICAL to how it looked one tick ago: dirty, and unchanged since.
#
# ⛔ STATE LIVES OUTSIDE THE REPO, and that is load-bearing, not tidiness. A fingerprint file stored
# under documents/ would be rewritten by this script every tick, so the tree would never be
# quiescent, so the watcher would commit forever, every tick, and its own state file would be the
# only thing changing. Same family as [[never-measure-a-tree-with-two-writers]]: an instrument that
# perturbs what it measures reports its own noise. This also rules out writing a liveness stamp into
# documents/state/, which is the house convention elsewhere: here it would be that exact loop.
#
# 🔴 FOUR DEFECTS FOUND BY AN ADVERSARIAL REVIEW ON THE DAY THIS SHIPPED (2026-08-11). Each is fixed
# below and named at its fix, because a fix with no reason attached is the next person's mystery.
#
# Exit: 0 always (a watcher that fails a launchd job teaches nobody anything; it logs instead).
set -uo pipefail

REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
STATE_DIR="$HOME/Library/Application Support/jobsearch-watchers"
FP_FILE="$STATE_DIR/repo-fingerprint.txt"
LOCK="$STATE_DIR/.watch-repo.lock"
# 📏 LITERAL, NOT "$STATE_DIR/…", and that is not a style choice. check_job_liveness.py finds a
# job's real evidence by reading `^LOG="([^"]+)"` out of the script, and it does not expand shell
# variables: a declared `$STATE_DIR/watch-repo.log` resolved to a repo-relative path that never
# exists, so the checker fell through to the plist's StandardOutPath in /tmp. That file is 0 bytes,
# because everything here goes through log(). So the checker printed "✅ ran 0.0d ago (stdout)" on
# the strength of launchd having OPENED a redirect target. A watcher that died on line 1 would have
# looked identical. Found by the ops review, 2026-08-11.
LOG="${JOBKIT_WATCHER_LOG_DIR:-$HOME/Library/Application Support/jobsearch-watchers}/watch-repo.log"

# Overridable so the quiescence path can be exercised without waiting on it. ⚠️ Only ever set this
# in a test invocation; a 0 here in the launchd job would commit mid-write, which is the behavior
# the quiescence test exists to prevent.
QUIET_SECONDS="${WATCH_REPO_QUIET_SECONDS:-90}"
LOCK_STALE_SECONDS=900
# 🔴 THE HOSTAGE CEILING. The fingerprint is one hash over the WHOLE dirty set, so a single file
# that is rewritten faster than the tick interval resets the clock every tick and holds every other
# finished change hostage indefinitely, silently, forever. The state stores under documents/state/
# are exactly that shape: other automation rewrites them on a cadence. Past this ceiling the tree
# has been dirty long enough that shipping a possibly-mid-write file beats not backing up at all.
MAX_HOLD_SECONDS="${WATCH_REPO_MAX_HOLD:-3600}"

mkdir -p "$STATE_DIR" || exit 0
cd "$REPO" || { echo "$(date '+%F %T') [!] cannot enter repo" >> "$LOG"; exit 0; }

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

# ⛔ -uall IS LOAD-BEARING. Plain porcelain collapses an untracked DIRECTORY to one `?? dir/` line
# and does not recurse, and stat on that directory only moves when an entry is added or removed. So
# a tool that creates a new folder and then keeps appending to a file inside it reads as byte-for-
# byte QUIESCENT from the first tick onward, and this script would commit the partial bytes: the
# precise failure the quiescence design exists to prevent, defeated for new directories. Reproduced
# by the red-team review in a scratch repo, 2026-08-11.
porcelain() { git status --porcelain --untracked-files=all 2>/dev/null; }

# ── LOCK. mkdir is the atomic primitive available everywhere; macOS ships no flock. ──────────────
# 🔴 THE LOCK CARRIES ITS OWNER'S PID. Without one, staleness was judged on the lock's mtime alone
# and the exit trap deleted whatever sat at $LOCK. A backup whose `git push` hangs past the stale
# ceiling would have had its lock taken by a later tick, then deleted THAT tick's lock on its own
# exit, so two runs could sit inside backup.sh at once with the lock claiming otherwise.
if mkdir "$LOCK" 2>/dev/null; then
  echo "$$" > "$LOCK/pid"
else
  _age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || echo 0) ))
  _owner="$(cat "$LOCK/pid" 2>/dev/null)"
  # A dead owner is stale immediately; a live owner gets the full ceiling. ⚠️ Fail TOWARD backing
  # up: a stale lock must never silence backups forever, the same reasoning backup.sh applies to
  # the prove_check sentinel.
  if { [ -n "$_owner" ] && ! kill -0 "$_owner" 2>/dev/null; } || [ "$_age" -gt "$LOCK_STALE_SECONDS" ]; then
    log "[ok] clearing a stale lock (owner '${_owner:-?}', age ${_age}s)"
    rm -rf "$LOCK"
    mkdir "$LOCK" 2>/dev/null || exit 0
    echo "$$" > "$LOCK/pid"
  else
    # 🔴 THIS PATH USED TO LOG NOTHING. Several consecutive ticks could vanish from the log with no
    # trace, which is the exact ambiguity somebody debugging "why has it not backed up" walks into.
    log "[..] lock held by pid ${_owner:-?} (age ${_age}s), not yet stale, skipping"
    exit 0
  fi
fi
# Release only OUR OWN lock. Checking the pid is what stops a late exit from deleting a lock that a
# later tick legitimately acquired.
trap '[ "$(cat "$LOCK/pid" 2>/dev/null)" = "$$" ] && rm -rf "$LOCK"' EXIT

# ── DEFER TO ANY OTHER GIT WRITER. ───────────────────────────────────────────────────────────────
# The 21:00 backup job, a human running backup.sh, and this watcher are three callers of one git
# index. Whoever holds index.lock wins; we come back next tick.
if [ -e ".git/index.lock" ]; then
  log "[..] git index.lock held by another writer, deferring"
  exit 0
fi

# ── NEVER COMMIT ACROSS A prove_check MUTATION WINDOW. ───────────────────────────────────────────
# backup.sh already refuses this, but checking here keeps the log honest about WHY a dirty tree sat
# uncommitted, instead of leaving a silent gap somebody has to reconstruct later.
if [ -f "documents/state/.prove-check-active" ]; then
  log "[..] prove_check sentinel present, deferring (backup.sh would refuse anyway)"
  exit 0
fi

# ── NOR ACROSS A breaktest MUTATION WINDOW (found 2026-08-11, the day this watcher shipped). ─────
# 🔴 backup.sh does NOT guard this one, and until this watcher existed it did not need to: the only
# committer was a human and a 21:00 job. tests/breaktest.py REVERTS live safety-critical files in
# place (check_preview.py the BUILD gate, mail-draft.sh the send path, consistency-check.sh) and
# relies on try/finally to restore them, so on any given second of a run one gate is sitting on disk
# with its guard removed. A five-minute auto-committer turns that window into a race that eventually
# gets lost, and the loss is a PUSHED commit disarming a gate. breaktest's own header names this
# class: two overlapping runs once left three files reverted and "nothing noticed, because the
# symptom is a SKIP, which reads like harmless decay."
# ⚠️ Deliberately NO staleness override here, unlike the lock above. breaktest holds its lock for
# minutes, not hours, and the cost of waiting is one skipped tick.
if [ -f ".breaktest.lock" ]; then
  log "[..] breaktest is mid-revert (lock held); deferring so a disarmed gate cannot be committed"
  exit 0
fi

# ── A CLEAN TREE IS NOT THE SAME AS NOTHING TO BACK UP. ──────────────────────────────────────────
# 🔬 FOUND BY WATCHING IT RUN, NOT BY READING IT (2026-08-11). The first version exited here
# whenever `git status` came back clean, which looked obviously correct and was wrong. backup.sh
# does THREE things before it ever consults git: it rsyncs the memory store in from ~/.claude (346
# files that live OUTSIDE this repo), it mirrors the launchd plists in from ~/Library/LaunchAgents,
# and it syncs the partner kit. Those are the sources that MAKE the tree dirty. Gating on dirtiness
# first inverted the order, so a night of memory writes and the three plists for these very watchers
# were invisible: the watcher ran, saw clean, exited, forever. The 21:00 job never had this bug
# because it calls backup.sh directly and backup.sh mirrors first.
MEM="${JOBKIT_MEMORY_DIR:-$HOME/.claude/projects/$(printf %s "$REPO" | tr "/ " "--")/memory}"
LA="$HOME/Library/LaunchAgents"

external_newest() {   # newest mtime among the out-of-repo sources backup.sh pulls in
  {
    [ -d "$MEM" ] && find "$MEM" -type f -exec stat -f %m {} + 2>/dev/null
    compgen -G "$LA/${JOBKIT_LAUNCHD_PREFIX:-com.jobkit}.*.plist" > /dev/null && stat -f %m "$LA"/${JOBKIT_LAUNCHD_PREFIX:-com.jobkit}.*.plist 2>/dev/null
  } | sort -rn | head -1
}

DIRTY="$(porcelain)"
EXT="$(external_newest)"; EXT="${EXT:-0}"
LAST_COMMIT="$(git log -1 --format=%ct 2>/dev/null || echo 0)"

if [ -z "$DIRTY" ] && [ "$EXT" -le "$LAST_COMMIT" ]; then
  rm -f "$FP_FILE"
  exit 0
fi

# ── FINGERPRINT: what changed, plus each changed file's mtime and size. ──────────────────────────
# Porcelain alone is too coarse: editing the same file twice produces the same ` M path` line both
# times, so a tree under active editing would read as quiescent and commit mid-write. mtime+size is
# what makes "still being worked on" distinguishable from "finished".
fingerprint() {
  {
    echo "ext:$EXT"          # so a memory-store write alone still settles and still fires
    porcelain
    porcelain | cut -c4- | while IFS= read -r p; do
      # A rename prints "old -> new"; stat will simply miss it and the porcelain line above still
      # carries the change. Failing quietly here is correct.
      [ -e "$p" ] && stat -f "%m %z %N" "$p" 2>/dev/null
    done
  } | shasum | awk '{print $1}'
}

FP="$(fingerprint)"
NOW="$(date +%s)"
PREV_FP=""; PREV_AT=0; FIRST_DIRTY=0
if [ -f "$FP_FILE" ]; then
  PREV_FP="$(sed -n '1p' "$FP_FILE")"
  PREV_AT="$(sed -n '2p' "$FP_FILE")"; [ -n "$PREV_AT" ] || PREV_AT=0
  FIRST_DIRTY="$(sed -n '3p' "$FP_FILE")"; [ -n "$FIRST_DIRTY" ] || FIRST_DIRTY=0
fi
[ "$FIRST_DIRTY" -eq 0 ] && FIRST_DIRTY="$NOW"

HELD=$(( NOW - FIRST_DIRTY ))
FORCED=""
if [ "$FP" != "$PREV_FP" ]; then
  if [ "$HELD" -lt "$MAX_HOLD_SECONDS" ]; then
    printf '%s\n%s\n%s\n' "$FP" "$NOW" "$FIRST_DIRTY" > "$FP_FILE"
    exit 0          # tree is moving; wait for it to settle
  fi
  FORCED="yes"      # past the ceiling: something never settles, back up anyway
elif [ $(( NOW - PREV_AT )) -lt "$QUIET_SECONDS" ]; then
  printf '%s\n%s\n%s\n' "$FP" "$PREV_AT" "$FIRST_DIRTY" > "$FP_FILE"
  exit 0            # unchanged, but not for long enough yet
fi

_files="$(porcelain | wc -l | tr -d ' ')"
if [ -n "$FORCED" ]; then
  log "[!!] tree has been dirty ${HELD}s and never settles; backing up anyway (${_files} change(s))"
  log "     Something is rewriting a file faster than the tick. Check the log's newest entries."
else
  log "[>>] tree quiet for $(( NOW - PREV_AT ))s with ${_files} change(s); running backup.sh"
fi

HEAD_BEFORE="$(git rev-parse HEAD 2>/dev/null)"
bash "$REPO/scripts/backup.sh" >> "$LOG" 2>&1
_rc=$?
HEAD_AFTER="$(git rev-parse HEAD 2>/dev/null)"

# 🔴 backup.sh's EXIT CODE IS NOT A SUCCESS SIGNAL. It has no `set -e`, its last statement is an
# if/else whose branches both succeed, and `git add -A` failing on a lock race is never checked. So
# it exits 0 whether it committed or silently no-op'd, and "[ok] backup.sh exited 0" would look
# identical either way. That is the worst failure this script can have: a backup watcher whose log
# reads green while nothing reaches GitHub. Ask git directly instead of believing the exit code.
UNPUSHED="$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo '?')"
if [ "$HEAD_BEFORE" = "$HEAD_AFTER" ] && [ -n "$(porcelain)" ]; then
  log "[!!] backup.sh exited $_rc but HEAD DID NOT MOVE and the tree is still dirty. Nothing was"
  log "     committed. Read the backup.sh output directly above this line for the git error."
elif [ "$UNPUSHED" != "0" ]; then
  log "[!!] committed, but ${UNPUSHED} commit(s) are still UNPUSHED. Run: git -C \"$REPO\" push"
else
  log "[ok] backed up and pushed (exit $_rc, HEAD ${HEAD_BEFORE:0:7} -> ${HEAD_AFTER:0:7})"
fi
rm -f "$FP_FILE"
exit 0
