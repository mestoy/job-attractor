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
    from record_decision import LEDGER, NEGATION, _key, _norm, row_mac
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
    # SPLIT-ROOT FIX: the LEDGER import from record_decision honors CLAUDE_PROJECT_DIR, but this
    # resolver once computed its own root from the script location. When the two diverge the WRITER
    # (ledger) and the READER (board/queue corpus) point at different repos, so an explicit "build
    # the email to X" for an X on the CLAUDE_PROJECT_DIR board resolves to no company and authorizes
    # nothing. Derive the root the same way the ledger does.
    repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
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


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        text = str(payload.get("prompt") or payload.get("user_prompt") or "")
        if not text.strip():
            sys.exit(0)

        # SYSTEM-INJECTED TEXT IS NOT A RULING. Background task-notifications, scheduled prompts and
        # reminders must never be recorded as if you had said them — the value of this ledger is that
        # it holds YOUR words and nothing else. Only genuine user input counts.
        INJECTED = ("<task-notification>", "<system-reminder>", "<local-command-",
                    "[SYSTEM NOTIFICATION", "<command-name>", "Caveat: The messages below",
                    "This is an automated background-task event")
        if any(marker in text for marker in INJECTED):
            sys.exit(0)

        is_skip = bool(SKIP_INTENT.search(text))
        is_build = bool(BUILD_INTENT.search(text)) and not NEGATION.search(_norm(text))
        if not (is_skip or is_build):
            sys.exit(0)  # not a ruling — record nothing

        company = _company_from(text)
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
        row["mac"] = row_mac(row, _key())
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
