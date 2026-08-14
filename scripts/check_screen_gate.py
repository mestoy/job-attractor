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
    CONFIG_ERROR = None
except Exception as _e:  # standalone fallback: screens disabled
    # 🔴 THIS FALLBACK USED TO BE SILENT, AND ITS OWN COMMENT CLAIMED "it says so at runtime"
    # while nothing anywhere said so (found 2026-08-05). The comment 14 lines above warns that an
    # empty veto list "passes everything silently, which is the failure mode this whole gate exists
    # to prevent" — and this handler was producing precisely that.
    #
    # HOW IT FIRES, and it is not exotic. The import is ONE tuple, so a SINGLE name missing from
    # kit_config.py zeroes EVERY list at once: industry veto, blocked employers, politics, PE, and
    # the remote disqualifiers. A defense contractor then passes the mechanical screen clean.
    #
    # WHO IT HITS: not a fresh clone, which copies kit_config.example.py and has every name. It hits
    # a LONG-LIVED install. kit_config.py is gitignored, so no update ever adds a newly-required
    # name to it, and the config quietly falls behind the code that reads it. The occasion: a kit
    # deployed for weeks was missing NOT_A_COMPANY, so all 22 of its veto patterns were dead and
    # `doctor.py` still reported the veto list healthy, because doctor reads kit_config directly
    # and never asks whether THIS module's import of it succeeded.
    #
    # ⚖️ It stays a fallback rather than a hard exit, because standalone use is real. What changes
    # is that it is now LOUD, and CONFIG_ERROR lets doctor.py ask the question directly.
    CONFIG_ERROR = f"{type(_e).__name__}: {_e}"
    INDUSTRY_VETO = INDUSTRY_CLEARED = REMOTE_DISQUAL = REMOTE_CONFIRM = []
    POLITICS_DISQUAL = POLITICS_CLEAR = PE_FLAG = PE_CLEARED = []
    VETO_EMPLOYERS = NOT_A_COMPANY = []
    RULES_DOC = "documents/WORKFLOW-RULES.md"
    print(
        "🔴 check_screen_gate: kit_config did not load, so EVERY screening list is EMPTY and this\n"
        f"   gate now passes everything silently. Cause: {CONFIG_ERROR}\n"
        "   fix: your scripts/kit_config.py predates a name the code needs. Copy the missing name(s)\n"
        "   from scripts/kit_config.example.py into it (keep your own values for the rest).",
        file=sys.stderr,
    )


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
def derive_multiword(patterns):
    """The squashed multi-word veto keys derived from a list of employer-name patterns.

    ⚖️ FACTORED OUT OF THE MODULE BODY 2026-08-08 so a TEST CAN EXERCISE IT. It used to be an
    inline comprehension computed once at import, which meant a test could only cover it by
    patching `_MULTIWORD_VETO` to a literal — and a test that patches the value it claims to check
    is measuring the fixture, not the derivation. With a function, a test can hand in its OWN
    employer patterns and assert on what the REAL squash-and-filter produces.
    """
    _strip = lambda p: re.sub(r"\\b|\(\?[!=][^)]*\)|[\\^$*+?.()\[\]{}|]", " ", p)
    keys = sorted({_squash(_strip(p)) for p in patterns if " " in _strip(p).strip()})
    return [v for v in keys if len(v) >= 8]


_MULTIWORD_VETO = derive_multiword(VETO_EMPLOYERS)


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


# ── STRUCTURAL PARSE ARTIFACTS, shipped with the CODE and never with the config ───────────────
#
# ⛔ WHY THESE ARE NOT IN kit_config. `kit_config.py` is the recipient's parameterization layer and
# `backup.sh` copies it IF-ABSENT so a filled-in copy is never clobbered. That is correct for
# preferences, and WRONG for a fact about markdown parsing. Shipping these as config means an
# install that already has a `kit_config.py` never receives them, while any test asserting them
# arrives on schedule and fails.
#
# 📊 That is not hypothetical: it happened on 2026-08-10, hours after the patterns were first
# shipped as config. A partner install pulled the sync, ran the suite, and reported six failures,
# one per fragment: "Culture 3.1 reached the pool as an employer", and the same for WLB 3.8,
# Career 3.9, D&I 3.9, PE and 4.2. Their config was untouched by design, so they received the test
# and not the data it needed. **A preference is configurable; a parser fact is not.**
#
# WHAT THEY CATCH. Banked-candidate files are `·`-separated name lists, and a screen write-up with
# bolded sub-bullets ("**Culture:** Glassdoor 3.7, 66% recommend, WLB 3.8") gets split on the same
# separator, so a write-up's SUB-FIELDS are promoted to employers.
# ⚖️ ANCHORED ON A KNOWN SUB-RATING LABEL, never on the bare decimal, so a real company with a
# version-shaped name (Web 3.0 Labs) is untouched.
_STRUCTURAL_ARTIFACTS = [
    r"^(culture|career|wlb|work[- ]?life( balance)?|d&i|diversity|comp|compensation|leadership|"
    r"senior leadership|mgmt|management|benefits|rec|recommend)\b[\s:]*\d+(\.\d+)?$",
    r"^pe$", r"^\d+(\.\d+)?$",
]


