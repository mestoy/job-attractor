#!/usr/bin/env python3
"""Slice 1 gate (plan-praise-explanation-cli-first): a praise-backfill row's WHY is recorded, sourced and honest.

    python3 scripts/check_praise_why.py [--repo DIR]     (read-only; checks every documents/state/praise-backfill-*.json)

A row with none of why / why_quote / why_url / mirror is "why owed" and passes. A row with any of them must carry all four
on a FULL praise record (value and url present), and:
  - why_url is https; why_quote is a substring of documents/state/praise-pages/<slug>.txt (whitespace collapsed);
  - the why names a term the value lacks, and under 60% of its tokens appear in the value (not a restated press release);
  - mirror is "none yet" or EQUALS one whole sentence or bullet of 01-candidate-profile.md (normalized: lowercase,
    punctuation stripped, whitespace collapsed), never a fragment;
  - the CLAUDE.md honesty denylist finds nothing in mirror or why.
Exits 1 on any problem, and on a repo with no backfill files (an empty check passes nothing)."""
import glob
import json
import os
import re
import sys

WHY_FIELDS = ("why", "why_quote", "why_url", "mirror")
PROFILE = os.path.join(".claude", "skills", "job-application-assistant", "01-candidate-profile.md")
DENYLIST = [
    (r"98\s*%", "98%"),
    (r"analyzer[^.\n]{0,80}\d+(\.\d+)?\s*%|\d+(\.\d+)?\s*%[^.\n]{0,40}analyzer", "TO Analyzer accuracy %"),
    (r"39\s*m(illion)?\s+users", "39M users"),
    (r"adopted\s+company-?\s*wide", "adopted company-wide"),
    (r"\b(is|am|as|was|a)\s+an?\s+(software\s+)?engineer\b|engineering\s+background|background\s+in\s+engineering", "engineer as background"),
    (r"\b(earned|holds?|completed|graduated)\b[^.\n]{0,30}\bdegree\b|\b(bachelor|master)'?s\b", "a degree"),
    (r"secured[^.\n]{0,40}sbir|sbir[^.\n]{0,40}secured", "SBIR secured"),
]
STOP = set("a an the of to in on for and or but is are was were be it its with that this as at by from not no".split())


def norm(s):
    s = re.sub(r"[^\w\s]", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def tokens(s):
    return [t for t in norm(s).split() if t not in STOP]


def profile_units(repo):
    """Every whole line (bullet or paragraph) and every sentence of the profile, normalized."""
    path = os.path.join(repo, PROFILE)
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None
    units = set()
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", line.replace("**", "")).strip()
        if not line:
            continue
        units.add(norm(line))
        for sent in re.split(r"(?<=[.!?])\s+", line):
            units.add(norm(sent))
    units.discard("")
    return units


def check_row(row, repo):
    """Problems (a list of strings) for one {slug, praise} row."""
    probs = []
    slug = row.get("slug") if isinstance(row, dict) else None
    praise = row.get("praise") if isinstance(row, dict) else None
    where = "slug %r" % slug
    if isinstance(row, dict) and any(k in row for k in WHY_FIELDS):
        return ["%s: why fields sit outside the praise record" % where]
    if not isinstance(praise, dict):
        return []
    have = [k for k in WHY_FIELDS if praise.get(k)]
    if not have:
        return []
    if not (praise.get("value") and praise.get("url")):
        probs.append("%s: a why-only row; repeat the full praise record (value, url) beside the why" % where)
    for k in WHY_FIELDS:
        if k not in have:
            probs.append("%s: %s missing; why, why_quote, why_url and mirror travel together" % (where, k))
    if probs:
        return probs
    why, quote, url, mirror = (praise[k] for k in WHY_FIELDS)
    if not str(url).startswith("https://"):
        probs.append("%s: why_url is not https" % where)
    # excerpt
    ex = os.path.join(repo, "documents", "state", "praise-pages", "%s.txt" % slug)
    try:
        excerpt = open(ex, encoding="utf-8").read()
    except OSError:
        excerpt = None
        probs.append("%s: no saved excerpt at documents/state/praise-pages/%s.txt" % (where, slug))
    if excerpt is not None:
        if len(excerpt.encode("utf-8")) > 20 * 1024:
            probs.append("%s: excerpt is over 20 KB" % where)
        if re.sub(r"\s+", " ", quote).strip() not in re.sub(r"\s+", " ", excerpt):
            probs.append("%s: why_quote is not a substring of the saved excerpt" % where)
        if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+|\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b", excerpt):
            probs.append("%s: excerpt carries an email or phone; scrub it" % where)
    # floor: not a restated value
    wt, vt = tokens(why), set(tokens(praise["value"]))
    new = [t for t in wt if t not in vt]
    if not new:
        probs.append("%s: the why names no term absent from the value" % where)
    if wt and (len(wt) - len(new)) / float(len(wt)) >= 0.6:
        probs.append("%s: the why restates the value (token overlap 0.6 or more)" % where)
    # mirror
    if norm(mirror) != "none yet":
        units = profile_units(repo)
        if units is None:
            probs.append("%s: profile file not found; mirror cannot be checked" % where)
        elif len(norm(mirror).split()) < 6:
            probs.append("%s: mirror is under 6 tokens; a fragment is not a mirror (use 'none yet')" % where)
        elif norm(mirror) not in units:
            probs.append("%s: mirror is not 'none yet' and does not equal a whole profile sentence or bullet" % where)
    # voice: no "not X, Y" contrast construction in the why
    if re.search(r",\s*not\s|\bnot\s+(just|only|merely)\b", why, re.I):
        probs.append("%s: the why uses a 'not X, Y' contrast construction" % where)
    # honesty
    for field, text in (("mirror", mirror), ("why", why)):
        for pat, label in DENYLIST:
            if re.search(pat, text, re.I):
                probs.append("%s: honesty denylist hit in %s (%s)" % (where, field, label))
    return probs


def check_file(path, repo):
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return ["%s: unreadable (%s)" % (os.path.basename(path), e)]
    if not isinstance(rows, list):
        return ["%s: not a list" % os.path.basename(path)]
    out = []
    for r in rows:
        out.extend(check_row(r, repo))
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]
    files = sorted(glob.glob(os.path.join(repo, "documents", "state", "praise-backfill-*.json")))
    if not files:
        print("check_praise_why: no praise-backfill files found; an empty check passes nothing")
        return 1
    bad = 0
    owed = ready = 0
    for f in files:
        probs = check_file(f, repo)
        try:
            for r in json.load(open(f, encoding="utf-8")):
                p = r.get("praise") if isinstance(r, dict) else None
                if isinstance(p, dict):
                    ready, owed = (ready + 1, owed) if p.get("why") else (ready, owed + 1)
        except (OSError, ValueError):
            pass
        for p in probs:
            print("FAIL %s: %s" % (os.path.basename(f), p))
        bad += len(probs)
        print("%s %s" % ("ok  " if not probs else "FAIL", os.path.basename(f)))
    print("rows ready (why recorded): %d, why owed: %d, problems: %d" % (ready, owed, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
