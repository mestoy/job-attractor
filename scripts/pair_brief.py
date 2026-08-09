#!/usr/bin/env python3
"""pair_brief.py — the ONE computer of the durable pair: a ladder summary plus a derived default.

WHY THIS EXISTS. Two things are owed at every stopping point in a job search: the LADDER (how each
rung is actually performing) and a PICKER of what to do next, with the method's own suggestion as
the default. Both are easy to write down as a habit and impossible to keep as one. Observed failure:
three turns in a row ended on a status report with no picker at all, and the numbers quoted in the
last one had been carried forward from an earlier message and were already stale.

A rule that lives only in prose is not a rule. So the deliverable is not a picker FORMAT. It is a
loop in which the pair cannot silently stop appearing and the ladder numbers cannot be stale. This
file computes the facts; `check_pair.py` enforces them at the two moments the harness can see.

WHAT IT OWNS
  1. THE LADDER SUMMARY, by importing rung_ladder (load/tally/render), never by a second join.
     `--full` gives the whole table for session open; the default gives a compact block that never
     buries the picker.
  2. THE STAMP, one line, the mechanical heart of the design:
         LADDER 2026-01-01 · sent 12 · replied 1 · rate 8.3% · 3-3-3 1/3   (shape, not real data)
     `stamp()` is the ONE producer of that line. check_pair and every test IMPORT it rather than
     reimplementing it, because a second formatter is a second answer (the phantom-followup lesson,
     session_start.py).
  3. THE DERIVED DEFAULT plus alternates, from the ordered decision table in PRIORITIES. Every
     predicate reads LIVE state through an existing single-source reader. None is typed by an agent
     at runtime: he decides, the pipeline calculates (HARD-INVARIANTS.md SEND GATE).

The assistant still AUTHORS the picker text — his voice, the irreverent option, the badges. This
script supplies the facts, the default and the stamp to copy in verbatim.

⛔ READ-ONLY, offline, exits 0 always. It runs inside the SessionStart hook, and a briefing that
crashes blocks a session from opening.

Usage:
    scripts/pair_brief.py             # compact post-action pair
    scripts/pair_brief.py --full      # session-open pair (whole ladder table)
    scripts/pair_brief.py --json      # {stamp, default, alternates, andy_read, evidence, ...}
    scripts/pair_brief.py --stamp     # the stamp line alone
Exit: 0 always (a report, not a gate)
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

# The delivered/undelivered vocabulary is IMPORTED, never re-typed (it lives with the writer).
from log_linkedin_send import NOT_DELIVERED, UNSENT_STATUSES  # noqa: E402

# The literal marker a NEXT-STEP picker must carry. Same explicit-marker pattern as check_preview's
# `WARM-RUNG:` / `FOLLOWUP:` / `REFERRED:` anchors: an UNMARKED picker (a scorecard, a voice pick)
# is never touched by the pair gate, so this adds zero risk to the BUILD gate and cannot nag an
# ordinary question.
PAIR_MARKER = "NEXT-STEP"

# THE QUESTION AND HEADER THE PICKER MUST USE, as constants rather than as advice.
#
# ⛔ WHY THEY ARE FIXED (record_decision interplay). `record_decision.classify_answer` reads the
# QUESTION and HEADER as BUILD CONTEXT : inside a build-context
# question, a bare "yes" is promoted to a MAC-signed BUILD ruling. So a next-step picker phrased
# "draft the next move?" would turn your click into an authorization he never gave, in the one
# store that exists to make authorization unforgeable. These two strings carry no BUILD_CONTEXT
# vocabulary, and a test reads THEM rather than a copy of them, because a test that does not read
# the production value is not a test of it (documents/ENFORCEMENT-REGISTER.md).
#
# Rows recorded from this picker are OTHER: an audit trail, authorizing nothing.
QUESTION_TEMPLATE = "{marker} · what now? {stamp}"
HEADER_TEMPLATE = "Next move"


# 🔴 THE TOOL'S OWN OUTPUT USED TO FAIL THE TOOL'S OWN GATE (fixed 2026-08-03). check_pair
# --hook-ask requires option 1 to NAME the method, matching kit_config.METHOD_TERMS. The default
# label printed here read "Next initial contact: ..." and named nobody, so an agent that copied
# this output verbatim into the picker got blocked, with the fix living nowhere in the output it
# had just followed. The label now carries the name itself, derived from the SAME config the gate
# reads, so the two can never drift apart again.
def method_name():
    """Display name for the method, guaranteed to contain a METHOD_TERMS token.

    Derived from the config rather than typed, because a partner who renames the method in
    kit_config.METHOD_TERMS would otherwise get a default label that fails their own gate. The
    lacivita special case is only about capitalization; any other term prints as the partner wrote it.
    """
    terms = ["lacivita", "andy"]
    try:
        import kit_config
        cfg = getattr(kit_config, "METHOD_TERMS", None)
        if cfg:
            terms = [str(t) for t in cfg if str(t).strip()]
    except Exception:
        pass
    if not terms:
        return ""
    first = terms[0]
    return "LaCivita" if first.lower() == "lacivita" else first


def question_for(today=None, repo=None):
    """The exact question string to put in the picker, stamp already inlined."""
    return QUESTION_TEMPLATE.format(marker=PAIR_MARKER, stamp=stamp(today, repo))

# ⚠️ A DEFAULT ORDER, NOT YOUR RULING. The CONTENTS of each row below trace to the method; the
# ORDER they are tried in is a starting proposal. It prints its own provenance so a shipped default
# is never mistaken for a decision you made. Re-order it once you have watched it run, then delete
# this caveat.
PRIORITY_PROVENANCE = ("(the P0-P4 ORDER is a shipped default, not your ruling · watch it work, "
                       "then re-order it · scripts/pair_brief.py PRIORITIES)")

# The ordered table. First hit wins. IDs are stable so a test can name a row.

# ⏰ THE OUTBOUND WINDOW. Never offer "stop for the day" before this hour, local Eastern.
#
# ⛔ HOUSE METHOD, not LaCivita. The kit owner who wrote this ruled that mornings are for OUTBOUND
# and that hitting 3 messages does not end the day: 3-3-3 is the daily FLOOR, never a cap. The card
# must say so rather than laundering a personal cadence as a LaCivita ruling.
#
# ⚠️ THIS VALUE IS A PROPOSAL FOR YOU, NOT A RULING YOU MADE. It ships at 16 so a paired session
# behaves the same on both machines. It is YOUR cadence to set: change the hour, or set it to 0 to
# turn the window off entirely and get "stop for the day" back as soon as the loop closes.
OUTBOUND_WINDOW_CLOSES_ET = 16


def _outbound_window_open(now=None):
    """True while the morning and early-afternoon outbound block is still running.

    Passing `now` keeps this testable without touching the clock.
    """
    if not OUTBOUND_WINDOW_CLOSES_ET:
        return False                      # 0 disables the window: stop-for-the-day is always offered
    if now is None:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            # A missing tzdb must not answer in the permissive direction. Failing CLOSED would
            # suppress the stop option forever; failing OPEN costs at most one extra send offered.
            return True
    return now.hour < OUTBOUND_WINDOW_CLOSES_ET


PRIORITIES = ["P0", "P1", "P2", "P3", "P4"]

# ⛔ NEVER DERIVABLE AT ANY PRIORITY (documents/HARD-INVARIANTS.md SEND GATE): a follow-up or bump
# that chases silence. The method's own line is to make the initial contact and then move on. A
# reply, a thank-you and the person pivot stay allowed, because none of them chases silence.
FORBIDDEN_DEFAULTS = re.compile(r"\bfollow[\s-]?up\b|\bbump\b|\bnudge (?:them|him|her)\b|"
                                r"\bchase\b|\bcheck in (?:on|with)\b|\bping (?:them|him|her)\b",
                                re.I)


def _rd(rel, repo=None):
    try:
        with open(os.path.join(repo or REPO, rel), encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception:
        return ""


# ── ONE COUNTER PER NUMBER ────────────────────────────────────────────────────────────────────
# These three readers used to live inline in session_start.py. They are needed here too, and the
# repo has paid three times for a second parser of the same store (session_start.py). So they
# move HERE and session_start imports them. Direction matters: session_start imports pair_brief, so
# nothing in this file may ever import session_start.

def sends_today(today=None, repo=None):
    """Today's 3-3-3 count from outreach_log.md `## <date>` headers.

    ⚠️ THIS IS THE NARRATIVE COUNTER, and it is NOT the one the stamp uses. Kept because
    session_start has printed it from the start and changing what a long-standing briefing line
    means is its own kind of drift. See counter_gap() for why there are two.
    """
    d = today or date.today().isoformat()
    return len(re.findall(r"^##\s*" + re.escape(d), _rd("outreach_log.md", repo), re.M))


def sends_today_logged(today=None, repo=None):
    """Today's 3-3-3 count from send-log.jsonl, excluding rows that reached nobody.

    ⛔ NOT_DELIVERED IS IMPORTED, never re-typed. The set lives in log_linkedin_send and reaches
    here through rung_ladder, so the ladder's denominator and this counter cannot disagree about
    what a delivered send IS. That parity has failed before: consistency-check [13] once counted a
    hard bounce as outreach and printed "3/3 loop closed" on a day when one of the three reached
    nobody. Excluded statuses are named in ONE place for exactly that reason.
    """
    d = today or date.today().isoformat()
    try:
        import rung_ladder
        not_delivered = rung_ladder.NOT_DELIVERED     # which is log_linkedin_send's, by import
    except Exception:
        # NO LOCAL FALLBACK SET, deliberately. A hardcoded copy here would be a SECOND definition of
        # "delivered" and would drift from the writer's the moment a status is added, which is the
        # whole defect this docstring is about. ladder_counts() already degrades to an empty ladder
        # in exactly this case, so returning 0 keeps both halves of the stamp consistent.
        return 0
    n = 0
    for line in _rd("documents/send-log.jsonl", repo).splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("date") == d and str(r.get("status", "")).lower() not in not_delivered:
            n += 1
    return n


def counter_gap(today=None, repo=None):
    """(narrative, logged) when the two 3-3-3 counters DISAGREE, else None.

    🔴 REPORTED, NOT SILENTLY RESOLVED (found live 2026-07-27). There are two counters for one
    number and they read different stores:

        outreach_log.md `## <date>` headers   the narrative log, one header per WRITE-UP
        send-log.jsonl rows dated today       the machine log, one row per SEND

    They can disagree by design: several sends can be written up under one shared header. Neither
    counter is broken; they are answering different questions, and only one of them is the 3-3-3.

    The STAMP uses the send-log count, because every other field in that line (sent, replied, rate)
    is a send-log figure and consistency-check [13] already counts the loop the same way. Sourcing
    one field of one line from a different store makes the line internally incoherent.

    But which counter is the 3-3-3 is YOUR ruling, not this file's, so the disagreement is PRINTED
    rather than papered over. Two counters disagreeing about what a send IS is a defect class this
    pipeline has already paid for once.
    """
    d = today or date.today().isoformat()
    a, b = sends_today(d, repo), sends_today_logged(d, repo)
    return (a, b) if a != b else None


def stale_drafted(today=None, repo=None):
    """send-log rows still `drafted` from BEFORE today, formatted for display.

    mail-draft.sh writes an UNSENT status on every row it creates: it makes a visible mail draft
    and cannot know whether you pressed Send. The flip to "sent" is manual. Nothing watched that
    store at first, so a missed flip left a real send invisible to rung_ladder (excluded as
    undelivered) with no tripwire anywhere.

    ⛔ THE SPELLING IS NOT ONE STRING, AND ASSUMING IT WAS MADE THIS FUNCTION DEAD. This docstring
    used to claim the status is always "drafted". It is not: `mail-draft.sh` declares
    `STAGED_STATUS = "staged"` and writes that, so the test below matched a value nothing in this
    tree ever produced and the stale-draft alert could never fire for a partner. Both spellings are
    accepted, because an install upgraded from an older kit can hold rows written either way, and a
    reader that recognizes only the current spelling silently drops the history.

    Today's drafts are legitimately unflipped, so the grace period is the whole of today.

    A drafted row is SUPERSEDED when a later row for the same message (same recipient, same subject,
    same date) carries a delivered status. mail-draft.sh writes the drafted row, then the manual
    flip appends a second row rather than rewriting the first, because the log is append-only.
    Without this check the staging row is reported as an open item forever, even after the send is
    confirmed elsewhere.
    """
    d = today or date.today().isoformat()
    rows = []
    for line in _rd("documents/send-log.jsonl", repo).splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue

    def key(r):
        return (str(r.get("to", "")), str(r.get("subject", "")), str(r.get("date", "")))

    delivered = {key(r) for r in rows
                 if str(r.get("status", "")).lower() not in NOT_DELIVERED}

    out = []
    for r in rows:
        if str(r.get("status", "")).lower() not in UNSENT_STATUSES or (r.get("date") or "") >= d:
            continue
        if key(r) in delivered:
            continue
        out.append(f"{r.get('date')} · {r.get('company') or '?'} · {str(r.get('to', ''))[:38]}")
    return out


# Inbound rows that are machinery or a closed outcome, not a person waiting on an answer. A bounce
# arms nothing (HARD-INVARIANTS SEND GATE), an out-of-office is not a reply, a rejection needs no
# answer, and a connection ACCEPTANCE is a rung 1-2 outcome to work later, never a message owed a
# response (an acceptance is not an outcome, it is an entry into the 1st-degree pool).
_NOT_A_REPLY = re.compile(r"bounce|auto[\s-]?respond|auto[\s-]?acknowledg|out[\s-]?of[\s-]?office|"
                          r"no[\s-]?reply|mailer[\s-]?daemon|rejection|connection accepted|"
                          r"backfill", re.I)

# ⚠️ A SHIPPED DEFAULT, NOT YOUR RULING. An inbound that has sat for a fortnight is either dead or
# was answered somewhere the log never learned about, and neither is today's default. render()
# prints the provenance caveat covering the whole table. Same reasoning as every calibrated check
# here: one that is permanently red is one nobody reads.
INBOUND_OPEN_DAYS = 14

_EVENT = re.compile(r"^#{2,4}\s*[^\n]*?(\d{4}-\d{2}-\d{2})[^\n]*$", re.M)


def inbound_rows(repo=None):
    """Every inbound header in correspondence-log.md, in FILE order (newest on top, its own rule).

    Kept as the RAW scan because session_start displays it verbatim and has since 2026-07-25. The
    decision table reads open_inbound() instead, which is a different question.
    """
    return re.findall(r"^##[^\n]*(?:📥|INBOUND)[^\n]*$", _rd("documents/correspondence-log.md", repo),
                      re.M)


def _correspondent(line):
    """The other party's name out of an event header. `← Name` inbound, `→ Name` outbound.

    🔴 F4 (verifier, 2026-07-27): a thread closed by a TEXT carries no arrow at all. A live header
    can read `📤 OUTBOUND · SomeCo — TEXT to Jane Doe (SMS, post-application)`, which is literally
    the human's own sentence about the contact, and an arrow-only parse read its correspondent as
    NOBODY, so the closed-thread reader could never see the close. The fallback keys on `to <Name>`
    / `with <Name>` with a capitalized name, so channel words like "TEXT to" and "call with"
    resolve while prose fragments stay unmatched.
    """
    m = re.search(r"[←→]\s*([^\[\(|—]+)", line)
    if not m:
        m = re.search(r"\b(?:to|with)\s+([A-Z][^\[\(|—·]*)", line)
    return re.sub(r"\s+", " ", m.group(1)).strip(" ·-,").lower() if m else ""


def _norm_name(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def closed_threads(repo=None):
    """Names and companies whose outreach_log thread records a COMPLETED outcome.

    ⛔ REUSE, NOT A FOURTH PARSER. The "is this thread done" question already has an answer in
    `check_followups.is_completed`, which knows `status:done`, `FOLLOWUP-DUE: none`, completion
    markers and the "if no reply is ARMING language" correction. This repo has paid four times for
    a second reader of these logs, and the LAST time was exactly such a thread: session_start's
    private follow-up regex opened every session with a phantom 🔴 on a thread that had closed out
    end to end.
    """
    try:
        import check_followups
    except Exception:
        return set()
    closed = set()
    for block in re.split(r"(?=^## )", _rd("outreach_log.md", repo), flags=re.M):
        head = block.splitlines()[0] if block.strip() else ""
        if not head.startswith("## ") or not check_followups.is_completed(block):
            continue
        # Header shape: `## 2026-07-17 · Acme (acme.com) · Jane Roe (Co-founder…) — …`
        # Both the COMPANY and the PERSON are keys, because an inbound header may name either.
        # Everything from the first `(` is dropped, INCLUDING an unclosed one: splitting on `—`
        # first cuts `(Co-founder & Co-CEO — builder)` in half, so a balanced-paren strip left
        # "jane roe co founder co ceo" as the key and the person was never matchable.
        for seg in re.split(r"·|—|–", re.sub(r"^\s*#+\s*", "", head)):
            seg = _norm_name(re.sub(r"[^\w&.' -]", " ", seg.split("(")[0]))
            if len(seg) >= 4 and not re.fullmatch(r"[\d ]+", seg):
                closed.add(seg)
    return closed


def open_inbound(today=None, repo=None):
    """Inbound messages somebody is still owed an answer to. Best effort, deliberately.

    WHY NOT THE RAW SCAN. session_start's line counts every 📥 header the file has ever carried,
    which is the right shape for "here is what exists" and the wrong shape for "what do I owe". As
    a PREDICATE it is permanently true, because the log is an archive, so P1 would win every
    derivation forever and the four rows below it would be dead code.

    🔴 THE DEFECT THIS SHAPE FIXES, found on the first live run. v1 paired inbound to outbound by
    CORRESPONDENT NAME across the whole file, and it proposed replying to someone whose thread was
    long closed. Three separate records already said so and none was read: the thread's own later
    OUTBOUND (a reply-all whose recipient field the name matcher could not parse), the outreach_log
    block carrying `status:done … Nothing is owed`, and a correspondence header stating the
    conversion was complete end to end.

    The general shape of the miss: a MATCHMAKER intro resolves through a downstream action to a
    DIFFERENT person, so pairing on the sender's own name can never see the close.

    THREE LAYERS NOW, cheapest first, any one of them closes the thread:
      L1  the thread block holds a LATER outbound than the inbound (answered in-thread, whoever it
          was addressed to). This alone catches the referral-handoff case.
      L2  an explicit closure: `check_followups.is_completed` on the correspondence block, or the
          correspondent/company appearing in closed_threads() from outreach_log.
      L3  a later outbound to the same correspondent ANYWHERE in the file, for the many events that
          are their own standalone `## <date> · 📥 INBOUND` block rather than part of a thread.

    HONEST LIMIT: a reply sent and never logged anywhere still reads as open. It surfaces as one
    extra suggestion in a picker you can overrule in a click, which is the cheap direction.
    """
    d = today or date.today().isoformat()
    src = _rd("documents/correspondence-log.md", repo)
    closed = closed_threads(repo)

    latest_out = {}                       # L3: newest outbound per correspondent, whole file
    for m in _EVENT.finditer(src):
        line = m.group(0)
        if "📤" in line or re.search(r"\bOUTBOUND\b", line):
            who = _norm_name(_correspondent(line))
            if who:
                latest_out[who] = max(latest_out.get(who, ""), m.group(1))

    out = []
    for block in re.split(r"(?=^## )", src, flags=re.M):
        head = block.splitlines()[0] if block.strip() else ""
        if not head.startswith("## "):
            continue
        events = []
        for m in _EVENT.finditer(block):
            line = m.group(0)
            if "📥" in line or re.search(r"\bINBOUND\b", line):
                events.append((m.group(1), line, True))
            elif "📤" in line or re.search(r"\bOUTBOUND\b", line):
                events.append((m.group(1), line, False))
        ins = [e for e in events if e[2]]
        if not ins:
            continue
        newest_in = max(ins, key=lambda e: e[0])
        outs = [e[0] for e in events if not e[2]]
        if outs and max(outs) >= newest_in[0]:
            continue                                          # L1: answered inside the thread
        if check_followups_is_completed(block) or check_followups_is_completed(head):
            continue                                          # L2a: explicit closure in-block
        line = newest_in[1].strip()
        if _NOT_A_REPLY.search(line) or _NOT_A_REPLY.search(head):
            continue
        who = _norm_name(_correspondent(line)) or _norm_name(_correspondent(head))
        if not who:
            continue
        # L2b: outreach_log's block for this person or company records a completed outcome.
        # EXACT membership only. A prefix or substring rule was tried and removed the same hour:
        # `closed` legitimately holds short brand keys ("zylo", "apt"), and a fuzzy match on those
        # silently closes unrelated people. Over-closing here is invisible, which is the failure
        # direction this file is least able to notice.
        if who in closed:
            continue
        if _days_between(newest_in[0], d) > INBOUND_OPEN_DAYS:
            continue
        if latest_out.get(who, "") >= newest_in[0]:
            continue                                          # L3: answered elsewhere in the file
        out.append(line)
    return out


def check_followups_is_completed(text):
    """Thin import shim so a missing check_followups degrades to 'not closed' instead of raising."""
    try:
        import check_followups
        return bool(check_followups.is_completed(text))
    except Exception:
        return False


def _days_between(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except Exception:
        return 0


def inbound_name(header):
    """The correspondent's name out of an inbound header, best effort.

    Two live shapes: `📥 INBOUND ← Jane Roe [LinkedIn, 1:45 PM]` and
    `📥 INBOUND · Acme — bounce for ...`. Prefer the arrow, which names a PERSON.
    """
    m = re.search(r"←\s*([^\[\(|]+)", header)
    if not m:
        m = re.search(r"(?:📥|INBOUND)\s*[·-]\s*([^\[\(|—]+)", header)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip(" ·-—,")


# ── THE LADDER ────────────────────────────────────────────────────────────────────────────────

def ladder_counts(repo=None):
    """(agg, dropped) from documents/send-log.jsonl, computed by rung_ladder, never re-joined.

    rung_ladder.load() raises FileNotFoundError on a fresh install (its own SENDLOG constant is
    unguarded, rung_ladder.py:66-68). A missing log is the partner-kit path and the day-one path,
    both of which must brief rather than crash — so it degrades to an empty ladder and the caller
    prints step one.
    """
    try:
        import rung_ladder
        rows = rung_ladder.load(os.path.join(repo or REPO, "documents", "send-log.jsonl"))
        return rung_ladder.tally(rows)
    except Exception:
        return {}, 0


def ladder_health(repo=None):
    """(healthy, detail). Tells a log that is truly at zero apart from one that cannot be read.

    ladder_counts() degrades to a zeroed ladder on ANY failure, which is right for a briefing and
    wrong for a gate: on 2026-07-27 the verifier showed a corrupt send log producing a well formed
    `sent 0 · replied 0` stamp that the gate then instructed the model to show as live (F3, an
    honesty failure). A MISSING log is healthy, because day one really is at zero. A file that
    raises on read, or a non-empty file with no parseable row, is not, and a gate consulting this
    must stand down rather than present zeros.
    """
    p = os.path.join(repo or REPO, "documents", "send-log.jsonl")
    if not os.path.exists(p):
        return True, "absent"
    try:
        import rung_ladder
        rows = rung_ladder.load(p)
    except Exception as e:
        return False, f"unreadable ({e.__class__.__name__})"
    try:
        size = os.path.getsize(p)
    except OSError:
        size = 0
    if not rows and size:
        return False, "no parseable row in a non-empty log"
    return True, "ok"


def totals(repo=None):
    agg, _ = ladder_counts(repo)
    sent = sum(v[0] for v in agg.values())
    replied = sum(v[1] for v in agg.values())
    return sent, replied


def stamp(today=None, repo=None):
    """THE STAMP. One line, recomputable, and the reason the two halves cannot be separated.

    It proves the ladder numbers you were shown matched send-log.jsonl at the moment the picker
    fired, and that the summary was not carried forward from an earlier message in the session
    (the drift this rule exists to stop). It does NOT prove the chat prose above the picker rendered
    the full table — a hook cannot see chat prose. That is exactly why the stamp lives INSIDE the
    picker: even if the prose half drifts, the numbers survive in the artifact you act on.

    Middots only, NEVER an em dash: an em dash in option text blocks the picker outright
    (check_preview.py:607-608), and a stamp that cannot render is not a gate, it is an outage.
    """
    d = today or date.today().isoformat()
    sent, replied = totals(repo)
    rate = (100.0 * replied / sent) if sent else 0.0
    return (f"LADDER {d} · sent {sent} · replied {replied} · "
            f"rate {rate:.1f}% · 3-3-3 {sends_today_logged(d, repo)}/3")


# ⚠️ SAY WHAT THE LOG SAYS, NOT WHAT IT SEEMS TO PROVE.
#
# rung_ladder reports zero `referred` rows and the obvious reading is "rung 8-9 has NEVER been
# used". That reading can be FALSE. Observed counterexample: a co-founder answered a cold email,
# CC'd the head of product as an introduction, and that produced a call, an invited application and
# a thank-you. Every message in it was logged `reply` / `thank-you` / `application`, because the
# mechanism was a reply-all inside ONE thread and the writer had no rung to reach for.
#
# So the zero is a LABELLING fact about the log, not a fact about the search. The flag stays,
# because working rung 5-7 into an explicit intro is still the right suggestion, but the WORDING
# must not assert something the data cannot support. The counting is untouched here on purpose.
REFERRED_FLAG = ("rung 8-9 (referred) carries NO rows in the send log, on {warm} warm sends. "
                 "That is a LABELLING fact, not proof it never happened: a referral that arrives "
                 "as a reply-all in one thread gets logged reply/thank-you/application.")


def referred_gap(repo=None):
    """(no_referred_rows, warm_sends). Zero rows is what this measures, never "never happened"."""
    agg, _ = ladder_counts(repo)
    return (not agg.get("referred", [0, 0])[0], agg.get("warm", [0, 0])[0])


def ladder_full(today=None, repo=None):
    """rung_ladder.render() verbatim, plus the two notes its own main() prints. Session open."""
    try:
        import rung_ladder
        agg, dropped = ladder_counts(repo)
        if not agg:
            return ("no sends on file yet. Step one of the method: 3 companies, 3 people, "
                    "3 messages.")
        out = [rung_ladder.render(agg, dropped)]
        gap, warm = referred_gap(repo)
        if gap:
            out.append("\n  🔴 " + REFERRED_FLAG.format(warm=warm) +
                       " Rung 5-7 is what produces a labelled one.")
        out.append("\n  ⚠️ Every rate above is an UPPER BOUND. Sends missing from this log shrink "
                   "the denominator\n     and inflate the rate; run scripts/reconcile_linkedin.py "
                   "for the size of that gap.")
        gap = counter_gap(today, repo)
        if gap:
            out.append(f"\n  ⚠️ The two 3-3-3 counters disagree: outreach_log `## date` headers say "
                       f"{gap[0]}, send-log rows say {gap[1]}.\n     The stamp uses the SEND-LOG "
                       f"count, the same store every other number in it comes from. Which counter "
                       f"is\n     the 3-3-3 is YOUR ruling, so this prints rather than picking "
                       f"(scripts/pair_brief.py counter_gap).")
        return "\n".join(out)
    except Exception:
        return "ladder unavailable"


# The five rungs that carry the method. Off-ladder kinds (reply, thank-you, application) are real
# work and stay in the TOTAL, they just do not belong in a compact five-line read.
CORE_RUNGS = ["cold-stranger", "cold-boss", "warm", "referred", "event"]


def ladder_compact(today=None, repo=None):
    """<=8 lines: the core rungs that have sends, the TOTAL, today's 3-3-3, one gap flag."""
    try:
        import rung_ladder
        agg, _dropped = ladder_counts(repo)
        d = today or date.today().isoformat()
        lines = []
        for k in CORE_RUNGS:
            s, rp = agg.get(k, [0, 0])
            if not s:
                continue
            lines.append(f"  {rung_ladder.RUNG_LABEL.get(k, k):24} {s:5} sent {rp:5} replied "
                         f"{(100 * rp / s):6.1f}%")
        sent, replied = totals(repo)
        lines.append(f"  {'TOTAL':24} {sent:5} sent {replied:5} replied "
                     f"{(100 * replied / sent if sent else 0):6.1f}%")
        lines.append(f"  {'3-3-3 today':24} {sends_today_logged(d, repo)}/3")
        gap = counter_gap(d, repo)
        if gap:
            lines.append(f"  ⚠️ the two 3-3-3 counters disagree: outreach_log headers say {gap[0]}, "
                         f"send-log rows say {gap[1]} (see pair_brief.counter_gap)")
        gap, warm = referred_gap(repo)
        if gap and warm:
            lines.append(f"  🔴 rung 8-9 (referred): 0 rows on {warm} warm sends "
                         f"(a labelling gap, see --full)")
        return "\n".join(lines)
    except Exception:
        return "  ladder unavailable"


