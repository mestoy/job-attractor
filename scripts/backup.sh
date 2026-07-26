#!/usr/bin/env bash
# backup.sh — snapshot your job-search work. PORTABLE (no absolute paths, works in any clone).
#
# Two safety nets, because your private working data and the shared tooling live differently:
#   1) Your PRIVATE data lives in the git-ignored documents/ (profile, outreach log, résumés,
#      blocked list). It is never pushed to the shared kit repo, so a git push does NOT protect it.
#      This makes a local timestamped snapshot of documents/ — that is your real backup.
#   2) Your tracked customizations (kit_config.py, any edits) are committed and pushed IF you have a
#      writable remote of your own (a fork). A read-only clone can't push; the local snapshot covers you.
#
# Run it from anywhere inside your kit repo:  bash scripts/backup.sh
set -e
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

# 0) mirror the assistant's memory store into the repo so the snapshot and the commit capture it.
# Without this step, durability-check.sh section 4 reports "memory drift" on every run forever and
# tells you to run THIS script to fix it, which did nothing about memory. An instruction that
# cannot resolve the warning it prints trains people to ignore the whole report. Override the
# location with JOBSEARCH_MEMORY_DIR if your assistant stores memory elsewhere.
_MEMSLUG="$(printf '%s' "$ROOT" | tr '/' '-')"
MEM="${JOBSEARCH_MEMORY_DIR:-$HOME/.claude/projects/$_MEMSLUG/memory}"
if [ -d "$MEM" ]; then
  mkdir -p _memory-backup
  cp "$MEM"/*.md _memory-backup/ 2>/dev/null || true
  echo "[ok] memory store mirrored to _memory-backup/"
fi

# 1) local snapshot of the private, git-ignored working data (the real safety net)
if [ -d documents ]; then
  SNAP="../job-kit-backup-$(date +%Y-%m-%d-%H%M)"
  mkdir -p "$SNAP" && cp -R documents "$SNAP/" 2>/dev/null \
    && echo "[ok] private documents/ snapshotted to $SNAP"
fi

# 2) commit tracked changes; push only if a writable remote exists
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  git add -A && git commit -q -m "backup $(date '+%Y-%m-%d %H:%M')" && echo "[ok] committed tracked changes."
else
  echo "[ok] no tracked changes since last backup."
fi
if git push -q 2>/dev/null; then
  echo "[ok] pushed to your remote."
else
  echo "[i] no push (read-only clone or offline) — your local documents/ snapshot above is your backup."
fi
