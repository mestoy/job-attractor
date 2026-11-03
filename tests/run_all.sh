#!/usr/bin/env bash
# Run the kit's regression suite. Standard library only, no install step, no network.
#   bash tests/run_all.sh
# Exit 0 = green. Run it after editing anything under scripts/, and before trusting a gate again.
#
# 🔴 IT ALSO FINGERPRINTS YOUR LIVE STORES AND FAILS IF A TEST TOUCHED THEM (added 2026-08-05).
# This guard exists upstream and was missing from the shipped copy, which is how the following
# reached a partner install: running the suite appended fake SENT rows to `outreach_log.md`, and
# `check_followups.py` then reported follow-ups overdue on people nobody had written to.
#
# ⚠️ IT IS INVISIBLE WITHOUT THIS CHECK. `outreach_log.md` is git-ignored, so `git status` stays
# clean while the corruption grows on every run. A suite that quietly edits the data it exists to
# protect is worse than no suite, because the green result is what you trust afterwards.
#
# ⛔ If this fires, the defect is the TEST'S ISOLATION, not your data. Restore the named file and
# report it upstream rather than deleting the check.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
GUARD_DIR="$REPO/tests"   # where _tree_guard.py lives: the fingerprint reads the ONE exemption set from it (BUG-733 slice 2, C3)

# Temp hygiene (kit issue #137). /tmp is RAM here and on small partner machines -- a suite that
# leaves its temp dirs behind is spending RAM, not disk, and a big enough leak OOM-kills whatever
# else is running (it took down live sessions overnight, 2026-09-14: 3.5 G across 19,507 entries).
# Give the run its own folder under the REPO (never /tmp) so a leak here costs repo-local disk,
# never shared RAM, and remove that folder on exit -- pass, fail, or interrupt -- via a trap.
# A caller-supplied TMPDIR (a harness that already scoped one, or the per-user folder macOS sets for every
# login) is the PARENT of this run's folder and is never removed: the run makes its own mktemp -d inside it
# and tears down only that inner folder at exit. (It used to rm -rf the caller's TMPDIR itself, which on a Mac
# deleted the user's whole per-user temp folder.)
_ja_tmp_base="${TMPDIR:-$REPO/.test-tmp}"
mkdir -p "$_ja_tmp_base" || { echo "🔴 could not create TMPDIR at $_ja_tmp_base"; exit 1; }
_ja_run_dir="$(mktemp -d "$_ja_tmp_base/run-XXXXXX")" || { echo "🔴 could not create a run folder under $_ja_tmp_base"; exit 1; }
TMPDIR="$_ja_run_dir"
export TMPDIR
_ja_cleanup_tmpdir() {
  # Only the folder this script made itself is ever removed; the caller's TMPDIR (its parent) is never named here.
  [ -n "${_ja_run_dir:-}" ] && [ -d "$_ja_run_dir" ] && rm -rf "$_ja_run_dir"
}
trap _ja_cleanup_tmpdir EXIT

# Dry-run hook for tests/test_test_hygiene.py: prove the TMPDIR setup/trap above in isolation,
# without paying for a full `unittest discover` (hundreds of tests, real seconds) on every check.
if [ "${JA_RUN_ALL_TMPDIR_ONLY:-}" = "1" ]; then
  echo "TMPDIR=$TMPDIR"
  exit "${JA_RUN_ALL_TMPDIR_ONLY_EXIT:-0}"
fi

# A clean clone (a fork, or the Actions runner) has no scripts/kit_config.py, because that file is
# git-ignored and holds one person's values. Every test that imports it would error before its
# first assertion, and the red check would look like the contributor's fault. Seed it from the
# shipped example so the suite exercises the defaults. Added 2026-09-05 after a clean-clone run
# showed 56 red of 832 for this reason alone.
if [ ! -f "$REPO/scripts/kit_config.py" ] && [ -f "$REPO/scripts/kit_config.example.py" ]; then
  cp "$REPO/scripts/kit_config.example.py" "$REPO/scripts/kit_config.py"
  echo "ℹ️  scripts/kit_config.py was absent; seeded it from kit_config.example.py for this run."
fi

fingerprint() {
  python3 - "$REPO" "${GUARD_DIR:-$REPO/tests}" <<'PY'
import sys, os, hashlib
repo = sys.argv[1]
for rel in ("documents/send-log.jsonl", "outreach_log.md", "documents/contact-closeness.json",
            "documents/decision-ledger.jsonl", "job_search_tracker.csv",
            "documents/green-board.md", "prospect_queue.md"):
    p = os.path.join(repo, rel)
    if os.path.exists(p):
        print(f"{rel} {hashlib.sha256(open(p,'rb').read()).hexdigest()[:16]}")
    else:
        print(f"{rel} MISSING")

# The enumerated list above misses anything new — which is how weights-derive.json and
# company.jsonl fixture rows drifted clean (kit #37). Walk ALL of documents/ recursively too (BUG-733 slice 2: it was documents/state/ only,
# so a new file under documents/outbox/ or documents/*.md went unseen), so a test can never invent a new live-store file that this guard has
# no name for.
# weights-derive.json is a WITNESS file: it rewrites its own last_run stamp on every ranking derivation by design (see
# rank_criteria._stamp_derivation), so it must never feed this guard. The exemption set is defined ONCE, in tests/_tree_guard.py, and read
# here, so this fingerprint and the atexit guard can never disagree.
os.environ["JA_TREE_GUARD_ROOT"] = repo      # importing the module installs its exit check; point it at the tree being fingerprinted
sys.path.insert(0, sys.argv[2])
from _tree_guard import EXEMPT as IGNORE_FILES
docs_dir = os.path.join(repo, "documents")
if os.path.isdir(docs_dir):
    for root, dirs, files in os.walk(docs_dir):
        dirs.sort()
        for name in sorted(files):
            p = os.path.join(root, name)
            rel = os.path.relpath(p, repo)
            if rel in IGNORE_FILES:
                continue
            print(f"{rel} {hashlib.sha256(open(p,'rb').read()).hexdigest()[:16]}")
else:
    print("documents/ MISSING")
PY
}

BEFORE="$(fingerprint)"
python3 -m unittest discover -s tests -p 'test_*.py' -v
RC=$?
AFTER="$(fingerprint)"

# check_tokens.py: hygiene report only, plan step 8. Its own exit code is ignored --
# it always returns 0 by design ("hygiene, never a release gate") -- so it can never
# affect $RC, only print its per-file counts after the real test run.
if [ -f scripts/check_tokens.py ]; then
  echo ""
  python3 scripts/check_tokens.py || true
fi

if [ "$BEFORE" != "$AFTER" ]; then
  echo ""
  echo "🔴 LIVE-STORE DRIFT — a test wrote into your real data:"
  diff <(printf '%s\n' "$BEFORE") <(printf '%s\n' "$AFTER") | sed 's/^/   /'
  echo "   This is a defect even if every assertion passed. Restore the file above, then report it"
  echo "   through documents/partner-feedback.md so the isolation gets fixed upstream."
  exit 1
fi

exit "$RC"
