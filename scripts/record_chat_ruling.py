#!/usr/bin/env python3
"""record_chat_ruling.py — UserPromptSubmit hook. Records a build/skip ruling you type in CHAT.

`record_decision.py` only fires on AskUserQuestion, so it captures rulings made by CLICKING an
option. When you approve a build in plain chat ("yes, build the email to Alex"), that is an explicit,
specific ruling — but without this hook no ledger row is written, and check_preview.py's BUILD gate
would block the very work you just authorized. This hook reads your actual words instead of forcing
you to re-issue the decision through a widget.

NON-FORGEABILITY: the prompt text arrives from the HARNESS on stdin, not from the agent — the same
property that makes the PostToolUse hook trustworthy. Rows are MAC-signed with the same key, so a
hand-written row still fails verification.

Wired in .claude/settings.json as a UserPromptSubmit hook. Always exits 0: this hook only OBSERVES,
it must never block you from typing.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    from record_decision import (LEDGER, NEGATION, _REPO, _append_unsigned, _key, _norm,
                                 _promotion_vetoed, key_error_message, row_mac)
    import ledger_keys as _lk
    import ledger_write as _lw
except Exception:
    sys.exit(0)  # observation-only: never break the prompt path

# An explicit ruling names the ACTION. Bare "yes"/"ok"/"go" is deliberately NOT enough — it could be
# answering any question. This must stay narrow: over-matching would manufacture authorizations.
BUILD_INTENT = re.compile(
    r"\b(?:build|draft|write|prep(?:are)?|stage|compose)\b[^.?!]{0,60}?"
    r"\b(?:email|outreach|note|message|letter|draft|it|one)\b"
    # "go ahead"/"proceed" only count PAIRED with a build object — never bare, so a lone
    # "go"/"yes"/"ok" still records nothing (over-matching would manufacture authorizations).
    r"|\b(?:go\s+ahead|proceed)\b[^.?!]{0,60}?"
    r"\b(?:build|draft|write|prep|stage|compose|send|email|outreach|note|message|letter)\b"
    r"|\byes,?\s*build\b|\bbuild\s+(?:it|the\s+email|the\s+outreach)\b"
    r"|\bstage\s+(?:it|the\s+(?:email|outreach|draft|note))\b"
    r"|\bsend\s+(?:it|the\s+(?:email|outreach|note|message))\b",
    re.I,
)
# BUG-775 (#379, 2026-10-28): ANOTHER SESSION'S MESSAGE IS NOT HIS WORDS EITHER. `<cross-session-message ...>` was missing from this
# list, so a peer's text was read as his typed prompt: 1,817 of the 2,144 typed-path ledger rows (108 BUILD, 1,673 SKIP) came from
# peer messages. The markers match ANYWHERE in the prompt, so a wrapper after a line of preamble does not slip past.
INJECTED = ("<task-notification>", "<system-reminder>", "<local-command-",
            "[SYSTEM NOTIFICATION", "<command-name>", "Caveat: The messages below",
            "This is an automated background-task event",
            "<cross-session-message", "</cross-session-message>", "Another Claude session sent a message",
            "from another Claude session", "[Cross-session delivery notice]", "[Cross-session idle notice]",
            # 2b round 1 (BUG-775): other user-role turns the harness injects. The PAIR stop hook QUOTES assistant prose back as a user turn,
            # so an assistant's "skip X" could record a SKIP and pause a contact. Matched case-insensitively, anywhere in the prompt.
            "Stop hook feedback:", "Stop hook blocking error", "hook blocking error from command", "[MESSAGE FROM NON-USER SOURCE",
            "NOT USER INPUT", "<command-message>", "<command-args>", "<bash-input>", "<bash-stdout>", "<bash-stderr>")
_INJECTED_LOW = tuple(m.lower() for m in INJECTED)
_PASTE_OPEN = re.compile(r"<pasted_content\b([^>]*)>", re.I)
_PASTE_ID = re.compile(r"""\bid\s*=\s*["']?([^"'\s>]+)""", re.I)




def is_injected(text):
    """True when the prompt is system-injected or another session's text, never his typed words (case-insensitive)."""
    low = (text or "").lower()
    return any(marker in low for marker in _INJECTED_LOW)


def his_words(text):
    """The prompt with pasted blocks removed: a ruling is read from what he typed, never from what he pasted.

    The harness gives a block's opening and closing tags the SAME random id so pasted text cannot fake an end, so a block closes only at a
    closing tag that carries the opening tag's id (a plain closing tag only when the opening tag has no id). Text inside a paste that
    looks like a closing tag is part of the paste. A block with no matching close drops everything after its opening tag (fail closed)."""
    out, pos = [], 0
    text = text or ""
    while True:
        m = _PASTE_OPEN.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos:m.start()])
        idm = _PASTE_ID.search(m.group(1) or "")
        if idm:
            close = re.compile(r"</pasted_content\b[^>]*(?<![\w-])" + re.escape(idm.group(1)) + r"(?![\w-])[^>]*>", re.I)
        else:
            close = re.compile(r"</pasted_content\s*>", re.I)
        cm = close.search(text, m.end())
        if not cm:
            break          # unclosed: drop the rest
        out.append(" ")
        pos = cm.end()
    return "".join(out)


