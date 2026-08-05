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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The column contract and the durable store. Same import-never-copy rule as the veto lists below:
# canonical column names live in schema.py so a board table gaining a column cannot shift a reader's
# indices, and state.py owns the ONE recency rule every reader funnels through.
import schema  # noqa: E402
import state  # noqa: E402
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
    from check_screen_gate import VETO_EMPLOYERS, veto_hits, is_artifact
except Exception:  # standalone fallback — no squashed pass, and no artifact filter
    VETO_EMPLOYERS = []

    def veto_hits(name, text=""):
        low = f"{name or ''} {text or ''}".lower()
        return sorted({re.search(v, low).group(0) for v in INDUSTRY_VETO if re.search(v, low)})

    def is_artifact(name):
        return False

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

    def __contains__(self, needle):
        n = (needle or "").strip().lower()
        if not n:
            return False
        try:
            from screen_sweep import canon, blocked_keys_from_list
            k = canon(n)
            return bool(k) and k in blocked_keys_from_list()
        except Exception:
            # FAIL CLOSED on a broken import. A ranker that cannot read the blocked list must not
            # quietly start offering blocked companies; an empty pool is a visible failure, a
            # silently unblocked one is not.
            return True


def blocked_set():
    """Blocked-list text with word-bounded membership. See _BlockedText for why it is not a str."""
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


def _score_fields(company, lane, remote, culture, nonpe, boss, praise):
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
    if re.search(r"hybrid|onsite required|relocat", remote, re.I) or "✅" not in remote and "remote" not in remote.lower():
        return None, f"veto (remote): {remote.strip() or 'not confirmed'}"
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
    conf = CONFIDENCE_MULTIPLIER.get(tier, 0.5)
    return {
        "company": company, "lane": lane, "tier": tier, "pts": round(pts * conf, 1),
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


def banked_topup(have, done, blocked, need):
    """Fill from the agent-screened BANKED files before falling back to raw discovery.

    Reads the dot-separated batch lists that screen_sweep.py --bank writes to
    documents/banked-candidates-*.md. Keep this reader interface intact: screen_sweep.py's bank()
    points at this function, and it deliberately skips lines starting with `|`, `#`, `>` or `-`.
    """
    out = []
    havenames = {c["company"].lower() for c in have}
    for path in banked_sweep_files():
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for line in text.splitlines():
            if len(out) >= need:
                return out
            # rows look like:  Company A · Company B · **Company C** ·  (batch lists)
            if not line.strip() or line.lstrip().startswith(("#", ">", "|", "-")):
                continue
            for chunk in line.split("·"):
                co = chunk.strip().strip("*~ ").strip()
                co = re.sub(r"\s*\(.*?\)\s*$", "", co).strip()
                if not (2 <= len(co) <= 34) or not re.match(r"^[A-Z][\w&.\-' ]+$", co):
                    continue
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
                out.append({"company": co, "lane": "MECHANICAL gates only, NOT screened",
                            "tier": 1, "pts": 0.5,
                            "reasons": ["BANKED sweep: mechanical gates only. Remote, PE, culture "
                                        "and boss ALL still owed. Worth screening, never worth sending."],
                            "boss": "", "source": os.path.basename(path)})
                havenames.add(low)
                if len(out) >= need:
                    return out
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
    if len(cands) < n:
        cands += _drop_deferred(discovery_topup(cands, done, blocked, n - len(cands)), skipped, supp)
    # Sort by the final criteria score, which ALREADY folds in culture-screen confidence (the
    # per-tier multiplier in score_board_row). A verified clean row therefore floats up on merit
    # rather than by fiat, and the number the user reads is the number they are sorted by — no
    # "why is #1 below #2 in score" confusion. Tier stays a visible tag. Ties broken by tier.
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
                              "product-ic": 25, "connector": 15, "other": 5}
try:
    from kit_config import PERSON_WEIGHTS_V2 as PERSON_BASE
except Exception:
    PERSON_BASE = dict(_PERSON_WEIGHTS_V2_DEFAULT)

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
# Trailing window that decides which category is STARVED of sends (the exposure floor, below).
EXPOSURE_WINDOW_DAYS = 30

PERSON_BADGE = {"product-leader": "🎯 likely boss", "founder-exec": "🏛 founder/CEO",
                "senior-exec": "🏢 senior exec", "product-ic": "🤝 product peer",
                "connector": "📇 connector", "other": "· other"}

