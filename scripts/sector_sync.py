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

Usage:
    python3 scripts/sector_sync.py DIR                 # dry run
    python3 scripts/sector_sync.py DIR --apply          # rewrite stat cores
"""
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)

SEGMENT_HEADER_RE = re.compile(r"^###\s+(.+?)\s*\(n=(\d+)\)\s*$", re.M)
STAT_ROW_RE = re.compile(
    r"^\|\s*(median|q1|q3)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|",
    re.M | re.I,
)
COMPANY_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|", re.M)

SECTOR_LINE_RE = re.compile(
    r"(Sector:[\*_\s]*)([\w-]+)(\s*\(n=)(\d+)([^)]*\)\s*[·&]\w*\s*median\s*)([\d.]+)"
    r"(\s*[·&]\w*\s*Q1\s*)([\d.]+)(\s*[·&]\w*\s*Q3\s*)([\d.]+)",
    re.I,
)
PER_SEAT_RE = re.compile(
    r"(per-seat medians CPO\s*)([\d.]+)(\s*/\s*CTO\s*)([\d.]+)(\s*/\s*CEO\s*)([\d.]+)", re.I
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
        if stats:
            out[_normalize_segment(seg_name)] = {"n": n, "companies": companies, **stats}
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
        # Also rewrite per-seat medians for whichever segment each Sector: line named.
        for m in SECTOR_LINE_RE.finditer(text):
            seg = baseline.get(_normalize_segment(m.group(2)))
            if seg:
                new_text = rewrite_per_seat(new_text, seg)
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
    args = ap.parse_args()

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
