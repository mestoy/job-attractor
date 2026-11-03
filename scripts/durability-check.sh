#!/bin/bash
# Durability check: verifies every layer of the job-search workflow survives a cold start
# (new session / context loss / new machine). READ-ONLY — makes no changes, pushes nothing.
# Run anytime: bash scripts/durability-check.sh   (exit 0 = all durable, 1 = something at risk)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"

FAIL=0
# Color only on a terminal; plain text when logged/piped (keeps the daily log clean).
if [ -t 1 ]; then C_G=$'\033[32m'; C_Y=$'\033[33m'; C_B=$'\033[1m'; C_0=$'\033[0m'; else C_G=; C_Y=; C_B=; C_0=; fi
pass() { printf "  %s✓%s %s\n" "$C_G" "$C_0" "$1"; }
warn() { printf "  %s!%s %s\n" "$C_Y" "$C_0" "$1"; FAIL=1; }
hdr()  { printf "\n%s%s%s\n" "$C_B" "$1" "$C_0"; }

# Point JOBSEARCH_MEMORY_DIR at your assistant's memory store; the default derives it
# from this repo's path. JOBKIT_LAUNCHD_PREFIX must match the labels you actually installed.
_MEMSLUG="$(printf '%s' "$REPO" | tr '/' '-')"
MEM="${JOBSEARCH_MEMORY_DIR:-$HOME/.claude/projects/$_MEMSLUG/memory}"
LAUNCHD_PREFIX="${JOBKIT_LAUNCHD_PREFIX:-com.example.jobsearch}"

hdr "1. Scheduled jobs (auto-backup + prep + durability check survive a reboot)"
# BUG FIXED 2026-07-19: this loop used `launchctl list | grep -q "$job"` under `set -o pipefail`.
# `grep -q` exits on the FIRST match, closing the pipe; launchctl then dies on SIGPIPE (141), and
# pipefail propagates that as a pipeline failure — so a job that IS loaded gets reported
# "NOT loaded". It hit whichever label sits earliest in launchctl's output (consistencycheck),
# which is why that one looked permanently missing while the others passed. Snapshot once, then grep.
LC_SNAPSHOT="$(launchctl list 2>/dev/null || true)"
# ⛔ DERIVE THE JOB LIST; NEVER TYPE ONE. A typed list drifted twice upstream (autosweep
# 2026-08-05, dailyrank 2026-08-10) and each time the new job was the one nothing verified. It is
# worse in the kit: a typed list also decides FOR you that your only jobs are these four, so a
# fifth job you schedule yourself is unmonitored by construction.
#
# Three sources, because each sees a failure the others cannot: the mirrored plists are what a
# rebuild would restore, the loaded labels are what is actually running, and git is the memory —
# a plist tracked in the repo but gone from the worktree is exactly "a rebuild would lose this",
# and a list built only from what exists right now would report zero jobs and call that clean.
JOBS=()
while IFS= read -r _lab; do [ -n "$_lab" ] && JOBS+=("$_lab"); done < <(
  { ls "scripts/launchd/$LAUNCHD_PREFIX."*.plist 2>/dev/null | xargs -n1 basename 2>/dev/null | sed 's/\.plist$//'
    git ls-files "scripts/launchd/$LAUNCHD_PREFIX.*.plist" 2>/dev/null | xargs -n1 basename 2>/dev/null | sed 's/\.plist$//'
    printf '%s\n' "$LC_SNAPSHOT" | grep -o "$(printf '%s' "$LAUNCHD_PREFIX" | sed 's/[.[\*^$]/\\&/g')\.[A-Za-z0-9._-]*" || true
  } | sort -u)
