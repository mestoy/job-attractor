#!/usr/bin/env python3
"""rank_applications.py — deterministic prioritization of open-JD apply candidates.

WHY THIS EXISTS. When you have a stack of open job postings to weigh against each other, put the
prioritization to code instead of re-deriving a ranking by hand each time — a hand ranking drifts
toward whatever answer you already expect. This is a reusable, deterministic scorer: structured
per-candidate signals in, a ranked list with a per-dimension breakdown and a verdict out.

THE METHOD:
  1. skill_match (1-5)        — how tightly the JD's stated requirements map to your profile.
  2. package_appeal (1-5)     — how RARE/compelling your edge is for THAT role (a generic senior
                                req should score LOW even when fit is fine).
  3. odds (1-5)               — posting recency + applicant-pool competition. A booster, not an override.
  4. org size                 — under ~50 headcount = a PLUS; 50-150 neutral; >150 a mild minus. Never a gate.
  5. culture                  — Glassdoor + Indeed, normalized and WEIGHTED BY REVIEW COUNT; low
                                volume damps toward neutral and is marked low-confidence.
                                "insufficient reviews" is NOT "bad".
  6. instability PENALTY      — layoffs / reorgs / turnover / low job-security / leadership churn /
                                pay erosion / "chaotic"/"do not join". HEAVY: can DROP a candidate
                                below the apply bar EVEN AT STRONG FIT. Verdict "drop-on-instability".
                                Stage-risk (small + no reviews yet) is "unproven", NOT penalized.

WEIGHTING: skill_match + package_appeal dominate ("best fit regardless of odds"); odds is light;
culture is folded in; size is a small plus; instability/culture act as the harder-edged gate. Weights
live in kit_config.RANK_WEIGHTS — retune there, never in this file. The go/no-go bar is
kit_config.RANK_APPLY_BAR.

Usage:
    rank_applications.py --candidates cands.json      # JSON list in, ranked JSON out
    cat cands.json | rank_applications.py             # stdin also accepted
    rank_applications.py --candidates cands.json --table   # human-readable ranked table

Exit: 0 ok · 2 usage/no-candidates
Stdlib only. Deterministic: same input → same output, no clocks or randomness.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 🔧 PARAMETERIZED: every tunable below comes from kit_config, never a hardcoded number here. See
# kit_config's "SCORING WEIGHTS" section (RANK_*) to retune the method to your own strategy.
try:
    from kit_config import (
        RANK_WEIGHTS, RANK_APPLY_BAR, RANK_BORDERLINE_FLOOR,
        RANK_SIZE_SMALL_MAX, RANK_SIZE_MID_MAX, RANK_SIZE_BONUS_SMALL,
        RANK_SIZE_ADJ_MID, RANK_SIZE_MINUS_LARGE,
        RANK_CULTURE_NEUTRAL_5, RANK_CULTURE_FULL_CONF_REVIEWS, RANK_CULTURE_LOW_CONF_REVIEWS,
        RANK_INSTABILITY_BASE_PENALTY, RANK_INSTABILITY_PER_FLAG, RANK_INSTABILITY_MAX_PENALTY,
        RANK_JOB_SECURITY_FLOOR, RANK_INSTABILITY_FLAGS, RANK_INSTABILITY_NEGATORS,
        RANK_STAGE_RISK_MAX_HEADCOUNT, RANK_STAGE_RISK_MAX_REVIEWS,
    )
except Exception:
    RANK_WEIGHTS = {"skill": 0.40, "package": 0.35, "odds": 0.10, "culture": 0.15}
    RANK_APPLY_BAR = 80.0
    RANK_BORDERLINE_FLOOR = 65.0
    RANK_SIZE_SMALL_MAX = 50
    RANK_SIZE_MID_MAX = 150
    RANK_SIZE_BONUS_SMALL = 6.0
    RANK_SIZE_ADJ_MID = 0.0
    RANK_SIZE_MINUS_LARGE = -3.0
    RANK_CULTURE_NEUTRAL_5 = 3.0
    RANK_CULTURE_FULL_CONF_REVIEWS = 100
    RANK_CULTURE_LOW_CONF_REVIEWS = 30
    RANK_INSTABILITY_BASE_PENALTY = 30.0
    RANK_INSTABILITY_PER_FLAG = 8.0
    RANK_INSTABILITY_MAX_PENALTY = 55.0
    RANK_JOB_SECURITY_FLOOR = 3.0
    RANK_INSTABILITY_FLAGS = {
        "layoffs", "layoff", "reorg", "reorgs", "whiplash", "turnover", "leadership churn",
        "pay erosion", "pay freeze", "chaotic", "do not join", "down round", "funding trouble",
        "instability",
    }
    RANK_INSTABILITY_NEGATORS = {"no", "not", "without", "zero", "avoided", "averted", "never", "ended"}
    RANK_STAGE_RISK_MAX_HEADCOUNT = 60
    RANK_STAGE_RISK_MAX_REVIEWS = 15

W_SKILL = float(RANK_WEIGHTS.get("skill", 0.40))
W_PACKAGE = float(RANK_WEIGHTS.get("package", 0.35))
W_ODDS = float(RANK_WEIGHTS.get("odds", 0.10))
W_CULTURE = float(RANK_WEIGHTS.get("culture", 0.15))
assert abs((W_SKILL + W_PACKAGE + W_ODDS + W_CULTURE) - 1.0) < 1e-9, \
    "kit_config.RANK_WEIGHTS must sum to 1.0 (else the 0-100 base ceiling shifts under the fixed RANK_APPLY_BAR)"

APPLY_BAR = float(RANK_APPLY_BAR)
BORDERLINE_FLOOR = float(RANK_BORDERLINE_FLOOR)

SIZE_SMALL_MAX = RANK_SIZE_SMALL_MAX
SIZE_MID_MAX = RANK_SIZE_MID_MAX
SIZE_BONUS_SMALL = RANK_SIZE_BONUS_SMALL
SIZE_ADJ_MID = RANK_SIZE_ADJ_MID
SIZE_MINUS_LARGE = RANK_SIZE_MINUS_LARGE

CULTURE_NEUTRAL_5 = RANK_CULTURE_NEUTRAL_5
CULTURE_FULL_CONF_REVIEWS = RANK_CULTURE_FULL_CONF_REVIEWS
CULTURE_LOW_CONF_REVIEWS = RANK_CULTURE_LOW_CONF_REVIEWS

INSTABILITY_BASE_PENALTY = RANK_INSTABILITY_BASE_PENALTY
INSTABILITY_PER_FLAG = RANK_INSTABILITY_PER_FLAG
INSTABILITY_MAX_PENALTY = RANK_INSTABILITY_MAX_PENALTY
JOB_SECURITY_FLOOR = RANK_JOB_SECURITY_FLOOR

INSTABILITY_FLAGS = RANK_INSTABILITY_FLAGS
_NEGATORS = RANK_INSTABILITY_NEGATORS

STAGE_RISK_MAX_HEADCOUNT = RANK_STAGE_RISK_MAX_HEADCOUNT
STAGE_RISK_MAX_REVIEWS = RANK_STAGE_RISK_MAX_REVIEWS


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _norm_1_5(v):
    """Map a 1-5 dimension to 0..1. Values outside 1-5 are clamped, not rejected."""
    return (_clamp(float(v), 1.0, 5.0) - 1.0) / 4.0


def derive_odds(recency_days=None, applicant_pool=None):
    """Derive a 1-5 odds score from posting freshness + competition when an explicit odds is absent.

    Fresher posting → higher; smaller applicant pool → higher. Both are optional; whichever is given
    contributes. Returns a float in 1-5. Neutral (3.0) when nothing is provided.
    """
    parts = []
    if recency_days is not None:
        # <=7d ~ 5, 30d ~ 3, >=90d ~ 1 (linear between anchors).
        rd = _clamp(float(recency_days), 0.0, 90.0)
        parts.append(_clamp(5.0 - (rd / 90.0) * 4.0, 1.0, 5.0))
    if applicant_pool is not None:
        # <=25 applicants ~ 5, ~200 ~ 3, >=500 ~ 1.
        ap = _clamp(float(applicant_pool), 0.0, 500.0)
        parts.append(_clamp(5.0 - (ap / 500.0) * 4.0, 1.0, 5.0))
    if not parts:
        return 3.0
    return sum(parts) / len(parts)


def culture_score(glassdoor=None, indeed=None):
    """Return (culture_0_100, low_confidence, total_reviews).

    Normalizes Glassdoor+Indeed (0-5) into 0-100, weighting each platform by its own review count, then
    damps the result toward neutral by overall confidence (combined review volume). No reviews at all →
    neutral score, low_confidence=True (absence of data is neither good nor bad).
    """
    def _r(d):
        if not d:
            return (None, 0.0)
        return (d.get("score"), float(d.get("reviews") or 0.0))

    g_score, g_rev = _r(glassdoor)
    i_score, i_rev = _r(indeed)
    total_reviews = g_rev + i_rev

    if total_reviews <= 0 or (g_score is None and i_score is None):
        neutral_100 = (CULTURE_NEUTRAL_5 / 5.0) * 100.0
        return (neutral_100, True, 0.0)

    # Review-count-weighted average of the raw ratings (only platforms that actually have reviews).
    num = 0.0
    den = 0.0
    if g_score is not None and g_rev > 0:
        num += float(g_score) * g_rev
        den += g_rev
    if i_score is not None and i_rev > 0:
        num += float(i_score) * i_rev
        den += i_rev
    raw_5 = (num / den) if den else CULTURE_NEUTRAL_5

    confidence = _clamp(total_reviews / CULTURE_FULL_CONF_REVIEWS, 0.0, 1.0)
    damped_5 = CULTURE_NEUTRAL_5 + confidence * (raw_5 - CULTURE_NEUTRAL_5)
    culture_100 = _clamp(damped_5 / 5.0, 0.0, 1.0) * 100.0
    low_confidence = total_reviews < CULTURE_LOW_CONF_REVIEWS
    return (culture_100, low_confidence, total_reviews)


def size_adjustment(headcount):
    """Return the additive size bonus/minus. Small (<50) is a plus; big (>150) a mild minus."""
    if headcount is None:
        return SIZE_ADJ_MID
    h = float(headcount)
    if h < SIZE_SMALL_MAX:
        return SIZE_BONUS_SMALL
    if h <= SIZE_MID_MAX:
        return SIZE_ADJ_MID
    return SIZE_MINUS_LARGE


def _signal_fires(signal):
    """True if a free-text instability signal names a hard flag as a whole word/phrase, un-negated."""
    stem = re.sub(r"[-_]", " ", str(signal).strip().lower())
    if not stem:
        return False
    for k in INSTABILITY_FLAGS:
        for m in re.finditer(r"(?<!\w)" + re.escape(k) + r"(?!\w)", stem):
            # negation guard: a negator in the ±2-token window means the signal is POSITIVE
            # ("no layoffs" before, "reorg averted" after) — do not fire.
            before = stem[:m.start()].split()[-2:]
            after = stem[m.end():].split()[:2]
            if any(t in _NEGATORS for t in before + after):
                continue
            return True
    return False


def instability_assessment(flags=None, job_security=None):
    """Return (penalty, is_unstable, reasons).

    is_unstable is True when a hard flag is present OR the job-security sub-score is below the floor.
    penalty is the (positive) number of points to subtract; 0 when clean. Reasons list what fired.
    """
    flags = flags or []
    reasons = []
    hard = 0
    for f in flags:
        if _signal_fires(f):
            hard += 1
            reasons.append(f"flag: {str(f).strip().lower()}")

    low_jobsec = job_security is not None and float(job_security) < JOB_SECURITY_FLOOR
    if low_jobsec:
        reasons.append(f"job-security {float(job_security):.1f} < {JOB_SECURITY_FLOOR}")

    is_unstable = hard > 0 or low_jobsec
    if not is_unstable:
        return (0.0, False, reasons)

    # Base penalty once ANY instability is present; each ADDITIONAL hard flag stacks. Low job-security
    # alone = the base penalty (it TRIGGERS the drop but does not itself stack a per-flag increment).
    penalty = INSTABILITY_BASE_PENALTY + INSTABILITY_PER_FLAG * max(0, hard - 1)
    if low_jobsec and hard == 0:
        penalty = INSTABILITY_BASE_PENALTY
    penalty = _clamp(penalty, 0.0, INSTABILITY_MAX_PENALTY)
    return (penalty, True, reasons)


def is_stage_risk(headcount, total_reviews, is_unstable):
    """Early-stage uncertainty (small + too few reviews), and ONLY when no real instability fired."""
    if is_unstable:
        return False
    if headcount is None:
        return False
    return float(headcount) <= STAGE_RISK_MAX_HEADCOUNT and total_reviews <= STAGE_RISK_MAX_REVIEWS


def score_candidate(c, apply_instability=True):
    """Score one candidate dict → a result dict with breakdown + verdict.

    apply_instability=False disables the instability rule entirely (used only to PROVE the rule is
    load-bearing: a strong-fit unstable candidate must stop being dropped when the rule is off).
    """
    # Coerce absent OR explicit-null primary dimensions to the floor (1) and flag the gap, so a
    # missing assessment is not silently read as a genuine 1/5.
    incomplete = c.get("skill_match") is None or c.get("package_appeal") is None
    skill = c.get("skill_match") if c.get("skill_match") is not None else 1
    package = c.get("package_appeal") if c.get("package_appeal") is not None else 1
    if c.get("odds") is not None:
        odds_5 = _clamp(float(c["odds"]), 1.0, 5.0)
    else:
        odds_5 = derive_odds(c.get("recency_days"), c.get("applicant_pool"))

    skill_n = _norm_1_5(skill)
    package_n = _norm_1_5(package)
    odds_n = _norm_1_5(odds_5)
    culture_100, low_conf, total_reviews = culture_score(c.get("glassdoor"), c.get("indeed"))
    culture_n = culture_100 / 100.0

    base = 100.0 * (W_SKILL * skill_n + W_PACKAGE * package_n
                    + W_ODDS * odds_n + W_CULTURE * culture_n)
    size_adj = size_adjustment(c.get("headcount"))

    penalty, is_unstable, instab_reasons = instability_assessment(
        c.get("instability_signals"), c.get("job_security"))
    if not apply_instability:
        penalty, is_unstable, instab_reasons = 0.0, False, []

    stage_risk = is_stage_risk(c.get("headcount"), total_reviews, is_unstable)

    final = _clamp(base + size_adj - penalty, 0.0, 100.0)

    # Verdict, resolved in priority order. Stage-risk is NOT penalized, so a stage-risk company that
    # clears the bar reads "apply" and keeps only the "unproven/stage-risk" FLAG — no ranking
    # demotion. Below the bar it is "unproven-bet". Dysfunction still drops unconditionally.
    if is_unstable:
        verdict = "drop-on-instability"
    elif stage_risk and final < APPLY_BAR:
        verdict = "unproven-bet"
    elif final >= APPLY_BAR:
        verdict = "apply"
    else:
        verdict = "borderline"

    return {
        "company": c.get("company", ""),
        "role": c.get("role", ""),
        "score": round(final, 1),
        "verdict": verdict,
        "breakdown": {
            "base": round(base, 1),
            "norm": {"skill": round(skill_n, 3), "package": round(package_n, 3),
                     "odds": round(odds_n, 3), "culture": round(culture_n, 3)},
            "weighted": {
                "skill": round(100 * W_SKILL * skill_n, 1),
                "package": round(100 * W_PACKAGE * package_n, 1),
                "odds": round(100 * W_ODDS * odds_n, 1),
                "culture": round(100 * W_CULTURE * culture_n, 1),
            },
            "odds_5": round(odds_5, 2),
            "culture_100": round(culture_100, 1),
            "culture_low_confidence": low_conf,
            "culture_reviews": total_reviews,
            "size_adjustment": size_adj,
            "instability_penalty": round(penalty, 1),
            "instability_reasons": instab_reasons,
            "stage_risk": stage_risk,
        },
        "flags": _flags(low_conf, stage_risk, is_unstable, incomplete),
    }


def _flags(low_conf, stage_risk, is_unstable, incomplete=False):
    out = []
    if is_unstable:
        out.append("instability")
    if stage_risk:
        out.append("unproven/stage-risk")
    if low_conf:
        out.append("low-review-confidence")
    if incomplete:
        out.append("data-incomplete")
    return out


def rank(candidates, apply_instability=True):
    """Score all candidates and return them sorted best-first.

    Sort: apply-worthy verdicts ahead of drops, then by score desc, then company name for stability.
    """
    scored = [score_candidate(c, apply_instability=apply_instability) for c in candidates]
    verdict_rank = {"apply": 0, "unproven-bet": 1, "borderline": 2, "drop-on-instability": 3}
    scored.sort(key=lambda r: (verdict_rank.get(r["verdict"], 9), -r["score"], r["company"]))
    return scored


def _render_table(ranked):
    lines = []
    lines.append(f"{'#':>2}  {'SCORE':>5}  {'VERDICT':<20}  {'COMPANY':<22}  ROLE")
    lines.append("-" * 88)
    for i, r in enumerate(ranked, 1):
        bar = "✅" if r["score"] >= APPLY_BAR and r["verdict"] == "apply" else "  "
        lines.append(f"{i:>2}  {r['score']:>5.1f}  {r['verdict']:<20}  "
                     f"{r['company'][:22]:<22}  {r['role']} {bar}")
        b = r["breakdown"]
        w = b["weighted"]
        detail = (f"       skill {w['skill']} · pkg {w['package']} · odds {w['odds']} "
                  f"· culture {w['culture']} (raw {b['culture_100']}, {b['culture_reviews']:.0f} rev"
                  f"{', low-conf' if b['culture_low_confidence'] else ''}) "
                  f"· size {b['size_adjustment']:+} · instab -{b['instability_penalty']}")
        lines.append(detail)
        if b["instability_reasons"]:
            lines.append(f"         instability: {'; '.join(b['instability_reasons'])}")
    counts = {}
    for r in ranked:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    lines.append("-" * 88)
    lines.append("  " + " · ".join(f"{counts[v]} {v}" for v in
                 ("apply", "unproven-bet", "borderline", "drop-on-instability") if counts.get(v)))
    return "\n".join(lines)


def _load(args):
    raw = None
    if args.candidates:
        with open(args.candidates, encoding="utf-8") as fh:
            raw = fh.read()
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    if not raw or not raw.strip():
        return None
    data = json.loads(raw)
    if isinstance(data, dict) and "candidates" in data:
        data = data["candidates"]
    return data if isinstance(data, list) else None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--candidates", help="path to a JSON list of candidates (else read stdin)")
    p.add_argument("--table", action="store_true", help="human-readable ranked table instead of JSON")
    p.add_argument("--no-instability", action="store_true",
                   help="DISABLE the instability rule (diagnostic: proves the rule is load-bearing)")
    args = p.parse_args(argv)

    candidates = _load(args)
    if not candidates:
        print("no candidates supplied (JSON list on stdin or --candidates FILE)", file=sys.stderr)
        return 2
    ranked = rank(candidates, apply_instability=not args.no_instability)
    if args.table:
        print(_render_table(ranked))
    else:
        print(json.dumps(ranked, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
