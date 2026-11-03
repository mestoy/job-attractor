#!/usr/bin/env python3
"""sector_sync.py — keep every card's/HTML's Sector: line's STAT CORE in sync with the
latest sector-score-baseline-*.md, per sector-line-sync-plan-53-2026-09-09.md.

WHY. c9 found sector lines go stale on every card addition — a new card's baseline
refresh doesn't propagate to every sibling card's own Sector: line, so n/median/Q1/Q3
drift out of date across the whole segment.

WHAT THIS TOUCHES, AND WHAT IT DOESN'T. A sector line has a stable STAT CORE
(n=/median/Q1/Q3/per-seat medians — pure baseline lookups, always safe to rewrite) and a
DESCRIPTIVE CLAUSE that is sometimes a mechanical "ranks N of M (mean X)" sentence and
sometimes hand-written free prose naming another company or a ⚠️ warning about a
segment's own ceiling changing. This script ONLY ever rewrites the stat core. The
descriptive clause is never touched, never regenerated, never deleted — per the plan's
own finding that a naive full-line rewrite would silently destroy real analysis.

Dry-run by default (prints what would change). --apply writes the stat-core rewrite.
Refuses --apply outright if any scored card's company is missing from the baseline
entirely (the baseline itself can lag a same-day card addition).

BUG-256 (2026-09-10): --apply's own refusal above was correct behavior but had no way
out — nothing built the baseline file in the first place, so a stale/incomplete
baseline could block --apply indefinitely. --refresh-baseline (below) closes that: it
scans every scored card, groups by segment, and writes a brand-new dated baseline file
(never mutates an existing one, same as every other record this pipeline keeps). Also
BUG-256: the descriptive clause's mechanical "ranks N of M (mean Z)" form is no longer
frozen forever the way the module docstring above describes for hand-written prose —
`rewrite_rank_clause` (below, called from `sync_tree`, never from `rewrite_stat_core`)
recomputes it against the baseline's own per-company means and the card's own CURRENT
mean, so a re-panel's new rank/mean propagates the same way n=/median/Q1/Q3 already did.
`rewrite_stat_core` itself is untouched by this — it still only ever rewrites the stat
core, exactly as the module docstring says.

Usage:
    python3 scripts/sector_sync.py DIR                    # dry run
    python3 scripts/sector_sync.py DIR --apply             # rewrite stat cores + rank clause
    python3 scripts/sector_sync.py DIR --refresh-baseline  # write a new dated baseline, exit
"""
import argparse
import datetime
import glob
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

SEGMENT_HEADER_RE = re.compile(r"^###\s+(.+?)\s*\(n=(\d+)\)\s*$", re.M)
STAT_ROW_RE = re.compile(
    r"^\|\s*(median|q1|q3)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|",
    re.M | re.I,
)
COMPANY_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|", re.M)
# Company table row's own Mean column (5th cell: Company|CPO|CTO|CEO|Mean|...), needed to
# compute "ranks N of M" against the baseline's real per-company distribution rather than
# just knowing which company names exist (COMPANY_ROW_RE, above, only ever needed that).
COMPANY_MEAN_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*[\d.]+\s*\|\s*[\d.]+\s*\|\s*[\d.]+\s*\|\s*([\d.]+)\s*\|", re.M
)

SECTOR_LINE_RE = re.compile(
    r"(Sector:[\*_\s]*)([\w-]+)(\s*\(n=)(\d+)([^)]*\)\s*[·&]\w*\s*median\s*)([\d.]+)"
    r"(\s*[·&]\w*\s*Q1\s*)([\d.]+)(\s*[·&]\w*\s*Q3\s*)([\d.]+)",
    re.I,
)
PER_SEAT_RE = re.compile(
    # BUG-256: `[\d.]+` on the CEO group greedily ate a trailing sentence period as part of
    # the number (a real line ends "... / CEO 73.") -- tightened to a real-number shape on
    # all three groups so a following "." is never mistaken for part of the score.
    r"(per-seat medians CPO\s*)(\d+(?:\.\d+)?)(\s*/\s*CTO\s*)(\d+(?:\.\d+)?)"
    r"(\s*/\s*CEO\s*)(\d+(?:\.\d+)?)", re.I
)
RANK_CLAUSE_RE = re.compile(
    r"(this card ranks\s*)(\d+)(\s*of\s*)(\d+)(\s*\(mean\s*)([\d.]+)(\))", re.I
)
# Recognized reasons a card carries no panel score ON PURPOSE (transcribed from the
# hand-built 2026-09-08 baseline's own "Method" section) -- anything that reduces to
# neither "has a score" nor one of these matches goes to needs-manual-review instead of
# being silently guessed into or out of the numbers (BUG-256, e4's stop condition).
OUT_OF_SCOPE_RE = re.compile(
    r"stopping here per the recipe|no panel,?\s*no card|not a boss-hunt vector|"
    r"panel[- ]scoring methodology", re.I
)


