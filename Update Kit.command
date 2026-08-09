#!/bin/bash
# ============================================================
#  Update Kit — double-click to get the latest Job Attractor
#  tooling (skills, rules, scripts, search CLIs).
#
#  NON-DESTRUCTIVE: your private documents/ folder — profile,
#  outreach queue, logs, tracker, blocked list, résumés — is
#  git-ignored and is NEVER overwritten. Your identity in
#  scripts/kit_config.py is preserved across the update.
#
#  Anything this script does replace is copied to
#  documents/.superseded/ first, so nothing is ever lost.
# ============================================================
cd "$(dirname "$0")" || { echo "Could not find the kit folder."; exit 1; }

echo ""
echo "▶  Updating the Job Attractor Kit…"
echo ""

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "⚠  This folder isn't a git clone. Run the installer once, or clone"
  echo "   https://github.com/mestoy/job-attractor-kit first."
  echo ""; read -n1 -s -p "Press any key to close."; echo; exit 1
fi

BK="documents/.superseded/$(date '+%Y-%m-%d-%H%M%S')"
_keep() { # $1 = path to preserve a copy of, before anything replaces it
  [ -f "$1" ] || return 0
  mkdir -p "$BK/$(dirname "$1")" 2>/dev/null
  cp "$1" "$BK/$1" 2>/dev/null
}

# ── 1. Protect the config you filled in ───────────────────────────────────────────────────────
# scripts/kit_config.py used to ship TRACKED while /setup told you to fill it in. That combination
# broke updates permanently: git refuses to overwrite a locally-modified tracked file, so
# `git pull --ff-only` aborted every single time and this script blamed your internet connection.
# The kit now ships scripts/kit_config.example.py and git-ignores your real copy. This block
# carries an older install across that change without losing your identity.
CFG="scripts/kit_config.py"
CFG_SAVED=""
if [ -f "$CFG" ]; then
  CFG_SAVED="$(mktemp)"; cp "$CFG" "$CFG_SAVED"; _keep "$CFG"
  # If it is still tracked here, restore the pristine copy so the tree is clean and the pull can
  # fast-forward. Your real values are already saved above and are restored after the pull.
  if git ls-files --error-unmatch "$CFG" >/dev/null 2>&1; then
    git checkout -- "$CFG" 2>/dev/null || true
  fi
fi

# ── 2. Find the remote that actually IS the kit ───────────────────────────────────────────────
# ⛔ NEVER ASSUME `origin` (fixed 2026-08-03). This script used to pull with a bare `git pull` and
# fetch with a hardcoded `git fetch origin`, on the assumption that `origin` is the kit. For anyone
# who forked the kit into their own GitHub account, `origin` is THEIR repo. One real install carried
# three remotes:
#     origin    -> <their-account>/job-search      (theirs)
#     kit       -> the kit
#     upstream  -> the kit
# with the branch tracking `origin/main`. So every double-click pulled from their own repo, found
# nothing new, and reported success. Months of published fixes never arrived and nothing said so.
# A silent no-op that prints "up to date" is worse than an error, because it teaches you to trust it.
#
# So: pick the remote whose URL looks like the kit, whatever it is named, and fall back to origin
# only when nothing matches (the ordinary single-remote install, unchanged).
#
# ⛔ AND A NAME MATCH IS NOT ENOUGH EITHER (fixed 2026-08-03). The first version of this loop walked
# the remotes in `git remote` order (alphabetical) and took the first URL containing
# "job-attractor-kit". A GitHub FORK KEEPS THE REPO NAME, so a fork at
# <their-account>/job-attractor-kit named `origin` matched, sorted before `upstream`, and won —
# reproducing the exact silent no-op this block was written to end. So the preference order is now:
#   (i)   a remote whose URL matches the CANONICAL owner AND name — the only unambiguous answer;
#   (ii)  else any remote whose URL contains the kit name, preferring one that is NOT the branch's
#         current tracking remote, because the tracking remote is where the silent-no-op pulls were
#         already coming from and a second kit-named remote is the likelier real upstream;
#   (iii) else origin (the ordinary single-remote install, unchanged).
KIT_CANONICAL="mestoy/job-attractor-kit"
KIT_REMOTE=""
_kit_named=""
_track_remote="$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null | cut -d/ -f1 || true)"
for _r in $(git remote 2>/dev/null); do
  _u="$(git remote get-url "$_r" 2>/dev/null)"
  case "$_u" in
    *"$KIT_CANONICAL"*) KIT_REMOTE="$_r"; break ;;                    # (i) exact owner + name
    *job-attractor-kit*)                                              # (ii) name only: collect
      if [ -z "$_kit_named" ] || { [ "$_kit_named" = "$_track_remote" ] && [ "$_r" != "$_track_remote" ]; }; then
        _kit_named="$_r"
      fi
      ;;
  esac
done
[ -n "$KIT_REMOTE" ] || KIT_REMOTE="$_kit_named"
if [ -z "$KIT_REMOTE" ]; then
  KIT_REMOTE="origin"