def is_artifact(name):
    """True when a pool row is a page title, ATS boilerplate, or a write-up sub-field.

    Reads the configured list AND the structural one above, so a stale `kit_config.py` can weaken
    the owner's own additions but can never lose the parser facts.
    """
    low = (name or "").strip().lower()
    return any(re.search(p, low) for p in list(NOT_A_COMPANY) + _STRUCTURAL_ARTIFACTS)

def industry_resolution(name, text=""):
    """('vetoed'|'resolved'|'unknown', detail) — was this company's INDUSTRY ever established?

    ⛔ WHY `veto_hits` IS NOT ENOUGH. `veto_hits` matches industry words against the company NAME,
    so it only ever stops a company that spelled its industry into its own name. On one measured
    sweep, the handful of employers carrying "Bank", "Fintech" or "Defense" in the name were
    caught, while a large majority of financial firms — whose names say nothing about what they
    do — reached the banked pool of an operator whose FIRST hard filter was financial services.
    An empty `veto_hits` has always meant "no veto term appeared", never "this company was
    screened". This function is the difference between those two, said out loud.

    ⛔ A TIGHTER REGEX CANNOT FIX IT. On the same measurement, the overwhelming majority of
    employers were unresolvable from the name alone: household payments and AI names all read
    unknown, and a name like `PaymentVerse` fails the word boundary. Tightening one pattern only
    trades one failure for another. Industry needs real data, not name matching.

    ⚖️ THE RULING: an unknown industry **RANKS, carrying a visible mark**, and the veto moves to
    the SEND. Blocking everything unresolved would hold back nearly the whole pool and collapse it.

    ⚠️ SOURCED CACHE FIRST, NAME PATTERNS SECOND, and 'unknown' is a real answer rather than a
    failure to compute. Delegates to `contact_signals.segment_read`, which owns the tri-state, so
    there is ONE definition of "do we know what this company does".
    """
    hits = veto_hits(name, text)
    if hits:
        return "vetoed", ", ".join(hits)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import contact_signals
        seg, detail = contact_signals.segment_read(company=name or "", extra=text or "")
    except Exception as e:                                   # pragma: no cover - import guard
        # A missing cache must not silently upgrade an unknown company to resolved. Degrade to
        # unknown, which is the conservative side of this ruling: it marks and gates, it never
        # blocks the board.
        return "unknown", f"segment cache unreadable ({e.__class__.__name__})"
    # ⛔ OFF-SEGMENT IS *RESOLVED*, NOT VETOED. `segment_read`'s "off" means "outside the target
    # segments you configured", which is a thesis-fit answer. A deal-breaker is a different axis
    # entirely, and `veto_hits` above is the only thing that decides it. Mapping "off" to "vetoed"
    # made a company in an ordinary unrelated industry read identically to a defense contractor,
    # and would have suppressed perfectly sendable companies on a preference. The question THIS
    # function answers is "do we know what they do", and for an off-segment company that is yes.
    if seg in ("off", "relevant"):
        return "resolved", detail or ("off-segment" if seg == "off" else "in a target segment")
    return "unknown", None


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

    # G1b — THE INDUSTRY MUST BE STATED, not merely free of trigger words.
    # ⛔ G1 ABOVE ONLY FIRES WHEN A VETO WORD APPEARS, so a scorecard that never mentions the
    # industry at all sails through it. "No veto term appeared" is not "we screened the industry",
    # and treating them alike is how a run of financial firms reached a partner's banked pool
    # against an operator whose FIRST hard filter was financial services. Every one of them was
    # silent on the veto list; that silence was the whole problem.
    # ⚖️ THE VETO BELONGS HERE, AT THE SEND. An unresolved industry still RANKS and still carries
    # its board mark, because the great majority of employers are unresolvable from the name alone
    # and blocking them would collapse the pool. What it may not do is go out unscreened.
    if not _veto and not any(re.search(c, low) for c in INDUSTRY_CLEARED):
        missing.append("the INDUSTRY is never stated — no deal-breaker term appears, which is not "
                       "the same as a screen. Say what this company actually does and give the "
                       "verdict ('INDUSTRY: CLEARED — <what they do>'). A company can only reach "
                       "this gate unscreened by being silent, which is exactly how a bank passes")

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
