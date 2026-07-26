#!/usr/bin/env python3
"""check_followups.py — are any armed boss-hunt follow-ups due or overdue?

Follow-up policy is WARM-ONLY: a cold boss who did not reply gets NO second touch; the
next action is a NEW target. Follow up only where you have a warm relationship, and when
you do, the channel is EMAIL (forward your original and add a line or two), not LinkedIn.
This scans outreach_log.md for follow-up due-dates (the standardized
`FOLLOWUP-DUE: YYYY-MM-DD` token, or legacy free-text "follow-up ... ~YYYY-MM-DD") and
flags any warm follow-up due today/earlier with no later logged second-touch or reply.

Usage:  scripts/check_followups.py           (defaults to today)
Exit:   0 = nothing overdue · 1 = overdue items printed
"""
import os, re, sys
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Where sends are logged. KIT DEVIATION from the upstream script: the upstream assumes
# outreach_log.md always exists and crashes without it, which is the state of every fresh
# install. Fall back to the review queue, then skip cleanly.
LOGS = ["outreach_log.md", "documents/outreach-queue-archive.md", "documents/outreach-queue.md"]

def scan(today=None, repo=None):
    """Pure scan: return (due, upcoming, undated) without printing or exiting.

    Exists so there is exactly ONE follow-up parser. `session_start.py` used to carry its own,
    much weaker regex for the session banner:

        FOLLOWUP-DUE:\\s*(\\d{4}-\\d{2}-\\d{2})[^\\n]*status:armed

    That reads ONE LINE. It has no completion detection, no `FOLLOWUP-DUE: none` handling and no
    warm-only awareness, so it disagreed with this file's verdict the moment a thread closed out:
    a row left at `status:armed` after the conversation had finished made the checker print 🟢
    while the banner opened every session with a phantom 🔴 against a thread where nothing was
    owed. Two parsers give two answers, and the wrong one is the one you read first each morning.
    A banner that is permanently red is a banner nobody reads.

    `repo` overrides the module-level REPO because `session_start.py` honors CLAUDE_PROJECT_DIR
    and this module does not; passing it keeps both reading the same file in a relocated checkout.
    Returns ([], [], []) when no log exists — a fresh install has nothing due, which is not an error.
    """
    today = today or date.today().isoformat()
    root = repo or REPO
    path = next((p for p in (os.path.join(root, f) for f in LOGS) if os.path.exists(p)), None)
    if path is None:
        return [], [], []
    src = open(path, encoding="utf-8", errors="ignore").read()
    blocks = re.split(r"(?=^## )", src, flags=re.M)
    due, upcoming, undated = [], [], []
    for b in blocks:
        head = b.splitlines()[0] if b.strip() else ""
        if not head.startswith("## "):
            continue
        # follow-up date: explicit token first, then legacy free-text near "follow-up"
        m = re.search(r"FOLLOWUP-DUE:\s*(\d{4}-\d{2}-\d{2})", b)
        if not m:
            # EXPLICIT DECLINE BEATS THE LEGACY GUESS. `FOLLOWUP-DUE: none` does not match the
            # token regex above, so a cold-rung block falls through to the free-text fallback
            # below — which then matches the very annotation explaining the decline:
            #     **Rung:** cold-boss | FOLLOWUP-DUE: none  <!-- no follow-up armed, warm-only
            #     policy 2026-07-23 -->
            # The fallback reads "follow-up armed, warm-only policy 2026-07-23" and arms a
            # follow-up for 2026-07-23. Documenting that a follow-up was DECLINED creates the
            # follow-up. Every correctly-annotated cold send becomes a permanent phantom 🔴, and a
            # check that is always red is a check nobody reads — which then masks the real ones.
            # The token being PRESENT with a non-date value is a human decision, whatever words
            # were used: "none", "n/a", "(cleared, nothing to follow up)". Matching a fixed
            # vocabulary here would just move the bug to the next phrasing someone types.
            if re.search(r"FOLLOWUP-DUE:", b):
                continue
            m = re.search(r"follow[- ]?up[^\n]*?~?\s*(\d{4}-\d{2}-\d{2})", b, re.I)
        if not m:
            # A SENT block with no parseable date used to be skipped SILENTLY, which is how
            # dozens of real outreaches went invisible and the tool reported a false 🟢 while a
            # whole follow-up wave was coming due. Surface them instead.
            if re.search(r"\b(sent|SENT)\b", b) and not re.search(
                r"(followed up|follow-up sent|✅\s*replied|\breplied\b|reply received)", b, re.I
            ):
                _h = re.sub(r"^\s*#*\s*", "", head)[:48]
                undated.append(_h)
            continue
        dd = m.group(1)
        cm = re.search(r"·\s*([^·(]+?)\s*(?:\(|·)", head)
        if not cm:
            # Header format "## 2026-01-15 — Acme Corp (Jane Doe, CPO) — boss-hunt" has no '·'
            # separator, so this used to fall through to head[:40] and print the whole header
            # as the company name.
            cm = re.search(r"^\s*#*\s*\d{4}-\d{2}-\d{2}\s*[—–-]\s*([^(—–\n]+)", head)
        comp = cm.group(1).strip() if cm else head[:40].strip()
        # done ONLY if the block records a COMPLETED second touch / an actual reply.
        # BUG: bare `REPLY` was unanchored + case-insensitive, so the standard
        # arming phrase "follow-up = forward the email ~1 wk if no reply" MATCHED and silently
        # marked the block done. That disarmed 14 of 21 dated blocks — a false green on live
        # follow-ups. Require an affirmative completion marker, never the word "reply" alone.
        done = re.search(
            r"(followed up|follow-up sent|follow-up done|LinkedIn (msg|message|note) sent"
            r"|✅\s*replied|\breplied\b|reply received|responded|status:\s*(done|replied|closed))",
            b, re.I,
        )
        # "if no reply" / "if no response" are ARMING language, not completion. Never let them close.
        if done and re.fullmatch(r"(?i)responded|replied", done.group(1) or ""):
            ctx = b[max(0, done.start() - 24):done.end()]
            if re.search(r"if\s+no\s+(reply|response)", ctx, re.I):
                done = None
        if done:
            continue
        (due if dd <= today else upcoming).append((dd, comp.strip()))
    due.sort(); upcoming.sort()
    return due, upcoming, undated