def latest_baseline_path(state_dir):
    paths = sorted(glob.glob(os.path.join(state_dir, "sector-score-baseline-*.md")))
    return paths[-1] if paths else None


def _normalize_segment(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_baseline(path):
    """{normalized_segment: {"n": int, "median": float, "q1": float, "q3": float,
    "cpo_median": float, "cto_median": float, "ceo_median": float, "companies": set}}"""
    text = open(path, encoding="utf-8").read()
    headers = list(SEGMENT_HEADER_RE.finditer(text))
    out = {}
    for i, m in enumerate(headers):
        seg_name, n = m.group(1), int(m.group(2))
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]
        stats = {}
        for row_m in STAT_ROW_RE.finditer(block):
            kind = row_m.group(1).lower()
            mean, cpo, cto, ceo = (float(row_m.group(k)) for k in (2, 3, 4, 5))
            if kind == "median":
                stats["median"], stats["cpo_median"], stats["cto_median"], stats["ceo_median"] = (
                    mean, cpo, cto, ceo
                )
            elif kind == "q1":
                stats["q1"] = mean
            elif kind == "q3":
                stats["q3"] = mean
        companies = set()
        for row_m in COMPANY_ROW_RE.finditer(block):
            cell = row_m.group(1).strip()
            if cell and cell.lower() not in ("stat", "company") and not re.fullmatch(r"[-\s]+", cell):
                companies.add(cell)
        company_means = []
        # The Stat table (min/q1/median/q3/max/mean rows) has the same 5-pipe-column shape
        # as the Company table, so COMPANY_MEAN_RE matches both -- exclude the stat labels
        # themselves, not just the two literal header words, or a segment's own median row
        # is silently read back as a fictional "company" named "median".
        _stat_labels = ("stat", "company", "min", "q1", "median", "q3", "max", "mean")
        for row_m in COMPANY_MEAN_RE.finditer(block):
            cell = row_m.group(1).strip()
            if cell and cell.lower() not in _stat_labels and not re.fullmatch(r"[-\s]+", cell):
                company_means.append((cell, float(row_m.group(2))))
        if stats:
            out[_normalize_segment(seg_name)] = {
                "n": n, "companies": companies, "company_means": company_means, **stats
            }
    return out


def find_sector_lines(text):
    """[(match_object, matched_text)] for every Sector: line's stat-core match."""
    return list(SECTOR_LINE_RE.finditer(text))


def rewrite_stat_core(text, baseline):
    """(new_text, changes) — changes is a list of (segment, old, new) tuples describing
    what was rewritten. Only the n=/median/Q1/Q3 numbers and the per-seat medians are
    ever replaced; everything else in the line (segment name, descriptive clause, any
    trailing ⚠️ note) is left byte-for-byte untouched."""
    changes = []

    def repl(m):
        seg_key = _normalize_segment(m.group(2))
        seg = baseline.get(seg_key)
        if not seg:
            return m.group(0)  # unknown segment, leave untouched
        old = m.group(0)
        new = (
            f"{m.group(1)}{m.group(2)}{m.group(3)}{seg['n']}{m.group(5)}{seg['median']:g}"
            f"{m.group(7)}{seg['q1']:g}{m.group(9)}{seg['q3']:g}"
        )
        if new != old:
            changes.append((m.group(2), old, new))
        return new

    text = SECTOR_LINE_RE.sub(repl, text)

    # Per-seat medians: rewrite independently, matched against whichever segment the
    # nearest preceding Sector: line named (best-effort — same line in every real card).
    def repl_seats(m):
        return m.group(0)  # placeholder; seat rewrite done per-segment below via caller

    return text, changes


def rewrite_per_seat(text, seg):
    def repl(m):
        old = m.group(0)
        new = (f"{m.group(1)}{seg['cpo_median']:g}{m.group(3)}{seg['cto_median']:g}"
               f"{m.group(5)}{seg['ceo_median']:g}")
        return new if seg else old
    return PER_SEAT_RE.sub(repl, text)