# ── THE DECISION TABLE ────────────────────────────────────────────────────────────────────────

def _tripwires_due(today=None, repo=None):
    try:
        import check_tripwires
        due, _up, _undated, _cleared = check_tripwires.scan(
            date.fromisoformat(today) if today else None)
        return due
    except Exception:
        return []


def _held(name, store):
    """Belt and braces on top of rank_people's own hold filter.

    rank_people already refuses a held contact, and this re-asks the store anyway. The redundancy is
    the point: a hold is the one filter whose failure contacts somebody you said not to contact, and
    a ranker with no hold list leaves the store as the only gate. A second consult costs nothing.
    """
    try:
        import closeness
        return bool(closeness.is_held(closeness.tier_for(name, store)))
    except Exception:
        return False


def _already_contacted(name, company):
    """Belt and braces on top of rank_people's own contacted filter, the same as _held above.

    🔴 WHY THIS EXISTS. The contacted filter joined two stores on an EQUALITY test over company
    keys, and the stores spell employers differently:

        send-log.jsonl    "Pay with Example"                → paywithexample
        the network file  "Example - Pay with Example, Inc" → examplepaywithexampleinc

    So a person emailed that same morning, in the send that WAS the day's 1 of 3, came back as the
    #1 person to reach. The caller then named them as the derived default, and `check_pair.py`
    BLOCKED every picker that left them out, because check_pair validates that option 1 MATCHES
    the default and never that the default is still reachable. **A bad join became a
    gate-enforced instruction.**

    A second consult costs nothing, and this is the one filter whose failure spends real
    credibility with a real person by writing to them twice.

    ⚖️ Fails OPEN on any error. A brief that goes blank teaches the operator to stop reading it.
    """
    try:
        import re as _re

        import rank_criteria
        key = _re.sub(r"[^a-z0-9]", "", str(name).lower())
        if key and key in rank_criteria.contacted_people():
            return True
    except Exception:
        pass
    return False