def main():
    today = date.today().isoformat()
    if not any(os.path.exists(os.path.join(REPO, f)) for f in LOGS):
        print(f"⚠️  no outreach log found (looked for: {', '.join(LOGS)}) — nothing to check yet.")
        sys.exit(0)
    due, upcoming, undated = scan(today)
    if due:
        print(f"🔴 {len(due)} follow-up(s) DUE/OVERDUE (as of {today}):")
        for dd, c in due:
            print(f"   • {dd}  {c}  → if WARM: forward your original email (add a line or two). A cold non-reply gets a NEW target, not a chase.")
    else:
        print(f"🟢 no follow-ups overdue (as of {today})")
    if upcoming:
        print(f"   ⏳ {len(upcoming)} upcoming: " + ", ".join(f"{c} ({dd})" for dd, c in upcoming[:12]))
        if len(upcoming) > 12:
            print(f"      (+{len(upcoming) - 12} more)")
    if undated:
        print(f"\n🟠 {len(undated)} SENT outreach(es) with NO follow-up date.")
        print("   For a WARM contact, arm an email follow-up: FOLLOWUP-DUE: YYYY-MM-DD | channel:email | status:armed")
        print("   A COLD non-reply needs no follow-up. Reach a NEW person instead.")
        for h in undated[:12]:
            print(f"   • {h}")
        if len(undated) > 12:
            print(f"   (+{len(undated) - 12} more)")
    # Exit non-zero on undated sends too: a silent skip is what produced the false green.
    sys.exit(1 if (due or undated) else 0)

if __name__ == "__main__":
    main()
