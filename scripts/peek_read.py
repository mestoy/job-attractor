#!/usr/bin/env python3
"""peek_read.py: read what a person pasted from Glassdoor or LinkedIn, and score it with the SAME logic the CLI uses.

WHY (slice B of "the app copies the CLI"). In the terminal, the 60-second culture peek is read by a person and then scored by rank_applications.py:
  - Glassdoor: culture_score(glassdoor={score, reviews}) weights the rating by the review count and damps a thin one toward neutral; instability_assessment() turns
    layoff, reorg and leadership-churn words into the heavy penalty; and the peek's own tripwire (HARD-INVARIANTS, "THE 60-SECOND CULTURE PEEK") says STOP when the
    NEWEST negative review is under about 6 months old AND names leadership or the function he would own.
  - LinkedIn: size_adjustment(headcount) (small is a plus, large a mild minus, never a gate), the industry words against the person's INDUSTRY_VETO, and the same
    instability words.
This module only READS the paste into those functions' inputs; it adds no scoring rule of its own. A paste that carries nothing it can read says so and scores nothing:
"insufficient" is never "bad", and an unreadable paste is never a pass.

USAGE  python3 scripts/peek_read.py --source glassdoor|linkedin [--repo DIR] [--today YYYY-MM-DD] < pasted text
OUTPUT one JSON object: {source, state: clear|blocked|unknown, reason, facts: {...}, known?}. EXIT 0 answered · 2 bad source or empty paste.
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import rank_applications as ra  # noqa: E402
import local_gates  # noqa: E402

PASTE_MAX = 20000
TRIPWIRE_DAYS = 183
LEADERSHIP = re.compile(r"\b(leadership|management|managers?|executives?|ceo|cpo|founders?|product vision|product management|product team|roadmap)\b", re.I)
NEGATIVE = re.compile(r"\b(poor|toxic|chaotic|no vision|lack of|avoid|terrible|worst|disorganized|micromanag\w*|layoffs?|laid off|turnover|do not join|don't join)\b", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b|\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")
RATING = re.compile(r"(?<![\d.,/])([1-5](?:\.\d)?)\s*(?:/\s*5|★|stars?\b|out of 5)", re.I)
RATING_LABELLED = re.compile(r"\brating[^\d\n]{0,12}([1-5](?:\.\d)?)(?![\d,.]*\d)", re.I)
REVIEWS = re.compile(r"([\d][\d,]*(?:\.\d+)?)\s*([kKmM])?\s*(?:\+\s*)?reviews?\b", re.I)
JOBSEC = re.compile(r"job\s+security\D{0,8}([1-5](?:\.\d)?)", re.I)


def _date(m):
    try:
        if m.group(1):
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m.group(4):
            mon = MONTHS.get(m.group(4)[:3].lower())
            return datetime.date(int(m.group(6)), mon, int(m.group(5))) if mon else None
        mon = MONTHS.get(m.group(8)[:3].lower())
        return datetime.date(int(m.group(9)), mon, int(m.group(7))) if mon else None
    except (ValueError, TypeError):
        return None


def _count(num, suffix):
    n = float(num.replace(",", ""))
    if suffix:
        n *= 1000 if suffix.lower() == "k" else 1000000
    return int(round(n))


def _out(source, state, reason, facts, known=None):
    out = {"source": source, "state": state, "reason": reason, "facts": facts}
    if known:
        out["known"] = known
    return out


def read_glassdoor(text, today):
    facts = {}
    m = RATING.search(text) or RATING_LABELLED.search(text)
    if m:
        facts["rating"] = float(m.group(1))
    rv = REVIEWS.search(text)
    if rv:
        facts["reviews"] = _count(rv.group(1), rv.group(2))
    js = JOBSEC.search(text)
    jobsec = float(js.group(1)) if js else None
    # The newest review that is negative AND names leadership or the function: blocks are paragraphs; a block carries a date and a low star or a negative phrase.
    newest = None
    for block in re.split(r"\n\s*\n", text):
        dm = DATE.search(block)
        if not dm:
            continue
        d = _date(dm)
        if not d:
            continue
        low_star = False
        rm = RATING.search(block)
        if rm and float(rm.group(1)) <= 2.0:
            low_star = True
        if (low_star or NEGATIVE.search(block)) and LEADERSHIP.search(block):
            if newest is None or d > newest[0]:
                newest = (d, " ".join(block.split())[:160])
    if newest:
        facts["newest_negative_leadership"] = newest[0].isoformat()
    signals = [ln.strip() for ln in re.split(r"[\n.]", text) if ln.strip() and ra._signal_fires(ln)]
    penalty, unstable, why = ra.instability_assessment(signals[:6], jobsec)
    if unstable:
        facts["instability"] = why[:4]
    if "rating" not in facts and "reviews" not in facts and not newest and not unstable:
        return _out("glassdoor", "unknown", "I could not find a rating, a review count or a dated review in what was pasted",
                    facts, "when you paste the company's Glassdoor overview and its newest reviews")
    parts = []
    if "rating" in facts or "reviews" in facts:
        gd = {"score": facts.get("rating"), "reviews": facts.get("reviews", 0)}
        culture, low, total = ra.culture_score(glassdoor=gd if gd["score"] is not None else None)
        facts.update({"culture_score": round(culture, 1), "low_confidence": bool(low)})
        if "rating" in facts and "reviews" in facts:
            parts.append("rated %.1f from %s reviews, culture score %d of 100%s" % (facts["rating"], format(facts["reviews"], ","), round(culture), ", thin evidence" if low else ""))
        elif "rating" in facts:
            parts.append("rated %.1f, but no review count was pasted, so it reads as neutral" % facts["rating"])
        else:
            parts.append("%s reviews, no rating was pasted" % format(facts["reviews"], ","))
    if newest:
        age = (today - newest[0]).days
        facts["newest_negative_age_days"] = age
        if age <= TRIPWIRE_DAYS:
            parts.append("the newest negative review (%s) is under 6 months old and names leadership or the product function" % newest[0].isoformat())
            return _out("glassdoor", "blocked", "Stopped by the culture peek: " + "; ".join(parts), facts)
        parts.append("the newest negative review naming leadership is %s, older than 6 months" % newest[0].isoformat())
    if unstable:
        parts.append("it mentions " + "; ".join(w.replace("flag: ", "") for w in why[:3]))
        return _out("glassdoor", "unknown", "; ".join(parts) + ". A pattern like this needs your eyes before Build", facts,
                    "you read the reviews it came from; the app does not judge instability on its own")
    return _out("glassdoor", "clear", "; ".join(parts), facts)


def read_linkedin(text, repo):
    facts = {}
    industry = None
    for ln in text.splitlines():
        m = re.match(r"\s*industry\s*[:\-]?\s*(.+)$", ln, re.I)
        if m and m.group(1).strip():
            industry = m.group(1).strip()
            break
    if not industry:
        m = re.search(r"^\s*([A-Za-z][A-Za-z &,/-]{3,60})\s*[·|•]\s*[\d,]+(?:\s*-\s*[\d,]+)?\+?\s*employees", text, re.M)
        if m:
            industry = m.group(1).strip()
    if industry:
        facts["industry"] = industry
    hm = re.search(r"([\d,]+)\s*-\s*([\d,]+)\s*employees|([\d,]+)\+\s*employees|\b([\d,]+)\s+employees", text, re.I)
    headcount = None
    if hm:
        if hm.group(1):
            lo, hi = int(hm.group(1).replace(",", "")), int(hm.group(2).replace(",", ""))
            headcount = (lo + hi) // 2
        else:
            headcount = int((hm.group(3) or hm.group(4)).replace(",", ""))
        facts["headcount"] = headcount
    if not industry and headcount is None:
        return _out("linkedin", "unknown", "I could not find an industry or a headcount in what was pasted", facts,
                    "when you paste the company's LinkedIn About section")
    parts = []
    if headcount is not None:
        adj = ra.size_adjustment(headcount)
        facts["size_adjustment"] = adj
        word = "a small-company plus" if adj > ra.SIZE_ADJ_MID else ("a mild minus for size" if adj < ra.SIZE_ADJ_MID else "neutral on size")
        parts.append("about %s people, %s (size is never a gate)" % (format(headcount, ","), word))
    industry_pats, employer_pats = local_gates.industry_veto_patterns(repo) if repo else ([], [])
    hit = local_gates._industry_hit(industry or "", industry_pats, []) if industry else None
    if hit:
        facts["industry_veto"] = hit
        return _out("linkedin", "blocked", "Deal-breaker industry: LinkedIn lists it as %s, which matches your veto %r" % (industry, hit), facts)
    if industry:
        parts.insert(0, "industry %s, no match with your vetoes" % industry)
    signals = [ln.strip() for ln in re.split(r"[\n.]", text) if ln.strip() and ra._signal_fires(ln)]
    _p, unstable, why = ra.instability_assessment(signals[:6])
    if unstable:
        facts["instability"] = why[:4]
        parts.append("it mentions " + "; ".join(w.replace("flag: ", "") for w in why[:3]))
        return _out("linkedin", "unknown", "; ".join(parts) + ". A pattern like this needs your eyes before Build", facts,
                    "you read where it came from; the app does not judge instability on its own")
    return _out("linkedin", "clear", "; ".join(parts), facts)


def read(source, text, repo=None, today=None):
    text = (text or "")[:PASTE_MAX]
    if source == "glassdoor":
        return read_glassdoor(text, today or datetime.date.today())
    if source == "linkedin":
        return read_linkedin(text, repo)
    raise ValueError("source must be glassdoor or linkedin")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read a pasted Glassdoor or LinkedIn page the way the CLI scores it.")
    ap.add_argument("--source", required=True)
    ap.add_argument("--repo", default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    ap.add_argument("--today")
    a = ap.parse_args(argv)
    text = sys.stdin.read()
    if a.source not in ("glassdoor", "linkedin") or not text.strip():
        print(json.dumps({"error": "send glassdoor or linkedin and some pasted text"}))
        return 2
    today = datetime.date.fromisoformat(a.today) if a.today else None
    print(json.dumps(read(a.source, text, a.repo, today), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