def next_target(repo=None):
    """(label, source) for the next INITIAL contact. Never a person on hold.

    Falls back through people -> companies -> "refill the board", mirroring session_start's ranked
    fallbacks: a briefing that goes blank teaches the operator to stop reading it.
    """
    try:
        import closeness
        import rank_criteria
        store = closeness.load()
        people, _skipped = rank_criteria.rank_people(10)
        for c in people:
            if _held(c.get("name", ""), store):
                continue
            if _already_contacted(c.get("name", ""), c.get("company", "")):
                continue
            # The confirm state travels WITH the suggestion (2026-08-02). rank_criteria computes a
            # close_flag for inferred, doubted, unrecorded and reunion-gated rows and this line
            # used to drop it, so a machine-levelled know-well read as the human's own judgment at
            # the exact point they decide. The flag's own words, not a fixed label: the flag fires
            # for several distinct reasons and one hardcoded explanation misstates the others.
            # Em dashes are swapped out because one in picker option text blocks the picker.
            _cf = (" · ⚠️ " + str(c["close_flag"]).replace("—", "·")[:70]
                   if c.get("close_flag") else "")
            return (f"{c['name']} · {c.get('title', '')[:30]} @ {c.get('company', '')[:24]} "
                    f"· rung {c.get('rung', '?')} ({c.get('band', '')}){_cf}", "rank_people")
    except Exception:
        pass
    try:
        import rank_criteria
        ranked, _sk = rank_criteria.rank(10)
        if ranked:
            c = ranked[0]
            return (f"{c['company']} · {c.get('lane', '')[:34]} · cold-boss rung", "rank")
    except Exception:
        pass
    return ("run discovery to refill the board", "empty")