def typed_is_build(text):
    """The typed-ruling BUILD decision, shared with the replay test: a genuine prompt, a build verb with an object, no negation, and
    none of the whole-answer vetoes the picker path uses (question, deferral, refusal, hedge, condition, second recipient, bulk)."""
    typed = his_words(text)
    return (not is_injected(text) and bool(BUILD_INTENT.search(typed)) and not NEGATION.search(_norm(typed))
            and not _promotion_vetoed(typed.strip(), _norm(typed), ()))


SKIP_INTENT = re.compile(
    r"\b(?:skip|drop|pass\s+on|don'?t\s+build|do\s+not\s+build|hold\s+off)\b", re.I
)

# Markdown table HEADER cells, which look precisely like a company name to a shape test but are
# ordinary English words. Any of these resolving to a "target" would let an unrelated sentence
# match it and manufacture a ruling for a company that does not exist.
TABLE_HEADINGS = {
    "company", "companies", "org", "employer", "name", "lane", "boss", "role", "title",
    "status", "badge", "score", "rank", "notes", "next", "stage", "source", "date", "why",
    "verdict", "action", "owner", "queue", "target", "product", "team", "link", "url",
}


def _known_targets():
    """(company, [aliases]) already vetted in your board/queue. Never invent a target from free text.

    Includes BOSS NAMES mapped to their company: people often refer to a target by the person's name
    ("build email to Alex") rather than the company, so a company-only resolver would miss the ruling.
    Resolving the boss is not inventing — the mapping comes from a row you already scorecarded.
    """
    targets = {}
    # SPLIT-ROOT FIX, second round (kit #121, 2026-09-15). The WRITER (ledger) and this READER
    # (board/queue corpus) must name the same install. Both once honored CLAUDE_PROJECT_DIR; the ledger
    # now resolves from the install the script lives in, and this reader read on from the session
    # folder, so a session opened elsewhere matched the OTHER folder's board: this install's company
    # resolved to nothing, and the other folder's company could scope a signed BUILD row here. Use the
    # ledger's own root, imported rather than recomputed so the two cannot drift again.
    repo = _REPO
    # Read the fuller durable corpus: a company found in discovery that has not yet been promoted to
    # the green board / prospect queue would otherwise resolve to "" and classify OTHER.
    for rel in ("documents/green-board.md", "documents/prospect_queue.md", "prospect_queue.md",
                "documents/discovery-board.md", "documents/outreach-queue.md"):
        p = os.path.join(repo, rel)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if not line.strip().startswith("|"):
                        continue
                    cells = [c.strip().strip("*~ ") for c in line.split("|")]
                    if len(cells) < 4:
                        continue
                    company = ""
                    for c in cells[1:4]:
                        c = c.strip("*~ ")
                        if c.lower() in TABLE_HEADINGS:
                            # A board file usually holds TWO tables, a numbered one
                            # (`| # | Company | …`) and an unnumbered radar one
                            # (`| Company | Lane | …`), so the literal word "Company" appears in
                            # a cell as a HEADER, and it passed every shape test here. That
                            # registered a target named "Company" whose alias "company" matches
                            # the ordinary English word, so "build the email to the company"
                            # resolved to it and wrote a signed BUILD row for a company that does
                            # not exist. A header is not a record.
                            continue
                        if 2 <= len(c) <= 34 and re.match(r"^[A-Z][\w&.\- ]+$", c):
                            company = c
                            break
                    if not company:
                        continue
                    aliases = {company.lower()}
                    # Boss names anywhere in the row (First Last, allowing a middle initial).
                    for m in re.finditer(r"\b([A-Z][a-z]+)\s+(?:[A-Z]\.\s+)?([A-Z][a-z]+)\b", line):
                        first, last = m.group(1), m.group(2)
                        if first in ("Remote", "Series", "Founder", "Product", "Green", "Board"):
                            continue
                        aliases.add(f"{first} {last}".lower())
                        aliases.add(first.lower())
                    targets.setdefault(company, set()).update(aliases)
        except Exception:
            pass
    # DURABLE STORE, ADDED ALONGSIDE. The loop above scans the leading cells for something that looks
    # like a company, which across a board's several table shapes lands on the right cell only
    # sometimes, and its `^[A-Z]` guard rejects a lowercase brand outright. The store names the
    # company column by header across every shape. Same widening intent as the resolver already has:
    # a company it does not know resolves to "" and classifies OTHER.
    #
    # ⛔ EXACT DISPLAY NAMES ONLY, NO ALIAS DERIVATION, and that restraint is the point. This
    # resolver GRANTS BUILD AUTHORIZATION, and the comments above record what happened the last time
    # its alias set widened: a bare English word became an alias for a company, so any prompt
    # containing that word plus a build verb wrote a signed, valid BUILD ruling for a company the
    # human never ruled on. Authorize strictly: a real company name is specific enough to be safe, a
    # name fragment is not.
    try:
        import state as _state
        # state.REPO is fixed at import from CLAUDE_PROJECT_DIR, so in a session opened elsewhere it is
        # another folder's store. That store must never scope a ruling here: read it only when it is
        # THIS install's store (narrower, never wider; the markdown boards above still resolve).
        if os.path.realpath(_state.REPO) != os.path.realpath(repo):
            raise RuntimeError("the state store belongs to another folder")
        for _rec in _state.from_source("company", "green-board"):
            _name = ((_rec.get("payload") or {}).get("name") or "").strip()
            if 2 <= len(_name) <= 34:
                targets.setdefault(_name, set()).add(_name.lower())
    except Exception:
        pass
    return targets