# The org-OWNER titles Ruling A elevates. Deliberately narrow: CTO/VP/directors/partners are senior
# but would not manage a product hire; "managing director" is a level at large firms.
# "(?<!vice )president" because \bpresident\b matches the second word of "Vice President" — the
# first live run promoted a "VP Senior Recruiting Consultant" into the founder band on that token.
_OWNER_TITLE = re.compile(r"\b(founder|co-?founder|ceo|chief executive|coo|chief operating|"
                          r"(?<!vice )president|owner)\b", re.I)
# A "Product Owner" is a scrum-role IC, but SENIOR's \bowner\b matched inside the phrase, so every
# Product Owner in the network scored as a product LEADER under v1 (four of one tied top 10).
_PO_PHRASE = re.compile(r"\bproduct\s+owner\b", re.I)
# Principal/Staff PMs are senior ICs. Under Ruling A "likely boss" means MANAGES the role, so they
# are peers unless the title ALSO carries a real management marker (Head/VP/Director/CPO/founder…).
_IC_SENIORITY = re.compile(r"\b(principal|staff)\b", re.I)


def _person_category(title):
    """Category from the TITLE alone — the company-shape half of the likely-boss predicate is
    applied by the caller via _company_shape_map(), because shape lives on the green board, not in
    the title. With shape UNKNOWN (most of a network), both plausible-boss reads stay equal."""
    t = title or ""
    # Mask to a SINGLE word: "product-owner" still leaves a \b before "owner" (the hyphen is a
    # non-word char), so the first cut of this mask changed nothing. Verified against a live pool:
    # a "Product Owner" ranked #1 as a likely boss under the hyphen mask.
    masked = _PO_PHRASE.sub("productowner", t)
    pm, sr = is_pm(t), bool(SENIOR.search(masked))
    if pm and sr:
        # Ruling A: a Principal/Staff PM whose only "senior" token is that seniority marker is a
        # peer, not the person who would manage a product hire.
        if _IC_SENIORITY.search(masked) and not SENIOR.search(_IC_SENIORITY.sub("", masked)):
            return "product-ic"
        return "product-leader"   # Head/VP/Dir/CPO of Product — plausibly manages this role
    if sr:
        if _OWNER_TITLE.search(masked):
            return "founder-exec"  # founder/CEO/COO — the likely boss where no product org exists
        return "senior-exec"       # functional senior (CTO, IT/mktg dir, partner) — hires or refers
    if pm:
        return "product-ic"       # PM/Sr PM — a would-be teammate who can refer/intro
    if CONNECTOR.search(t):
        return "connector"        # recruiter/talent — routes you
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
    for name, title, _co, _fl, _ks in _people_rows():
        nm = re.sub(r"[^a-z0-9]", "", name.lower())
        if len(nm) >= 6:
            cats[nm] = _person_category(title)
            by_name[nm] = _person_category(title)
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


