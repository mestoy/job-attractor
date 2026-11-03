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
4. For survivors (aim for ~3-5, quality over volume), print each as ONE fenced block, ```queue-entry ... ```, that starts with a "### Company" heading and carries a line "STATUS: NEW", then: company, boss if found, why-match, screen results, flags for you. No code fence and no other heading inside a block.
5. Print a one-line dated run summary as ONE fenced block, ```metrics-line ... ```, on a single line.
Do NOT contact anyone, send, apply, or open anything. You have NO file tools and NO shell: you cannot write or edit anything, and the wrapper that ran you appends your blocks to documents/outreach-queue.md and documents/outreach-metrics.md.'

GUARD='UNATTENDED PREP TASK — no human is present and you have NO shell/Bash. HARD RULES: you MUST NOT attempt to send, email, contact, connect, apply, or open anything (you have no way to, keep it that way). You ONLY research (WebSearch/WebFetch/Read/Grep/Glob) and PRINT review-ready entries as queue-entry blocks (STATUS: NEW) plus a one-line metrics-line block; the wrapper that ran you writes them. You are in a scratch folder that holds only the files you must read. Respect documents/blocked-employers-list.md and every hard filter. If unsure, put a NOTE line inside an entry rather than acting. You review everything when he returns.'

{
  echo "===== PREP RUN $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  # ── BUG-215 RUNTIME CEILING (mechanical). Abort before spending if the day is over budget; bound
  # the run with a hard --max-turns + a portable wall-clock watchdog; record usage from the stream.
  # No silent cap. The wall-clock is `runtime_budget run` (a stdlib process-group watchdog), NOT shell
  # `timeout` — macOS ships no `timeout`, so the old call exited 127 and never bounded the run.
  if ! python3 scripts/runtime_budget.py check prep; then
    echo "budget: daily cap reached — aborting prep (nothing spent)"
  else
    _MT="$(python3 scripts/runtime_budget.py max-turns)"
    _WALL="$(python3 scripts/runtime_budget.py wall-clock)"
    # ── BUG-218 follow-up (2026-09-09) parity with auto-sweep.sh. This script always had NO Bash
    # grant, but "WebFetch" with no domain restriction was a materially larger fetch surface than
    # auto-sweep.sh's own documented tradeoff — same allowlist rationale applies here: the ATS APIs,
    # LinkedIn, Crunchbase, Wikipedia, SEC EDGAR, nothing else. `--disallowedTools "Bash"` is added
    # explicitly too: the "VERIFIED-NOT-ENFORCED" finding was specifically about a granted pattern
    # being ignored, not about omission being unsafe, but relying on mere absence from --allowedTools
    # is the same class of assumption this whole fix exists to stop making on faith.
    # ── BUG-218 RE-ENABLE PLAN (63, 2026-10-28): no file tool of any kind, scratch working directory. Write, Edit,
    # MultiEdit and NotebookEdit join Bash in --disallowedTools, the agent prints queue-entry and metrics-line blocks,
    # and apply_findings_from_stream.py (this wrapper's own shell) appends them to the two fixed files. See auto-sweep.sh.
    SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/prep-scratch.XXXXXX")"
    STREAM="$(mktemp "${TMPDIR:-/tmp}/prep-stream.XXXXXX")"
    trap 'rm -rf "$SCRATCH" "$STREAM"' EXIT
    mkdir -p "$SCRATCH/documents"
    cp documents/blocked-employers-list.md documents/outreach-queue.md "$SCRATCH/documents/"
    cp WORKFLOW-RULES.md CLAUDE.md "$SCRATCH/"
    python3 scripts/runtime_budget.py run --wall "$_WALL" --run prep -- \
      bash -c 'cd "$1" && shift && exec "$@"' _ "$SCRATCH" "$CLAUDE" -p "$TASK" \
      --max-turns "$_MT" --output-format stream-json --verbose \
      --allowedTools "WebSearch" \
                     "WebFetch(domain:*.greenhouse.io)" "WebFetch(domain:*.ashbyhq.com)" \
                     "WebFetch(domain:*.lever.co)" \
                     "WebFetch(domain:linkedin.com)" "WebFetch(domain:*.linkedin.com)" \
                     "WebFetch(domain:crunchbase.com)" "WebFetch(domain:*.crunchbase.com)" \
                     "WebFetch(domain:en.wikipedia.org)" "WebFetch(domain:*.sec.gov)" \
                     "Read(./**)" "Grep(./**)" "Glob(./**)" \
      --disallowedTools "Bash" "Write" "Edit" "MultiEdit" "NotebookEdit" \
      --append-system-prompt "$GUARD" 2>&1 \
      | tee "$STREAM" \
      | python3 scripts/runtime_budget.py record-from-stream prep
    python3 scripts/apply_findings_from_stream.py "$STREAM" --queue-append documents/outreach-queue.md --metrics-append documents/outreach-metrics.md
  fi
  echo "===== END (exit $?) ====="
  echo
} >> "$LOG" 2>&1
