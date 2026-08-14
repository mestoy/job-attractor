#!/usr/bin/env python3
"""log_linkedin_send.py — write a send-log row for a LinkedIn message.

WHY THIS EXISTS (2026-07-24)
----------------------------
`mail-draft.sh` is the ONLY writer of `documents/send-log.jsonl`, and LinkedIn outreach is
deliberately paste-and-send (browser prefill is RETIRED, WORKFLOW-RULES §8). So **every LinkedIn
message silently skips the log**, and that log is the source of truth for FOUR mechanisms:

  1. `replied`            → every reply-rate number, including the per-rung ladder
  2. the 3-3-3 counter    → consistency-check [13]
  3. the segment hot-zone → consistency-check [15]
  4. `targets`            → `rank_criteria.burned_targets()`, the guard that stops one company
                            being named in two different warm trios

It bit twice in one day on 2026-07-24:

  • Three real replies (three warm contacts) sat flagged `False`, so the
    ladder reported the WARM rung at **0%** when it was in fact running at 13.6% — the best rung
    on the board, and the one the strategy had just pivoted to.
  • A rung-7 trio named to one contact never burned, so the ranker
    would have re-offered those same three companies to the next contact the following morning. That is the exact
    convergence Andy forbids (Boss Hunting Bible p.3: *"No. Pick the one you think is most likely
    the 'direct' boss and try that person first."*).

Three rows had to be hand-written that day. This script is the fix.

PARITY WITH mail-draft.sh IS THE POINT
--------------------------------------
mail-draft.sh carries the warm-only follow-up rule (see its FOLLOW-UP ARMING block) with this comment: *"Both paths must agree
or the rule is decorative."* The same applies here. `_followup_for()` below mirrors that case
statement exactly, and `tests/test_groupD_send.py` asserts the two stay in sync.

USAGE
-----
    python3 scripts/log_linkedin_send.py --rung warm --to linkedin.com/in/example \
        --company ExampleCo --targets "AlphaCo,BetaCo,GammaCo" --segment payments \
        --note "rung-7 trio ask"

    python3 scripts/log_linkedin_send.py --rung reply --to linkedin.com/in/example2 \
        --company "ExampleCo2" --no-targets --followup-due 2026-07-31

    python3 scripts/log_linkedin_send.py --mark-replied --to linkedin.com/in/example
"""
import argparse
import datetime
import json
import os
import re
import sys

# ⚠️ HONOR `CLAUDE_PROJECT_DIR` (fixed 2026-08-05). This used to derive REPO from `__file__`
# alone, so a test that redirected the JSONL half with `--path` still wrote the NARRATIVE half into
# the real `outreach_log.md`. On a partner install that appended fake SENT rows to their live log,
# and `check_followups.py` then reported follow-ups overdue on people they had never written to.
# The file is git-ignored, so `git status` stayed clean and nothing surfaced it.
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENDLOG = os.path.join(REPO, "documents", "send-log.jsonl")
OUTREACH_LOG = os.path.join(REPO, "outreach_log.md")

# Rungs mail-draft.sh accepts, plus the LinkedIn-only ones. `followup` (no hyphen) is a LEGACY
# spelling that exists in historical rows; we normalize to `follow-up` on write but still accept it
# so a user copying an old row does not get a spurious error.
RUNGS = {
    "cold-boss", "cold-stranger", "warm", "referred", "event", "off-ladder",
    "reply", "thank-you", "follow-up", "reunion", "application",
}
LEGACY_RUNG = {"followup": "follow-up"}

# Statuses meaning NOTHING REACHED THE PERSON, so the row must not count as a send.
# ⚠️ HAND-MIRRORED from consistency-check.sh's NOT_DELIVERED, the same way _followup_for below
# mirrors mail-draft.sh. It cannot be imported: that copy lives inside a shell heredoc. Two counters
# disagreeing about what a send IS is a real defect — a daily-send check that excludes bounces while
# a reply-rate table counts them puts rows in the denominator that never arrived.
# If you edit one copy, edit both; a test pins them together.
NOT_DELIVERED = {"bounced", "drafted", "staged", "failed", "blocked"}