def _extract_card_mean(text):
    """The card's own CURRENT mean -- header `panel N/N/N ... mean X` wins when present
    (board.py already trusts this field; it's the one thing this pipeline keeps in sync on
    every re-panel). Falls back to render_scorecard.py's own body-Panel-section extraction
    when the header carries no panel/mean field at all.

    BUG-256: a naive whole-body search for "mean" is not safe here. A re-panelled card can
    carry an OLD mean in its own ruling prose describing the score BEFORE the re-panel
    (Sibol GRC, confirmed live: header reads "mean 74.7", the ruling paragraph above it
    quotes the prior "mean 76" score as history) -- that prose sits earlier in the body
    than the real Score-history table, so a body-wide search would grab the stale number.
    The header field is the one place this codebase already keeps unambiguously current."""
    import board as _board
    lines = text.splitlines()
    if lines:
        head = _board.parse_header(lines[0])
        if head.get("seats") and head.get("mean") is not None:
            return head["mean"]
    import render_scorecard as _render_scorecard
    parsed = _render_scorecard._extract_panel_scores(text)
    return parsed[1] if parsed else None


def rewrite_rank_clause(text, seg, company, card_mean, changes):
    """Rewrite 'this card ranks N of M (mean Z)' against the baseline's own per-company
    means for this segment and the card's own current mean. Never called from
    `rewrite_stat_core` -- that function's contract (module docstring, and its own test)
    is that it NEVER touches the descriptive clause. This is a separate rewrite, applied
    only from `sync_tree`, so a hand-written free-prose descriptive clause (no "ranks N of
    M" shape at all) is left untouched exactly as before -- the regex simply won't match."""
    if seg is None or card_mean is None:
        return text
    # Same fuzzy prefix match `_company_known` already uses -- a filename-derived company
    # guess routinely drops a suffix a baseline's full name carries ("Fictional Fabrics"
    # vs. "Fictional Fabrics Co"), and a strict `!=` here would fail to exclude the card's
    # own (possibly stale) baseline row from its own rank comparison.
    want = _normalize_segment(company)
    others = [
        v for c, v in seg.get("company_means") or []
        if not (_normalize_segment(c).startswith(want) or want.startswith(_normalize_segment(c)))
    ]
    rank = 1 + sum(1 for v in others if v > card_mean)
    total = seg["n"]

    def repl(m):
        old = m.group(0)
        new = f"{m.group(1)}{rank}{m.group(3)}{total}{m.group(5)}{card_mean:g}{m.group(7)}"
        if new != old:
            changes.append(("rank", old, new))
        return new

    return RANK_CLAUSE_RE.sub(repl, text)


def _segment_tag(raw):
    """The baseline's own convention: 'segment normalized to the first tag before any / or
    parenthetical' (2026-09-08 baseline, "Method"). E.g. "regulated-workflow (no-code
    GRC/audit/risk)" -> "regulated-workflow"."""
    return re.split(r"[/(]", raw.strip())[0].strip()


def _quartiles(vals):
    """(q1, median, q3) via Tukey hinges — median of the lower/upper half (excluding the
    overall median on an odd-length list), never interpolated."""
    s = sorted(vals)
    n = len(s)
    med = statistics.median(s)
    if n < 2:
        return med, med, med
    mid = n // 2
    lower = s[:mid]
    upper = s[mid + 1:] if n % 2 else s[mid:]
    return (statistics.median(lower) if lower else med, med, statistics.median(upper) if upper else med)


def _stats_row(vals):
    q1, median, q3 = _quartiles(vals)
    return {"min": min(vals), "q1": q1, "median": median, "q3": q3, "max": max(vals),
            "mean": statistics.mean(vals)}


