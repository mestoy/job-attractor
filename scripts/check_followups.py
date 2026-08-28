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

REPO = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Where sends are logged. KIT DEVIATION from the upstream script: the upstream assumes
# outreach_log.md always exists and crashes without it, which is the state of every fresh
# install. Fall back to the review queue, then skip cleanly.
LOGS = ["outreach_log.md", "documents/outreach-queue-archive.md", "documents/outreach-queue.md"]

# ── "IS THIS THREAD DONE?" — ONE detector, three callers ──────────────────────────────────────
# EXTRACTED from the middle of scan(), where it was an inline regex with one reader.
# `pair_brief.open_inbound` needs the SAME question answered ("does anybody still owe an answer
# here?"), and hand-rolling a second copy is a defect this pipeline has already paid for: a private
# follow-up regex in session_start opened every session with a phantom 🔴 on a thread that had
# closed out end to end.
#
# ⚠️ The bare word `reply` is deliberately NOT a completion marker. It was, once, and the standard
# arming phrase "follow-up ~1 wk if no reply" matched it and silently closed 14 of 21 dated blocks.
# Require an affirmative completion marker, never the word alone.
_COMPLETED = re.compile(
    r"(followed up|follow-up sent|follow-up done|LinkedIn (msg|message|note) sent"
    r"|✅\s*replied|\breplied\b|reply received|responded|status:\s*(done|replied|closed)"
    r"|nothing is owed|closed out|conversion complete|handed (me )?off"
    # the closure wording actually used in correspondence-log thread headers. "resolved" is
    # accepted ONLY with a ruling date — a bare "resolved" also matches hedges like "LIKELY
    # RESOLVED (check SMS first)", which is a to-do, not a closure.
    r"|no reply owed|not reply[- ]?owed|✅\s*closed|resolved\s+\d{4}-\d{2}-\d{2})",
    re.I,
)


def is_completed(block):
    """Does this log block record a COMPLETED outcome, so nothing is owed on it?

    Returns the matched marker (truthy) or None. Callers: scan() below, and
    pair_brief.open_inbound, which asks the same question of the correspondence log.

    "if no reply" / "if no response" is ARMING language, not completion, and it is stripped here
    rather than at the call site so every caller inherits the correction.
    """
    m = _COMPLETED.search(block or "")
    if m and re.fullmatch(r"(?i)responded|replied", m.group(1) or ""):
        ctx = block[max(0, m.start() - 24):m.end()]
        if re.search(r"if\s+no\s+(reply|response)", ctx, re.I):
            return None
    return m


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
        # done ONLY if the block records a COMPLETED second touch / an actual reply. The detector
        # (and the "if no reply is ARMING language" correction) live in is_completed() above, so
        # pair_brief asks the same question of the same rules instead of growing a second copy.
        if is_completed(b):
            continue
        (due if dd <= today else upcoming).append((dd, comp.strip()))
    due.sort(); upcoming.sort()
    return due, upcoming, undated



# ── PORTED (2026-08-05): method parity with the main pipeline. ──
# WHICH RUNGS ARM A FOLLOW-UP. This is the POLICY, and it is now empty.
#
# RETIRED 2026-07-27 (you): "Kuya Andy prefers to make the initial contact, then move on.
# Please make the change." Follow-ups that chase silence are retired at every rung, warm included.
# The prior rule (2026-07-23) was warm-only; this supersedes it. Primary source, Boss Hunting Bible:
# p.9 "Generally, I'm not much for following up" · p.11 "You will benefit much more from reaching
# out to new people than chasing individuals who are either not getting back to you" + spend 90% of
# your time on initial communication.
#
# STILL ALLOWED, because none of them chases silence: a REPLY to someone who answered, a THANK-YOU,
# and the PERSON PIVOT (a new initial contact to someone else at the same company — Andy's own
# recommendation, mechanized as mail-draft.sh --next-target). A deliberate bump also remains
# possible by passing an explicit date; it just never arms on its own.
ARMS_FOLLOWUP = ()


# WHICH RUNGS ARE WARM. This is a FACT about the ladder, not a policy about follow-ups. It is
# pinned equal to check_outreach.WARM_RUNGS by tests/test_groupD_send.py:1179, and that copy has a
# SECOND consumer (check_outreach.py:671, signature-block shape). Do not empty it to change a
# follow-up rule — the two questions were conflated in one constant and only one of them moved.
WARM_RUNGS = ("warm", "referred", "event", "off-ladder")


def _block_rung(block):
    """Rung recorded on an outreach_log block, lowercased, or None if absent.

    Only ~25 of 151 blocks carry a `**Rung:**` token (it post-dates most of the log), so callers
    must treat None as UNKNOWN and fall back to the conservative branch, never to a default.
    """
    m = re.search(r"\*\*Rung:\*\*\s*([a-z-]+)", block, re.I)
    rung = (m.group(1).strip().lower() if m else "")
    return rung or None