def gather(today=None, repo=None):
    """Everything the table reads, in one pass. Pure data, so decide() can be tested synthetically."""
    d = today or date.today().isoformat()
    gap, warm = referred_gap(repo)
    return {
        "today": d,
        "stale_drafted": stale_drafted(d, repo),
        "inbound": open_inbound(d, repo),
        "tripwires": _tripwires_due(d, repo),
        "sends_today": sends_today_logged(d, repo),
        "target": next_target(repo),
        "referred_gap": gap,
        "warm_sends": warm,
        # Open rows from documents/state/referral.jsonl (referral_intake.py). This is the reader
        # that makes the intake store real: a name mined from a warm reply surfaces here as ready
        # rung 8-9 supply instead of evaporating (a promotion is only as strong as its reader).
        "referrals": _open_referrals(),
    }


def _open_referrals():
    """['Name via Introducer', ...] for referrals still waiting on a send. Empty on any failure."""
    try:
        import referral_intake
        return [f"{r['referred']} via {r['introducer']}"
                for r in referral_intake.open_referrals()]
    except Exception:
        return []


def decide(state):
    """THE TABLE. Ordered, first hit wins, evaluated over an already-gathered state.

    Pure on purpose. Every predicate reads live state through an existing single-source reader in
    gather(); separating the two is what lets a test hand this function a synthetic P0-P4 state and
    assert the derived default, instead of manufacturing five whole repos.

    The method's grounding is cited per row against the primary source
    (the method's own primary source, read from the document rather than
    from recall). Where a row is a house mechanism rather than the method's, it says so.
    """
    n = state.get("sends_today", 0)
    closed = n >= 3
    # The outbound window suppresses "stop for the day" and keeps the derived default on a NEW
    # initial contact, which is the one activity the method spends 90% of its time on.
    # ⏱ The clock is INJECTABLE through the state dict so a test can pin it. Without this the
    # decision table is time-dependent: the same test passes after the cutoff and fails
    # before it, which is a test that reports the hour rather than the rule.
    outbound_window = _outbound_window_open(state.get("now"))
    if outbound_window:
        closed = False
    stop_alt = {"badge": "🟢", "label": "Stop for the day",
                "state": f"the 3-3-3 is closed at {n}/3"}

    if state.get("stale_drafted"):
        rows = state["stale_drafted"]
        return {
            "priority": "P0",
            "default": f"Confirm whether these {len(rows)} send(s) went out",
            "andy_read": [
                "THE GRID's unit of work is messages SENT, not companies eliminated.",
                "A row still marked drafted is a message nobody can say was sent, so it corrupts "
                "the count the whole method runs on.",
                "[the framing here is this kit's; the SENT rule is the method's]",
            ],
            "cite": "the method: the unit of work is messages SENT",
            "evidence": rows[:5],
            "alternates": [
                {"badge": "🟡", "label": "Work today's 3-3-3 anyway",
                 "state": f"{n}/3 sent · the unflipped rows stay unresolved"},
                {"badge": "🔴", "label": "Reconcile the whole send log",
                 "state": "wider than the rows above · reconcile_linkedin.py measures the gap"},
            ] + ([stop_alt] if closed else []),
        }

    if state.get("inbound"):
        rows = state["inbound"]
        who = inbound_name(rows[0]) or "the newest inbound"
        return {
            "priority": "P1",
            "default": f"Reply to {who}",
            "andy_read": [
                "The method's response playbook is about FIELDING an answer somebody actually "
                "sent. Only its last scenario is silence, and its line there is to move on "
                "rather than follow up.",
                "A reply never chases silence, so it survives the 2026-07-27 retirement of "
                "follow-ups intact.",
            ],
            "cite": "the method's response playbook: fielding an answer, never chasing silence",
            "evidence": [r.strip()[:80] for r in rows[:3]],
            "alternates": [
                {"badge": "🟡", "label": "Next initial contact instead",
                 "state": f"3-3-3 stands at {n}/3 · the reply waits"},
                {"badge": "🟢", "label": "Capture the thread first",
                 "state": "verbatim into correspondence-log.md, then reply"},
            ] + ([stop_alt] if closed else []),
        }

    if state.get("tripwires"):
        tw = state["tripwires"]
        first = tw[0] if isinstance(tw[0], dict) else {}
        co = first.get("company") or "company unknown"
        return {
            "priority": "P2",
            "default": f"Work the due tripwire: {co}",
            "andy_read": [
                "HOUSE MECHANISM, not the method's. A tripwire is a date you armed yourself, so it "
                "carries your authority rather than the method's.",
                "Named as house method on purpose: the card must never launder a repo mechanism "
                "as a LaCivita ruling.",
            ],
            "cite": "repo mechanism · scripts/check_tripwires.py",
            "evidence": [f"{r.get('date')} · {r.get('company') or 'company unknown'}"
                         for r in tw[:3] if isinstance(r, dict)],
            "alternates": [
                {"badge": "🟡", "label": "Next initial contact instead",
                 "state": f"3-3-3 stands at {n}/3 · the tripwire slips a day"},
                {"badge": "🟢", "label": "Clear the tripwire as no longer live",
                 "state": "a condition that cannot fire should not keep firing"},
            ] + ([stop_alt] if closed else []),
        }

    if not closed:
        label, _src = state.get("target", ("run discovery to refill the board", "empty"))
        read = [
            "The method: spend most of your time researching people and organizations, "
            "finding the right people to target, and sending them your INITIAL communication.",
            "Same source: you benefit much more from reaching out to NEW people than from "
            "chasing individuals who are not getting back to you.",
            "The rung ladder: it does not have to be perfect alignment, you just need an in.",
        ]
        if n >= 3 and outbound_window:
            read.append(
                f"HOUSE METHOD, not Andy's: the 3-3-3 is already met at {n}/3, and the outbound "
                f"window keeps the day open. 'Stop for the day' is not offered before "
                f"{OUTBOUND_WINDOW_CLOSES_ET}:00 ET. 3-3-3 is the daily floor, never a cap. "
                f"Set pair_brief.OUTBOUND_WINDOW_CLOSES_ET to your own hour, or 0 to turn it off.")
        alts = [
            {"badge": "🟡", "label": "Refill the board with a discovery run",
             "state": "widens tomorrow's pool · sends nothing today"},
            {"badge": "🟢", "label": "Screening debt on the banked pool",
             "state": "converts banked rows into rankable ones"},
        ]
        if state.get("referred_gap") and state.get("warm_sends"):
            read.append(REFERRED_FLAG.format(warm=state["warm_sends"]) +
                        " Rung 5-7 is the only thing that produces a labelled one.")
            alts.insert(0, {"badge": "🔴", "label": "Ask a close-tier contact for the intro (rung 8-9)",
                            "state": f"0 rows on {state['warm_sends']} warm sends · the rung is "
                                     f"unlabelled in the log, not proven unused"})
        if state.get("referrals"):
            # A mined name outranks the generic "go ask someone" alt above: it IS the rung 8-9
            # supply that alt keeps asking for. Inserted last so it lands first. New key, so
            # synthetic decide() states without it are unchanged.
            _refs = state["referrals"]
            alts.insert(0, {"badge": "🔴",
                            "label": f"Draft the referred send: {_refs[0]} (rung 8-9)",
                            "state": f"{len(_refs)} open referral(s) recorded and waiting · "
                                     "the conveyor's first labelled output"})
        return {
            "priority": "P3",
            "default": f"Next initial contact: {label}",
            "andy_read": read,
            "cite": "the method: most of your time on INITIAL communication · the person pivot",
            "evidence": [f"3-3-3 at {n}/3", f"target source: {state.get('target', ('', ''))[1]}"],
            "alternates": alts,
        }

    return {
        "priority": "P4",
        "default": "Stop for the day",
        "andy_read": [
            "The loop closed: 3 messages are out, and the method's daily unit is done.",
            "The method's own framing is a never-ending daily loop, not a longer day. Deskwork after "
            "the loop closes is deskwork.",
        ],
        "cite": "the method's daily loop",
        "evidence": [f"3-3-3 at {n}/3"],
        "alternates": [
            {"badge": "🟡", "label": "Refill the board with a discovery run",
             "state": "the ranked board thins out as targets are worked"},
            {"badge": "🟢", "label": "Screening debt on the banked pool",
             "state": "banked rows are not rankable until they are screened"},
        ],
    }