def build_baseline(state_dir):
    """(segments, excluded, needs_review). segments: {seg_tag: [{"company","cpo","cto",
    "ceo","mean","date"}, ...]}. excluded: [(company, reason)] -- confidently out of scope,
    a recognized signal matched. needs_review: [(path, company)] -- no detectable score AND
    no recognized out-of-scope signal; NEVER silently included or dropped (BUG-256, e4's
    stop condition: a card that doesn't reduce to has-a-score-or-not, and isn't obviously
    out of scope, gets flagged for a human, not guessed in either direction)."""
    import board as _board
    import render_scorecard as _render_scorecard
    paths = sorted(glob.glob(os.path.join(state_dir, "*-card-*.md")))
    segments = {}
    excluded = []
    needs_review = []
    for path in paths:
        base = os.path.basename(path)
        if any(tag in base for tag in _board.NOT_A_CARD):
            excluded.append((base, "not a company-fit card (calibration/call/template)"))
            continue
        text = open(path, encoding="utf-8", errors="ignore").read()
        lines = text.splitlines()
        if not lines:
            continue
        head = _board.parse_header(lines[0])
        company = head.get("company") or _company_from_filename(path)
        seats, mean = None, None
        if head.get("seats") and head.get("mean") is not None:
            seats, mean = head["seats"], head["mean"]
        else:
            parsed = _render_scorecard._extract_panel_scores(text)
            if parsed:
                seats, mean = parsed
        if seats is None or mean is None:
            m = OUT_OF_SCOPE_RE.search(text)
            if m:
                excluded.append((company, m.group(0)))
            else:
                needs_review.append((path, company))
            continue
        seg_tag = _segment_tag(head.get("segment") or "") or "unsegmented"
        segments.setdefault(seg_tag, []).append({
            "company": company, "cpo": float(seats[0]), "cto": float(seats[1]),
            "ceo": float(seats[2]), "mean": float(mean), "date": head.get("date") or "",
        })
    return segments, excluded, needs_review


