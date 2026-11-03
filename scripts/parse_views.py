#!/usr/bin/env python3
"""parse_views.py — capture "Who viewed your profile" into an append-only store (BUG-181 WU-4).

WHY THIS EXISTS (2026-08-13). LinkedIn's connections export (`Connections.csv`) carries NO viewers —
the "Who viewed your profile" PAGE does, and nothing in the pipeline reads it. So a Founder and a CPO
who viewed the profile last week cannot appear anywhere in the ranking of who to contact, because the
signal was never captured. This is the ingest that captures it.

⚠️ A SURFACE, NEVER A SCORED TERM. The ranker prints a profile-view as a reason line, exactly the way
`nonus_tell` and the title-freshness note are printed: a fact placed where the human decides, not a
weight that reorders anyone. It stays a surface until it clears its own outcome join at n≥15
([[validate-a-signal-against-outcomes-before-scoring-it]]). This script only WRITES the store.

⛔ IDEMPOTENT, BATCH-KEYED (kit issue #36's lesson: a paste-in ingest that is re-run must add ZERO
rows). Every row's identity is `norm(name) | view_date-or-batch`. Re-ingesting the same paste — the
normal thing a human does when unsure whether it took — appends nothing. The batch label (default:
today) stands in for the date when a pasted row carries none, so re-running the SAME batch is a no-op
while a genuinely new batch is admitted.

INPUT. One viewer per line, CSV / TSV / pipe-delimited, columns in order:

    name, title, company, view_date

A header row (any line whose first cell is "name") is honored and may reorder the columns. `view_date`
is optional per row; when absent the batch label supplies it. Read from `--csv PATH` or from stdin, so
the human pastes the table straight in:

    pbpaste | scripts/parse_views.py --batch 2026-08-13
    scripts/parse_views.py --csv /tmp/views.csv

The store is `documents/state/profile-views.jsonl`, append-only, one JSON row per line, newest wins.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import date

REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(REPO, "documents", "state", "profile-views.jsonl")

# ⛔ THE ONE contact key. Identical to contact_signals.norm and rank_criteria's inline
# `re.sub(r"[^a-z0-9]", "", ...)` — a second spelling silently splits the join the ranker uses to put
# a badge on the right row. Kept local so the ingest has no import dependency and runs in a bare tree.
def _norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _row_key(name, view_date, batch):
    """A row's identity for dedup. The date (or, absent one, the caller-controlled batch) is part of
    it so the SAME person viewing on two different days is two events, but a re-paste of one batch is
    not."""
    return f"{_norm(name)}|{(view_date or batch or '').strip()}"


# The header names that map a column to a field. Anything else in a header row is ignored, and a
# file with no header falls back to positional order (name, title, company, view_date).
_FIELDS = {
    "name": "name", "viewer": "name",
    "title": "title", "headline": "title", "role": "title",
    "company": "company", "employer": "company", "organization": "company",
    "date": "view_date", "view_date": "view_date", "viewed": "view_date", "viewed_on": "view_date",
    "when": "view_date",
}
_ORDER = ["name", "title", "company", "view_date"]


def _split(line):
    """Split one input line on the delimiter it actually uses. Pipe first (LinkedIn copy-paste and the
    repo's own markdown tables use it), then tab, then comma via the csv module so a quoted comma in a
    title does not shatter the row."""
    if "|" in line:
        return [c.strip() for c in line.split("|")]
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in next(csv.reader(io.StringIO(line)))]


def parse_rows(text, batch=""):
    """[{name,title,company,view_date}] from pasted/CSV text. Blank lines and pure-punctuation table
    rules (|---|---|) are skipped. A header row remaps the columns; without one, positional order."""
    rows, colmap = [], None
    for raw in text.splitlines():
        line = raw.strip().strip("﻿")
        if not line:
            continue
        cells = _split(line)
        # A markdown table rule row ("| --- | --- |") carries no data.
        if cells and all(re.fullmatch(r"[-:\s]*", c) for c in cells):
            continue
        low0 = re.sub(r"[^a-z_ ]", "", (cells[0] or "").lower()).strip().replace(" ", "_")
        if colmap is None and low0 in ("name", "viewer"):
            colmap = []
            for c in cells:
                key = re.sub(r"[^a-z_ ]", "", (c or "").lower()).strip().replace(" ", "_")
                colmap.append(_FIELDS.get(key))
            continue
        vals = colmap if colmap else _ORDER
        rec = {"name": "", "title": "", "company": "", "view_date": ""}
        for i, field in enumerate(vals):
            if field and i < len(cells):
                rec[field] = cells[i].strip()
        if not rec["name"]:
            continue
        if not rec["view_date"]:
            rec["view_date"] = batch
        rows.append(rec)
    return rows


def load_keys(path=STORE):
    """The set of row keys already in the store, for the dedup. {} when the store does not exist."""
    keys = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("key"):
                    keys.add(row["key"])
    except OSError:
        pass
    return keys


def ingest(rows, batch="", path=STORE, ingested_on=None):
    """Append only rows whose key is not already present. Returns (new_rows, dup_count)."""
    ingested_on = ingested_on or str(date.today())
    existing = load_keys(path)
    new, dups = [], 0
    seen = set()
    for rec in rows:
        key = _row_key(rec["name"], rec.get("view_date"), batch)
        if key in existing or key in seen:
            dups += 1
            continue
        seen.add(key)
        new.append({"name": rec["name"].strip(), "title": rec.get("title", "").strip(),
                    "company": rec.get("company", "").strip(),
                    "view_date": (rec.get("view_date") or batch).strip(),
                    "batch": batch, "key": key, "ingested_on": ingested_on})
    if new:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for row in new:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return new, dups


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="", help="a file to read; omitted = read the paste from stdin")
    ap.add_argument("--batch", default="", help="batch label (default: --date or today). Part of a "
                                                "row's identity when the row itself carries no date.")
    ap.add_argument("--date", default="", help="ingest date stamped on the rows, YYYY-MM-DD; today by default")
    ap.add_argument("--dry-run", action="store_true", help="parse and report, write nothing")
    a = ap.parse_args()

    batch = a.batch or a.date or str(date.today())
    if a.csv:
        with open(a.csv, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()
    rows = parse_rows(text, batch=batch)
    if not rows:
        print("⚪ no viewer rows parsed. Expected one viewer per line: name, title, company, [date].",
              file=sys.stderr)
        return 1

    if a.dry_run:
        existing = load_keys()
        would_new = sum(1 for r in rows if _row_key(r["name"], r.get("view_date"), batch) not in existing)
        print(f"dry-run: {len(rows)} parsed · {would_new} new · {len(rows) - would_new} already on file")
        for r in rows:
            print("  " + json.dumps(r, ensure_ascii=False))
        return 0

    new, dups = ingest(rows, batch=batch, ingested_on=a.date or str(date.today()))
    print(f"✅ profile-views: {len(rows)} parsed · {len(new)} new · {dups} already on file "
          f"(batch {batch}) → {os.path.relpath(STORE, REPO)}")
    for r in new:
        print(f"   👀 {r['name']} — {r['title'] or '?'} @ {r['company'] or '?'} ({r['view_date']})")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