def open_bugs(repo=None):
    """The OPEN rows of documents/BUG-LOG.md, in the order they were written.

    Deliberately dumb: a row is `- [ ]` under the OPEN heading and its label is the bolded title.
    A parser needing structured front matter would be a second thing to keep in sync, and the log
    is written for a human first.
    """
    src = _rd("documents/BUG-LOG.md", repo)
    if not src:
        return []
    body = src.split("## OPEN", 1)[-1].split("## FIXED", 1)[0]
    out = []
    for m in re.finditer(r"^- \[ \]\s+\*\*(BUG-\d+)\*\*\s*(\S*)\s*\*\*(.+?)\*\*", body, re.M | re.S):
        out.append({"id": m.group(1), "sev": m.group(2),
                    "title": re.sub(r"\s+", " ", m.group(3)).strip().rstrip(".")})
    return out


def bug_alternate(repo=None):
    """The single always-last alternate for bug and test work, or None when the log is clean."""
    bugs = open_bugs(repo)
    if not bugs:
        return None
    top = bugs[0]
    reds = sum(1 for b in bugs if b["sev"] == "🔴")
    state = f"{len(bugs)} open in documents/BUG-LOG.md"
    if reds:
        state += f" · {reds} 🔴"
    state += f" · top: {top['id']} {top['title']}"
    return {"badge": "🐞", "label": "Bug and test work (never interrupts 3-3-3)", "state": state}