else
  _tracking="$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || true)"
  case "$_tracking" in
    "$KIT_REMOTE"/*) : ;;   # already tracking the kit, nothing to say
    *)
      echo "ℹ  This branch was tracking '${_tracking:-nothing}', which is not the kit."
      echo "   Pointing it at '$KIT_REMOTE' so updates can reach you."
      _branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
      git fetch "$KIT_REMOTE" --quiet 2>/dev/null
      git branch --set-upstream-to="$KIT_REMOTE/$_branch" "$_branch" >/dev/null 2>&1 \
        || git branch --set-upstream-to="$KIT_REMOTE/main" "$_branch" >/dev/null 2>&1 || true
      echo ""
      ;;
  esac
fi

# ── 3. Pull ───────────────────────────────────────────────────────────────────────────────────
if ! git pull --ff-only "$KIT_REMOTE"; then
  # A fast-forward can fail for two very different reasons, and they need opposite responses.
  # (a) HISTORY WAS REWRITTEN UPSTREAM. If published content ever has to be removed for real
  #     (an address, a name, anything that should not have shipped), the only honest fix is to
  #     rewrite and force-push, which changes every commit id. Your clone is then not "behind",
  #     it is on a history that no longer exists, and no fast-forward can ever succeed again.
  #     Recovering is safe here because everything of yours is either git-ignored (documents/,
  #     your profile, logs, tracker, résumés) or preserved above (scripts/kit_config.py).
  # (b) You edited a file the kit also ships. Then a reset WOULD lose your work, so stop instead.
  git fetch "$KIT_REMOTE" --quiet 2>/dev/null
  _upstream="$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || echo "$KIT_REMOTE/main")"
  # ⛔ CIRCUIT BREAKER (BUG-040, added 2026-08-07). THE TEST BELOW USED TO BE THE ANCESTOR CHECK
  # ALONE, and that conflates two situations with opposite correct responses. "HEAD is not an
  # ancestor of upstream" is true when upstream rewrote history, AND it is equally true when YOU
  # have local commits upstream has never seen. The comment above reads the condition as case (a)
  # only, so a partner with their own work took the rewrite branch and `git reset --hard` deleted
  # it. A real partner clone carries exactly that: local fixes to boss_registry.py, parse_network.py,
  # record_finding.py and screen_sweep.py, plus commits 3c36a6a and 19c943a. It did not fire on
  # 2026-08-06 by luck, not by design.
  #
  # The discriminator is not "is HEAD behind" but "does HEAD carry commits upstream does not have".
  # If it does, nothing here is allowed to destroy them, whatever the reason for the failure.
  _local_only=0
  if [ -n "$_upstream" ]; then
    _local_only="$(git rev-list --count "$_upstream..HEAD" 2>/dev/null || echo 0)"
  fi
  if [ "${_local_only:-0}" -gt 0 ]; then
    _safety="kit-backup-$(date +%Y%m%d-%H%M%S)"
    git branch "$_safety" HEAD 2>/dev/null
    echo ""
    echo "🛑 STOPPED. You have $_local_only commit(s) the published kit does not have, so a"
    echo "   re-sync here would delete your own work. Nothing was changed."
    echo ""
    echo "   Your work is also saved on a branch named:  $_safety"
    echo "   See what is yours:   git -C \"$(pwd)\" log --oneline $_upstream..HEAD"
    echo ""
    echo "   Send that list to the kit maintainer, who can tell you which parts are already"
    echo "   upstream."
    [ -n "$CFG_SAVED" ] && cp "$CFG_SAVED" "$CFG" 2>/dev/null
    echo ""; read -n1 -s -p "Press any key to close."; echo; exit 1
  fi
  if [ -n "$_upstream" ] && ! git merge-base --is-ancestor HEAD "$_upstream" 2>/dev/null; then
    echo ""
    echo "ℹ  The kit's history was rewritten upstream, so a fast-forward is impossible."
    echo "   Re-syncing to the published version. Your documents/ folder is git-ignored and"
    echo "   is not touched; your scripts/kit_config.py is preserved."
    git reset --hard "$_upstream" || {
      echo "⚠  Re-sync failed. Nothing was changed."
      [ -n "$CFG_SAVED" ] && cp "$CFG_SAVED" "$CFG" 2>/dev/null
      echo ""; read -n1 -s -p "Press any key to close."; echo; exit 1; }
  else
    echo ""
    echo "⚠  Couldn't fast-forward, and your history is not behind the published one."
    echo "   That usually means you edited a file the kit also ships, so nothing was changed."
    echo "   Run this to see it:   git -C \"$(pwd)\" status"
    [ -n "$CFG_SAVED" ] && cp "$CFG_SAVED" "$CFG" 2>/dev/null
    echo ""; read -n1 -s -p "Press any key to close."; echo; exit 1
  fi
fi

# ── 4. Put your config back ───────────────────────────────────────────────────────────────────
if [ -n "$CFG_SAVED" ]; then
  cp "$CFG_SAVED" "$CFG"; rm -f "$CFG_SAVED"
  echo "  [ok] your scripts/kit_config.py (identity + deal-breakers) was preserved"
elif [ ! -f "$CFG" ] && [ -f "scripts/kit_config.example.py" ]; then
  cp scripts/kit_config.example.py "$CFG"
fi

# ── 5. Re-seed and UPGRADE ────────────────────────────────────────────────────────────────────
# install.sh re-seeds anything missing and also converges an existing install on the shipped
# doctrine: it refreshes the rulebook in documents/ and your live .claude/settings.json when they
# are older copies of what the kit ships, backing up anything it replaces to
# documents/.superseded/. It never touches your profile, logs, tracker or blocked list.
# Deliberately NOT duplicated here: install.sh owns that logic, so an older copy of THIS script
# still performs the upgrade correctly after it pulls.
bash install.sh .

# ── 6. How fresh is the network data? ─────────────────────────────────────────────────────────
# Informational tail: prompts loudly when there is no export yet (or a stale one), and names the
# next step (/level-network). An update must NEVER fail on it, hence the || true.
command -v python3 >/dev/null 2>&1 && python3 scripts/check_network_freshness.py || true

echo ""
echo "✅  You're on the latest version."
echo "    Your documents/, your logs and your tracker were not touched."
echo ""
read -n1 -s -p "Press any key to close."
echo
