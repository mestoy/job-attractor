#!/usr/bin/env python3
"""record_scorecard.py — mark WHICH company a scorecard was just presented for.

WHY THIS EXISTS (2026-07-21, three forced sends in one session):
`record_chat_ruling.py` reads your prompt in isolation, but a scorecard ruling is inherently a
REPLY: its subject lives in the question that was just asked, not in the answer. `workflow-checklist`
step 6 asks for a badge card ending in `👉 YOUR CALL:`, and the natural answers to that question —
"build", "draft", "let's build", "3,a", "A" — name no company, so `_company_from()` resolved to ""
and every one of them authorized nothing. The gate demanded the one phrasing the workflow does not
produce, so it got `--force`d three times in a session, and a gate that is always forced enforces
nothing while still making the log read as though a check ran.

THE FIX: the agent records WHICH company it just scorecarded. your typed build verb then
resolves against that pending row instead of against nothing.

WHAT THIS FILE IS AND IS NOT:
  • It is a HINT about context. It records the subject of a question.
  • It is NOT authorization and carries NO HMAC. It cannot promote itself.
  • A BUILD row is still written ONLY by the UserPromptSubmit hook, ONLY from your own typed
    words, and ONLY MAC-signed with the key stored outside the repo. That property is unchanged.

HONEST LIMIT, stated plainly: the agent writes this file, so the agent chooses the company name that
a later generic "build the email" will attach to. That is a real widening of what a non-specific
ruling can authorize. It is bounded on purpose:
  • ONE slot. A new scorecard overwrites the old one; pendings cannot be stacked.
  • EXPIRY (default 2h). A stale context cannot be cashed in later in the session.
  • VISIBLE PROVENANCE. Rows promoted this way carry `"via": "pending-scorecard"` plus the pending
    row's timestamp, so an audit can tell a directly-named ruling from a context-resolved one.
  • It never upgrades a NON-ruling. No build verb in your prompt means no row, as before.
The residual risk is that the agent names a company you was not actually shown. That risk
already exists upstream (the agent authors the scorecard too); this makes it auditable rather than
invisible.

Usage:
    python3 scripts/record_scorecard.py "Carrum Health"
    python3 scripts/record_scorecard.py --clear
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
PENDING = os.path.join(REPO, "documents", "pending-scorecard.json")
TTL_SECONDS = 2 * 60 * 60


def write(company: str) -> None:
    os.makedirs(os.path.dirname(PENDING), exist_ok=True)
    row = {
        "company": company.strip(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "note": "Scorecard presented; awaiting your build/skip ruling. NOT authorization.",
    }
    with open(PENDING, "w", encoding="utf-8") as fh:
        json.dump(row, fh, ensure_ascii=False, indent=2)
    print(f"pending scorecard recorded: {row['company']}")


def read():
    """Return (company, ts_iso) if a non-expired pending scorecard exists, else (None, None)."""
    try:
        with open(PENDING, encoding="utf-8") as fh:
            row = json.load(fh)
    except Exception:
        return None, None
    co = (row.get("company") or "").strip()
    ts = row.get("ts") or ""
    if not co or not ts:
        return None, None
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
    except Exception:
        return None, None
    if age < 0 or age > TTL_SECONDS:
        return None, None  # expired or clock-skewed: fail closed
    return co, ts


def clear() -> None:
    try:
        os.remove(PENDING)
        print("pending scorecard cleared")
    except FileNotFoundError:
        print("no pending scorecard")


USAGE = (
    "usage: record_scorecard.py [COMPANY | --clear]\n"
    "  (no args)   print the current pending scorecard, if any\n"
    "  COMPANY     record COMPANY as the scorecard's subject (a context HINT, not authorization)\n"
    "  --clear     clear the pending scorecard\n"
    "  -h, --help  show this message\n"
)


def main(argv) -> int:
    args = [a for a in argv if a.strip()]
    if not args:
        co, ts = read()
        print(f"pending: {co or '(none)'}" + (f"  (recorded {ts})" if ts else ""))
        return 0
    if args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    if args[0] == "--clear":
        clear()
        return 0
    # BUG-152: a flag is not a company. `record_scorecard.py --help` used to write {"company":
    # "--help"} into the file that gates whether a scorecard exists. Reject any leading-dash token
    # (no real employer name starts with "-") so a typo, a shell glob, or an unknown flag can never
    # land in the authorization record silently, and refuse an all-whitespace name.
    if args[0].startswith("-"):
        sys.stderr.write(f"record_scorecard.py: unknown option {args[0]!r}\n{USAGE}")
        return 2
    company = " ".join(args).strip()
    if not company:
        sys.stderr.write("record_scorecard.py: refusing to record an empty company name\n")
        return 2
    write(company)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