def live_weights():
    """The weights the ranker actually scores with: DERIVED from the send log, on every run.

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
        except Exception:
            _LIVE_WEIGHTS["w"] = _stored_weights()
    return _LIVE_WEIGHTS["w"]


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
    if a == b:
        return None
    return (f"  ⚖️ category order MOVED since the {old.get('as_of')} snapshot: "
            f"{' > '.join(a)}  →  {' > '.join(b)} · snapshot it with --recompute-weights")


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


def nonus_tell(company):
    """The matched non-US legal-form suffix in a company name, or '' when there is none.

    ⚠️ A SURFACE, never a veto. No store here records a company's COUNTRY, so this only spots a
    legal-form suffix in the name. It will miss a foreign company whose stored name carries no
    suffix, which is how the case that motivated it got through. Check the country yourself on any
    founder before spending anything else on them: it is the cheapest disqualifier available.
    """
    m = _NONUS_SUFFIX.search(company or "")
    return m.group(1) if m else ""


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
            m = re.search(r"linkedin\.com/in/([^/?\s]+)", str(d.get("to") or ""))
            if m:
                slug = m.group(1).lower()
                nm = re.sub(r"[^a-z0-9]", "", slug)
                if len(nm) >= 4:
                    names.add(nm)
                # 🔴 A MIDDLE INITIAL IN THE SLUG BREAKS THE JOIN. A profile at
                # `/in/jordan-a-lee` keys as `jordanalee`, while the contact pool knows the person
                # as "Jordan Lee" and keys as `jordanlee`. The two never match, so the
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
            in_pool = any(k in line for k in ("Product people", "Senior decision", "Connectors"))
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
        cat = _person_category(title)
        # ── SEGMENT READ, TRI-STATE, and only a POSITIVE off-segment match may demote ─────────
        # "unknown" KEEPS the band, because most real companies do not carry their industry in
        # their name. Demoting on "no match" would push a Head of Product at a major payments
        # company down exactly as far as an artist-management sole trader.
        _segstate, _segdetail = ("unknown", None)
        _evtier = 1
        _evsrc = None
        if contact_signals:
            _segstate, _segdetail = contact_signals.segment_read(company, title)
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
        # 🌡️ THREAD DEPTH — the second axis. Closeness says how STRONG the tie is; this says whether
        # it is LIVE. A live thread is a warmer starting point than a cold one at the SAME closeness,
        # and the term is small on purpose so strength keeps dominating temperature.
        if closeness:
            _tstate, _tlast = closeness.thread_state(crow)
            _tb = PERSON_THREAD_BONUS.get(_tstate, 0.0)
            if _tb:
                pts = round(pts + _tb, 1)
                reasons.append(f"thread {_tstate}"
                               + (f" (last reply {_tlast}, +{_tb:g})" if _tlast else f" (+{_tb:g})"))
        dist, yrs = "unknown", 0.0
        m_date = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", known_since)
        if cbonus:
            pts = round(pts + cbonus, 1)
            tier = (crow or {}).get("closeness", "?")
            reasons.append(f"{tier} (+{cbonus:g})")
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
        if contact_signals:
            if _evtier == contact_signals.EV_NOT_FOUND:
                reasons.append(f"⚪ searched and NOT placeable ({_evsrc}) — sorts below every "
                               f"resolved employer, and below one nobody has looked at yet")
            elif _evtier == contact_signals.EV_LOW_CONF:
                reasons.append(f"🟡 employer resolved at LOW confidence ({_evsrc})")
            elif _evtier == contact_signals.EV_RESOLVED:
                reasons.append(f"🔬 employer resolved ({_evsrc})")
        out.append({"name": name, "title": title[:46], "company": company, "cat": cat,
                    # ⚠️ `evtier`, NOT `tier` — the `tier` key below is CLOSENESS. Reusing the
                    # name would silently overwrite it.
                    "evtier": _evtier,
                    "pts": round(pts, 1), "reasons": reasons, "distance": dist,
                    "known_since": known_since, "founder_last": founder_last, "yrs": yrs,
                    # The ask travels WITH the row. One blended pool of the whole network is only
                    # defensible because closeness drives the ask SHAPE — so if the rung lives only
                    # in the reader's head that basis is unenforceable, and unenforceable is how a
                    # warm-shaped ask reaches a stranger at scale.
                    "rung": rung, "band": band, "ask": ask,
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
    out.sort(key=lambda c: (-c["evtier"], -c["pts"], c["founder_last"], -c["yrs"],
                            c["name"].lower()))
    return _with_exposure_floor(out, n), skipped


def _recent_sends_by_category(days=EXPOSURE_WINDOW_DAYS):
    """{category: delivered sends in the trailing window}, from the send log × the roster."""
    per = {c: 0 for c in PERSON_BASE}
    try:
        from rung_ladder import load as _load_sends, NOT_DELIVERED
        from datetime import timedelta as _td
        cutoff = (_date.today() - _td(days=days)).isoformat()
        cats = {}
        for name, title, _co, _fl, _ks in _people_rows():
            nm = re.sub(r"[^a-z0-9]", "", name.lower())
            if len(nm) >= 6:
                cats[nm] = _person_category(title)
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
        _sc = collections.Counter(round(float(c["pts"]), 1) for c in ranked)
        _top, _cnt = (_sc.most_common(1) or [(None, 0)])[0]
        if _cnt > PLATEAU_WARN_AT:
            print(f"  ⚠️  PLATEAU: {_cnt} of {len(ranked)} shown rows share the score {_top}. "
                  f"Ties this wide mean the ordering below them is a tiebreak, not a ranking.")
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
    if skipped:
        print(f"  excluded on a veto: " + ", ".join(f"{co} ({why})" for co, why in skipped[:4]))
    print("\n  Ranked on RECORDED signals (culture, remote, PE, boss, praise) mapped to the matrix.")
    print("  Unrecorded criteria are shown 'n/a', never scored as zero. Full criterion-by-criterion")
    print("  scoring is an interview-stage workup, not this.")
    sys.exit(0)


if __name__ == "__main__":
    main()
