#!/bin/bash
# Daily wrapper for durability-check.sh (run by launchd com.<you>.jobsearch.durabilitycheck).
# Runs the read-only audit, appends a timestamped result to documents/durability-check.log,
# and keeps only the last ~200 lines. Exits non-zero if any layer is at risk (visible in the log).
set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}" || exit 1
LOG="documents/durability-check.log"

out="$(bash scripts/durability-check.sh 2>&1)"; code=$?
verdict=$([ "$code" = "0" ] && echo "PASS" || echo "AT-RISK")

{
  echo "===== $(date '+%Y-%m-%d %H:%M') · $verdict ====="
  # log only the headers + any '!' at-risk lines to stay compact; full run is reproducible on demand
  echo "$out" | grep -E "^[0-9]\.|  ! |All layers|One or more"
  echo
} >> "$LOG"

# prune to last 200 lines
tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
exit $code
