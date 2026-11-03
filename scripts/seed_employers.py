#!/usr/bin/env python3
"""seed_employers.py — one-time migration from the prose list into the entity registry.

⛔ READ-ONLY ON THE SOURCE. It never modifies `documents/blocked-employers-list.md`. That file stays
authoritative, and the registry is an ADDITION: every reader keeps parsing prose until this has run
at least once, because `employers.available()` answers False while the registry file is absent.

⚖️ THREE OUTCOMES PER CANDIDATE, ALL MATERIALIZED, NONE SILENT. The prose harvest has two silent
failure modes and this migration is designed to have neither:

    in a NAME POSITION  → `employers.jsonl`, status carried from its section
    only in PROSE       → `employer-review-queue.jsonl`, WITH its source line, NOT blocking
    digit / fragment    → discarded, and the count is REPORTED

A name position is where the blocked list records a company: the head of a bullet, the first cell of
a table row, or a segment of a middot list. That is a fact about the record's SHAPE, not a guess
about whether a string looks like a company, which is what every previous parser fix tried to get
right.

📊 Measured on the install this was built from, before anything was written: 2,774 harvested keys for
1,257 employer bullets. 328 keys carry a digit (`000145`, `000customers`, scraped out of salary
figures), 713 more are lowercase sentence fragments (`acceptablewasnevertheissue`). Those are not
judgment calls; they are parser debris.

Usage:
    python3 scripts/seed_employers.py --dry-run   # report only, writes nothing
    python3 scripts/seed_employers.py             # write the three stores
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)


def _import_sibling(modname):
    """Import a same-directory sibling module, immune to a STALE `sys.modules` entry.

    The same guard `screen_sweep._import_sibling` carries. Python caches an import by BARE NAME and
    never by path, so a copy of a module loaded from another directory can poison the shared name
    for every later importer in the process, and a screening module resolving the wrong sibling can
    make a blocked-list lookup answer False for everything.
    """
    expected = os.path.join(HERE, modname + ".py")
    mod = sys.modules.get(modname)
    if mod is not None and os.path.abspath(getattr(mod, "__file__", "") or "") == os.path.abspath(expected):
        return mod
    import importlib.util
    spec = importlib.util.spec_from_file_location(modname, expected)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # kit#test_gates-15: registering before the load succeeds means a failed load (the
        # file is missing, or has a syntax error) leaves this HALF-BUILT module cached under
        # the bare name forever -- every later `from modname import X` anywhere else in the
        # process then hits the same empty stub and raises AttributeError, never the clean
        # ModuleNotFoundError/ImportError every caller's own try/except expects and recovers
        # from. Pop it and re-raise the ORIGINAL error.
        sys.modules.pop(modname, None)
        raise
    return mod


_ss = _import_sibling("screen_sweep")
canon, blocked_keys_from_list = _ss.canon, _ss.blocked_keys_from_list
_employers = _import_sibling("employers")
REGISTRY, NOTES, QUEUE = _employers.REGISTRY, _employers.NOTES, _employers.QUEUE
exoneration = _import_sibling("exoneration")
FILTERS = _import_sibling("reconcile_findings").FILTERS

SRC = os.path.join(REPO, "documents", "blocked-employers-list.md")

REASON = re.compile(r"\b(blocked|declined|owned|culture|layoff|always-on|grindset|pe-owned|"
                    r"leadership|reversal|turmoil|acquisition|not blocked|corrected|filter|"
                    r"remote|travel|company|reason)\b")
# ⛔ `corrected` ALONE IS NOT AN EXONERATION, and treating it as one un-blocked a real company.
#
# 🔴 THE DEFECT: a bullet said `blocked <date>, filter 8` in its NAME position and then narrated
# *"the sweeping agent first logged it as a SURVIVOR, caught the parent-entity miss 58 seconds later
# and **corrected** it to DROP"*. This regex read that word out of the NARRATIVE and flipped the
# entity to `cleared`, so a company blocked three months earlier for being acquired by an excluded
# parent was not blocked at all. A correction runs in EITHER direction, so the bare word carries no
# verdict.
#
# ⚖️ THE FIX IS THE MARKER THE FILE ACTUALLY USES. An entry-level correction is written
# `⚠️ ENTRY CORRECTED <date>`; a mid-sentence "corrected it to DROP" is narration. Requiring `entry
# corrected` keeps the genuinely exonerated rows cleared and stops reading a company's own history
# as a reprieve.
# ⛔ WIDENING THIS VOCABULARY UN-BLOCKED A REAL COMPANY, recorded because the mistake is the same
# shape as the bug being fixed. One exonerated row is phrased "NOT **a** blocked employer", which
# `not blocked` misses, so the alternative `not a blocked` was added. Another company's bullet
# contains the sentence *"a parked row is not a blocked row"*, a general statement about how the
# pipeline works, and the new alternative matched it. A company blocked for REMOTE FAIL, verified
# twice, came back cleared.
# ⚖️ `entry corrected` already covers the phrasing on its own, so the wider alternative bought
# nothing and cost a real block. Keep this vocabulary NARROW.
# 🏗 THE LITERAL MOVED TO `scripts/exoneration.py`; THE HISTORY ABOVE STAYS HERE, because this is
# the file whose parse the two regressions actually broke. `check_dup` (the send gate) can hold a
# hand-copied twin of the same pattern with a comment asking it to stay identical, which pins
# nothing. Both should read ONE object. The attribute name is kept so every caller and test that
# says `seed_employers.EXONERATED` still resolves.
EXONERATED = exoneration.EXONERATED
SECTION = re.compile(r"^\*\*⛔ Filter (\d+): (.+?)\*\*\s*$")
HEADING = re.compile(r"^#{1,6}\s+(.*)$")
DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")

# BUG-246: `filter`/`filter_label` used to come entirely from the last `**⛔ Filter N: ...**`
# heading `scan()` had walked past, never from the entry's own text — so a maintainer forgetting
# to re-declare a heading for a long stretch of entries silently mislabeled every one of them with
# whatever reason the PREVIOUS heading named. Three-tier resolution per entry, highest-confidence
# first, each used ONLY when the tier above finds nothing:
#   1. an explicit "filter N" stated in the entry's OWN text — the author's own claim about THIS
#      company, never inherited context.
#   2. a keyword read of the entry's stated reason, using the same reason-vocabulary a blocked
#      list already writes in prose (see FILTER_KEYWORDS below).
#   3. the section-heading state, kept only as the last resort for an entry with no recognizable
#      reason-vocabulary at all.
# A cleared/PASS entry gets no filter number at all — a filter number names a drop reason, and a
# company that was NOT dropped has no drop reason to name, regardless of which tier produced one.
INLINE_FILTER = re.compile(r"\bfilter\s+(\d{1,2})\b", re.I)

# Keyword -> filter number, first match wins, checked in this order (most specific reason-phrases
# first so e.g. "predatory lending" never falls through to a looser pattern). `reconcile_findings
# .FILTERS` is the single source for every filter's label; filter 12 (values) is the newest entry
# there.
FILTER_KEYWORDS = [
    # 13 (BUG-255, on the Tanggulan Federal federal-clearance req): a categorical hard filter distinct
    # from filter 2 ("defense or military mission") -- a role requiring Public Trust or a
    # security clearance can sit at a company with no defense mission at all (a commercial
    # integrator's federal subsidiary, a civilian-agency contractor), so it needs its own
    # category and is checked before filter 2's broader "defense" match so it isn't shadowed.
    (13, re.compile(r"public trust|federal suitability|security clearance", re.I)),
    (12, re.compile(r"values fail|human[- ]lives?|human[- ]life|FAKE-precedent-12|"
                     r"dollar value on a human", re.I)),
    (5, re.compile(r"predatory lending|subprime|collections agency|charged-off consumer debt", re.I)),
    (3, re.compile(r"law enforcement|policing|security vendor presumption", re.I)),
    (2, re.compile(r"\bdefense\b|\bmilitary mission\b", re.I)),
    (6, re.compile(r"DTC prescription|telehealth marketing", re.I)),
    (4, re.compile(r"crypto[- ]primary|\bgambling\b|social media as the primary", re.I)),
    (10, re.compile(r"foreign[- ]anchor|foreign-anchored", re.I)),
    (1, re.compile(r"remote (hard )?fail|\bhybrid\b|\bRTO\b|return[- ]to[- ]office|\bin-office\b|"
                    r"metro-locked|days? per week in|five days a week|remote-absolute fail", re.I)),
    (9, re.compile(r"right-leaning", re.I)),
    (7, re.compile(r"LGBTQ", re.I)),
    (11, re.compile(r"170K floor|cannot clear the \$170K", re.I)),
    (8, re.compile(r"PE[-\s]owned|private equity|\bPE sponsor\b|\bPE firm\b|buyout|"
                    r"majority[- ]control|majority[- ]owned|majority[- ]acquired|acquired by|"
                    r"roll-up|control acquisition|\bLBO\b", re.I)),
    # 0 (BUG-247, live find on Tinig AI/Liwanag Health): a culture-fail DROP has no filter
    # code of its own in the base 0-12 set — it is a judgment call on the owner's own read of the
    # reviews, not a hard veto, so it belongs with filter 0 ("Not a hard filter, the owner's own
    # ruling on fit") per the same BUG-055 reasoning that created that code. Checked LAST,
    # after every specific category above, so a row that is ALSO PE-owned/remote-fail/etc and
    # happens to mention culture in passing still resolves to its real, more specific reason
    # first — this tier only catches a row whose OWN stated reason is culture and nothing else
    # matched. Scoped to actual culture-fail phrasing (never a bare "Glassdoor", which appears
    # in nearly every entry regardless of its real reason and would over-trigger).
    (0, re.compile(r"culture fail|culture,\s|\bculture:|toxic (culture|leadership)|"
                    r"recurring[- ]layoffs|leadership instability|corroborated (negative|toxic)",
                    re.I)),
]


_UNRECOGNIZED_HEADING = re.compile(r"not recognized", re.I)


def _resolve_filter(line_text, section):
    """(filter_number, filter_label) for one blocked-list line, tiered per BUG-246 above.

    BUG-247: a blocked-list heading occasionally reads `**⛔ Filter N: other, filter number
    not recognized**` with an Example Co 07, arbitrary N (12, 13, 16 seen in the wild) instead of
    the already-established 99 "other" sentinel (see `kit_config.EXTRA_FILTERS`'s own
    comment: "34 of 79 prior DROPs sat in filter 99"). Left alone, tier 3 below would hand
    back that arbitrary N verbatim, numerically colliding with any REAL filter that happens
    to share the same digit — BUG-246's new base filter 12 ("Values") is exactly such a
    collision, discovered live in `employers.jsonl`. Caught here, at the point tier 3 would
    otherwise trust the heading's printed number, so it never depends on which arbitrary
    number a given "not recognized" heading happens to carry, present or future.
    """
    m = INLINE_FILTER.search(line_text)
    if m:
        num = int(m.group(1))
        return num, FILTERS.get(num, (section or {}).get("label"))
    for num, pat in FILTER_KEYWORDS:
        if pat.search(line_text):
            return num, FILTERS.get(num)
    if section and _UNRECOGNIZED_HEADING.search(section.get("label", "")):
        return 99, "Other, filter number not recognized"
    return (section or {}).get("filter"), (section or {}).get("label")


def _head_names(segment, bold_line=False):
    """Candidate display names in NAME POSITION within a line segment.

    ⛔ TWO SHAPES IN A BLOCKED LIST ARE NOT NAMES, and both get harvested as companies by a naive
    parser. Neither guard is a heuristic about whether a string LOOKS like a company; both are facts
    about the record's structure, which is the distinction this whole module rests on.

    1. **A WIKI-LINK IS A MEMORY POINTER.** `- SomeCo (aggressive-growth = ethics risk) ·
       [[aggressive-growth-ethics-risk]]` split on the middot and handed `[[…]]` straight through, so
       `aggressivegrowthethicsrisk` became a blocked employer. Six of these were blocking.

    2. **ON A LINE THAT OPENS IN BOLD, THE FIRST SEGMENT IS A LABEL.** The file writes
       `**⛔ Defense or DoD mission**: AlphaCo · BetaCo · GammaCo · …`, so the line carries a heading
       AND real companies. `Note`, `Lesson`, `Sub-ratings`, `⛔ PE control` and
       `Failed the ranked-top-10 screen` all became blocked entities this way.

    ⚠️ THE NARROWNESS IS THE WHOLE POINT, and a blanket rule was measured and rejected. Skipping
    every line that starts with `**` would have dropped 27 REAL COMPANIES sitting in the later
    segments of exactly those lines. Only the FIRST segment is the label.

    📊 MEASURED BEFORE SHIPPING: keys 1,323 → 1,301. 22 dropped, 0 real companies lost. Two of the
    22, `note` and `lesson`, were short enough to false-block a company of that name, so this closes
    a silent-exclusion risk as well as a silent-admission one.
    """
    out = []
    for idx, seg in enumerate(re.split(r"\s*·\s*", segment.lstrip("-* ").strip())):
        if seg.strip().startswith("[["):
            continue
        if bold_line and idx == 0:
            # ⛔ STRIP THE LABEL, DO NOT DROP THE SEGMENT, and the difference is five companies.
            # The real shape is `**⛔ Defense or DoD mission (filter 2):** AlphaCo · BetaCo · …`,
            # so segment 0 carries the label AND the first company. Dropping the segment loses that
            # company; a plain head-split loses it too, by cutting at the label's own `(`.
            # ⚠️ THE OPENING `**` IS ALREADY GONE by the time this runs: the split above operates on
            # `segment.lstrip("-* ")`, which eats it. So the label is everything up to the CLOSING
            # `**`, and a regex anchored on a leading `**` matches nothing. It was written that way
            # first and silently recovered none of the five companies.
            m = re.match(r".*?\*\*[:\s]*(.*)$", seg.strip())
            seg = m.group(1) if m else ""
            if not seg.strip():
                continue
        head = re.split(r"\s*[(—–:]|\s+\*\*", seg, 1)[0]
        cand = head.strip(" *_`~")
        if not cand:
            continue
        # ⛔ A CATEGORY LABEL IS NOT A COMPANY, whatever its length. This runs BEFORE the word cap
        # AND BEFORE THE `REASON` TEST, because a label is very often a reason word itself:
        # `- PE-owned (filter 8, default pass): **AlphaCo**, **BetaCo**, **GammaCo**, …` was
        # rejected on the head `PE-owned` and returned early, so all nine companies on that line
        # blocked nothing. Rejecting the label is right; rejecting the line it introduces is the
        # lapse. The cap alone never identified a label either: `Banks, insurers, and mega-finance`
        # is four words and sailed past as a legitimate head, registering
        # `banksinsurersandmegafinance` as a blocked employer while the six real banks on the same
        # line were blocked by nothing. The `: **Name**` shape is the tell, not the length.
        # ⚠️ A BOLD HEAD IS A COMPANY, NEVER A LABEL, and this guard is why. `- **Worth Co**: **no
        # open Product role at all**, …` wears the same `: **` shape as a category line, because the
        # REASON is bolded too. Without this the rule DROPPED three companies that were blocked and
        # harvested a Glassdoor sub-rating in their place. The label in a category line is plain
        # text; the company in a company line is bold. The opening `**` is already eaten by the
        # `lstrip("-* ")` above, so the tell is the CLOSING one.
        _tail = seg[len(head):]
        if not head.rstrip().endswith("**") and re.match(r"\s*:\s*\*\*", re.sub(r"\([^)]*\)", "", _tail)):
            out.extend(_bold_names(_tail))
            continue
        # A corporate suffix or domain marks a NAME, so it outranks the reason veto.
        if REASON.search(cand.lower()) and not NAME_MARKER.search(cand):
            continue
        if len(cand) > 44 or len(cand.split()) > 5:
            # ⛔ A CATEGORY LABEL IS NOT A LIST OF COMPANIES, and it wears the same commas.
            # `- Retail, CPG, DTC, appliances, or industrial distribution (off-segment): **AlphaCo**,
            # **BetaCo**, …` would otherwise register `Retail, CPG, DTC` as an employer and make
            # `retail` a blocking key. The structural tell: a LABEL is followed by bold company
            # names OUTSIDE the parenthetical, while a genuine list keeps all its bold INSIDE it
            # (`AlphaCo, BetaCo, … (**PE**, all four.)`). Strip the parentheses; a label is what
            # remains as `: **Name**`.
            # ⚠️ Anchored on that colon rather than on "any bold in the tail", which was the first
            # version and was too broad: `**AlphaCo / Alpha Financial** (**PE-OWNED**…). Acquired by
            # **Some Fund**…` carries NARRATIVE bold after the parenthetical and is a real blocked
            # company. Rejecting it would have traded one silent admission for another.
            # 🔴 THE CAP USED TO RUN ON THE WHOLE COMMA-JOINED HEAD, so a six-company list measured
            # six words and yielded ZERO entities. Three of those six were named nowhere else in the
            # file and were blocked by nothing.
            # ⚖️ The cap is kept and applied PER PART instead of being loosened, because a loose
            # parser here is how the junk keys arrived in the first place.
            cand = _name_list_prefix(cand)
            if not cand:
                continue
        out.append(cand)
    return out


# ⛔ A ROLE IS NOT A COMPANY, and the list uses a comma for BOTH shapes.
#
# 🔴 MEASURED. The comma appears in `AlphaCo, BetaCo, GammaCo, DeltaCo` (four companies) and in
# `Some Bank, Treasury Management Officer III` (one company and the ROLE that failed). That second
# row's ruling is `REMOTE FAIL … Workday locations "Virtual" and "Virtual - New York" only`, which
# is a fact about that POSTING, not about the employer. Without this guard the first version of the
# fix blocked the bank registry-wide on the strength of one job's location list and registered
# `Treasury Management Officer III` as an employer. That bank was #4 on the company board that
# morning, so the silent-exclusion cost would have been immediate and invisible.
#
# ⛔ A CORPORATE SUFFIX OR A DOMAIN IS A NAME MARKER, and it OUTRANKS the REASON veto.
# 🔴 THE DEFECT. `REASON` exists to stop a reason PHRASE being harvested as a company, and it fires
# on `remote`, `travel` and `company`. Those words also sit inside real names, so five blocked
# employers were vetoed by their own names and blocked NOTHING: names of the shape `Example.com`,
# `Example Travel Group`, `Sample Holding Company LLC`, `Sample Insurance Company` and
# `Sample Electric Company, LLC`.
# 📊 MEASURED BEFORE CHANGING IT: REASON vetoes 193 bullet heads, and EXACTLY 5 of them carry a
# corporate suffix or a domain. Those 5 are the false kills; the other 188 are prose like
# "Permanent culture excludes" and "Declined, culture/grindset/PE/turmoil". So the exemption
# recovers every real name and surrenders none of the veto's actual work.
# ⚖️ WHY THIS SHAPE. The module already rests on STRUCTURE over vocabulary: the name position is the
# signal, not what the words mean. A legal suffix or a domain is the strongest structural evidence a
# string is an organization, and reason prose does not carry one. Narrower than loosening REASON,
# which is how the junk keys arrived in the first place.
NAME_MARKER = re.compile(
    r"\b(Inc|Incorporated|LLC|L\.L\.C|Corp|Corporation|Company|Companies|Co|Ltd|Limited|PLC|"
    r"LLP|LP|Group|Holdings?|Partners|Ventures|Systems|Solutions|Technologies|Labs|"
    r"Industries|Enterprises|Associates|Foundation|Institute)\b\.?|"
    r"\.(com|io|ai|co|org|net|app|dev|health|law|tech)\b", re.I)

ROLE_TAIL = re.compile(
    r"\b(officer|manager|director|engineer|analyst|architect|designer|specialist|associate|"
    r"consultant|administrator|coordinator|president|principal|partner|lead|head|chief|"
    r"vp|svp|evp|intern|i{1,3}|iv|v)\b\.?$")


def _bold_names(tail):
    """The `**Name**` spans in a label line's tail, filtered by the same rules as a bullet head.

    Only ever called on the `Label (reason): **A**, **B**, **C**` shape, where every bold span is a
    company. Reason tags such as `**PE**` or `**REMOTE FAIL**` live INSIDE the parenthetical, which
    the caller has already used to recognize the shape, so they are excluded here by REASON anyway.
    """
    out = []
    for b in re.findall(r"\*\*([^*]+)\*\*", tail):
        b = b.strip(" *_`~:,.")
        if not b or len(b) > 44 or len(b.split()) > 5:
            continue
        if REASON.search(b.lower()) or not re.match(r"[A-Z0-9]", b):
            continue
        out.append(b)
    return out


def _name_list_prefix(cand):
    """The leading run of COMPANY names in an over-cap head, or "" when it is not one.

    Deliberately strict, because everything returned here becomes a blocking key. A part qualifies
    only if it passes the same caps on its own AND opens with a capital or a digit, which is the
    same proper-noun signal `main()` already uses to separate fragments from parked keys.

    ⚖️ A LOWERCASE PART ENDS THE LIST, it does not invalidate it. A real line reads
    `AlphaCo, BetaCo, GammaCo, DeltaCo, EpsilonCo, see batch-6 block above.`, five companies and a
    trailing cross-reference. Rejecting the whole head on that tail is how the first version of this
    fix left that line lapsing even though it is one of the genuine company lists. Companies are
    capitalized, so the first lowercase part is where the record turns into prose; the run before it
    is the list, and at least two parts have to survive.

    ⛔ A ROLE anywhere in the surviving run rejects the whole head, because
    `Some Bank, Treasury Management Officer III` rules on a POSTING and not on an employer.
    """
    parts = [p.strip(" *_`~()") for p in ALIAS_SPLIT.split(cand)]
    kept = []
    for p in parts:
        if not p:
            continue
        if not re.match(r"[A-Z0-9]", p):
            break                       # prose starts here; everything after it is commentary
        if len(p) > 44 or len(p.split()) > 5 or REASON.search(p.lower()):
            return ""
        kept.append(p)
    if len(kept) < 2 or any(ROLE_TAIL.search(p.lower()) for p in kept):
        return ""
    return ", ".join(kept)


# ── ALIAS PARTS: the `A/B` and `A, B, C` forms a blocked list actually uses ──────────────────────
#
# 🔴 THE DEFECT THIS CLOSES, and it was LIVE. `_head_names` splits a line on `·` and stops there, so
# a bullet named `Alpha/Alpha Web Services (AWS)` produced ONE key, `alphaalphawebservices`, which
# is a string no company will ever be called. Neither `Alpha` nor `Alpha Web Services` was in the
# registry, and the registry is what the ranker's blocked check reads, so the parent company was NOT
# blocked. Eight more parent brands failed the same way.
#
# 📊 MEASURED: 58 bullets carry a slash in the NAME position, 55 of them had no part blocked, and
# 112 distinct company names were invisible to the live gate. Every one of them is a company the
# pipeline owner had already declined, sitting eligible in the ranked pool with nothing printed.
#
# ⚖️ THE FUSED KEY STAYS AS THE ENTITY. It is what the source line says, and rewriting the identity
# would lose the tie between the two names. The parts become ALIASES, which `employers.registry()`
# already resolves onto the same row, so both spellings answer for the same entity and the source
# line stays the authority.
#
# ⛔ A SHORT PART IS PARKED, NEVER ALIASED. Three-character initialisms canon to three characters,
# and a three-character alias is a skeleton key: it would take every company with those letters in
# its canon key down with it. Four characters is the same floor the harvest already uses. Parked
# parts go to the REVIEW QUEUE with their source line, visible and not blocking, because nothing is
# dropped on a heuristic.
ALIAS_SPLIT = re.compile(r"\s*[/,]\s*")
ALIAS_MIN = 4


def alias_parts(name):
    """(aliases, parked). Split a display name on `/` and `,`; short parts are parked, not dropped."""
    if not ALIAS_SPLIT.search(name or ""):
        return [], []
    aliases, parked = [], []
    for part in ALIAS_SPLIT.split(name):
        part = part.strip(" *_`~()")
        if not part or part == name:
            continue
        k = canon(part)
        if not k or k == canon(name):
            continue
        (aliases if len(k) >= ALIAS_MIN else parked).append(part)
    return aliases, parked
# ── RENAME ALIASES ───────────────────────────────────────────────────────────────────────────
#
# WHY (2026-08-09). A blocked employer's FORMER or CURRENT alternate name, announced on its own row,
# was captured nowhere, so the company was blocked under one name and walked through under the
# other. `_head_names()` cuts the head at the first `(`, so everything a parenthetical says about
# identity was discarded before any alias code ran.
#
# 📊 REALIZED, NOT THEORETICAL. a row of the shape blocked-employers-list.md (a `(now X)` row).
# The parent was blocked; the renamed company had no entity and `is_blocked()` returned
# False; and the renamed company appeared in 14 separate sweep files across three weeks. It never reached the board, so a later gate happened to catch it. That
# is containment by accident, not a gate.
#
# ⭐ Found by running this pipeline on a second machine with a different blocked list, which is the
# only way this class surfaces: an install satisfies its own assumptions by construction.
#
# ⛔ CASE-INSENSITIVITY IS SCOPED TO THE MARKER TOKEN, NEVER THE CAPTURE, and that is not a style
# choice. An `re.I` over the whole pattern was MEASURED letting `at Harness` into a capture: with the
# capture case-folded, `[A-Z]` stops meaning "a proper noun" and the run swallows ordinary words.
#
# ⛔ MARKERS DELIBERATELY EXCLUDED, each with its receipt from the live file. All three name a
# COUNTERPARTY rather than another name for this row's entity, so aliasing them would block a
# different company on this row's ruling:
#   · `merged into/with X`   → four different company names
#   · `rebranded to X`       → the one live instance is one live instance, whose bullet DISPROVES it
#                              ("example.com redirects to Other Co, unrelated")
#   · `rebranding it 'X'`    → one live instance is the new name of a named company's PARENT
#   · `resolves to X`        → recorded, not harvested: `AmerisourceBergen` and `CRC Group` stay
#                              unblocked. Under-block, logged rather than guessed at.
_TOK = r"(?:[A-Z][A-Za-z0-9&.'’\-]*|\d+[A-Za-z][A-Za-z0-9&.'’\-]*)"
_RUN = rf"{_TOK}(?:\s+{_TOK})*"
_LTOK = r"[A-Z][A-Za-z&.'’\-]*"
RENAME_FORMS = (
    re.compile(rf"\b(?i:formerly|fka|dba|rebranded\s+from)\s+({_RUN})"),
    # Paren-anchored ON PURPOSE: bare "now" is one of the commonest words in the reason prose, and
    # unanchored it captured "~19 ppl" and "serves on its Board of Directors".
    re.compile(rf"\((?i:\s*now)\s+({_RUN})"),
    # Prose form. Some rows announce a rename in PROSE ("OldName rebrand") rather than in a
    # parenthetical, and this is the only form that reaches those. Directionally blind by nature, so the self guard below is what makes it safe.
    re.compile(rf"\b({_LTOK}(?:\s+{_LTOK})*)\s+rebrand\b"),
)
RENAME_MAX_WORDS = 5
RENAME_MAX_CHARS = 44


def rename_aliases(text, own_keys=frozenset()):
    """(kept, parked) alias display strings declared by a rename marker on ONE source line.

    Pure, no I/O, so the seeder, the gate and the tests all drive the identical rule. That shared
    single definition is the whole point: `registry_equivalence` decides whether a blocked key is
    traceable to a name position, and if it held a SECOND copy of this rule the two would drift and
    the gate would start failing correct data (or, worse, passing junk).

    ⛔ `own_keys` IS THE SELF GUARD AND IT IS LOAD-BEARING. `a self-narrating row` reads "...still private through
    the 2025 NewName rebrand", where `NewName` is the row's OWN CURRENT NAME narrating its own
    rebrand, not a former name. The prose form cannot tell "X rebrand" (X = the new name) from
    "formerly X" (X = the old one); rejecting a capture that canons to a name this row already
    declares is what separates them.

    ⚖️ RESIDUAL RISK, stated rather than hidden: a bullet narrating ANOTHER entity's rebrand in its
    reason text would alias that entity onto this row. That direction is OVER-block, which is
    visible on the board and in `why()`. The direction this function exists to close is
    silent UNDER-block. The asymmetry is deliberate.
    """
    kept, parked = [], []
    seen = set()
    for form in RENAME_FORMS:
        for m in form.finditer(text or ""):
            cand = (m.group(1) or "").strip(" *_`~:,.")
            if not cand or len(cand) > RENAME_MAX_CHARS or len(cand.split()) > RENAME_MAX_WORDS:
                continue
            k = canon(cand)
            # A canon with no letters is a date or a money figure, never an employer.
            if not k or not re.search(r"[a-z]", k) or k in seen:
                continue
            if k in own_keys:                      # self-narration, see the docstring
                continue
            seen.add(k)
            # Same floor as alias_parts, for the same reason: a three-character alias is a skeleton
            # key. `GPS` (a 3-char row) parks here rather than making `gps` blocked.
            (kept if len(k) >= ALIAS_MIN else parked).append(cand)
    return kept, parked


# ── ABBREVIATION FORM: `ABBR (Full Name)` and `Full Name (ABBR)` (Q29a, 2026-10-04) ─────────────
#
# 🔴 THE GAP. `canon()` drops every parenthetical, so `- **ZQNOV (ZQNOV Holdings)**` keys as `zqnov`
# and the FULL NAME was never captured: `ZQNOV Holdings` was not blocked under its own spelling.
# Found from a partner install (kit #92). Same registry aliases the rename forms feed, one more form.
#
# ⛔ NOT ANY PARENTHETICAL. The parenthetical must read as a NAME (2 to 5 capitalized words) and the
# ABBR must read as ITS abbreviation: 2 to 6 capitals or digits whose letters run in order through the
# full name, starting at its first letter (`ZCS` for Zzyzx Computer Services, `QBW` for Quorble
# Widgets, `ZQNOV` for ZQNOV Holdings). `Zorbposh (zorbposh.vip, consumer ticketing)` is neither and aliases
# nothing.
#
# ⛔ THE ABBR IS HELD TO THE SAME FLOOR AS EVERY OTHER ALIAS (`ALIAS_MIN`): under 4 characters it is
# PARKED and printed, never aliased, because a three-letter key would block every name holding those letters. The FULL
# NAME is what gets aliased. When the row's own head is such a short ABBR, the entity is keyed on the
# full name instead (`abbr_row`), so the short head never becomes a blocked key either.
_ABBR_WORD = r"[A-Z][A-Za-z0-9&.'’\-]*"
_ABBR_FULL = rf"{_ABBR_WORD}(?:\s+{_ABBR_WORD}){{1,4}}"
_ABBR_LEAD = r"^[\s\-*|_`]*"
_ABBR_FWD = re.compile(rf"{_ABBR_LEAD}([A-Z0-9]{{2,6}})\s*\(\s*({_ABBR_FULL})\s*[,;:)\u2014]")
_ABBR_REV = re.compile(rf"{_ABBR_LEAD}({_ABBR_FULL})\s*\(\s*([A-Z0-9]{{2,6}})\s*[,;:)]")


def _abbr_of(abbr, full):
    """True when `abbr` abbreviates `full`: its letters run in order through the full name and the
    first one opens the first word. Lenient on purpose (the parenthetical already sits beside it)."""
    a = re.sub(r"[^a-z0-9]", "", abbr.lower())
    f = re.sub(r"[^a-z0-9]", "", full.lower())
    first = re.sub(r"[^a-z0-9]", "", full.split()[0].lower())
    if not a or not f or not first or a[0] != first[0]:
        return False
    it = iter(f)
    return all(ch in it for ch in a)


def abbr_form(text):
    """(shape, abbr, full) when the line head is an abbreviation form, else None. Pure, no I/O.
    shape is "fwd" for `ABBR (Full Name`, "rev" for `Full Name (ABBR)`."""
    t = text or ""
    m = _ABBR_FWD.match(t)
    if m and _abbr_of(m.group(1), m.group(2)):
        return "fwd", m.group(1), m.group(2).strip()
    m = _ABBR_REV.match(t)
    if m and _abbr_of(m.group(2), m.group(1)):
        return "rev", m.group(2), m.group(1).strip()
    return None


def abbr_aliases(text, own_keys=frozenset()):
    """(kept, parked) alias display strings declared by the abbreviation form on ONE source line.

    The full name is KEPT when its canon is 4+ characters and is not already one of the row's keys.
    The ABBR is kept only when ITS canon is 4+ (and not the row's own key), else PARKED.
    """
    af = abbr_form(text)
    if not af:
        return [], []
    _shape, abbr, full = af
    kept, parked = [], []
    fk, ak = canon(full), canon(abbr)
    if fk and len(fk) >= ALIAS_MIN and fk not in own_keys:
        kept.append(full)
    if ak and ak not in own_keys and ak != fk:
        (kept if len(ak) >= ALIAS_MIN else parked).append(abbr)
    return kept, parked


def abbr_row(text, head_name):
    """(display, kept, parked) for a ONE-entity line whose head is `head_name`.

    The display is the head, unless the head is a forward ABBR under the alias floor and the full
    name clears it: then the row is keyed on the FULL NAME and the short ABBR is parked (a 3-letter
    blocked key is a skeleton key).
    """
    af = abbr_form(text)
    display = head_name
    if af and af[0] == "fwd" and len(canon(head_name)) < ALIAS_MIN and len(canon(af[2])) >= ALIAS_MIN \
            and canon(head_name) == canon(af[1]):
        display = af[2]
    own = {canon(display)} | {canon(a) for a in alias_parts(display)[0]}
    kept, parked = abbr_aliases(text, own)
    return display, kept, parked


# ── PROVENANCE, CARRIED FROM THE STORE THAT OWNS IT ─────────────────────────────────────────────
#
# ⚖️ SPLIT THE AUTHORITY. `employers.jsonl` owns identity, status and the filter number;
# `documents/state/company.jsonl` owns history and provenance. The split only works if each store
# can ASK the other for the half it does not own, so this reads state's provenance and stamps it
# onto the registry row.
#
# 📊 WHY IT IS WORTH CARRYING, stated at the strength the data supports. On the install measured,
# state held 4,045 events, every one with an `as_of`. 1,333 of them, 33%, carry a git SHA in
# `as_of_source`; the other 2,712 say `authored`, which means the date was read off the text rather
# than off the repo.
# ⚠️ An earlier version of this comment said "every one with a git SHA". That was wrong by a factor
# of three, and it was the kind of wrong that makes a store look more trustworthy than it is. The
# registry's own `ruled_on` is a date the prose asserts about itself; a git SHA is a fact about when
# the line entered the repo. Only a third of these are the stronger kind, and the field says which.
#
# ⛔ A LINE NUMBER TRAVELS WITH ITS FILE OR IT MEANS NOTHING. State's rows span dozens of source
# files, so `source_line: 42` alone is not a citation. The first version of this carried the line
# and dropped the file, and a row came out reading `state_source_line: 42` beside
# `source: blocked-employers-list.md:1768`, two numbers that look like they disagree and are simply
# about different documents. A receipt cites a NAME.
#
# ⛔ IT DOES NOT OVERWRITE `source` OR `ruled_on`. Those are the seeder's own reading of the bullet
# and they answer a different question (which line did this entity come from, and what date does
# that line assert). Provenance is added alongside, never on top, so a disagreement between the two
# stays visible instead of being resolved by whichever ran last.
#
# ⛔ FIELD-LEVEL LAST-WRITE-WINS, ordered by `recorded_at`, the same rule
# `registry_equivalence.reduce_events` uses and for the same reason: a later event that does not
# MENTION a field has not retracted it. Row-level last-write-wins over that store answers 17 blocked
# instead of 1,287.
PROV_FIELDS = ("as_of", "as_of_source", "source_file", "source_line")
STATE_COMPANY = os.path.join(REPO, "documents", "state", "company.jsonl")


def state_provenance(path=None):
    """key -> {as_of, as_of_source, source_line}, merged per FIELD over the event log."""
    out = {}
    try:
        rows = []
        with open(path or STATE_COMPANY, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("kind") == "company" and r.get("key"):
                    rows.append(r)
    except OSError:
        return {}
    rows.sort(key=lambda r: (r.get("recorded_at") or "", r.get("source_line") or 0))
    for r in rows:
        cur = out.setdefault(r["key"], {})
        for f in PROV_FIELDS:
            v = r.get(f)
            if v not in (None, "", [], {}):
                cur[f] = v
    return out


def attach_provenance(entities, prov=None):
    """Stamp state's provenance onto each registry row. Returns (matched, via_alias)."""
    prov = state_provenance() if prov is None else prov
    matched = via_alias = 0
    for k, row in entities.items():
        p = prov.get(k)
        if p is None:
            # ⚠️ TRY THE ALIASES. Dozens of entities match only through one, because the registry's
            # key is the fused `A/B` string the source line spells and state recorded the halves.
            for a in row.get("aliases") or ():
                p = prov.get(canon(a))
                if p:
                    via_alias += 1
                    break
        if not p:
            continue
        matched += 1
        row["as_of"] = p.get("as_of")
        row["as_of_source"] = p.get("as_of_source")
        # One field, `file:line`, so the number can never be read without the document it indexes.
        _f, _l = p.get("source_file"), p.get("source_line")
        row["state_source"] = f"{_f}:{_l}" if _f and _l else (_f or None)
    return matched, via_alias


def scan():
    raw = open(SRC, encoding="utf-8", errors="ignore").read().split("\n")
    section, heading = None, None
    entities, notes, parked_aliases = {}, [], []
    for i, line in enumerate(raw, 1):
        s = line.strip()
        m = SECTION.match(s)
        if m:
            section = {"filter": int(m.group(1)), "label": m.group(2)}
            continue
        h = HEADING.match(s)
        if h:
            heading = h.group(1)
            continue
        if not s or not s.startswith(("-", "*", "|")):
            continue
        exonerated = bool(EXONERATED.search(s.lower()))
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not cells or set(cells[0]) <= set("-: "):
                continue
            names = _head_names(cells[0], bold_line=cells[0].startswith("**"))
        else:
            names = _head_names(s, bold_line=s.startswith("**"))
        d = DATE.search(s)
        # ── RENAME CAPTURES, attributed by how many entities this line declares ───────────────
        # ⛔ ATTRIBUTION IS THE RISK, not extraction. A rename marker says "this entity is also
        # called X", and on a middot line declaring six companies there is no way to know WHICH one
        # it means. Guessing would alias a name onto the wrong employer and block a company on
        # another company's ruling, which is the exact false-block class the registry exists to
        # abolish. So: one declared name → attribute; more than one → park every capture with its
        # source line, visible and not blocking; zero → harvest nothing.
        # 📊 Measured: zero live lines hit the multi-entity branch, so its only coverage is a
        # fabricated test fixture, and the test says so.
        _rn_kept, _rn_parked = [], []
        _ab_kept, _ab_parked = [], []
        if len(names) == 1:
            # Q29a: `ABBR (Full Name)`. A short forward ABBR head re-keys the row on the full name.
            _disp, _ab_kept, _ab_parked = abbr_row(s, names[0])
            names = [_disp]
            _own = {canon(names[0])} | {canon(a) for a in alias_parts(names[0])[0]}
            _rn_kept, _rn_parked = rename_aliases(s, _own)
            _rn_kept = _rn_kept + [a for a in _ab_kept if canon(a) not in {canon(x) for x in _rn_kept}]
        elif len(names) > 1:
            _amb, _amb_parked = rename_aliases(s)
            for _p in _amb + _amb_parked:
                parked_aliases.append({
                    "key": canon(_p), "display": _p,
                    "reason": "rename marker on a multi-entity line, attribution ambiguous",
                    "parent": canon(names[0]), "source": f"blocked-employers-list.md:{i}",
                })
        for _p in _rn_parked:
            parked_aliases.append({
                "key": canon(_p), "display": _p, "reason": "rename alias under 4 chars",
                "parent": canon(names[0]), "source": f"blocked-employers-list.md:{i}",
            })
        for _p in _ab_parked:
            parked_aliases.append({
                "key": canon(_p), "display": _p, "reason": "abbreviation under 4 chars",
                "parent": canon(names[0]), "source": f"blocked-employers-list.md:{i}",
            })

        for name in names:
            k = canon(name)
            if not k or len(k) < 2:
                continue
            # ⚖️ EXONERATION WINS FOR THIS LINE. The file carries explicit "NOT blocked" notes, and
            # harvesting their names is how documenting an exception creates the thing it excepted.
            status = "cleared" if exonerated else "blocked"
            # BUG-246: a cleared/PASS row carries no filter number at all — a filter code names a
            # reason for a DROP, and a company that was NOT dropped has no drop reason to name,
            # regardless of which tier below would have produced one.
            _filt_num, _filt_label = (None, None) if status == "cleared" else _resolve_filter(s, section)
            _al, _parked = alias_parts(name)
            # Rename captures join the slash/comma parts. Only reachable when this line declared
            # exactly ONE entity, so `_rn_kept` is empty on every multi-entity line by construction.
            _al = _al + [a for a in _rn_kept if canon(a) != k and canon(a) not in {canon(x) for x in _al}]
            for _p in _parked:
                parked_aliases.append({
                    "key": canon(_p), "display": _p, "reason": "alias part under 4 chars",
                    "parent": k, "source": f"blocked-employers-list.md:{i}",
                })
            row = entities.get(k)
            if row is None:
                entities[k] = {
                    "key": k, "display": name, "aliases": list(_al), "status": status,
                    "filter": _filt_num,
                    "filter_label": _filt_label,
                    "ruled_on": d.group(1) if d else None,
                    "source": f"seed:blocked-employers-list.md:{i}",
                }
            else:
                # 🔴 THE LAST RULING WINS, IN BOTH DIRECTIONS. This used to read
                # `if status == "cleared"`, so a clearance won PERMANENTLY and no later line could
                # restore a block. One company was parked early as "NOT blocked … pending a call"
                # and ruled 10 days later against a named hard filter. The later ruling never landed
                # and the company read CLEARED against a filter it had failed.
                # 📊 Blast radius measured before shipping: of the 7 cleared entities, exactly ONE
                # had a later name-position mention. No other row moved.
                # ⚠️ `source` still names where the entity was first declared; `status_source` names
                # the line that decided the status, so a flip is never anonymous.
                if status != row["status"]:
                    row["status"] = status
                    row["status_source"] = f"blocked-employers-list.md:{i}"
                    if d:
                        row["ruled_on"] = d.group(1)
                    # BUG-246: a flip TO cleared drops any filter number the row was carrying; a
                    # flip TO blocked adopts this line's own resolved filter if none is set yet.
                    if status == "cleared":
                        row["filter"] = None
                        row["filter_label"] = None
                    elif not row.get("filter"):
                        row["filter"], row["filter_label"] = _filt_num, _filt_label
                if name != row["display"] and name not in row["aliases"]:
                    row["aliases"].append(name)
                for _a in _al:
                    if _a not in row["aliases"]:
                        row["aliases"].append(_a)
            notes.append({
                "key": k, "ts": d.group(1) if d else None,
                "kind": "exoneration" if exonerated else "screen",
                "text": s, "source": f"blocked-employers-list.md:{i}",
            })
    return entities, notes, parked_aliases


def main():
    dry = "--dry-run" in sys.argv
    if not os.path.exists(SRC):
        print(f"no blocked list to migrate: {SRC}")
        print("nothing to seed. The prose path stays in use and nothing changes.")
        return 2
    entities, notes, parked_aliases = scan()
    declared = set(entities)
    harvested = set(blocked_keys_from_list(SRC))

    gap = harvested - declared
    debris = {k for k in gap if any(c.isdigit() for c in k)}
    # Everything left appeared only in prose but reads like a proper noun. PARKED, never dropped.
    parked = sorted(gap - debris)

    raw = open(SRC, encoding="utf-8", errors="ignore").read().split("\n")
    queue = []
    for k in parked:
        line_no = next((i for i, l in enumerate(raw, 1) if k in canon(l)), None)
        queue.append({
            "key": k, "status": "unresolved",
            "why": "appeared only in PROSE, never in a name position",
            "src_line": line_no,
            "context": (raw[line_no - 1].strip()[:300] if line_no else None),
        })
    # ⛔ THE SHORT ALIAS PARTS ARE PARKED HERE, NOT DROPPED. Three-character initialisms are under
    # the 4-character floor, so aliasing them would make a 3-letter string a skeleton key across the
    # whole pool. They stay VISIBLE with their parent and source line: nothing is dropped on a
    # heuristic, and a parked row does not block.
    for pa in parked_aliases:
        queue.append({
            "key": pa["key"], "status": "unresolved",
            "why": f"{pa.get('reason') or f'alias part under {ALIAS_MIN} chars, too short to alias'} "
                   f"(parent: {pa['parent']})",
            "display": pa["display"], "parent": pa["parent"],
            "src_line": int(pa["source"].rsplit(":", 1)[1]),
            "context": None,
        })

    print(f"source            : {SRC}  ({len(raw):,} lines)")
    print(f"declared entities : {len(declared):,}   (name position: bullet head, table cell, middot)")
    print(f"  blocking        : {sum(1 for r in entities.values() if r['status']=='blocked'):,}")
    print(f"  cleared         : {sum(1 for r in entities.values() if r['status']=='cleared'):,}")
    print(f"notes             : {len(notes):,}")
    print(f"old harvest       : {len(harvested):,}  -> registry is "
          f"{len(harvested)-len(declared):,} smaller")
    print(f"  digit debris    : {len(debris):,}  DISCARDED (salary fragments, reported not hidden)")
    # ⛔ THE NAMES, NOT JUST THE COUNT (2026-08-09). This line claimed "reported not hidden" while
    # printing a bare number, and a number is not a report. A digit-bearing key that is a REAL
    # employer (a name like Q9Fakeco) would be discarded here and appear to the reader
    # as one increment. Confirming the current set was all noise took four filtering passes and a
    # targeted search for known digit-named companies; nobody does that from a count.
    # ⚠️ FULL LIST, NEVER A SAMPLE. A truncated list re-creates the exact problem: the one name that
    # matters is the one past the cutoff. Reported from a second install.
    if debris:
        _d = sorted(debris)
        for _j in range(0, len(_d), 6):
            print("                    " + " · ".join(_d[_j:_j + 6]))
    _prov_matched, _prov_alias = attach_provenance(entities)
    _alias_ct = sum(len(r["aliases"]) for r in entities.values())
    print(f"  aliases           : {_alias_ct:,}  (A/B and A, B, C parts resolved onto the same row)")
    _sha = sum(1 for r in entities.values() if str(r.get("as_of_source") or "").startswith("git:"))
    print(f"  provenance carried: {_prov_matched:,} of {len(entities):,} entities got as_of + a "
          f"sourced citation from state ({_prov_alias} via an alias)")
    print(f"    of those, {_sha:,} carry a git SHA; the rest are dates the prose asserts")
    print(f"  parked for review: {len(queue):,}  NOT blocking, each with its source line")
    # Q29a: a short abbreviation is parked, never aliased. Printed IN FULL so it is visible.
    _abp = [pa for pa in parked_aliases if pa.get("reason") == "abbreviation under 4 chars"]
    if _abp:
        print(f"  abbreviations parked (under {ALIAS_MIN} chars, NOT aliased): "
              + " · ".join(f"{pa['display']} (parent {pa['parent']}, {pa['source']})" for pa in _abp))
    if dry:
        print("\n--dry-run: nothing written")
        return 0
    os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
    for path, rows in ((REGISTRY, list(entities.values())), (NOTES, notes), (QUEUE, queue)):
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"wrote {len(rows):,} rows -> {os.path.relpath(path, REPO)}")
    print("⛔ blocked-employers-list.md was NOT modified.")
    print("↻ the registry is now the screening authority. Prove it with: "
          "python3 scripts/registry_equivalence.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
