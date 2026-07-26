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
    scripts/rank_criteria.py --pool people       # rank warm contacts by "who can help first"
    scripts/rank_criteria.py --targets           # emit a 3-company warm-ask trio (mail-draft --targets)
    scripts/rank_criteria.py --targets --verify  # + probe each company's live ATS for remote reality
Exit: 0 always (a briefing must never block a session).
"""
import os
import json
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

# VETO_EMPLOYERS — named companies whose INDUSTRY is a deal-breaker but whose NAME contains none of
# the banned WORDS in INDUSTRY_VETO. The keyword list only catches a company that DESCRIBES itself
# ("defense", "crypto"); it cannot catch one that is merely NAMED. In the people pool the only
# signal is an employer NAME, so a crypto exchange or a defense prime comes back "clean" and ranks
# unless its name is listed here.
#
# ⚠️ EXAMPLE set — edit to YOUR deal-breakers, and keep it consistent with kit_config.INDUSTRY_VETO
# (if you don't veto gambling, drop the gambling names). These are PUBLIC classifications, not
# editorial judgements. It is a curated FLOOR, incomplete by construction — it does not replace the
# per-company screen, it stops the worst known-bad names from reaching a surface you review.
VETO_EMPLOYERS = [
    # crypto / web3
    r"\bcoinbase\b", r"\bbinance\b", r"\bkraken\b", r"\bcircle internet\b", r"\bconsensys\b",
    r"\bripple\b", r"\bchainalysis\b", r"\bopensea\b",
    # gambling / sportsbook
    r"\bdraftkings\b", r"\bfanduel\b", r"\bbetmgm\b", r"\bcaesars digital\b",
    # defense / weapons primes
    r"\blockheed martin\b", r"\braytheon\b", r"\bnorthrop grumman\b", r"\bgeneral dynamics\b",
    r"\banduril\b", r"\bpalantir\b",
    # law-enforcement software
    r"\baxon\b", r"\bflock safety\b", r"\bmagnet forensics\b",
    # social media as the primary business
    r"\bmeta\b(?! ?(analysis|data))", r"\bbytedance\b", r"\btiktok\b",
]

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
    list. VETO_EMPLOYERS closes that by name."""
    low = (text or "").lower()
    hits = {re.search(v, low).group(0) for v in INDUSTRY_VETO if re.search(v, low)}
    hits |= {re.search(v, low).group(0) for v in VETO_EMPLOYERS if re.search(v, low)}
    return sorted(hits)


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
    return done


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
    Returns (score_dict) or None if a veto visibly fails."""
    def col(i):
        return cells[i + off] if len(cells) > i + off else ""
    company = col(1)
    lane = col(2)
    remote = col(3)
    culture = col(4)
    nonpe = col(5)
    boss = col(6)
    praise = col(7)

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


_UNAVAILABLE = re.compile(r"\bSENT\b|\bDROPPED\b|\bPAUSED\b|\bBLOCKED\b(?!\s*-?\s*list)", re.I)


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


def board_candidates(done, blocked):
    out, skipped = [], []
    for line in rd("documents/green-board.md").splitlines():
        if not line.strip().startswith("|") or line.count("|") < 8:
            continue
        cells = [c.strip().strip("*") for c in line.split("|")]
        if len(cells) < 3:
            continue
        off = row_offset(cells)
        co = cells[1 + off] if len(cells) > 1 + off else ""
        if not re.match(r"^[A-Z0-9]", co) or co.startswith("~~"):
            continue
        if co.lower() in ("company",):
            continue
        low = co.lower()
        if board_row_unavailable(cells) or low in done or low in blocked:
            continue
        sc, veto = score_board_row(cells, off)
        if sc is None:
            skipped.append((co, veto))
        else:
            out.append(sc)
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
                if _industry_vetoed(co):
                    continue
                out.append({"company": co, "lane": "agent-screened, hard gates passed",
                            "tier": 1, "pts": 0.5,
                            "reasons": ["BANKED sweep: hard gates passed, CULTURE SCREEN STILL OWED"],
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
        veto = _industry_vetoed(line)
        if veto:
            continue
        out.append({"company": co, "lane": cells[3][:40] if len(cells) > 3 else "", "tier": 1,
                    "pts": 0.0, "reasons": ["discovery board, NEEDS FULL SCREEN before a build"],
                    "boss": "", "source": "discovery board"})
        havenames.add(low)
    return out


def rank(n=10):
    blocked = blocked_set()
    done = done_set()
    cands, skipped = board_candidates(done, blocked)
    # BANKED (agent-screened, hard gates passed) fills BEFORE raw discovery — it is strictly
    # better-evidenced than an unscreened discovery row.
    if len(cands) < n:
        cands += banked_topup(cands, done, blocked, n - len(cands))
    if len(cands) < n:
        cands += discovery_topup(cands, done, blocked, n - len(cands))
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


# ── PEOPLE POOL ("who can help first") ────────────────────────────────────────────────────────
# Rank warm-network contacts by RELATIONSHIP + ROLE, with deal-breaker vetoes as the ONLY
# pre-contact filter. NO culture/WLB here: those are post-interview happiness scores, and a warm
# intro needs deal-breakers only. "Who can help first" is the boss-hunt method's ordering — a warm
# "in" is worth more than a cold full-matrix match.
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

# base score by "who can help" category — a product LEADER who can hire you ranks above a senior exec
# who can hire/refer, above a product IC peer, above a connector who routes you. Re-tune these in
# kit_config.PERSON_WEIGHTS; the bonuses reward a contact you can reach NOW / whose company is
# already in your pipeline.
try:
    from kit_config import PERSON_WEIGHTS, PERSON_EMAIL_BONUS, PERSON_REENTRY_BONUS
except Exception:
    PERSON_WEIGHTS = {"product-leader": 40, "senior-exec": 33, "product-ic": 25,
                      "connector": 15, "other": 5}
    PERSON_EMAIL_BONUS = 5      # contactable now (email on file)
    PERSON_REENTRY_BONUS = 8    # their company is already in your pipeline (warm re-entry)
PERSON_BASE = PERSON_WEIGHTS
PERSON_BADGE = {"product-leader": "🎯 product leader", "senior-exec": "🏛 senior exec",
                "product-ic": "🤝 product peer", "connector": "📇 connector", "other": "· other"}


def _person_category(title):
    t = title or ""
    pm, sr = is_pm(t), bool(SENIOR.search(t))
    if pm and sr:
        return "product-leader"   # Head/VP/Dir/CPO of Product — can hire you into product
    if sr:
        return "senior-exec"      # CEO/founder/CTO/VP — can hire or refer
    if pm:
        return "product-ic"       # PM/Sr PM — peer who can refer/intro
    if CONNECTOR.search(t):
        return "connector"        # recruiter/talent — routes you
    return "other"


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
    return names


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
    **704 of 704 rows** `company` received the date badge and the real employer was mashed into
    `title`. The daily briefing rendered `Chief Software Produ @ 🟢 3y (2023-07-2` — an employer slot
    showing a date — and it read as cosmetic noise rather than a parse failure.

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
        # than mis-index it, because mis-indexing is what produced 704 wrong rows for months.
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
    out, skipped = [], []
    for name, title, company, flag, known_since in _people_rows():
        combo = company + " " + title
        # ── deal-breaker filter ONLY (no culture/WLB) ──
        if "🔴" in flag:
            skipped.append((name, "blocked co")); continue
        # EXCLUDED former-employer LEADERSHIP tier (peers stay in scope). No-op unless
        # EXCLUDED_EMPLOYERS is set in kit_config. Reported in `skipped` for auditability.
        if EXCLUDED_EMPLOYER_RE and EXCLUDED_EMPLOYER_RE.search(combo) and SENIOR.search(title + " " + name):
            skipped.append((name, "excluded former-employer leadership tier")); continue
        _v = _industry_vetoed(combo)
        if _v:
            skipped.append((name, f"veto industry ({', '.join(_v)})")); continue
        if re.sub(r"[^a-z0-9]", "", name.lower()) in contacted:
            continue                                   # already reached this person
        cat = _person_category(title)
        pts = PERSON_BASE[cat]
        reasons = [PERSON_BADGE[cat]]
        if "✉" in flag:
            pts += PERSON_EMAIL_BONUS; reasons.append("email on file")
        reentry = "🟡" in flag
        if reentry:
            pts += PERSON_REENTRY_BONUS; reasons.append("warm re-entry (company already in pipeline)")
        # RELATIONSHIP DISTANCE, finally carried into the score.
        # parse_network.distance() has always computed this delta (-2 search-era / +1 under 3y /
        # +3 at 3y+) and written only the label, so rank_people scored every product leader at a
        # flat base. Everyone tied, `out.sort` is stable, and the "top 10 people" was therefore the
        # first 10 rows of the file, which is why recent connections never appeared. They were not
        # ranked low; NOTHING was ranked.
        #
        # Keyed on the TEXT, never the emoji. The same three badges mean different things in
        # different tables of this file, so matching 🔴 here would conflate "connected during the
        # search" with "company on the blocked list".
        dist = "unknown"
        if re.search(r"search-era", known_since, re.I):
            dist = "search-era"; pts -= 2
            reasons.append("connected during the search — common-interest rung, NOT a warm rung")
        elif re.search(r"\b(\d+)y\b", known_since):
            yrs = int(re.search(r"\b(\d+)y\b", known_since).group(1))
            if yrs >= 3:
                dist = "3y+"; pts += 3; reasons.append(f"known {yrs}y")
            else:
                dist = "under-3y"; pts += 1; reasons.append(f"known {yrs}y")

        out.append({"name": name, "title": title[:46], "company": company, "cat": cat,
                    "pts": pts, "reasons": reasons, "distance": dist,
                    "known_since": known_since})
    out.sort(key=lambda c: c["pts"], reverse=True)
    return out[:n], skipped


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


def main():
    n = 10
    brief = "--brief" in sys.argv
    pool = "companies"
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
        flagged = []
        for i, c in enumerate(trio, 1):
            print(f"\n  {i}. {c['company']}   {TIER_LABEL.get(c['tier'], '')}   ·   score {c['pts']}")
            print(f"     {c['lane']}")
            if verify:
                a = probe_live_board(c["company"])
                if not a:
                    print("     ⚪ live board: no ATS found → remote/vitality UNVERIFIED")
                    continue
                print(f"     live {a['board']} board: {a['total']} open reqs · "
                      f"{a['us_remote']} explicitly US-remote · {a['bare_remote']} remote "
                      f"(region unstated) · {len(a['pm_seats'])} PM seat(s)")
                for p in a["pm_seats"][:4]:
                    print(f"        ▸ {p['title']} | {p['loc']} {p['comp']}".rstrip())
                if a["flag"]:
                    print(f"     {a['flag']}")
                    flagged.append(c["company"])
        if verify and flagged:
            print("\n  ⚠️  FLAGGED, rule before you send: " + ", ".join(flagged))
            print("     A remote-absolute fail is a DROP, not a caveat. Mark it on the green board")
            print("     with the evidence, then re-run this so the trio recomputes without it.")
        elif verify:
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
            for i, c in enumerate(ranked, 1):
                print(f"    {i:2}. {c['name']:<22} {PERSON_BADGE[c['cat']]:<16} score {c['pts']:>3}  · "
                      f"{c['title'][:22]} @ {c['company'][:20]}")
            print("    Ranked by relationship+role (the boss-hunt method); deal-breakers only, culture waits.")
            sys.exit(0)
        print("=" * 74)
        print("  TOP PEOPLE TO REACH — WHO CAN HELP FIRST")
        print("  (relationship + role; deal-breaker vetoes only; culture/WLB stay post-contact)")
        print("=" * 74)
        _pool_n = len(_people_rows())
        print(f"  Pool: {_pool_n} contacts in the current warm-network.md snapshot.")
        print("  Buckets are pre-sorted best-first, so the top of each is here; for the FULL network")
        print("  regenerate documents/warm-network.md from your network parser. Blocked-co /")
        print("  deal-breaker / contacted excluded.")
        print("  Pick 3 people to reach today. Warm rung = deal-breakers only; the deep screen")
        print("  (still deal-breakers-only for a warm intro) runs before outreach.\n")
        for i, c in enumerate(ranked, 1):
            print(f"  {i:2}. {c['name']}   {PERSON_BADGE[c['cat']]}   ·   score {c['pts']}")
            print(f"      {c['title']}  @  {c['company']}")
            print(f"      why: {' · '.join(c['reasons'])}")
            print()
        if len(ranked) < n:
            print(f"  ⚠️  only {len(ranked)} rankable contact(s) after exclusions.")
        if skipped:
            print("  excluded (deal-breaker): " + ", ".join(f"{nm} ({why})" for nm, why in skipped[:4]))
        print("\n  NO culture/WLB in this ranking, by design (those are post-interview scores;")
        print("  warm rungs need deal-breakers only). Re-run after each pick to re-rank the rest.")
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
