#!/usr/bin/env python3
"""rank_criteria.py — rank the day's candidate companies (and warm contacts) by YOUR employer criteria.

WHY. A daily shortlist that shows the FIRST few rows of a board in file order is not a ranking — it
makes the pick arbitrary. This scores the current pool against your weighted employer-criteria matrix
(the small set of factors that actually decide whether a company is worth your time — culture/WLB,
retention, leadership stability, calm pace) and prints the top N with a per-criterion breakdown, so the
pick is informed. The WEIGHTS live in kit_config.CRITERIA_WEIGHTS — re-tune there, never in this file.

POOL ("board, topped up"): the vetted green board first, and when it holds fewer than N live rows,
fill from the agent-screened BANKED files, then from the raw discovery board (tagged as needing a full
screen). SENT / blocked / already-worked companies are excluded — the point is who to work NEXT.

WHAT IT SCORES — and, honestly, what it does not. The score is computed from the signals actually
RECORDED on the board (culture sub-ratings, remote, PE, boss, praise), mapped to the matching
criteria-matrix rows. Most criteria (IC track, vacation, meeting load, ...) are NOT recorded per row,
so they are shown "not scored" rather than counted as zero — which would unfairly sink a company for a
fact nobody wrote down. A full criterion-by-criterion workup is an interview-stage scorecard, not this.

RANKING MODEL — culture confidence FIRST, then criteria points. Leadership/culture stability is the
top-weighted rule, so a verified-clean row outranks an unproven one regardless of a raw number. Within
a confidence tier, by criteria points.

Usage:
    scripts/rank_criteria.py                     # print the ranked top 10 companies
    scripts/rank_criteria.py --n 15              # a different depth
    scripts/rank_criteria.py --brief             # compact (used by a session-start briefing)
    scripts/rank_criteria.py --pool people       # "who can help first" (likely-boss scoring v2)
    scripts/rank_criteria.py --weights           # inspect the current learned person-weights row
    scripts/rank_criteria.py --recompute-weights # the ONLY writer of the person-weights store
    scripts/rank_criteria.py --targets           # emit a 3-company warm-ask trio (mail-draft --targets)
    scripts/rank_criteria.py --targets --verify  # + probe each company's live ATS for remote reality
Exit: 0 always (a briefing must never block a session).
"""
import collections
import os
import json
import re
import sys
from datetime import date as _date

REPO = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The column contract and the durable store. Same import-never-copy rule as the veto lists below:
# canonical column names live in schema.py so a board table gaining a column cannot shift a reader's
# indices, and state.py owns the ONE recency rule every reader funnels through.
import schema  # noqa: E402
import state  # noqa: E402
# BUG-135: the remote veto reads the ✅/🔴 verdict marker first, and only falls back to a keyword scan
# when no marker is present — and that fallback must be NEGATION-AWARE (a disqualifier offset by a
# remote-confirm phrase is not a fail). Reuse check_screen_gate's canonical lists so the two never
# drift; if it cannot be imported, degrade to marker-only (never silently re-add the naive scan).
_LEGACY_REMOTE_DISQUAL = [r"hybrid", r"onsite required", r"relocat", r"\brto\b", r"in[- ]office"]
try:
    from check_screen_gate import REMOTE_DISQUAL as _REMOTE_DISQUAL  # noqa: E402
except Exception:
    _REMOTE_DISQUAL = _LEGACY_REMOTE_DISQUAL
# The tier → rung → ask contract. Imported, never copied: check_preview.py refuses a wrong-shaped ask
# from the SAME table this recommends from, and two copies of one rule drift the first time either is
# fixed. Degrades to a stub when the closeness store has never been built, so a partner who has not
# run the levelling interview still gets a ranked list.
try:
    import closeness  # noqa: E402
except Exception:  # pragma: no cover — the ranker must never fail to import
    closeness = None
# SEGMENT + EMPLOYER EVIDENCE. A ranker that scores people by TITLE alone will offer you a "likely
# boss" who could never hire you, because the title column cannot tell a landscaping owner from a
# Head of Product. contact_signals answers what the COMPANY does, and supplies the evidence tier
# that keeps an unidentifiable employer from floating to the top. Same degrade-to-None contract as
# closeness above: the ranker must never fail to import.
try:
    import contact_signals  # noqa: E402
except Exception:  # pragma: no cover
    contact_signals = None

# ── deal-breaker INDUSTRY veto vocabulary + PE-ownership flag (from kit_config) ─────────────────
# Reuse the CANONICAL screening vocabulary rather than copy it. A second copy would drift from this
# one, and a drifted veto list is how a deal-breaker company reaches a surface it should never reach
# — which is exactly the class of bug that put a crypto company at #7 on this script's first run,
# because a top-up path applied no veto screen. INDUSTRY_VETO and PE_FLAG are the SAME lists
# check_screen_gate.py and screen_sweep.py use; edit them in kit_config, not here.
try:
    from kit_config import INDUSTRY_VETO, PE_FLAG
except Exception:  # standalone fallback — generic examples; [] would silently pass everything
    INDUSTRY_VETO = [r"\bcrypto\b", r"\bweb3\b", r"\bgambling\b", r"\bcasino\b", r"sportsbook",
                     r"\bdefense\b", r"\bmilitary\b", r"law[- ]enforcement", r"\bpolicing\b"]
    PE_FLAG = [r"private equity", r"\bpe[- ]owned", r"\bpe[- ]backed", r"leveraged buyout",
               r"\blbo\b", r"\bbuyout\b", r"portfolio co"]

# VETO_EMPLOYERS + the MATCHER itself — one implementation, imported from check_screen_gate.
#
# VETO_EMPLOYERS names companies whose INDUSTRY is a deal-breaker but whose NAME contains none of the
# banned WORDS in INDUSTRY_VETO. The keyword list only catches a company that DESCRIBES itself
# ("defense", "crypto"); it cannot catch one that is merely NAMED. In the people pool the only signal
# IS an employer name, so a crypto exchange or a defense prime comes back "clean" and ranks unless it
# is listed. Edit the list in kit_config, never here.
#
# ⚠️ THE MATCHER IS IMPORTED, NOT RE-IMPLEMENTED, and that is the whole point. check_screen_gate adds
# a third pass this file used to lack: names SQUASHED to letters and digits. A curated veto list can
# only catch the spelling someone typed, and scrapers do not preserve spacing — a two-word
# law-enforcement vendor stored by a sweep with the space dropped sat in the "passes" list on a
# whitespace difference alone, while the same name sat verbatim in the veto list. One matcher, one
# place. `is_artifact` comes along for the same reason: the pool accumulates page titles and ATS
# boilerplate that are not employers at all, and the rule for what counts as a company belongs in the
# same module as the rule for what counts as vetoed.
try:
    from check_screen_gate import VETO_EMPLOYERS, veto_hits, is_artifact, industry_resolution
except Exception:  # standalone fallback — no squashed pass, and no artifact filter
    VETO_EMPLOYERS = []

    def veto_hits(name, text=""):
        low = f"{name or ''} {text or ''}".lower()
        return sorted({re.search(v, low).group(0) for v in INDUSTRY_VETO if re.search(v, low)})

    def is_artifact(name):
        return False

    def industry_resolution(name, text=""):
        # ⛔ THE FALLBACK MUST NOT UPGRADE. With no gate module there is no segment cache either,
        # so every company here is genuinely unresolved unless a veto term fired. Answering
        # "resolved" would let the mark disappear exactly where the least is known.
        return ("vetoed", ", ".join(veto_hits(name, text))) if veto_hits(name, text) \
            else ("unknown", None)

# ── SCORING WEIGHTS — YOUR employer-criteria matrix, parameterized ──────────────────────────────
# The weights that turn recorded signals into a rank. These are the ONE thing a different user must
# re-tune, so they live in kit_config (imported here); this file only supplies working defaults.
# Reweight in kit_config.CRITERIA_WEIGHTS — leadership stability defaults to the top weight because a
# bad-leadership exit is the most expensive miss. Do NOT edit the numbers here.
try:
    from kit_config import (CRITERIA_WEIGHTS, WLB_FLOOR, WLB_RANGE, LEADERSHIP_CLEAN_TIER,
                            LEADERSHIP_CAVEAT_FRACTION, LEADERSHIP_UNPROVEN_FRACTION,
                            CONFIDENCE_MULTIPLIER)
except Exception:
    CRITERIA_WEIGHTS = {
        "wlb": 10.0,                   # work-life-balance rating
        "retention": 10.0,             # %recommend / retention
        "leadership_stability": 10.0,  # leadership/culture stability — the top-weighted criterion
        "calm_pace": 8.0,              # calm / mature / bootstrapped pace
        "boss_reachable": 3.0,         # readiness tiebreak: a boss with an email on file
        "sourced_praise": 2.0,         # readiness tiebreak: a sourced praise link
    }
    WLB_FLOOR = 3.0             # below this WLB rating = veto-level drop
    WLB_RANGE = 2.0            # full WLB weight is reached at WLB_FLOOR + WLB_RANGE
    LEADERSHIP_CLEAN_TIER = 3  # culture-confidence tier at/above which leadership scores full weight
    LEADERSHIP_CAVEAT_FRACTION = 0.3    # turmoil/reorg flagged → this fraction of the leadership weight
    LEADERSHIP_UNPROVEN_FRACTION = 0.5  # unproven screen → this fraction of the leadership weight
    CONFIDENCE_MULTIPLIER = {4: 1.0, 3: 0.9, 2: 0.75, 1: 0.6, 0: 0.5}

# The doc your criteria matrix lives in, cited in the printed headers. Generic default; override it
# in kit_config if your file lives elsewhere.
try:
    from kit_config import CRITERIA_MATRIX_DOC
except Exception:
    CRITERIA_MATRIX_DOC = "documents/employer-criteria-matrix.md"


def _industry_vetoed(text):
    """Deal-breaker industry check, by DESCRIPTION and by NAME.

    INDUSTRY_VETO catches a company that describes itself ("defense", "crypto"). That works on the
    company board, where every row carries lane text. It does NOTHING in the people pool, where the
    only signal is an employer NAME — so a crypto exchange and a law-enforcement-software vendor both
    come back clean and rank, and a social-media giant sits mid-list on a network-sourced company
    list. VETO_EMPLOYERS closes that by name.

    ⚠️ DELEGATES to check_screen_gate.veto_hits, which adds the squashed multi-word pass. This
    function kept its name because several call sites read it, but it must NOT re-implement the
    matching — a second copy of a veto rule drifts the first time either side is fixed, and a drifted
    veto is how an explicitly listed deal-breaker company passes a gate on a whitespace difference.
    One matcher, one place."""
    return veto_hits(text)


def rd(path):
    f = os.path.join(REPO, path)
    return open(f, encoding="utf-8", errors="ignore").read() if os.path.exists(f) else ""


# ── confidence tiers (the primary sort key) ─────────────────────────────────────────────────
# Derived from the Culture cell's leading marker + text. Higher tier = more trustworthy screen.
# This is the "keep the culture screen" philosophy made into a sort order.
TIER = {"verified": 4, "screened": 3, "soft": 2, "thin": 1, "unproven": 0}
TIER_LABEL = {4: "🔬 verified", 3: "🟢 screened", 2: "🟡 soft", 1: "💡 founder-signal", 0: "⚪ unproven"}


def _tier(culture):
    c = culture.lower()
    if "🔬" in culture or "verified" in c:
        return 4
    if "⚪" in culture or "unproven" in c or "wrong-co" in c:
        return 0
    if "thin" in c or "founder-signal" in c or "founder" in c and "signal" in c:
        return 1
    if "🟡" in culture or "soft" in c:
        return 2
    if "🟢" in culture:
        return 3
    return 1  # unmarked → treat as low-confidence, never as verified


def _num(pattern, text, default=None):
    m = re.search(pattern, text, re.I)
    return float(m.group(1)) if m else default


# ── PARSE ONCE PER FILE STATE ─────────────────────────────────────────────────────────────────
#
# 📊 This function re-read and re-parsed the whole blocked list on EVERY membership test, which is
# once per candidate. A profile of the sign-in briefing put 16.2 of its 22.9 seconds here: 1,990
# calls, feeding 2.66 million calls to `canon()`, to answer 2,056 questions about a file that never
# changed between them. `screen_sweep.blocked_keys_from_list` carries the same cache for the same
# reason; this is its twin and it was left uncached.
#
# ⛔ KEYED ON (path, mtime, size), NOT a bare lru_cache. The blocked list IS written inside a
# session when a screening run records a drop, and a cache blind to that would hand back a stale
# spelling for a company blocked moments earlier.
_BLOCKED_NAMES_CACHE = {}


