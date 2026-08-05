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
#       1. He has HELD the title (Product Owner, MERP Systems, CalPEST, Jan-2022 to Jun-2023), so an
#          IC PO req can be a DIRECT target, not merely a signal.
#       2. "Manager/Director OF Product Owners" is a high-quality boss-hunt tell: it means the org has
#          MULTIPLE POs, so there is a real product function with headcount and a product leader above
#          it. Perr & Knight surfaced exactly this way and produced Tigran Karsian.
#       3. The junior-PO risk needs no new filter — the $170K comp floor drops those mechanically.
#          Perr & Knight's Senior Manager of Product Owners posts at $160-200K.
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
# corner screened 0/8 on culture (Progyny/Rightway/Pair Team). Govtech queries take the public-sector.
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

run() {
  local seg="$1"; shift
  for q in "$@"; do
    echo "  · [$seg] $q" >&2
    bun run "$CLI" search -q "$q" --remote --limit 40 --format json 2>/dev/null \
      | python3 -c "
import json,sys
seg,q=sys.argv[1],sys.argv[2]
try: d=json.load(sys.stdin)
except Exception: raise SystemExit
for r in d.get('results',[]):
    r['segment']=seg; r['query']=q; print(json.dumps(r))
" "$seg" "$q" >> "$OUT"
    sleep 1
  done
}

: > "$OUT"
case "$SEG" in
  payments)           run payments "${payments[@]}" ;;
  applied-ai)         run applied-ai "${applied_ai[@]}" ;;
  ai-enablement)      run ai-enablement "${ai_enablement[@]}" ;;
  regulated-workflow) run regulated-workflow "${regulated_workflow[@]}" ;;
  govtech)            run govtech "${govtech[@]}" ;;
  all)
    run payments "${payments[@]}"
    run applied-ai "${applied_ai[@]}"
    run ai-enablement "${ai_enablement[@]}"
    run regulated-workflow "${regulated_workflow[@]}"
    run govtech "${govtech[@]}"
    ;;
  *) echo "unknown segment '$SEG' — one of: payments | applied-ai | ai-enablement | regulated-workflow | govtech | all" >&2; exit 2;;
esac

echo "✅ $(wc -l < "$OUT" | tr -d ' ') postings → $OUT" >&2
echo "   next: scripts/screen_sweep.py $OUT" >&2
