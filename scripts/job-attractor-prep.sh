#!/bin/bash
# Job Attractor — unattended PREP task (local replacement for the Cowork scheduled job).
# Runs headless Claude Code with NO shell access, so it can only research + draft into the
# review queue. It CANNOT send, email, connect, apply, or open anything. You review
# everything when he returns. Scheduled by ~/Library/LaunchAgents/com.<you>.jobattractor.prep.plist
set -uo pipefail

PROJECT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
CLAUDE="${CLAUDE_BIN:-$(command -v claude || echo "$HOME/.local/bin/claude")}"
LOG="$PROJECT/documents/prep-run.log"

cd "$PROJECT" || exit 1

TASK='Run the DISCOVERY + SCREENING prep task (prep-only, no human present).
1. Read documents/blocked-employers-list.md, WORKFLOW-RULES.md, CLAUDE.md, and the current documents/outreach-queue.md (what is already queued/blocked).
2. Discover a few NEW remote-US, PM-fit companies via WebSearch, biased to calm / bootstrapped / profitable / founder-stable orgs in his lanes (data infra, fintech/payments, healthtech, tech-for-good), per WORKFLOW-RULES.
3. Screen each in order, stopping at the first fail: (a) blocked-employers list -> skip if listed; (b) hard filters (permanent remote incl. FL, no required travel, deal-breaker industries, recurring layoffs, always-on, right-leaning politics); (c) culture/Glassdoor read. Drop failures WITH the reason.
4. For survivors (aim for ~3-5, quality over volume), append a review-ready entry to documents/outreach-queue.md marked STATUS: NEW: company, boss if found, why-match, screen results, flags for you.
5. Append a one-line dated run summary to documents/outreach-metrics.md.
Do NOT contact anyone, send, apply, or open anything. Do NOT edit outreach_log.md, job_search_tracker.csv, WORKFLOW-RULES.md, CLAUDE.md, or memory. Only write to documents/outreach-queue.md and documents/outreach-metrics.md.'

GUARD='UNATTENDED PREP TASK — no human is present and you have NO shell/Bash. HARD RULES: you MUST NOT attempt to send, email, contact, connect, apply, or open anything (you have no way to, keep it that way). You ONLY research (WebSearch/WebFetch/Read/Grep/Glob) and WRITE review-ready drafts into documents/outreach-queue.md (STATUS: NEW) plus a one-line summary in documents/outreach-metrics.md. NEVER edit outreach_log.md, job_search_tracker.csv, WORKFLOW-RULES.md, CLAUDE.md, documents/state/run-budget.jsonl (the runtime-budget ledger that enforces the daily cap), the ~/.claude memory store, or any file other than those two. Respect documents/blocked-employers-list.md and every hard filter. If unsure, write a NOTE in the queue rather than acting. You review everything when he returns.'

{
  echo "===== PREP RUN $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  # ── BUG-215 RUNTIME CEILING (mechanical). Abort before spending if the day is over budget; bound
  # the run with a hard --max-turns + wall-clock timeout; record usage from the stream. No silent cap.
  if ! python3 scripts/runtime_budget.py check prep; then
    echo "budget: daily cap reached — aborting prep (nothing spent)"
  else
    _MT="$(python3 scripts/runtime_budget.py max-turns)"
    _WALL="$(python3 scripts/runtime_budget.py wall-clock)"
    python3 scripts/runtime_budget.py run --wall "$_WALL" --run prep -- "$CLAUDE" -p "$TASK" \
      --max-turns "$_MT" --output-format stream-json --verbose \
      --allowedTools "WebSearch" "WebFetch" "Read" "Grep" "Glob" "Write" "Edit" \
      --append-system-prompt "$GUARD" 2>&1 \
      | python3 scripts/runtime_budget.py record-from-stream prep
  fi
  echo "===== END (exit $?) ====="
  echo
} >> "$LOG" 2>&1
