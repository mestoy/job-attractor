#!/usr/bin/env python3
"""check_screen_gate.py — is this candidate DECISION-READY, or still a task list?

Enforces "surface only screen-certified candidates": a boss-hunt candidate is not shown to
you unless its scorecard/queue block carries EVIDENCE that every screen layer ran. It checks
that the evidence is PRESENT, not whether the judgment was right (culture-fit / leadership
read stay human). A FAIL means: close the gap first, then surface — so you only ever choose
SEND/DROP/RADAR, never a verify-list.

The screening term lists live in kit_config.py. Edit them to YOUR deal-breakers; do not blank
them, because an empty list passes everything silently instead of failing loudly.

Usage:  scripts/check_screen_gate.py <scorecard.txt>     (or: - for stdin)
Exit:   0 = decision-ready · 1 = gaps (printed) · 2 = usage
"""
import sys, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# label -> regexes; a layer passes if ANY of its cues appear in the block
LAYERS = {
    "dedup verdict":        [r"dedup", r"check_dup", r"🟢\s*NEW", r"already[- ]seen"],
    "blocked-list checked": [r"blocked", r"not on the blocked", r"blocked-list"],
    "remote (with source)": [r"remote", r"work from anywhere", r"us-remote"],
    "travel cadence":       [r"travel", r"offsite", r"no[- ]travel", r"onsite"],
    "politics screen":      [r"politic", r"progressive", r"apolitical", r"right[- ]lean"],
    "Glassdoor/culture":    [r"glassdoor", r"culture", r"reviews", r"leadership"],
    "live/radar tag":       [r"\bradar\b", r"\blive\b", r"\bsend\b", r"\bdrop\b", r"greenfield"],
}
# remote must cite a SOURCE, not just say "remote" — require a source cue nearby
REMOTE_SOURCE = [r"careers", r"\bats\b", r"posting", r"job\b", r"http", r"greenhouse",
                 r"ashby", r"lever", r"job desc", r"jd\b", r"listing", r"verified"]
# culture must be the DEEP screen, not a headline rating — require a sub-rating/trend/thin marker
CULTURE_DEEP = [r"wlb", r"work[- ]life", r"sub[- ]rating", r"senior leadership", r"%\s*recommend",
                r"ceo approval", r"verbatim", r'"', r"trend", r"trajectory", r"headcount",
                r"restructure", r"unproven", r"too thin", r"insufficient", r"repvue", r"blind"]

# The screening term lists below come from kit_config.py so this file stays generic. They
# ship POPULATED with a working example set, and they are meant to be edited to YOUR
# deal-breakers — NOT blanked. An empty veto list does not screen nothing loudly; it passes
# everything silently, which is the failure mode this whole gate exists to prevent.
#
# G1 — deal-breaker INDUSTRY veto: a NEW company has no mechanical industry screen (dedup only
# knows the ones you already blocked). FAIL on a veto term unless the block carries an explicit
# "INDUSTRY: CLEARED" verdict, so silence is itself a failure.
# G5 — remote/politics gates must reflect the VERDICT, not merely mention the topic.
# Ownership — a PE-ownership signal must be adjudicated, not just mentioned.
try:
    from kit_config import (INDUSTRY_VETO, INDUSTRY_CLEARED, REMOTE_DISQUAL, REMOTE_CONFIRM,
                            POLITICS_DISQUAL, POLITICS_CLEAR, PE_FLAG, PE_CLEARED, RULES_DOC,
                            VETO_EMPLOYERS, NOT_A_COMPANY)
except Exception:  # standalone fallback: screens disabled, and it says so at runtime
    INDUSTRY_VETO = INDUSTRY_CLEARED = REMOTE_DISQUAL = REMOTE_CONFIRM = []
    POLITICS_DISQUAL = POLITICS_CLEAR = PE_FLAG = PE_CLEARED = []
    VETO_EMPLOYERS = NOT_A_COMPANY = []
    RULES_DOC = "documents/WORKFLOW-RULES.md"