# ⛔ BUG AND TEST WORK IS NEVER THE DERIVED DEFAULT.
#
# Two rules, both mechanized here rather than left to whoever authors the picker on a given day:
#   1. never the default at any priority  → the guard inside derive()
#   2. always present, always LAST        → bug_alternate() appended after every other alternate
#
# Why mechanize something this small: on the day it was written the day's real finding WAS a bug,
# and the pull to lead with it was strong. The daily unit is 3 messages sent, and deskwork that
# displaces a send is deskwork. A bug that BLOCKS a send is not bug work, it is the send, and it
# reaches the picker on its own merits rather than through this row.
NEVER_DEFAULT_BUGS = re.compile(r"\bbugs?\b|\bdefects?\b|\btest suite\b|\bred tests?\b|"
                                r"\bfix the (?:tests?|suite)\b", re.I)

# ⛔ THE 3-3-3 IS A WORKDAY LOOP, AND THIS FILE USED TO HAVE NO IDEA WHAT DAY IT WAS. On a Saturday
# it kept deriving "send your first contact of the day", so every picker read as a nag about a
# counter that should not have been running. The 3-3-3 stays VISIBLE on a weekend, because the
# number is a fact; what changes is that a send stops being the derived DEFAULT. The alternates are
# untouched, so a weekend you DO want to work is still one pick away.
#
# Same shape as the bug-work rule above: asserted at derivation, so no decide() branch can quietly
# put a send back on a day off.
WEEKEND = (5, 6)   # Saturday, Sunday