def arm_undated(dry_run=False):
    """Back-fill `FOLLOWUP-DUE:` on SENT blocks that have no date — WARM RUNGS ONLY.

    Why this exists (2026-07-20). The checker was upgraded to SURFACE undated sends rather than
    skip them silently, which turned an invisible problem into a visible one: 64 real outreaches
    with no armed second touch. Surfacing is not fixing. The date is derivable from the send date,
    and 64 hand-edits is exactly the kind of task that does not get done.

    ⚖️ NARROWED 2026-07-23 (you): *"Kuya Andy isn't a fan of following up, so I will only
    follow up with folks I have a warm relationship with."* This function used to arm EVERY sent
    block, which manufactured a chase backlog Andy explicitly argues against. Boss Hunting Bible
    p.9, scenario 8: *"Generally, I'm not much for following up"*, and p.10: *"You will benefit
    much more from reaching out to new people than chasing individuals who are either not getting
    back to you... spend 90% of your time... sending them your initial communication."* A cold
    boss who did not answer is not a relationship; the next action is a NEW target, not a bump.

    So: arm warm/referred/event/off-ladder. Never arm cold-boss/cold-stranger. **Unknown rung is
    treated as NOT-warm and skipped** — under an opt-in policy the conservative branch is silence,
    and 126 of 151 blocks carry no rung token, so defaulting unknown to "arm" would restore the
    exact behavior this change removes. Skipped counts are printed, never silently dropped.

    Channel is `Email`, not LinkedIn (fixed 2026-07-23). The old hardcoded `channel:LinkedIn`
    inverted Andy, who says to *"Forward your original email (not necessary for LinkedIn)"* — a
    forward is an email action. It also armed a channel that does not exist for a 2nd-degree
    contact: all four follow-ups due 2026-07-23 turned out to be unmessageable on LinkedIn.

    Idempotent: only blocks with no existing date are touched. The date is send + 7 days, so a
    send old enough that its follow-up is already overdue arms as OVERDUE rather than being
    quietly rescheduled into the future. That is the honest result: the backlog is real, and
    hiding it behind fresh dates would be the same failure in a new costume.
    """
    path = os.path.join(REPO, "outreach_log.md")
    if not os.path.exists(path):
        print("(nothing to arm — no outreach_log.md yet)")
        return 0
    src = open(path, encoding="utf-8", errors="ignore").read()
    blocks = re.split(r"(?=^## )", src, flags=re.M)
    armed, out, skipped_cold = [], [], []
    for b in blocks:
        head = b.splitlines()[0] if b.strip() else ""
        if not head.startswith("## "):
            out.append(b); continue
        has_date = re.search(r"FOLLOWUP-DUE:\s*\d{4}-\d{2}-\d{2}", b) or \
            re.search(r"follow[- ]?up[^\n]*?~?\s*\d{4}-\d{2}-\d{2}", b, re.I)
        is_sent = re.search(r"\b(sent|SENT)\b", b) and not re.search(
            r"(followed up|follow-up sent|✅\s*replied|\breplied\b|reply received)", b, re.I)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", head)
        if has_date or not is_sent or not m:
            out.append(b); continue
        # ARMING GATE. Retired 2026-07-27: ARMS_FOLLOWUP is empty, so this now skips EVERY rung.
        # Kept as a gate rather than deleted so restoring a rung is a one-line change to the
        # constant, and so the skip stays LOUD — a silent no-op reads identically to a bug.
        rung = _block_rung(b)
        if rung not in ARMS_FOLLOWUP:
            skipped_cold.append((rung or "unknown", re.sub(r"^\s*#*\s*", "", head).strip()[:52]))
            out.append(b); continue
        due = (date.fromisoformat(m.group(1)) + timedelta(days=7)).isoformat()
        token = f"FOLLOWUP-DUE: {due} | channel:Email | status:armed\n"
        lines = b.splitlines(keepends=True)
        # insert directly above the quoted message body, else before the block's trailing rule
        idx = next((i for i, l in enumerate(lines) if l.startswith(">")), None)
        if idx is None:
            idx = next((i for i, l in enumerate(lines) if l.strip() == "---"), len(lines))
        lines.insert(idx, token)
        out.append("".join(lines))
        armed.append((due, re.sub(r"^\s*#*\s*", "", head).strip()[:58]))
    if armed and not dry_run:
        open(path, "w", encoding="utf-8").write("".join(out))
    today = date.today().isoformat()
    overdue = [a for a in armed if a[0] <= today]
    print(f"{'(dry-run) would arm' if dry_run else '✅ armed'} {len(armed)} undated WARM send(s) at send+7")
    print(f"   ⚠️  {len(overdue)} of them land DUE/OVERDUE as of {today} — that is the real backlog, not a bug")
    for due, h in sorted(armed)[:10]:
        print(f"   • {due}  {h}")
    if len(armed) > 10:
        print(f"   (+{len(armed) - 10} more)")
    if skipped_cold:
        # Never silent: these are DELIBERATELY not chased, and a quiet skip reads like a bug.
        print(f"   ⏭️  {len(skipped_cold)} NOT armed — policy, not an error.")
        print("      you 2026-07-27: make the initial contact, then move on. Follow-ups that")
        print("      chase silence are retired at EVERY rung. The next action is a new target, or")
        print("      a different person at the same company (mail-draft.sh --next-target).")
        for r, h in skipped_cold[:8]:
            print(f"      • [{r}] {h}")
        if len(skipped_cold) > 8:
            print(f"      (+{len(skipped_cold) - 8} more)")
    return 0


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