# A CHECK THAT CAN NEVER PASS IS NOT A CHECK. The kit ships no scripts/launchd/ plists, and
# scheduling is optional, so this loop used to emit eight warnings on every run for every user
# and pin the overall result at "at risk" permanently. A report that is always red teaches people
# to stop reading it, which costs more than the thing it was warning about. So: if you have not
# set up scheduling at all, say so once, as information. Once ANY plist or loaded label exists,
# scheduling is something you rely on, and every missing piece of it is a real warning again.
_sched_any=0
for job in ${JOBS[@]+"${JOBS[@]}"}; do   # empty-array guard: bash 3.2 + set -u errors on "${JOBS[@]}" when unset
  if [ -f "scripts/launchd/$job.plist" ] || printf '%s\n' "$LC_SNAPSHOT" | grep -q "$job"; then
    _sched_any=1
  fi
done
if [ "$_sched_any" = "0" ]; then
  printf "  %si%s no scheduled jobs configured (optional). To automate backup/prep/checks, add\n" "$C_Y" "$C_0"
  printf "     plists under scripts/launchd/ named %s.<backup|prep|durabilitycheck|consistencycheck>.plist\n" "$LAUNCHD_PREFIX"
  printf "     and load them with launchctl. Until then, run scripts/backup.sh by hand.\n"
else
  for job in ${JOBS[@]+"${JOBS[@]}"}; do   # empty-array guard: bash 3.2 + set -u errors on "${JOBS[@]}" when unset
    if printf '%s\n' "$LC_SNAPSHOT" | grep -q "$job"; then pass "$job loaded"; else warn "$job NOT loaded (run: launchctl load ~/Library/LaunchAgents/$job.plist)"; fi
    [ -f "scripts/launchd/$job.plist" ] && pass "$job plist mirrored in repo" || warn "$job plist NOT mirrored (run scripts/backup.sh, schedule config would be lost on rebuild)"
  done
fi

hdr "2. Offsite backup (survives machine loss)"
# FALSE GREEN FIXED: this ran `git status --porcelain` with no check that the folder is a git repo
# at all. Outside a repo, git writes "fatal: not a git repository" to stderr and produces EMPTY
# stdout, so the emptiness test passed and the report printed "workspace clean, last backup is
# current" to a user who has no repository and therefore NO backup of any kind. The one state this
# section exists to catch was the one state it reported as healthy. Establish the repo first.
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  warn "not a git repository, nothing here is backed up offsite. Run: git init && git remote add origin <your-repo>, then bash scripts/backup.sh"
else
if [ -z "$(git status --porcelain)" ]; then
  pass "workspace clean — last backup is current"
else
  n=$(git status --porcelain | wc -l | tr -d ' ')
  warn "$n uncommitted change(s) — run scripts/backup.sh to make durable"
fi
# ⛔ NEVER COMPARE AGAINST THE BRANCH'S CONFIGURED UPSTREAM (`@{u}`). On an install that TRACKS
# the shared kit, `main`'s upstream IS the kit remote, and your own private commits are ALWAYS
# ahead of it by definition — they must never be pushed there. This used to report "64 local
# commit(s) not pushed offsite" while HEAD and the real private remote were identical and
# everything was durable, because it was measuring distance from the kit, not from your backup.
# A durability check that is structurally always red on a kit-tracking install is worse than no
# check: it teaches you to skim past a real warning.
#
# Same kit-remote detection "Update Kit.command" uses (URL match, never a hardcoded name — a
# fork keeps the repo name, so name-only matching picks the wrong remote on a forked install):
# find the remote that IS the kit, then check durability against a DIFFERENT remote, never that
# one. If every remote is the kit (no private remote configured at all), say so plainly instead
# of reporting a false pass or a confusing ahead-count against the kit.
KIT_CANONICAL="mestoy/job-attractor-kit"
KIT_REMOTE=""
for _r in $(git remote 2>/dev/null); do
  _u="$(git remote get-url "$_r" 2>/dev/null)"
  case "$_u" in
    *"$KIT_CANONICAL"*) KIT_REMOTE="$_r"; break ;;
    *job-attractor-kit*) [ -z "$KIT_REMOTE" ] && KIT_REMOTE="$_r" ;;
  esac
