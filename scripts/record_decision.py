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
NEGATION = re.compile(r"(?:\bdon'?t\b|\bdo not\b|\bnever\b|\bnot\b|\bno\b|\bskip\b|\bdrop\b|"
                      r"\bhold\b|\bpass\b|\blater\b|\bnot now\b|\bnot yet\b)", re.I)

BUILD_EXACT = {
    "build", "build it", "build this", "build now",
    "yes build", "yes, build", "yes build it", "approve build", "approved build",
}
SKIP_EXACT = {"skip", "skip it", "drop", "drop it", "hold", "pass", "no", "not now"}


def _norm(a: str) -> str:
    a = (a or "").strip().lower()
    a = re.sub(r"[^a-z0-9,\s']", " ", a)
    return re.sub(r"\s+", " ", a).strip()


def classify(answer: str) -> str:
    """BUILD only on an EXACT affirmative ruling. Ambiguity and negation are never BUILD."""
    if not answer:
        return "UNKNOWN"
    a = _norm(answer)
    if a in SKIP_EXACT:
        return "SKIP"
    if NEGATION.search(a):
        return "SKIP"  # a refusal, a conditional, or a deferral — never an authorization
    if a in BUILD_EXACT:
        return "BUILD"
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


def classify_answer(answer: str, *context: str) -> str:
    """Ruling for an answer, using the question/header as build CONTEXT. Exact rulings and negations
    are unchanged from classify(); only a free-text OTHER answer that AFFIRMS proceeding INSIDE a
    build-context question promotes to BUILD."""
    base = classify(answer)
    if base != "OTHER":
        return base
    a = _norm(answer)
    if NEGATION.search(a):
        return "SKIP"
    if _is_build_context(*context) and AFFIRM.search(a):
        return "BUILD"
    return "OTHER"


def extract_company(*texts: str) -> str:
    """Pull a company from a scorecard-style question, e.g. 'build ... for Acme?'.

    Best-effort only. The gate does NOT depend on parsing this correctly - it depends
    on a BUILD ruling existing at all. Company is recorded for the audit trail.

    Prepositions that usually precede a COMPANY (for/at/on) are tried before ones that often
    precede a PERSON (to/with), so "draft the note to Vic at Acme" resolves 'Acme', not 'Vic'.
    """
    for prep in (r"for|at|on", r"to|with"):
        for t in texts:
            if not t:
                continue
            m = re.search(
                r"\b(?:" + prep + r")\s+([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,2})", str(t))
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
