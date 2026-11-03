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
try:
    import local_day as _local_day  # BUG-795: "today" for send-log readers is the writers' day
except ImportError:  # a partial copy of scripts/ keeps the machine calendar
    _local_day = None


def _send_day():
    return _local_day.today() if _local_day else date.today().isoformat()

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

# The delivered/undelivered vocabulary is IMPORTED, never re-typed (it lives with the writer).
from log_linkedin_send import NOT_DELIVERED  # noqa: E402

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

# ⏰ THE OUTBOUND WINDOW. The brief keeps the day open until this hour, local Eastern, and never offers a stop at any hour.
#
# ⛔ HOUSE METHOD, not LaCivita. The kit owner who wrote this ruled that mornings are for OUTBOUND
# and that hitting 3 messages does not end the day: 3-3-3 is the daily FLOOR, never a cap. The card
# must say so rather than laundering a personal cadence as a LaCivita ruling.
#
# ⚠️ THIS VALUE IS A PROPOSAL FOR YOU, NOT A RULING YOU MADE. It ships at 16 so a paired session
# behaves the same on both machines. It is YOUR cadence to set: change the hour, or set it to 0 to
# turn the window off entirely.
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
    # 🕰 A DECLARED END-OF-DAY BEATS THE HOUR CONSTANT.
    # ⛔ WHY THE CONSTANT ALONE IS NOT ENOUGH. `OUTBOUND_WINDOW_CLOSES_ET` is a FLOOR for keeping the
    # day open, and without this it silently does a second job it was never given: deciding the day
    # ENDS at that hour. One minute past the floor the brief reads the 3-3-3 as closed and leads with
    # the next-loop branch, so a late evening you meant to work has no way to say so.
    # ⚖️ Raising the constant would fix one evening and hide the real gap, which is that there is no
    # way to SAY when your day ends. This reads a declaration, so a late day and an early one are
    # both expressible and neither needs a code change.
    end = _declared_workday_end(now)
    if end is not None:
        return now.hour + now.minute / 60.0 < end
    return now.hour < OUTBOUND_WINDOW_CLOSES_ET


BOSS_HUNTING_PAUSE_FILE = os.path.join(REPO, "documents", "state", "boss-hunting-pause.json")


