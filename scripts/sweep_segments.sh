#!/usr/bin/env bash
# sweep_segments.sh — segment-first discovery sweep via the hiring.cafe aggregator.
#
# WHY THIS EXISTS (2026-07-21). Discovery had been running by GUESSING company names and probing
# their ATS tokens. On 2026-07-21 that method probed ~34 companies and yielded ONE usable row, and I
# concluded from it that "cold discovery in these segments is exhausted." That conclusion was wrong:
# six queries through .agents/skills/hiring-cafe-search returned 141 companies, 118 with no prior
# record in the repo. The constraint was the CHANNEL, not the market. hiring.cafe indexes straight
# from company ATSes (Greenhouse/Ashby/Lever/iCIMS), so it sees the live-remote-PM population that
# token-guessing cannot enumerate.
#
# Segments come from documents/segments.md — the sweep is segment-first by construction, so it
# cannot re-create the clean-energy problem (9 sends into a lane that was a discovery artifact).
#
# Usage:  scripts/sweep_segments.sh [payments|applied-ai|ai-enablement|regulated-workflow|govtech|all]   (default: all)
# Output: JSONL to documents/sweep-<date>.jsonl, then run scripts/screen_sweep.py to filter.
#
# ⚠️ Personal use only, keep volume low (the skill's own terms). Queries are deliberately few and
# targeted rather than exhaustive paging.
set -euo pipefail
cd "$(dirname "$0")/.."

# ── A FAILING QUERY NEVER KILLS THE SWEEP (2026-09-14, pre-launch audit risk 5) ───────────────
# What it used to do: every CLI call was `bun run ... 2>/dev/null | python3 -c ...` under
# `set -euo pipefail`. Three things compounded. The pipeline's failure became the script's
# failure, `set -e` aborted immediately, and stderr had already been thrown away — so a missing
# bun or an HTTP 403 ended the sweep after ONE progress line with nothing said about why, and
# the caller saw an empty output file and no reason. There was also no retry and no bound on how
# long a call could take, so a hung request hung the whole run.
#
# Now: each call goes through cli_call(), which keeps stderr, bounds the call with `timeout`,
# backs off and retries the two answers that are worth retrying (429 slow down, 403 turned away),
# explains anything else in a sentence, and returns non-zero WITHOUT aborting. The sweep finishes
# and its last line says how many queries came back empty.
SWEEP_TIMEOUT="${SWEEP_TIMEOUT:-90}"   # seconds any ONE query may take before it is cut off
SWEEP_BACKOFF="${SWEEP_BACKOFF:-5}"    # base seconds between retries; multiplied by the attempt
SWEEP_TRIES="${SWEEP_TRIES:-3}"        # attempts per query, for a retryable answer only
SWEEP_PAUSE="${SWEEP_PAUSE:-1}"        # the standing courtesy pause between queries
SWEEP_ERR="$(mktemp -t sweep-err.XXXXXX)"
SWEEP_JSON="$(mktemp -t sweep-json.XXXXXX)"
SWEEP_FAILED=0

# kit#168/#172: stock macOS ships neither GNU `timeout` nor Homebrew coreutils' `gtimeout`, so
# `command -v timeout` failed and cli_call() fell to its unbounded `else` branch with NO message
# -- SWEEP_TIMEOUT silently did nothing on exactly the platform this kit targets. Resolved ONCE,
# not per call, and the warning fires ONCE (not once per query) if neither binary exists.
if command -v timeout >/dev/null 2>&1; then
  SWEEP_TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  SWEEP_TIMEOUT_BIN="gtimeout"
else
  SWEEP_TIMEOUT_BIN=""
  echo "⚠️  no timeout/gtimeout binary available — SWEEP_TIMEOUT (${SWEEP_TIMEOUT}s) is NOT" \
       "enforced; a hung call can run unbounded. Install coreutils (brew install coreutils)" \
       "for gtimeout." >&2
fi

sweep_why() {
  # One friendly sentence for a failed call: the exit code first, then what the CLI said.
  local rc="$1" tail_lines
  case "$rc" in
    127) echo "bun is not installed, so I could not search (install it from https://bun.sh)"
         return 0 ;;
    124|137) echo "the search took longer than ${SWEEP_TIMEOUT}s, so I gave up on it"
         return 0 ;;
  esac
  if grep -q "429" "$SWEEP_ERR" 2>/dev/null; then
    echo "the board asked me to slow down (HTTP 429)"; return 0
  fi
  if grep -q "403" "$SWEEP_ERR" 2>/dev/null; then
    echo "the board turned me away (HTTP 403 Forbidden)"; return 0
  fi
  tail_lines="$(tail -n 2 "$SWEEP_ERR" 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g; s/ *$//')"
  if [ -n "$tail_lines" ]; then
    echo "the search failed: $tail_lines"
  else
    echo "the search failed and said nothing about why (exit $rc)"
  fi
}