def _company_from(text):
    """Resolve to a company already known to the pipeline, else empty (authorizes nothing)."""
    low = text.lower()
    best, best_len = "", 0
    for company, aliases in _known_targets().items():
        for a in aliases:
            if len(a) < 3:
                continue
            if re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", low):
                if len(a) > best_len:
                    best, best_len = company, len(a)
    return best



# ── PORTED (2026-08-05): method parity with the main pipeline. ──
# Deliberately LOOSER than BUILD_INTENT and used for NOTHING but the lost-ruling warning below.
# It must never gate or authorize: over-matching here is harmless (a spurious warning), whereas
# over-matching BUILD_INTENT would manufacture authorizations, which is the one thing that must
# not happen. Bare verbs only — no object required — because a MISSING object is the exact defect
# it is meant to surface.
LOOSE_BUILD_HINT = re.compile(
    r"\b(?:build|draft|write|prep(?:are)?|pre-?fill|stage|compose|go\s+ahead|proceed)\b", re.I
)


# Words that must NEVER resolve to a company on their own, however they got capitalized in a board
# cell. Two families: ordinary English that shows up sentence-initially in prose columns, and
# generic business/pipeline vocabulary that appears in nearly every row. A bare first name has to
# clear this list AND be >= 4 chars to become an alias.
_ALIAS_STOPWORDS = {
    "the", "this", "that", "then", "they", "them", "there", "these", "those", "with", "from",
    "have", "has", "been", "was", "were", "will", "would", "could", "should", "also", "only",
    "just", "both", "each", "same", "than", "when", "what", "which", "while", "after", "before",
    "here", "into", "over", "under", "still", "note", "and", "but", "for", "not", "now", "new",
    # short function words: length is no longer a filter, so these must be named explicitly
    "our", "its", "his", "her", "who", "why", "how", "all", "any", "one", "two", "use", "see",
    "get", "let", "out", "off", "top", "key", "big", "low", "end", "via", "per", "yes", "was",
    "are", "has", "had", "did", "can", "may", "own", "few", "far", "due", "you", "him", "she",
    "the", "why", "not", "add", "set", "run", "way", "day", "job", "ask", "say", "put", "yet",
    # generic pipeline/business vocabulary
    "product", "board", "green", "remote", "series", "founder", "team", "health", "data", "open",
    "email", "outreach", "message", "draft", "build", "send", "sent", "role", "roles", "company",
    "boss", "culture", "radar", "live", "verified", "blocked", "screen", "screened", "target",
    "targets", "lane", "hiring", "manager", "director", "principal", "senior", "staff", "chief",
    "head", "vice", "president", "officer", "engineer", "engineering", "design", "growth",
}


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        text = str(payload.get("prompt") or payload.get("user_prompt") or "")
        if not text.strip():
            sys.exit(0)

        # SYSTEM-INJECTED TEXT AND OTHER SESSIONS' MESSAGES ARE NOT A RULING (see INJECTED above): only your own typed words count.
        if is_injected(text):
            sys.exit(0)

        is_skip = bool(SKIP_INTENT.search(his_words(text)))
        is_build = typed_is_build(text)
        if not (is_skip or is_build):
            sys.exit(0)  # not a ruling — record nothing

        company = _company_from(his_words(text))
        ruling = "SKIP" if is_skip else ("BUILD" if company else "OTHER")

        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session": payload.get("session_id", ""),
            "question": "(chat ruling)",
            "header": "chat",
            "answer": text.strip()[:400],
            "ruling": ruling,
            "company": company,
            "source": "userpromptsubmit-hook",
        }
        # The stored answer is cut at 400 characters; say so, and keep a hash of the whole prompt, outside the MAC field set.
        if len(text.strip()) > 400:
            import hashlib
            row["answer_truncated"] = True
            row["answer_sha256"] = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
        key = _key()
        if not key:
            # Security review L4 kept its property (no row ever carries an empty mac) and proxy 70 (2026-10-03)
            # added the record: the ruling is written UNSIGNED, with no mac field at all and the loud reason,
            # so no decision is lost silently and no gate ever counts it. Exit 1 shows the message without
            # blocking the prompt. The writer never creates a key: only `--migrate` does.
            _append_unsigned([row], key_error_message())
            print(key_error_message(), file=sys.stderr)
            sys.exit(1)
        _lw.append_signed_row(LEDGER, row, key, _lk.key_id(key))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
