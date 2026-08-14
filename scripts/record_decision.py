#!/usr/bin/env python3
"""record_decision.py — PostToolUse hook on AskUserQuestion.

Appends YOUR ACTUAL ANSWER to the decision ledger.

WHY THIS EXISTS:
Every other gate in this kit is satisfied by evidence the ASSISTANT supplies. A
`--lacivita-check pass` flag is the assistant typing a word. `--praise-phrasing` proves a
string is in the body, not that you chose it. So an assistant can satisfy every gate
without you having ruled on anything, and the first symptom is a drafted email for a
company you never approved.

This hook is written by the HARNESS from your real response, not by the assistant.
That makes it the one piece of non-forgeable evidence in the system, and it is what
`check_preview.py` consults to enforce the BUILD GATE.

Fail-open by design: a hook crash must never block legitimate work. A MISSING ledger
entry blocks (that's the gate); a BROKEN hook does not.
"""
import hashlib
import hmac
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from kit_config import LEDGER_PATH, LEDGER_KEYFILE
except Exception:
    LEDGER_PATH = os.path.join("documents", "decision-ledger.jsonl")
    LEDGER_KEYFILE = "~/.jobsearch-ledger-key"

# PATH DIVERGENCE: this once defaulted to "." (cwd) while check_preview.py defaulted to the
# script's parent, so with CLAUDE_PROJECT_DIR unset the WRITER and the READER used different
# files — the ledger looked empty to the gate no matter what you ruled. Both now resolve to
# the project root the script lives in. Keep them identical.
_REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(_REPO, LEDGER_PATH)

# Key material lives OUTSIDE the project so it is never committed, never synced to anyone
# else's copy of this kit, and never sitting next to the ledger it authenticates.
KEYFILE = os.path.expanduser(LEDGER_KEYFILE)

# Fields covered by the MAC. Order is fixed so the digest is reproducible.
MAC_FIELDS = ("ts", "session", "question", "header", "answer", "ruling", "company", "source")


