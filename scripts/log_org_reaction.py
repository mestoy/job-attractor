#!/usr/bin/env python3
"""log_org_reaction.py — capture the OWNER'S OWN WORDS about an organization, verbatim.

WHY THIS EXISTS. The operator's own framing, upstream, 2026-08-09: *"let's capture my thoughts on
each organization i review leading to a decision. just capture my responses and log to durable
storage. as we gather more data, we'll notice patterns to help make better decisions."*

⚖️ THIS IS NOT THE DECISION LEDGER, AND THE DIFFERENCE IS THE WHOLE POINT.
`documents/decision-ledger.jsonl` records WHICH OPTION he picked. It cannot tell you WHY, because a
picker label is the assistant's phrasing, not the owner's. This store holds the REASONING in their
own words, so a later pass can find the criteria they apply that nobody ever wrote down.

⭐ THE FIELD THAT MAKES IT WORTH KEEPING is `pipeline_read`: what the pipeline thought of the company
at the moment they ruled. The value of this corpus is the DIVERGENCE. On the entry that prompted it
upstream, the ranker had scored a company's AI feature list as `applied-ai` segment FIT, and the
owner read the same list as evidence the product was about to be commoditized. Same facts, opposite
conclusions. That gap is the signal; a store of verdicts alone would have recorded only "SKIP" and
lost it.

⛔ VERBATIM MEANS VERBATIM. Do not clean up, summarize or de-slop the owner's words. The corpus is
only useful if it holds what they said, hedges and asides included, because the hedges are where an
unstated criterion usually hides. Style checks do not apply to the `verbatim` field.

Usage:
    scripts/log_org_reaction.py --company "<Company>" --decision SKIP \\
        --verbatim "..." --stage "post-culture-peek" \\
        --pipeline-read "ranker scored the AI feature list as applied-ai segment fit" \\
        --criteria commoditization,product-moat --source "chat 2026-08-09"

    scripts/log_org_reaction.py --report        # frequency of criteria across the corpus

Stdlib only. Append-only; never rewrites a prior row.
"""
import argparse
import collections
import datetime
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(REPO, "documents", "org-reactions.jsonl")

DECISIONS = ["PURSUE", "SKIP", "BLOCK", "BOSS-HUNT", "DEFER", "REVISIT", "NOTE"]


def load(path=STORE):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                # A malformed line is preserved by being skipped, never rewritten.
                continue
    return rows


def report(path=STORE):
    rows = load(path)
    if not rows:
        print("org-reactions: empty. Nothing logged yet.")
        return 0
    print(f"org-reactions: {len(rows)} entr(ies) across "
          f"{len({r.get('company') for r in rows})} organization(s)\n")
    crit = collections.Counter(c for r in rows for c in (r.get("criteria") or []))
    dec = collections.Counter(r.get("decision") for r in rows)
    print("decisions:")
    for d, n in dec.most_common():
        print(f"  {n:3d}  {d}")
    print("\ncriteria invoked, most frequent first:")
    for c, n in crit.most_common():
        print(f"  {n:3d}  {c}")
    # The divergence view: entries where the owner's read and the pipeline's differed.
    div = [r for r in rows if r.get("pipeline_read")]
    if div:
        print(f"\n{len(div)} entr(ies) carry a pipeline read to compare against:")
        for r in div:
            print(f"  · {r.get('date')} {r.get('company')} → {r.get('decision')}")
            print(f"      pipeline: {r.get('pipeline_read')}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--company")
    ap.add_argument("--decision", choices=DECISIONS)
    ap.add_argument("--verbatim", help="HIS OWN WORDS, unedited")
    ap.add_argument("--stage", default="", help="where in the funnel he ruled")
    ap.add_argument("--pipeline-read", default="", dest="pipeline_read",
                    help="what the pipeline thought at that moment; this is the divergence field")
    ap.add_argument("--criteria", default="",
                    help="comma-separated tags for what he weighed, for aggregation")
    ap.add_argument("--source", default="", help="where the verbatim came from")
    ap.add_argument("--date", default=None)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--path", default=STORE, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    if a.report:
        return report(a.path)

    missing = [f for f in ("company", "decision", "verbatim") if not getattr(a, f)]
    if missing:
        print(f"🔴 missing required field(s): {', '.join('--' + m for m in missing)}", file=sys.stderr)
        print("   The verbatim is the point of this store. A row without his words is a verdict, "
              "and the decision ledger already holds those.", file=sys.stderr)
        return 2

    row = {
        "ts": datetime.datetime.now().astimezone().isoformat(),
        "date": a.date or datetime.date.today().isoformat(),
        "company": a.company,
        "decision": a.decision,
        "verbatim": a.verbatim,
        "stage": a.stage,
        "pipeline_read": a.pipeline_read,
        "criteria": [c.strip() for c in a.criteria.split(",") if c.strip()],
        "source": a.source,
    }
    os.makedirs(os.path.dirname(a.path), exist_ok=True)
    with open(a.path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"✅ logged: {a.company} → {a.decision}"
          + (f"  [{', '.join(row['criteria'])}]" if row["criteria"] else ""))
    if not a.pipeline_read:
        print("   ⚠️  no --pipeline-read given. The divergence between his read and the pipeline's "
              "is what makes this corpus worth keeping; add it when you know it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
