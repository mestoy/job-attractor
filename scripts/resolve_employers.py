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
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contact_signals as cs   # noqa: E402

REPO = cs.REPO
CACHE = cs.EMPLOYER_CACHE
VALID = cs._VALID_SEGMENTS


# #33: a source must be a CITATION, not a bare assertion. cmd_ingest used to accept any non-empty
# source, so unsourced rows like "web search" or "well-known company" sat at the top evidence tier
# next to a row citing the company's own site, letting an unsourced guess put an employer on the
# board. A citation points somewhere retrievable that is not a bare web domain: a recorded ruling
# (wikilink), an ISO-ish date (a dated ruling or filing), or a named authoritative source.
_NOT_FOUND_TOKENS = {"not-found", "not found", "notfound"}
_URL_RE = re.compile(r"https?://|\b[a-z0-9][a-z0-9-]*\.[a-z]{2,}\b", re.I)
# A hedge is the tell that the source is a belief, not a citation. Checked BEFORE the URL match so a
# guess cannot smuggle itself past the gate by name-dropping any word.tld token
# ("google.com search results say...", "I think acme.com might be..., not confirmed").
_HEDGE_RE = re.compile(
    r"\b(web|internet|online|a\s+quick)\s+search\b|\b(google|bing|duckduckgo|yahoo)\b"
    r"|\bwell[-\s]?known\b|\b(general|common|public|widely|prior|background|domain|my)\s+knowledge\b"
    r"|\bcommon\s+sense\b|\beveryone\s+knows\b|\bbased\s+on\s+the\s+name\b|\bmy\s+training\b"
    r"|\bi\s+(think|believe|assume|guess|reckon)\b|\bassum(e|es|ed|ing|ption)\b"
    r"|\bpresum(e|es|ed|ing|ption|ably)\b|\bguess(ed|ing)?\b|\b(not|un)[\s-]?confirmed\b"
    r"|\bunverified\b|\bnot\s+sure\b|\bmaybe\b|\bmight\s+be\b|\bmay\s+be\b|\blikely\b|\bprobably\b"
    r"|\bappears?\s+to\s+be\b|\bmade\s+up\b|\bfabricat|\binvent(ed|ing)?\b|\bmaking\s+it\s+up\b",
    re.I,
)
# The source IS a domain (optionally labelled or with a path), as opposed to prose that merely names
# one. Anchored end to end so "google.com search results say..." (trailing prose) does not match.
_BARE_DOMAIN_RE = re.compile(
    r"^\s*(source:\s*|site:\s*|via\s+|from\s+|see\s+|at\s+)?(https?://)?(www\.)?"
    r"[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)*\.[a-z]{2,}(/\S*)?\s*$",
    re.I,
)
# Locator tokens (a URL, a wikilink, or a domain), removed before the hedge check so a hedge word
# INSIDE a locator ("https://guess.com") is ignored while a hedge floating in the PROSE around a
# locator ("I think it is https://sec.gov/x, not confirmed") still rejects.
_LOCATOR_STRIP_RE = re.compile(
    r"https?://\S+|\[\[[^\]]*\]\]|\b[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)*\.[a-z]{2,}(/\S*)?",
    re.I,
)
_CITATION_RE = re.compile(
    r"\b(19|20)\d{2}[-/]\d{1,2}\b"                        # an ISO-ish date: 2026-08-12
    r"|\b(10[- ]?[kq]|8[- ]?k|s[- ]?1|sec|edgar|prospectus|annual report|press release|"
    r"newsroom|filing|crunchbase|pitchbook|linkedin|glassdoor|wikipedia|careers page)\b",
    re.I,
)


def _source_is_cited(src):
    """True only when `src` POSITIVELY looks like a citation: an explicit not-found, a URL or bare
    domain, or a named document/ruling (a wikilink, a dated ruling/filing, or an authoritative
    source name).

    Default is REJECT, matching this file's own rule that a wrong band is worse than an absent one:
    an absent row falls back to the name read, while a bare assertion cached at the top tier corrupts
    the board. #33 showed that blocklisting assertion phrases is defeated by any lead-in or article
    ("Based on web search", "a well-known company"), so this requires a locator rather than
    enumerating the ways a guess can be phrased.
    """
    s = (src or "").strip()
    if not s:
        return False
    low = s.lower()
    if low in _NOT_FOUND_TOKENS:
        return True
    # Hedge is judged on the prose with locator tokens removed, so a hedge floating around a locator
    # rejects while a hedge word inside a hostname does not.
    if _HEDGE_RE.search(_LOCATOR_STRIP_RE.sub(" ", low)):
        return False
    # A locator: a NON-EMPTY recorded-ruling wikilink whose content is not itself a bare hedge word
    # ("[[maybe]]" is a placeholder, not a ruling), a URL, or a source that IS a bare domain.
    _wl = re.search(r"\[\[([^\]]+)\]\]", s)
    if _wl and not _HEDGE_RE.search(_wl.group(1).lower()):
        return True
    if re.search(r"https?://\S", low):
        return True
    if _BARE_DOMAIN_RE.match(s):
        return True
    # A named authoritative source or a dated ruling, with no hedge in the prose.
    if _CITATION_RE.search(s):
        return True
    return False


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
        if not _source_is_cited(src):
            bad.append((emp, f"source {src!r} is not a citation — a bare assertion is not a "
                            "source; cite a URL, a named document, or not-found")); continue
        # BUG-001: country is OPTIONAL and free text on purpose — only ever feeds a printed
        # surface (nonus_tell), never a score or a filter. Left "" when a resolver did not look it
        # up; that degrades to prior suffix-guess behavior, never a false claim.
        good.append({"employer": emp, "segment": seg, "industry": ind, "source": src,
                     "confidence": r.get("confidence") or "stated",
                     "country": (r.get("country") or "").strip(),
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