# What counts as a send-shaped default, for the weekend rule below.
SEND_SHAPED = re.compile(r"\binitial contact\b|\breach out\b|\bnext contact\b|"
                         r"\bsend\b|\boutreach\b|\bfirst contact\b", re.I)


def _is_weekend(today=None):
    """True on Saturday or Sunday. Accepts a date, an ISO string, or None for today."""
    import datetime
    d = today or datetime.date.today()
    if isinstance(d, str):
        try:
            d = datetime.date.fromisoformat(d[:10])
        except ValueError:
            # An unparseable stamp is not evidence of a weekend. Fail toward the working-day
            # behaviour rather than silently muting a send-shaped default on a Tuesday.
            return False
    return d.weekday() in WEEKEND


def derive(today=None, repo=None):
    d = decide(gather(today, repo))
    # The one shape that can never be derived, asserted at the point of derivation rather than
    # trusted to a comment. A silence-chasing default is retired at EVERY rung.
    if FORBIDDEN_DEFAULTS.search(d["default"]):
        d["default"] = "Next initial contact: run discovery to refill the board"
        d["andy_read"] = ["A follow-up that chases silence is retired at every rung "
                          "(documents/HARD-INVARIANTS.md). Falling back to a new initial contact."]
    # Rule 1: bug work never leads. Asserted at derivation, the same shape as FORBIDDEN_DEFAULTS
    # above, so a future decide() branch cannot quietly promote it.
    if NEVER_DEFAULT_BUGS.search(d["default"]):
        d["default"] = "Next initial contact: run discovery to refill the board"
        d["andy_read"] = ["Bugs and tests never interrupt the 3-3-3 unless you ask for it. "
                          "Falling back to a new initial contact; the bug row is still "
                          "available as the last alternate."]
    # Rule 1b: NOT ON A WEEKEND. A send-shaped default on a Saturday is the pipeline pressuring a
    # loop that is not running. The alternates stay, so if you want to work you still can.
    if _is_weekend(today) and SEND_SHAPED.search(d["default"]):
        d["default"] = "Rest. The 3-3-3 is a workday loop and today is not a work day"
        d["andy_read"] = ["The method's loop is daily on WORKING days. A weekend nag is the "
                          "pipeline pressuring a counter that should not be running.",
                          "The ladder is still shown, because the number is a fact. The alternates "
                          "are still there if you want them."]
        d["priority"] = "P5"
    # NAME THE METHOD IN THE LABEL ITSELF, here rather than in render(), so that BOTH surfaces the
    # agent can copy from (the printed brief and --json's "default") carry it. This is what makes a
    # picker built verbatim from this tool pass check_pair --hook-ask.
    name = method_name()
    if name and name.lower() not in d["default"].lower():
        d["default"] = f"{name}'s pick: {d['default']}"
    # 📰 UNREAD RELEASE NOTES BECOME A PICKER OPTION, appended LAST and never the default.
    # Same rule as bug work: reading about the kit is not outreach, and it must never displace the
    # 3-3-3. But an update that changed how the ranker orders people is worth a slot, because the
    # alternative is a partner quietly distrusting a list they cannot explain.
    try:
        import release_notes
        _new = release_notes.unseen()
        if _new:
            d.setdefault("alternates", []).append({
                "badge": "📰",
                "label": "Read what changed in the kit (never interrupts the 3-3-3)",
                "state": f"{len(_new)} unread release note(s) · newest {_new[0][0]} · "
                         f"python3 scripts/release_notes.py",
            })
    except Exception:
        pass
    # Rule 2: bug work is always present and always LAST. Appended after every branch's own
    # alternates AND after the release-notes row, so its position never depends on which priority
    # fired or on which optional rows happened to be added.
    _alt = bug_alternate(repo)
    if _alt:
        d["alternates"] = list(d.get("alternates", [])) + [_alt]
    return d