def render_baseline_markdown(segments, excluded, needs_review, as_of):
    lines = [
        f"# Sector score baseline, {as_of} (auto-refreshed by sector_sync.py --refresh-baseline)",
        "",
        "Auto-generated from every scored `*-card-*.md` under this state directory. A "
        "card's own header `panel N/N/N ... mean X` field wins when present (kept current "
        "on every re-panel); falls back to `render_scorecard.py`'s own body Panel-section "
        "extraction when the header carries no panel/mean field. A card with no detectable "
        "score is either EXCLUDED (a recognized out-of-scope signal matched) or flagged "
        "NEEDS MANUAL REVIEW (no recognized signal) — never silently guessed into or out "
        "of the numbers below.",
        "",
    ]
    if needs_review:
        lines.append(f"## Needs manual review ({len(needs_review)})")
        lines.append("")
        for path, company in needs_review:
            lines.append(f"- {company} (`{os.path.basename(path)}`) — no detectable score, "
                          f"no recognized out-of-scope signal.")
        lines.append("")
    if excluded:
        lines.append(f"## Excluded, out of scope ({len(excluded)})")
        lines.append("")
        for company, reason in excluded:
            lines.append(f"- {company} — {reason}")
        lines.append("")
    lines.append("---")
    lines.append("")
    total = sum(len(v) for v in segments.values())
    lines.append(f"**{total} scored companies across {len(segments)} segment tag(s)** as of {as_of}.")
    lines.append("")
    for seg_tag in sorted(segments):
        rows = segments[seg_tag]
        title = seg_tag[:1].upper() + seg_tag[1:] if seg_tag else seg_tag
        lines.append(f"### {title} (n={len(rows)})")
        lines.append("")
        means = [r["mean"] for r in rows]
        cpos = [r["cpo"] for r in rows]
        ctos = [r["cto"] for r in rows]
        ceos = [r["ceo"] for r in rows]
        mean_stats, cpo_stats = _stats_row(means), _stats_row(cpos)
        cto_stats, ceo_stats = _stats_row(ctos), _stats_row(ceos)
        lines.append("| Stat | Mean | CPO | CTO | CEO |")
        lines.append("|---|---|---|---|---|")
        for stat in ("min", "q1", "median", "q3", "max", "mean"):
            lines.append(f"| {stat} | {mean_stats[stat]:g} | {cpo_stats[stat]:g} | "
                          f"{cto_stats[stat]:g} | {ceo_stats[stat]:g} |")
        lines.append("")
        median = mean_stats["median"]
        lines.append("| Company | CPO | CTO | CEO | Mean | Date | vs median |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in sorted(rows, key=lambda r: -r["mean"]):
            vs = "at" if r["mean"] == median else ("above" if r["mean"] > median else "below")
            lines.append(f"| {r['company']} | {r['cpo']:g} | {r['cto']:g} | {r['ceo']:g} | "
                          f"{r['mean']:g} | {r['date']} | {vs} |")
        lines.append("")
    return "\n".join(lines)


def refresh_baseline(state_dir, as_of=None):
    as_of = as_of or datetime.date.today().isoformat()
    segments, excluded, needs_review = build_baseline(state_dir)
    text = render_baseline_markdown(segments, excluded, needs_review, as_of)
    out_path = os.path.join(state_dir, f"sector-score-baseline-{as_of}.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return out_path, segments, excluded, needs_review


def _company_from_filename(path):
    base = os.path.basename(path)
    base = re.sub(r"-card-\d{4}-\d{2}-\d{2}\.md$", "", base)
    base = re.sub(r"-\d{4}-\d{2}-\d{2}\.html$", "", base)
    return base.replace("-", " ").title()


def _company_known(company, baseline):
    want = _normalize_segment(company)
    for seg in baseline.values():
        for c in seg["companies"]:
            if _normalize_segment(c).startswith(want) or want.startswith(_normalize_segment(c)):
                return True
    return False


def sync_tree(state_dir, baseline, apply=False):
    """Returns (touched_files, missing_companies). missing_companies is populated
    whenever a scored card's company isn't found anywhere in the baseline — --apply
    refuses if this is non-empty."""
    targets = sorted(glob.glob(os.path.join(state_dir, "*-card-*.md"))) + \
        sorted(glob.glob(os.path.join(state_dir, "scorecards", "*.html")))
    touched = []
    missing = []
    for path in targets:
        text = open(path, encoding="utf-8").read()
        if "Sector:" not in text:
            continue
        company = _company_from_filename(path)
        if not _company_known(company, baseline):
            missing.append((path, company))
            continue
        new_text, changes = rewrite_stat_core(text, baseline)
        card_mean = _extract_card_mean(text)
        # Also rewrite per-seat medians, and (BUG-256) the "ranks N of M (mean Z)" clause,
        # for whichever segment each Sector: line named.
        for m in SECTOR_LINE_RE.finditer(text):
            seg = baseline.get(_normalize_segment(m.group(2)))
            if seg:
                new_text = rewrite_per_seat(new_text, seg)
                new_text = rewrite_rank_clause(new_text, seg, company, card_mean, changes)
        if changes:
            touched.append((path, changes))
            if apply:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new_text)
    return touched, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state_dir")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--baseline", default=None, help="override: path to a specific baseline file")
    ap.add_argument("--refresh-baseline", action="store_true",
                     help="write a new dated sector-score-baseline-*.md from every scored "
                          "card under state_dir and exit; never mutates an existing baseline")
    args = ap.parse_args()

    if args.refresh_baseline:
        out_path, segments, excluded, needs_review = refresh_baseline(args.state_dir)
        total = sum(len(v) for v in segments.values())
        print(f"wrote {out_path} ({total} scored compan{'y' if total == 1 else 'ies'} "
              f"across {len(segments)} segment(s))")
        if excluded:
            print(f"   {len(excluded)} card(s) excluded, out of scope")
        if needs_review:
            print(f"⚠️  {len(needs_review)} card(s) need manual review (no detectable "
                  f"score, no recognized out-of-scope signal):")
            for path, company in needs_review:
                print(f"   {os.path.basename(path)}  ({company})")
        return 0

    baseline_path = args.baseline or latest_baseline_path(args.state_dir)
    if not baseline_path:
        print(f"⛔ no sector-score-baseline-*.md found under {args.state_dir}", file=sys.stderr)
        return 2
    baseline = parse_baseline(baseline_path)
    print(f"baseline: {baseline_path} ({len(baseline)} segment(s))")

    touched, missing = sync_tree(args.state_dir, baseline, apply=False)

    if missing:
        print(f"⛔ {len(missing)} scored card(s) whose company is not in the baseline at all:")
        for path, company in missing:
            print(f"   {os.path.basename(path)}  (company guessed: {company!r})")
        if args.apply:
            print("⛔ REFUSED --apply: fix the missing companies above (or refresh the "
                  "baseline) before syncing everyone else against a baseline that doesn't "
                  "yet know about them.", file=sys.stderr)
            return 2

    if not touched:
        print("nothing to sync — every sector line's stat core already matches the baseline")
        return 0

    for path, changes in touched:
        print(f"{'APPLIED' if args.apply else 'DRY-RUN'} {os.path.basename(path)}:")
        for seg, old, new in changes:
            print(f"   [{seg}] {old}\n        -> {new}")

    if args.apply:
        # Re-run to actually write.
        sync_tree(args.state_dir, baseline, apply=True)
        print(f"applied to {len(touched)} file(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
