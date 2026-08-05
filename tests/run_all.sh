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

fingerprint() {
  python3 - "$REPO" <<'PY'
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
PY
}

BEFORE="$(fingerprint)"
python3 -m unittest discover -s tests -p 'test_*.py' -v
RC=$?
AFTER="$(fingerprint)"

if [ "$BEFORE" != "$AFTER" ]; then
  echo ""
  echo "🔴 LIVE-STORE DRIFT — a test wrote into your real data:"
  diff <(printf '%s\n' "$BEFORE") <(printf '%s\n' "$AFTER") | sed 's/^/   /'
  echo "   This is a defect even if every assertion passed. Restore the file above, then report it"
  echo "   through documents/partner-feedback.md so the isolation gets fixed upstream."
  exit 1
fi

exit "$RC"