def _boss_hunting_paused(repo=None):
    """True when documents/state/boss-hunting-pause.json marks outreach paused. Used only to
    note the pause in the printed brief's DEFAULT section -- it never changes what derive()
    computes as the default itself, only whether the DEFAULT block notes that the method's
    default is paused. Fails closed to "not paused" on any read/parse error."""
    try:
        with open(os.path.join(repo or REPO, "documents", "state", "boss-hunting-pause.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        return bool(data.get("paused"))
    except Exception:
        return False


WORKDAY_FILE = os.path.join(REPO, "documents", "state", "workday.json")


def _declared_workday_end(now):
    """The hour (float, local) you said today ends, or None when you have not said.

    ⚠️ TODAY ONLY, ON PURPOSE. The row carries the date it was declared for and is ignored on any
    other date, so a late Tuesday cannot quietly become a standing rule. Forgetting to clear it is
    the likely failure, and this makes forgetting harmless.
    """
    try:
        with open(WORKDAY_FILE, encoding="utf-8") as fh:
            row = json.load(fh)
    except Exception:
        return None
    if str(row.get("date") or "") != now.strftime("%Y-%m-%d"):
        return None
    try:
        hh, _, mm = str(row.get("until_et") or "").partition(":")
        end = int(hh) + (int(mm) / 60.0 if mm else 0.0)
    except ValueError:
        return None
    # ⛔ NEVER SHORTEN THE FLOOR. A declaration may extend the outbound window, never cut it below
    # the configured hour — otherwise "I am done at 11" resurrects the premature stop prompt that
    # the window exists to prevent.
    return max(end, float(OUTBOUND_WINDOW_CLOSES_ET))


def _workday_declared(today=None, now=None):
    """True only while a DECLARED workday window is STILL OPEN for `today` (local time).

    🕰 A DECLARED WORKDAY BEATS THE WEEKEND REST OVERRIDE. Same shape as _declared_workday_end
    beating the configured floor: the weekend rule forces "Rest" because the file assumes Sat/Sun is
    not a work day, but when you have said today IS a work day the assumption is wrong and the
    send-shaped default must stand.

    ⛔ WITHIN THE WINDOW, NOT THE WHOLE DAY. It honors the declared end the way its sibling
    _declared_workday_end does, so once the declared window closes the honest weekend default
    returns; matching the DATE alone would re-plant the weekend nag for the rest of the calendar day.
    TODAY ONLY: a stale declaration for another date is ignored. Fails CLOSED on every error path, so
    a missing/malformed file leaves the weekend Rest override in place. `now` is injectable for tests.
    """
    import datetime
    n = now or datetime.datetime.now()
    if isinstance(today, str):
        d = today[:10]
    elif today is not None:
        d = today.strftime("%Y-%m-%d")
    else:
        d = n.strftime("%Y-%m-%d")
    try:
        with open(WORKDAY_FILE, encoding="utf-8") as fh:
            row = json.load(fh)
    except Exception:
        return False
    if not isinstance(row, dict) or str(row.get("date") or "") != d:
        return False
    try:
        hh, _, mm = str(row.get("until_et") or "").partition(":")
        end = int(hh) + (int(mm) / 60.0 if mm else 0.0)
    except (ValueError, AttributeError):
        return False
    return (n.hour + n.minute / 60.0) < end


def _set_working_until(value):
    """Record when TODAY ends. `clear` removes the declaration. Prints what it did."""
    if str(value).strip().lower() == "clear":
        try:
            os.remove(WORKDAY_FILE)
            print(f"🕰 workday declaration cleared — the {OUTBOUND_WINDOW_CLOSES_ET}:00 floor "
                  f"governs again.")
        except FileNotFoundError:
            print("🕰 nothing to clear.")
        return
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        today = datetime.now().strftime("%Y-%m-%d")
    hh, _, mm = str(value).partition(":")
    try:
        hh, mm = int(hh), int(mm or 0)
    except ValueError:
        print(f"🔴 could not read {value!r} as HH:MM — nothing recorded.")
        return
    os.makedirs(os.path.dirname(WORKDAY_FILE), exist_ok=True)
    with open(WORKDAY_FILE, "w", encoding="utf-8") as fh:
        json.dump({"date": today, "until_et": f"{hh:02d}:{mm:02d}"}, fh, indent=2)
    print(f"🕰 today ends {hh:02d}:{mm:02d}. The brief will not suggest ending the day before then.")


PRIORITIES = ["P0", "P1", "P2", "P3", "P4"]

# ⛔ NEVER DERIVABLE AT ANY PRIORITY (documents/HARD-INVARIANTS.md SEND GATE): a follow-up or bump
# that chases silence. The method's own line is to make the initial contact and then move on. A
# reply, a thank-you and the person pivot stay allowed, because none of them chases silence.
FORBIDDEN_DEFAULTS = re.compile(r"\bfollow[\s-]?up\b|\bbump\b|\bnudge (?:them|him|her)\b|"
                                r"\bchase\b|\bcheck in (?:on|with)\b|\bping (?:them|him|her)\b",
                                re.I)


def _open_sendlog(path, errors="ignore"):
    """The send log as a reader should see it: the file plus any spooled change not yet folded in (sendlog_lock.open_lines). Readers take no lock.
    A copy of scripts/ without sendlog_lock.py reads the file as it always did."""
    try:
        import sendlog_lock
    except ImportError:
        import importlib.util
        try:
            _spec = importlib.util.spec_from_file_location("sendlog_lock", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sendlog_lock.py"))
            sendlog_lock = importlib.util.module_from_spec(_spec)
            sys.modules["sendlog_lock"] = sendlog_lock
            _spec.loader.exec_module(sendlog_lock)
        except (OSError, ImportError):
            sys.modules.pop("sendlog_lock", None)
            return open(path, encoding="utf-8", errors=errors)
    return sendlog_lock.open_lines(path, errors)


def _rd(rel, repo=None):
    try:
        with open(os.path.join(repo or REPO, rel), encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception:
        return ""


def _rd_sendlog(repo=None):
    """The send log's text as the board should see it: the file plus any spooled change not yet folded in. "" when unreadable."""
    try:
        with _open_sendlog(os.path.join(repo or REPO, "documents", "send-log.jsonl")) as fh:
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
    d = today or _send_day()
    return len(re.findall(r"^##\s*" + re.escape(d), _rd("outreach_log.md", repo), re.M))


def sends_today_logged(today=None, repo=None):
    """Today's 3-3-3 count from send-log.jsonl, excluding rows that reached nobody.

    ⛔ NOT_DELIVERED IS IMPORTED, never re-typed. The set lives in log_linkedin_send and reaches
    here through rung_ladder, so the ladder's denominator and this counter cannot disagree about
    what a delivered send IS. That parity has failed before: consistency-check [13] once counted a
    hard bounce as outreach and printed "3/3 loop closed" on a day when one of the three reached
    nobody. Excluded statuses are named in ONE place for exactly that reason.
    """
    d = today or _send_day()
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
    for line in _rd_sendlog(repo).splitlines():
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
    d = today or _send_day()
    a, b = sends_today(d, repo), sends_today_logged(d, repo)
    return (a, b) if a != b else None


def stale_drafted(today=None, repo=None):
    """send-log rows still unresolved (UNSENT_STATUSES) from BEFORE today, formatted for display.

    mail-draft.sh writes an UNSENT status on every row it creates: it makes a visible mail draft
    and cannot know whether you pressed Send. The flip to "sent" is manual. Nothing watched that
    store at first, so a missed flip left a real send invisible to rung_ladder (excluded as
    undelivered) with no tripwire anywhere.

    Today's drafts are legitimately unflipped, so the grace period is the whole of today.

    The supersede check (does a resolving row EXIST for this message, never whether it is LATER)
    is `board.unresolved_drafts()` -- shared with `board.staged_sends()` so the two producers
    cannot diverge on this the way board.py's own copy used to (it split on date only, with no
    supersede check at all, and reported real, confirmed sends as open work every session).

    ⛔ IMPORTED LAZILY, HERE, NOT AT MODULE LEVEL (2026-09-12). A module-level `import board`
    made this whole module unimportable in any execution context that copies pair_brief.py
    without board.py alongside it -- a real regression on the main-tree twin of this function,
    caught by a test that isolates scripts/ in a temp copy. Only this function needs board.py.
    """
    import board  # noqa: PLC0415
    d = today or _send_day()
    rows = []
    for line in _rd_sendlog(repo).splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue

    out = []
    for r in board.unresolved_drafts(rows):
        if (r.get("date") or "") >= d:
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
    d = today or _send_day()
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
        # `closed` legitimately holds short brand keys ("zqfake", "apt"), and a fuzzy match on those
        # silently closes unrelated people. Over-closing here is invisible, which is the failure
        # direction this file is least able to notice.
        if who in closed:
            continue
        if _days_between(newest_in[0], d) > INBOUND_OPEN_DAYS:
            continue
        if latest_out.get(who, "") >= newest_in[0]:
            continue                                          # L3: answered elsewhere in the file
        out.append(line)

    # Everything above reads ONLY correspondence-log.md, which is written by hand — so a message
    # that arrived and was never logged reads as ANSWERED, the dangerous direction for a row that
    # decides whether the day opens on an owed reply. `check_inbound.py` reads `messages.csv`
    # itself (the complete inbox record) and reports anyone the RAW ARCHIVE shows wrote in with no
    # later reply, independent of whether a human ever typed the thread in here. Age-gated to
    # ~2 days (`check_inbound.DEFAULT_AGE_DAYS`), deliberately shorter than and separate from this
    # function's own 14-day `INBOUND_OPEN_DAYS` window, which governs the different, already-logged
    # signal above. Fails open to [] on any error — a degraded archive read must not crash the
    # whole briefing, only lose its own supplemental signal.
    # The archive is a STATIC export: it cannot see a reply logged after the snapshot was taken,
    # and it cannot read a human closure ruling in a thread header. Both live in
    # correspondence-log.md, parsed above — consult them before re-offering an archive row as
    # owed, or the default names people the owner already answered weeks ago. Same closure
    # semantics as the main loop's L2a/L3, applied to the supplemental rows.
    log_closed = set()
    for block in re.split(r"(?=^## )", src, flags=re.M):
        head = block.splitlines()[0] if block.strip() else ""
        if not head.startswith("## "):
            continue
        if check_followups_is_completed(head) or check_followups_is_completed(block):
            for seg in re.split(r"·|—|–", re.sub(r"^\s*#+\s*", "", head)):
                seg = _norm_name(re.sub(r"[^\w&.' -]", " ", seg.split("(")[0]))
                if len(seg) >= 4 and not re.fullmatch(r"[\d ]+", seg):
                    log_closed.add(seg)
            for m in _EVENT.finditer(block):
                w = _norm_name(_correspondent(m.group(0)))
                if w:
                    log_closed.add(w)

    already = {_norm_name(_correspondent(l)) for l in out} - {""}
    try:
        import check_inbound
        for row in check_inbound.unanswered_aged(repo=repo, today=d):
            who = _norm_name(row["name"])
            if not who or who in already or who in closed:
                continue
            if who in log_closed:
                continue                          # a thread header carries an explicit closure
            if latest_out.get(who, "") >= row.get("last_inbound", ""):
                continue                          # answered after the archive snapshot, logged
            out.append(f"📥 INBOUND ← {row['name']} — unlogged in correspondence-log.md, last "
                       f"wrote {row['last_inbound']} ({row['days_open']}d ago, from messages.csv)")
    except Exception:
        pass
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
    d = today or _send_day()
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
# So the zero is a LABELING fact about the log, not a fact about the search. The flag stays,
# because working rung 5-7 into an explicit intro is still the right suggestion, but the WORDING
# must not assert something the data cannot support. The counting is untouched here on purpose.
REFERRED_FLAG = ("rung 8-9 (referred) carries NO rows in the send log, on {warm} warm sends. "
                 "That is a LABELING fact, not proof it never happened: a referral that arrives "
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
                       " Rung 5-7 is what produces a labeled one.")
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
        d = today or _send_day()
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
                         f"(a labeling gap, see --full)")
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


def _already_contacted(name, company, scope="ever"):
    """Belt and braces on top of rank_people's own contacted filter, the same as _held above.

    `scope` (ruling 2026-09-12): must match whichever bar rank_people applied to THIS candidate's
    lane -- "ever" for a cold pick, "search" for a warm one -- or this second consult would
    re-apply the stricter "ever" bar rank_people had already agreed to relax. The caller decides
    scope from the same signal rank_criteria uses: whether the candidate's `rung` reads warm.

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
        if key and key in rank_criteria.contacted_people(scope=scope):
            return True
    except Exception:
        pass
    return False


def _company_blocked(company):
    """True if this company is registry-blocked, so the derived default never re-offers a ruling.

    The registry (`employers.is_blocked`) is the single screening authority. Asking it here is
    what stops a declined company from being handed back as the pair-brief default the next time
    it is computed: a company you have already ruled out is not a fresh target just because it
    still ranks well on every OTHER criterion. Fails open (returns False) only if the registry is
    unreadable, matching every other degraded path in this module.
    """
    try:
        import employers
        return bool(company) and employers.is_blocked(company)
    except Exception:
        return False


# ⛔ A WARM TIE WHO CANNOT HIRE IS NOT AN INITIAL-CONTACT TARGET. The people pool is mostly 1st-degree
# connections, most of them base-5 `other` warm ties, so the raw top row is often a dormant contact
# with no line to a target role. Andy's 90% is finding and reaching the RIGHT people (plausible bosses
# and referral paths), so next_target skips these categories and lets a genuine boss, connector, or
# peer, or the cold-boss COMPANY target below, be the derived default. Skipped warm ties are never
# lost: they stay on the people board and in warm-network.md, workable whenever the human picks them.
NON_BOSS_HUNT_CATS = {"other", "senior-ic"}


def next_target(repo=None):
    """(label, source) for the next INITIAL contact. Never a person on hold.

    Falls back through boss-hunt people -> companies -> "refill the board", mirroring session_start's
    ranked fallbacks: a briefing that goes blank teaches the operator to stop reading it.
    """
    try:
        import closeness
        import rank_criteria
        store = closeness.load()
        # Pull a deeper slice than the 10 shown on the board: after the base-5 floor is filtered out,
        # a real boss/connector/peer may sit below the wall of warm `other` ties that top the pool.
        people, _skipped = rank_criteria.rank_people(40)
        for c in people:
            if c.get("cat") in NON_BOSS_HUNT_CATS:
                continue
            # ⛔ RUNG 1-2 IS NOT A BOSS-HUNT VECTOR. The category skip above is necessary but NOT
            # sufficient: closeness._cold() only returns cold-boss (rung 3-4) for the boss
            # categories. Every other eligible category (senior-exec, product-ic, connector), when
            # the tie is unrecorded / never-spoke, resolves to cold-stranger "rung 1-2 · connect
            # only, zero ask" — a common-interest connect, not a boss hunt. The sanctioned RUNG, not
            # the category, is the discriminator: a cold-boss (rung 3-4) or a warm rung 5-7 boss/
            # peer/connector stays; a rung 1-2 cold stranger is skipped so the cold-boss COMPANY
            # target below — where the target bosses live — becomes the default.
            if str(c.get("band", "")).strip() == "rung 1-2":
                continue
            if _held(c.get("name", ""), store):
                continue
            # Same lane test rank_criteria used for this candidate: warm rungs scope to "search",
            # cold ones keep "ever" (ruling 2026-09-12).
            _scope = "search" if c.get("rung") not in ("cold-stranger", "cold-boss") else "ever"
            if _already_contacted(c.get("name", ""), c.get("company", ""), scope=_scope):
                continue
            # A boss at a declined company is not a target either: if the employer is ruled out,
            # its hiring manager cannot be the next initial contact. Same registry authority as
            # the company fallback below.
            if _company_blocked(c.get("company", "")):
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
        # Dedup the default against rulings: rank() returns the top companies by fit, but a
        # company already declined must never be re-offered as the next initial contact. Ask the
        # registry per company and skip any blocked one, iterating to the first clean row instead
        # of trusting position 0.
        for c in ranked:
            if _company_blocked(c.get("company", "")):
                continue
            return (f"{c['company']} · {c.get('lane', '')[:34]} · cold-boss rung", "rank")
    except Exception:
        pass
    return ("run discovery to refill the board", "empty")


def gather(today=None, repo=None):
    """Everything the table reads, in one pass. Pure data, so decide() can be tested synthetically."""
    d = today or _send_day()
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
    # The outbound window keeps the derived default on a NEW
    # initial contact, which is the one activity the method spends 90% of its time on.
    # ⏱ The clock is INJECTABLE through the state dict so a test can pin it. Without this the
    # decision table is time-dependent: the same test passes after the cutoff and fails
    # before it, which is a test that reports the hour rather than the rule.
    outbound_window = _outbound_window_open(state.get("now"))
    if outbound_window:
        closed = False
    # ⛔ NO STOP OR REST OPTION EXISTS ANYWHERE IN THIS TABLE. The day's end is the person's to declare, in their own words; the script never offers it,
    # as a default or as an alternate, on any day (the terminal brief he signs in with dropped it 2026-09-19; the kit now matches it).

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
            ],
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
            ],
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
            ],
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
                f"window keeps the day open until {OUTBOUND_WINDOW_CLOSES_ET}:00 ET. 3-3-3 is the daily floor, never a cap. "
                f"Set pair_brief.OUTBOUND_WINDOW_CLOSES_ET to your own hour, or 0 to turn it off.")
        alts = [
            {"badge": "🟡", "label": "Refill the board with a discovery run",
             "state": "widens tomorrow's pool · sends nothing today"},
            {"badge": "🟢", "label": "Screening debt on the banked pool",
             "state": "converts banked rows into rankable ones"},
        ]
        if state.get("referred_gap") and state.get("warm_sends"):
            read.append(REFERRED_FLAG.format(warm=state["warm_sends"]) +
                        " Rung 5-7 is the only thing that produces a labeled one.")
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
                                     "the conveyor's first labeled output"})
        return {
            "priority": "P3",
            "default": f"Next initial contact: {label}",
            "andy_read": read,
            "cite": "the method: most of your time on INITIAL communication · the person pivot",
            "evidence": [f"3-3-3 at {n}/3", f"target source: {state.get('target', ('', ''))[1]}"],
            "target_source": state.get("target", ("", ""))[1],
            "alternates": alts,
        }

    # P4: the 3-3-3 floor is met past the outbound window. The default is NOT "Stop for the day":
    # the workday's end is the human's to DECLARE by picking it out of the alternates, never the
    # script's to assume. The never-ending-loop framing derives STARTING THE NEXT LOOP as the default,
    # and no stop option is offered at all.
    label, _src = state.get("target", ("run discovery to refill the board", "empty"))
    return {
        "priority": "P4",
        "default": f"Start the next loop · next initial contact: {label}",
        "andy_read": [
            "The 3-3-3 floor is met, but the method's framing is a NEVER-ENDING daily loop, so a "
            "closed unit begins the next one, it does not end the day.",
            "HOUSE METHOD: the workday's end is yours to DECLARE, in your own words. The script never "
            "assumes it and never offers it, as a default or an alternate.",
        ],
        "cite": "the method's never-ending loop · the day's end is declared, not assumed",
        "evidence": [f"3-3-3 at {n}/3", f"target source: {state.get('target', ('', ''))[1]}"],
        "target_source": state.get("target", ("", ""))[1],
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
    # Headings are LINES, not substrings: a row that quotes a heading must not truncate the log (BUG-057 in the terminal brief).
    _open = re.search(r"^##\s+OPEN\s*$", src, re.M)
    body = src[_open.end():] if _open else src
    _fixed = re.search(r"^##\s+FIXED\s*$", body, re.M)
    if _fixed:
        body = body[:_fixed.start()]
    out = []
    for m in re.finditer(r"^- \[ \]\s+\*\*(BUG-[A-Za-z0-9-]+)\*\*\s*(\S*)\s*\*\*(.+?)\*\*",
                         body, re.M | re.S):
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
            # behavior rather than silently muting a send-shaped default on a Tuesday.
            return False
    return d.weekday() in WEEKEND


def _next_rise8_activity(repo=None):
    """The next Rise8 activity as NAMED in documents/state/boss-hunting-pause.json's `next_activity`, only while the pause is in force; "" otherwise.
    Never names the play the same file lists as the previous, finished activity. Any trouble reads as ""."""
    try:
        with open(os.path.join(repo or REPO, "documents", "state", "boss-hunting-pause.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        if not data.get("paused"):
            return ""
        act = data.get("next_activity")
        act = act.strip() if isinstance(act, str) else ""
        prev = data.get("previous_activity")
        if act and isinstance(prev, dict) and isinstance(prev.get("activity"), str) and prev["activity"].strip().casefold() == act.casefold():
            return ""
        return act
    except Exception:
        return ""


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
    # Rule 1b: NOT ON A WEEKEND, and NEVER "REST". A send-shaped default on a Saturday is the pipeline nagging about a loop that is not running, so it is
    # swapped for the next piece of work, never the absence of work. The ladder is still shown, because the number is a fact. A declared work day
    # (see _workday_declared) beats the weekend assumption. When a next Rise8 activity is named, Rule 1d below governs every day.
    rise8 = _next_rise8_activity(repo)
    if (not rise8 and _is_weekend(today) and SEND_SHAPED.search(d["default"]) and not _workday_declared(today)):
        d["default"] = "Refill the board with a discovery run"
        d["evidence"] = ["No next Rise8 activity has been named yet, so this is the fallback."]
        d["andy_read"] = ["The method's loop is daily on WORKING days. A weekend nag is the pipeline pressuring a counter that should not be running, "
                          "so the counter stays quiet.",
                          "Quiet is not rest: the default is the next piece of work. The ladder is still shown, because the number is a fact."]
        d["priority"] = "P5"
        d["alternates"] = [x for x in d.get("alternates", []) if x.get("label") != d["default"]]
    # Rule 1d: while boss hunting is paused and a next Rise8 activity is named, option 1 is that activity and the default it displaces moves down one.
    # Only a folder with a pause file reaches this, so a partner's brief never carries it. The row says owner_only for the app.
    if rise8:
        moved = {"badge": "🟡", "label": d["default"], "state": "the default, moved down while boss hunting is paused", "moved_down": True}
        d["alternates"] = [moved] + [x for x in d.get("alternates", []) if x.get("label") != d["default"]]
        d["default"] = f"Next Rise8 activity · {rise8}"
        d["evidence"] = ["Until the app ships, option 1 is the next Rise8 activity."]
        d["andy_read"] = ["Boss hunting is paused until the app ships, so option 1 is the next Rise8 activity. The default is not gone: it is the next option down."]
        d["cite"] = "the pause in documents/state/boss-hunting-pause.json · option 1 is the next Rise8 activity"
        d["priority"] = "P5"
        d["owner_only_default"] = True
    # NAME THE METHOD IN THE LABEL ITSELF, here rather than in render(), so that BOTH surfaces the
    # agent can copy from (the printed brief and --json's "default") carry it. This is what makes a
    # picker built verbatim from this tool pass check_pair --hook-ask.
    name = method_name()
    if name and not d.get("owner_only_default") and name.lower() not in d["default"].lower():
        d["default"] = f"{name}'s pick: {d['default']}"
    # 📰 UNREAD RELEASE NOTES BECOME A PICKER OPTION, appended LAST and never the default.
    # Same rule as bug work: reading about the kit is not outreach, and it must never displace the
    # 3-3-3. But an update that changed how the ranker orders people is worth a slot, because the
    # alternative is a partner quietly distrusting a list they cannot explain.
    try:
        import release_notes
        _new = [] if _pause_state(repo)["paused"] else release_notes.unseen()
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

def spooled_orphans_note(repo=None):
    """'' or one line: spooled send-log changes (a confirm, a bounce, a stage) that found no row to land on yet. They stay in the spool and are never dropped (BUG-687)."""
    try:
        try:
            import sendlog_lock
        except ImportError:
            return ""
        got = sendlog_lock.orphans(repo or REPO)
    except Exception:
        return ""
    if not got:
        return ""
    return "%d spooled change%s found no row: %s" % (len(got), "" if len(got) == 1 else "s", "; ".join(got[:5]))


def render(full=False, today=None, repo=None):
    d = derive(today, repo)
    out = ["── THE PAIR ──", "",
           "LADDER", ladder_full(today, repo) if full else ladder_compact(today, repo), "",
           "STAMP (paste this INTO the picker, verbatim)", f"  {stamp(today, repo)}", ""]
    try:
        import balancer
        out += [balancer.render(balancer.recommend(repo=repo or REPO)), ""]
    except Exception:
        pass
    note = spooled_orphans_note(repo)
    if note:
        out += [note, ""]
    out += [
           f"THE METHOD'S READ ({d['priority']})"]
    for line in d["andy_read"]:
        out.append(f"  · {line}")
    out.append(f"  source: {d['cite']}")
    out.append("")
    out.append("DEFAULT (option 1, name it as the method's)")
    if _boss_hunting_paused(repo):
        out.append("  ⏸ outreach is PAUSED by a standing ruling in "
                   "documents/state/boss-hunting-pause.json; option 1 should reflect that.")
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


# ── THE STRUCTURED BRIEF (slice A, 2026-10-13) ────────────────────────────────────────────────
# The app's Home draws the ladder and the door from THIS, never from numbers of its own: serve.py's GET /pair/brief runs
# `pair_brief.py --brief` and hands the JSON through. Every figure is produced by the code the printed brief uses
# (rung_ladder.tally, stamp, sends_today_logged, balancer.recommend, derive), so the page and the terminal cannot disagree.

def _pause_state(repo=None):
    """{paused, ruling, next_activity} from documents/state/boss-hunting-pause.json. Absent or unreadable: not paused, nothing named."""
    try:
        with open(os.path.join(repo or REPO, "documents", "state", "boss-hunting-pause.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        if not data.get("paused"):
            raise ValueError("not paused")
        act = data.get("next_activity")
        ruling = data.get("ruling")
        return {"paused": True, "ruling": ruling.strip() if isinstance(ruling, str) else "",
                "next_activity": act.strip() if isinstance(act, str) else ""}
    except Exception:
        return {"paused": False, "ruling": "", "next_activity": ""}


def _ladder_rows(repo=None):
    """The ladder as rows, in rung_ladder.render's own order and labels, cells as it prints them: the acceptance rungs print a dash for
    replied and rate (None here)."""
    import rung_ladder
    agg, dropped = ladder_counts(repo)
    rows = []
    for k in rung_ladder._order(agg):
        s, rp = agg.get(k, (0, 0))
        if k in rung_ladder.ACCEPTANCE_RUNGS:
            replied, rate = None, None
        else:
            replied, rate = rp, "%.1f" % (100 * rp / s if s else 0)
        rows.append({"key": k, "label": rung_ladder.RUNG_LABEL.get(k, k).strip(), "sent": s, "replied": replied, "rate": rate})
    sent = sum(v[0] for v in agg.values())
    replied = sum(v[1] for v in agg.values())
    total = {"key": "total", "label": "TOTAL", "sent": sent, "replied": replied, "rate": "%.1f" % (100 * replied / sent if sent else 0)}
    return {"rows": rows, "total": total, "excluded_undelivered": dropped}


def _segments_configured():
    """True when this install's kit_config.py sets its own TARGET_SEGMENT_MIX. Without it the balancer falls back to placeholder segment names."""
    try:
        import kit_config
        return bool(getattr(kit_config, "TARGET_SEGMENT_MIX", None))
    except Exception:
        return False


def _balancer(repo=None):
    try:
        import balancer
        rec = balancer.recommend(repo=repo or REPO)
    except Exception:
        return None
    segs_ok = _segments_configured()
    if not segs_ok:
        rec = dict(rec, segment_table={}, segment="", segment_reason="")
    elif rec["untagged_frac"] >= 1.0:
        rec = dict(rec, segment="", segment_reason="")
    return {"window_n": rec["window_n"], "unequipped_n": rec["unequipped_n"], "untagged_frac": rec["untagged_frac"],
            "rungs": [{"key": k, "now": v[0], "share": v[1], "target": v[2]} for k, v in rec["rung_table"].items()],
            "segments": [{"key": k, "now": v[0], "share": v[1], "target": v[2]} for k, v in rec["segment_table"].items()],
            "next": {"rung": rec["rung"], "segment": rec["segment"], "rung_reason": rec["rung_reason"], "segment_reason": rec["segment_reason"]}}


WITHHELD_STATE = "Your terminal names your next contact. Not in the app yet."


def _target_for(label):
    """Where the app's press on this option goes: one of the page's own words ("card", "discovery", "screening", "after") or "" for work the
    app does not open yet. Decided here, once, so the page never reads a label to guess."""
    low = label.lower()
    if "refill the board" in low:
        return "discovery"
    if "screening debt" in low:
        return "screening"
    if low.startswith("reply to") or "capture the thread" in low:
        return "after"
    if "next initial contact" in low:
        return "card"
    return ""


def _attach_scores(opts, repo=None, today=None):
    """Put the NEXT-STEP picker's scores on the options a FRESH sidecar scored (documents/state/next-step-scores.json), through nextstep_scores,
    the one matcher the static card uses. No module, no sidecar, a stale or old-scale one: nothing is attached and nothing is raised. Runs before
    the redaction below, so a withheld name still matches here and never crosses the wire."""
    try:
        import nextstep_scores
        nextstep_scores.attach_scores({"default": opts[0], "alternates": opts[1:]}, repo=repo or REPO, today=today)
    except Exception:
        pass


def _landed_block(today=None, repo=None):
    """The brief's "landed" facts (what landed since his last visit, typed by the seat that merged it), the ones the terminal brief draws.
    None when this install has no documents/state/landed.jsonl (a partner) or the module is absent; never raises."""
    try:
        import landed
        _base = repo or REPO
        return landed.as_block(os.path.join(_base, landed.RECORD), os.path.join(_base, landed.LEDGER), today, repo_dir=_base)
    except Exception:
        return None


def brief(today=None, repo=None):
    """Everything the app's Home needs, computed by this file and its siblings. `options` is the picker in the order the printed
    brief lists it: option 1 is the derived default, then each alternate."""
    d = derive(today, repo)
    ladder = _ladder_rows(repo)
    opts = [{"n": 1, "badge": "\U0001f9ed", "label": d["default"], "state": " ".join(d.get("evidence", [])), "is_default": True,
             "target": _target_for(d["default"])}]
    for i, a in enumerate(d["alternates"], 2):
        opts.append({"n": i, "badge": a.get("badge", ""), "label": a["label"], "state": a.get("state", ""), "is_default": False,
                     "target": _target_for(a["label"])})
        if a.get("moved_down"):
            opts[-1]["moved_down"] = True
    if d.get("owner_only_default"):
        opts[0]["owner_only"] = True
    _attach_scores(opts, repo, today)
    # A named next contact comes from THIS kit's ranker, which cannot be shown to pick the person the terminal's does, and the app has no card for a
    # person. So the app names nobody: it says the terminal does, and opens nothing. The wire label is the redacted one, so no withheld name crosses to the page.
    ranked = d.get("target_source") in ("rank_people", "rank")
    for o in opts:
        o["shown"], o["shown_state"], o["withheld"] = o["label"], o["state"], False
        if ranked and re.search(r"next initial contact:\s", o["label"], re.I) and not o.get("owner_only"):
            o["shown"] = re.sub(r"(?i)(next initial contact):\s.*$", r"\1", o["label"])
            o["shown_state"], o["withheld"], o["target"] = WITHHELD_STATE, True, ""
            # The wire carries no withheld name: label and state are the redacted words too (the printed brief, which is the terminal's, is built elsewhere).
            o["label"], o["state"] = o["shown"], o["shown_state"]
    return {
        "stamp": stamp(today, repo),
        "question": question_for(today, repo),
        "header": HEADER_TEMPLATE,
        "ladder": ladder,
        "three_three_three": {"sent_today": sends_today_logged(today or _send_day(), repo), "goal": 3},
        "balancer": _balancer(repo),
        "pause": _pause_state(repo),
        "priority": d["priority"],
        "andy_read": d["andy_read"],
        "cite": d["cite"],
        "options": opts,
        "landed": _landed_block(today, repo),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="The ladder summary + the derived next-step default")
    ap.add_argument("--full", action="store_true", help="whole ladder table (session open)")
    ap.add_argument("--json", action="store_true", help="machine-readable, for hooks and tests")
    ap.add_argument("--stamp", action="store_true", help="the stamp line alone")
    ap.add_argument("--brief", action="store_true", help="the structured brief the app reads: ladder rows, 3-3-3, balancer, stamp, picker options")
    ap.add_argument("--working-until", metavar="HH:MM",
                    help="declare when TODAY ends. The brief never suggests ending the day; this only records your word. "
                         "Today only; ignored on any other date. 'clear' removes it.")
    a = ap.parse_args(argv)
    if a.working_until:
        _set_working_until(a.working_until)
    if a.stamp:
        print(stamp())
    elif a.brief:
        print(json.dumps(brief(), ensure_ascii=False, indent=2))
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