def _blocked_names_by_key():
    """canon key → the RAW blocked name it came from, so an alias test can see the real words.

    `blocked_keys_from_list()` returns canon keys only ("otherco financial" → "othercofinancial"),
    which cannot be split back into words. This re-parses the same two bullet shapes for DISPLAY
    names, and is deliberately a READER of the same file rather than a second source of truth about
    who is blocked: membership is still decided by `blocked_keys_from_list()`; this only supplies
    the spelling.
    """
    import re as _re
    path = os.path.join(REPO, "documents", "blocked-employers-list.md")
    try:
        st = os.stat(path)
        stamp = (path, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
    except OSError:
        return {}
    hit = _BLOCKED_NAMES_CACHE.get(stamp)
    if hit is not None:
        return hit
    out = {}
    try:
        from screen_sweep import canon
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if not line.lstrip().startswith("-"):
                    continue
                body = line.lstrip()[1:].strip()
                m = _re.match(r"\*\*(.+?)\*\*", body) or \
                    _re.match(r"([A-Za-z][\w&.\-' ]{1,44}?)\s*[(:—]", body)
                if not m:
                    continue
                nm = m.group(1).strip()
                k = canon(nm)
                if k:
                    out.setdefault(k, nm)
    except Exception:
        return {}
    if len(_BLOCKED_NAMES_CACHE) > 8:
        _BLOCKED_NAMES_CACHE.clear()
    _BLOCKED_NAMES_CACHE[stamp] = out
    return out


class _BlockedText(str):
    """The blocked-list text, whose `in` test is WORD-BOUNDED rather than raw substring.

    🔴 DEFECT FIXED. This used to be a bare lowercased string, and every caller asked
    `if low in blocked`. That is a raw substring test against a 600-line document, so ANY company
    whose name appears inside ANY word in the file was silently dropped from the entire ranked pool.
    Silently: nothing printed, no veto line, the company simply never appeared.

    Confirmed casualties at the time of the fix, several of them fresh survivors from that same
    day's discovery sweeps: any company whose name is a substring of a common word. A five-letter
    brand can hide inside "contract"; four-letter ones hide inside almost anything. The expensive
    case was a company with a live remote senior req above the comp floor, invisible to the ranker
    only because the blocked list happened to use an ordinary English word.

    The original comment read "substring test is enough here; the row is already board-vetted", and
    that assumption was true when only hand-vetted board rows flowed through. It stopped being true
    once `banked_topup()` began feeding in agent-screened names nobody had eyeballed, which is
    exactly the class of short brand name that collides.

    `check_dup.py` carries THREE separate dated guards against this same false-positive shape. This
    module never got them. Subclassing str keeps every existing `low in blocked` call site working
    while changing what the test means.

    ⚠️ WORD BOUNDARIES ALONE WERE NOT ENOUGH, and the second cut is why this reads the way it does.
    Bounding on alphanumerics freed the longest of them but still killed three short brands at once,
    all matched inside a SINGLE quoted phrase in another company's entry (a JD excerpt that happened
    to contain three ordinary words). Matching brand names against hundreds of lines of PROSE will
    always collide,
    because the file is written for humans and is full of quotes, reasons and JD excerpts.

    The fix is two-layer, and the second layer is the one that took a second attempt:

      1. PARSED NAMES via `screen_sweep.blocked_keys_from_list()`, which already knows the file's two
         bullet shapes. Exact, canon-normalized, so ", Inc." cannot dodge it.
      2. TEXT, with every QUOTED SPAN STRIPPED FIRST. Parsed names alone lost 9 real blocks
         (several live in one comma list; others sit in middot lists after a colon). Length
         thresholds were tried and rejected: "engine" (6 chars) is a false positive and "docker"
         (6) is real, so length does not separate them.
    """

    # Corporate qualifiers: the words that can trail a parent brand in a legal name without
    # changing WHO the company is. Used by the entity-variant alias layer below.
    _QUALIFIERS = frozenset({
        "inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "sas",
        "sa", "ag", "gmbh", "bv", "nv", "ab", "oy", "pty", "srl", "spa",
        "group", "holdings", "holding", "global", "international", "worldwide",
        "financial", "finance", "capital", "technologies", "technology", "tech", "systems",
        "solutions", "services", "software", "labs", "digital", "data", "health", "healthcare",
        "care", "security", "networks", "media", "partners", "ventures", "industries",
        # ⚠️ KEEP EACH PLURAL AND ITS SINGULAR TOGETHER. Upstream shipped seven plurals without
        # their singular forms, so a legal name ending "… Service SAS" or "… Data Lab" never
        # aliased to its parent brand and two blocked companies ranked under their bare names. A
        # qualifier list that carries "services" and not "service" is a coin flip on spelling.
        "service", "solution", "system", "lab", "partner", "venture", "network", "industry",
    })

    def __contains__(self, needle):
        n = (needle or "").strip().lower()
        if not n:
            return False
        try:
            from screen_sweep import canon, blocked_keys_from_list
            k = canon(n)
            if not k:
                return False
            keys = blocked_keys_from_list()
            if k in keys:
                return True
            # ── ENTITY-VARIANT ALIAS, added after a LIVE leak upstream ──────────────────────
            # The list records a company under its LEGAL name; the sweeps emit the BRAND. Exact
            # canon matching cannot bridge that, so a blocked company gets offered as a candidate.
            # Shape of the receipt: "SOMECO SERVICE SAS" is blocked over one of its government
            # subsidiaries, and plain "SomeCo" ranks on the board anyway. "Otherco Financial" is
            # blocked; "Otherco" is not.
            #
            # ⛔ THIS IS NOT A RAW TEXT TEST OVER THE FILE, AND THE EVIDENCE SAYS NOT TO BUILD ONE.
            # A text test blocks a company that is not blocked at all, because its name appears once
            # as PROSE inside another company's reason ("same failure class as Thirdco"). Stripping
            # quoted spans does not help, because such a mention is usually unquoted. Matching brand
            # names against reasons re-creates the exact false-positive class that this whole
            # two-layer design exists to avoid.
            #
            # The rule instead: the needle must be a WHOLE-WORD leading run of a blocked entry, and
            # every remaining word must be a corporate QUALIFIER. Word-level, so a three-letter
            # brand never matches inside a longer ordinary word.
            words = [w for w in re.split(r"[^a-z0-9]+", n) if w]
            if not words:
                return False
            for key, raw in _blocked_names_by_key().items():
                other = [w for w in re.split(r"[^a-z0-9]+", raw.lower()) if w]
                if len(other) <= len(words) or other[:len(words)] != words:
                    continue
                if all(w in _BlockedText._QUALIFIERS for w in other[len(words):]):
                    return True
            return False
        except Exception:
            # FAIL CLOSED on a broken import. A ranker that cannot read the blocked list must not
            # quietly start offering blocked companies; an empty pool is a visible failure, a
            # silently unblocked one is not.
            return True


def blocked_set():
    """Word-bounded blocked membership. See `_BlockedText` for why it is not a plain str.

    ⚠️ THE TEXT IS NOT THE AUTHORITY AND IS NOT READ. `_BlockedText.__contains__` answers entirely
    from `screen_sweep.blocked_keys_from_list()`, i.e. the REGISTRY. Proven by wrapping a blocked
    list that names NOBODY and asking for a registry key: it still answers True. That is the ruling
    working as intended — the registry is the screening authority and `blocked-employers-list.md` is
    a generated render, read by humans and parsed by nothing — but the old signature said otherwise,
    so a SEEDED or hand-appended list looked authoritative and silently was not. The text is still
    passed because `_BlockedText` subclasses `str` and several call sites use `in`; it is carried,
    never consulted.

    ⛔ DO NOT "FIX" THIS BY MAKING THE TEXT A MATCH SURFACE. That re-creates the false-block class
    that hid a batch of ordinary short brand names, and it would block a company that is not blocked
    at all whenever its name appears once as prose inside another company's reason ("same failure
    class as Thirdco").

    🔬 A DIVERGENCE WARNING WAS TRIED HERE AND REJECTED ON MEASUREMENT. Comparing the markdown's
    names against the registry to catch "a block that never landed" reported dozens of divergences,
    nearly all of them prose fragments the scraper lifted out of reason text (review counts, city
    names, industry words). Routing them through the shipped `is_artifact` removed exactly one. A
    warning that is almost entirely noise trains its reader to ignore it, and the reason it cannot
    be built is the reason the registry exists: the markdown is not a parseable source. The place to
    catch an unlanded block is at the WRITE, via `employers.declare_blocked`.
    """
    return _BlockedText(rd("documents/blocked-employers-list.md").lower())


def burned_targets():
    """Companies ALREADY NAMED in a warm-ask trio. A company burns after ONE naming.

    This is a boss-hunt-method guard, not a nicety. The method is explicit that you do NOT converge
    several approaches on one organization: pick the single most-likely direct boss, try that person,
    give them a week, and only then try someone else. Converging multiple asks on one company is the
    anti-pattern — whether it is several bosses AT the company or several connections referring INTO
    it.

    `done_set()` only catches companies we CONTACTED. A company named in someone ELSE's trio was
    never contacted, so it stays eligible — and the ranker will duly re-offer a company that was
    named to a different connection hours earlier, which reads as careless and spends a second warm
    relationship on the same target. This closes that.

    Source of truth is the send-log `targets` field, which mail-draft.sh writes on every warm send.
    """
    burned = set()
    p = os.path.join(REPO, "documents", "send-log.jsonl")
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                for co in (row.get("targets") or "").split(","):
                    co = co.strip().lower()
                    if co:
                        burned.add(co)
    except Exception:
        pass  # fail OPEN on read error: a missing send-log must not empty the pipeline
    return burned


class _DoneSet(set):
    """Companies already contacted, with ALIAS-AWARE membership.

    🔴 THE DEFECT THIS FIXES. `done_set()` read the prose log and the send-log `targets` field and
    never read the send-log's own `company` column. Measured upstream before the fix: **77 of the
    148 companies with a delivered send were not excluded**, so the ranker and the warm-ask trio
    went on offering them as fresh.

    The second half is spelling. One company was offered as a fresh warm target AFTER an interview
    there and a thank-you sent to someone's address at its own domain: the send log said one form
    of the name, the board said a longer form, and plain set membership cannot see those as one
    company.

    So membership is plain `in` OR **exact equality of the two RESOLVED keys**. `state.resolve()`
    consults recorded aliases, which makes a spelling collapse a RECORDED ruling rather than a
    read-time guess, and an unknown name resolves to None so two unknowns can never match.

    ⛔ NO FUZZY OR CONTAINMENT MATCHING, and that is the design rather than an omission. Substring
    matching on company names is what the blocked-list reader had to be rescued from twice, taking
    a pile of short-named companies down with it. A matcher that guesses is how this set got into
    trouble; more guessing does not get it out.

    Subclassing `set` keeps every existing `co.lower() in done` call site working unchanged.

    ⚠️ FAILS OPEN, opposite to the blocked-list reader, and the asymmetry is deliberate. Blocked
    means "must not send", so an unreadable blocked list must veto everything. Done means "already
    sent", so an unreadable store degrades to plain membership and re-offers a company at worst.
    Failing closed here would empty the pipeline over an unrelated store problem.
    """

    def _resolved(self):
        """Resolved keys of the members, computed ONCE per instance.

        Resolving per membership test would re-resolve every member on every miss, and the
        canonicalizer does a `sys.path.insert` per call, so the hot loop would grow `sys.path` by
        six figures of duplicate entries and slow every later import in the process.
        """
        cache = self.__dict__.get("_keys")
        if cache is None:
            cache = set()
            try:
                for member in set(self):
                    k = state.resolve("company", member)
                    if k:
                        cache.add(k)
            except Exception:
                cache = set()          # fail OPEN: degrade to plain set membership
            self.__dict__["_keys"] = cache
        return cache

    def __contains__(self, needle):
        if set.__contains__(self, needle):
            return True
        n = str(needle or "").strip()
        if not n:
            return False
        try:
            mine = state.resolve("company", n)
            return bool(mine) and mine in self._resolved()
        except Exception:
            return False               # fail OPEN: a broken store re-offers, it does not empty


def done_set():
    """Companies already SENT/contacted OR already burned as a named warm-ask target."""
    done = set()
    for line in rd("outreach_log.md").splitlines():
        if line.startswith("## ") and re.search(r"sent", line, re.I):
            m = re.search(r"·\s*([^·(]+?)\s*(?:\(|·)", line) or \
                re.search(r"^\s*#*\s*\d{4}-\d{2}-\d{2}\s*[—–-]\s*([^(—–\n]+)", line)
            if m:
                done.add(m.group(1).strip().lower())
    done |= burned_targets()
    # The column done_set() never read: companies with a DELIVERED send-log row. Without
    # this, a company you already wrote to can be offered again as a fresh target.
    done |= sent_companies()
    return _DoneSet(done)


def row_offset(cells):
    """green-board.md holds TWO tables with DIFFERENT layouts:
        numbered green board -> | # | Company | Lane | Remote | Culture | Non-PE | Boss | Praise | Status |
        radar table (below)  -> | Company | Lane | Remote | Culture | Non-PE | Boss | Praise | Tier |
    The radar table has no leading '#', so its columns sit one to the LEFT. Reading every row with the
    numbered layout makes a radar row's LANE its company name and checks its CULTURE cell against the
    remote veto — which silently vetoes legitimately-remote radar companies (including ones tagged
    'RADAR (top fit)' on the board itself) and ranks a company under its LANE text as its name. Detect
    per row: a numbered row has a digit in cells[1]."""
    return 1 if len(cells) > 1 and cells[1].strip().isdigit() else 0


def score_board_row(cells, off=1):
    """cells = the split board row; off = 1 for the numbered green board, 0 for the radar table.
    Returns (score_dict) or None if a veto visibly fails.

    ⚠️ POSITIONAL, and kept only for callers that still hold raw cells. `off` encodes an assumption
    that the board has TWO layouts; a mature board grows many more (see scripts/schema.py). Prefer
    `score_board_record()`, which reads the same seven fields by NAME out of the durable state store.
    """
    def col(i):
        return cells[i + off] if len(cells) > i + off else ""
    return _score_fields(col(1), col(2), col(3), col(4), col(5), col(6), col(7))


def score_board_record(rec):
    """Score one durable state-store record. The replacement for `score_board_row`.

    Reads the seven scored fields by canonical NAME via `schema.field()`, so a column inserted into
    any of the board's table shapes cannot shift what gets scored. Same core, same thresholds, same
    veto order as the positional path: this changes WHERE the fields come from, never how they are
    judged.
    """
    payload = rec.get("payload") or {}
    # `name` is the DISPLAY name and `key` is the canonical join key. The pipe-table extractor drops
    # the company CELL from payload and keeps the cleaned name under `name`, so read that; falling
    # back to the key would put a squashed lowercase string in front of a human on every card.
    return _score_fields(
        payload.get("name") or schema.field(payload, "company") or rec.get("key", ""),
        schema.field(payload, "lane"),
        schema.field(payload, "remote"),
        schema.field(payload, "culture"),
        schema.field(payload, "non_pe"),
        schema.field(payload, "boss"),
        schema.field(payload, "praise"),
    )


# ── DESK-ANSWERABLE CRITERIA ─────────────────────────────────────────────────────────────────
#
# ⛔ THE PROBLEM THIS SOLVES, measured rather than assumed. In the tree this shipped from, the board
# held 37 scored companies and **36 of them sat at exactly the same score**. The reasons line on
# every one read the same three things: WLB not scored, recommend-rate not scored, leadership
# unproven. The scorer was not failing to discriminate because its criteria list was too short. It
# was STARVED: those are all CULTURE criteria, `_screened_fields` returns `culture` EMPTY for every
# ledger row on purpose (the review sites block automated readers, so an agent reporting "culture
# clean" may only be reporting "culture unreachable"), and the quick culture peek belongs to the
# human. So the only inputs that could move a screened row were unavailable BY DESIGN, and every
# screened company collapsed to one number.
#
# 📊 THE WASTE THIS RECOVERS. A single screening session recorded comp bands, live product seats,
# reporting lines, ownership shape and IC-versus-management titles for 20 companies, and NONE of it
# reached the score. Companies screened that day against their own job boards ranked identically to
# companies screened weeks earlier on far thinner evidence.
#
# ⚖️ WHY THESE CRITERIA AND NOT EVERY CRITERION. The method this kit follows splits desk work from
# hand-to-hand: company, industry, function and location are answerable from your desk; culture,
# people, comp and travel are "decide once engaged". Most rows in a full criteria matrix are the
# second kind, and scoring those from a desk would be inventing answers. Everything below is a fact
# already printed on a job posting, so it needs no new research and cannot be guessed.
#
# ⛔ ADDITIVE AND TRANSPARENT ONLY. Nothing here subtracts and nothing here VETOES. A missing field
# scores zero and says so in its own reason line, so "unscored" never masquerades as "bad". The hard
# filters stay where they are, in the gates.
#
# 🔧 PARAMETERIZED: the salary floor and target come from `kit_config`, never a hardcoded number.
_IC_TITLE = re.compile(r"\b(senior|sr\.?|staff|principal|lead)\s+(product\s+)?(manager|owner|pm)\b", re.I)
_MGMT_ONLY = re.compile(r"\b(director|head of|vp|vice president|chief)\b", re.I)
_SEAT_TITLE = re.compile(r"product\s+(manager|owner|lead)|head of product", re.I)
_REPORTS_TO_TOP = re.compile(r"report(s|ing)?\s+to\s+the\s+(ceo|founder|cpo|coo)", re.I)
_MONEY = re.compile(r"\$\s?([0-9]{2,3})(?:,([0-9]{3}))?\s?(k\b)?", re.I)

# ⛔ THE FLOOR IS NOT A BAND, and this cost a false positive on the first run. The comp evidence a
# screener writes routinely NAMES the floor while saying the band is unknown: "UNVERIFIED. No band
# in the posting. The $170K floor is unconfirmed." A bare money regex read that floor out of the
# sentence and scored two companies as publishing a band that cleared it, when neither had published
# anything at all. The number was in the text; it was not the employer's number.
_NOT_A_BAND = re.compile(r"\bunverified\b|\bno band\b|\bnot published\b|\bunpublished\b", re.I)
_FLOOR_FIGURE = re.compile(r"\$\s?[0-9]{2,3}(?:,[0-9]{3})?\s?k?\s*(floor|target)\b|"
                           r"\b(floor|target)\s*(is|of|at)?\s*\$\s?[0-9]{2,3}(?:,[0-9]{3})?\s?k?", re.I)


def _salary_floor():
    """(floor, target) from `kit_config.COMP_FLOOR`, the knob the batch screen already uses.

    ⛔ REUSES THE EXISTING KNOB rather than adding a second one. `COMP_FLOOR` already drives the
    mechanical comp screen, and two settings for one fact is how they drift apart. `COMP_FLOOR = 0`
    means "no comp filtering" there, and it means "do not score comp" here, which is the same
    intent expressed once.
    """
    try:
        import kit_config
        floor = int(getattr(kit_config, "COMP_FLOOR", 0) or 0)
        target = int(getattr(kit_config, "COMP_TARGET", 0) or 0)
    except Exception:
        floor, target = 0, 0
    # A target above the floor lets a strong band outscore a merely-adequate one. Derived when
    # unset so the kit works with the single knob most owners will configure.
    return floor, (target or (int(floor * 1.3) if floor else 0))


def _money_max(text):
    """Largest dollar figure in a comp string, normalized to whole dollars. None when absent.

    Refuses the whole field when it declares itself unverified, and strips figures that are
    explicitly the FLOOR or the TARGET rather than the employer's posted band.
    """
    text = text or ""
    if _NOT_A_BAND.search(text):
        return None
    text = _FLOOR_FIGURE.sub(" ", text)
    best = None
    for m in _MONEY.finditer(text):
        head, tail, kilo = m.group(1), m.group(2), m.group(3)
        if tail:
            val = int(head) * 1000 + int(tail)
        elif kilo:
            val = int(head) * 1000
        else:
            continue          # a bare "$93" is not a salary; require thousands or a k suffix
        if val >= 40_000 and (best is None or val > best):
            best = val
    return best


def _desk_points(desk):
    """Points and reason lines from criteria a JOB POSTING already answers. Never vetoes."""
    pts, reasons = 0.0, []
    if not desk:
        return pts, reasons
    comp = str(desk.get("comp") or "")
    pm_req = str(desk.get("pm_req") or "")
    note = str(desk.get("note") or "")
    owner = str(desk.get("ownership") or "")
    floor, target = _salary_floor()

    # Comp against the configured floor. A PUBLISHED band is the strongest desk fact available,
    # because it is the one criterion that otherwise only surfaces after an interview.
    top = _money_max(comp)
    if top is not None and floor:
        if target and top >= target:
            pts += 10; reasons.append(f"comp ${top:,} published, clears the target (10/10)")
        elif top >= floor:
            pts += 7; reasons.append(f"comp ${top:,} published, clears the floor (7/10)")
        else:
            reasons.append(f"comp ${top:,} published, UNDER the floor (0)")
    else:
        reasons.append("comp unpublished (not scored)")

    # IC track. Some owners would rather not formally people-manage; when that is not your
    # preference, set the weight to 0 in kit_config rather than deleting the signal.
    if _IC_TITLE.search(pm_req):
        pts += 8; reasons.append("IC-track seat open (+8)")
    elif _MGMT_ONLY.search(pm_req):
        pts += 2; reasons.append("management title only (+2, partial)")

    # Live product seats — actionability, the same idea as the boss+email readiness point.
    seats = len(set(_SEAT_TITLE.findall(pm_req)))
    if seats:
        p = min(seats * 2, 6)
        pts += p; reasons.append(f"{seats} live product seat kind(s) (+{p})")

    # A named reporting line straight to the top IS the boss hunt, at a company small enough for the
    # chief executive to be the hiring manager.
    if _REPORTS_TO_TOP.search(note + " " + pm_req):
        pts += 4; reasons.append("reporting line to the top named (+4, boss hunt shortened)")

    # Calm pace, read from OWNERSHIP shape rather than culture text.
    # ⛔ ONE AWARD ONLY. `_score_fields` may already grant this from the culture/ownership text, and
    # on the first run one company collected it twice, printing two calm-pace lines on the same row
    # for double the points of a single criterion.
    if desk.get("_calm_already"):
        pass
    elif re.search(r"bootstrap|no funding|founder-owned|angel", owner, re.I):
        pts += 8; reasons.append("bootstrapped or angel-funded (+8, calm pace)")
    elif re.search(r"hypergrowth|founding (pm|product)", note + " " + pm_req, re.I):
        reasons.append("hypergrowth shape flagged (no points)")
    return pts, reasons


def _remote_is_disqualifying(remote):
    """(True, reason) when the recorded remote evidence is a FAIL, else (False, "").

    BUG-135: the recorded field is PROSE the screener wrote, so a clean seat proves itself by NAMING
    the disqualifiers it lacks ("No hybrid, RTO or relocation clause"). Reading topic words vetoed
    exactly those confirmations. Read the ✅/🔴 VERDICT MARKER the field carries instead; only when
    NEITHER marker is present do we fall back to check_screen_gate's NEGATION-AWARE scan (a
    disqualifier that no remote-confirm phrase offsets). A pattern that matches the TOPIC is not a
    check on the VERDICT."""
    text = remote or ""
    if "🔴" in text:
        return True, text.strip() or "marked disqualified"
    if "✅" in text:
        return False, ""                       # marked-clean: trust the screener's remote verdict
    low = text.lower()
    if any(re.search(d, low) for d in _REMOTE_DISQUAL):
        return True, text.strip() or "disqualifying arrangement (unmarked)"
    if "remote" not in low:
        return True, text.strip() or "not confirmed"
    return False, ""


def _score_fields(company, lane, remote, culture, nonpe, boss, praise, desk=None):
    """The scoring core, shared by the positional and the state-store readers.

    Extracted so the two paths cannot drift. Every threshold, weight and veto below is unchanged
    from the positional version it came from.
    """

    reasons = []   # per-criterion breakdown lines (matrix-referenced)
    W = CRITERIA_WEIGHTS

    # ── VETOES — a visible failure excludes the row entirely ──
    _v = _industry_vetoed(lane + " " + company)
    if _v:
        return None, f"veto industry ({', '.join(_v)})"
    _rem_bad, _rem_reason = _remote_is_disqualifying(remote)
    if _rem_bad:
        return None, f"veto (remote): {_rem_reason}"
    if any(re.search(p, nonpe, re.I) for p in PE_FLAG) and "✅" not in nonpe:
        return None, f"veto (PE): {nonpe.strip()}"

    pts = 0.0
    tier = _tier(culture)

    # WLB — prefer an explicit WLB rating, else the overall culture rating. Below WLB_FLOOR is a
    # veto-level drop; from the floor up it scales to the full weight at WLB_FLOOR + WLB_RANGE.
    wlb = _num(r"wlb\s*([0-9.]+)", culture) or _num(r"🟢?\s*([0-9]\.[0-9])", culture)
    if wlb is not None:
        if wlb < WLB_FLOOR:
            return None, f"veto-level: WLB {wlb} < {WLB_FLOOR} floor"
        p = min((wlb - WLB_FLOOR) / WLB_RANGE, 1.0) * W["wlb"]
        pts += p
        reasons.append(f"WLB {wlb} ({p:.0f}/{W['wlb']:.0f})")
    else:
        reasons.append("WLB n/a (not scored)")

    # retention / %recommend
    rec = _num(r"([0-9]{2,3})%\s*rec", culture)
    if rec is not None:
        p = rec / 100 * W["retention"]
        pts += p
        reasons.append(f"{rec:.0f}% rec ({p:.0f}/{W['retention']:.0f})")
    else:
        reasons.append("rec n/a")

    # leadership stability, read from screen confidence + turmoil caveats. "no turmoil" is a
    # POSITIVE and must not trip the caveat branch (`turmoil` matches inside `no turmoil`). Require
    # the negatives to be un-negated.
    lw = W["leadership_stability"]
    if re.search(r"(?<!no )(?<!no-)(turmoil|growth-strain|instab|reorg|\brif\b|layoff)", culture, re.I):
        p = lw * LEADERSHIP_CAVEAT_FRACTION
        pts += p
        reasons.append(f"leadership: caveat flagged ({p:.0f}/{lw:.0f})")
    elif tier >= LEADERSHIP_CLEAN_TIER:
        pts += lw
        reasons.append(f"leadership: clean screen ({lw:.0f}/{lw:.0f})")
    else:
        p = lw * LEADERSHIP_UNPROVEN_FRACTION
        pts += p
        reasons.append(f"leadership: unproven ({p:.0f}/{lw:.0f})")

    # calm pace: bootstrapped / mature / calm / no-turmoil
    if re.search(r"bootstrap|mature|calm|content|no turmoil", culture + " " + nonpe, re.I):
        pts += W["calm_pace"]
        reasons.append(f"calm/bootstrapped (+{W['calm_pace']:.0f})")

    # readiness tiebreaks toward targets you can act on today
    if "@" in boss:
        pts += W["boss_reachable"]
        reasons.append("boss+email ✓")
    if re.search(r"https?://|\.(com|io|org|dev|us)", praise):
        pts += W["sourced_praise"]
        reasons.append("sourced praise ✓")

    # confidence discount on the culture-derived score keeps an unproven row from topping a verified
    # one on a lone high number — but the tier is ALSO the primary sort key, so this is secondary.
    # ── DESK-ANSWERABLE CRITERIA ──
    # Added AFTER the culture block and BEFORE the confidence discount, deliberately. These are
    # posting facts, not culture inferences, so they must not be scaled by a culture-confidence
    # multiplier that exists to stop an unproven row topping a verified one on a lone high rating.
    _dp, _dr = _desk_points(dict(desk or {},
                                 _calm_already=any("calm" in r for r in reasons)))
    reasons.extend(_dr)

    conf = CONFIDENCE_MULTIPLIER.get(tier, 0.5)
    return {
        "company": company, "lane": lane, "tier": tier, "pts": round(pts * conf + _dp, 1),
        "reasons": reasons, "boss": boss.strip(), "source": "green board",
    }, None


# Status tokens that mean "this row is not available to propose". Read from the STATUS COLUMN only.
# ⚠️ BLOCKED is guarded against "blocked-list": a status legitimately reads "…not blocked-list,
# dropped on remote", and a bare \bBLOCKED\b matches inside that phrase.
#
# PARKED IS IN THE LIST BECAUSE A SYNONYM GOT MISSED. An earlier widening added PAUSED and stopped
# there, while the board itself was writing "⏸️ **PARKED** — remote not cited; do not work until
# resolved". The token appeared nowhere in the scripts, so parked rows stayed fully rankable and one
# reached #2 in a computed warm trio — every one of them parked because REMOTE could not be verified,
# which makes them the worst possible rows to propose.
#
# The lesson is the ENUM, not the word: a status vocabulary that lives only in prose grows synonyms
# the code does not know. If you add a status word to your board, add it here in the same change.
_UNAVAILABLE = re.compile(
    r"\bSENT\b|\bDROPPED\b|\bPAUSED\b|\bPARKED\b|\bBLOCKED\b(?!\s*-?\s*list)", re.I)


def board_row_unavailable(cells):
    """True when the STATUS column marks the row as not proposable.

    WIDENED 2026-07-25. Previously matched only \bSENT\b, so BLOCKED / DROPPED / PAUSED rows were
    still scored as candidates unless they also happened to be struck through. A ranker that offers
    a company the user has already ruled out is the failure this guard exists to stop.
    ⚠️ BLOCKED is guarded against "blocked-list", which appears in legitimate status prose.
    **If a ruling must bind the ranker, it has to be written into the ROW, not a section header.**
    """
    status = cells[-2] if len(cells) >= 2 and not cells[-1] else (cells[-1] if cells else "")
    return bool(_UNAVAILABLE.search(status))


def board_row_sent(cells):
    """SENT MUST BE READ FROM THE STATUS COLUMN, NOT THE WHOLE ROW.

    A naive `"SENT" in line.upper()` is a substring test across the entire row, so any company whose
    NAME merely CONTAINS those four letters reads as already-contacted and is silently dropped from
    the ranked list — a name holding a word like "absent", "consent" or "assent" would false-match.
    Word-boundary the token against the STATUS cell only.

    `cells` is the row split on "|", so the trailing empty cell after the closing pipe means the
    status sits at cells[-2].
    """
    status = cells[-2] if len(cells) >= 2 and not cells[-1] else (cells[-1] if cells else "")
    return bool(re.search(r"\bSENT\b", status, re.I))


# Dispositions the pipe-table extractor assigns that mean "not proposable". The prose-token
# equivalent of `_UNAVAILABLE`, read off the extracted field instead of the status CELL.
_UNAVAILABLE_DISPOSITIONS = {"blocked", "sent", "parked", "dropped", "paused"}


def board_candidates(done, blocked):
    """Scored board candidates, read from the DURABLE STATE STORE, then topped up from the markdown.

    ⛔ WHAT THIS REPLACED AND WHY, measured before the switch rather than asserted. The old body
    walked the board markdown with a pipe-count heuristic plus a two-layout offset guess. A mature
    board carries many more shapes than two, so reading by header NAME finds substantially more
    companies than the positional walk does — and every extra is one the ranker could not see. A
    separate `re.match(r"^[A-Z0-9]", name)` guard rejected lowercase brands outright, losing more.

    Migrating gained companies and lost NONE. The old reader never invented a company either; it
    only dropped them. Silent loss is the failure class the store exists to end, and screening that
    never reaches the pool is not screening.

    ⛔ UNION, NOT SUBSTITUTION. Two things break under a clean swap:

      · The store answers "what was extracted", not "what the file says right now". A store that has
        gone behind would serve a SMALLER board than the markdown it replaced — the same silent loss
        pointed the other way.
      · A fresh sandbox has an empty store. Substituting outright makes every test that builds a
        board fixture and asks this function to read it fail. Those tests are not wrong; a reader
        that ignores the file it is asked about is. The gate stays, the reader widens.

    The store WINS on conflict: its rows are header-driven and field-merged, so they carry more than
    a positional read of the same row can.

    ⚠️ The store must be CURRENT for the gain to hold. The consistency check is where currency is
    asserted; re-run the extractor when it reports the store behind.
    """
    out, skipped, seen = [], [], set()

    for rec in state.from_source("company", "green-board"):
        payload = rec.get("payload") or {}
        co = payload.get("name") or rec.get("key", "")
        if not co:
            continue
        seen.add(state.key_for("company", co))
        if (payload.get("disposition") or "") in _UNAVAILABLE_DISPOSITIONS:
            continue
        if co.lower() in done or co.lower() in blocked or rec.get("key") in blocked:
            continue
        sc, veto = score_board_record(rec)
        (skipped.append((co, veto)) if sc is None else out.append(sc))

    # The markdown pass. Positional and lossy, kept because it is the only reader that sees a row the
    # store has not extracted yet. Anything the store already covered is skipped by key, so this can
    # only ADD, never contradict.
    for line in rd("documents/green-board.md").splitlines():
        if not line.strip().startswith("|") or line.count("|") < 8:
            continue
        cells = [c.strip().strip("*") for c in line.split("|")]
        if len(cells) < 3:
            continue
        off = row_offset(cells)
        co = cells[1 + off] if len(cells) > 1 + off else ""
        if not co or co.startswith("~~") or co.lower() in ("company", "board", "#"):
            continue
        if not re.match(r"^[\w]", co):
            continue
        k = state.key_for("company", co)
        if not k or k in seen:
            continue
        seen.add(k)
        if board_row_unavailable(cells) or co.lower() in done or co.lower() in blocked:
            continue
        sc, veto = score_board_row(cells, off)
        (skipped.append((co, veto)) if sc is None else out.append(sc))

    return out, skipped


def banked_sweep_files():
    """Every `documents/banked-candidates-*.md` file, newest first.

    A mechanical segment sweep produces companies that have passed the HARD gates (blocked-list ·
    dedup · remote-absolute · industry · PE · comp floor) and are written to these files by
    screen_sweep.py --bank. If NOTHING reads them, the ranker keeps scraping the bottom of a stale
    green board while a fresh screened batch sits unused.

    These rank ABOVE raw discovery (they cleared the hard gates) and BELOW the green board (they
    still owe the culture screen), so they enter at tier 1 like a discovery row but carry an honest
    reason string. A warm-ask trio needs only the hard gates, so they are immediately usable as
    `--targets` fuel even before any culture work.
    """
    import glob as _glob
    fs = _glob.glob(os.path.join(REPO, "documents", "banked-candidates-*.md"))
    return sorted(fs, reverse=True)


def survivor_rulings():
    """company canon-key → the latest SURVIVOR row, for rows whose screen is genuinely DONE.

    ⚖️ FAILS OPEN, the same direction as the deferred reader and for the same reason: an unreadable
    ledger costs a screened row its upgrade, which is one repeated screen, whereas failing closed
    would take the pool down entirely.

    ⛔ SURVIVOR ONLY, and the narrowness is the whole safety of this. UNVERIFIED means the screen
    STARTED and did not finish, so those rows keep the conservative default; DEFERRED is already
    removed upstream by `_drop_deferred`; DROP never reaches here because the reconciler writes it
    to the blocked list. Widening this set past SURVIVOR would put an unfinished screen in front of
    you wearing a finished badge, which is the failure this reader exists to prevent.

    ⛔ THE DEFECT THIS CLOSES. The `==` test used to compare the raw field, so a row recorded as
    `"SURVIVOR (qualified)"` failed it and fell back to the conservative default, unnoticed —
    `findings_ledger.normalize_verdict()` recovers the token from that prose without widening
    what counts as SURVIVOR.
    """
    try:
        import findings_ledger
        return {k: r for k, r in findings_ledger.rulings().items()
                if findings_ledger.normalize_verdict(r.get("verdict")) == "SURVIVOR"}
    except Exception:
        return {}


def _screened_fields(row):
    """Map one SURVIVOR ledger row onto the strings `_score_fields()` expects.

    ⛔ THE LEDGER'S FREE TEXT IS NEVER PASSED THROUGH RAW, and this is the trap that turns a display
    bug into a silent exclusion. `_score_fields()` vetoes remote on
    `"✅" not in remote and "remote" not in remote.lower()`, and recorded `--remote` evidence often
    reads like "United States. https://jobs.example.com/…", which contains neither token. Fed in
    raw, the row would be VETOED off the board by the very screen that cleared it. So the VERDICT
    supplies the verdict token and the recorded text rides along behind it as evidence.

    ⛔ `culture` is returned EMPTY for every verdict, without exception. Review sites block agents,
    so an agent's "culture clean" may only mean "culture unreachable", and those are opposite
    findings. Leaving it empty is also what keeps the row at tier 0 and prints
    "leadership: unproven", so a screened row outranks an unscreened one without ever claiming to be
    culture-verified. The 60-second human peek stays a human's.

    ⛔ `boss` is never synthesized: an "@" in it earns a readiness point, so inventing one would
    manufacture actionability that does not exist.
    """
    when = str(row.get("ts") or "")[:10]
    remote_txt = str(row.get("remote") or "").strip()
    owner_txt = str(row.get("ownership") or "").strip()
    # No recorded evidence for a gate means that gate is NOT upgraded, even on a SURVIVOR row.
    remote = f"✅ remote (screened {when}) · {remote_txt}" if remote_txt else ""
    nonpe = f"✅ no PE · {owner_txt}" if owner_txt else ""
    return remote, nonpe, str(row.get("boss") or "")


def _screened_lane(row, remote, nonpe):
    """The lane text a screened row shows, naming what is STILL OWED rather than implying done."""
    when = str(row.get("ts") or "")[:10]
    got = []
    if remote:
        got.append("remote")
    if nonpe:
        got.append("noPE")
    # ⚠️ WHAT IS OWED COMES BEFORE WHAT CLEARED, AND THE ORDER IS THE WHOLE POINT.
    # There are TWO renderers with DIFFERENT truncations: the detail block cuts at 60 and the
    # compact top-10 list cuts at 34. The compact one is what the morning 3-3-3 brief prints, so it
    # is the view actually read. A string tuned to the 60 gets sheared by the 34 into
    # "SCREENED <date> · remote+noPE ", a row advertising everything it cleared and silently
    # dropping everything it still owed. Truncation that flatters is a render defect, and fixing it
    # for one renderer while a stricter sibling still lies fixes nothing.
    # The full string fits the 60; the 34 cut lands inside "culture", which still reads as OWED.
    got = "+".join(got) or "verdict"
    return f"SCREENED {when} · OWED culture+boss · {got} ✅"


# ── OPEN SEATS AS A TIEBREAK AMONG UNSCREENED ROWS (2026-08-10) ──────────────────────────────
#
# ⛔ THE PROBLEM THIS SOLVES, measured rather than assumed. The 2026-08-10 sweep banked 182
# companies. `banked_topup` correctly refuses to grant any of them a screened verdict, so every one
# arrives at the SAME pts=0.5, and the board showed 142 rows tied. A tie that large is not an
# ordering, it is an alphabetical accident, and it made "screen the top of the pool" meaningless:
# there was no top.
#
# ⚖️ THIS DOES NOT UPGRADE ANY ROW. The lane text, the tier and the 0.5 all stand, because none of
# them has been earned. What changes is only the order WITHIN the tie, and only by a fact the sweep
# already collected: how many distinct product seats that employer has open right now.
#
# 📊 WHY SEAT COUNT AND NOT SOMETHING ELSE. It is the one signal on hand that is about the employer
# rather than the posting, it needs no lookup, and it was the field that separated the pool the
# first time anyone looked: ordering by it put Virtusa (9 seats), GitHub (7), Couchbase (7) and Ping
# Identity (5) on top, and THREE OF THOSE FOUR turned out to be PE-owned buyouts. So it surfaces
# large, acquisition-shaped employers early, which is where the cheap kills are.
#
# ⚠️ IT IS A TIEBREAK, NOT A FIT SIGNAL. A company with nine openings is not a better match; it is
# a company worth screening SOONER because the answer is cheap and it clears more of the pool.
def _open_seat_counts(repo=None):
    """{company_lower: distinct open product seats} from the newest sweep file. {} on any failure."""
    # ⛔ MATCH THE DATED JOB SWEEP ONLY, NEVER `sweep-*`. `sorted(glob("sweep-*.jsonl"))[-1]` sorts
    # LEXICALLY, so any same-prefixed neighbour whose next character outranks a digit wins the sort.
    # In the tree this shipped from, a `sweep-chambers-…` file (a local business directory of 2,279
    # names, nothing to do with job postings) beat every `sweep-YYYY-MM-DD` file, so the "newest
    # sweep" was never the newest sweep. No banked employer appeared in it, every row scored 0 seats,
    # and the tiebreak ordered nothing while looking like it worked.
    # 📌 A tiebreak that returns a constant for every row is a bug wearing the badge of a tie.
    import glob as _glob
    import re as _re
    repo = repo or REPO
    files = [f for f in _glob.glob(os.path.join(repo, "documents", "sweep-*.jsonl"))
             if _re.match(r"^sweep-\d{4}-\d{2}-\d{2}", os.path.basename(f))]
    # Sort on the DATE the name carries, so a future suffix cannot reorder the list again.
    files.sort(key=lambda f: os.path.basename(f))
    if not files:
        return {}
    counts = {}
    try:
        with open(files[-1], encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                co = (d.get("company") or "").strip().lower()
                if co:
                    counts.setdefault(co, set()).add(d.get("id") or d.get("url") or d.get("title"))
    except OSError:
        return {}
    return {c: len(v) for c, v in counts.items()}


def banked_topup(have, done, blocked, need):
    """Fill from the agent-screened BANKED files before falling back to raw discovery.

    Reads the dot-separated batch lists that screen_sweep.py --bank writes to
    documents/banked-candidates-*.md. Keep this reader interface intact: screen_sweep.py's bank()
    points at this function, and it deliberately skips lines starting with `|`, `#`, `>` or `-`.

    ⚠️ IT MEASURED THE FILE, NOT THE VERDICT. This used to stamp `pts=0.5` and "NOT screened" on
    every banked name, never once asking what verdict that company actually held, so a company with
    a SURVIVOR row carrying verified remote and ownership still displayed as unscreened. It measured
    which file a name came from instead of the thing itself.

    ⚠️ THE CONSERVATIVE DEFAULT STAYS, and only a recorded SURVIVOR verdict overrides it.
    """
    out = []
    survivors = survivor_rulings()
    _seat_counts = _open_seat_counts()
    havenames = {c["company"].lower() for c in have}
    for path in banked_sweep_files():
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        skipped_by_shape = 0
        found_in_this_file = 0
        for line in text.splitlines():
            # rows look like:  Company A · Company B · **Company C** ·  (batch lists)
            if not line.strip() or line.lstrip().startswith(("#", ">", "|", "-")):
                if line.strip():
                    skipped_by_shape += 1
                continue
            for chunk in line.split("·"):
                co = chunk.strip().strip("*~ ").strip()
                co = re.sub(r"\s*\(.*?\)\s*$", "", co).strip()
                if not (2 <= len(co) <= 34) or not re.match(r"^[A-Z][\w&.\-' ]+$", co):
                    continue
                # Counted here, not at the output append: a plain-English intro line ("Here are
                # the companies I found:") is not a header or a bullet, so it is never skipped by
                # shape, but it also produces no company-shaped token — a lines-present counter
                # would treat it as content and silently suppress the shape warning below. This
                # counts an actual TOKEN this file produced, the instant it passes the shape/regex
                # test — before dedup/veto, so a file that is genuinely readable but 100% redundant
                # with an already-known company still counts as readable.
                found_in_this_file += 1
                low = co.lower()
                if low in havenames or low in done or low in blocked:
                    continue
                # `is_artifact` alongside the veto: a banked file is written from a scraped pool, so
                # it carries page titles and ATS boilerplate ("Company Overview", "Job
                # Opportunities") that no screen can ever clear and no veto can ever catch. They are
                # not companies, so they are dropped as artifacts rather than ranked as employers.
                if _industry_vetoed(co) or is_artifact(co):
                    continue
                # ⚠️ THE LANE TEXT MUST NOT UPGRADE THE ROW PAST WHAT ITS SOURCE GRANTS. This used to
                # read "agent-screened, hard gates passed", and the banked files say the opposite in
                # their own header: passed the MECHANICAL gates only (dedup, blocked-list, industry,
                # title, comp floor), with remote verification, PE ownership, culture and boss ALL
                # still owed. A name in a banked file means *worth screening*, never *worth sending*.
                # Reading those rows as pre-screened is how a PE-owned company and a predatory-lending
                # company both sat in a proposed pool.
                # ── A RECORDED SURVIVOR VERDICT OVERRIDES THE DEFAULT ──
                # SURVIVOR only. UNVERIFIED keeps the default because an unfinished screen is not a
                # verdict; DEFERRED is stripped upstream by `_drop_deferred`; DROP never arrives
                # because the reconciler puts it on the blocked list. See `survivor_rulings()`.
                row = survivors.get(_deferred_key(co))
                if row is not None:
                    remote, nonpe, boss = _screened_fields(row)
                    lane = _screened_lane(row, remote, nonpe)
                    # The ledger row already holds comp, the seat titles, ownership shape and the
                    # note. Pass them through so the desk criteria can score; the BOARD path
                    # deliberately does not, because a board row has no such columns.
                    _desk = {"comp": row.get("comp"), "pm_req": row.get("pm_req"),
                             "ownership": row.get("ownership"), "note": row.get("note")}
                    scored, _why = _score_fields(co, lane, remote, "", nonpe, boss, "", desk=_desk)
                    if scored:
                        scored["source"] = os.path.basename(path)
                        out.append(scored)
                        havenames.add(low)
                        continue
                    # A screened row that the scorer VETOES is a real disagreement between the
                    # ledger and the gates, not a reason to go quiet. Fall through to the default so
                    # the company still appears and can be looked at.
                out.append({"company": co, "lane": "MECHANICAL gates only, NOT screened",
                            "tier": 1, "pts": 0.5,
                            # ⚖️ A TIEBREAK INSIDE THE 0.5, never an addition to it.
                            "seats": _seat_counts.get(low, 0),
                            "reasons": ["BANKED sweep: mechanical gates only. Remote, PE, culture "
                                        "and boss ALL still owed. Worth screening, never worth sending."],
                            "boss": "", "source": os.path.basename(path)})
                havenames.add(low)
        # ⛔ "UNREADABLE" AND "EMPTY" MUST NOT PRINT THE SAME SENTENCE. The caller's "0 rankable
        # candidate(s) — the board + discovery are thin" is what a genuinely thin file AND a file in
        # the wrong shape both produced, because this reader could not tell them apart.
        # `screen_sweep.py --bank` writes a dot-separated batch list; a discovery AGENT writing the
        # same file by hand writes prose, where companies are `## 1. SomeCo (STRONG, send-ready)`
        # headings and every attribute is a `-` bullet. That is every line, so every line is
        # skipped, and fully screened companies sat unseen in a file the board had just opened and
        # called thin.
        # 🎯 THE PREDICATE IS THE SHAPE, NOT THE COUNT. Zero real company tokens found WITH skipped
        # content is a shape failure; zero found and nothing skipped is an empty file, which is not
        # this warning's business. A file that parsed fine and simply held nothing NEW stays silent
        # too, because a dedup/veto continue still counted toward `found_in_this_file` above.
        # Counting TOKENS FOUND rather than LINES PRESENT closes a gap where a prose file's plain
        # intro line satisfied a lines-present counter without containing a single real company.
        if found_in_this_file == 0 and skipped_by_shape:
            print(f"  ⚠️  {os.path.basename(path)}: all {skipped_by_shape} non-blank line(s) matched "
                  f"the header/bullet skip pattern (#, >, |, -), so this file is in a shape "
                  f"banked_topup CANNOT READ, not a file with nothing eligible in it. Expected the "
                  f"dot-separated batch list `screen_sweep.py --bank` writes; this looks like prose.",
                  file=sys.stderr)
    # ⛔ SORT BEFORE TRUNCATING. This used to return the first `need` rows in FILE ORDER and stop,
    # so whether a company had been SCREENED had no bearing on whether it was ever reached: only
    # where its name sat in a dot-separated batch list. Measured on the maintainer's board, it was
    # showing 8 unscreened rows at 0.5 while 140 recorded SURVIVOR rulings sat unshown, including
    # the highest-scoring company on file. Collect the whole eligible pool, order it, THEN cut.
    #
    # ⚖️ Screened rows keep precedence because `pts` is the first key; `seats` only decides the
    # order INSIDE a tie, which is where the unscreened rows all sit by construction.
    out.sort(key=lambda r: (r.get("pts", 0), r.get("seats", 0)), reverse=True)
    return out[:need]


def network_topup(have, done, blocked, need):
    """Fill from companies where you ALREADY KNOW SOMEONE, which no ranker read until this was added.

    ⛔ THE GAP THIS CLOSES. `rank_network_companies.py` ranks companies by who you know there, and the
    network-companies ranker's own step order (pick the company first, then who-you-know) says that is
    where to start — but the board never consulted it. Meanwhile the warm-path term ratified
    2026-08-11 scored every board row at zero, because the pool was built entirely from companies
    where you know nobody.
    📊 The evidence that makes that the wrong pool to draw from: replies were markedly more likely
    where a path existed than where none did, and the board was systematically sourcing from the
    weaker side.

    ⚠️ THESE ARE UNSCREENED, and they say so. A network company has passed no gate beyond the
    industry and blocked checks `rank_network_companies` already applies, so it enters at the same
    low `pts` as a banked row and can never outrank a screened one. The warm-path term then scores
    it on its own merits, which is the whole point: it earns its place through the ratified signal
    rather than through a hand-placed bonus.
    """
    out = []
    try:
        import rank_network_companies as rnc
        ranked = rnc.rank(need * 4)
        ranked = ranked[0] if isinstance(ranked, tuple) else ranked
    except Exception:
        return out
    havenames = {c["company"].lower() for c in have}
    for r in ranked:
        co = (r.get("company") or "").strip()
        low = co.lower()
        if not co or low in havenames or low in done or low in blocked:
            continue
        if _industry_vetoed(co) or is_artifact(co):
            continue
        # ⛔ A WARM DOOR IS NOT A TARGET UNTIL IT IS ALSO A VIABLE EMPLOYER, and this is the line
        # that was missing when wiring this source made the board worse. Ranked on who you know
        # ALONE, the top of the network list is dominated by mega-caps and incumbents: real doors,
        # none of them somewhere you would work. Requiring a POSITIVE target-segment read is the
        # cheapest disqualifier available and it does the whole job: the pool narrows sharply.
        # ⚖️ POSITIVE ONLY. An `unknown` segment is not admitted here, which is the opposite of the
        # tri-state rule for DEMOTING a person, and deliberately so: this source ADDS rows to a pick
        # surface rather than reordering ones already screened, so the burden of proof runs the
        # other way (employer industry needs real data, never a name match).
        try:
            _seg, _detail = contact_signals.segment_read(company=co)
        except Exception:
            continue
        if _seg != "relevant":
            continue
        # ⛔ THE DISQUALIFIERS RUN HERE, NOT IN THE CHAT (ruled 2026-08-11: disqualifiers must be
        # screened before reaching the reviewer, not filtered by hand in the chat).
        # 📊 THE OCCASION. The first network top-up surfaced companies that were dead on arrival:
        # foreign firms that failed remote-US, and government agencies that were govtech, which you
        # deprioritized. They were filtered by hand in the chat, which fixes one run and leaves the
        # next one identical. A disqualifier applied in prose is not applied.
        # ⚖️ READ OFF THE RESOLVED INDUSTRY TEXT, which is sourced and already in hand, so this
        # costs nothing and cannot invent a reason. It is a CHEAP first pass, never the remote
        # gate itself: a US company is not cleared for remote by surviving this (cheapest
        # disqualifier first; remote is absolute).
        _d = str(_detail or "")
        # ⛔ A NAME-PATTERN MATCH IS NOT A SEGMENT READ, and admitting one here would repeat the
        # mistake this source was built to undo. `segment_read` falls back to matching the COMPANY
        # NAME when the sourced cache has no row, and returns `payments (matched "FinTech")` for a
        # company whose NAME merely contains a segment word, which nobody screened. The vast
        # majority of employers are unresolvable from the name alone.
        # ⚖️ So this source requires a SOURCED read. The cache writes a real industry sentence and a
        # URL; the fallback writes `(matched "...")` and nothing else. Requiring the source is the
        # difference between "we know what they do" and "their name contains a word".
        if 'matched "' in _d or "·" not in _d:
            continue
        if _NON_US_TELL.search(_d):
            continue
        if _seg == "relevant" and _detail and "govtech" in _d.lower():
            continue          # deprioritized by your ruling; not a veto, so it simply does not top up
        out.append({"company": co, "lane": f"FROM YOUR NETWORK · {str(_detail)[:40]}",
                    "tier": 1, "pts": 0.5, "seats": 0,
                    "reasons": [f"🔗 {r.get('people', 0)} known there"
                                + (f" ({r.get('product', 0)} in product)" if r.get("product") else "")
                                + ". NOT screened: remote, PE, culture and boss all still owed."],
                    "boss": "", "source": "network"})
        havenames.add(low)
        if len(out) >= need:
            break
    return out


def discovery_topup(have, done, blocked, need):
    """Fill toward N from the discovery board when the green board is thin. These are NOT fully
    screened, so they are tagged 💡 and sorted below every green-board row by construction."""
    out = []
    havenames = {c["company"].lower() for c in have}
    for line in rd("documents/discovery-board.md").splitlines():
        if len(out) >= need:
            break
        if not line.strip().startswith("|") or line.count("|") < 5:
            continue
        cells = [c.strip().strip("*") for c in line.split("|")]
        m = re.search(r"[A-Z][\w&.\- ]+", cells[2]) if len(cells) > 2 else None
        if not m:
            continue
        co = m.group(0).strip()
        low = co.lower()
        if low in havenames or low in done or low in blocked or low in ("company", "badge"):
            continue
        # a PASSED/DROP row on the discovery board is not a candidate
        if re.search(r"passed|dropped|reject", line, re.I):
            continue
        # INDUSTRY VETO on the top-up. A deal-breaker industry must never reach the pick list, even
        # as an unscreened suggestion — an early run put a crypto company at #7 precisely because
        # this path had no veto screen.
        # Artifact rows are dropped here too: a raw discovery board is the scraper's own output, so
        # it holds the most page-title noise of any pool this file reads.
        veto = _industry_vetoed(line)
        if veto or is_artifact(co):
            continue
        out.append({"company": co, "lane": cells[3][:40] if len(cells) > 3 else "", "tier": 1,
                    "pts": 0.0, "reasons": ["discovery board, NEEDS FULL SCREEN before a build"],
                    "boss": "", "source": "discovery board"})
        havenames.add(low)
    return out


def rank(n=10):
    blocked = blocked_set()
    done = done_set()
    # 📼 THE DEFERRED LEDGER. Upstream, NO ranker read it until a 2026-08-02 ruling: 138 companies
    # carried a DEFERRED latest verdict and every one was still eligible to be recommended. A
    # verdict that was reached and then had no reader is the same defect class as a rule that lives
    # only in prose.
    # ⚠️ DORMANT IN THIS KIT UNTIL `findings_ledger.py` SHIPS. `deferred_set()` degrades to {} when
    # that module is absent, so `_drop_deferred` is a no-op here today. It is wired ANYWAY, because
    # a filter that is ported but never called is worse than one that is absent: it reads as
    # shipped and changes nothing. Wiring it now means the day the ledger arrives, it works.
    supp = deferred_set()
    cands, skipped = board_candidates(done, blocked)
    cands = _drop_deferred(cands, skipped, supp)
    # BANKED (agent-screened, hard gates passed) fills BEFORE raw discovery — it is strictly
    # better-evidenced than an unscreened discovery row.
    # ⚠️ Filtered after EVERY stage rather than once at the end: the `len(cands) < n` tests below
    # COUNT rows, so filtering only at the end would let suppressed rows satisfy those counts and
    # the pool would stop topping up at n and then hand back fewer.
    if len(cands) < n:
        cands += _drop_deferred(banked_topup(cands, done, blocked, n - len(cands)), skipped, supp)
    # 🔗 THEN COMPANIES YOU ALREADY HAVE A PATH INTO. Wired only AFTER the segment gate went in:
    # ranking on who-you-know alone surfaces mega-caps and incumbents you would never work at. The
    # warm-path signal is real; a pool sourced ONLY on it is not. See network_topup.
    if len(cands) < n:
        cands += _drop_deferred(network_topup(cands, done, blocked, n - len(cands)), skipped, supp)
    if len(cands) < n:
        cands += _drop_deferred(discovery_topup(cands, done, blocked, n - len(cands)), skipped, supp)
    # 🔗 WARM PATH, the ratified term (2026-08-11). Measured live, so a run where the evidence thins
    # below the floor scores NOTHING rather than carrying yesterday's weight.
    _lift, _wc, _woc = warm_path_lift()
    if _lift is None:
        print(f"  ⚪ warm path NOT scored: {_wc[1]} joinable send(s) with a path, under the "
              f"n={WARM_PATH_MIN_N} floor. The signal is unmeasurable today, so it weighs nothing.",
              file=sys.stderr)
    for c in cands:
        _p, _why = warm_path_points(c.get("company", ""), _lift)
        if _why:
            c.setdefault("reasons", []).append(_why)
        if _p:
            c["pts"] = round(float(c.get("pts") or 0) + _p, 1)
    # Sort by the final criteria score, which ALREADY folds in culture-screen confidence (the
    # per-tier multiplier in score_board_row). A verified clean row therefore floats up on merit
    # rather than by fiat, and the number the user reads is the number they are sorted by — no
    # "why is #1 below #2 in score" confusion. Tier stays a visible tag. Ties broken by tier.
    # 🏷 INDUSTRY RESOLUTION, MARKED ON THE ROW. `veto_hits` matching industry words against a
    # company NAME only ever stops a company that spelled its industry into its own name: a run of
    # financial firms reached a partner's banked pool against an operator whose first hard filter
    # was financial services. An empty veto has always meant "no veto term appeared", never "this
    # company was screened", and nothing said so.
    # ⚖️ THESE ARE NOT BLOCKED. The great majority of employers are unresolvable from the name
    # alone, so an unknown industry RANKS carrying a visible mark and the veto moves to the SEND.
    # This ADDS A REASON and changes no score and no order.
    for c in cands:
        try:
            _state, _detail = industry_resolution(c.get("company", ""), c.get("lane", ""))
        except Exception:
            continue
        if _state == "unknown":
            c["industry_unresolved"] = True
            c.setdefault("reasons", []).append(
                "🏷 industry UNRESOLVED — never established, so this cannot be sent to yet")
    cands.sort(key=lambda c: (c["pts"], c["tier"]), reverse=True)
    # DEDUPE BY COMPANY. The pool is built from BOTH the ACTIVE board and the BANKED tier, and a
    # company promoted from banked to active exists in both — so one company could occupy TWO of a
    # 10-slot list. The user is asked to "pick 3 companies" from this list; duplicate slots silently
    # shrink the real choice and can make a trio that is not three distinct companies. Keep the
    # highest-scoring row per company (the list is already sorted, so the first occurrence wins).
    deduped, seen = [], set()
    for c in cands:
        key = c["company"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped[:n], skipped


# ── PEOPLE POOL — "who can help first", scoring v2 (2026-07-26) ───────────────────────────────
# Rank warm-network contacts by LIKELY-BOSS-NESS + RELATIONSHIP DISTANCE, with deal-breaker vetoes
# as the ONLY pre-contact filter. NO culture/WLB here: those are post-interview happiness scores,
# and a warm rung needs deal-breakers only.
#
# v1 was a TITLE LADDER (product-leader 40 › senior-exec 33 › …) that was never derived from the
# method's own sources, and it encoded a product-lead-only targeting rule the kit owner revoked
# 2026-07-26. It also SATURATED: on a real network a whole bloc of product leaders landed on one
# identical score, so the "top 10" was the first 10 file rows of a category rather than a ranking.
# A ranking that ties is not a ranking, and the tie is invisible — the list still looks ordered.
#
# What the PRIMARY sources actually say (page-cited — never from recall):
#   · Boss_Hunting_Bible p.2 — the target is "your best guess at a boss, the boss, or some
#     authority figure likely maintaining oversight" of the role. A RELATION to the role, not a title.
#   · Bible p.10 — company shape conditions who that is: "If the company is very small, such as
#     less than 10 people, it is a good idea to go straight to the CEO. If the company is less
#     than 100 people, you can also target other members of the management team."
#   · Bible p.3 — several plausible bosses at ONE company: "Pick the one you think is most likely
#     the 'direct' boss and try that person first… Give them a week or so… then target someone else."
#   · Job_Search_Challenge workbook pp.10-11 — the easy-target ORDER: bosses → teammates →
#     HR/recruiters → first degrees → anyone.
#   · Networking_Templates — the ten rungs are ordered by RELATIONSHIP DISTANCE; "that ordering IS
#     the method."
#
# ENCODED RULINGS (the owner's 2026-07-26 rulings):
#   A. LIKELY BOSS — target whoever would actually MANAGE this role, derived from how the company
#      is built, never read off a title ladder. No product function → the founder/CEO/COO IS the
#      likely boss, FIRST-CLASS. So the exec band scores EQUAL to the product-leader band; company
#      shape (where the green board records it) refines the read; relationship distance — the
#      ladder's own axis — separates what used to tie.
#   B. FOUNDER ORDERING — the ruling: when only a founder can be found among several plausible
#      bosses, treat the founder as the last choice rather than the first. An ORDERING inside the plausible-boss set, encoded as a
#      sort TIEBREAK, never a score gap — a score gap would be the revoked ladder by the back door.
#
# ⚖️ THE v2 WEIGHTS ARE PROPOSED, NOT RATIFIED. Changing them reorders who the owner is shown
# tomorrow, and that is THEIR ruling. The output announces v2 until it is ratified; the numbers to
# rule on are listed at PERSON_BASE below, and every one of them is retunable from kit_config
# WITHOUT editing this file.
try:
    from parse_network import SENIOR, CONNECTOR
except Exception:  # generic fallbacks keep the ranker importable with no network parser present
    SENIOR = re.compile(r"\b(founder|co-?founder|ceo|cto|coo|cpo|chief|vp\b|vice president|head of|"
                        r"director|president|partner|principal|owner)\b", re.I)
    CONNECTOR = re.compile(r"\b(recruit|talent|people ops|hr\b|human resources|staffing|search)\b", re.I)

# EXCLUDED_EMPLOYERS — former employers you'd rather not warm-approach (e.g. after a bad-leadership
# exit). Only the LEADERSHIP tier at these employers is filtered; PEERS stay in scope, because the
# exclusion is about leadership harm, not teammates. Ships EMPTY — no one is excluded until you name
# them in kit_config. Lesson worth keeping: a partial policy like this must be applied in the SAME
# place the user actually reads the ranked list. Relaxing it in the network parser but not here once
# silently dropped every in-scope peer from the list that gets reviewed — half-shipping a policy
# change is worse than not shipping it, because it LOOKS relaxed everywhere and is not where the
# pick happens. The count is always reported in `skipped`: an exclusion that hides its own effect is
# not auditable.
try:
    from kit_config import EXCLUDED_EMPLOYERS
except Exception:
    EXCLUDED_EMPLOYERS = []
EXCLUDED_EMPLOYER_RE = re.compile("|".join(EXCLUDED_EMPLOYERS), re.I) if EXCLUDED_EMPLOYERS else None

try:
    from check_ats import is_pm
except Exception:
    def is_pm(t):
        return bool(re.search(r"\bproduct (manager|management|owner|lead)\b", (t or "").lower()))

# Base score by "who can help" category. v2: the PLAUSIBLE-BOSS band is product leaders AND org
# owners (founder/CEO/COO/president/owner), EQUAL — Ruling A's own words: "the founder, CEO or COO
# IS the likely boss, first class." Ruling B orders them as a TIEBREAK, below. Functional senior
# execs (IT/marketing/eng directors, CTOs, partners) would not MANAGE a product hire, so they stay
# a REFERRER band — the first live v2 run put an IT Director, a Marketing Director and a Chief
# Business Development Officer in the top 10 as "likely bosses" before this split, which is exactly
# the function-blindness of the revoked ladder, pointed the other way. Peers → connectors → other
# follows the easy-target order (workbook pp.10-11: bosses → teammates → HR/recruiters → anyone).
#
# ⚙️ EVERY NUMBER BELOW IS RETUNABLE FROM kit_config — never edit them here. Each knob is imported
# in its OWN try/except on purpose: one combined import means a partner who adds ONE new name to an
# older kit_config (or omits one) silently loses ALL of them to the fallback branch, and a scoring
# model that quietly reverts to defaults is the failure mode this whole section exists to remove.
_PERSON_WEIGHTS_V2_DEFAULT = {"product-leader": 40, "founder-exec": 40, "senior-exec": 33,
                              "product-ic": 25, "connector": 15, "senior-ic": 5, "other": 5}
try:
    from kit_config import PERSON_WEIGHTS_V2 as PERSON_BASE
except Exception:
    PERSON_BASE = dict(_PERSON_WEIGHTS_V2_DEFAULT)
# 🧩 BUG-181 WU-6a: the fourth bucket ALWAYS scores at "other"'s value, whatever a partner's tuned
# kit_config carries. This is the ABSENCE of a typed weight (the bucket's send history has not
# cleared the n≥15 floor), NOT a chosen one — so it is pinned to "other" rather than tuned. An older
# kit_config that predates the bucket keeps working: senior-ic defaults in here.
PERSON_BASE.setdefault("senior-ic", PERSON_BASE.get("other", 5))

# LEGACY v1 WEIGHTS — imported ONLY to report that they are inert, never to score with.
# kit_config ships tracked, so an existing recipient's `git pull --ff-only` must keep working and
# this file cannot rewrite their PERSON_WEIGHTS. That leaves a trap: a partner who retuned v1
# weights would see v2 ignore them and read the new ranking as a bug in their tuning. It is not
# silent, and it is not overridden either — v1 has five categories and v2 has six, so honouring it
# would KeyError on the founder-exec band the moment a founder appeared. Say so once, on stderr,
# and point at the replacement name.
_PERSON_WEIGHTS_V1_SHIPPED = {"product-leader": 40, "senior-exec": 33, "product-ic": 25,
                              "connector": 15, "other": 5}
try:
    from kit_config import PERSON_WEIGHTS as _PERSON_WEIGHTS_V1
except Exception:
    _PERSON_WEIGHTS_V1 = None
if _PERSON_WEIGHTS_V1 and _PERSON_WEIGHTS_V1 != _PERSON_WEIGHTS_V1_SHIPPED:
    print("⚠️  kit_config.PERSON_WEIGHTS holds retuned v1 people weights, which the v2 likely-boss "
          "model IGNORES — retune via PERSON_WEIGHTS_V2 in kit_config instead.", file=sys.stderr)

try:
    from kit_config import PERSON_EMAIL_BONUS
except Exception:
    PERSON_EMAIL_BONUS = 5      # contactable now (email flagged on the contact's row)
# ⚠️ WORTH AUDITING BEFORE YOU TRUST IT. Upstream this bonus is now ZERO: the ✉ flag comes from a
# LinkedIn export column and does NOT mean a usable address is on file. An audit there found only
# a small fraction of ✉-flagged contacts had an address findable anywhere in the repo, and the bonus
# repeatedly floated a contact to #1 on an address that does not exist. The kit keeps it at 5 deliberately,
# because a partner whose export DOES carry addresses is being told something true — but if your ✉
# column is a flag rather than an address, set PERSON_EMAIL_BONUS = 0 in kit_config.
try:
    from kit_config import PERSON_REENTRY_BONUS
except Exception:
    PERSON_REENTRY_BONUS = 8    # their company is already in your pipeline (warm re-entry)
# Relationship distance — the ladder's own axis, CONTINUOUS so equal-category contacts spread
# instead of tying (the saturation fix). The exact connect date already sits in the Known-since
# cell; the cap also bounds the known proxy error that a pre-platform friendship shows only its
# LinkedIn connect date, so decades of history read as "since we connected online".
try:
    from kit_config import PERSON_DISTANCE_PER_YEAR
except Exception:
    PERSON_DISTANCE_PER_YEAR = 0.5
try:
    from kit_config import PERSON_DISTANCE_CAP
except Exception:
    PERSON_DISTANCE_CAP = 5.0
try:
    from kit_config import PERSON_SEARCH_ERA
except Exception:
    PERSON_SEARCH_ERA = -2      # a search-era connect must not receive a warm-rung ask
try:
    from kit_config import PERSON_EXEC_AT_PRODUCT_LED
except Exception:
    PERSON_EXEC_AT_PRODUCT_LED = 33  # the one place the old 33 survives, now MEANING something: an
                                     # exec at a company whose board row shows a seated product
                                     # leader would not manage this role — referrer, not the boss.

# 🌡️ THREAD DEPTH — the SECOND relationship axis. Closeness says how strong the tie is; this says
# whether it is LIVE. A live thread is a warmer starting point than a cold one at the SAME closeness.
# The term is deliberately small so strength keeps dominating temperature, and it has no outcome data
# behind it yet — retune it in kit_config once your send log can join enough replies to measure.
try:
    from kit_config import PERSON_THREAD_BONUS
except Exception:
    PERSON_THREAD_BONUS = {"live": 4.0, "cooling": 2.0, "dead": 0.0, "never": 0.0}
# Where you have STATED the relationship, the connect-date proxy may separate equals but must not
# dilute your statement — so the years term is additive at a REDUCED slope, capped well under the
# closeness bonus itself. Removing it entirely (an earlier design) reintroduced a TIE CEILING: with
# the continuous term gone, every stated-tier contact in a category landed on one of a handful of
# discrete values and the whole top of a board shared a single score.
try:
    from kit_config import PERSON_STATED_PER_YEAR
except Exception:
    PERSON_STATED_PER_YEAR = 0.25
try:
    from kit_config import PERSON_STATED_CAP
except Exception:
    PERSON_STATED_CAP = 2.5
# Shown rows sharing one score before the ceiling announces itself. A scoring function built from a
# few discrete bonuses over a large population WILL pile up on one value; a ceiling that announces
# itself is found the same day rather than weeks later by eye.
PLATEAU_WARN_AT = 5
# Above this share of the shown top band being indistinguishable, the #1 row is a coin flip.
TIE_RATE_WARN_AT = 0.50

# ── CLOSENESS BAND — the LEADING people-sort key (BUG-181 WU-2) ─────────────────────────────────
# An evtier-led sort buries every stated relationship when the only shippable evidence band is
# almost entirely `never-spoke`, so the closeness bonus can never lift a warm contact past a
# stranger and the board returns a connect-date artifact. The fix: a band computed from the STATED
# tier leads the sort, ABOVE evtier — a warm contact outranks a never-spoke senior exec.
#   band 2 = strong (worked-together, know-well, personal-friend)
#   band 1 = thin   (every other tier rung_for grants a bonus for, inferred-strong included)
#   band 0 = never-spoke / absent / unstated
# ⛔ DEGRADES TO TODAY'S BEHAVIOR WITH NO CLOSENESS STORE: with `closeness` absent the band is 0 for
# every row, so `-close_band` is a constant and the rest of the sort key is unchanged. A test pins it.
_CLOSE_BAND_STRONG = frozenset({"worked-together", "know-well", "personal-friend"})

# WU-2 marker: 1 = the stated-closeness band LEADS the people sort; 0 reproduces the pre-WU-2
# evtier-led ordering. `--audit-signals` reads it to classify the evtier signal.
CLOSE_BAND_LEADS = 1
# WU-3 audit-state flags (see `audit_signals`). A tree predating WU-3 lacks these names, so the
# audit's `globals().get(..., <RED default>)` reports the pre-WU-3 picture. `_THREAD_SCORED False`
# ⇒ the thread bonus is leakage-silenced; `_EVTIER_RATIFIED True` ⇒ evtier is a demoted, ratified
# within-band tiebreak that scores 0, not an unvalidated lexicographic lead.
_THREAD_SCORED = False
_EVTIER_RATIFIED = True


def _close_band(crow, category):
    """The WU-2 closeness band (2/1/0) that leads the people sort.

    ⛔ PROVENANCE-RESPECTING BY CONSTRUCTION. It reads the bonus back from `closeness.rung_for`, so
    an `inferred-from-messages` strong tier (which hands back the THIN bonus) lands band 1, never
    band 2; a doubted tier is likewise capped; an unmapped tier or `never-spoke` lands band 0.
    """
    if not closeness or not crow:
        return 0
    tier = crow.get("closeness")
    tier = closeness.TIER_ALIASES.get(tier, tier)
    if not tier or tier == "never-spoke":
        return 0
    _rung, _band, _ask, cbonus, _flag = closeness.rung_for(crow, category)
    if not cbonus or cbonus <= 0:
        return 0
    return 2 if (tier in _CLOSE_BAND_STRONG and cbonus >= closeness.CLOSENESS_STRONG) else 1


def reason_terms(why):
    """A reason string reduced to its SCORING terms, provenance stripped.

    `🔬 employer resolved (<url>)` is provenance, not a term that ordered anything, and leaving it
    in makes every row look unique — which would let a tie hide behind a URL. One definition,
    shared by the tie tripwire below and by `contact_card.py`, so the two cannot drift.

    Accepts a string or the row's `reasons` list, so callers need not agree on the join.
    """
    if isinstance(why, (list, tuple)):
        why = " · ".join(str(w) for w in why)
    return " ".join(re.sub(r"·?\s*🔬 employer resolved \([^)]*\)", "", why or "").split())


def top_band_tie(ranked):
    """How much of a shown ranking is indistinguishable from its own top rows?

    Returns `(n_rows, n_score_tied, score, n_reason_tied, reason, n_tied)`, where `n_tied` is the
    UNION of the two groups — the rows whose position is a tiebreak rather than a verdict — CELL COUNTS, never a bare
    percentage.

    ⚠️ WHOLE POINTS, NOT 0.1: a continuous tenure term spreads a functionally identical band across
    50.2/50.1/49.8 and defeats an exact-match counter. ⚖️ The reason string is the sharper half —
    identical stated grounds means no feature separates those rows at all.
    """
    rows = list(ranked or [])
    if not rows:
        return 0, 0, None, 0, "", 0
    sc = collections.Counter(round(float(c.get("pts") or 0)) for c in rows)
    score, n_score = sc.most_common(1)[0]
    rs = collections.Counter(reason_terms(c.get("reasons") or c.get("why") or "") for c in rows)
    reason, n_reason = rs.most_common(1)[0]
    # THE UNION, and it must be the union rather than either count alone. Either condition on its
    # own already makes a row's position a tiebreak, and taking only the larger group understates
    # a band that is tied on score in one half and on stated grounds in the other.
    tied = sum(1 for c in rows
               if (n_score > 1 and round(float(c.get("pts") or 0)) == score)
               or (n_reason > 1 and reason_terms(c.get("reasons") or c.get("why") or "") == reason))
    return len(rows), n_score, score, n_reason, reason, tied


def print_tie_tripwires(ranked, tiebreak):
    """Announce a band the ranker cannot tell apart, for ANY ranked list it shows.

    ⛔ WHY THIS IS A FUNCTION AND NOT TWO COPIES. Both tripwires were written for the PEOPLE board,
    after a cluster of contacts tied on the same score and row 1 was presented as a verdict. They
    were wired into that branch only. The COMPANY board — same module, same `pts`/`reasons` shape,
    same failure — printed its rows and stopped, so it went on showing most of its top ten tied at
    one score, several of them stating byte-identical grounds, and said nothing.

    ⚠️ THE COMPANY TIE WAS ALREADY KNOWN. A sweep had banked most of its companies at one identical
    score, leaving the majority of rows in an alphabetical accident. The response was a BETTER
    TIEBREAK (open seats), which changes who wins a coin flip without ever telling the reader a coin
    was flipped. A tiebreak is not a disclosure. This is the disclosure.

    `tiebreak` names what actually decided the order, so the warning is specific about which
    accident the reader is looking at.
    """
    n, cnt, top, rcnt, rwhy, tied = top_band_tie(ranked)
    if cnt > PLATEAU_WARN_AT:
        print(f"  ⚠️  PLATEAU: {cnt} of {n} shown rows score within a point of "
              f"{top}. Ties this wide mean the ordering below them is a tiebreak, not a "
              f"ranking.")
    if n and tied and tied / n > TIE_RATE_WARN_AT:
        print(f"  🔴 TIE RATE: {tied} of {n} shown rows are indistinguishable — {cnt} share "
              f"the whole-point score {top} and {rcnt} state an IDENTICAL reason.")
        print(f"     The order among them is the TIEBREAK ({tiebreak}), never a "
              "verdict. Row 1 here is a coin flip.")
        if rcnt > 1:
            print(f"     shared reason: {rwhy[:150]}")


# ── SCREENING QUEUE: what to MEASURE next, when the ranking has nothing left to say ────────────
#
# ⛔ THE PROBLEM THIS ANSWERS. `print_tie_tripwires` tells the reader that row 1 is a coin flip. It
# does not tell them what to DO about it, and "pick 3" still points at a band the ranker cannot
# order. The tie is an INPUT problem — the culture criteria are unrecorded on every screened row by
# design, because review sites block agents and the short manual peek is the human's alone — so the
# useful next action is not a better sort, it is a measurement.
#
# 📏 POINTS AT STAKE COME FROM THE SCORER'S OWN WEIGHTS, never a second table, so re-tuning
# CRITERIA_WEIGHTS in kit_config moves this queue with it. `_score_fields` already banks part of the
# leadership weight as "unproven", so a clean screen only adds the remainder.
# ⚠️ The WLB criterion also VETOES below WLB_FLOOR, which no other missing datum can do. A peek does
# not just add points there, it can remove the company from the board entirely — that is why the
# peek is worth more than its point total suggests, and the renderer says so.
COMP_STAKE_POINTS = 10.0     # the published-comp branch of `_score_fields` is worth this much


def _culture_stake():
    """(label, points, …) triples for the culture data a peek would resolve, from the live weights."""
    lw = float(CRITERIA_WEIGHTS.get("leadership_stability", 0) or 0)
    return (("WLB", float(CRITERIA_WEIGHTS.get("wlb", 0) or 0), "peek"),
            ("%recommend", float(CRITERIA_WEIGHTS.get("retention", 0) or 0), "peek"),
            ("leadership", lw * (1.0 - LEADERSHIP_UNPROVEN_FRACTION), "peek"))


def screening_stake(row):
    """(points_at_stake, [what is unmeasured], can_veto) for one scored board row.

    Reads the row's OWN reason strings, which is what the scorer actually emitted, rather than
    re-deriving from the source cells. A criterion the scorer called "n/a" or "not scored" is
    unmeasured BY THE SCORER, which is the only definition that matters here.
    """
    why = " · ".join(row.get("reasons") or [])
    culture = _culture_stake()
    owed, stake, veto = [], 0.0, False
    if "WLB n/a" in why:
        owed.append(culture[0][0]); stake += culture[0][1]; veto = True
    if "rec n/a" in why:
        owed.append(culture[1][0]); stake += culture[1][1]
    if "leadership: unproven" in why:
        owed.append(culture[2][0]); stake += culture[2][1]
    if "comp unpublished" in why:
        owed.append("comp band"); stake += COMP_STAKE_POINTS
    return stake, owed, veto


def print_screening_queue(ranked, limit=10):
    """What to MEASURE next, ordered by how much of the score is currently unmeasured.

    ⛔ AND IT REFUSES TO FAKE AN ORDER. When every row owes the same data — which is the normal
    case, because the culture screen is owed board-wide by design — the stake is identical and
    there is no honest ordering. Inventing one would be the tiebreak mistake a second time: a
    tiebreak dressed as a verdict. It says they are indistinguishable and names the one action that
    resolves all of them instead. A uniform penalty cannot break a tie.
    """
    rows = [(screening_stake(c), c) for c in (ranked or [])]
    rows = [(s, owed, veto, c) for (s, owed, veto), c in rows if owed]
    if not rows:
        return
    rows.sort(key=lambda t: -t[0])
    top = rows[0][0]
    uniform = all(abs(s - top) < 0.01 for s, _o, _v, _c in rows)

    print(f"\n  📋 SCREENING QUEUE — {len(rows)} row(s) carry unmeasured criteria.")
    if uniform:
        names = ", ".join(str(c.get("company") or "") for _s, _o, _v, c in rows[:limit])
        owed = rows[0][1]
        print(f"     All {len(rows)} owe the SAME data and are worth the SAME {top:.0f} points, so "
              f"there is no order here to give you.")
        print(f"     unmeasured on every one: {' · '.join(owed)}")
        print(f"     {names}")
    else:
        for s, owed, veto, c in rows[:limit]:
            flag = " ⚠️ can VETO" if veto else ""
            print(f"     {s:5.0f} pts at stake  {str(c.get('company') or '')[:28]:28} owed: "
                  f"{', '.join(owed)}{flag}")
    if any(v for _s, _o, v, _c in rows):
        print(f"     ⚠️  WLB is the only one that can VETO (below the {WLB_FLOOR} floor). A peek")
        print("         there can remove a company outright, which is worth more than the points say.")


# Trailing window that decides which category is STARVED of sends (the exposure floor, below).
EXPOSURE_WINDOW_DAYS = 30

PERSON_BADGE = {"product-leader": "🎯 likely boss", "founder-exec": "🏛 founder/CEO",
                "senior-exec": "🏢 senior exec", "product-ic": "🤝 product peer",
                "connector": "📇 connector", "senior-ic": "🧩 senior IC", "other": "· other"}

# The org-OWNER titles Ruling A elevates. Deliberately narrow: CTO/VP/directors/partners are senior
# but would not manage a product hire; "managing director" is a level at large firms.
# "(?<!vice )president" because \bpresident\b matches the second word of "Vice President" — the
# first live run promoted a "VP Senior Recruiting Consultant" into the founder band on that token.
_OWNER_TITLE = re.compile(r"\b(founder|co-?founder|ceo|chief executive|coo|chief operating|"
                          r"(?<!vice )president|owner)\b", re.I)
# A "Product Owner" is a scrum-role IC, but SENIOR's \bowner\b matched inside the phrase, so every
# Product Owner in the network scored as a product LEADER under v1 (four of one tied top 10).
_PO_PHRASE = re.compile(r"\bproduct\s+owner\b", re.I)
# `is_pm()` matches `product\b`, which stops at the singular, so "Vice President of Products" and
# "Chief Products Officer" read as senior-exec and every plural-titled product leader sank below
# the fold.
# ⛔ The singularization lives HERE, in the PEOPLE path, and never in `is_pm()` itself: that
# function answers "is this a PM seat worth applying to" and feeds live-role detection, where
# loosening it pushes RADAR companies back to green.
_PLURAL_PRODUCT = re.compile(r"\bproducts\b", re.I)
# Principal/Staff PMs are senior ICs. Under Ruling A "likely boss" means MANAGES the role, so they
# are peers unless the title ALSO carries a real management marker (Head/VP/Director/CPO/founder…).
_IC_SENIORITY = re.compile(r"\b(principal|staff)\b", re.I)
# 🧩 BUG-181 WU-6a. Seniority words `SENIOR` (executive-only) does not match, carried by a non-exec
# IC/manager: the fourth bucket. Kept in lockstep with parse_network.SENIOR_IC, the writer that
# decides which table these rows land in.
_SENIOR_IC = re.compile(r"\b(senior|staff|lead|manager|executive|group)\b", re.I)
# kit issue #57 (partner feedback). A one-person shop has no seat to hire into, whatever the title
# says: "Self Employed" is a KNOWN shape, not the UNKNOWN _company_shape_map() coverage gap the
# module docstring below describes — discarding it let a self-employed contact and a two-person
# family business both rank as functional seniors who "hire or refer". Anchored variants only
# (word-boundary phrases, or the WHOLE employer field being the bare word "self"), never a loose
# substring: a real company legitimately named "Independent Bank" must not be swept in.
_SELF_EMPLOYED_EMPLOYER = re.compile(
    r"\b(self[\s-]?employed|freelanc\w*|independent\s+(?:contractor|consultant)|"
    r"sole\s+propriet\w*)\b|^\s*self\s*$", re.I)


def _is_multi_credit_headline(title):
    """kit#57 guard 2: 3+ slash-separated segments read as a CREDITS LIST ("Performer / Writer /
    Director"), not a single title one seniority token governs."""
    segs = [s.strip() for s in re.split(r"\s*/\s*", title or "") if s.strip()]
    return len(segs) >= 3


def _person_category(title, employer=""):
    """Category from the TITLE and, since kit#57, the EMPLOYER's self-employment shape — the
    company-shape half of the likely-boss predicate is otherwise applied by the caller via
    _company_shape_map(), because shape lives on the green board, not in the title. With shape
    UNKNOWN (most of a network), both plausible-boss reads stay equal. Self-employment is the one
    shape that is NEVER unknown when the employer field says so plainly, so it is read here."""
    t = _PLURAL_PRODUCT.sub("product", title or "")
    # Mask to a SINGLE word: "product-owner" still leaves a \b before "owner" (the hyphen is a
    # non-word char), so the first cut of this mask changed nothing. Verified against a live pool:
    # a "Product Owner" ranked #1 as a likely boss under the hyphen mask.
    masked = _PO_PHRASE.sub("productowner", t)
    pm, sr = is_pm(t), bool(SENIOR.search(masked))
    if sr and _is_multi_credit_headline(title):
        sr = False  # a credits list, not a governing title — do not let it promote
    if pm and sr:
        # Ruling A: a Principal/Staff PM whose only "senior" token is that seniority marker is a
        # peer, not the person who would manage a product hire.
        if _IC_SENIORITY.search(masked) and not SENIOR.search(_IC_SENIORITY.sub("", masked)):
            return "product-ic"
        return "product-leader"   # Head/VP/Dir/CPO of Product — plausibly manages this role
    if sr:
        self_employed = _SELF_EMPLOYED_EMPLOYER.search(employer or "")
        if _OWNER_TITLE.search(masked):
            # kit#57: a verified Owner/Manager of an unrelated one- or two-person shop is not the
            # "likely boss where no product org exists" this tier exists for.
            return "connector" if self_employed else "founder-exec"
        return "connector" if self_employed else "senior-exec"
    if pm:
        return "product-ic"       # PM/Sr PM — a would-be teammate who can refer/intro
    if CONNECTOR.search(t):
        return "connector"        # recruiter/talent — routes you
    # 🧩 THE FOURTH BUCKET (BUG-181 WU-6a). Runs LAST, so it only catches a seniority word carried by
    # a title none of the sharper reads matched — a non-exec IC/manager. A SEPARATE people-test,
    # never a loosened `is_pm()`. Mirrors parse_network.classify(), the writer of the table it reads.
    if _SENIOR_IC.search(masked):
        return "senior-ic"
    return "other"


# Boss-cell readers for _company_shape_map. A 🌾 row (no product function yet — a greenfield 0-to-1
# target) is founder-led by definition; otherwise the recorded boss's own title is the tell.
_BOSS_IS_PRODUCT = re.compile(r"\b(cpo|chief product|vp,?\s*(of\s+)?product|head of product|"
                              r"director,?\s*(of\s+)?product|product lead)\b", re.I)
_BOSS_IS_FOUNDER = re.compile(r"\b(founder|co-?founder|ceo|coo|owner|president)\b", re.I)


def _company_shape_map():
    """company(lower) → 'product-led' | 'founder-led', read from the green board's Boss column.

    This is the second input the likely-boss predicate needs: "likely boss" is a two-place predicate
    of PERSON and COMPANY SHAPE (Bible p.10 — small/flat company → the CEO IS the target), and v1's
    category read the title only. warm-network.md records no shape, but the green board does,
    implicitly, in whose name sits in the Boss cell. Coverage is only the boarded companies;
    everywhere else shape is honestly UNKNOWN and both plausible-boss reads stay equal rather than
    one being guessed. Reads the same board file and column offset as board_candidates(), so the two
    cannot drift onto different rows.
    """
    shapes = {}
    for line in rd("documents/green-board.md").splitlines():
        if not line.strip().startswith("|") or line.count("|") < 8:
            continue
        cells = [c.strip().strip("*") for c in line.split("|")]
        off = row_offset(cells)
        co = cells[1 + off] if len(cells) > 1 + off else ""
        boss = cells[6 + off] if len(cells) > 6 + off else ""
        if not co or not re.match(r"^[A-Z0-9]", co) or co.lower() == "company":
            continue
        if "🌾" in line or (_BOSS_IS_FOUNDER.search(boss) and not _BOSS_IS_PRODUCT.search(boss)):
            shapes[co.lower()] = "founder-led"
        elif _BOSS_IS_PRODUCT.search(boss):
            shapes[co.lower()] = "product-led"
    return shapes


# ── DYNAMIC WEIGHTS (the ruling: weights should be dynamic as the pipeline grows, and the same
#    applies to founder ordering) ────────────────────────────────────────────────────────────
# The category numbers above are PRIORS, not truths. What the pipeline can already MEASURE is
# reply-per-send by rung (scripts/rung_ladder.py); joining each delivered send to the contact's
# CATEGORY gives reply evidence per category, and that evidence pulls the effective weight away
# from the prior as N grows. Design decisions, each explicit because each is contestable:
#
#   · PRIOR = Beta(m·p0, m·(1-p0)) with p0 EQUAL across categories. The literature orders VALUE
#     (whom a reply is worth having from: workbook pp.10-11), it nowhere claims founders REPLY
#     less — so propensity starts flat and only the log can bend it. PERSON_BASE carries the
#     value ordering; the evidence ratio carries the learned propensity. Separating them is what
#     keeps the score explainable.
#   · SHRINKAGE: m = 25 pseudo-sends. At ~25 joined sends in a category the data and the prior are
#     equal partners; below ~10 the prior dominates. On a real pipeline a meaningful share of sends
#     is typically MISSING from the log, so every measured rate is an UPPER BOUND — heavy shrinkage
#     is honesty, not caution.
#   · EXPLORE: effective rate = posterior mean + κ·σ (κ=1). A pure outcome-learner never tries what
#     it never tried (a referred rung with ZERO sends ever stays at zero forever); the uncertainty
#     term keeps a thin category competitive instead of letting one lucky reply elsewhere bury it.
#   · CLAMP [0.5, 2.0] on the evidence ratio: one 1/1 fluke cannot triple a band, and no volume of
#     silence can zero one — bounded influence is what makes a tiny-N learner safe to ship.
#   · FOUNDER ORDER IS EVIDENCE-MOVABLE, by the same ruling. Default "last" is the owner's; it flips to "neutral" when the founder-exec posterior mean overtakes the
#     product-leader's on ≥10 joined founder sends. Flipping past neutral to "first" is the OWNER's
#     ruling to make when the evidence exists, not the model's.
#   · THE WRITE IS DISCIPLINED. Weights recompute ONLY via `--recompute-weights`, which appends a
#     dated, provenance-carrying row to documents/state/person-weights.jsonl (append-only, newest
#     wins — state.py's guarantees, hand-carried because state.KINDS is a fixed tuple and extending
#     it is a migration of a TRACKED file). rank_people READS the stored row and prints its date +
#     how many sends have landed since, so a session can SEE the weights' age; it never recomputes
#     silently. No stored row → pure priors, and the output says so.
#
# ⚙️ Every knob below is retunable from kit_config, each in its OWN try/except — see the note at
# PERSON_BASE for why they are not one combined import. WEIGHTS_STORE stays a module constant
# because it must match state.py's STATE_DIR convention (documents/state/), not a taste setting.
WEIGHTS_STORE = "documents/state/person-weights.jsonl"
try:
    from kit_config import PERSON_PRIOR_RATE
except Exception:
    PERSON_PRIOR_RATE = 0.10      # p0 — flat across categories on purpose (see above)
try:
    from kit_config import PERSON_PRIOR_STRENGTH
except Exception:
    PERSON_PRIOR_STRENGTH = 25    # m — pseudo-sends; the "when does data outrank the prior" knob
try:
    from kit_config import PERSON_EXPLORE_KAPPA
except Exception:
    PERSON_EXPLORE_KAPPA = 1.0    # κ — optimism for under-sampled categories
try:
    from kit_config import PERSON_RATE_CLAMP
except Exception:
    PERSON_RATE_CLAMP = (0.5, 2.0)
try:
    from kit_config import WEIGHTS_STALE_AFTER
except Exception:
    WEIGHTS_STALE_AFTER = 15      # sends landed since compute before the output flags staleness

# ── THE SAMPLING ALLOWANCE ──────────────────────────────────────────────────────────────────
# κ above is an optimism term on the RATE. It cannot fix the failure it was written for, because a
# category that never scores high enough to be PICKED never produces a send to learn from, and a rate
# multiplier applied to a base of 15 against a base of 45 does not close that gap. A pure
# outcome-learner never tries what it never tried. On a real run the `connector` band — where every
# warm off-segment contact lands — showed zero sends and zero replies at w 1.00, while the top band
# sat at w 1.83 on real evidence. The ranker structurally could not sample the empty band.
#
# ⚖️ THIS IS A SAMPLING DEVICE, NOT A VALUE CLAIM, and the distinction is the whole point. It does
# NOT assert a connector is worth as much as a founder — PERSON_BASE still carries your ratified
# value ordering, untouched. It buys the band enough score to be SEEN a few times so the learned rate
# has something to learn from, and it decays to exactly ZERO once that has happened. After
# PERSON_EXPLORE_N joined sends the term vanishes and the band is judged on evidence alone, so this
# cannot become a permanent hand-typed thumb on the scale.
#
# 🔴 THE FLAT-BONUS VERSION OF THIS WAS WRONG AND A TEST CAUGHT IT. It added a flat +20 to every
# under-sampled band, so the HIGHEST band — merely unsampled in that fixture — outscored a band with
# real sends and real replies. An untested band outranking an EARNED one inverts the entire point of
# learning. The comment already said "parity with the LOWEST measured band"; the code said "+20 to
# anyone". Intent and implementation disagreed and the code shipped.
#
# CEILINGED FORM: an untested band is lifted to just BELOW the weakest band that HAS been tested.
# That is enough to get it sampled and cannot outrank anything that earned its place. Self-sizing, so
# there is no magic number to re-tune when the priors or the evidence change.
try:
    from kit_config import PERSON_EXPLORE_N
except Exception:
    PERSON_EXPLORE_N = 5        # joined sends after which a band is "tested" and the loan is repaid
try:
    from kit_config import PERSON_EXPLORE_EPSILON
except Exception:
    PERSON_EXPLORE_EPSILON = 1.0  # stay strictly UNDER the weakest tested band — evidence wins ties


def explore_allowance(cat, wcat):
    """(points, reason) letting an untested category be sampled. Never outranks earned evidence.

    Zero when: the band is already tested, no band is tested yet (nothing to calibrate against), or
    the band already scores at or above the weakest tested band on its own.
    """
    n = int((wcat.get(cat) or {}).get("sends", 0) or 0)
    if n >= PERSON_EXPLORE_N:
        return 0.0, None
    tested = [PERSON_BASE[c] * float((wcat.get(c) or {}).get("w", 1.0))
              for c in PERSON_BASE
              if int((wcat.get(c) or {}).get("sends", 0) or 0) >= PERSON_EXPLORE_N]
    if not tested:
        return 0.0, None
    ceiling = min(tested) - PERSON_EXPLORE_EPSILON
    own = PERSON_BASE[cat] * float((wcat.get(cat) or {}).get("w", 1.0))
    pts = round(ceiling - own, 1)
    if pts <= 0:
        return 0.0, None
    seen = f"{n} joined send{'s' if n != 1 else ''}" if n else "never sampled"
    return pts, (f"🎲 exploration allowance ({seen}, +{pts:g}) — lifted to just under the weakest "
                 f"TESTED band so it can be sampled, repaid to 0 by {PERSON_EXPLORE_N} sends")


def _posterior(sends, replies, p0=None, m=None):
    """Beta-binomial posterior (mean, sd) for a category's reply propensity."""
    p0 = PERSON_PRIOR_RATE if p0 is None else p0
    m = PERSON_PRIOR_STRENGTH if m is None else m
    a = m * p0 + replies
    b = m * (1 - p0) + (sends - replies)
    mean = a / (a + b)
    sd = (a * b / ((a + b) ** 2 * (a + b + 1))) ** 0.5
    return mean, sd


# Rungs whose recipient SHOULD be findable in the warm roster. Everything else is a stranger by
# definition, and its absence from the roster is CORRECT rather than a missed join.
#
# 📏 THIS IS THE COVERAGE DENOMINATOR, and getting it wrong is how a healthy join rate gets read as
# "most of the evidence is lost". Measured on a live log, joins by rung ran ~1% on cold-boss sends
# (strangers — 1% is right, not a defect), ~28% on cold-stranger, ~49% on warm and ~26% on reply.
# Scoring the COLD rungs into coverage understates it by roughly half, which would drive the
# shrinkage correction below to over-widen every posterior on evidence that was never missing.
ROSTER_RUNGS = {"warm", "reply", "follow-up", "followup", "thank-you", "reunion",
                "off-ladder", "referred", "application"}


def _identity_map():
    """{squashed LinkedIn slug or lowercased email: "First Last"} from the newest network export.

    The send log records WHOM by whatever handle the send used, and on a real log that is a mix:
    most rows carry a `linkedin.com/in/<slug>`, a good share carry an email, a few carry a bare name
    and the rest carry nothing at all. Substring-matching a NAME against a SLUG recovers only the
    slugs that happen to BE the name — it cannot resolve a nickname or an initials handle, and it
    cannot resolve an email at all. The connections export carries both `URL` and `Email Address`
    beside the name, so the mapping is a LOOKUP rather than a guess.

    Best-effort by contract: any failure returns {} and the caller falls back to the substring
    heuristic. A briefing must never block (`Exit: 0 always`).
    """
    out = {}
    try:
        import csv as _csv
        import io as _io
        from parse_network import find_export
        _path, text = find_export()
        # The export prefixes Connections.csv with a multi-line "Notes:" preamble about missing email
        # addresses. Feeding that straight to DictReader makes "Notes:" the header and every lookup
        # silently returns None — a map of size 0 that raises nothing and looks like "no matches".
        lines = text.splitlines(True)
        for i, ln in enumerate(lines):
            if ln.lstrip().startswith("First Name"):
                text = "".join(lines[i:])
                break
        for row in _csv.DictReader(_io.StringIO(text)):
            name = f"{(row.get('First Name') or '').strip()} {(row.get('Last Name') or '').strip()}"
            if not name.strip():
                continue
            url = (row.get("URL") or "").strip().lower()
            m = re.search(r"/in/([^/?#]+)", url)
            if m:
                out[re.sub(r"[^a-z0-9]", "", m.group(1))] = name.strip()
            email = (row.get("Email Address") or "").strip().lower()
            if email:
                out[email] = name.strip()
    except Exception:
        return {}
    return out


def _category_evidence():
    """(per_category {cat: [sends, replies]}, joined, log_rows, attributable) — send log × network.

    Only rows whose recipient matches a warm-network contact join — those are the population this
    ranker ranks. Cold sends to strangers are a different population and stay in rung_ladder's
    per-rung view. Undelivered rows leave the denominator, same rule as the ladder: a bounce never
    reached a person, so counting it as a silent send would learn "this category ignores me" from
    a mail server.

    ⚖️ Resolution is TWO-PASS: the export's identity map FIRST (exact, by slug or email), then the
    original substring heuristic. `attributable` counts the rows that could EVER have joined (see
    ROSTER_RUNGS), so coverage is honest about what is MISSING rather than about what was never
    there — a distinction the shrinkage term below depends on completely."""
    try:
        from rung_ladder import load as _load_sends, NOT_DELIVERED
        rows = _load_sends()
    except Exception:
        return {c: [0, 0] for c in PERSON_BASE}, 0, 0, 0
    cats, by_name = {}, {}
    for name, title, co, _fl, _ks in _people_rows():
        nm = re.sub(r"[^a-z0-9]", "", name.lower())
        if len(nm) >= 6:
            cats[nm] = _person_category(title, co)
            by_name[nm] = _person_category(title, co)
    ident = _identity_map()
    per = {c: [0, 0] for c in PERSON_BASE}
    joined = attributable = 0
    for r in rows:
        if str(r.get("status", "")).lower() in NOT_DELIVERED:
            continue
        raw = str(r.get("to", "")).strip()
        rung = str(r.get("rung", "")).strip().lower()
        if raw and rung in ROSTER_RUNGS:
            attributable += 1
        to = re.sub(r"[^a-z0-9]", "", raw.lower())
        if len(to) < 6:
            continue
        cat = None
        # Pass 1 — exact identity, via the export's slug/email map.
        who = ident.get(raw.lower()) or ident.get(re.sub(r"^.*?/in/", "", to))
        if who is None:
            m = re.search(r"/in/([^/?#]+)", raw.lower())
            if m:
                who = ident.get(re.sub(r"[^a-z0-9]", "", m.group(1)))
        if who:
            cat = by_name.get(re.sub(r"[^a-z0-9]", "", who.lower()))
        # Pass 2 — the original substring heuristic, unchanged.
        if cat is None:
            cat = next((c for nm, c in cats.items() if nm in to or to in nm), None)
        if cat is None:
            continue
        joined += 1
        per[cat][0] += 1
        per[cat][1] += 1 if r.get("replied") else 0
    return per, joined, len(rows), attributable


# A predictor may only read what was known ON THE SEND DATE. A title from an export snapshot passes.
# Anything read from today's thread state (they replied, the thread is live, closeness was later
# stated) is reading the outcome back into the predictor, and it will look brilliant and predict
# nothing.
LEAKY_FIELDS = ("replied", "reply_date", "reply_kind", "stage", "stage_at", "replied_note",
                "outcome", "followup_due")


# ── WARM PATH: the first signal to clear the validation gate (ratified 2026-08-11) ──────────────
#
# 📊 THE EVIDENCE IT RATIFIED ON, measured over this user's own send log: replies were markedly
# more likely where a path into the company already existed BEFORE the send than where none did.
# First signal to pass since the gate killed three endorsement variants.
#
# ⚠️ THE SAME SIGNAL READ FLAT SIX HOURS EARLIER and that was an ARTEFACT, not a null. The join was
# starved: `company` and `to_name` were missing on precisely the rungs that convert, so the joinable
# half was a cold-boss sample with a depressed base rate against the true one. Reporting it as a
# kill would have retired the one feature the outcome record points at.
# ⛔ Do not call an underpowered result a negative one.
#
# ⚖️ THE WEIGHT IS LEARNED, NEVER TYPED. `warm_path_lift()` re-measures the ratio from the live send
# log on every run, so the bonus tracks the evidence instead of freezing a number someone liked in
# August (learned weights, never typed; a validated signal, not a hand-placed bonus).
# 🌏 A COUNTRY NAMED IN THE RESOLVED INDUSTRY TEXT IS A CHEAP REMOTE-US TELL. The segment cache
# writes a plain-language industry line ("Nigerian microfinance bank offering...", "Singapore-based
# super-app"), so the country is usually right there for free. Deliberately CONSERVATIVE: it fires
# only on an explicit national adjective or a country name, never on a city, so a US company with a
# foreign office survives and reaches the real remote gate.
_NON_US_TELL = re.compile(
    r"\b(nigerian?|indian?|singapore(an)?|chinese|china|brazil(ian)?|mexican|mexico|"
    r"german(y)?|french|france|spanish|spain|italian|italy|dutch|netherlands|swedish|sweden|"
    r"norwegian|norway|danish|denmark|finnish|finland|polish|poland|israeli|israel|"
    r"japanese|japan|korean|korea|australian|australia|kenyan|kenya|"
    r"south africa(n)?|indonesia(n)?|philippin|vietnam(ese)?|thai(land)?|malaysia(n)?|"
    r"south ?east asia|latin america|emea|apac|uk[- ]based|british)\b", re.I)

WARM_PATH_MIN_N = 15          # the same floor `validate_signal` refuses to ratify under
WARM_PATH_MAX_POINTS = 10.0   # ceiling, so one learned term cannot swamp the whole 36-criterion card


def warm_path_lift():
    """(lift, with_cell, without_cell) measured live, or (None, ...) when the evidence is too thin.

    Returns None for the lift when `n` is under the floor, and every caller must then score NOTHING.
    A signal that cannot be measured today must not carry yesterday's weight.
    """
    try:
        from rung_ladder import load as _load, NOT_DELIVERED as _ND
        import send_identity as _si
        from screen_sweep import canon as _canon
        from datetime import datetime as _dt
        import parse_network as _pn
    except Exception:
        return None, (0, 0), (0, 0)
    known = _known_people_by_company(_pn, _canon)
    if not known:
        return None, (0, 0), (0, 0)
    cache = _si.store()
    a_s = a_r = b_s = b_r = 0
    for r in _load():
        if str(r.get("status", "")).lower() in _ND:
            continue
        co = _canon(_si.company_for(r, cache=cache)[0])
        if not co:
            continue
        try:
            sd = _dt.strptime((r.get("date") or "")[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        me = re.sub(r"[^a-z0-9]", "", (_si.name_for(r, cache=cache)[0] or "").lower())
        # ⛔ STRICTLY BEFORE, and never the recipient themself. Without the date guard every cold
        # send that LATER became a connection counts as a path that existed beforehand, which is
        # the outcome leaking into the predictor.
        hit = any(d < sd and re.sub(r"[^a-z0-9]", "", w.lower()) != me for d, w in known.get(co, ()))
        if hit:
            a_s += 1; a_r += 1 if r.get("replied") else 0
        else:
            b_s += 1; b_r += 1 if r.get("replied") else 0
    if a_s < WARM_PATH_MIN_N or not b_s or not b_r:
        return None, (a_r, a_s), (b_r, b_s)
    return (a_r / a_s) / (b_r / b_s), (a_r, a_s), (b_r, b_s)


_KNOWN_BY_CO = None


def _known_people_by_company(pn, canon):
    """company key -> [(connect_date, person)], from the export. Cached for the process."""
    global _KNOWN_BY_CO
    if _KNOWN_BY_CO is not None:
        return _KNOWN_BY_CO
    out = collections.defaultdict(list)
    d = os.path.join(REPO, "documents", "linkedin-exports")
    if os.path.isdir(d):
        best = {}
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(".csv"):
                continue
            try:
                text = open(os.path.join(d, fn), encoding="utf-8-sig", errors="replace").read()
            except Exception:
                continue
            for r in pn.parse_rows(text):
                key = (r.get("URL") or "").strip().lower()
                when = pn.connected_on(r.get("Connected On"))
                co = (r.get("Company") or "").strip()
                who = f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip()
                if not key or not when or not co or not who:
                    continue
                if key not in best or when < best[key][0]:
                    best[key] = (when, co, who)
        for when, co, who in best.values():
            k = canon(co)
            if k:
                out[k].append((when, who))
    _KNOWN_BY_CO = out
    return out


def warm_path_points(company, lift):
    """(points, reason) for one company. Scores NOTHING when the signal is unmeasurable today."""
    if lift is None or not company:
        return 0.0, None
    try:
        from screen_sweep import canon as _canon
        import parse_network as _pn
    except Exception:
        return 0.0, None
    people = _known_people_by_company(_pn, _canon).get(_canon(company), [])
    if not people:
        return 0.0, "warm path: none known there"
    # Scaled by the MEASURED lift, capped, and flat in the count: knowing six people is not six
    # times one door. The evidence says a path exists or it does not.
    pts = min(WARM_PATH_MAX_POINTS, (lift - 1.0) * WARM_PATH_MAX_POINTS)
    return max(0.0, pts), (f"🔗 warm path: {len(people)} known there "
                           f"(+{max(0.0, pts):.1f}, learned lift {lift:.2f}x)")


# ── PERSON-LEVEL LEARNED TERMS (BUG-181 WU-3) ────────────────────────────────────────────────────
# Among equally-warm peers the score is band-uniform, so a tie collapses onto the connect date. WU-3
# derives per-person candidates the same way the category weights are derived: measure a reply-rate
# lift from the live send log, clamp it, refuse it below n≥15, and score NOTHING when it cannot be
# measured — never a typed guess. Degrades to "scores nothing" on a thin/absent partner join, which
# is the correct behavior, not a bug.
PERSON_LIFT_MIN_N = 15
PERSON_LIFT_MAX_POINTS = 6.0                  # capped BELOW the ratified closeness bonus of +6
PERSON_LIFT_CLAMP = PERSON_RATE_CLAMP


def _person_signal_cells():
    """Join every delivered send to its recipient's STATED closeness band and thread state.

    Returns {"closeness": {band: [s, r]}, "thread": {state: [s, r]}, "joined": n, "delivered": n}.
    The partner tree has no send-identity sidecar, so the recipient name is read from the row's own
    `to_name`, then the export identity map — a THINNER join than the primary tree by design. A thin
    join keeps every cell under the n≥15 floor, so the learned terms correctly score nothing.

    ⚠️ LEAKAGE. The closeness BAND is a stated prior relationship (valid predictor); an
    `inferred-from-messages` strong tier is haircut to band 1 by `_close_band`. The THREAD state is
    `closeness.thread_state(TODAY)`, where "live" MEANS "they replied" — the outcome read back into
    the predictor, so its cells are counted for the audit but never scored."""
    out = {"closeness": {}, "thread": {}, "joined": 0, "delivered": 0}
    for k in ("strong", "thin", "never"):
        out["closeness"][k] = [0, 0]
    try:
        from rung_ladder import load as _load, NOT_DELIVERED as _ND
    except Exception:
        return out
    if not closeness:
        return out
    close = closeness.load()
    ident = _identity_map()
    for r in _load():
        if str(r.get("status", "")).lower() in _ND:
            continue
        out["delivered"] += 1
        nm = (r.get("to_name") or "").strip()
        if not nm:
            raw = str(r.get("to", "")).strip().lower()
            who = ident.get(raw)
            if who is None:
                m = re.search(r"/in/([^/?#]+)", raw)
                if m:
                    who = ident.get(re.sub(r"[^a-z0-9]", "", m.group(1)))
            nm = who or ""
        if not nm:
            continue
        crow = closeness.tier_for(nm, close)
        band = _close_band(crow, "other") if crow else 0
        rep = 1 if r.get("replied") else 0
        out["joined"] += 1
        # ⛔ B1 LEAKAGE GUARD. An `inferred-from-messages` closeness tier was read out of the very
        # thread this reply lives in — the same leakage class the thread bonus is silenced for.
        # `_close_band` haircuts an inferred `know-well` to band 1, so its reply would otherwise
        # corroborate that inferred band in the THIN scored cell. Only STATED-provenance replies may
        # enter a scored lift cell, so the guard fires for strong/thin. The `never` base is
        # preserved: an inferred band-0 row is `never-spoke` (no bonus, no tier to corroborate), so
        # counting it in the denominator is not leakage and dropping it would bias the base upward.
        inferred = bool(crow) and str(crow.get("source") or "") in closeness.INFERRED_SOURCES
        key = {2: "strong", 1: "thin"}.get(band, "never")
        if not (inferred and key != "never"):
            out["closeness"][key][0] += 1
            out["closeness"][key][1] += rep
        tstate = closeness.thread_state(crow)[0] if crow else "never"
        cell = out["thread"].setdefault(tstate, [0, 0])
        cell[0] += 1
        cell[1] += rep
    return out


_PERSON_CELLS_CACHE = {}


def _cells():
    if "c" not in _PERSON_CELLS_CACHE:
        _PERSON_CELLS_CACHE["c"] = _person_signal_cells()
    return _PERSON_CELLS_CACHE["c"]


def _lift(cell, base):
    """(lift, treated, base) with the n≥15 floor: None when the treated cell is under-floor or a base
    rate cannot be formed. Clamped so one term cannot invert the card."""
    a_s, a_r = cell[0], cell[1]
    b_s, b_r = base[0], base[1]
    if a_s < PERSON_LIFT_MIN_N or not b_s or not b_r or not a_s:
        return None, (a_r, a_s), (b_r, b_s)
    lo, hi = PERSON_LIFT_CLAMP
    raw = (a_r / a_s) / (b_r / b_s)
    return max(lo, min(hi, raw)), (a_r, a_s), (b_r, b_s)


def closeness_tier_lift():
    """{band: (lift|None, treated, base)} for the stated-closeness bands, measured live."""
    c = _cells()["closeness"]
    base = c.get("never", [0, 0])
    return {b: _lift(c.get(b, [0, 0]), base) for b in ("strong", "thin")}


def closeness_tier_points(band, lifts):
    """(points, reason) — the LEARNED closeness term that enters `pts`, or (0.0, None). Scores nothing
    when the band's cell is under the floor; only orders WITHIN a band (the sort leads on close_band)."""
    key = {2: "strong", 1: "thin"}.get(band)
    if not key:
        return 0.0, None
    lift, treated, _base = lifts.get(key, (None, (0, 0), (0, 0)))
    if lift is None:
        return 0.0, None
    pts = max(0.0, min(PERSON_LIFT_MAX_POINTS, (lift - 1.0) * PERSON_LIFT_MAX_POINTS))
    if pts <= 0:
        return 0.0, (f"closeness-tier learned: {key} lift {lift:.2f}x — no lift over never-spoke, +0")
    return round(pts, 1), (f"📊 {key}-tier learned +{pts:.1f} "
                           f"({treated[0]}/{treated[1]} joined replies, lift {lift:.2f}x)")


def thread_depth_lift():
    """(None, treated, base, reason) — ALWAYS None: thread_state is a post-send outcome ('live' ==
    'they replied') with no dated snapshot, so it cannot be validated leakage-free."""
    c = _cells()["thread"]
    live = c.get("live", [0, 0])
    never = c.get("never", [0, 0])
    return None, (live[1], live[0]), (never[1], never[0]), \
        "thread state is a post-send outcome (no dated snapshot) — leakage, cannot validate"


def thread_depth_points():
    """(0.0, None) — the thread bonus is unvalidatable (leakage), so it scores nothing."""
    return 0.0, None


def audit_signals():
    """Walk every live people-scoring term, classify its basis, and print joined-n per cell every
    run (the learner-never-learns guard). Returns the count of TYPED-UNVALIDATED terms; 0 is GREEN.

    ⚖️ ONE CLASSIFIER, TWO CODE STATES: reads `_THREAD_SCORED`/`_EVTIER_RATIFIED` via
    `globals().get(..., <RED default>)`, so a pre-WU-3 tree is RED under the identical function."""
    LEARNED, RATIFIED, SILENT, TYPED = "LEARNED", "RATIFIED", "SCORES-NOTHING", "TYPED-UNVALIDATED"
    thread_scored = globals().get("_THREAD_SCORED", True)
    evtier_ratified = globals().get("_EVTIER_RATIFIED", False)
    band_leads = bool(globals().get("CLOSE_BAND_LEADS", 0))
    cells = _cells()
    W = live_weights(stamp=False) or {}   # inspection mode: derive but do NOT write the stamp (DoD #6, kit parity)
    wcat = W.get("per_category", {})
    lines, typed_n = [], [0]

    def row(term, status, basis, witness=""):
        if status == TYPED:
            typed_n[0] += 1
        lines.append((term, status, basis, witness))

    row("category multiplier ×w", LEARNED, f"reply rate per category, clamped {list(PERSON_RATE_CLAMP)}",
        f"{W.get('joined', 0)}/{W.get('log_rows', 0)} sends joined")
    for cat, d in sorted(wcat.items()):
        lines.append((f"    ├ {cat}", "", f"×{d.get('w', 1):g}",
                      f"n={d.get('sends', 0)} replies={d.get('replies', 0)}"))
    row("exploration allowance", LEARNED, "self-repaying sampler for an under-sampled band", "e.g. senior-ic")
    cl = closeness_tier_lift()
    row("closeness bonus +6/+3", RATIFIED, "stated strong/thin tiers", "corroboration below")
    for b in ("strong", "thin"):
        lift, treated, base = cl.get(b, (None, (0, 0), (0, 0)))
        ls = f"lift {lift:.2f}x" if lift is not None else "under n≥15 floor → scores nothing"
        lines.append((f"    ├ {b} learned-lift", "", ls,
                      f"n={treated[1]} replies={treated[0]} vs never n={base[1]} replies={base[0]}"))
    any_clear = any(cl.get(b, (None,))[0] is not None for b in ("strong", "thin"))
    row("closeness-tier learned +pts", LEARNED if any_clear else SILENT,
        "clamp, n≥15 floor, under-floor ⇒ 0.0", "adds to pts only where a band clears the floor")
    # warm path (company-level) — ratified + learned lift, re-measured every run.
    wl, wa, wb = warm_path_lift()
    row("warm path (company)", RATIFIED,
        "ratified 2026-08-11; lift re-measured every run",
        (f"with n={wa[1]} replies={wa[0]} vs without n={wb[1]} replies={wb[0]}; "
         + (f"lift {wl:.2f}x" if wl is not None else "under floor → scores nothing")))
    t = cells["thread"]
    tw = "  ".join(f"{k}:n={t.get(k, [0, 0])[0]}/r={t.get(k, [0, 0])[1]}"
                   for k in ("live", "cooling", "dead", "never"))
    if thread_scored:
        row("thread bonus +4/+2", TYPED, "typed +4/+2/0, no outcome data", tw)
    else:
        row("thread bonus", SILENT, "leakage: thread_state is post-send ('live'=='replied') → 0 pts", tw)
    if evtier_ratified and band_leads:
        row("evtier (employer evidence)", RATIFIED, "within-band ordering, demoted below closeness; 0 pts", "")
    else:
        row("evtier (employer evidence)", TYPED, "no outcome join; leads the sort as unvalidated primary", "")
    row("closeness band sort-lead", RATIFIED, "WU-2: stated tier leads the sort", "")
    row("connect-date distance/years", RATIFIED, "capped plateau-spreader proxy", "")

    print("=" * 74)
    print("  SIGNAL AUDIT — every live people-scoring term, classified (BUG-181 WU-3)")
    print("=" * 74)
    for term, status, basis, witness in lines:
        if status:
            print(f"  {status:18} {term}")
            print(f"  {'':18}   {basis}")
            if witness:
                print(f"  {'':18}   witness: {witness}")
        else:
            print(f"  {'':18} {term:30} {basis:14} {witness}")
    print("-" * 74)
    print(f"  person-cell join: {cells['joined']} of {cells['delivered']} delivered sends named")
    print(f"\n  TYPED-UNVALIDATED terms: {typed_n[0]}   "
          f"({'✅ GREEN' if typed_n[0] == 0 else '🔴 RED'})")
    return typed_n[0]


_SEND_IDENTITY_CACHE = None


def _send_identity_name(row):
    """The recipient's name for a send row, filling from the sidecar where the row is silent.

    ⚠️ DEGRADES TO THE ROW, never to a guess. If the sidecar is missing or unreadable this returns
    exactly what the row already said, so the join gets no worse than it was.
    """
    global _SEND_IDENTITY_CACHE
    try:
        import send_identity
        if _SEND_IDENTITY_CACHE is None:
            _SEND_IDENTITY_CACHE = send_identity.store()
        return send_identity.name_for(row, cache=_SEND_IDENTITY_CACHE)[0]
    except Exception:
        return (row.get("to_name") or "").strip()


def validate_signal(name, predicate=None, path=None, population="note"):
    """Join a candidate predicate to the send log and report whether it discriminates.

    Returns a dict; prints a human report. NEVER scores anything — ratification is yours.

    `population` chooses WHERE the predicate is matched to build the flagged set:
      · "note"   — the closeness store's `note` field (the original path; loose, note-dependent).
      · "titles" — the recipient's TITLE from `_people_rows()`, the export-snapshot title frozen at
                   the connect date (for title-shaped hypotheses like function relevance). A title is
                   a SEND-DATE-safe feature, so it clears leakage by construction. Added so the
                   harness can test title predicates without misreading them against `note`.
    """
    known = {
        # Title-shaped, computable from the export snapshot as of the send date.
        "recruiter": (r"recruit|talent|sourcer|staffing|people ops|acquisition|headhunt",
                      "note", "title carries a placement-side word"),
        "founder": (r"founder|ceo|co-?founder|owner|principal", "note", "title carries an owner word"),
    }
    pred = predicate
    field, why = "note", "custom predicate"
    if pred is None:
        if name not in known:
            print(f"🔴 unknown signal {name!r}. Known: {', '.join(sorted(known))}, "
                  f"or pass a regex.")
            return {"error": "unknown"}
        pred, field, why = known[name]
    if population == "titles":
        field = "title"
        why = f"{why} · matched over TITLES (_people_rows)"

    # ── LEAKAGE TEST, first, because a leaky feature must never reach the join ──
    leaks = [f for f in LEAKY_FIELDS if f in (pred or "")]
    if leaks or field in LEAKY_FIELDS:
        print(f"🔴 REFUSED: {name!r} reads {leaks or [field]}, which is only known AFTER the send.")
        print("   That is the outcome leaking into the predictor. It would score beautifully and")
        print("   predict nothing. A feature must be computable from what was known on the SEND DATE.")
        return {"error": "leaky", "fields": leaks or [field]}

    rx = re.compile(pred, re.I)
    norm = lambda x: re.sub(r"[^a-z0-9]", "", (x or "").lower())
    if population == "titles":
        # Flag by TITLE from the people rows (name, title, company, flag, known_since).
        flagged = set()
        try:
            for _row in _people_rows():
                _nm, _title = _row[0], _row[1]
                if rx.search(str(_title or "")):
                    flagged.add(norm(_nm))
        except Exception:
            pass
    else:
        store = {}
        try:
            cl_path = os.path.join(REPO, "documents", "contact-closeness.json")
            store = json.load(open(cl_path, encoding="utf-8")).get("contacts", {})
        except Exception:
            pass
        flagged = {norm(k) for k, v in store.items() if rx.search(str(v.get(field) or ""))}

    try:
        from rung_ladder import load as _load_sends, NOT_DELIVERED
        rows = _load_sends()
    except Exception:
        print("🔴 cannot read the send log; nothing to validate against.")
        return {"error": "no-log"}

    a_s = a_r = b_s = b_r = unjoined = 0
    for r in rows:
        if str(r.get("status", "")).lower() in NOT_DELIVERED:
            continue
        # 🔗 THE SIDECAR FILLS THE SILENCE (BUG-166). A large share of delivered sends carry no
        # `to_name`, and most replies sit in that group, so this join saw a fraction of the evidence
        # and two separate signals died of it. The log is NEVER rewritten, so the name lives beside
        # it keyed on the address the row DOES carry. `name_for` puts the row's own `to_name` first
        # and answers only where the row is silent.
        who = norm(_send_identity_name(r))
        if not who:
            unjoined += 1
            continue
        hit = who in flagged
        if hit:
            a_s += 1
            a_r += 1 if r.get("replied") else 0
        else:
            b_s += 1
            b_r += 1 if r.get("replied") else 0

    print(f"\n── SIGNAL: {name} ── ({why})")
    if a_s == 0:
        print(f"   ⚪ CANNOT BE VALIDATED: 0 joinable sends carry this signal.")
        print(f"      {unjoined} row(s) carry no recipient NAME at all and can never join.")
        print("      This is not a 0% rate. It is an absence of evidence, and scoring it would be")
        print("      typing a weight from nothing. Send to some and re-run.")
        return {"error": "no-cells", "unjoined": unjoined}

    # ⛔ CELL COUNTS, never bare percentages. A rate with no n invites a ruling the data cannot carry.
    print(f"   carries it   : {a_r}/{a_s} replied")
    print(f"   does not     : {b_r}/{b_s} replied")
    print(f"   unjoinable   : {unjoined} row(s) with no recipient name")
    if a_s < 15:
        print(f"   ⚠️  n={a_s} is TOO SMALL to rank. Report it as a hint and keep sending; do not")
        print("      ratify a weight on it. The exploration allowance already samples thin bands.")
    return {"signal": name, "with": [a_r, a_s], "without": [b_r, b_s], "unjoined": unjoined}


def _compute_weights():
    """The full dated weights row: posteriors, clamped evidence ratios, founder order."""
    per, joined, log_rows, attributable = _category_evidence()
    lo, hi = PERSON_RATE_CLAMP
    # 📉 COVERAGE-SCALED SHRINKAGE. Missing data is LESS evidence, and the arithmetic has to say so.
    # Before this, the banner called every rate an upper bound while the multiplier was applied at
    # full strength regardless — honesty in the prose, confidence in the math. Widening the prior by
    # 1/coverage makes a half-joined category learn half as fast, which is what a half-observed
    # sample is worth.
    #
    # ⚠️ Bounded at 4x deliberately. Unbounded, a coverage collapse would freeze the ranker on its
    # hand-typed priors forever while still wearing a learner's badge, which is the failure mode this
    # whole mechanism exists to leave behind.
    cov = (joined / attributable) if attributable else 1.0
    cov = max(0.25, min(1.0, cov)) if attributable else 1.0
    m_eff = PERSON_PRIOR_STRENGTH / cov
    prior_mean, prior_sd = _posterior(0, 0, m=m_eff)
    prior_eff = prior_mean + PERSON_EXPLORE_KAPPA * prior_sd
    out = {}
    for cat, (s, rp) in per.items():
        mean, sd = _posterior(s, rp, m=m_eff)
        eff = mean + PERSON_EXPLORE_KAPPA * sd
        w = max(lo, min(hi, eff / prior_eff))
        out[cat] = {"sends": s, "replies": rp, "post_mean": round(mean, 4),
                    "post_sd": round(sd, 4), "w": round(w, 2)}
    # "same applies to founder": the ordering ruling is a DEFAULT the data can move.
    founder_order = "last"
    f, p = out.get("founder-exec", {}), out.get("product-leader", {})
    if f.get("sends", 0) >= 10 and f.get("post_mean", 0) > p.get("post_mean", 1):
        founder_order = "neutral"
    return {"as_of": _date.today().isoformat(), "as_of_source": "export:send-log.jsonl",
            "log_rows": log_rows, "joined": joined,
            "attributable": attributable, "coverage": round(cov, 3),
            "params": {"p0": PERSON_PRIOR_RATE, "m": PERSON_PRIOR_STRENGTH,
                       "m_effective": round(m_eff, 1),
                       "kappa": PERSON_EXPLORE_KAPPA, "clamp": list(PERSON_RATE_CLAMP),
                       "value_priors": dict(PERSON_BASE)},
            "per_category": out, "founder_order": founder_order}


def _stored_weights():
    """Newest row of the weights store, or None. Append-only + newest-wins, per state.py's rules."""
    last = None
    for line in rd(WEIGHTS_STORE).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not last or str(rec.get("as_of", "")) >= str(last.get("as_of", "")):
            last = rec
    return last


_LIVE_WEIGHTS = {}


def live_weights(stamp=True):
    """The weights the ranker actually scores with: DERIVED from the send log, on every run.

    ⛔ `stamp=False` is the READ-ONLY path (BUG-181 DoD #6, 2026-08-13). `--audit-signals` is an
    inspection mode and must not mutate the tree, but a plain call derives weights AND writes
    `documents/state/weights-derive.json` via `_stamp_derivation`. The audit still READS that file
    for its witness line — it just must not be the thing that writes it. When the process-cache is
    already warm the stamp was (or was not) written by the first caller, so this flag only governs
    the deriving call. ([[never-measure-a-tree-with-two-writers]] — the same guard main carries.)

    ⚖️ CONTINUOUS LEARNING, not read-a-stored-row. Every send in the log is already learned from by
    the time this returns; there is no command to remember and no age to go stale. The stored row is
    the AUDIT TRAIL now (see recompute_weights), not the input.

    Cached per process so ONE invocation cannot disagree with itself — the ranked list is printed,
    then re-read by --targets and by the session briefing in the same breath, and two different
    weight rows inside one run would produce two different orderings under one header. Cheap either
    way: a single pass over the send log joined against the network snapshot.

    Falls back to the stored snapshot, then to pure priors, because a briefing must never block
    (`Exit: 0 always`). A derivation that raises would otherwise take the whole session down.
    """
    if "w" not in _LIVE_WEIGHTS:
        try:
            _LIVE_WEIGHTS["w"] = _compute_weights()
            if stamp:
                _stamp_derivation(_LIVE_WEIGHTS["w"])
        except Exception:
            _LIVE_WEIGHTS["w"] = _stored_weights()
    return _LIVE_WEIGHTS["w"]


def _stamp_derivation(w):
    """Witness that a derivation RAN, with the numbers it produced.

    🔴 WHY (2026-08-11). The learner works — weights genuinely move as sends accumulate, proven by
    re-deriving against chronological truncations of the send log (senior-exec travelled
    0.98 → 1.31 → 1.28 across 50/75/100% of the log). But `documents/state/person-weights.jsonl`
    last wrote **2026-07-30 at joined=56** while live derivation stands at **joined=102**. Learning
    ran on every invocation and NOTHING durable witnessed it.

    ⚖️ That is the distinction `check_job_liveness.py` exists for, one level down: *"a job that is
    LOADED is not a job that RAN, and the two come apart silently."* Here it is *a learner that is
    WIRED is not a learner that LEARNED*. Without a stamp, "the ranker adapts" is a claim about
    code rather than a fact about this install, and the only honest answer to "is it active?" was
    a shrug ([[a-self-heal-must-verify-itself-and-never-write-its-own-input]]).

    ⛔ BEST EFFORT, NEVER FATAL. A briefing must not die because a witness file is unwritable; the
    contract on the caller is `Exit: 0 always`. A missing stamp is itself the finding, and the
    liveness check reports it.
    """
    import datetime as _dt
    path = os.path.join(REPO, "documents", "state", "weights-derive.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {"last_run": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                   "joined": (w or {}).get("joined"),
                   "log_rows": (w or {}).get("log_rows"),
                   "coverage": (w or {}).get("coverage"),
                   "founder_order": (w or {}).get("founder_order"),
                   "per_category": (w or {}).get("per_category")}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)          # atomic: a half-written witness is worse than none
    except Exception as exc:
        # ⛔ NON-FATAL BUT NEVER SILENT. The first cut was `except Exception: pass`, and it hid a
        # NameError (`datetime` is not imported in this module, only `date as _date`) so the stamp
        # never wrote and the run still reported success. A witness that fails quietly is worse
        # than no witness, because the liveness check then reports "never ran" and the operator
        # goes looking in the wrong place. Print to stderr; the caller's `Exit: 0 always` contract
        # is unaffected.
        print(f"   ⚪ weights stamp not written ({exc.__class__.__name__}: {exc})", file=sys.stderr)


def weights_reorder_note():
    """A one-line diff when the top three categories reorder against the last SNAPSHOT, else None.

    This is the mitigation for the COST of continuous learning. While weights were stale and had to
    be recomputed by hand, a reordering reached you as a visible event precisely BECAUSE of the
    pause. Deriving them every run removes the pause, so the reordering has to announce itself
    instead — otherwise the board silently reshuffles under you between two runs.
    """
    old, new = _stored_weights(), live_weights()
    if not old or not new:
        return None

    def top3(rec):
        cats = rec.get("per_category", {})
        return [c for c, _ in sorted(cats.items(), key=lambda kv: -float(kv[1].get("w", 1.0)))][:3]

    a, b = top3(old), top3(new)
    if a != b:
        return (f"  ⚖️ category order MOVED since the {old.get('as_of')} snapshot: "
                f"{' > '.join(a)}  →  {' > '.join(b)} · snapshot it with --recompute-weights")

    # ⛔ ORDER IS NOT THE ONLY THING WORTH ANNOUNCING (added 2026-08-11). Reorder-only was a PROXY:
    # weights can travel a long way without swapping rank, and this note then stays silent while
    # the audit trail rots. Measured the day this was written: the newest `person-weights.jsonl`
    # row was 2026-07-30 at joined=56 while live derivation stood at joined=102, so **46 sends of
    # evidence had accumulated with no snapshot and nothing said a word.** The scoring was current;
    # only the RECORD was stale, which is the harder failure to notice because nothing looks wrong.
    # ⚖️ Reuses WEIGHTS_STALE_AFTER, the threshold this file already defines for exactly this
    # question, rather than introducing a second number that could drift from it.
    try:
        grew = int(new.get("joined") or 0) - int(old.get("joined") or 0)
    except Exception:
        return None
    if grew >= WEIGHTS_STALE_AFTER:
        return (f"  ⚖️ {grew} more joined send(s) than the {old.get('as_of')} snapshot "
                f"({old.get('joined')} → {new.get('joined')}), order unchanged · "
                f"snapshot it with --recompute-weights")
    return None


def recompute_weights():
    """Snapshot the LIVE derivation into the append-only audit trail. Prints old→new.

    ⚖️ No longer 'the only writer of the weights the ranker reads' — the ranker derives its own (see
    live_weights). This records what the derivation SAID on a date, so a reordering can be diffed
    after the fact and so `weights_reorder_note` has a baseline to diff against.
    """
    old, new = _stored_weights(), _compute_weights()
    path = os.path.join(REPO, WEIGHTS_STORE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(new, ensure_ascii=False) + "\n")
    print(f"⚖️ person-weights recomputed {new['as_of']} — {new['joined']} of {new['log_rows']} "
          f"logged sends joined to a categorized contact")
    print(f"{'category':16} {'sends':>5} {'repl':>5} {'post-rate':>9} {'w (was)':>10}")
    for cat, d in sorted(new["per_category"].items()):
        was = (old or {}).get("per_category", {}).get(cat, {}).get("w")
        print(f"{cat:16} {d['sends']:>5} {d['replies']:>5} {d['post_mean']:>9.3f} "
              f"{d['w']:>5.2f} ({was if was is not None else '—'})")
    print(f"founder order: {new['founder_order']}"
          + (f" (was {old.get('founder_order')})" if old else " (first row)"))
    print("  Every rate is an UPPER BOUND — sends missing from the log shrink the denominator")
    print("  (scripts/reconcile_linkedin.py measures the gap). This row is the AUDIT TRAIL — the")
    print("  ranker derives its own weights every run (continuous learning).")
    return new


# ── PORTED GUARDRAILS ─────────────────────────────────────────────────────────────────────────
# ⛔ NOT ported on purpose, and the reason belongs next to the gap rather than in a commit message:
#   · `_headcount_read` / `SIZE_FLOOR` — the owner's repo keeps a company-size constant that is
#     already DEFANGED there (it prints headcount as context and moves nobody's band). The rule it
#     came from was RETIRED after "I am OK with organizations up to 50 employees" was misread as a
#     lower bound. Shipping a constant named SIZE_FLOOR without that paragraph is how a dead rule
#     comes back to life in somebody else's pipeline. Company size is not a filter here.
#   · `_is_boarded` — dead code upstream with no call sites; it existed to serve the size floor's
#     evidence override.

# How many characters the SHORTER company key must have before containment is allowed to mean "same
# employer". Guards the known collision where a short brand name swallows unrelated companies that
# merely start with the same letters.
_COKEY_MIN_CONTAIN = 8


def _cokey_joins(a, b):
    """Do two company keys, from DIFFERENT stores, describe the same employer?

    🔴 THE DEFECT THIS FIXES. The test used to be `k == cokey`, and two stores spell the same
    employer differently:

        send-log.jsonl    "Pay with Example"                 → paywithexample
        the network file  "Example - Pay with Example, Inc." → examplepaywithexampleinc

    Equality failed, so the already-emailed filter never fired, and a person emailed that very
    morning was recomputed as the #1 person to reach. `pair_brief.py` reads the same path for its
    derived default, so the sign-in card proposed them too, and the pair gate then BLOCKED any
    picker that left them out. **A bad join propagated into a gate that enforced the bad answer.**

    ⚠️ The name half cannot cover for this: a send-log row carries an ADDRESS, not a recipient name,
    so the name filter has nothing to match on. The company key is the only join.

    Containment, not equality, with two guards against short-name collisions:
      1. the SHORTER key must be at least _COKEY_MIN_CONTAIN chars, so a five letter brand never
         swallows three unrelated companies that begin the same way, and
      2. the caller still ANDs this with `_addr_fits_name`, so containment alone never marks
         somebody contacted.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= _COKEY_MIN_CONTAIN and short in long_


def _deferred_key(name):
    """Canon key for the DEFERRED lookup, degrading to a bare key if the normalizer is missing."""
    try:
        import findings_ledger
        return findings_ledger.canon(name)
    except Exception:
        return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def deferred_set():
    """company canon-key → reason, for DEFERRED rulings that still hold. {} if unreadable.

    ⚖️ FAILS OPEN, unlike blocked_set(), and the asymmetry is deliberate. An unreadable BLOCKED list
    that failed open would offer you companies you have vetoed, which is a real harm. An unreadable
    DEFERRED ledger that failed closed would hide the whole pool behind a parse error. The cost of
    failing open here is one repeated screen.
    """
    try:
        import findings_ledger
        return findings_ledger.suppressed()
    except Exception:
        return {}


def _drop_deferred(cands, skipped, supp):
    """Remove companies whose DEFERRED ruling still holds, recording each in `skipped`.

    ⚠️ Called after EVERY pool stage rather than once at the end, and that is not fussiness. The
    top-up tests below count rows, so filtering only at the end would let suppressed rows satisfy
    those counts: the pool would stop topping up at 10 and then hand back 7. A check applied to one
    source but not its siblings is a defect this pipeline has recorded several times.
    """
    if not supp:
        return cands
    kept = []
    for c in cands:
        why = supp.get(_deferred_key(c.get("company", "")))
        if why:
            skipped.append((c.get("company", ""), why))
        else:
            kept.append(c)
    return kept


def sent_companies():
    """Companies with a DELIVERED send-log row. The column `done_set()` never read.

    ⚠️ DELIVERED ONLY. **A bounce is not a contact.** The log carries drafted, staged, bounced and
    discarded rows, and counting those would suppress companies you never actually reached, which is
    a worse failure than re-offering one: a re-offer is visible and a silent suppression is not.

    Skips rows with an empty `company`, since a blank would become a set member matching nothing.
    """
    out = set()
    try:
        for line in rd(SEND_LOG).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if str(d.get("status") or "").strip().lower() not in _DELIVERED:
                continue
            co = str(d.get("company") or "").strip().lower()
            if co:
                out.add(co)
    except Exception:
        pass          # fail OPEN on a read error: a missing send log must not empty the pipeline
    return out


# Conservative on purpose. Bare "Ltd"/"AB"/"OY"/"NV" are omitted: they collide with English words
# and US brand names, and a false flag on a good target costs more than a missed flag on a bad one,
# since the screen runs either way.
_NONUS_SUFFIX = re.compile(
    r"(?<![a-z])(pte\.?\s*ltd|gmbh|pty\.?\s*ltd|sdn\.?\s*bhd|s\.a\.r\.l|sarl|s\.r\.l|"
    r"b\.v\.|a/s|aps|ltda|oyj|plc|kabushiki|co\.,?\s*ltd)(?![a-z])", re.I)


_US_COUNTRY_NAMES = {"us", "usa", "u.s.", "u.s.a.", "united states", "united states of america"}


def nonus_tell(company):
    """The best non-US location signal available for `company`, or '' when there is none.

    BUG-001 FIX. A RESOLVED country (from resolve_employers.py's employer cache, populated by real
    research) is checked FIRST and, when present, is authoritative — captured at resolution time,
    since the export never carries a country and the only place one can be captured honestly is the
    same out-of-band research pass that already resolves segment/industry. Falls back to the
    legal-form-suffix guess ONLY when no resolution exists, exactly as before: additive, so an
    unresolved company degrades to prior behavior and cannot regress.

    ⚠️ Still a SURFACE, never a veto, in both branches.
    """
    if company:
        try:
            row = contact_signals.load_employer_cache().get(
                contact_signals._employer_key(company))
        except Exception:
            row = None
        if row:
            country = str(row.get("country") or "").strip()
            if country and country.lower() not in _US_COUNTRY_NAMES:
                return country
    m = _NONUS_SUFFIX.search(company or "")
    return m.group(1) if m else ""


# ── PROFILE VIEWS — a SURFACE, not a scored term (BUG-181 WU-4, 2026-08-13) ─────────────────────
# The LinkedIn connections export carries no viewers; the "Who viewed your profile" page does, and
# `scripts/parse_views.py` ingests it into this store. The ranker reads it here and prints a reason
# line on a matching row — it NEVER enters `pts`, the same posture `nonus_tell` takes, until it
# clears its own outcome join at n≥15. Manual-entry data goes stale silently, so the board also
# prints the store's age. Degrades to {} when the store is absent (the default partner install).
PROFILE_VIEWS = os.path.join(REPO, "documents", "state", "profile-views.jsonl")


def load_profile_views(path=None):
    """{norm(name): newest_view_row}. {} when the store is absent, so every effect below degrades
    to today's behavior rather than failing."""
    path = path or PROFILE_VIEWS
    out = {}
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
                name = row.get("name")
                if not name:
                    continue
                key = re.sub(r"[^a-z0-9]", "", name.lower())
                prev = out.get(key)
                if prev is None or (str(row.get("view_date", "")), str(row.get("ingested_on", ""))) \
                        >= (str(prev.get("view_date", "")), str(prev.get("ingested_on", ""))):
                    out[key] = row
    except OSError:
        return {}
    return out


def _profile_views_age_line(views):
    """One line naming the store's freshness, or '' when nothing is captured."""
    if not views:
        return ""
    latest = max((str(r.get("view_date", "")) for r in views.values()), default="")
    line = f"  👀 profile-views: {len(views)} viewer(s) on file"
    if latest:
        try:
            days = (_date.today() - _date(*(int(x) for x in latest.split("-")))).days
            line += f" · latest {latest} ({days}d old)"
        except (ValueError, TypeError):
            line += f" · latest {latest}"
    return line + " — a SURFACE, not scored (needs n≥15 to validate)"


_H2N_CACHE = None


def _handle_to_name():
    """Map a LinkedIn slug to the contact's real name, read from the state store.

    `documents/state/contact.jsonl` is written by `parse_network.py` and carries both `linkedin`
    and `name` in its payload, so a slug that no pattern can unpack ("janedoe") still resolves by
    lookup. Cached because `contacted_people()` runs inside a ranking loop.

    Later rows win, matching the append-only last-write-wins rule the other stores follow. Returns
    an empty dict on any failure, so a missing store degrades the caller rather than breaking it.
    """
    global _H2N_CACHE
    if _H2N_CACHE is not None:
        return _H2N_CACHE
    out = {}
    try:
        for line in rd("documents/state/contact.jsonl").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                p = (json.loads(line) or {}).get("payload") or {}
            except ValueError:
                continue
            m = re.search(r"linkedin\.com/in/([^/?\s]+)", str(p.get("linkedin") or ""))
            if m and p.get("name"):
                out[m.group(1).lower().rstrip("/")] = p["name"]
    except Exception:
        pass
    _H2N_CACHE = out
    return out


def contacted_people():
    """Person NAMES already contacted, so a fresh pick does not re-surface them.

    POSITION-INDEPENDENT. Real SENT headers do not agree on which '·' field holds the person:
        ## 2026-01-15 · Jordan Lee · Product Manager, Example Co — ✅ SENT     (name is the 2nd field)
        ## 2026-01-15 · Robin Alvarez (AI PM, Example Co) — ✅ SENT [LinkedIn] (name is the 2nd field)
        ## 2026-01-15 · Example Co · jordan@example.com — ✅ SENT              (company is 2nd)
    A fixed-position parser will re-offer a person minutes after they were messaged — the same harm
    as re-offering a burned company: it wastes attention and risks a duplicate approach that reads
    as careless.

    So: scan EVERY '·' field of a SENT header and keep any that looks like a personal name. A company
    or an address is not two capitalised words, so this does not over-match.

    🔴 THREE SOURCES, AND IT USED TO READ ONE. `outreach_log.md` is the hand-kept prose log, so this
    function only knew about a contact if a SENT header had been written for them. It did not read
    the structured send log the ladder is computed from, and it did not read the closeness store's
    OUTBOUND MESSAGE COUNTS.

    Measured on a live pool: the majority of the people on the board had already been written to, and
    this function was excluding a small fraction of them. The case that surfaced it was a contact
    with more than a dozen outbound messages on file, offered as a fresh target — and the reaction
    was the obvious one, that all of these people had already been contacted. It is a recurring class
    (a bench count that does not filter on status) and the shape is the same every time: one pool
    reads a LIVE source, another reads a STALE snapshot, and the two disagree where nobody looks.

    ⚖️ `he_sent > 0` IS THE BAR, not "recently contacted". This set answers exactly one question — may
    this person be offered as a NEW INITIAL CONTACT — and someone you have already written to is not
    a new initial contact whatever the date. Re-engaging an old thread is a DIFFERENT move with a
    different shape (the reunion rung), and it must not arrive disguised as a fresh pick.
    """
    names = set()
    NAME = re.compile(r"^([A-Z][\w.'\-]+(?:\s+[A-Z][\w.'\-]+){1,3})$")
    for line in rd("outreach_log.md").splitlines():
        if not (line.startswith("## ") and re.search(r"\bsent\b", line, re.I)):
            continue
        head = re.split(r"—|\[", line)[0]          # drop the trailing status/channel tail
        for chunk in head.lstrip("# ").split("·"):
            chunk = re.sub(r"\(.*?\)", " ", chunk).strip().strip(",")
            m = NAME.match(chunk)
            if not m:
                continue
            nm = re.sub(r"[^a-z0-9]", "", m.group(1).lower())
            if len(nm) >= 4:
                names.add(nm)
    # (2) the structured send log — the same rows rung_ladder.py counts.
    try:
        for line in rd(SEND_LOG).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            # Writer-side half: rows written by the current logger carry the resolved NAME, so
            # the handle join below is a fallback for older rows rather than the only path.
            for variant in (d.get("to_name"),
                            closeness.normalize_name(d.get("to_name") or "") if closeness else ""):
                tn = re.sub(r"[^a-z0-9]", "", str(variant or "").lower())
                if len(tn) >= 4:
                    names.add(tn)
            # ⛔ BOTH `to` SPELLINGS, because the writer emits both (found upstream 2026-08-10).
            # This read only `linkedin.com/in/<slug>`, while `log_linkedin_send.py --to` accepts and
            # DOCUMENTS the short form `linkedin:<handle>` in its own help text. Measured on the
            # upstream log: **76 of 393 rows (19% of every send ever made)** used the short form with
            # no `to_name` and were invisible here, including four replies to live threads. A
            # contacted person this set cannot see is offered again as a NEW initial contact, which
            # is the single thing it exists to prevent.
            _to = str(d.get("to") or "")
            m = (re.search(r"linkedin\.com/in/([^/?\s]+)", _to)
                 or re.search(r"^linkedin:([^/?\s]+)$", _to.strip(), re.I))
            if m:
                slug = m.group(1).lower()
                nm = re.sub(r"[^a-z0-9]", "", slug)
                if len(nm) >= 4:
                    names.add(nm)
                # 🔴 LINKEDIN'S DISAMBIGUATOR BREAKS THE JOIN THE SAME WAY A MIDDLE INITIAL DOES.
                # A taken handle gets a hash appended: `avery-garner-b967b429` keys as
                # `averygarnerb967b429`, which never equals the pool's `averygarner`. Strip a
                # trailing segment ONLY when it mixes letters AND digits, which is the hash's shape
                # and not a surname's, so `mary-jane-smith` and `jennifer-dennis-brown` stay whole.
                _parts = slug.split("-")
                if len(_parts) > 2:
                    _tail = _parts[-1]
                    if (len(_tail) >= 4 and any(c.isdigit() for c in _tail)
                            and any(c.isalpha() for c in _tail)):
                        _base = re.sub(r"[^a-z0-9]", "", "".join(_parts[:-1]))
                        if len(_base) >= 4:
                            names.add(_base)
                # 🔴 A MIDDLE INITIAL IN THE SLUG BREAKS THE JOIN. A profile at
                # `/in/jane-a-doe` keys as `janeadoe`, while the contact pool knows the person
                # as "Jane Doe" and keys as `janedoe`. The two never match, so the
                # already-contacted test cannot see the send, and the ranker offers that person
                # again as a fresh target MINUTES after they were messaged.
                # A credential suffix (`-mba`, `-phd`) survives this because the name normalizer
                # strips credentials. A middle initial is not a credential, so nothing strips it.
                # ⚖️ Defect family: one side of a join carries a token the other side never had.
                # Register the initial-stripped spelling in ADDITION to the literal one, so a
                # genuine single-letter name keeps its own key too.
                parts = [p for p in re.split(r"[^a-z0-9]+", slug) if p]
                trimmed = re.sub(r"[^a-z0-9]", "", "".join(p for p in parts if len(p) > 1))
                if len(trimmed) >= 4 and trimmed != nm:
                    names.add(trimmed)
                # 🔴 A SLUG THAT COMPRESSES THE FIRST NAME TO A BARE INITIAL CAN NEVER BE SPLIT
                # BACK INTO THE POOL'S KEY. A profile at `/in/janedoe` keys as `janedoe`, while the pool
                # knows the person as "Jane Doe" and keys as `janedoe`. The middle-initial
                # repair above cannot help: it works by DROPPING one-letter parts, and here the
                # initial is FUSED to the surname with no separator, so there is nothing to split.
                # In a mature log almost every LinkedIn send row carries no personal name at all,
                # in the row or in the narrative header.
                # The harm is worse than a re-offer. A contact can rank #1 before the send and #1
                # again AFTER it, at a HIGHER score, while every other name drifts down. A
                # first-ever LinkedIn contact is the exact case that slips through, because the
                # closeness store's `he_sent` count in source (3) comes from a periodic EXPORT and
                # stays 0 until the next export is parsed. Initial contacts are the whole job.
                # ⚖️ THE FIX RESOLVES THE HANDLE INSTEAD OF GUESSING AT ITS MORPHOLOGY. Slug shapes
                # are unbounded (`janedoe`, `jane-a-doe`, `janedoemba`) and every repair by
                # pattern has failed once already. The contact store already holds the LinkedIn URL
                # beside the real name, so the join is a LOOKUP. Add the resolved name in addition
                # to the slug keys, so a cold target absent from that store still registers.
                real = _handle_to_name().get(slug.rstrip("/"))
                if real:
                    for variant in (real, closeness.normalize_name(real) if closeness else ""):
                        rn = re.sub(r"[^a-z0-9]", "", str(variant or "").lower())
                        if len(rn) >= 4:
                            names.add(rn)
    except Exception:
        pass                                        # degrade to the other sources, never fail
    # (3) the closeness store's own message counts — the source that caught the other two out.
    try:
        st = closeness.load() if closeness else {}
        for disp, row in (st or {}).items():
            if disp.startswith("_") or not isinstance(row, dict):
                continue
            if (row.get("messages") or {}).get("he_sent"):
                raw = str(row.get("display_name") or disp)
                # BOTH forms, because the two sides spell the same person differently: the network
                # snapshot carries the export's display name WITH credentials ("Jane Doe, MBA") and
                # the store key usually drops them. Keying on one form alone let credentialed names
                # straight through the filter on the first run of this fix.
                for variant in (raw, closeness.normalize_name(raw)):
                    nm = re.sub(r"[^a-z0-9]", "", str(variant).lower())
                    if len(nm) >= 4:
                        names.add(nm)
    except Exception:
        pass
    return names


# Send-log statuses that mean the message REACHED the person. A bounce did NOT reach them, so it must
# not exclude them from the pool — that is exactly the case where a corrected retry is the right move.
_DELIVERED = {"sent", "delivered", "replied", "submitted"}

# ⛔ THE PATH IS REPO-RELATIVE, AND WRITING IT AS A BARE FILENAME IS A SILENT NO-OP. rd() joins against
# the REPO ROOT, so `rd("send-log.jsonl")` returns "" on every call and the send-log branch of
# contacted_people() never once executes its loop body. Upstream that bug sat unnoticed through the
# very measurement that was used to justify the three-source fix: the docstring said it read three
# sources, it read two, confidently. A store read through a wrong path fails silently and looks
# exactly like a store with nothing in it.
SEND_LOG = "documents/send-log.jsonl"


def contacted_addresses():
    """{(company_key, address_local_part)} for every DELIVERED send-log row. Empty on any failure.

    🔴 THE HOLE contacted_people() STILL HAD. That function reads the send log, but it only recovers
    a NAME from a `linkedin.com/in/<slug>` address. An EMAIL send yields nothing: a first-name-only
    local part at a company domain cannot be turned back into the key `janedoe`, so the person it
    reached stays eligible and gets offered again as a fresh initial contact.

    The receipt upstream: two of the top three ranked people had each received a cold-boss EMAIL the
    previous day, and both were offered as fresh contacts the next morning. The prose logs did not
    save it either — both still read "staged, awaiting send" while the send log said `sent`, the same
    one-pool-reads-live, one-reads-stale split every prior occurrence had.

    ⚖️ COMPANY MATCH ALONE IS NOT THE BAR. Emailing one boss at a company does not burn every person
    there, and a filter that broad would quietly delete reachable people from the pool. The test is
    company AND an address COMPATIBLE WITH THIS PERSON'S NAME, which is precise enough to catch both
    `jane@` and `jdoe@` without touching a colleague of theirs.
    """
    out = set()
    try:
        for line in rd(SEND_LOG).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if str(d.get("status") or "").strip().lower() not in _DELIVERED:
                continue
            to = str(d.get("to") or "")
            co = str(d.get("company") or "")
            if "@" not in to or not co.strip():
                continue
            local = re.sub(r"[^a-z0-9]", "", to.split("@", 1)[0].lower())
            key = re.sub(r"[^a-z0-9]", "", co.lower())
            if local and key:
                out.add((key, local))
    except Exception:
        pass                                        # degrade to the other filters, never fail
    return out


def _addr_fits_name(local, name):
    """Is `local` (an email local part) plausibly THIS person's address?

    Covers the shapes a company actually issues: first, last, firstlast, first.last (dots already
    stripped by the caller), and initial+last. Deliberately NOT a substring test — a short first name
    inside an unrelated word is the kind of loose match that produces a FALSE BLOCK, and a false
    block silently removes a real candidate from the board, which is the harm this module keeps
    re-learning from the other direction.
    """
    parts = [re.sub(r"[^a-z0-9]", "", p.lower()) for p in str(name).split()]
    parts = [p for p in parts if len(p) >= 2]
    if not parts or not local:
        return False
    first, last = parts[0], parts[-1]
    cands = {first, last, first + last, last + first}
    if first and last:
        cands.add(first[0] + last)
        cands.add(last + first[0])
    return local in cands


def _people_rows():
    """Parse the Product / Senior / Connector tables of warm-network.md.

    Returns (name, title, company, flag, known_since).

    Anchored from the RIGHT because a LinkedIn title can itself contain pipes
    ('Product Manager | AI & Cloud Platforms'). The row shape is six columns plus the artifact of
    the closing pipe:

        ['', '39', 'Jane Doe', 'Director…', 'SomeCo Inc.', '🟡 1y (2025-03-07)', '✉', '']
          0    1          2              3            -4              -3            -2   -1

    🔴 OFF-BY-ONE FIXED. This read `company=cells[-3]` and `title=cells[3:-3]`, which
    predates the `Known since` column. The writer grew a column and the reader never learned, so for
    **every row in the table** `company` received the date badge and the real employer was mashed
    into `title`. The daily briefing rendered an employer slot showing a date, and it read as
    cosmetic noise rather than a parse failure.

    ⚠️ `flag` at cells[-2] was always CORRECT and must stay there. It is the real unnamed sixth
    column carrying `✉` plus the blocked/contacted status, empty for most rows only because most
    contacts have neither. Widening it to swallow `Known since` would newly skip every search-era
    contact as "blocked co", which is the opposite of the intent.

    Why no test caught it: the fixture in tests/test_rank_criteria.py was a FIVE-column table from
    before `Known since` existed, so the old indices were correct for the fixture and wrong for
    production. The layout is now asserted against parse_network.PEOPLE_TABLE_HEADER.
    """
    try:
        from parse_network import PEOPLE_TABLE_HEADER
        expected_cols = PEOPLE_TABLE_HEADER.count("|") - 1
    except Exception:
        expected_cols = 6            # the known-good shape; never widen this silently

    rows, in_pool, checked = [], False, False
    for line in rd("documents/warm-network.md").splitlines():
        if line.startswith("## "):
            # "Senior ICs" is the fourth pool section (BUG-181 WU-6a); identical header contract.
            in_pool = any(k in line for k in ("Product people", "Senior decision", "Connectors",
                                              "Senior ICs"))
            checked = False
            continue
        if not in_pool or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        # HEADER ASSERTION. The first table line in each pool section must have the column count the
        # writer promises. A mismatch means the contract drifted again; refuse that section rather
        # than mis-index it, because mis-indexing is what corrupted an entire table for months.
        if not checked and not cells[1].isdigit():
            checked = True
            if len(cells) - 2 != expected_cols:
                print(f"⚠️  warm-network people table has {len(cells) - 2} columns, expected "
                      f"{expected_cols} — layout drifted; skipping this section", file=sys.stderr)
                in_pool = False
            continue
        if len(cells) < 8 or not cells[1].isdigit():   # skip separator / continuation rows
            continue
        name, flag, known_since, company = cells[2], cells[-2], cells[-3], cells[-4]
        title = " | ".join(cells[3:-4]).strip()
        # KEY ON NAME ALONE. The old guard was `if name and company`, which was harmless only
        # because `company` then held the always-populated date badge. With the columns read
        # correctly, a contact whose LinkedIn profile lists no employer has a genuinely EMPTY
        # company cell, and requiring it silently dropped them, caught while verifying this very
        # fix. A contact with no listed employer is still a contact, and
        # a parser that quietly loses people is the defect this whole pass exists to remove.
        if name:
            rows.append((name, title, company, flag, known_since))
    return rows


def rank_people(n=10):
    contacted = contacted_people()
    contacted_addrs = contacted_addresses()
    shapes = _company_shape_map()
    # THE STATED RELATIONSHIP, which this ranker was blind to before the closeness store existed.
    # Every answer you have already given about who you actually know sits in that store, read by
    # the message parser and the freshness check and by NO ranker — so the score used the connect
    # DATE as a proxy for closeness and badged a stated "know but not close" acquaintance as a
    # "likely boss", which downstream reads as the "would you have a seat for me" ask. You told the
    # pipeline and it recommended the one ask you had ruled out.
    #
    # `None` when the store is absent (a fresh install that has not run the levelling interview),
    # which is NOT the same as empty: every closeness effect below degrades to the previous
    # behaviour rather than failing.
    close = closeness.load() if closeness else None
    # ⚖️ DERIVED, not read. Every send in the log is already learned from by the time this line runs;
    # there is no command to remember and no age to go stale. The stored row is the audit trail —
    # see live_weights / recompute_weights.
    W = live_weights()
    # The LIVE blocked list, the same object the company pool filters against.
    blocked = blocked_set()
    worder = (W or {}).get("founder_order", "last")
    wcat = (W or {}).get("per_category", {})
    _cl_lifts = closeness_tier_lift()      # WU-3: learned closeness-tier lift, derived once per run
    # WU-4: the captured "Who viewed your profile" store, read ONCE per run. A surface only — a
    # reason line on a matching row, never `pts`. {} when the store is absent (default install).
    _views = load_profile_views()
    out, skipped = [], []
    for name, title, company, flag, known_since in _people_rows():
        combo = company + " " + title
        # ── deal-breaker filter ONLY (no culture/WLB) ──
        if "🔴" in flag:
            skipped.append((name, "blocked co")); continue
        # 🔴 THE BADGE TEST ABOVE IS NOT A BLOCKED-LIST CHECK. `flag` is a PRE-COMPUTED badge baked
        # into the warm-network.md snapshot, so any company blocked AFTER that snapshot was generated
        # stays invisible to it. The COMPANY pool has always tested `low in blocked_set()`, which
        # parses the list LIVE. The two pools disagreeing is the whole bug — upstream, a run put
        # eight of its top ten recommended people at companies blocked the day after the snapshot,
        # under a header that read "blocked-co / deal-breaker / already-contacted excluded".
        #
        # ⛔ Do NOT "fix" this by regenerating warm-network.md. That refreshes the badge for one day
        # and makes it look trustworthy again, while the ranker stays one snapshot behind forever.
        # The badge stays only because it ALSO carries states the live list cannot know.
        if company and company.lower() in blocked:
            skipped.append((name, "blocked co (live list)")); continue
        # EXCLUDED former-employer LEADERSHIP tier (peers stay in scope). No-op unless
        # EXCLUDED_EMPLOYERS is set in kit_config. Reported in `skipped` for auditability.
        if EXCLUDED_EMPLOYER_RE and EXCLUDED_EMPLOYER_RE.search(combo) and SENIOR.search(title + " " + name):
            skipped.append((name, "excluded former-employer leadership tier")); continue
        _v = _industry_vetoed(combo)
        if _v:
            skipped.append((name, f"veto industry ({', '.join(_v)})")); continue
        # Test BOTH spellings for the same reason contacted_people() stores both: the pool name
        # carries credentials the store key drops.
        if any(re.sub(r"[^a-z0-9]", "", str(v).lower()) in contacted
               for v in (name, closeness.normalize_name(name) if closeness else name)):
            skipped.append((name, "already contacted"))
            continue                                   # already reached this person
        # The EMAIL half of the same question. The name-key test above cannot see an email send,
        # because an address does not spell a full name. See contacted_addresses().
        _cokey = re.sub(r"[^a-z0-9]", "", str(company).lower())
        # Containment rather than equality, because the two stores spell an employer
        # differently and the equality test silently never fired. See _cokey_joins.
        if _cokey and any(_cokey_joins(k, _cokey) and _addr_fits_name(loc, name)
                          for k, loc in contacted_addrs):
            skipped.append((name, "already emailed (send log)"))
            continue
        # HANDLING STATE OVERRIDES CLOSENESS, and it is checked BEFORE scoring so a held contact can
        # never be surfaced, however warm or senior. The store says it itself: knowing someone is
        # never permission to contact them.
        #
        # ⛔ Without this, a hold is only as strong as whoever remembers it. A note in a memory file
        # is not a gate, and held contacts usually carry STRONG tiers — so they would be surfaced
        # WITH the closeness bonus, promoted by the very feature meant to respect the relationship.
        crow = closeness.tier_for(name, close) if closeness else None
        _held = closeness.is_held(crow) if closeness else None
        if _held:
            skipped.append((name, f"HELD — {_held}")); continue
        # 🕰 VERIFY-BEFORE-SURFACE (BUG-181 WU-5). The export freezes a title at the CONNECT date, so
        # a `changed` verdict recorded by `/verify-titles` (via record_role.py) had no effect on the
        # ASK the ranker produced — because classification still ran off the stale title. This is the
        # READ path: a still-current verified role with a DIFFERENT title drives `_person_category`
        # and `segment_read`, which can MOVE the person's category. Still NOT scored (a re-cat, not a
        # penalty). Degrades to the export title with no store, an ENDED role, or a matching title.
        _class_title = title
        _recat = ""
        if contact_signals:
            _vrole = contact_signals.verified_role(name)
            if _vrole and _vrole.get("still_there") is not False and _vrole.get("title") \
                    and re.sub(r"[^a-z0-9]", "", _vrole["title"].lower()) \
                    != re.sub(r"[^a-z0-9]", "", (title or "").lower()):
                _class_title = _vrole["title"]
                _recat = (f"🕰 re-categorized on verified title \"{_vrole['title']}\" "
                          f"(was \"{title}\", verified {_vrole.get('verified_on', '?')})")
        cat = _person_category(_class_title, company)
        # ── SEGMENT READ, TRI-STATE, and only a POSITIVE off-segment match may demote ─────────
        # "unknown" KEEPS the band, because most real companies do not carry their industry in
        # their name. Demoting on "no match" would push a Head of Product at a major payments
        # company down exactly as far as an artist-management sole trader.
        _segstate, _segdetail = ("unknown", None)
        _evtier = 1
        _evsrc = None
        if contact_signals:
            _segstate, _segdetail = contact_signals.segment_read(company, _class_title)
            # 🔬 EVIDENCE TIER — the PRIMARY sort key. Never touches `pts` and never rebands, so
            # every scoring term keeps its meaning; it only decides which rows may sit ABOVE which.
            _evtier, _evsrc = contact_signals.employer_evidence(company)
        _reband = None
        if cat in ("product-leader", "founder-exec") and _segstate == "off":
            _reband = cat
            cat = "connector"
        shape = shapes.get(company.strip().lower())
        pts = float(PERSON_BASE[cat])
        reasons = [PERSON_BADGE[cat]]
        if _recat:
            reasons.append(_recat)
        if _reband:
            reasons.append(f"↩ off-segment employer (\"{_segdetail}\"), so {_reband} → connector "
                           f"(ask who they know, never hire-me)")
        elif _segstate == "relevant":
            reasons.append(f"🎯 {_segdetail} employer")
        # Ruling B (the owner's ruling): when only a founder can be found among several plausible
        # bosses, the founder is the last choice rather than the first. Among equal-scored plausible
        # bosses the exec sorts LAST — a sort TIEBREAK, never a deduction. When the board says the
        # company is founder-led there is no seated product leader to prefer, so the tiebreak
        # clears: the founder is the first-class answer (Ruling A), not a fallback.
        # Ruling B is a DEFAULT the evidence can move ("same applies to founder") — the stored
        # founder_order flips to neutral when founder replies overtake product leaders'.
        founder_last = 1 if (cat == "founder-exec" and worder == "last") else 0
        if cat == "founder-exec" and shape == "founder-led":
            founder_last = 0
            reasons.append("🌾 founder-led per the green board — the founder IS the likely boss")
        elif cat == "founder-exec" and shape == "product-led":
            pts = float(PERSON_EXEC_AT_PRODUCT_LED)
            reasons.append("board shows a seated product leader — likely a REFERRER, not the boss")
        # Learned propensity: the clamped evidence ratio for this CATEGORY, from the dated weights
        # row. Applied after the shape decision so the multiplier scales whatever base the
        # likely-boss read produced. w == 1.0 (no row / no evidence) changes nothing.
        _wd = wcat.get(cat, {})
        w = float(_wd.get("w", 1.0))
        if w != 1.0:
            pts = round(pts * w, 1)
            reasons.append(f"reply-evidence ×{w:g} "
                           f"({_wd.get('replies', 0)}/{_wd.get('sends', 0)} joined sends)")
        # Applied AFTER the multiplier, never THROUGH it: the allowance is a flat loan against the
        # band's score so it can be sampled, and multiplying it by a rate the band has not earned yet
        # would compound a guess with a guess. See explore_allowance.
        _xa, _xreason = explore_allowance(cat, wcat)
        if _xa:
            pts = round(pts + _xa, 1)
            reasons.append(_xreason)
        if "✉" in flag:
            pts += PERSON_EMAIL_BONUS; reasons.append("email on file")
        reentry = "🟡" in flag
        if reentry:
            pts += PERSON_REENTRY_BONUS; reasons.append("warm re-entry (company already in pipeline)")

        # RELATIONSHIP DISTANCE, carried into the score and CONTINUOUS since v2.
        # The banded form (-2 search-era / +1 under 3y / +3 at 3y+) collapsed every 3y+ contact onto
        # one value, which is how a real run tied a whole bloc of product leaders at one score and
        # the "top 10" became the first 10 file rows of a category. The exact connect date is already in the Known-since
        # cell, so read it and let the ladder's own axis — distance — spread the band. Falls back to
        # the integer "Ny" badge when a row predates the dated format, so an older warm-network.md
        # still ranks rather than flattening to the base score.
        #
        # Keyed on the TEXT, never the emoji. The same three badges mean different things in
        # different tables of this file, so matching 🔴 here would conflate "connected during the
        # search" with "company on the blocked list".
        #
        # ── THE STATED RELATIONSHIP OUTRANKS THE DATE PROXY ─────────────────────────────────────
        # The rung, the sanctioned ask, and — where YOU have stated a relationship — the relationship
        # term itself. Calibration: strong +6, thin +3, and an `inferred-from-messages` strong tier
        # scores THIN until you confirm the person.
        #
        # Why the stated bonus REPLACES the date term rather than adding to it at full slope: a
        # connect date is a platform artifact, not a measure of closeness. The store's own README is
        # blunt about it — dates identify STRANGERS reliably but CANNOT identify RELATIONSHIPS. A
        # decades-old school friendship with a recent connect date reads as a weak tie to the proxy.
        # Where you have stated the truth, the proxy must not dilute it.
        rung = band = ask = None
        cbonus, cflag = 0, None
        if closeness:
            rung, band, ask, cbonus, cflag = closeness.rung_for(crow, cat)
        # 🪜 WU-2: the closeness BAND (2/1/0) that leads the sort. Provenance-respecting and
        # None-safe — with no closeness store it is 0 for every row, degrading to today's ordering.
        close_band = _close_band(crow, cat)
        # 🌡️ THREAD DEPTH — the second axis. Closeness says how STRONG the tie is; this says whether
        # it is LIVE. A live thread is a warmer starting point than a cold one at the SAME closeness,
        # and the term is small on purpose so strength keeps dominating temperature.
        # 🌡️ THREAD DEPTH is a CONTEXT line, not a scored term (WU-3): thread_state reads TODAY's
        # thread, so "live" MEANS "they replied" — scoring it joins the reply outcome to itself
        # (leakage), and there is no dated snapshot to read it as-of-send. `thread_depth_points`
        # scores nothing; the state survives only as a note that changes the ASK.
        if closeness:
            _tstate, _tlast = closeness.thread_state(crow)
            _tb, _ = thread_depth_points()
            if _tb:
                pts = round(pts + _tb, 1)             # unreachable today; kept for a future dated snapshot
            if _tstate in ("live", "cooling", "dead"):
                reasons.append(f"thread {_tstate}"
                               + (f" (last reply {_tlast}, context only)" if _tlast
                                  else " (context only)"))
        dist, yrs = "unknown", 0.0
        m_date = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", known_since)
        if cbonus:
            pts = round(pts + cbonus, 1)
            tier = (crow or {}).get("closeness", "?")
            reasons.append(f"{tier} (+{cbonus:g})")
            # 📊 WU-3 LEARNED closeness-tier term, on top of the ratified flat bonus. Scores nothing
            # when the band's cell is under n≥15 (then the ratified bonus stands alone). Orders only
            # WITHIN a band — the sort leads on close_band.
            _clp, _clr = closeness_tier_points(close_band, _cl_lifts)
            if _clp:
                pts = round(pts + _clp, 1)
            if _clr:
                reasons.append(_clr)
            dist = "stated"
            if m_date:
                y, mo, dd = (int(x) for x in m_date.groups())
                try:
                    yrs = max((_date.today() - _date(y, mo, dd)).days / 365.25, 0.0)
                except ValueError:
                    yrs = 0.0
            # 📐 THE YEARS TERM IS ADDITIVE HERE, AT A REDUCED SLOPE. Dropping it entirely (the
            # earlier design) reintroduced a TIE CEILING: with the continuous term gone, every
            # stated-tier contact in a category landed on one of a handful of discrete values and the
            # whole top of the board shared a single score — the same ceiling the continuous distance
            # term was written to end, simply undone for the rows that now top the board. Reduced
            # slope, not the full one, and capped well under the closeness bonus: where you have
            # STATED the tie, the proxy may separate equals but must not dilute your statement.
            if yrs:
                _sb = round(min(yrs * PERSON_STATED_PER_YEAR, PERSON_STATED_CAP), 1)
                pts = round(pts + _sb, 1)
                reasons.append(f"known {yrs:.1f}y (+{_sb:g})")
        elif re.search(r"search-era", known_since, re.I):
            dist = "search-era"; pts += PERSON_SEARCH_ERA
            reasons.append("connected during the search — common-interest rung, NOT a warm rung")
        elif m_date or re.search(r"\b(\d+)y\b", known_since):
            if m_date:
                y, mo, dd = (int(x) for x in m_date.groups())
                try:
                    yrs = max((_date.today() - _date(y, mo, dd)).days / 365.25, 0.0)
                except ValueError:
                    yrs = float(re.search(r"\b(\d+)y\b", known_since).group(1)) \
                        if re.search(r"\b(\d+)y\b", known_since) else 0.0
            else:
                yrs = float(re.search(r"\b(\d+)y\b", known_since).group(1))
            bonus = round(min(yrs * PERSON_DISTANCE_PER_YEAR, PERSON_DISTANCE_CAP), 1)
            pts = round(pts + bonus, 1)
            dist = "3y+" if yrs >= 3 else "under-3y"
            reasons.append(f"known {yrs:.1f}y (+{bonus:g})")

        if cflag:
            reasons.append(f"⚠️ {cflag}")
        # 👀 PROFILE VIEW (WU-4). A surface, not a scored term: printed where the human decides,
        # never added to `pts`, until it clears its own n≥15 outcome join.
        _vrow = _views.get(re.sub(r"[^a-z0-9]", "", name.lower())) if _views else None
        _viewed = bool(_vrow)
        if _vrow:
            _vd = _vrow.get("view_date")
            reasons.append(f"👀 viewed your profile{f' {_vd}' if _vd else ''} "
                           f"(surface only, not scored)")
        if contact_signals:
            if _evtier == contact_signals.EV_NOT_FOUND:
                reasons.append(f"⚪ searched and NOT placeable ({_evsrc}) — sorts below every "
                               f"resolved employer, and below one nobody has looked at yet")
            elif _evtier == contact_signals.EV_LOW_CONF:
                reasons.append(f"🟡 employer resolved at LOW confidence ({_evsrc})")
            elif _evtier == contact_signals.EV_RESOLVED:
                reasons.append(f"🔬 employer resolved ({_evsrc})")
        out.append({"name": name, "title": title[:46], "company": company, "cat": cat,
                    "viewed": _viewed,
                    # ⚠️ `evtier`, NOT `tier` — the `tier` key below is CLOSENESS. Reusing the
                    # name would silently overwrite it.
                    "evtier": _evtier,
                    "pts": round(pts, 1), "reasons": reasons, "distance": dist,
                    "known_since": known_since, "founder_last": founder_last, "yrs": yrs,
                    # The ask travels WITH the row. One blended pool of the whole network is only
                    # defensible because closeness drives the ask SHAPE — so if the rung lives only
                    # in the reader's head that basis is unenforceable, and unenforceable is how a
                    # warm-shaped ask reaches a stranger at scale.
                    "rung": rung, "band": band, "ask": ask, "close_band": close_band,
                    "tier": (crow or {}).get("closeness"), "close_flag": cflag})
    # Sort: score desc → Ruling B tiebreak (exec/founder LAST among equals, never a deduction) →
    # longer-known first → name, so the order is TOTAL and two runs cannot disagree. The old key
    # sorted on score alone and leaned on Python's stable sort, which silently made file order the
    # real tiebreak.
    # ── THE EVIDENCE TIER LEADS THE SORT ───────────────────────────────────────────────────
    # Sort: evidence tier desc → score desc → founder-last tiebreak → longer-known → name, so the
    # order is total and two runs cannot disagree.
    #
    # WHY A FLOOR AND NOT A PENALTY. The first attempt at this was a multiplier on the score of an
    # unverified employer. It failed twice over: a uniform constant cannot break a tie among rows
    # that are otherwise identical, and it was applied AFTER the learned category multiplier, so an
    # unverified founder computed a HIGHER score than its own un-multiplied base. The penalty for
    # being unidentifiable read as a promotion, and the same unplaceable company sat at #1 for days.
    #
    # A floor is not tunable and cannot be out-multiplied by any weight the learner later finds.
    # Points still order rows WITHIN a tier, so nothing else loses its meaning.
    # 🪜 CLOSENESS LEADS, THEN EVIDENCE TIER (BUG-181 WU-2). The stated-closeness band sorts ABOVE
    # evtier, so a warm contact outranks a never-spoke senior exec whatever their employer evidence.
    # Within a band the evtier ruling still holds — resolved employers outrank unplaceable ones among
    # closeness-equals. With no closeness store every band is 0, so the ordering is unchanged.
    out.sort(key=lambda c: (-CLOSE_BAND_LEADS * c["close_band"], -c["evtier"], -c["pts"],
                            c["founder_last"], -c["yrs"], c["name"].lower()))
    return _with_exposure_floor(out, n), skipped


def _recent_sends_by_category(days=EXPOSURE_WINDOW_DAYS):
    """{category: delivered sends in the trailing window}, from the send log × the roster."""
    per = {c: 0 for c in PERSON_BASE}
    try:
        from rung_ladder import load as _load_sends, NOT_DELIVERED
        from datetime import timedelta as _td
        cutoff = (_date.today() - _td(days=days)).isoformat()
        cats = {}
        for name, title, co, _fl, _ks in _people_rows():
            nm = re.sub(r"[^a-z0-9]", "", name.lower())
            if len(nm) >= 6:
                cats[nm] = _person_category(title, co)
        ident = _identity_map()
        for r in _load_sends():
            if str(r.get("status", "")).lower() in NOT_DELIVERED:
                continue
            if str(r.get("date", "")) < cutoff:
                continue
            raw = str(r.get("to", "")).strip()
            to = re.sub(r"[^a-z0-9]", "", raw.lower())
            if len(to) < 6:
                continue
            who = ident.get(raw.lower())
            if who is None:
                m = re.search(r"/in/([^/?#]+)", raw.lower())
                if m:
                    who = ident.get(re.sub(r"[^a-z0-9]", "", m.group(1)))
            cat = (cats.get(re.sub(r"[^a-z0-9]", "", who.lower())) if who else None) \
                or next((c for nm, c in cats.items() if nm in to or to in nm), None)
            if cat:
                per[cat] += 1
    except Exception:
        pass
    return per


def _with_exposure_floor(ranked, n):
    """Guarantee the least-worked eligible category ONE slot in the shown list.

    ⚖️ THE ANTI-COLLAPSE RULE. A learner that only exploits never tries what it has not tried. One
    recompute upstream moved a single band to the top and the ENTIRE top ten became that band —
    which may be right, and is UNFALSIFIABLE if no other category is ever sent to again. Categories
    with no sends sit at the flat prior forever, so their absence is self-confirming rather than
    evidence.

    ⛔ DELIBERATELY NOT THOMPSON SAMPLING, which was the other candidate. This function's caller
    promises "the order is total and two runs cannot disagree", and a per-session random draw breaks
    that promise for everyone downstream — the printed board, --targets, the session briefing, and
    any test that happens to run on the wrong day. The floor buys the same exploration
    DETERMINISTICALLY: it is a reordering computed from behaviour, reproducible and auditable.

    Cost, stated plainly: one of the n shown slots is not the highest-scoring row. That is the price
    of learning anything about a category you have stopped sending to.
    """
    if n <= 1 or len(ranked) <= n:
        return ranked[:n]
    head = ranked[:n]
    shown = {c["cat"] for c in head}
    recent = _recent_sends_by_category()
    # Eligible: a category that exists further down the list and is NOT already represented.
    below = [c for c in ranked[n:] if c["cat"] not in shown]
    if not below:
        return head
    starved = min({c["cat"] for c in below}, key=lambda k: (recent.get(k, 0), k))
    pick = next((c for c in below if c["cat"] == starved), None)
    if pick is None:
        return head
    pick = dict(pick)
    pick["reasons"] = list(pick["reasons"]) + [
        f"🎲 exposure slot — fewest sends in the last {EXPOSURE_WINDOW_DAYS}d "
        f"({recent.get(starved, 0)}), so this category stays falsifiable"]
    return head[:-1] + [pick]


# ── LIVE GAP-CLOSE on a proposed trio ───────────────────────────────────────────────────────
# WHY: the ranker scores from signals RECORDED on the green board, and a recorded signal goes stale.
# A row can sit high on the board with a hand-written "verify US/remote" note while the live ATS
# shows the truth — every US product seat onsite, and the sole "remote" PM req denominated in a
# foreign currency. That is a REMOTE HARD FAIL, not a caveat, and it would ship inside an approved
# trio because "verify" was a note to a human rather than a step. So the trio gets probed against the
# live ATS before it is proposed.
#
# DELIBERATELY NOT AN AUTO-DROP. This reports evidence and RAISES A FLAG; the ruling stays with the
# human. A regex that silently vetoes a company on a location string would make exactly the class of
# invisible error this whole gate exists to prevent.
US_REMOTE = re.compile(r"remote", re.I)
# A location string that declares itself hybrid or on-site is NOT a remote seat, whatever else it
# says. See the veto in assess_postings for the two live defects that motivated this.
NOT_REMOTE_WORKPLACE = re.compile(r"\bhybrid\b|\bon-?site\b|\bin-?office\b", re.I)
US_MARKER = re.compile(r"\b(u\.?s\.?a?|united states|nationwide|anywhere in the us)\b", re.I)
NON_US = re.compile(r"\b(india|pune|bengaluru|bangalore|london|uk|united kingdom|ireland|germany|"
                    r"berlin|france|paris|spain|portugal|poland|toronto|canada|sydney|australia|"
                    r"singapore|japan|tokyo|brazil|argentina|colombia|mexico|chile|peru|emea|apac)\b", re.I)
# Foreign-currency comp is the tell when the LOCATION string names no country at all — a req can say
# "Remote" and only the €-denominated band gives it away. Cover symbols AND ISO codes, because ATS
# bands use either; a band in INR/JPY/BRL/MXN/SEK/CHF/PLN/ZAR/SGD/ILS/KRW/CNY would otherwise read
# as a US seat. Plain "$" is deliberately NOT here: it is the US default, and the prefixed forms
# (CA$/A$/NZ$/S$/HK$/R$/MX$/NT$) carry the distinction. `(?<![A-Za-z])` keeps "R$"/"A$" from firing
# inside a word.
NON_USD = re.compile(
    r"[€£¥₹₽₩₪₺฿]"
    r"|(?<![A-Za-z])(?:CA|A|NZ|S|HK|R|MX|NT)\$"
    r"|\b(?:EUR|GBP|CAD|AUD|NZD|INR|JPY|CNY|RMB|BRL|MXN|ARS|CLP|COP|PEN|SEK|NOK|DKK|ISK|CHF|"
    r"PLN|CZK|HUF|RON|TRY|ZAR|NGN|KES|SGD|HKD|TWD|KRW|THB|MYR|IDR|PHP|VND|ILS|AED|SAR|UAH)\b",
    re.I)


def assess_postings(jobs):
    """jobs = [{'title','loc','comp','is_pm'}]. Pure, so it is testable without a network call.
    Returns the evidence a remote-absolute ruling needs."""
    tot = len(jobs)
    us_remote, bare_remote, pm_seats, pm_us_remote = 0, 0, [], 0
    for j in jobs:
        loc = j.get("loc") or ""
        comp = j.get("comp") or ""
        # HYBRID/ON-SITE VETO (2026-07-25): Ashby reports isRemote:true on Hybrid reqs.
        remote = bool(US_REMOTE.search(loc)) and not NOT_REMOTE_WORKPLACE.search(loc)
        foreign_loc = bool(NON_US.search(loc))
        foreign_cur = bool(NON_USD.search(comp))
        # AN EXPLICIT US MENTION WINS OVER A CO-LISTED FOREIGN REGION. "Remote — US or Canada" is a
        # legitimate US-eligible seat, but NON_US matches "canada" and would knock it out of BOTH
        # buckets, so a board whose only remote reqs are dual-region would score as having no remote
        # posting of any kind — a false 🔴 on a company that IS hiring US-remote. Foreign CURRENCY
        # still disqualifies: a band quoted in EUR is not a US seat whatever the location string says.
        us_ok = remote and not foreign_cur and (bool(US_MARKER.search(loc)) or not foreign_loc)
        if us_ok and US_MARKER.search(loc):
            us_remote += 1
        elif us_ok:
            bare_remote += 1
        if j.get("is_pm"):
            pm_seats.append(j)
            if us_ok:
                pm_us_remote += 1
    # A board with postings but ZERO unambiguous US-remote signal is the remote-in-title shape.
    flag = None
    if tot and not us_remote and not bare_remote:
        flag = "🔴 no remote posting of any kind on the live board"
    elif pm_seats and not pm_us_remote:
        flag = "🔴 PM seats exist but NONE is US-remote (remote-in-title, foreign-in-practice)"
    elif not tot:
        flag = "⚪ board empty or unreachable — treat remote as UNVERIFIED"
    return {"total": tot, "us_remote": us_remote, "bare_remote": bare_remote,
            "pm_seats": pm_seats, "pm_us_remote": pm_us_remote, "flag": flag}


def probe_live_board(company):
    """Fetch ALL postings (not just PM seats — the remote POSTURE shows across the whole board, which
    is how a company's several 'Remote US' reqs confirm it). Never raises: a briefing helper must not
    block on a flaky network."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import check_ats
    except Exception:
        return None
    for tk in check_ats.tokens_from(company):
        for url, kind in ((f"https://boards-api.greenhouse.io/v1/boards/{tk}/jobs", "Greenhouse"),
                          (f"https://api.ashbyhq.com/posting-api/job-board/{tk}"
                           "?includeCompensation=true", "Ashby"),
                          (f"https://api.lever.co/v0/postings/{tk}?mode=json", "Lever")):
            d = check_ats.get_json(url)
            jobs = None
            if kind == "Greenhouse" and isinstance(d, dict) and "jobs" in d:
                jobs = [{"title": j.get("title", ""), "loc": (j.get("location") or {}).get("name", ""),
                         "comp": "", "is_pm": check_ats.is_pm(j.get("title", ""))} for j in d["jobs"]]
            elif kind == "Ashby" and isinstance(d, dict) and "jobs" in d:
                jobs = [{"title": j.get("title", ""),
                         "loc": check_ats.ashby_location(j),
                         "comp": (j.get("compensation") or {}).get("compensationTierSummary", ""),
                         "is_pm": check_ats.is_pm(j.get("title", ""))} for j in d["jobs"]]
            elif kind == "Lever" and isinstance(d, list) and d:
                jobs = [{"title": j.get("text", ""), "loc": (j.get("categories") or {}).get("location", ""),
                         "comp": "", "is_pm": check_ats.is_pm(j.get("text", ""))} for j in d]
            if jobs:
                return {"board": kind, "token": tk, **assess_postings(jobs)}
    return None


def _weights_age_line():
    """One line a session can read to see what the weights ARE and where they came from.

    ⚖️ It no longer reports AGE, because there is none to report — the weights are derived from the
    send log on every run. The old "N sends landed since" warning is gone along with the condition it
    warned about. What replaces it is the REORDER note, which answers the question the age line was
    really a proxy for: has the ranking changed under me?
    """
    W = live_weights()
    if not W or not int(W.get("joined", 0)):
        # Silence here would be a recompute-shaped change hiding in a default: an unmoved score looks
        # identical whether the evidence said "no change" or there was no evidence at all.
        return ("  ⚖️ no weights row yet — no send-log evidence joins a categorized contact, so "
                "literature priors only (w=1.0 everywhere); the ranker learns as sends land")
    line = (f"  ⚖️ weights derived live · {W.get('joined', 0)} of {W.get('log_rows', 0)} logged "
            f"sends joined · founder order: {W.get('founder_order', 'last')}")
    note = weights_reorder_note()
    return line + ("\n" + note if note else "")


def main():
    n = 10
    brief = "--brief" in sys.argv
    pool = "companies"
    # ── dynamic person-weights: the explicit write, and the inspection view ──────────────────
    if "--recompute-weights" in sys.argv:
        recompute_weights()
        sys.exit(0)
    if "--audit-signals" in sys.argv:
        sys.exit(0 if audit_signals() == 0 else 2)
    if "--validate-signal" in sys.argv:
        _i = sys.argv.index("--validate-signal")
        _name = sys.argv[_i + 1] if _i + 1 < len(sys.argv) else ""
        _pred = None
        if "--predicate" in sys.argv:
            _j = sys.argv.index("--predicate")
            _pred = sys.argv[_j + 1] if _j + 1 < len(sys.argv) else None
        if not _name:
            print('usage: --validate-signal <name> [--predicate <regex>]')
            sys.exit(3)
        validate_signal(_name, _pred)
        sys.exit(0)
    if "--weights" in sys.argv:
        W = _stored_weights()
        if not W:
            print("no stored weights row — the people ranker is running on pure literature "
                  "priors.\nCompute the first row: scripts/rank_criteria.py --recompute-weights")
            sys.exit(0)
        print(f"person-weights row of {W.get('as_of')}  "
              f"(source {W.get('as_of_source')}; {W.get('joined')} of {W.get('log_rows')} "
              f"sends joined)")
        print(f"params: {json.dumps(W.get('params', {}), ensure_ascii=False)}")
        print(f"{'category':16} {'sends':>5} {'repl':>5} {'post-rate':>9} {'sd':>7} {'w':>5}")
        for cat, d in sorted(W.get("per_category", {}).items()):
            print(f"{cat:16} {d.get('sends', 0):>5} {d.get('replies', 0):>5} "
                  f"{d.get('post_mean', 0):>9.3f} {d.get('post_sd', 0):>7.3f} {d.get('w', 1):>5.2f}")
        print(f"founder order: {W.get('founder_order', 'last')}")
        print(_weights_age_line())
        sys.exit(0)
    if "--pool" in sys.argv:
        _i = sys.argv.index("--pool")
        if _i + 1 < len(sys.argv):
            pool = sys.argv[_i + 1]
    if "--n" in sys.argv:
        i = sys.argv.index("--n")
        if i + 1 < len(sys.argv):
            try:
                n = int(sys.argv[i + 1])
            except ValueError:
                pass
    # ── TARGET TRIO for a warm ask ──────────────────────────────────────────────────────────
    # WHY: the criteria ranking IS the rolling list of top-matched companies. Asking the user to
    # NAME three target companies from memory is asking them to redo, by recall, the calculation this
    # ranker already performs — the user should make decisions, not perform calculations leading to
    # decisions. The boss-hunt method's warm template needs exactly three ("rather than toss you a
    # long list…"), and mail-draft.sh BLOCKS a warm rung without --targets, so the trio is a hard
    # requirement of the message — which makes it the pipeline's job to COMPUTE and the user's job to
    # APPROVE OR SWAP. This mode emits the ready --targets string.
    if "--targets" in sys.argv:
        if "--n" not in sys.argv:
            n = 3
        ranked, _ = rank(max(n, 10))
        trio = ranked[:n]
        print("=" * 74)
        print("  WARM-ASK TARGET TRIO — computed from your criteria, dedup-clean")
        print(f"  ({CRITERIA_MATRIX_DOC} · SENT/blocked/already-contacted excluded)")
        print("=" * 74)
        if not trio:
            print("\n  ⚠️  no rankable candidates — refill the green board before building a warm ask.\n")
            sys.exit(0)
        verify = "--verify" in sys.argv
        # `unverified` is NOT a subset of `flagged`, and conflating them is the bug this fixes.
        # A company whose ATS never resolved was not CHECKED; it did not PASS. The old code hit
        # `continue` on that branch without recording anything, so `flagged` stayed empty and the
        # closing line announced "all three cleared the live remote check" about companies nothing
        # had read. Remote is the filter that is never waived, so a summary claiming it passed is
        # the most expensive false statement this script can make.
        flagged, unverified = [], []
        for i, c in enumerate(trio, 1):
            print(f"\n  {i}. {c['company']}   {TIER_LABEL.get(c['tier'], '')}   ·   score {c['pts']}")
            print(f"     {c['lane']}")
            if verify:
                a = probe_live_board(c["company"])
                if not a:
                    print("     ⚪ live board: no ATS found → remote/vitality UNVERIFIED")
                    unverified.append(c["company"])
                    continue
                print(f"     live {a['board']} board: {a['total']} open reqs · "
                      f"{a['us_remote']} explicitly US-remote · {a['bare_remote']} remote "
                      f"(region unstated) · {len(a['pm_seats'])} PM seat(s)")
                for p in a["pm_seats"][:4]:
                    print(f"        ▸ {p['title']} | {p['loc']} {p['comp']}".rstrip())
                if a["flag"]:
                    print(f"     {a['flag']}")
                    flagged.append(c["company"])
        if verify:
            if flagged:
                print("\n  ⚠️  FLAGGED, rule before you send: " + ", ".join(flagged))
                print("     A remote-absolute fail is a DROP, not a caveat. Mark it on the green board")
                print("     with the evidence, then re-run this so the trio recomputes without it.")
            if unverified:
                print("\n  ⚪ NOT VERIFIED (no ATS board resolved): " + ", ".join(unverified))
                print("     Remote was never CHECKED for these. That is not a pass and must not be")
                print("     read as one. Fine to name in a warm intro ask, where the full screen")
                print("     runs later anyway. Verify by hand on the company's own careers page")
                print("     before any application, resume build, or live-role framing.")
            if not flagged and not unverified:
                print("\n  ✅ all three cleared the live remote check.")
        print("\n  Ready for mail-draft.sh:")
        print('     --targets "' + ",".join(c["company"] for c in trio) + '"')
        print("\n  YOUR CALL: approve this trio, or swap any one of them. The rest of the ranked")
        print("  list is `scripts/rank_criteria.py` with no flags.\n")
        sys.exit(0)

    # ── PEOPLE pool ─────────────────────────────────────────────────────────────────────────
    if pool == "people":
        ranked, skipped = rank_people(n)
        if brief:
            print(f"  TOP {len(ranked)} PEOPLE — who can help first (pick 3 to reach):")
            _flagged = 0
            for i, c in enumerate(ranked, 1):
                # 🌏 No store here records a company's COUNTRY, so nothing can gate on it. This
                # prints the doubt at the point of decision instead: a non-US legal-form suffix in
                # the name means check where they are before spending anything else on them.
                _tell = nonus_tell(c.get("company"))
                if _tell:
                    _flagged += 1
                print(f"    {i:2}. {c['name']:<22} {PERSON_BADGE[c['cat']]:<16} score {c['pts']:>5}  · "
                      f"{c['title'][:22]} @ {c['company'][:20]}"
                      + (f"  🌏 '{_tell}' — CHECK THE COUNTRY FIRST" if _tell else ""))
            if _flagged:
                print(f"    🌏 {_flagged} row(s) carry a non-US legal form. The suffix is the only "
                      f"country signal any store here holds, so absence proves nothing.")
            print("    Ranked by likely-boss + relationship distance (scoring v2, 2026-07-26);")
            print("    deal-breakers only, culture waits. Tune the priors in kit_config.")
            print(_weights_age_line())
            _vab = _profile_views_age_line(load_profile_views())
            if _vab:
                print(_vab)
            sys.exit(0)
        print("=" * 74)
        print("  TOP PEOPLE TO REACH — WHO CAN HELP FIRST (the boss-hunt method)")
        print("  (likely-boss + relationship distance; deal-breaker vetoes only; culture/WLB post-contact)")
        print("=" * 74)
        print("  ⚖️ scoring v2 (2026-07-26): likely-boss model — founder/CEO band EQUAL to product")
        print("     leaders (Ruling A), founder last only as a TIEBREAK among equals (Ruling B,")
        print("     evidence-movable), distance +0.5/yr capped +5, category weights learned from")
        print("     the send log with heavy shrinkage. Tune the priors in kit_config.")
        print("     (retune in kit_config: PERSON_WEIGHTS_V2, PERSON_DISTANCE_PER_YEAR,")
        print("     PERSON_DISTANCE_CAP, PERSON_SEARCH_ERA, PERSON_PRIOR_STRENGTH).")
        print(_weights_age_line())
        _pool_n = len(_people_rows())
        print(f"  Pool: {_pool_n} contacts in the current warm-network.md snapshot.")
        print("  Buckets are pre-sorted best-first, so the top of each is here; for the FULL network")
        print("  regenerate documents/warm-network.md from your network parser. Blocked-co /")
        print("  deal-breaker / contacted excluded. Display ties at 0.1 are ordered by exact connect")
        print("  date (older first), founder/CEO last among equals.")
        print("  Pick 3 people to reach today. Warm rung = deal-breakers only; the deep screen")
        print("  (still deal-breakers-only for a warm intro) runs before outreach.\n")
        for i, c in enumerate(ranked, 1):
            print(f"  {i:2}. {c['name']}   {PERSON_BADGE[c['cat']]}   ·   score {c['pts']}")
            print(f"      {c['title']}  @  {c['company']}")
            # THE SANCTIONED ASK, printed WITH the person. The category badge above says who they
            # ARE ("🎯 likely boss"), which reads as permission to ask for the job — and that badge
            # on a stated "know but not close" acquaintance is the whole defect the closeness store
            # exists to stop. This line says what may be ASKED, a different question and the one
            # that governs.
            if c.get("band") == "BLOCKED":
                print(f"      ask: ⛔ BLOCKED — {c['ask']}")
            elif c.get("ask"):
                print(f"      ask: 🪜 {c['band']} — {c['ask']}")
            print(f"      why: {' · '.join(c['reasons'])}")
            print()
        if len(ranked) < n:
            print(f"  ⚠️  only {len(ranked)} rankable contact(s) after exclusions.")
        # 📊 PLATEAU TRIPWIRE. A scoring function built from a few discrete bonuses over a large
        # population WILL pile up on one value, and upstream that happened three separate times —
        # each one found by eye, weeks apart. A ceiling that announces itself is found the same day.
        # ⚠️ WHOLE POINTS, and the reason string on top of it. An exact 0.1 match is defeated by
        # any continuous term (a tenure bonus spread one identical band across five "distinct"
        # scores), and even a whole-point tie understates the problem: upstream, six tied rows
        # carried FIVE byte-identical reason strings, meaning no feature separated them at all.
        # ⚖️ AND THE SCORE IS THE WEAKER HALF. Rows can tie on score while a continuous term hides
        # it, and identical stated grounds means the ranker owns no feature that separates those
        # people at all — so the shared instrument fires on its own count, at its own threshold.
        print_tie_tripwires(ranked, "older connect date first")
        # 👀 PROFILE VIEWS (WU-4). The store's age, then the viewers who are NOT in the connection
        # pool — the natural on-ramp for a bridge sweep, since a stranger who viewed the profile is
        # exactly the person no connections-based ranker can see.
        _views_p = load_profile_views()
        _va = _profile_views_age_line(_views_p)
        if _va:
            print(_va)
            _pool_keys = {re.sub(r"[^a-z0-9]", "", nm.lower()) for nm, *_ in _people_rows()}
            _strangers = [r for k, r in _views_p.items() if k not in _pool_keys]
            for r in _strangers[:5]:
                print(f"     · {r.get('name')} — {r.get('title') or '?'} @ "
                      f"{r.get('company') or '?'} viewed you, NOT a connection")
            if len(_strangers) > 5:
                print(f"     · … and {len(_strangers) - 5} more viewer(s) who are not connections")
        # ⚖️ A board that is ALL reunions is honest but not a job search. A reunion IS a send and
        # counts as work, so this never suppresses the rows — it names the SHAPE of the day so the
        # day's picks are a choice rather than a surprise.
        _reu = sum(1 for c in ranked if c.get("rung") == "reunion")
        if _reu and _reu >= max(1, len(ranked) // 2):
            print(f"  🔁 {_reu} of {len(ranked)} shown are REUNION-first (strong tie, cold thread): "
                  f"no ask, and the outreach follows later as its own message.")
        if skipped:
            print("  excluded (deal-breaker): " + ", ".join(f"{nm} ({why})" for nm, why in skipped[:4]))
        print("\n  NO culture/WLB in this ranking, by design (those are post-interview scores;")
        print("  warm rungs need deal-breakers only). Re-run after each pick to re-rank the rest.")
        print("  Likely-boss is a TWO-PLACE read (person + company shape): where the green board")
        print("  knows the shape, a founder at a founder-led company IS the boss (🌾) and an exec")
        print("  behind a seated product leader scores as a referrer. Unknown shape = both equal.")
        sys.exit(0)

    ranked, skipped = rank(n)

    if brief:
        print(f"  TOP {len(ranked)} BY YOUR CRITERIA (pick 3 companies to work today):")
        for i, c in enumerate(ranked, 1):
            tag = TIER_LABEL[c["tier"]]
            print(f"    {i:2}. {c['company']:<22} {tag:<16} score {c['pts']:>4}  · {c['lane'][:34]}")
        print("    Ranked on RECORDED criteria signals; culture confidence is the primary key.")
        sys.exit(0)

    print("=" * 74)
    print("  TOP COMPANIES BY YOUR EMPLOYER CRITERIA")
    print(f"  ({CRITERIA_MATRIX_DOC} · culture confidence first, then points)")
    print("=" * 74)
    print(f"  Pool: green board, topped up from discovery. SENT/blocked/done excluded.")
    print(f"  Pick 3 companies to work today.\n")
    for i, c in enumerate(ranked, 1):
        print(f"  {i:2}. {c['company']}   {TIER_LABEL[c['tier']]}   ·   score {c['pts']}   ·   {c['source']}")
        print(f"      lane: {c['lane'][:60]}")
        print(f"      criteria: {' · '.join(c['reasons'])}")
        if c["boss"]:
            print(f"      boss: {c['boss'][:70]}")
        print()
    if len(ranked) < n:
        print(f"  ⚠️  only {len(ranked)} rankable candidate(s) — the board + discovery are thin. "
              f"Refill to see a full top {n}.")
    # 📊 THE SAME TRIPWIRES THE PEOPLE BOARD GETS. Companies sort on (pts, tier, seats); when all
    # three match, the order is the input order, which is a file-and-dict accident. The human is
    # asked to "pick 3" off the top of this list, so a silent tie sends them at whoever happened to
    # be parsed first. See `print_tie_tripwires` for why this took two boards to reach.
    print_tie_tripwires(ranked, "equal score and tier — input order decides")
    # 📋 AND WHAT TO DO ABOUT IT. The tripwire above says row 1 is a coin flip; this says which
    # measurement stops it being one. Printed after, because it is the answer to the warning.
    print_screening_queue(ranked)
    if skipped:
        print(f"  excluded on a veto: " + ", ".join(f"{co} ({why})" for co, why in skipped[:4]))
    print("\n  Ranked on RECORDED signals (culture, remote, PE, boss, praise) mapped to the matrix.")
    print("  Unrecorded criteria are shown 'n/a', never scored as zero. Full criterion-by-criterion")
    print("  scoring is an interview-stage workup, not this.")
    sys.exit(0)


if __name__ == "__main__":
    main()
