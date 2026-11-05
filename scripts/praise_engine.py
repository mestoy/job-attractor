#!/usr/bin/env python3
"""praise_engine.py -- the accomplishment allowlist, one home for both the client (kit
build.py, `from praise_engine import praise_candidates`) and the feed-build backfill fold
(BUG-366/BUG-367). Extracted verbatim from app/design/phases/build.py's own
card_praise_source/_card_praise_candidates (2a's module; one-writer rule, agreed 2026-09-27 --
this seat owns this file, 2a wires the one-line import into build.py, never a direct edit here
from that side or there from this one).

A card's own research.leadership/research.news text, and its gates.leadership/gates.news
why-text, were written for RISK SCREENING, not accomplishment-hunting -- 66 of 68 kept
candidates in the first real-feed pass were not praise ("No ... found" risk checks, bare bios,
even a red-flagged succession line). This is an ALLOWLIST applied per SENTENCE, never to the
whole why text: a sentence survives only when it names no red flag, carries no negation (almost
every risk-check sentence opens with "No"/"None"), is not a bare identity/appointment/bio line,
and does carry an accomplishment verb. A why text with no sentence meeting all four yields no
candidate -- the caller shows its own honest "no sourced praise yet" state, never a guess.

Ranked impact-first: rank 0 (something built/shipped), rank 1 (a funding fact -- a duty every
company performs the same way when it raises money, not a thing someone built,
[[praise-is-judged-on-impact-not-duty]]), rank 2 (everything else the allowlist still passed).
"""
import re

_RESEARCH_NOTE = re.compile(
    r"\d{3}'d|\b(?:40[0-9]|50[0-9])\b|fetch|https?:|www\.|\burl\b|snippet|unread|"
    r"\breviews?\b|glassdoor|indeed|\bblind\b|\bowed\b|verif|\bgates?\b|\bpass\b|unproven|"
    r"\bradar\b|\bpark\b|\bdrop\b|scorecard|\bsources?\b|\bsearch\b|\bpage\b|"
    r"\bboard\b|posting|\breq\b|reporting line|full-time|mirrored|thread-level|sweep|"
    r"re-checked|\bcards?\b|\bruled\b|sample beat|no stable|\d{4}-\d{2}", re.I)

_PRAISE_RED_FLAG = re.compile(
    r"\U0001F534|succession|layoff|exodus|lawsuit|scandal|crisis|instability|"
    r"\bchurn\b|turnover|exec-exit|leadership-exit|\bdeparture\b", re.I)
# Anywhere in the sentence, not just at its start: "current as of the latest check, no
# successor announced" carries a real verb (announced) but is still a negative-result clause
# mid-sentence, the same shape as a sentence that opens with "No"/"None".
_PRAISE_NEGATION = re.compile(r"\bno\b|\bnone\b|\bnot\b|n't\b|\bnever\b", re.I)
_PRAISE_TITLE_ONLY = re.compile(
    r"\b(CEO|CTO|COO|CFO|CMO|CPO|Chief\s+\w+\s+Officer|Founder|Co-Founder|President|"
    r"Chairman|board member)\b", re.I)
_PRAISE_RESEARCH_PROCESS = re.compile(
    r"\d{3}'d|\b(prior|this|original)\s+pass\b|identity resolved|\bcorroborat\w*|"
    r"search-indexed|not independently|\bas of this check\b", re.I)
