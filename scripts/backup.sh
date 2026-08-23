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

# ── PII HARD GATE before any push to your WRITABLE fork (P0-1). Your private working data (contacts,
# bosses, thread text) lives in this tree; a bare push would send whatever `git add -A` caught to your
# fork with NO scan. Refuse the push if the gate finds PII (exit 3) OR cannot build a trustworthy
# vocabulary (exit 2 = a fresh/empty install: configure your identity + contact stores first, so the
# gate knows whose PII to look for). Fail CLOSED: the local commit + documents/ snapshot above still
# protect you; only the PUSH is withheld until the tree is clean.
#
# ⛔ kit#61: THIS USED TO BE `--scan "$_ROOT"` — the WHOLE WORKING TREE, every run, forever. On a
# real install that is not a push guard, it is a permanent lock: the operator's own résumé (their
# own name, the expected content of a résumé) and the memory store mirrored into the tracked
# `_memory-backup/` a few lines above BOTH sit in that tree on every single run, so every push was
# withheld regardless of what the push actually added — including a push whose entire diff was pure
# kit plumbing with zero personal content (the issue's own repro).
#
# `--push-guard` asks the right question instead: does THIS push's diff add a THIRD PARTY's PII.
# Resolve the writable remote/branch FIRST (moved up from below), so the gate can diff against what
# is ALREADY on that remote — nothing already published there needs to block a push again. A fresh
# fork with nothing pushed yet has no such ref; diff against git's empty-tree constant instead, so
# EVERYTHING in HEAD is treated as new on a first push, which is the correct and safe default.
_BR="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
if git remote get-url origin >/dev/null 2>&1; then
  _PUSH_REMOTE="origin"
else
  _PUSH_REMOTE="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null | cut -d/ -f1)"
fi

_PG="$(dirname "$0")/pii_gate.py"
if [ -f "$_PG" ]; then
  _ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
  if [ -n "$_PUSH_REMOTE" ] && [ -n "$_BR" ] && \
     git rev-parse --verify -q "${_PUSH_REMOTE}/${_BR}" >/dev/null 2>&1; then
    _PG_BASE="${_PUSH_REMOTE}/${_BR}"
  else
    _PG_BASE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"   # git's empty-tree constant
  fi
  # An explicit, LOGGED override for the case where the operator has judged a flagged finding
  # acceptable (kit#61 suggestion 6). Never silent: pii_gate.py appends the overridden findings to
  # documents/state/pii-gate-overrides.jsonl before proceeding. Third-party PII still blocks
  # underneath this — the override is the operator's call to make, on the record, not the gate's.
  _PG_OVERRIDE=""
  if [ "${PII_GATE_OVERRIDE:-}" = "1" ]; then
    _PG_OVERRIDE="--override"
  fi
  if python3 "$_PG" --push-guard --repo "$_ROOT" --base "$_PG_BASE" \
       --remote "${_PUSH_REMOTE:-origin}" --quiet $_PG_OVERRIDE; then
    echo "[ok] PII gate clean (scanned the push diff)."
  else
    echo "[!] ⛔ PUSH WITHHELD by the PII gate. Nothing was pushed to your fork." >&2
    echo "    A commit being pushed adds a name/email/phone/address the gate doesn't recognize as" >&2
    echo "    your own. Remove it, or if you've judged it acceptable, re-run with:" >&2
    echo "        PII_GATE_OVERRIDE=1 bash scripts/backup.sh" >&2
    echo "    (this is logged to documents/state/pii-gate-overrides.jsonl, never silent). Your" >&2
    echo "    local commit and the documents/ snapshot above still protect your work." >&2
    exit 3
  fi
else
  echo "[!] pii_gate.py not found next to backup.sh — refusing to push unscanned. Restore it and re-run." >&2
  exit 3
fi

# Push to a WRITABLE remote. A bare `git push` aims at the branch's UPSTREAM, and in the kit's
# two-remote layout (origin = your writable fork, a shared read-only upstream you cloned from) `main`
# tracks the READ-ONLY upstream after a sync — so a bare push fails EVERY time, and the old message
# blamed "read-only clone or offline" when your own fork was one correct push away. `_PUSH_REMOTE`
# and `_BR` were already resolved above, for the PII gate's diff base.
if [ -z "$_PUSH_REMOTE" ] || [ -z "$_BR" ] || [ "$_BR" = "HEAD" ]; then
  echo "[i] no writable remote (or a detached HEAD) — your local documents/ snapshot above is your backup."
elif _perr="$(git push -q "$_PUSH_REMOTE" "$_BR" 2>&1)"; then
  echo "[ok] pushed $_BR to '$_PUSH_REMOTE'."
else
  echo "[!] push of $_BR to '$_PUSH_REMOTE' FAILED. Your local documents/ snapshot above still" >&2
  echo "    protects you, but tracked changes are NOT on the remote. Reason:" >&2
  printf '%s\n' "$_perr" | sed 's/^/    /' | head -3 >&2
fi

# 📝 GIT NOTES DO NOT TRAVEL WITH A NORMAL PUSH, and that silence is the whole problem.
# Notes live under refs/notes/commits, which `git push` never includes, so a note stays on the
# machine that wrote it while the commit it annotates sits on the remote without it.
# 🔴 WHY THIS MATTERS MORE THAN IT SOUNDS. A note is how you correct a commit message you cannot
# amend because it is already pushed. If the note never travels, the remote keeps the wrong claim
# and the retraction is invisible to everyone but you. A correction nobody can read is not a
# correction.
# ⚖️ Its own line, and NEVER fatal: most repos have no notes, and one that does not must not fail a
# backup over it. The failure branch is LOUD on purpose, because silence is the failure mode.
if [ -n "$_PUSH_REMOTE" ] && git rev-parse --quiet --verify refs/notes/commits >/dev/null 2>&1; then
  if git push -q "$_PUSH_REMOTE" refs/notes/commits 2>/dev/null; then
    echo "[ok] pushed git notes (corrections attached to commits) to '$_PUSH_REMOTE'."
  else
    echo "[!] git notes push to '$_PUSH_REMOTE' failed. Any correction you attached is still LOCAL ONLY."
  fi
fi