sweep_retryable() {
  # 403 is treated exactly like 429. Both are the board's answer to volume rather than a broken
  # query, and on this aggregator a 403 has been seen to clear on its own after a pause.
  grep -qE "429|403" "$SWEEP_ERR" 2>/dev/null
}

cli_call() {
  # cli_call <label> <command...>  → JSON on stdout. Never aborts the sweep.
  local label="$1"; shift
  local attempt=1 rc=0 wait why
  while : ; do
    : > "$SWEEP_ERR"
    rc=0
    if [ -n "$SWEEP_TIMEOUT_BIN" ]; then
      "$SWEEP_TIMEOUT_BIN" "$SWEEP_TIMEOUT" "$@" 2>"$SWEEP_ERR" || rc=$?
    else
      "$@" 2>"$SWEEP_ERR" || rc=$?
    fi
    [ "$rc" -eq 0 ] && return 0
    why="$(sweep_why "$rc")"
    if [ "$attempt" -lt "$SWEEP_TRIES" ] && sweep_retryable; then
      wait=$(( SWEEP_BACKOFF * attempt ))
      echo "  · [$label] $why — waiting ${wait}s and trying again" >&2
      [ "$wait" -gt 0 ] && sleep "$wait"
      attempt=$(( attempt + 1 ))
      continue
    fi
    echo "  · [$label] $why" >&2
    SWEEP_FAILED=$(( SWEEP_FAILED + 1 ))
    return 1
  done
}
CLI=".agents/skills/hiring-cafe-search/cli/src/cli.ts"
SEG="${1:-all}"
# FILENAME COLLISION FIXED 2026-07-21. This was date-only, so a SECOND sweep on the same day
# silently OVERWROTE the first. On 2026-07-21 that destroyed the morning sweep's output and the
# re-run was only caught because you said "these seem familiar" — git history then showed
# 363 of 364 companies were identical. A discovery artifact that overwrites its own predecessor
# makes duplicate work invisible, which is the expensive kind. Timestamped now.
OUT="documents/sweep-$(date +%Y-%m-%d-%H%M).jsonl"