done
PRIVATE_REMOTE=""
for _r in $(git remote 2>/dev/null); do
  if [ "$_r" = "origin" ] && [ "$_r" != "$KIT_REMOTE" ]; then PRIVATE_REMOTE="origin"; break; fi
done
if [ -z "$PRIVATE_REMOTE" ]; then
  for _r in $(git remote 2>/dev/null); do
    if [ "$_r" != "$KIT_REMOTE" ]; then PRIVATE_REMOTE="$_r"; break; fi
  done
fi
_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
if [ -z "$PRIVATE_REMOTE" ]; then
  warn "no private remote configured (only the kit remote${KIT_REMOTE:+ '$KIT_REMOTE'} is set) — commits are local-only, not offsite"
elif ! git rev-parse "$PRIVATE_REMOTE/$_branch" >/dev/null 2>&1; then
  warn "'$PRIVATE_REMOTE' has no '$_branch' branch yet — nothing pushed there so far"
else
  read -r behind ahead < <(git rev-list --left-right --count "$PRIVATE_REMOTE/$_branch...HEAD" 2>/dev/null)
  [ "${ahead:-0}" = "0" ] && pass "in sync with private remote '$PRIVATE_REMOTE'" \
    || warn "$ahead local commit(s) not pushed to '$PRIVATE_REMOTE'"
fi
last=$(git log -1 --format='%cr' 2>/dev/null)
if [ -n "$last" ]; then pass "last commit: $last"; else warn "no commits yet, run scripts/backup.sh"; fi
fi

hdr "3. Screening-critical rules live in the REPO (Discovery session can't read memory)"
for f in documents/PROFILE.md documents/WORKFLOW-RULES.md documents/HANDOFF.md \
         documents/writing-style-guide.md documents/blocked-employers-list.md; do
  [ -f "$f" ] && pass "$f" || warn "MISSING $f — a rule that lives only in memory is invisible to the other session"
done

hdr "4. Memory store mirrored into the repo (so backup captures it)"
if [ -d "$MEM" ]; then
  live=$(ls -1 "$MEM"/*.md 2>/dev/null | wc -l | tr -d ' ')
  mirror=$(ls -1 _memory-backup/*.md 2>/dev/null | wc -l | tr -d ' ')
  if [ "$live" = "$mirror" ]; then pass "memory in sync ($live files live = mirror)"
  else warn "memory drift: $live live vs $mirror mirrored — run scripts/backup.sh"; fi
else
  warn "memory store not found at $MEM"
fi

hdr "5. Mechanism scripts present and configured"
for s in kit_config.py check_dup.py check_outreach.py check_screen_gate.py verify_resume.py; do
  [ -f "scripts/$s" ] && pass "scripts/$s" || warn "MISSING scripts/$s — a gate that isn't installed is a gate that never fires"
done
if [ -f scripts/kit_config.py ]; then
  if python3 scripts/kit_config.py 2>/dev/null | grep -q "RETIRED lists are empty"; then
    warn "kit_config.py still has empty RETIRED lists — the honesty scrub is a no-op until you fill them"
  else
    pass "kit_config.py honesty lists populated"
  fi
  if python3 -c "import sys; sys.path.insert(0,'scripts'); import kit_config; sys.exit(0 if kit_config.OWNER_NAME != 'Your Name' else 1)" 2>/dev/null; then
    pass "kit_config.py identity filled in"
  else
    warn "kit_config.py still has placeholder identity (OWNER_NAME = 'Your Name') — fill it in"
  fi
fi

hdr "RESULT"
if [ "$FAIL" = "0" ]; then printf "  %sAll layers durable.%s A cold start reconstructs from MEMORY.md + session-state + repo.\n" "$C_G" "$C_0"; exit 0
else printf "  %sOne or more layers at risk (see ! above).%s\n" "$C_Y" "$C_0"; exit 1; fi