def _squash(s):
    """Lowercase and drop everything that is not a letter or digit."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# Multi-word veto names, PRE-SQUASHED. A curated list can only catch the spelling someone typed,
# and scrapers do not preserve spacing: a veto list carried a two-word law-enforcement vendor while
# a sweep stored the same name with the space dropped, so an explicitly blocked company sat in the
# passes list on a whitespace difference alone.
#
# ⚠️ SCOPED TO MULTI-WORD NAMES ON PURPOSE. Squashing discards word boundaries, so applying it to a
# single-word pattern would make `\bcircle\b` match "CircleCI". Spacing variance is only a failure
# mode for names that HAVE a space, so only those are squashed.
_MULTIWORD_VETO = sorted({
    _squash(re.sub(r"\\b|\(\?[!=][^)]*\)|[\\^$*+?.()\[\]{}|]", " ", p))
    for p in VETO_EMPLOYERS
    if " " in re.sub(r"\\b|\(\?[!=][^)]*\)|[\\^$*+?.()\[\]{}|]", " ", p).strip()
})
_MULTIWORD_VETO = [v for v in _MULTIWORD_VETO if len(v) >= 8]


def veto_hits(name, text=""):
    """Every veto term matching a company NAME (and optional descriptive TEXT).

    Three passes, because each catches what the others structurally cannot:
      1. INDUSTRY_VETO over name+text — catches a company that DESCRIBES itself ("defense")
      2. VETO_EMPLOYERS over name+text — catches a company that is merely NAMED
      3. squashed multi-word — catches a named company whose spacing a scraper dropped

    Returns a sorted list of the matched terms. Empty means no veto fired; it NEVER means
    "screened". A veto list is a floor under the per-company screen, never a substitute for it.
    """
    low = f"{name or ''} {text or ''}".lower()
    hits = {re.search(v, low).group(0) for v in INDUSTRY_VETO if re.search(v, low)}
    hits |= {re.search(v, low).group(0) for v in VETO_EMPLOYERS if re.search(v, low)}
    squashed = _squash(f"{name or ''} {text or ''}")
    hits |= {v for v in _MULTIWORD_VETO if v in squashed}
    return sorted(hits)


def is_artifact(name):
    """True when a pool row is a page title or ATS boilerplate rather than a company."""
    low = (name or "").strip().lower()
    return any(re.search(p, low) for p in NOT_A_COMPANY)

def main():
    if len(sys.argv) < 2:
        print("usage: check_screen_gate.py <scorecard.txt|->"); sys.exit(2)
    text = sys.stdin.read() if sys.argv[1] == "-" else open(sys.argv[1], encoding="utf-8", errors="ignore").read()
    low = text.lower()
    missing = []
    for label, cues in LAYERS.items():
        if not any(re.search(c, low) for c in cues):
            missing.append(label)
        elif label == "remote (with source)" and not any(re.search(c, low) for c in REMOTE_SOURCE):
            missing.append("remote decision has no cited source (careers/ATS/posting)")
        elif label == "Glassdoor/culture" and not any(re.search(c, low) for c in CULTURE_DEEP):
            missing.append("culture is not the DEEP screen — needs sub-ratings (WLB/Senior Leadership/%rec), verbatim reviews, and a TREND read; a headline rating is not a screen")

    # G1 — industry veto: a deal-breaker industry term with no explicit CLEARED verdict = FAIL
    _veto = sorted({re.search(v, low).group(0) for v in INDUSTRY_VETO if re.search(v, low)})
    if _veto and not any(re.search(c, low) for c in INDUSTRY_CLEARED):
        missing.append(f"deal-breaker INDUSTRY term(s) present {_veto} with no 'INDUSTRY: CLEARED' verdict — screen the industry and state the verdict (see INDUSTRY_VETO in kit_config.py)")

    # G5 — remote/politics must reflect the VERDICT, not merely mention the topic
    if any(re.search(d, low) for d in REMOTE_DISQUAL) and not any(re.search(c, low) for c in REMOTE_CONFIRM):
        missing.append("remote layer names a DISQUALIFYING arrangement (hybrid/RTO/relocation/in-office/fixed-tz) with no offsetting remote-confirmed verdict — if remote is one of your hard filters, this is a FAIL, not a mention")
    if any(re.search(d, low) for d in POLITICS_DISQUAL) and not any(re.search(c, low) for c in POLITICS_CLEAR):
        missing.append("politics layer names a disqualifying signal with no offsetting clearing verdict — if political alignment is one of your hard filters, this is a FAIL, not a topic to note")

    # PE-owned default deal-breaker: a PE-ownership signal must be adjudicated, not just mentioned
    _pe = sorted({re.search(v, low).group(0) for v in PE_FLAG if re.search(v, low)})
    if _pe and not any(re.search(c, low) for c in PE_CLEARED):
        missing.append(f"PE-OWNERSHIP signal present {_pe} with no adjudication — majority PE ownership is a DEFAULT deal-breaker (margin extraction tends to produce leadership churn and layoffs). State ownership plus a verdict: bootstrapped/VC-backed is fine; majority-PE/buyout is a default pass. See PE_FLAG in kit_config.py")

    if missing:
        print("🔴 NOT decision-ready — screen gaps (close before surfacing):")
        for m in missing:
            print(f"   ❌ {m}")
        print("   → resolve these so the human chooses SEND/DROP/RADAR, not a verify-list.")
        sys.exit(1)
    print("🟢 decision-ready — all screen layers have evidence present.")
    print("   (evidence-presence only; culture/leadership/politics judgments stay human)")
    sys.exit(0)

if __name__ == "__main__":
    main()