def _key() -> bytes:
    """Load (or create, 0600) the HMAC key. Created once, on the first recorded decision."""
    try:
        if os.path.exists(KEYFILE):
            with open(KEYFILE, "rb") as fh:
                k = fh.read().strip()
            if k:
                return k
        os.makedirs(os.path.dirname(KEYFILE), exist_ok=True)
        k = os.urandom(32).hex().encode()
        fd = os.open(KEYFILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(k)
        return k
    except Exception:
        return b""


def row_mac(row: dict, key: bytes) -> str:
    """Deterministic HMAC over the row's semantic fields (excludes 'mac' itself)."""
    if not key:
        return ""
    payload = json.dumps(
        {f: row.get(f, "") for f in MAC_FIELDS}, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

# BUILD is an EXACT-MATCH whitelist, never a regex over free text.
#
# REWRITTEN after a red-team found the regex version converted REFUSALS into AUTHORIZATIONS.
# The old rule was `SKIP and not BUILD -> SKIP; BUILD -> BUILD`, so any answer containing both
# words resolved to BUILD:
#     "don't build" -> BUILD          "do not build" -> BUILD
#     "Not yet, build next week" -> BUILD              "Go ahead and skip it" -> BUILD
#     "skip the email but build the resume" -> BUILD
# Each of those then got a VALID HMAC, so the ledger carried cryptographic proof of a decision
# the human never made — strictly worse than an unsigned forgery, because the audit trail
# corroborates it. Meanwhile genuine approvals ("yes", "Do it") classified as OTHER.
#
# Now: negation wins outright, and BUILD requires an exact match against a short literal set
# that the scorecard template emits as option labels. Paraphrase and free text NEVER classify
# as BUILD — they fall through to OTHER, which does not authorize anything.
# NARROWED, WITHOUT weakening the fail-closed property. Negation winning outright over the WHOLE
# answer fixed refusals-become-authorizations, but over-corrected: it also inverted real decisions
# whose VERDICT was affirmative and whose JUSTIFICATION merely contained a negative word, e.g.
#     "Keep it, X is not the mission"      -> recorded SKIP
#     "Build it, and negotiate Y later"    -> recorded SKIP
#     "Both in one pass"                   -> recorded SKIP  ("pass", the engineering sense)
# The affirmative opener was never consulted, because negation returned first.
#
# THE FIX: negation may only veto from the VERDICT CLAUSE (before the first comma). No comma means
# the whole answer is the verdict, so every red-teamed refusal ("don't build", "Not yet, build next
# week", "Go ahead and skip it", "skip the email but build the resume") behaves exactly as before.
# `pass` also lost its bare form; a bare "pass" answer is still caught verbatim by SKIP_EXACT.
NEGATION = re.compile(r"(?:\bdon'?t\b|\bdo not\b|\bnever\b|\bnot\b|\bno\b|\bskip\b|\bdrop\b|"
                      r"\bhold\b|\bpass on\b|\blater\b|\bnot now\b|\bnot yet\b)", re.I)

BUILD_EXACT = {
    "build", "build it", "build this", "build now",
    "yes build", "yes, build", "yes build it", "approve build", "approved build",
}
SKIP_EXACT = {"skip", "skip it", "drop", "drop it", "hold", "pass", "no", "not now"}

# The safety invariant the narrowing rests on, checked at import rather than in prose:
# if a BUILD label ever contained a negation token, moving the negation check could
# authorize something. It cannot, because it never can.
assert not any(NEGATION.search(_b) for _b in BUILD_EXACT), \
    "a BUILD_EXACT label contains a negation token — the clause-scoped check is unsafe"


def _norm(a: str) -> str:
    a = (a or "").strip().lower()
    a = re.sub(r"[^a-z0-9,\s']", " ", a)
    return re.sub(r"\s+", " ", a).strip()


def _verdict_clause(a: str) -> str:
    """The part of the answer carrying the RULING, not the reasoning.

    A ruling routinely names what did NOT disqualify a thing ("Keep it, X is not the mission"), so a
    negation in a trailing clause is evidence ABOUT the verdict, not the verdict itself.
    """
    return a.split(",", 1)[0].strip() or a


def classify(answer: str) -> str:
    """BUILD only on an EXACT affirmative ruling. Ambiguity and negation are never BUILD."""
    if not answer:
        return "UNKNOWN"
    a = _norm(answer)
    if a in SKIP_EXACT:
        return "SKIP"
    if a in BUILD_EXACT:
        return "BUILD"  # exact whole-string whitelist; provably contains no negation (see assert)
    if NEGATION.search(_verdict_clause(a)):
        return "SKIP"  # a refusal, a conditional, or a deferral — never an authorization
    return "OTHER"  # free text / paraphrase: recorded for audit, authorizes nothing


# ── BUILD BY AFFIRMATION-IN-CONTEXT ───────────────────────────────────────────────────────────
# classify() is an exact-match whitelist ON PURPOSE (a regex over a bare answer once turned refusals
# into authorizations). But that whitelist only knows the scorecard's option labels ("build", "yes,
# build"). A plain affirmation one step later — "yes, please proceed", picking an "Apple Mail draft"
# channel — is free text, so no BUILD row is written and both gates false-block work you plainly
# authorized. The fix reads the ANSWER together with the QUESTION as CONTEXT: a plain affirmation
# promotes to BUILD only when the QUESTION the assistant asked is itself a build/outreach step.
#   * NON-FORGEABLE: the RULING still comes from YOUR answer (harness-written); the assistant controls
#     only the CONTEXT. Any negation in the answer wins outright and the row is SKIP.
#   * NO OVER-MATCH: a bare "yes"/"ok" promotes only inside a build-context question. "Which company
#     next? -> yes" has no build context, so it stays OTHER and authorizes nothing.
BUILD_CONTEXT = re.compile(
    r"\b(?:build|draft|drafting|outreach|scorecard|boss[\s-]*match|praise\s*beat|"
    r"two[\s-]*stage|compose|apple\s*mail|mail\s*draft|gmail\s*draft|"
    r"send\s+(?:the\s+)?(?:email|note|outreach|draft|message)|"
    r"stage\s+(?:it|this|the\s+)?(?:email|outreach|draft|note)?)\b",
    re.I,
)
AFFIRM = re.compile(
    r"\b(?:yes|yep|yeah|yup|proceed|go\s+ahead|do\s+it|stage\s+it|build\s+it|"
    r"send\s+it|ship\s+it|approve|approved|draft\s+it|make\s+the\s+draft|"
    r"apple\s*mail|mail\s*draft|gmail\s*draft|please\s+proceed)\b",
    re.I,
)


def _is_build_context(*texts: str) -> bool:
    """Does the assistant-authored question/header frame this as a build/outreach step?"""
    return any(bool(t) and bool(BUILD_CONTEXT.search(str(t))) for t in texts)


# ── AN OPTION NUMBER IS A RULING (reported by a partner install, kit issue #15) ───────────────
#
# ⛔ THE DEFECT. `classify_answer` reads the ANSWER TEXT and never the SELECTED OPTION LABEL. So
# answering a scorecard picker with "#1" records `ruling: OTHER` and authorizes nothing, even though
# option 1 is labelled "Build it" and that exact label classifies as BUILD. Measured here:
#     'Build it (Recommended)'           -> BUILD
#     '#1'                               -> OTHER
#     '#1 but please research him first' -> OTHER
#
# ⚖️ WHY THIS IS WORSE THAN A PARSE BUG: it inverts the gate's purpose. HARD-INVARIANTS carries an
# explicit counter-rule, "NEVER make you repeat a decision to satisfy a mechanism. If a gate
# blocks an instruction you already gave plainly, the GATE is wrong, fix the gate." Answering by
# number is a normal thing to do, and operators do it. The failure is SILENT at the moment of the ruling
# and only surfaces a step later, at a gate that then names the wrong cause.
#
# ⛔ IT RESOLVES, IT NEVER INVENTS. The number must LEAD the answer and must index a real option on
# that question; anything else is left exactly as typed. And the appended free text is KEPT and
# classified alongside the label, so the strict negation veto still applies: "#1 but skip it" must
# not become a BUILD. An instruction appended to a choice MODIFIES the build; it does not withdraw
# one, but only the veto gets to decide that.
_OPTION_REF = re.compile(r"^\s*(?:option\s*)?#?\s*([1-9])\s*(?=$|[\s.,;:)\]-])", re.I)


def resolve_option_answer(answer, question):
    """Answer text with a leading option reference replaced by that option's LABEL.

    Returns the answer unchanged when there is no leading reference, no options, or the index does
    not exist. Pure and total: never raises, never guesses beyond the options actually present.
    """
    a = str(answer or "")
    m = _OPTION_REF.match(a)
    if not m:
        return a
    opts = (question or {}).get("options") or []
    idx = int(m.group(1)) - 1
    if not (0 <= idx < len(opts)):
        return a
    opt = opts[idx]
    label = str((opt or {}).get("label") or "").strip() if isinstance(opt, dict) else str(opt)
    if not label:
        return a
    rest = a[m.end():].strip()
    return f"{label} {rest}".strip() if rest else label


def classify_answer(answer: str, *context: str) -> str:
    """Ruling for an answer, using the question/header as build CONTEXT. Exact rulings and negations
    are unchanged from classify(); only a free-text OTHER answer that AFFIRMS proceeding INSIDE a
    build-context question promotes to BUILD."""
    base = classify(answer)
    if base != "OTHER":
        return base
    a = _norm(answer)
    # ── THE ASYMMETRY, AND IT IS DELIBERATE ───────────────────────────────────────────────────
    # Authorizing and refusing do not get the same evidence bar: a wrong BUILD puts an unapproved
    # message in front of a real person, while a wrong SKIP only mislabels the audit trail.
    #   BUILD promotion keeps the STRICT whole-string veto: ANY negation ANYWHERE blocks it.
    #   SKIP is decided from the VERDICT CLAUSE only, so a justification cannot invert a decision.
    # The veto is evaluated BEFORE the SKIP branch so it can never be bypassed by reordering.
    if _is_build_context(*context) and AFFIRM.search(a) and not NEGATION.search(a):
        return "BUILD"
    if NEGATION.search(_verdict_clause(a)):
        return "SKIP"
    return "OTHER"


def extract_company(*texts: str) -> str:
    """Pull a company from a scorecard-style question, e.g. 'build ... for Acme?'.

    Best-effort only. The gate does NOT depend on parsing this correctly - it depends
    on a BUILD ruling existing at all. Company is recorded for the audit trail.

    Prepositions that usually precede a COMPANY (for/at/on) are tried before ones that often
    precede a PERSON (to/with), so "draft the note to Vic at Acme" resolves 'Acme', not 'Vic'.
    """
    # ── KNOWN NAME FIRST, LONGEST MATCH WINS ─────────────────────────────────────────────────
    # The proper-noun heuristic below TRUNCATES any company whose name carries a lowercase
    # connector, because it requires every following word to be capitalized:
    #     "Build or skip for Pay with Spire?"        -> "Pay"       (stopped at "with")
    #     header "Pay with Spire"                    -> "Spire"     (started at the last capital)
    #     "Build or skip for Welcome to the Jungle?" -> "Welcome"   (stopped at "to")
    # Both halves of that first pair were recorded live against a real ruling.
    #
    # ⚠️ THIS IS A SAFETY FIX, NOT A CONVENIENCE ONE. `check_preview` binds authorization to a NAMED
    # company, so a truncated name does not merely look untidy: it scopes a ruling to a company the
    # human did not rule on. "Welcome" is not "Welcome to the Jungle". A stray match against a real
    # company of that shorter name is cross-company authorization leakage.
    #
    # ⛔ IT TIGHTENS, IT NEVER WIDENS. A name the pipeline ALREADY KNOWS is authoritative over a
    # guess, and a LONGER name matches strictly fewer things than the prefix it replaces. Where no
    # known name is present, behaviour is byte-for-byte what it was.
    #
    # ⚠️ THE RECOGNITION LIST IS POLLUTED, AND A LONGEST-MATCH SCAN EXPOSES IT. Names scraped from
    # markdown include entries that are not companies at all ("company", "remote", bare digits). The
    # OLD fallback never tripped on them by luck: its greedy multi-word windows meant a bare
    # "company" was never tested alone. A width-1 scan tests it, and a first draft of this scoped
    # "Which company should I screen next?" to a company literally named "company", which is the one
    # thing this edit may not do.
    #
    # The guard is POSITIONAL rather than a denylist, because a denylist rots as the list does: a
    # SINGLE-word known name only counts where a company actually sits, directly after a company
    # preposition or standing alone as the whole text. Multi-word known names need no guard; they
    # are too specific to collide.
    known = _known_companies()
    if known:
        for t in texts:
            s_txt = str(t or "")
            if not s_txt:
                continue
            best = ""
            # 6 words is well past the longest real name in the list and keeps the scan cheap.
            for width in range(6, 0, -1):
                pat = r"\b([A-Za-z][\w&.\-]*(?:\s+[\w&.\-]+){%d})" % (width - 1)
                for m in re.finditer(pat, s_txt):
                    cand = m.group(1).strip().rstrip(".,!?;:")
                    if cand.lower() not in known or len(cand) <= len(best):
                        continue
                    if width == 1:
                        before = s_txt[:m.start()].rstrip()
                        anchored = bool(re.search(r"\b(?:for|at|on|to|with)$", before, re.I))
                        if not (anchored or cand == s_txt.strip().rstrip(".,!?;:")):
                            continue
                    best = cand
            if best:
                return best

    for prep in (r"for|at|on", r"to|with"):
        for t in texts:
            if not t:
                continue
            # CONNECTOR-TOLERANT PROPER-NOUN RUN. Same truncation as above, for a company the
            # pipeline has NOT met yet, so the known-name pass cannot help it. Only a closed set of
            # lowercase joiners is allowed, and each must still be followed by a capitalized token,
            # so "for the team" and "for a minute" still resolve to nothing.
            m = re.search(
                r"\b(?i:" + prep + r")\s+([A-Z][\w&.\-]*"
                r"(?:(?:\s+(?:of|the|with|and|for|to|at|by|on|in|de|la))*"
                r"\s+[A-Z][\w&.\-]*){0,3})", str(t))
            if m:
                return m.group(1).strip().rstrip(".,!?;:")

    # LOWERCASE-BRAND FALLBACK. The pattern above is a proper-noun heuristic, and it silently
    # unscoped a real BUILD ruling for a company whose brand is spelled lowercase: "for <brand>"
    # matched nothing, the row recorded company:"", and the gate correctly refused to honour an
    # unscoped ruling, so a decision the human had plainly given blocked the next question.
    # Recognition-only, so ordinary words after a preposition still resolve to nothing.
    known = _known_companies()
    if known:
        for t in texts:
            for tok in re.findall(r"[A-Za-z][\w&.\-]*(?:\s+[\w&.\-]+){0,2}", str(t or "")):
                cand = tok.strip().rstrip(".,!?;:")
                if cand.lower() in known:
                    return cand
    return ""


def _known_companies() -> set:
    """Delegates to check_outreach.known_companies(), the single source for this list.

    Two copies of a recognition list drift, and a drifted list silently unscopes a BUILD ruling,
    which is the exact failure this path exists to prevent.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from check_outreach import known_companies
        return known_companies()
    except Exception:
        return set()


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    try:
        tool_input = payload.get("tool_input") or {}
        tool_response = payload.get("tool_response") or {}

        questions = tool_input.get("questions") or []
        # The harness returns the user's selections keyed by question text.
        answers = tool_response.get("answers") or tool_input.get("answers") or {}
        if isinstance(answers, str):
            try:
                answers = json.loads(answers)
            except Exception:
                answers = {}
        if not isinstance(answers, dict):
            answers = {}

        rows = []
        ts = datetime.now(timezone.utc).isoformat()
        for q in questions:
            if not isinstance(q, dict):
                continue
            qtext = str(q.get("question", ""))
            header = str(q.get("header", ""))
            answer = str(answers.get(qtext, "") or "")
            # Resolve "#1" to the label the assistant authored, BEFORE classifying. The label comes
            # from a known vocabulary; the free-text answer is the operator writing in their own
            # words and will never enumerate.
            _for_class = resolve_option_answer(answer, q)
            rows.append(
                {
                    "ts": ts,
                    "session": payload.get("session_id", ""),
                    "question": qtext,
                    "header": header,
                    "answer": answer,
                    "ruling": classify_answer(answer, qtext, header),
                    "company": extract_company(qtext, header, answer),
                    "source": "posttooluse-hook",
                }
            )

        if rows:
            key = _key()
            os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
            with open(LEDGER, "a", encoding="utf-8") as fh:
                for r in rows:
                    r["mac"] = row_mac(r, key)
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