# ── RENDERING ─────────────────────────────────────────────────────────────────────────────────

def render(full=False, today=None, repo=None):
    d = derive(today, repo)
    out = ["── THE PAIR ──", "",
           "LADDER", ladder_full(today, repo) if full else ladder_compact(today, repo), "",
           "STAMP (paste this INTO the picker, verbatim)", f"  {stamp(today, repo)}", "",
           f"THE METHOD'S READ ({d['priority']})"]
    for line in d["andy_read"]:
        out.append(f"  · {line}")
    out.append(f"  source: {d['cite']}")
    out.append("")
    out.append("DEFAULT (option 1, name it as the method's)")
    out.append(f"  🧭 {d['default']}")
    for e in d.get("evidence", []):
        out.append(f"       {e}")
    out.append("")
    out.append("ALTERNATES")
    for a in d["alternates"]:
        out.append(f"  {a['badge']} {a['label']}  ·  {a['state']}")
    out.append("")
    out.append("PICKER QUESTION + HEADER (use these verbatim; build vocabulary self-blocks)")
    out.append(f"  question: {question_for(today, repo)}")
    out.append(f"  header:   {HEADER_TEMPLATE}")
    out.append("")
    out.append(f"  {PRIORITY_PROVENANCE}")
    return "\n".join(out)


def as_json(today=None, repo=None):
    d = derive(today, repo)
    return {
        "stamp": stamp(today, repo),
        "marker": PAIR_MARKER,
        "question": question_for(today, repo),
        "header": HEADER_TEMPLATE,
        "priority": d["priority"],
        "default": d["default"],
        "alternates": d["alternates"],
        "andy_read": d["andy_read"],
        "cite": d["cite"],
        "evidence": d.get("evidence", []),
        "ladder_compact": ladder_compact(today, repo),
        "provenance": PRIORITY_PROVENANCE,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="The ladder summary + the derived next-step default")
    ap.add_argument("--full", action="store_true", help="whole ladder table (session open)")
    ap.add_argument("--json", action="store_true", help="machine-readable, for hooks and tests")
    ap.add_argument("--stamp", action="store_true", help="the stamp line alone")
    a = ap.parse_args(argv)
    if a.stamp:
        print(stamp())
    elif a.json:
        print(json.dumps(as_json(), ensure_ascii=False, indent=2))
    else:
        print(render(full=a.full))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # a brief that crashes must never block a session from opening
        print(f"[pair_brief] unavailable ({type(e).__name__}). "
              f"Run: python3 scripts/rung_ladder.py")
        sys.exit(0)
