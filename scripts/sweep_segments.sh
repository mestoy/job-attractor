#!/usr/bin/env bash
# sweep_segments.sh — segment-first discovery sweep via the hiring.cafe aggregator.
#
# WHAT IT DOES. For each of YOUR segments it runs that segment's queries through the
# hiring-cafe-search CLI, which indexes straight from company ATSes (Greenhouse/Ashby/Lever/
# iCIMS) and therefore sees the live-remote population that guessing-and-probing ATS tokens
# cannot enumerate. Every returned posting is tagged with the segment and query that surfaced
# it, then appended to a timestamped JSONL for the screen step.
#
# THE SEGMENTS ARE NOT HARDCODED HERE. They live in scripts/kit_config.py (SEGMENTS: a dict of
# slug -> list-of-queries), read at runtime, so this mechanism is identical for every kit owner
# and nothing about a particular job seeker is baked into the tooling. Edit your lanes there —
# see documents/segments.md for the discipline (send ~5 per segment, then compare reply rates;
# five labels inside one lane produce no comparison). The sweep is segment-first by construction,
# so it cannot manufacture a lane that was only ever a discovery artifact.
#
# Usage:  scripts/sweep_segments.sh [<segment-slug>|all]     (default: all)
#         Valid slugs:  python3 scripts/kit_config.py --segments
# Output: JSONL to documents/sweep-<date>-<HHMM>.jsonl, then run scripts/screen_sweep.py to filter.
#
# ⚠️ Personal use only, keep volume low (the search skill's own terms). Queries are deliberately
# few and targeted rather than exhaustive paging.
set -euo pipefail
cd "$(dirname "$0")/.."
CLI=".agents/skills/hiring-cafe-search/cli/src/cli.ts"
SEG="${1:-all}"

# FILENAME COLLISION FIX. Timestamp to the MINUTE, not the day. A date-only name let a SECOND
# sweep on the same day silently OVERWRITE the first, which makes duplicate work invisible — the
# expensive kind. With HHMM appended, two sweeps in one day keep two files.
OUT="documents/sweep-$(date +%Y-%m-%d-%H%M).jsonl"

# The segment slugs, READ FROM kit_config at runtime. bash 3.2-safe (macOS default): a while-read
# loop, not `mapfile`. Empty lines are skipped.
SLUGS=()
while IFS= read -r _s; do
  [ -n "$_s" ] && SLUGS+=("$_s")
done < <(python3 scripts/kit_config.py --segments)
if [ "${#SLUGS[@]}" -eq 0 ]; then
  echo "no segments defined — add some to SEGMENTS in scripts/kit_config.py" >&2
  exit 2
fi

# Run one segment: pull ITS queries from kit_config, then search each and tag the rows.
run_segment() {
  local seg="$1"
  local q
  local -a queries
  queries=()
  while IFS= read -r q; do
    [ -n "$q" ] && queries+=("$q")
  done < <(python3 scripts/kit_config.py --segment-queries "$seg")
  if [ "${#queries[@]}" -eq 0 ]; then
    echo "  ⚠️  [$seg] no queries in kit_config.py — skipping" >&2
    return
  fi
  for q in "${queries[@]}"; do
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
if [ "$SEG" = "all" ]; then
  for _seg in "${SLUGS[@]}"; do
    run_segment "$_seg"
  done
else
  _ok=0
  for _seg in "${SLUGS[@]}"; do
    [ "$_seg" = "$SEG" ] && _ok=1
  done
  if [ "$_ok" -ne 1 ]; then
    echo "unknown segment '$SEG' — one of: ${SLUGS[*]} | all" >&2
    echo "   (segments come from SEGMENTS in scripts/kit_config.py)" >&2
    exit 2
  fi
  run_segment "$SEG"
fi

echo "✅ $(wc -l < "$OUT" | tr -d ' ') postings → $OUT" >&2
echo "   next: scripts/screen_sweep.py $OUT" >&2