# QUERY SET BROADENED 2026-07-21 (you: "we can also expand industries so we keep BANKED
# populated"; he ruled option A, broaden the QUERIES, and explicitly held option C, adding a fourth
# segment). The starvation was partly self-inflicted: 21 queries produced 187 distinct companies, and
# the pool ran dry after six warm asks burned three companies each. The three SEGMENTS are unchanged
# and still closed (documents/segments.md) — what widens is how many questions we ask inside them.
#
# Two axes added per segment:
#   • SENIORITY. Every original query said "product manager", so Senior/Staff/Principal/Lead/Director
#     and Group PM postings that never use the bare phrase were invisible. His band is Senior through
#     Principal ([[ic-track-preferred]]), so those titles are the ones most likely to clear the floor.
#   • ADJACENT VOCABULARY. Real postings in these lanes say "platform", "data platform", "payments
#     infrastructure", "risk", "underwriting", "provider data", "identity" — not the textbook term.
#   • PRODUCT OWNER (added 2026-07-21, your catch). Every query above says "product manager".
#     Whole industries title the same job PRODUCT OWNER — insurance, financial services, healthcare,
#     and anywhere SAFe/agile-at-scale took hold — so those orgs were invisible to the entire engine.
#     Three reasons this matters, and they are distinct:
#       1. An operator who has HELD the title (e.g. Product Owner, Example Systems Corp, a
#          representative state agency, Jan-2022 to Jun-2023) can treat an IC PO req as a DIRECT
#          target, not merely a signal.
#       2. "Manager/Director OF Product Owners" is a high-quality boss-hunt tell: it means the org has
#          MULTIPLE POs, so there is a real product function with headcount and a product leader above
#          it. A prior sweep surfaced exactly this way and produced a boss-hunt contact.
#       3. The junior-PO risk needs no new filter — the comp floor drops those mechanically.
#          A representative firm's Senior Manager of Product Owners posted at a comparable band.
#     Handling differs by shape: an IC PO req clearing comp = DIRECT target; a Manager/Director-of-POs
#     req = BOSS-HUNT signal, reach the product lead ([[unqualified-live-role-is-boss-hunt-signal]]).
payments=(
  "product manager payments" "product manager fintech" "product manager billing"
  "product manager accounts payable" "product manager banking" "product manager embedded finance"
  "product manager invoicing" "product manager lending"
  "senior product manager payments" "staff product manager payments" "principal product manager fintech"
  "product manager payments infrastructure" "product manager money movement" "product manager treasury"
  "product manager payouts" "product manager reconciliation" "product manager card issuing"
  "product manager merchant" "product manager subscriptions revenue" "product manager spend management"
  "product owner payments" "senior product owner fintech" "manager of product owners payments"
)
applied_ai=(
  "AI product manager" "product manager machine learning" "product manager LLM"
  "product manager document AI" "product manager fraud risk" "product manager AI evaluation"
  "senior product manager AI" "staff product manager AI" "principal product manager AI"
  "product manager AI agents" "product manager RAG" "product manager AI platform"
  "product manager data platform" "product manager search relevance" "product manager AI infrastructure"
  "product manager intelligent automation" "product manager AI safety" "product manager applied AI"
  "product owner AI" "senior product owner data" "manager of product owners"
)
regulated_workflow=(
  "product manager healthcare claims" "product manager compliance" "product manager interoperability"
  "product manager revenue cycle" "product manager prior authorization" "product manager insurance"
  "product manager government"
  "senior product manager healthcare" "staff product manager healthcare" "principal product manager compliance"
  "product manager provider data" "product manager credentialing" "product manager underwriting"
  "product manager claims automation" "product manager regulatory" "product manager identity verification"
  "product manager audit" "product manager public sector" "product manager benefits eligibility"
  "product owner insurance" "product owner healthcare" "senior product owner compliance"
  "manager of product owners insurance" "director of product owners"
)
# ── added 2026-07-22 (you added ai-enablement + govtech as segments) ──
# regulated_workflow is now RE-AIMED at insurance/legal/wealth — the health-benefits/care-delivery
# corner once screened 0 for 8 on culture. Govtech queries take the public-sector.
ai_enablement=(
  "product manager AI enablement" "product manager AI adoption" "product operations manager"
  "director of product operations" "head of AI enablement" "product manager developer experience"
  "product manager internal tools AI" "product manager AI productivity" "AI enablement lead"
  "senior product operations manager" "principal product manager platform enablement"
  "product manager AI transformation" "product manager knowledge management AI"
  "product manager sales enablement AI" "product owner AI enablement" "director product enablement"
)
govtech=(
  "product manager govtech" "product manager public sector" "product manager government"
  "product manager civic technology" "product manager digital government" "product manager state government"
  "senior product manager govtech" "principal product manager public sector"
  "product manager permitting" "product manager licensing" "product manager benefits eligibility"
  "product manager government modernization" "product manager citizen services" "product manager elections"
  "product owner government" "product owner public sector" "director of product government"
)

# ── WE WORK REMOTELY ────────────────────────────────────────────────────────────────────────────
# A second channel for the same sweep. The primary CLI indexes company ATSes, so it misses a board
# that companies post to directly, and the remote-only boards are where a fully distributed company
# advertises first. We Work Remotely publishes every category as public RSS, so this needs no login
# and no HTML scraping. Absent CLI = skipped silently, so the sweep still runs without it.
#
# ⚠️ ONE FETCH PER SWEEP, not one per query. The whole product feed is a few dozen postings and
# every query is answered from a cached copy ($WWR_CACHE). Asking the board a hundred times for the
# same rows would be rude and slower, and the board's own terms ask for low volume.
#
# Rows come out of the CLI already carrying the sweep's field names (id, title, company, location,
# workplaceType, date, salary, url, applyUrl), so segment and query are the only fields added here,
# the same two `run` adds. Nothing is filtered for seniority or comp: screen_sweep.py owns those
# gates for every source and filtering twice would hide rows from its report.
WWR_CLI=".agents/skills/weworkremotely-search/cli/src/cli.ts"
# mktemp TEMPLATE NEEDS ITS X's (fixed 2026-09-14, rehearsal red #2). `mktemp -t wwr-feed` is a
# BSD-ism that GNU coreutils rejects outright ("too few X's in template"), so on Linux this line
# failed, both variables came back empty, and the whole sweep died before its first query. The
# rehearsal hit it at this line on a never-installed Linux box.
WWR_CACHE="$(mktemp -t wwr-feed.XXXXXX)"
WWR_SEEN="$(mktemp -t wwr-seen.XXXXXX)"
trap 'rm -f "$WWR_CACHE" "$WWR_SEEN" "$SWEEP_ERR" "$SWEEP_JSON"' EXIT