# ⛔ THE "DRAFT EXISTS, NOBODY PRESSED SEND YET" STATUSES, and there are TWO spellings.
# `mail-draft.sh` declares `STAGED_STATUS = "staged"` and writes that. Older rows, and the owner's
# tree, carry `"drafted"`. A reader that recognizes only one of them is dead code that still looks
# alive: `pair_brief.stale_drafted()` matched `"drafted"` against a writer emitting `"staged"`, so
# the stale-draft alert could never fire, and its own docstring asserted the wrong spelling as fact.
#
# ⚖️ NARROWER THAN NOT_DELIVERED ON PURPOSE. `bounced`, `failed` and `blocked` are also undelivered,
# but they are TERMINAL: nothing is waiting on a human. Only these two mean "a draft is sitting
# there unsent", which is the thing worth nudging about.
#
# ⚠️ It cannot be imported by the shell writer, which holds its own copy inside a heredoc, so a test
# reads the literal out of `mail-draft.sh` and asserts it is a member here. That is the only way to
# keep a shell constant and a Python constant honest with each other.
UNSENT_STATUSES = {"drafted", "staged"}

# ⛔ NO RUNG ARMS A FOLLOW-UP. The method is: make the initial contact, then move on.
# Bible p.9 "Generally, I'm not much for following up", p.11 "You will benefit much more from
# reaching out to new people than chasing individuals who are either not getting back to you",
# plus the guidance to spend 90% of your time on initial contact.
#
# 🔴 THIS WAS HALF-PORTED, AND THE HALF THAT LANDED WAS THE READER (BUG-094, fixed 2026-08-09).
# `check_followups.ARMS_FOLLOWUP` was emptied and carries the full rationale, while BOTH writers
# here and in `mail-draft.sh` kept arming four rungs. So the kit armed follow-ups that its own
# checker was not looking for: a partner's warm send got a 7-day date written into the log and
# nothing ever surfaced it. The constant disagreed with itself across a writer and a reader, which
# is the same shape as BUG-093 one file over.
#
# ⚠️ THREE SITES MUST AGREE OR THE RULE IS DECORATIVE: this constant, the `case "$RUNG"` in
# `mail-draft.sh`, and `check_followups.ARMS_FOLLOWUP`. The shell copy cannot import, so a test
# pins them. Still allowed because none of them chases silence: a reply, a thank-you, the person
# pivot, and a deliberate bump via an explicit --followup-due date.
#
# The empty set is kept rather than deleted so restoring a rung is a one-line change.
ARMS_FOLLOWUP = set()

# Rungs where the ask NAMES target companies, so an empty `targets` is almost certainly a mistake
# that silently defeats the burn guard. Requires an explicit --no-targets to proceed.
TARGETS_EXPECTED = {"warm", "referred"}


