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

# ── 2. Pull ───────────────────────────────────────────────────────────────────────────────────
if ! git pull --ff-only; then
  # A fast-forward can fail for two very different reasons, and they need opposite responses.
  # (a) HISTORY WAS REWRITTEN UPSTREAM. If published content ever has to be removed for real
  #     (an address, a name, anything that should not have shipped), the only honest fix is to
  #     rewrite and force-push, which changes every commit id. Your clone is then not "behind",
  #     it is on a history that no longer exists, and no fast-forward can ever succeed again.
  #     Recovering is safe here because everything of yours is either git-ignored (documents/,
  #     your profile, logs, tracker, résumés) or preserved above (scripts/kit_config.py).
  # (b) You edited a file the kit also ships. Then a reset WOULD lose your work, so stop instead.
  git fetch origin --quiet 2>/dev/null
  _upstream="$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || echo origin/main)"
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

# ── 3. Put your config back ───────────────────────────────────────────────────────────────────
if [ -n "$CFG_SAVED" ]; then
  cp "$CFG_SAVED" "$CFG"; rm -f "$CFG_SAVED"
  echo "  [ok] your scripts/kit_config.py (identity + deal-breakers) was preserved"
elif [ ! -f "$CFG" ] && [ -f "scripts/kit_config.example.py" ]; then
  cp scripts/kit_config.example.py "$CFG"
fi

# ── 4. Re-seed and UPGRADE ────────────────────────────────────────────────────────────────────
# install.sh re-seeds anything missing and also converges an existing install on the shipped
# doctrine: it refreshes the rulebook in documents/ and your live .claude/settings.json when they
# are older copies of what the kit ships, backing up anything it replaces to
# documents/.superseded/. It never touches your profile, logs, tracker or blocked list.
# Deliberately NOT duplicated here: install.sh owns that logic, so an older copy of THIS script
# still performs the upgrade correctly after it pulls.
bash install.sh .

echo ""
echo "✅  You're on the latest version."
echo "    Your documents/, your logs and your tracker were not touched."
echo ""
read -n1 -s -p "Press any key to close."
echo
