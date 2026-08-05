#!/usr/bin/env python3
"""Employer → segment resolution: the worklist, and the ingest.

WHY THIS EXISTS. The people ranker's likely-boss band depends on whether a contact's employer
sits in one of YOUR segments, and the naive way to decide that is to read the COMPANY NAME.
Measured on a real network: 291 distinct employers, **282 unresolvable from the name alone**.
`Stripe` reads unknown. So does `PaymentVerse`, because `\\bpayments?\\b` wants a word boundary that
"PaymentVerse" does not give. Regex answers "does this company SAY what it does", which is not the
question.

The cache this fills (`documents/state/employer-segments.jsonl`) is append-only, dated and sourced,
newest row wins, and `contact_signals.segment_read` consults it BEFORE the name patterns. An
employer absent from it degrades to the old name read, so the cache is purely additive.

  worklist : print the employers the pool needs and the cache lacks, as JSON, for a resolver agent
  ingest   : merge a resolver's JSON back in, validating every row before it lands

⚖️ VALIDATION IS THE POINT OF THE INGEST STEP. A resolver is a language model reading company
websites, and this cache silently decides whether you send someone a hire-me ask. So a row
lands only with a segment from the closed vocabulary, a non-empty industry, and a source. Anything
else is rejected loudly rather than defaulted — a wrong band is worse than an absent one, because
absent falls back to "unknown" and keeps the band.
"""
import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contact_signals as cs   # noqa: E402

REPO = cs.REPO
CACHE = cs.EMPLOYER_CACHE
VALID = cs._VALID_SEGMENTS


def pool_employers():
    """Distinct employers across the rankable people pool, most-common first."""
    import collections
    import rank_criteria as rc
    ranked, _ = rc.rank_people(5000)
    counts = collections.Counter(
        (x.get("company") or "").strip() for x in ranked if (x.get("company") or "").strip())
    return counts


def _stale_not_found(row, after_days):
    """A not-found verdict AGES OUT rather than suppressing the employer forever.

    Suppressing permanently would make the cache a memory hole: a company that had no web presence
    in August because it was three months old never gets a second look. Re-emitting it every run
    would send the resolvers down the same dead ends daily. So: re-ask, but not soon."""
    if row.get("segment") != cs._NOT_FOUND:
        return False
    try:
        seen = date.fromisoformat(str(row.get("date") or "")[:10])
    except ValueError:
        return True                    # undated verdict is not a verdict we can age; re-ask
    return (date.today() - seen).days >= after_days


def cmd_worklist(args):
    have = cs.load_employer_cache()
    counts = pool_employers()
    todo = [{"employer": e, "people_in_pool": n}
            for e, n in counts.most_common()
            if cs._employer_key(e) not in have
            or _stale_not_found(have[cs._employer_key(e)], args.recheck_after)]
    if args.limit:
        todo = todo[:args.limit]
    if args.shard is not None:
        todo = [t for i, t in enumerate(todo) if i % args.shards == args.shard]
    print(json.dumps({"generated": str(date.today()), "cached": len(have),
                      "employers_in_pool": len(counts), "todo": todo}, indent=1))


def cmd_ingest(args):
    try:
        with open(args.path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"⛔ cannot read {args.path}: {exc}", file=sys.stderr)
        return 2
    rows = payload.get("employers") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        print("⛔ expected {\"employers\": [...]} or a bare list", file=sys.stderr)
        return 2
    good, bad = [], []
    for r in rows:
        if not isinstance(r, dict):
            bad.append((r, "not an object")); continue
        emp = (r.get("employer") or "").strip()
        seg = (r.get("segment") or "").strip()
        ind = (r.get("industry") or "").strip()
        src = (r.get("source") or "").strip()
        if not emp:
            bad.append((r, "no employer")); continue
        if seg not in VALID and seg != cs._NOT_FOUND:
            bad.append((emp, f"segment {seg!r} not in the closed vocabulary")); continue
        # A not-found verdict carries no industry BY DEFINITION — that is the whole content of the
        # finding. It still needs a source, because the source records where the search actually
        # looked, which is what makes the verdict auditable and re-runnable later.
        if not ind and seg != cs._NOT_FOUND:
            bad.append((emp, "no industry stated")); continue
        if not src:
            bad.append((emp, "no source — an unsourced band is a guess, "
                            "and an unsourced not-found is an untraceable dead end")); continue
        good.append({"employer": emp, "segment": seg, "industry": ind, "source": src,
                     "confidence": r.get("confidence") or "stated",
                     "note": r.get("note") or "", "date": str(date.today())})
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    if good and not args.dry_run:
        with open(CACHE, "a", encoding="utf-8") as fh:
            for g in good:
                fh.write(json.dumps(g, ensure_ascii=False) + "\n")
    print(f"{'would add' if args.dry_run else 'added'}: {len(good)}   rejected: {len(bad)}")
    for e, why in bad[:20]:
        print(f"   ⛔ {str(e)[:44]:<46} {why}")
    if good:
        import collections
        by = collections.Counter(g["segment"] for g in good)
        print("   " + "  ".join(f"{k}:{v}" for k, v in by.most_common()))
    return 0


def cmd_status(_args):
    have = cs.load_employer_cache()
    counts = pool_employers()
    import collections
    by = collections.Counter(r["segment"] for r in have.values())
    resolved = sum(1 for e in counts if cs._employer_key(e) in have)
    print(f"employers in pool: {len(counts)}   resolved: {resolved}   "
          f"unresolved: {len(counts) - resolved}")
    for k, v in by.most_common():
        print(f"   {k:<20} {v}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worklist", help="employers the pool needs and the cache lacks")
    w.add_argument("--limit", type=int, default=0)
    w.add_argument("--shard", type=int, default=None, help="0-based shard index")
    w.add_argument("--shards", type=int, default=1)
    w.add_argument("--recheck-after", type=int, default=90, metavar="DAYS",
                   help="re-ask about a not-found employer this many days after the verdict")
    w.set_defaults(fn=cmd_worklist)
    i = sub.add_parser("ingest", help="merge a resolver's JSON into the cache")
    i.add_argument("path")
    i.add_argument("--dry-run", action="store_true")
    i.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("status", help="cache coverage against the pool")
    s.set_defaults(fn=cmd_status)
    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