_PRAISE_ACCOMPLISHMENT_VERB = re.compile(
    # (?<!-)\bled\b: "Founder-led" is a compound ownership-structure adjective, not the verb
    # "led" doing something.
    r"\blaunch(?:ed|es|ing)?\b|\bship(?:ped|s|ping)?\b|(?<!-)\bled\b|\bbuil[dt](?:s|ing)?\b|"
    r"\bgrew\b|\bgrow(?:s|ing)?\b|\brais(?:ed|es|ing)\b|\bclos(?:ed|es|ing)\b|"
    r"\bcut\b|\bcutting\b|\breduc(?:ed|es|ing)\b|\bincreas(?:ed|es|ing)\b|"
    r"\bdoubl(?:ed|es|ing)\b|\btripl(?:ed|es|ing)\b|\bwon\b|\bpublish(?:ed|es|ing)?\b|"
    r"\bannounc(?:ed|es|ing)\b|\breleas(?:ed|es|ing)\b|\bdeliver(?:ed|s|ing)?\b|"
    r"\bdriv(?:es|ing)\b|\bdrove\b|\bexpand(?:ed|s|ing)?\b|\bscal(?:ed|es|ing)\b|"
    r"\bgenerat(?:ed|es|ing)\b|\brolled\s+out\b|\bintroduc(?:ed|es|ing)\b|"
    r"\bhit\s+\d|\breach(?:ed|es)\s+\d", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

_PRAISE_LABEL_STRIP = re.compile(
    r"^(?:✅\s*|positive signal(?:\s+only)?:\s*|growth/shipping posture:\s*|"
    r"(?:company\s+)?posture is growth:\s*|notable:\s*)", re.I)
_PRAISE_CITATION_MARK = re.compile(r"\s*\(§\d+\)")
_PRAISE_EDITORIAL_TAIL = re.compile(r"\s*—\s*[^.]*\bsignals?\b[^.]*\.?\s*$", re.I)
_PRAISE_PER_SOURCES_ASIDE = re.compile(r"\s*\([^()]*\bper sources?\b[^()]*\)", re.I)
_PRAISE_KNOWN_OUTLETS = (
    "PR Newswire", "Businesswire", "BusinessWire", "TechCrunch", "Axios", "Morningstar",
    "Yahoo Finance", "Coverager", "SaaS News", "CUInsight", "SiliconANGLE", "Crunchbase",
    "ZoomInfo", "RocketReach", "LeadIQ", "Pulse2", "PitchBook", "Craft", "TheOrg", "BuiltIn",
    "Cooley",
)
_PRAISE_OUTLET_LIST = re.compile(
    r"\s*\([^()]*(?:" + "|".join(re.escape(o) for o in _PRAISE_KNOWN_OUTLETS) + r")[^()]*\)",
    re.I)
_PRAISE_DANGLING_PUNCT = re.compile(r"\s+([,.])")

_PRAISE_SHIPPED = re.compile(
    r"\bship(?:ped|s|ping)?\b|\blaunch(?:ed|es|ing)?\b|\breleas(?:ed|es|ing)\b|"
    r"\brolled\s+out\b|\bintroduc(?:ed|es|ing)\b|\bbuil[dt](?:s|ing)?\b", re.I)
_PRAISE_FUNDING = re.compile(
    r"\bseries\s+[a-z]\b|\bseed\s+round\b|\bfunding\s+round\b|\braised\b|\bvaluation\b", re.I)


def _strip_praise_clutter(text):
    """The sentence a caller may show, with citation markers, outlet-list parentheticals, "per
    sources" hedge asides, and a trailing editorial dash-clause removed -- that metadata already
    lives in the candidate's own "source"/"url" fields, never doubled into the shown text."""
    t = _PRAISE_CITATION_MARK.sub("", text)
    t = _PRAISE_OUTLET_LIST.sub("", t)
    t = _PRAISE_PER_SOURCES_ASIDE.sub("", t)
    t = _PRAISE_EDITORIAL_TAIL.sub(".", t)
    t = re.sub(r"\s*(?:—|---)\s*", ", ", t)
    t = _PRAISE_DANGLING_PUNCT.sub(r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _praise_rank(text):
    if _PRAISE_SHIPPED.search(text):
        return 0
    if _PRAISE_FUNDING.search(text):
        return 1
    return 2


def praise_sentences(text):
    """[str, ...] of every sentence in `text` that passes the allowlist -- an accomplishment
    fact, never a risk-check note, an identity line, a research-process note, or a red-flagged
    one. Any research-note label on the front is stripped before return. Ranked impact first, a
    funding duty second, everything else last; stable within a rank."""
    out = []
    for raw in _SENTENCE_SPLIT.split(str(text or "").strip()):
        s = raw.strip()
        if (not s or _PRAISE_RED_FLAG.search(s)
                or _PRAISE_NEGATION.search(s) or _PRAISE_RESEARCH_PROCESS.search(s)):
            continue
        has_verb = bool(_PRAISE_ACCOMPLISHMENT_VERB.search(s))
        if _PRAISE_TITLE_ONLY.search(s) and not has_verb:
            continue  # a bare identity/appointment/bio line, not an accomplishment
        if has_verb:
            cleaned = _PRAISE_LABEL_STRIP.sub("", s).strip()
            out.append(_strip_praise_clutter(cleaned))
    return sorted(out, key=_praise_rank)


# Who a source is ABOUT. The rule (BUG-702): a row says so itself, with its own `subject` or `about`. A row that says nothing, or a word that
# names neither the boss nor the organization, is about the ORGANIZATION, never the boss, whatever research key it sits under. Turning a key
# into a word is the feed writer's job (build_app_feed.stamp_gate_subjects), not the page's.
_BOSS_WORDS = ("boss", "person", "individual", "leader", "manager", "him", "her", "them")


def names_the_boss(value, boss_name):
    """True when every token of the boss's name (sync_contacted.name_tokens: credentials stripped, lower-cased) is a whole word in `value`.
    A one-token name needs that one token. No usable name is False."""
    import sync_contacted
    tokens = sync_contacted.name_tokens(str(boss_name or ""))
    if not tokens:
        return False
    words = set(re.findall(r"[a-z]+", str(value or "").lower()))
    return all(t in words for t in tokens)


def _gate_subject(key, why, boss_name):
    """Gate why-text (card.gates) has no row to stamp. Leadership text is the boss only when it names the card's boss, else the organization
    (same test as the feed writer's rows); news text is the organization."""
    return "boss" if key == "leadership" and names_the_boss(why, boss_name) else "org"


def _subject(item):
    """Who the record says it is about: its own `subject` (or `about`). A word that names neither the boss nor the organization, or no word at
    all, is the organization, never the boss."""
    raw = item.get("subject") if item.get("subject") not in (None, "") else item.get("about")
    return "boss" if str(raw or "").strip().lower() in _BOSS_WORDS else "org"


def _tier(value):
    """A or B as the record names it, else "none". Never guessed from the text."""
    v = str(value or "").strip().upper()
    return v if v in ("A", "B") else "none"


def _research_rows(item):
    """A research slot is one sourced row or a list of them. Only sourced rows with a value count."""
    rows = item if isinstance(item, list) else [item]
    return [r for r in rows if isinstance(r, dict) and r.get("status") == "sourced" and r.get("value")]


def praise_candidates(card):
    """Every praise candidate this card carries, deduped and ranked impact-first ACROSS every
    source: card.research.praise/leadership/news (when status == "sourced" and value is
    non-empty) then card.gates' leadership/news why-text. Same source precedence for ties within
    a rank: research before gates, leadership before news, praise checked first since it is the
    direct answer to a request this card asked for. Each item is {"text", "source", "url"};
    duplicate text is kept once, in its first (best-sourced) form."""
    out = []
    seen = set()

    def _add_filtered(text, source, url, subject=None, why="", tier="none"):
        for sentence in praise_sentences(text):
            if sentence in seen:
                continue
            seen.add(sentence)
            out.append({"text": sentence, "source": source, "url": url, "subject": subject, "why": why, "tier": tier, "_rank": _praise_rank(sentence)})

    research = (card or {}).get("research") or {}
    for key in ("praise", "leadership", "news", "praise_org"):
        for item in _research_rows(research.get(key)):
            why = item.get("why")
            _add_filtered(item["value"], item.get("source") or "research", item.get("url"), _subject(item),
                          why.strip() if isinstance(why, str) else "", _tier(item.get("tier")))
    gates = {g.get("key"): g for g in ((card or {}).get("gates") or []) if isinstance(g, dict)}
    for key in ("leadership", "news"):
        g = gates.get(key)
        if g and g.get("why"):
            _add_filtered(g["why"], g.get("source") or "gate check", None,
                          _gate_subject(key, g["why"], ((card or {}).get("boss") or {}).get("name")))
    ranked = sorted(out, key=lambda c: c["_rank"])
    for c in ranked:
        del c["_rank"]
    return ranked


def praise_source(card):
    """The single best praise candidate, or None."""
    candidates = praise_candidates(card)
    return candidates[0] if candidates else None


def praise_sources(card):
    """Up to 3 sourced accomplishments, impact-ranked, never invented or padded."""
    return praise_candidates(card)[:3]


# ---------------------------------------------------------------------------------------------
# Slice C1 (2026-10-28): the praise FACE is one line in the shape he sends, "I really like that
# <one real thing>." (Samples 110 to 113; his sent lines run 14 to 23 words, so the bound is 24).
# The allowlisted sentence stays whole in `what`; why / why_quote / why_url / source / mirror /
# beat ride as FIELDS beside the line, never inside it. praise_sources() is unchanged.
# ---------------------------------------------------------------------------------------------
PRAISE_OPENING = "I really like that"
PRAISE_LINE_MAX_WORDS = 24

# The finite verb that opens the accomplishment (the allowlist's verbs plus a few it implies).
_ONE_THING_VERB = re.compile(
    r"\b(?:launched|shipped|led|built|grew|raised|closed|cut|reduced|increased|doubled|tripled|won|"
    r"published|announced|released|delivered|drove|expanded|scaled|generated|introduced|wrote|"
    r"opened|named|rolled\s+out|reached|hit)\b")
# Clause boundaries a long object may be cut at (the cut keeps what is before the marker).
_ONE_THING_CUTS = re.compile(
    r",\s+(?=(?:and|which|with|to|co-\w+|\w+ing|designed|backed|led)\b)|;\s+|\s+(?:that|which|while|where)\s+")
_ONE_THING_CUTS_LATE = re.compile(r"\s+(?:to|by|with|through|from|after|so|for|because|and)\s+")
_ONE_THING_DANGLING = re.compile(r"(?:\s+(?:a|an|the|of|in|on|at|for|to|and|or|its|their|his|her|with|by|it|them)\s*)+$", re.I)
_ONE_THING_BAD_TAIL = re.compile(r"(?:ing|ed|ly)$|^(?:is|are|was|were|be|been|can|will|around|into|onto|over|under|about|than|as)$", re.I)
_ONE_THING_BAD_HEAD = re.compile(r"^(?:just|the|it|they|we|this|that)$|\b(?:reports?|says?|said|announces?|claims?)\b", re.I)
_ONE_THING_PRONOUN = re.compile(r"\b(?:his|her|hers|their|theirs)\b", re.I)


def _words(text):
    return len(text.split())


def one_thing(text, subject="org", max_words=PRAISE_LINE_MAX_WORDS):
    """The one real thing in an allowlisted sentence: the subject and the object of the accomplishment
    verb, without parentheticals, outlet names, citation marks, or trailing purpose clauses. The
    clause is cut at the latest boundary that keeps the whole line, opening included, within
    `max_words`. A boss-subject sentence addresses him ("you led ..."), an org-subject one names the
    org. No usable subject or no verb returns None; the caller shows its honest empty state."""
    s = _strip_praise_clutter(str(text or ""))
    s = re.sub(r"\s+\([^()]*\)", "", s).strip()
    s = s.split(";")[0].strip().rstrip(".!?").strip()  # one thing: the first clause only
    m = _ONE_THING_VERB.search(s)
    if not m or not s[:1].isupper() or re.search(r"\d{4}-\d{2}", s):
        return None
    head, rest = s[:m.start()].strip(" ,"), s[m.start():]
    if subject == "boss":
        head = "you"
        # his/her/their usually belongs to someone else in the clause; never turn it into "your".
        # Cut the clause before the pronoun at the last boundary instead.
        pron = _ONE_THING_PRONOUN.search(rest)
        if pron:
            cuts = [c.start() for pat in (_ONE_THING_CUTS, _ONE_THING_CUTS_LATE)
                    for c in pat.finditer(rest) if c.start() < pron.start()]
            rest = _ONE_THING_DANGLING.sub("", rest[:max(cuts)]).strip(" ,") if cuts else ""
            if _words(rest) < 3:
                return None
    elif not head or _words(head) > 8 or "," in head or _ONE_THING_BAD_HEAD.search(head):
        return None
    budget = max_words - _words(PRAISE_OPENING) - _words(head)
    if budget < 4:
        return None
    best = rest
    if _words(rest) > budget:
        best = None
        for pattern in (_ONE_THING_CUTS, _ONE_THING_CUTS_LATE):
            for cut in pattern.finditer(rest):
                if best and _words(rest[:cut.start()]) <= _words(best):
                    continue
                prefix = _ONE_THING_DANGLING.sub("", rest[:cut.start()]).strip(" ,")
                if (3 <= _words(prefix) <= budget and not _ONE_THING_BAD_TAIL.search(prefix.split()[-1])
                        and not re.search(r"\bto \w+$", prefix)):
                    best = prefix  # the latest boundary that still fits wins, in either tier
        if best is None:
            return None
    body = (head + " " + best).strip()
    return body.rstrip(" ,;:") + "."


def praise_line(candidate, max_words=PRAISE_LINE_MAX_WORDS):
    """ONE sentence, "I really like that <one real thing>.", at most `max_words` words, built from a
    praise_candidates() item; None when there is nothing honest to say."""
    if not isinstance(candidate, dict):
        return None
    thing = one_thing(candidate.get("text"), candidate.get("subject") or "org", max_words)
    if not thing:
        return None
    line = PRAISE_OPENING + " " + thing
    return line if _words(line) <= max_words else None


def praise_face(candidate, max_words=PRAISE_LINE_MAX_WORDS):
    """The line plus the parts that explain it, as fields beside it: what (the whole allowlisted
    sentence), why (why it mattered), why_quote, why_url, source, mirror (his side of it), beat.
    None when there is no line."""
    line = praise_line(candidate, max_words)
    if line is None:
        return None
    c = candidate

    def _s(key):
        v = c.get(key)
        return v.strip() if isinstance(v, str) else ""

    return {"line": line, "what": _s("text"), "why": _s("why"), "why_quote": _s("why_quote"),
            "why_url": _s("why_url"), "source": _s("source"), "url": _s("url"),
            "mirror": _s("mirror"), "beat": _s("beat")}


# ── K2 (plan-desk-cli-2026-10-29 rev 2): the praise beat's options, for the CLI picker ─────────────
# `python3 scripts/praise_engine.py <slug> [--three] [--feed FILE | --card FILE]`
# Option 1 = praise_line(best candidate) on one line, then a one-line description naming the source.
# --three = up to three faces; each shows its four seat scores and total ONLY when the research row
# carries a `scores` dict {cpo, cto, designer, rise8} from the panel (never invented). The why parts
# (praise_face) are for "Explain this line" and are not printed here. No honest line = the empty state.
# Read-only: it never writes the feed.
EMPTY_STATE = "nothing sourced to praise yet; research or skip the beat"
_SEATS = (("CPO", "cpo"), ("CTO", "cto"), ("Designer", "designer"), ("Rise8", "rise8"))


def _norm_scores(sc):
    try:
        return {k: int(sc[k]) for _l, k in _SEATS}
    except (KeyError, TypeError, ValueError):
        return None


def _row_scores(card, cand, scores_by_text=None):
    """The panel's scores for this candidate: the seat's --scores file (keyed by the face's sentence)
    first, else the research row's own `scores` dict, else None."""
    if scores_by_text and cand["text"] in scores_by_text:
        return _norm_scores(scores_by_text[cand["text"]])
    research = (card or {}).get("research") or {}
    for key in ("praise", "leadership", "news", "praise_org"):
        for r in _research_rows(research.get(key)):
            sc = r.get("scores")
            if isinstance(sc, dict) and cand["text"] in str(r.get("value")):
                return _norm_scores(sc)
    return None


def _row_date(card, cand):
    research = (card or {}).get("research") or {}
    for key in ("praise", "leadership", "news", "praise_org"):
        for r in _research_rows(research.get(key)):
            if cand["text"] in str(r.get("value")) and isinstance(r.get("date"), str):
                return r["date"].strip()
    return ""


def praise_options(card, three=False, scores_by_text=None):
    """[(line, description, scores_or_None)]. Option 1 is the highest panel total when scores exist
    (ties and unscored keep candidate order); at most 1 (or 3) are returned."""
    items = []
    for cand in praise_candidates(card):
        line = praise_line(cand)
        if line is None:
            continue
        src = cand.get("source") or "research"
        date = _row_date(card, cand)
        items.append((line, "from " + src + (", " + date if date else ""),
                      _row_scores(card, cand, scores_by_text)))
    items.sort(key=lambda t: -(sum(t[2].values()) if t[2] else -1))   # stable
    return items[:3 if three else 1]


def _find_card(slug, feed_path):
    import json
    with open(feed_path, encoding="utf-8") as fh:
        feed = json.load(fh)
    cards = feed.get("cards") if isinstance(feed, dict) else feed
    for c in cards or []:
        if isinstance(c, dict) and c.get("slug") == slug:
            return c
    return None


def main(argv=None):
    import argparse
    import json
    import os
    import sys
    ap = argparse.ArgumentParser(description="The praise beat's options for one card (read-only).")
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--three", action="store_true", help="up to three faces, with scores when the panel scored them")
    ap.add_argument("--scores", help="JSON file {face sentence: {cpo, cto, designer, rise8}} from the seat's panel")
    ap.add_argument("--card", help="a card JSON file instead of the feed")
    ap.add_argument("--feed", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                   "documents", "state", "app-feed.json"))
    a = ap.parse_args(argv)
    if a.card:
        with open(a.card, encoding="utf-8") as fh:
            card = json.load(fh)
    elif a.slug:
        card = _find_card(a.slug, a.feed)
        if card is None:
            print(f"praise_engine: no card with slug {a.slug!r} in {a.feed}", file=sys.stderr)
            return 2
    else:
        ap.error("give a slug or --card")
    by_text = None
    if a.scores:
        with open(a.scores, encoding="utf-8") as fh:
            by_text = json.load(fh)
    opts = praise_options(card, three=a.three, scores_by_text=by_text)
    if not opts:
        print(EMPTY_STATE)
        return 0
    for line, desc, scores in opts:
        print(line)
        if a.three:
            if scores:
                print("   " + desc + " | " + " · ".join(f"{l} {scores[k]}" for l, k in _SEATS)
                      + f" | total {sum(scores.values())}")
            else:
                print("   " + desc + " | not scored yet")
        else:
            print(desc)
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