run_wwr() {
  local seg="$1"; shift
  [ -f "$WWR_CLI" ] || return 0
  for q in "$@"; do
    cli_call "wwr/$seg" bun run "$WWR_CLI" search -q "$q" --us-only \
      --feed-cache "$WWR_CACHE" --format json > "$SWEEP_JSON" || { sleep "$SWEEP_PAUSE"; continue; }
    python3 -c "
import json,sys
seg,q,seen_path=sys.argv[1],sys.argv[2],sys.argv[3]
try: d=json.load(sys.stdin)
except Exception: raise SystemExit
seen=set(open(seen_path,encoding='utf-8').read().split())
out=[]
for r in d.get('results',[]):
    # One posting can answer several queries in the same sweep. Keep the first hit only, so a
    # company does not take two slots in the ranker.
    if r['id'] in seen: continue
    seen.add(r['id']); out.append(r['id'])
    r['segment']=seg; r['query']=q; print(json.dumps(r))
open(seen_path,'a',encoding='utf-8').write(''.join(i+'\n' for i in out))
" "$seg" "$q" "$WWR_SEEN" < "$SWEEP_JSON" >> "$OUT"
    sleep "$SWEEP_PAUSE"
  done
  echo "  · [wwr/$seg] done" >&2
}

run() {
  local seg="$1"; shift
  for q in "$@"; do
    echo "  · [$seg] $q" >&2
    cli_call "$seg" bun run "$CLI" search -q "$q" --remote --limit 40 --format json \
      > "$SWEEP_JSON" || { sleep "$SWEEP_PAUSE"; continue; }
    python3 -c "
import json,sys
seg,q=sys.argv[1],sys.argv[2]
try: d=json.load(sys.stdin)
except Exception: raise SystemExit
for r in d.get('results',[]):
    r['segment']=seg; r['query']=q; print(json.dumps(r))
" "$seg" "$q" < "$SWEEP_JSON" >> "$OUT"
    sleep "$SWEEP_PAUSE"
  done
}

: > "$OUT"
case "$SEG" in
  payments)           run payments "${payments[@]}"; run_wwr payments "${payments[@]}" ;;
  applied-ai)         run applied-ai "${applied_ai[@]}"; run_wwr applied-ai "${applied_ai[@]}" ;;
  ai-enablement)      run ai-enablement "${ai_enablement[@]}"; run_wwr ai-enablement "${ai_enablement[@]}" ;;
  regulated-workflow) run regulated-workflow "${regulated_workflow[@]}"; run_wwr regulated-workflow "${regulated_workflow[@]}" ;;
  govtech)            run govtech "${govtech[@]}"; run_wwr govtech "${govtech[@]}" ;;
  all)
    run payments "${payments[@]}"
    run applied-ai "${applied_ai[@]}"
    run ai-enablement "${ai_enablement[@]}"
    run regulated-workflow "${regulated_workflow[@]}"
    run govtech "${govtech[@]}"
    run_wwr payments "${payments[@]}"
    run_wwr applied-ai "${applied_ai[@]}"
    run_wwr ai-enablement "${ai_enablement[@]}"
    run_wwr regulated-workflow "${regulated_workflow[@]}"
    run_wwr govtech "${govtech[@]}"
    ;;
  *)
    # kit#167/#169: these five names are the OWNER'S OWN segments, hard-coded above. A partner's
    # real lanes live in their own kit_config.SEGMENTS (documents/segments.md derives from the
    # same source), already exposed via `kit_config.py --segment-queries <slug>` — the same
    # direct-call convention mail-draft.sh already uses for its own kit_config reads. Portable
    # array build (no `mapfile`/`readarray`: stock macOS bash is 3.2).
    _partner_queries=()
    while IFS= read -r _q; do
      [ -n "$_q" ] && _partner_queries+=("$_q")
    done < <(python3 scripts/kit_config.py --segment-queries "$SEG" 2>/dev/null || true)
    if [ "${#_partner_queries[@]}" -gt 0 ]; then
      run "$SEG" "${_partner_queries[@]}"
      run_wwr "$SEG" "${_partner_queries[@]}"
    else
      echo "unknown segment '$SEG' — one of: payments | applied-ai | ai-enablement | regulated-workflow | govtech | all, or one of your own kit_config.SEGMENTS slugs" >&2
      exit 2
    fi
    ;;
esac

if [ "$SWEEP_FAILED" -gt 0 ]; then
  echo "⚠️  $SWEEP_FAILED quer$([ "$SWEEP_FAILED" -eq 1 ] && echo y || echo ies) came back empty for the reasons above" >&2
fi
echo "✅ $(wc -l < "$OUT" | tr -d ' ') postings → $OUT" >&2
echo "   next: scripts/screen_sweep.py $OUT" >&2