def _followup_for(rung, override=None, suppress=False):
    """Return the follow-up date string. Parity with mail-draft.sh:394."""
    if suppress:
        return ""
    if override:
        return override
    if rung in ARMS_FOLLOWUP:
        return (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    return ""


def _load(path=SENDLOG):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                # A malformed historical line must not stop a send from being logged. Skipping is
                # correct here: this file is append-mostly and we rewrite it whole below.
                pass
    return rows


def _write(rows, path=SENDLOG):
    rows.sort(key=lambda r: (r.get("date", ""), r.get("ts", "")))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _slug(value):
    """LinkedIn slug for a `to` value, else None. Imported, never reimplemented.

    sync_contacted already parses every shape this field comes in (`linkedin:handle`, a full
    profile URL, trailing slashes, query strings). Reuse BY IMPORT, never by copy.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from sync_contacted import _slug_from_to
        return _slug_from_to(value or "")
    except ImportError:
        return None


CONTACT_STORE = os.path.join(REPO, "documents", "state", "contact.jsonl")
_H2N = None


def resolve_handle_name(to):
    """Turn a LinkedIn recipient into the contact's real NAME, or "" when it cannot be resolved.

    `--boss` already carries the name when the operator remembers to pass it, and it degrades
    SILENTLY to the bare handle when they forget. What that costs: `to` reads
    `linkedin.com/in/<handle>`, the outreach_log header carries the same handle, and the ranker's
    contacted-people join keys on NAMES, so the person is not recognised as already contacted and
    gets offered again at a higher score. Nearly every LinkedIn row in a mature log has this shape.

    A RECORD SHOULD NOT DEPEND ON OPERATOR DISCIPLINE TO BE READABLE. The reader-side repair lives
    in `rank_criteria` so existing rows resolve at read time; this is the writer-side half, so new
    rows carry the name and no future reader needs the join at all.

    Reads the same `documents/state/contact.jsonl` that `parse_network.py` writes, where `linkedin`
    and `name` sit side by side. Later rows win, matching the append-only last-write-wins rule.
    Returns "" on any failure, so a missing store never blocks a send.
    """
    global _H2N
    m = re.search(r"linkedin\.com/in/([^/?\s]+)", str(to or ""))
    if not m:
        return ""
    if _H2N is None:
        _H2N = {}
        try:
            with open(CONTACT_STORE, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        p = (json.loads(line) or {}).get("payload") or {}
                    except ValueError:
                        continue
                    u = re.search(r"linkedin\.com/in/([^/?\s]+)", str(p.get("linkedin") or ""))
                    if u and p.get("name"):
                        _H2N[u.group(1).lower().rstrip("/")] = p["name"]
        except Exception:
            pass                                    # degrade to "", never block the send
    return _H2N.get(m.group(1).lower().rstrip("/"), "")


def same_recipient(a, b):
    """Do two `to` values name the same person?

    THE DEFECT THIS FIXES. `--to` accepts BOTH `linkedin.com/in/<handle>` and `linkedin:handle` and
    normalizes neither, so a row stored one way is invisible to a lookup phrased the other way. The
    two spellings tend to partition a log rather than overlap, because whichever form you used the
    first time is the form you keep using. Marking a reply then fails silently, or files the reply
    under a second key for a person who already has a row, breaking the send-to-reply pairing that
    every reply-rate number is computed from.

    Falls back to exact equality for anything that is not a LinkedIn identity (emails, SMS rows,
    group threads), which must keep comparing as opaque strings.
    """
    if a == b:
        return True
    sa, sb = _slug(a), _slug(b)
    return bool(sa and sb and sa.lower() == sb.lower())


def _compress(slug):
    """Alphabetic-only form of a slug, dropping hyphens and any trailing numeric id.

    Lossy ON PURPOSE and used only to SUGGEST, never to assert a match: it collapses
    `first-last`, `firstlast` and `first-last-8412` onto each other, which is the family of near
    misses a hand-typed handle produces.
    """
    return "".join(t for t in re.split(r"[^A-Za-z0-9]+", (slug or "")) if t.isalpha()).lower()


def _near_misses(to, rows, limit=3):
    """Rows whose handle compresses to the same string as `to`. Suggestions only."""
    target = _compress(_slug(to) or to)
    if not target:
        return []
    out = []
    for r in rows:
        raw = r.get("to")
        if not raw or same_recipient(raw, to):
            continue
        if _compress(_slug(raw) or raw) == target:
            out.append(r)
    return sorted(out, key=lambda r: (r.get("date", ""), r.get("ts", "")), reverse=True)[:limit]


# ── THE FUNNEL STAGE, added 2026-08-11 ──────────────────────────────────────────────────────────
# 🎯 THE GOAL IS INTERVIEWS, NOT SENDS, and until today the log could not count either one.
# `replied` is a boolean and `outcome` was free prose on 5 of 397 rows. So "how many interviews has
# this search produced" was answerable only by reading `correspondence-log.md` end to end, which is
# what a three-agent forensic pass had to do on 2026-08-11 to establish the answer: SIX
# conversations, ZERO interviews, across 380 sends.
#
# ⛔ CONVERSATION AND INTERVIEW ARE DIFFERENT STAGES AND THE VOCABULARY MUST SAY SO. This is not
# pedantry, it is a guardrail with a receipt: on 2026-07-24 the pipeline reported "3 interviews this
# week" and the owner corrected it to three CONVERSATIONS and no interviews
# ([[interview-vs-informational-exchange]]). A field that cannot tell them apart will retell that
# flattering error every time it is summed. An informational exchange, a recruiter intro call and a
# coffee chat are `conversation`. `interview` means an employer is EVALUATING him for a named seat.
#
# ⚖️ MONOTONIC BY DESIGN. Stages only advance; `--stage` refuses to move a row backwards, because a
# funnel that can un-advance cannot be counted. `closed` is terminal and may follow any stage.
STAGES = [
    "sent",           # it left; nothing has come back
    "replied",        # a human answered, of any kind
    "conversation",   # a real exchange or call. NOT an interview. Intro calls live here.
    "screen",         # a recruiter or hiring screen against a NAMED seat
    "interview",      # an employer is evaluating him for a named seat
    "onsite",         # panel, loop, or final round
    "offer",
    "closed",         # rejected, withdrawn, ghosted-and-called. Terminal, allowed from anywhere.
]
_STAGE_RANK = {name: i for i, name in enumerate(STAGES)}


def stage_rank(name):
    return _STAGE_RANK.get((name or "").strip().lower(), -1)


def set_stage(to, stage, path=SENDLOG, when=None, note=None):
    """Advance the most recent row for `to` to `stage`. Returns (row, error_or_None).

    Refuses to move BACKWARDS. A funnel whose stages can regress cannot be summed, and the honest
    way to record a reversal is `closed` plus a note, never a demotion that erases the high-water
    mark that was actually reached.
    """
    want = (stage or "").strip().lower()
    if want not in _STAGE_RANK:
        return None, f"unknown stage {stage!r}; one of: {', '.join(STAGES)}"
    rows = _load(path)
    hits = [r for r in rows if same_recipient(r.get("to"), to)]
    if not hits:
        return None, f"no send-log row for {to!r}"
    target = max(hits, key=lambda r: (r.get("date", ""), r.get("ts", "")))
    cur = target.get("stage") or ("replied" if target.get("replied") else "sent")
    if want != "closed" and stage_rank(want) < stage_rank(cur):
        return None, (f"refusing to move {to} BACKWARDS from {cur!r} to {want!r}. "
                      f"Record a reversal as `closed` with a note; the high-water mark stays.")
    target["stage"] = want
    target["stage_at"] = when or datetime.date.today().isoformat()
    if note:
        target["stage_note"] = note
    # ⛔ DO NOT SET `replied` FROM A STAGE. Removed 2026-08-11, hours after being written, when
    # the owner asked what the backfill had changed.
    # 🔬 THE ERROR: STAGE is a property of the THREAD, `replied` is a property of the ROW, and the
    # first cut set `replied = True` on any advance past that rank. It flipped three rows, two of
    # them THANK-YOU notes sent at the END of a conversation. A thank-you often gets no reply at
    # all. The thread reached `conversation`; that row did not get answered.
    # 📊 COST, measured: the headline reply rate moved 16.5% → 17.3% on a backfill that added no
    # new replies, only stage labels. An instrument that changes the number it is meant to explain
    # is worse than no instrument.
    # ⚖️ The two facts stay separate: `--mark-replied` records that THIS row was answered;
    # `--stage` records how far the THREAD got. Neither implies the other.
    _write(rows, path)
    return target, None


def stage_counts(path=SENDLOG):
    """{stage: n} over delivered rows, using the high-water stage each row reached."""
    out = {s: 0 for s in STAGES}
    for r in _load(path):
        if (r.get("status") or "sent") != "sent":
            continue
        s = r.get("stage") or ("replied" if r.get("replied") else "sent")
        if s in out:
            out[s] += 1
    return out


# ── ONE CHANCE PER MEDIUM (Andy, Boss Hunting Bible p.4) ────────────────────────────────────────
# His words, verbatim: *"If it's me, I give them ONE chance via each medium. That is, I'd send an
# email and then a week or so later I'd send a LinkedIn message. If they don't get back to me, I'd
# move on."* And p.11: *"You will benefit much more from reaching out to NEW people than chasing
# individuals who are either not getting back to you."*
#
# ⚖️ HALF OF THIS WAS ALREADY ENFORCED AND HALF WAS NOT. `check_followups.ARMS_FOLLOWUP` is an empty
# tuple, so nothing ARMS a nudge automatically — that half has held since 2026-07-27. What had no
# guard is the MANUAL path: nothing stopped a second bump to the same person on the same medium if
# someone decided to send one. A rule that only binds the robot is not a rule.
#
# ⛔ MEDIUM, NOT PERSON, AND THE ORDER IS NOT SYMMETRIC. **Email is the default and preferred first
# touch; LinkedIn is the SECOND** (the owner, 2026-08-11, ratifying p.4: "I'd send an email and then a
# week or so later I'd send a LinkedIn message"). So the ledger keys on (recipient, channel), and a
# LinkedIn bump after an email bump is CORRECT and must pass. Keying on the person alone would
# forbid the very sequence he prescribes.
# ⚠️ The email-first default is a BOSS HUNT rule (rungs 3-4). On warm rungs the measured data runs
# the other way: warm-on-LinkedIn was 16/38 against 6/49 on the unrecorded mix. Do not carry the
# default onto a warm rung. [[email-is-the-default-linkedin-is-the-second-touch]]
#
# ⚠️ A DATED DEFERRAL IS NOT A BUMP. "Check back closer to October" is an invitation with a date on
# it, and the first touch on that medium is still the first touch. This only refuses a SECOND one.
BUMP_RUNGS = {"follow-up", "bump"}


def prior_bump_on_medium(to, channel, path=SENDLOG):
    """The earlier bump row for this recipient on this channel, or None.

    Delivered rows only: a discarded or bounced draft never reached them, so it never spent the
    one chance. Counting it would refuse a touch that never happened.
    """
    for r in _load(path):
        if (r.get("status") or "sent") != "sent":
            continue
        if (r.get("rung") or "") not in BUMP_RUNGS:
            continue
        if (r.get("channel") or "") != (channel or ""):
            continue
        if same_recipient(r.get("to"), to):
            return r
    return None


def mark_replied(to, path=SENDLOG, when=None):
    """Set replied=True on the most recent row for `to`. Returns the row or None.

    Backfilling replies by hand is what produced the 0%-warm-reply-rate defect, so this is a
    first-class command rather than something to do in an ad-hoc heredoc.
    """
    rows = _load(path)
    hits = [r for r in rows if same_recipient(r.get("to"), to)]
    if not hits:
        return None
    target = max(hits, key=lambda r: (r.get("date", ""), r.get("ts", "")))
    target["replied"] = True
    target["replied_note"] = f"marked replied {when or datetime.date.today().isoformat()}"
    _write(rows, path)
    return target



CORRESPONDENCE_LOG = os.path.join(REPO, "documents", "correspondence-log.md")


def advance_correspondence_line(text, company, to, subject):
    """Flip a terse `OUTBOUND (STAGED, not yet sent)` line to SENT. Returns (new_text, n_changed).

    THE THIRD WRITER. The mail drafter appends
    `- <date> · OUTBOUND (STAGED, not yet sent) · <co> → <to> · subj: <subj>`
    the moment a draft is built, and nothing advanced it when the send happened, because this
    logger did not touch the file at all. The result is a store that asserts the opposite of the
    truth about real sends, and it stays wrong indefinitely because nothing re-reads it.

    ⚠️ A presence check cannot catch this. Asking whether a sent company has AN outbound record is
    satisfied by a line saying the message was never sent. The check has to assert the STATE.

    Matched on company + recipient + subject, the same join key the other two writers use. Every
    matching line is advanced, not only the first, because a rebuilt draft can leave more than one.
    """
    marker = "OUTBOUND (STAGED, not yet sent)"
    out, changed = [], 0
    for line in text.splitlines(keepends=True):
        if (marker in line and f"{company} → {to}" in line
                and (not subject or f"subj: {subject}" in line)):
            out.append(line.replace(marker, "OUTBOUND (SENT)"))
            changed += 1
        else:
            out.append(line)
    return "".join(out), changed


def staged_marker(company, subject):
    """The exact key `mail-draft.sh` writes as `<!-- STAGED · <company> · <subject> -->`.

    Kept as a named function so the two writers share ONE definition of the join key. If the marker
    ever changes shape in the shell script, this is the single place that has to follow, and a test
    can pin the two against each other.
    """
    return f"STAGED · {company} · {subject}"


def replace_staged_block(text, marker, entry):
    """Swap the STAGED block carrying `marker` for `entry`. Returns (new_text, replaced).

    TWO WRITERS, ONE SEND. `mail-draft.sh` writes a `## … — STAGED (draft)` header the moment a
    draft exists, deliberately, so a second session can see work in flight. This function is what
    stops that header from being JOINED by a `## … — ✅ SENT` sibling when the send is confirmed:
    the staged block is overwritten in place, so one send leaves one header and the two daily
    counters agree.

    The marker comment is the anchor rather than the header text, because the two writers spell the
    recipient differently: one has only the address at draft time, the other has the resolved name.

    A block runs from its own `## ` header line to the next `## ` line or the end of the file.

    ⚠️ NO MATCH MEANS NO CHANGE AND A PLAIN APPEND. A send with no staged draft, which is every
    send that never went through the mail drafter, still gets logged. Losing a send is far worse
    than logging one twice, so the fall-through is the safe direction and it is deliberate.
    """
    anchor = f"<!-- {marker} -->"
    at = text.find(anchor)
    if at < 0:
        return text, False
    # Walk back to the start of the `## ` header line that owns this marker.
    start = text.rfind("\n## ", 0, at)
    start = 0 if start < 0 else start + 1
    # The block ends at the next header, or EOF.
    end = text.find("\n## ", at)
    end = len(text) if end < 0 else end + 1
    return text[:start] + entry + text[end:], True


def _append_narrative(row, a, rung):
    """Append a `## <date>` entry to outreach_log.md so BOTH daily counters move on one send.

    There are two counters for one number and they read different stores: `## <date>` headers in
    outreach_log.md (the narrative log, one per write-up) and rows in send-log.jsonl (the machine
    log, one per send). When only the machine log is written, every hand-sent message leaves the
    two disagreeing, and a number nobody trusts stops being useful.

    This writes the HEADER and the facts it can prove. The verbatim body is written when --body is
    supplied; without it the entry says so plainly rather than implying a write-up that does not
    exist. A store that is not written is a store that lies.
    """
    body = a.body
    if body and os.path.exists(body):
        body = open(body, encoding="utf-8").read().strip()

    # Prefer the NAME, so the header itself is joinable. `--boss` first because a human said it,
    # then the resolved store name, and the bare handle only when neither exists.
    who = getattr(a, "boss", None) or row.get("to_name") or a.to
    company = a.company or "no company named"
    chan = row.get("channel", "LinkedIn")
    bits = [f"## {row['date']} · {company} · {who} — ✅ SENT [{chan} · rung {rung}]"]
    bits.append(f"**Status:** ✅ SENT {row['date']} on {chan}. You typed and sent it.")
    if a.subject:
        # When this entry OVERWRITES a staged block, that block's `**Subject:**` line goes with it.
        # Carry the subject here or the collapse trades a double count for an information loss.
        bits.append(f"**Subject:** {a.subject}")
    # ⚠️ FOLLOWUP-DUE MUST SURVIVE THE COLLAPSE. The staged block written by the mail drafter
    # carries `FOLLOWUP-DUE: <date>`, and check_followups.py finds an armed send by reading that
    # token out of the block. Overwriting the staged block without re-stating it would silently
    # UN-ARM a send that was armed correctly, and the follow-up would read as one nobody set.
    bits.append(f"**Rung:** {rung} (kind:{a.kind}) | channel:{chan} | status:{a.status}"
                f" | FOLLOWUP-DUE: {row.get('followup_due') or 'none'}")
    if a.targets:
        bits.append(f"**Targets named (now burned):** {a.targets}")
    if getattr(a, "referred_by", None):
        bits.append(f"**Referred by:** {a.referred_by}")
    if a.praise_tier:
        bits.append(f"**Praise tier:** {a.praise_tier}")
    if a.note:
        bits.append(f"**Note:** {a.note}")
    if body:
        bits.append("**Verbatim as sent:**")
        bits.extend("> " + ln if ln.strip() else ">" for ln in body.splitlines())
    else:
        bits.append("**Verbatim as sent:** ⚠️ not captured at log time (no --body). "
                    "Paste it in; the send-log row is already correct.")
    entry = "\n".join(bits) + "\n\n"

    # ONE HEADER PER SEND. When the mail drafter staged this exact company and subject, its STAGED
    # block IS this send's header and gets overwritten; otherwise append as before. The marker is
    # built from the raw `a.company`, because that is the value the drafter keyed on.
    marker = staged_marker(a.company, a.subject) if (a.company and a.subject) else ""
    if marker and os.path.exists(OUTREACH_LOG):
        with open(OUTREACH_LOG, encoding="utf-8") as fh:
            text = fh.read()
        new_text, replaced = replace_staged_block(text, marker, entry)
        if replaced:
            with open(OUTREACH_LOG, "w", encoding="utf-8") as fh:
                fh.write(new_text)
            return "updated"

    with open(OUTREACH_LOG, "a", encoding="utf-8") as fh:
        fh.write("\n" + entry)
    return "appended"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Log a LinkedIn send to documents/send-log.jsonl")
    ap.add_argument("--rung", help="one of: " + ", ".join(sorted(RUNGS)))
    ap.add_argument("--to", required=False, help="linkedin.com/in/<handle> or linkedin:<handle>")
    ap.add_argument("--company", default="")
    # The real subject line, for a send that began as an email draft. Without it this logger can
    # only ever file a row as "(LinkedIn)", and the narrative collapse below has no key to join on:
    # mail-draft.sh writes its staged block under `<!-- STAGED · Company · Subject -->`, so the
    # subject is half of that key. A logger with no --subject cannot close a staged draft, and the
    # collapse would be present in the file and unreachable in practice.
    ap.add_argument("--subject", default="", help="the real subject line; email sends only")
    ap.add_argument("--targets", default="", help="comma-separated companies NAMED in the ask; these BURN")
    ap.add_argument("--no-targets", action="store_true", help="acknowledge a warm send that names no companies")
    ap.add_argument("--segment", default="")
    ap.add_argument("--kind", default="initial", choices=["initial", "reply"])
    ap.add_argument("--status", default="sent", choices=["sent", "bounced", "drafted"])
    ap.add_argument("--note", default="", help="sent_note: what it was and why")
    ap.add_argument("--praise-tier", choices=["A", "B", "none"], default=None,
                    help="A=primary-sourced artifact, B=specifics about their background, "
                         "none=no praise beat. Recorded so the reply rates of A vs B can be "
                         "compared before you loosen or tighten the rule.")
    ap.add_argument("--body", default="", help="path to the message text, or the text itself; "
                                               "written verbatim into outreach_log.md")
    ap.add_argument("--no-narrative", action="store_true",
                    help="skip the outreach_log.md entry (use only when writing it up by hand)")
    ap.add_argument("--followup-due", default=None, help="YYYY-MM-DD; overrides the rung default")
    ap.add_argument("--no-followup", action="store_true", help="deliberately arm nothing")
    ap.add_argument("--mark-replied", action="store_true", help="flip the latest row for --to to replied")
    ap.add_argument("--stage", choices=STAGES,
                    help="advance the latest row for --to to a funnel stage (monotonic; "
                         "conversation != interview)")
    ap.add_argument("--stage-note", help="what happened, for the stage row")
    ap.add_argument("--funnel", action="store_true", help="print the funnel: how many reached each stage")

    ap.add_argument("--boss", default="", help="REQUIRED on --rung cold-boss: the person, "
                                              "checked against documents/state/boss.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--path", default=SENDLOG, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    if not a.funnel and not a.to:
        # ⛔ --to stays mandatory for every WRITE. Only the read-only funnel report is exempt,
        # because a report about the whole log has no single recipient. Relaxing the argparse
        # requirement without this guard would let a send be logged against nobody.
        print("🔴 --to is required (except with --funnel)", file=sys.stderr)
        return 3
    if a.funnel:
        c = stage_counts(a.path)
        total = sum(c.values())
        print(f"── FUNNEL over {total} delivered send(s) ──")
        for st in STAGES:
            print(f"  {st:14s} {c[st]:4d}")
        reached = {st: sum(c[s2] for s2 in STAGES
                           if stage_rank(s2) >= stage_rank(st) and s2 != "closed")
                   for st in STAGES if st != "closed"}
        print("\n  reached AT LEAST this stage:")
        for st in STAGES:
            if st == "closed":
                continue
            print(f"  {st:14s} {reached[st]:4d}")
        print("\n  ⚖️ conversation is NOT interview. An intro call, a coffee chat and an")
        print("     informational exchange are `conversation`. `interview` means an employer is")
        print("     evaluating him for a NAMED seat. Summing the two is the error of 2026-07-24.")
        return 0
    if a.stage:
        row, err = set_stage(a.to, a.stage, a.path, note=a.stage_note)
        if err:
            print(f"🔴 {err}", file=sys.stderr)
            return 2
        print(f"✅ {a.to} → stage={row['stage']} ({row.get('stage_at')})")
        return 0
    if a.mark_replied:
        row = mark_replied(a.to, a.path)
        if not row:
            print(f"🔴 no send-log row found for {a.to}", file=sys.stderr)
            # A bare miss sends the reader hunting through the whole log. A handle typed or
            # guessed rather than copied from the profile is common, so "no row" usually means
            # "the row is there under a wrong handle". Naming the near miss surfaces that at the
            # one moment a person is looking at it.
            for cand in _near_misses(a.to, _load(a.path)):
                print(f"   ↳ did you mean {cand['to']!r}? "
                      f"({cand.get('date')} · rung={cand.get('rung')})", file=sys.stderr)
            return 1
        print(f"✅ marked replied: {row.get('date')} · rung={row.get('rung')} · {a.to}")
        return 0

    if not a.rung:
        print("🔴 --rung is required (or use --mark-replied)", file=sys.stderr)
        return 2
    rung = LEGACY_RUNG.get(a.rung, a.rung)
    if rung not in RUNGS:
        print(f"🔴 unknown rung {a.rung!r}. One of: {', '.join(sorted(RUNGS))}", file=sys.stderr)
        return 2

    # THE BURN GUARD. A warm ask that names companies must record them, or rank_criteria will
    # re-offer the same companies to the next contact. Fail loudly rather than log a row that
    # looks complete and silently defeats the guard.
    if rung in TARGETS_EXPECTED and not a.targets and not a.no_targets:
        print(f"🔴 rung {rung!r} usually NAMES target companies, and --targets is empty.\n"
              "   Those companies BURN on naming (Bible p.3), and rank_criteria.burned_targets()\n"
              "   reads this field. Pass --targets \"A,B,C\", or --no-targets if the message named none.",
              file=sys.stderr)
        return 2


    # BOSS REGISTRY, cold-boss only. Parity with mail-draft.sh: both paths must agree or the rule is
    # decorative. Scoped to cold-boss ALONE — cold-stranger has no boss, and a gate written for one
    # rung binds every rung that falls through to it.
    if rung == "cold-boss":
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import boss_registry
            if not a.boss:
                print("⛔ BLOCKED: missing --boss on a cold-boss send. Name the person you researched.")
                return 4
            if boss_registry.main(["check", "--company", a.company or "", "--person", a.boss]) != 0:
                return 4
        except ImportError:
            pass  # registry absent on a fresh install: degrade rather than block every send
    rows = _load(a.path)
    today = datetime.date.today().isoformat()
    dupes = [r for r in rows
             if same_recipient(r.get("to"), a.to) and r.get("date") == today and r.get("rung") == rung]
    if dupes:
        print(f"⚠️  {len(dupes)} row(s) already logged today for {a.to} at rung {rung} — check for a double-log.")

    # ⛔ ONE CHANCE PER MEDIUM (Bible p.4). Refuses a SECOND bump on the same medium to the same
    # person. Placed here, immediately before the row is built, because this is the last point both
    # channels pass through in this tree. The main repo attaches it at channel resolution; this
    # file has no such block, so the anchor differs while the rule is identical.
    _chan = (a.channel if getattr(a, "channel", "auto") != "auto"
             else ("email" if ("@" in a.to and "linkedin" not in a.to.lower()) else "linkedin"))
    if rung in BUMP_RUNGS and (a.status or "sent") == "sent":
        _prior = prior_bump_on_medium(a.to, _chan, a.path)
        if _prior:
            print(f"🔴 REFUSED: {a.to} already got a {_prior.get('rung')} on {_chan} "
                  f"({_prior.get('date')}).", file=sys.stderr)
            print("   Bible p.4: \"I give them ONE chance via each medium... If they don't get "
                  "back to me, I'd move on.\"", file=sys.stderr)
            print("   The OTHER medium is still open if unused. Otherwise pivot to a new person.",
                  file=sys.stderr)
            return 2

    row = {
        "ts": datetime.datetime.now().astimezone().isoformat(),
        "date": today,
        "rung": rung,
        "to": a.to,
        # The recipient's real NAME, so every downstream reader that keys on names can join
        # without resolving a handle. Empty for a cold target who was never a connection, which
        # is expected rather than a failure.
        "to_name": getattr(a, "boss", None) or resolve_handle_name(a.to),
        "company": a.company,
        "targets": a.targets,
        # A real subject wins when one was given; the LinkedIn placeholders stay the default, so
        # every existing caller keeps the exact value it filed before.
        "subject": a.subject or ("(LinkedIn, in-thread)" if a.kind == "reply" else "(LinkedIn)"),
        "segment": a.segment,
        "kind": a.kind,
        "followup_due": _followup_for(rung, a.followup_due, a.no_followup),
        "status": a.status,
        "replied": False,
        "sent_note": a.note or "logged via log_linkedin_send.py (LinkedIn paste-and-send)",
    }

    if a.praise_tier:
        # Two-tier praise beat: A=artifact, B=specifics about their background. Stored so the
        # reply rates can be compared; a two-tier rule nobody measures is just a looser rule.
        row["praise_tier"] = a.praise_tier

    if a.dry_run:
        print(json.dumps(row, ensure_ascii=False, indent=1))
        return 0

    rows.append(row)
    _write(rows, a.path)

    print(f"✅ logged: rung={rung} · {a.to} · status={a.status}")
    if a.no_narrative:
        print("   📝 outreach_log.md SKIPPED (--no-narrative) — the two daily counters will disagree")
    else:
        try:
            mode = _append_narrative(row, a, rung)
            if mode == "updated":
                print("   📝 outreach_log.md STAGED header updated in place (one header per send)")
            else:
                print("   📝 outreach_log.md entry appended (both daily counters now agree)")
        except Exception as exc:
            print(f"   ⚠️  outreach_log.md NOT written ({exc}) — counters will disagree, fix by hand")
        # Advance the THIRD store too, so it stops saying "not yet sent" about a real send.
        try:
            if a.company and os.path.exists(CORRESPONDENCE_LOG):
                with open(CORRESPONDENCE_LOG, encoding="utf-8") as fh:
                    _ctext = fh.read()
                _new, _n = advance_correspondence_line(_ctext, a.company, a.to, a.subject)
                if _n:
                    with open(CORRESPONDENCE_LOG, "w", encoding="utf-8") as fh:
                        fh.write(_new)
                    print(f"   📝 correspondence-log.md: {_n} STAGED line(s) advanced to SENT")
        except Exception as exc:
            print(f"   ⚠️  correspondence-log.md NOT advanced ({exc}) — it will read 'not yet sent'")
    if row["followup_due"]:
        print(f"   📒 follow-up armed {row['followup_due']}")
    else:
        print("   📒 NO follow-up armed"
              + ("  (deliberate, --no-followup)" if a.no_followup
                 else "  (cold or post-contact rung — warm-only policy 2026-07-23)"))
    if a.targets:
        burned = [t.strip() for t in a.targets.split(",") if t.strip()]
        print(f"   🔥 BURNED {len(burned)}: {', '.join(burned)}  (rank_criteria will now exclude them)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
