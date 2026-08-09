#!/usr/bin/env python3
"""check_pair.py — the two hooks that make the ladder+picker pair DURABLE instead of remembered.

WHY. The pair (a live ladder summary plus a next-step picker with the method's suggestion as the
default) is owed at sign-in and again whenever work reaches a stopping point. As prose it drifted
twice: three turns in a row ended on a status report with no picker, and the numbers in the last
one had been carried forward and were stale. documents/HARD-INVARIANTS.md RULE-EDIT GUARD states
the class in one line, a rule that lives only in prose is not a rule, and
documents/ENFORCEMENT-REGISTER.md states the pattern, strong scripts and weak triggering. So this
file is the triggering.

TWO MODES, mirroring check_style.py's one-script/two-flags shape.

  --hook-ask   PreToolUse on AskUserQuestion, alongside check_preview.
               Fires ONLY on a picker carrying the literal marker NEXT-STEP, the same explicit
               anchor pattern as check_preview's WARM-RUNG: / FOLLOWUP: / REFERRED: markers. Every
               other picker (scorecards, voice options, everything) passes untouched, so this adds
               ZERO risk to the BUILD gate and cannot nag an ordinary question.
               For a marked picker it requires: a stamp line, dated today, whose numbers match a
               LIVE recompute through pair_brief.stamp(), and an option 1 that names the method
               (kit_config.METHOD_TERMS).
               That is what turns "recomputed, never carried forward" into a property: a summary
               copied from an earlier message in the session is stale the moment anything was sent,
               and the recompute refuses it.

  --hook-stop  Stop hook, third entry alongside the consistency sweep and the style linter.
               The ONLY point that can observe "the turn ended and the pair never appeared."

⚖️ THE FAILURE POLARITIES DIFFER ON PURPOSE, and the difference is the design.

  --hook-ask FAILS OPEN on infrastructure error (unreadable send log, import failure). A stamp
  MISMATCH against a healthy recompute still blocks. This is the OPPOSITE of the BUILD gate's
  fail-closed , deliberately: the BUILD gate withholds authorization for
  an outward irreversible act, while this one enforces the freshness of a DISPLAY. Blocking every
  next-step picker on a corrupt send log would convert a data problem into a decision outage.

  --hook-stop ALWAYS exits 0 on any exception, and exits 0 unconditionally when stop_hook_active is
  already true. One block per turn, mechanically. documents/ENFORCEMENT-REGISTER.md keeps the Stop
  tier non-blocking in general, because a Stop hook that blocks can trap the agent in a loop, which
  is worse than a missed report. That reasoning is sound, and this is a CALIBRATED EXCEPTION to it
  rather than a reversal: the loop guard is what buys the exception.

⛔ WRITES NOTHING, EVER. Both modes are read-only. The two-writers corruption class stays closed
(two writers on one tree is a corruption class, not a hypothetical).

KILL SWITCH: CLAUDE_PAIR_GATE=off (silent pass) · =warn (print, pass). If the block turns out to
be too strict for you, downgrade it with the env var rather than by editing this file.

Usage:
    check_pair.py --hook-ask     # PreToolUse(AskUserQuestion), payload on stdin
    check_pair.py --hook-stop    # Stop, payload on stdin
Exit: 0 allow · 2 block (stderr is fed back to the model)
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

# The marker and the stamp shape are IMPORTED, never re-typed. pair_brief.stamp() is the ONE
# producer of that line; a second formatter here would be a second answer.
try:
    import pair_brief
    PAIR_MARKER = pair_brief.PAIR_MARKER
except Exception:                                    # pragma: no cover - import failure fails open
    pair_brief = None
    PAIR_MARKER = "NEXT-STEP"

STAMP_RE = re.compile(
    r"LADDER\s+(\d{4}-\d{2}-\d{2})\s*·\s*sent\s+(\d+)\s*·\s*replied\s+(\d+)\s*·\s*"
    r"rate\s+([\d.]+)%\s*·\s*3-3-3\s+(\d+)/3")

# Does option 1 name the method's author? your ruling, not a nicety: "the method's read is the
# DEFAULT, option 1, and it must be NAMED as his" (the method's read is the default, documents/HARD-INVARIANTS.md). A default presented as the assistant's preference is the exact thing he
# rejected three pickers in a row over.
# 🔴 NOW ACTUALLY READS THE CONFIG (2026-08-03). The docstring above has always claimed this check
# keys off kit_config.METHOD_TERMS, and it did not: the terms were hardcoded here, so a partner who
# renamed the method in their config changed nothing and got blocked by a regex naming somebody
# else's mentor. Same fallback list check_preview.py uses, for the config-absent and config-empty
# cases; an empty METHOD_TERMS turns this half of the check OFF (ANDY_RE is None), which
# first_option_names_andy already honors.
def _method_terms():
    try:
        import kit_config
    except Exception:
        return list(METHOD_TERMS_FALLBACK)
    terms = getattr(kit_config, "METHOD_TERMS", None)
    if terms is None:
        return list(METHOD_TERMS_FALLBACK)
    return [str(t) for t in terms if str(t).strip()]


METHOD_TERMS_FALLBACK = ["lacivita", "andy"]
METHOD_TERMS = _method_terms()
# \b around an escaped term keeps whole-word matching, the way the hardcoded pattern behaved.
ANDY_RE = (re.compile(r"\b(" + "|".join(re.escape(t) for t in METHOD_TERMS) + r")\b", re.I)
           if METHOD_TERMS else None)

LEDGER = os.path.join(REPO, "documents", "decision-ledger.jsonl")

# ── THE WATCHED SET: what counts as "an action of record" for moment (b) ──────────────────────
# A completed task is not a harness event, so this is the observable proxy: THE OUTREACH RECORD
# MOVED. Sends you performs in Apple Mail are invisible until LOGGED, and the logging is the
# observable event, which is also the rule already in force
# (log first, then ladder).
#
# 🔴 NARROWED IN THE FIELD, AFTER IT TAXED THE OWNER DIRECTLY. This set used to include
# `scripts/*.py`, `scripts/*.sh` and `documents/*.md`, on the plan's reasoning that a gate fix or a
# screening write IS a completed task. In practice that made the gate fire on writes a BACKGROUND
# SUBAGENT was making, attributed to the main session's turn: it blocked the main session twice
# while that session was doing nothing but asking you a one-line question, because a build agent
# happened to be editing scripts at that moment. He felt it as friction and said so.
#
# ⛔ THE FAILURE MODE THAT MATTERS MORE THAN THE FEATURE: a gate that cries wolf on the most
# user-visible surface in the repo gets switched off, and a switched-off gate protects nothing.
#
# WHY NARROWING IS THE FIX AND NOT A PATCH. The other two options were weighed and rejected:
#   (a) a marker captured at TURN START. There is no such marker to read.
#       `record_chat_ruling.py` is the only UserPromptSubmit hook and it exits WITHOUT WRITING
#       unless the prompt is a ruling (a small fraction of ledger rows in practice), so
#       a turn-start timestamp would mean adding a new writer. Both pair hooks write nothing, on
#       purpose (two writers on one tree is a corruption class, not a hypothetical), and a
#       snapshot file is the one thing this design forbids outright.
#   (b) ignoring changes inside a window where a SUBAGENT was active. Not observable: nothing in a
#       file's mtime says which process wrote it, and the harness exposes no subagent registry to a
#       Stop hook. It would be a heuristic over an unobservable, which is worse than a narrow rule.
#   (c) KEY OFF THE RECORD, which is this. A code edit is not work of record. A send-log write IS,
#       and it needs NO attribution to be correct: whoever moved it, THE LADDER IS NOW STALE,
#       which is the precise thing the pair exists to stop you seeing.
#
# 🔴 NARROWED AGAIN 2026-08-02 (F1). The earlier set held six entries and justified them with
# "whoever moved it, the ladder is now stale". Field verification showed that claim false for four
# of the six: stamp() reads ONLY documents/send-log.jsonl, so a discovery sweep, a thread capture,
# a board update or a tracker touch moved the clock while the stamp stayed IDENTICAL, and the gate
# forced a re-show of numbers you had just seen. The watched set is now exactly what stamp()
# reads, and it is the FALLBACK path only: pair_owed's primary test compares the stamp you were
# last shown against a live recompute, so even a send-log rewrite that changes no number stays
# quiet.
#
# HONEST COST, stated rather than hidden: a turn that ONLY fixes a gate, captures a thread, or
# updates the board no longer owes a pair through moment (b). The SessionStart instruction still
# asks for the pair after a status report. The mechanical gate now UNDER-covers instead of
# over-firing, and that is the correct direction for a surface you read every turn.
WATCHED_FILES = [
    "documents/send-log.jsonl",
]
WATCHED_GLOBS = []

# ⛔ MANDATORY EXCLUSIONS. Each is a self-trigger, and watching one makes the owed state PERMANENT
# and blocks EVERY turn, forever:
#   decision-ledger.jsonl   written by ANSWERING any picker, including this pair's own. No glob
#                           reaches it since the 2026-08-02 narrowing, but the exclusion STAYS:
#                           the last set widened once already, and this entry is what keeps a
#                           future widening from making the gate unsatisfiable.
#   .consistency-last.txt   written by the SIBLING Stop hook, every single turn.
# Dotfiles are excluded wholesale on top of that: they are machinery, not work of record. The two
# guards overlap on `.consistency-last.txt` deliberately, and the ledger is covered by this set
# ALONE, which is what the break-test keys on (a partially-shadowed revert reports a false alarm,
# breaktest.py's own lesson 3).
WATCHED_EXCLUDE = {
    "documents/.consistency-last.txt",
    "documents/decision-ledger.jsonl",
}


def is_watched(rel):
    """Pure, so a test can hand it the two self-triggering paths and assert they never count.

    Pure ON PURPOSE. A test that only walked the real tree would pass because the tree happens not
    to contain a counterexample at that moment, and would keep passing after someone deleted the
    exclusion. That is the decay `kit_parity_check.absent_files` is pure to avoid.
    """
    rel = rel.replace(os.sep, "/").lstrip("./")
    if rel in WATCHED_EXCLUDE:
        return False
    if any(part.startswith(".") for part in rel.split("/")):
        return False
    if rel in WATCHED_FILES:
        return True
    import fnmatch
    return any(fnmatch.fnmatch(rel, g) for g in WATCHED_GLOBS)


def newest_action_mtime(repo=None):
    """Newest mtime across the WATCHED set, as a POSIX timestamp. 0.0 when nothing is readable.

    FALLBACK ONLY since 2026-08-02: pair_owed compares stamps when the last pair row carries one,
    and reads this clock only for a legacy row that does not. A parallel session or a subagent
    that LOGS A SEND still owes this session a pair. That is not a false positive: the ladder
    moved, so the numbers you last saw are wrong, and showing the fresh pair is the
    correct response no matter which process moved them.

    Transcript diffing was considered as an attribution source and rejected: `transcript_path` is
    known-stale in some builds (anthropic/claude-code#8564), so it trades a small cost for an
    unreliable signal.
    """
    import glob
    repo = repo or REPO
    newest = 0.0
    cands = [os.path.join(repo, f) for f in WATCHED_FILES]
    for g in WATCHED_GLOBS:
        cands += glob.glob(os.path.join(repo, g))
    for p in cands:
        rel = os.path.relpath(p, repo)
        if not is_watched(rel):
            continue
        try:
            newest = max(newest, os.path.getmtime(p))
        except OSError:
            continue
    return newest


# ── LEDGER EVIDENCE: did the pair actually happen, and was it ruled on? ───────────────────────
def newest_pair_row(session_id, ledger=None):
    """The newest NEXT-STEP row for THIS session, or None.

    These rows are written by the HARNESS from YOUR real answer and MAC-signed by
    record_decision.py, so "the pair happened and it was ruled on" reads from the one
    non-forgeable store this kit already has. No new store, no transcript dependency, and this
    hook writes nothing.

    The MAC is deliberately NOT verified here. It authenticates AUTHORIZATION, and this row
    authorizes nothing — it is an audit trail (see the record_decision interplay note below). A
    forged NEXT-STEP row buys an agent the right to skip showing you a picker you asked for, which
    is not a security boundary, it is a self-inflicted wound.
    """
    path = ledger or LEDGER
    best = None
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if session_id and row.get("session") != session_id:
                    continue
                blob = f"{row.get('question', '')} {row.get('header', '')}"
                if PAIR_MARKER not in blob:
                    continue
                if best is None or str(row.get("ts", "")) >= str(best.get("ts", "")):
                    best = row
    except Exception:
        return None
    return best


def _ts_epoch(ts):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(ts)).timestamp()
    except Exception:
        return 0.0


def work_since(row, repo=None, now_mtime=None):
    """True when an action of record landed after this pair row was written.

    The LEGACY path's clock, kept as a named function so the two paths in `pair_owed` cannot drift
    apart the way they once did: a legacy row fell back to this mtime check, a stamped row did not,
    so a whole day of work with no sends never charged for a pair.

    ⛔ THIS IS NOT THE STAMPED PATH'S TEST, deliberately. When the row carries a ladder stamp,
    `pair_owed` compares the live sent/replied figures against the ones you last saw, which is a
    strictly better signal. A send-log mtime moves for reasons the ladder does not (a compaction, a
    dedup pass, a restore, a plain copy), so using it there would trade a precise comparison for a
    noisy one and start charging conversational turns for background writes.
    """
    mt = newest_action_mtime(repo) if now_mtime is None else now_mtime
    return mt > _ts_epoch(row.get("ts"))


def pair_owed(session_id, repo=None, ledger=None, now_mtime=None):
    """(owed, reason_key). Pure enough to test: ledger and the fallback mtime can be injected.

    REWORKED 2026-08-02 for F2 and F1. The old shape charged every fresh session's first turn
    ("no-pair-yet" with no watched file touched, F2) and charged conversational turns for subagent
    writes that left the stamp identical (F1). The question this now answers is the one the pair
    exists for: HAVE THE NUMBERS YOU LAST SAW GONE STALE?

    1. Baseline = the newest NEXT-STEP row for THIS session, falling back to the newest from ANY
       session: the ledger is one store and the ladder you last saw is the ladder you last saw,
       whichever terminal showed it. NO row anywhere -> not owed. Moment (a), the sign-in pair, is
       the SessionStart instruction's job, and a mechanical block on a pure first-turn question is
       exactly the cries-wolf failure that got this gate demoted to warn.
    2. The row's own question/header carry the stamp verbatim (block_message demands it, hook_ask
       enforces it). When it parses, owed = live sent/replied moved since that stamp
       ("ladder-moved"). sent and replied are cumulative send-log figures, so a sweep file, a
       thread capture, a board or tracker touch CANNOT trip this, and neither can a new day: the
       3-3-3 and date fields are excluded from the comparison because they roll over without any
       work happening.
    3. A legacy row with no parseable stamp falls back to the mtime clock over the narrowed
       watched set ("work-since-pair").
    4. An unreadable or corrupt send log stands the gate down ("ladder-unreadable", not owed):
       a zeroed recompute presented as live is F3's honesty failure, in either hook.
    """
    row = newest_pair_row(session_id, ledger)
    if row is None:
        row = newest_pair_row(None, ledger)
    if row is None:
        return False, "no-pair-ever"
    shown = STAMP_RE.search(f"{row.get('question', '')} {row.get('header', '')}")
    if shown is not None and pair_brief is not None:
        try:
            healthy, _detail = pair_brief.ladder_health(repo)
            if not healthy:
                return False, "ladder-unreadable"
            sent, replied = pair_brief.totals(repo)
        except Exception:
            return False, "ladder-unreadable"
        if (int(shown.group(2)), int(shown.group(3))) != (sent, replied):
            return True, "ladder-moved"
        return False, "current"
    if work_since(row, repo, now_mtime):
        return True, "work-since-pair"
    return False, "current"


BLOCK_REASON = {
    "ladder-moved": "the ladder moved after the last NEXT-STEP picker, so the numbers you "
                    "last saw are stale",
    "work-since-pair": "work of record landed after the last NEXT-STEP picker",
}


def block_message(reason_key, compact=True):
    """What the model is told to do. One command, then the shape of the picker."""
    try:
        stamp = pair_brief.stamp()
    except Exception:
        stamp = "run scripts/pair_brief.py --stamp"
    flag = "" if compact else " --full"
    return (
        f"🧭 THE PAIR IS OWED: {BLOCK_REASON.get(reason_key, reason_key)}.\n"
        f"1. Run `python3 scripts/pair_brief.py{flag}` and SHOW the ladder summary.\n"
        f"2. Then present the next-step picker. Its question and header must carry the literal "
        f"marker {PAIR_MARKER} and this stamp line, verbatim:\n"
        f"     {stamp}\n"
        f"3. Option 1 is the method's derived default, NAMED as the method's, with its read "
        f"in the description. Its label or description must contain one of these terms, "
        f"case-insensitively: {', '.join(repr(t) for t in METHOD_TERMS) or '(none — check off)'}"
        f" (from kit_config.METHOD_TERMS). Alternates carry their honest state.\n"
        f"⛔ Keep build/draft/send vocabulary OUT of the question and header (record_decision.py "
        f"reads those two fields as BUILD context). Say 'next move', never 'draft' or 'build'.\n"
        f"(one block per turn · CLAUDE_PAIR_GATE=off disables this gate, =warn downgrades it)"
    )


# ── MODE A: PreToolUse on AskUserQuestion ─────────────────────────────────────────────────────
def _strings(tool_input):
    """Every human-visible string in the payload. Same walk as check_preview._strings_from_questions."""
    for q in (tool_input.get("questions") or []):
        if not isinstance(q, dict):
            continue
        for k in ("question", "header"):
            if q.get(k):
                yield (k, str(q[k]))
        for oi, o in enumerate(q.get("options") or []):
            if isinstance(o, dict):
                for k in ("label", "description", "preview"):
                    if o.get(k):
                        yield (f"opt{oi + 1}.{k}", str(o[k]))


def is_pair_picker(tool_input):
    """Only a picker whose QUESTION or HEADER claims to be the pair is checked.

    ⚠️ WHAT ELSE FALLS THROUGH TO THIS BRANCH, asked deliberately. A gate written for one case binds
    every case that reaches it, and this repo has paid for that three times (warm rungs unsendable
    for months, cold-stranger unsendable, the boss gate nearly catching cold-stranger). The catch
    here is the literal string NEXT-STEP in question/header, so the ONE other thing it captures is a
    picker ABOUT this gate. That question self-blocks, exactly the way a scorecard question carrying
    your own voice markers self-blocks on check_preview, which documents/HARD-INVARIANTS.md warns
    about in those words. The cost is one paste of a stamp line, the mode fails OPEN on any error,
    and
    CLAUDE_PAIR_GATE=off ends it.

    Scoping to question/header rather than the whole payload is what keeps that surface small:
    option text discussing the marker in passing never arms the check.
    """
    fields = [t for f, t in _strings(tool_input) if f in ("question", "header")]
    return PAIR_MARKER in "\n".join(fields)


def first_option_names_andy(tool_input):
    for q in (tool_input.get("questions") or []):
        if not isinstance(q, dict):
            continue
        opts = [o for o in (q.get("options") or []) if isinstance(o, dict)]
        if not opts:
            continue
        if ANDY_RE is None:
            return True                              # METHOD_TERMS empty: this half is off
        blob = " ".join(str(opts[0].get(k, "")) for k in ("label", "description", "preview"))
        return bool(ANDY_RE.search(blob))
    return False


def verify_stamp(blob, live_stamp):
    """(ok, problem). Compares the stamp IN the picker with a LIVE recompute.

    Whitespace is normalized before comparison because a picker's description wraps; nothing else
    is. Comparing the whole line rather than field-by-field is deliberate: it means a change to the
    stamp FORMAT can never silently pass half a check.
    """
    m = STAMP_RE.search(blob)
    if not m:
        return False, "no ladder stamp found"
    found = re.sub(r"\s+", " ", m.group(0)).strip()
    want = re.sub(r"\s+", " ", live_stamp).strip()
    if found == want:
        return True, ""
    lm = STAMP_RE.search(want)
    if lm and m.group(1) != lm.group(1):
        return False, f"stamp is dated {m.group(1)}, today is {lm.group(1)}"
    return False, f"stamp numbers do not match a live recompute (picker: {found})"


def hook_ask():
    gate = os.environ.get("CLAUDE_PAIR_GATE", "").lower()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)                                  # fail-open: nothing parseable to judge
    if payload.get("tool_name") != "AskUserQuestion":
        sys.exit(0)
    tool_input = payload.get("tool_input") or {}
    try:
        if not is_pair_picker(tool_input):
            sys.exit(0)
        # 🔴 F3: ladder_counts() degrades a corrupt send log to a well formed ZEROED stamp, so the
        # except below never fires on the exact case the module docstring names. Probe health
        # FIRST: a gate that cannot recompute the ladder stands down. It must never block, and it
        # must never instruct the model to show `sent 0 · replied 0` as though it were live.
        healthy, detail = pair_brief.ladder_health()
        if not healthy:
            print(f"⚠️ check_pair standing down: send-log is {detail}, so the ladder cannot be "
                  "recomputed. Fix the log before trusting any ladder numbers.")
            sys.exit(0)
        blob = "\n".join(t for _f, t in _strings(tool_input))
        live = pair_brief.stamp()
        ok, problem = verify_stamp(blob, live)
        andy = first_option_names_andy(tool_input)
    except Exception:
        # FAIL-OPEN, and this is the polarity that differs from the BUILD gate on purpose. A broken
        # hook must not kill the one picker you most want to see.
        sys.exit(0)
    if gate == "off":
        sys.exit(0)
    problems = []
    if not ok:
        problems.append(problem)
    if not andy:
        # NAME THE ACCEPTED TERMS (2026-08-03). This used to say only "does not name the method",
        # which states the failure without stating the remedy: the reader cannot guess which token
        # satisfies a regex they cannot see. pair_brief's own printed default failed this check for
        # weeks and the block gave no way to fix it.
        problems.append("option 1 does not name the method (its read is the default and must "
                        "be NAMED as the method's). Accepted terms, any one of them, "
                        "case-insensitive: " + ", ".join(repr(t) for t in METHOD_TERMS) +
                        " (set kit_config.METHOD_TERMS to change them)")
    if not problems:
        sys.exit(0)
    msg = ("⛔ NEXT-STEP picker BLOCKED by check_pair: " + "; ".join(problems) + ".\n"
           f"▶ The live stamp right now is:\n     {live}\n"
           "Paste that line into the question or an option description, verbatim, and make option 1 "
           "the method's derived default with its read in the description "
           "(`python3 scripts/pair_brief.py` computes both).\n"
           "Why this blocks: a ladder summary carried forward from an earlier message in the "
           "session is stale the moment anything was sent, and the pair is only durable if the "
           "numbers are recomputed rather than remembered.")
    if gate == "warn":
        print(msg)
        sys.exit(0)
    print(msg, file=sys.stderr)
    sys.exit(2)


# ── MODE B: Stop ──────────────────────────────────────────────────────────────────────────────
def hook_stop():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        # LOOP GUARD FIRST, before anything that can be slow or can throw. `stop_hook_active` is
        # true when a prior Stop block already forced this continuation, so one block per turn is
        # mechanical rather than a promise. This IS the answer to the register's stated reason for
        # keeping Stop non-blocking.
        if payload.get("stop_hook_active"):
            sys.exit(0)
        gate = os.environ.get("CLAUDE_PAIR_GATE", "").lower()
        if gate == "off":
            sys.exit(0)
        # F3's stop-mode twin: an unreadable send log means every recompute is a zeroed stamp, and
        # block_message embeds one. Stand down instead of putting zeros in front of the human.
        if pair_brief is None or not pair_brief.ladder_health()[0]:
            sys.exit(0)
        owed, reason = pair_owed(payload.get("session_id", ""))
        if not owed:
            sys.exit(0)
        msg = block_message(reason, compact=True)
        if gate == "warn":
            print(msg)
            sys.exit(0)
        # exit 0 + decision:block is the documented shape: the reason is injected and the model
        # continues acting on it.
        print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
        sys.exit(0)
    except Exception:
        # ANY error exits 0. A Stop hook that errors closed traps the session, and that is the one
        # cost worse than a missed pair.
        sys.exit(0)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--hook-ask" in argv:
        hook_ask()
    elif "--hook-stop" in argv:
        hook_stop()
    else:
        print(__doc__.strip().splitlines()[0])
        print("usage: check_pair.py --hook-ask | --hook-stop   (payload on stdin)")
    sys.exit(0)


if __name__ == "__main__":
    main()
