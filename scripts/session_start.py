#!/usr/bin/env python3
"""session_start.py — brief the operator the moment the pipeline opens.

WHY: opening the workspace from a blank page bootstraps nothing — the method does not start itself.
The cost is measurable: a full day can open with no orientation, drift into tooling, and produce ONE
send. LaCivita's rule is the opposite — "3-3-3 every day before 8:00 AM," and "the 3-3-3 are equally
as important as interview prep." A loop that does not start itself does not start. So this hook prints
the day's brief the moment a session opens.

DESIGN (two rules):
  • BRIEF + PRE-COMPUTED PICKS, never drafts. Drafting before direction is set is the same
    over-eager-drafting failure, at session scale.
  • ALWAYS SHOW BOTH — unfinished work AND today's 3-3-3 — and let the operator choose. No recency
    heuristic silently deciding which was meant.

CONSTRAINTS:
  • FAST and OFFLINE. No network calls at session open (live-ATS checks belong to the build gate).
  • DEGRADES GRACEFULLY. Must work with no data stores, no session-state files and no outreach
    history — print the method and step one rather than erroring.
  • READ-ONLY. Never writes, never sends.

Every operator-specific value comes from kit_config.py — fill that in first. Paths are relative to
the repo root and resolve against your own data files.
"""
import csv
import glob
import os
import re
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
# The SessionStart hook runs with $CLAUDE_PROJECT_DIR set to the project root; fall back to the
# parent of this scripts/ dir when run standalone. Either way, no owner-specific absolute path.
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)

sys.path.insert(0, HERE)
# Identity + rules-doc pointer come from the shared kit_config. Import them on their own so a kit
# that has not yet added the NEW value below still gets the real OWNER_FIRST / RULES_DOC.
try:
    from kit_config import OWNER_FIRST, RULES_DOC
except Exception:  # standalone fallback — generic defaults, no PII
    OWNER_FIRST, RULES_DOC = "the operator", "documents/WORKFLOW-RULES.md"

# EXCLUDED_EMPLOYERS is a NEW kit_config value (not yet defined there): YOUR OWN past employers.
# Their people populate the warm network, but the companies themselves are where your network came
# FROM, not hiring targets — so they are filtered out of the daily picks. Default [] excludes nobody
# (the generic kit ships with no owner history baked in); add your own employer names in kit_config.
try:
    from kit_config import EXCLUDED_EMPLOYERS
except Exception:
    EXCLUDED_EMPLOYERS = []

_EXCLUDED_LC = [e.strip().lower() for e in EXCLUDED_EMPLOYERS if e and e.strip()]


def is_excluded_employer(name):
    """True if a company name matches one of kit_config.EXCLUDED_EMPLOYERS. Generic and default-empty:
    an empty list excludes nobody, so a fresh kit filters nothing until you list your own employers."""
    low = (name or "").lower()
    return any(e in low for e in _EXCLUDED_LC)


def rd(rel):
    p = os.path.join(REPO, rel)
    try:
        return open(p, encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""


def section(title):
    print(f"\n{title}")
    print("─" * min(len(title), 72))


# ── A. UNFINISHED WORK ───────────────────────────────────────────────────────────────────────
def _freshness_item(s, warn_days):
    """The warm-network freshness line for the briefing, or None when nothing is actionable.

    ⛔ GATE THE DOWNLOAD NAG ON export_taken_days, NEVER data_lag_days (kit issue #40). A high
    data_lag_days just means a quiet month on LinkedIn — nobody new connected. That is not stale
    DATA, and no download fixes it, so nagging "download a fresh export" off it is a no-op that
    prints forever and trains the operator to ignore the whole briefing. #7 corrected this in
    check_network_freshness's own verdict; this is the caller that re-derived it and kept the bug,
    so the CLI said "current" while the briefing said "34 days old, download now" off the SAME scan().
    The only nag a download can honestly resolve is a stale EXPORT (export_taken_days high); a stale
    parse (parse_is_behind_export) is fixed by re-parsing, with no download at all.
    """
    if not (s.get("newest_connection") and s.get("data_lag_days") is not None):
        return None
    if s.get("parse_is_behind_export"):
        return ("🟠", f"warm-network is behind an export on disk "
                      f"(parsed {s['newest_connection']}, available {s['export_newest_connection']})",
                ["fix: python3 scripts/parse_network.py    (no download needed)"])
    taken = s.get("export_taken_days")
    if taken is not None and taken >= warn_days:
        return ("🟠", f"warm-network export is {taken} days old",
                [f"last downloaded {s.get('export_taken')}",
                 "a fresh export pulls in anyone connected since then",
                 "fix: download a fresh LinkedIn export, then parse_network.py"])
    return None


def unfinished():
    items, today = [], date.today().isoformat()

    # A PENDING KIT UPDATE IS ASKED ABOUT BEFORE ANY OTHER WORK, and it is a CHOICE, not an order.
    # Applying takes a few minutes, and sometimes the right answer is "not in this session, I need
    # to work on what I already have". So it goes FIRST in the list (you decide before investing a
    # session) and offers three answers: now, at the end of this session, or skip.
    # Offline and non-fatal by construction — see scripts/kit_update.py.
    try:
        import kit_update
        _upd = kit_update.pending_notice(os.environ.get("CLAUDE_SESSION_ID", ""))
        if _upd:
            items.append(("🔄", _upd[0], _upd[1]))
    except Exception:
        # Same rule as every other block here: a briefing that crashes blocks the session from
        # opening, which costs more than a missing line.
        pass

    # ONE follow-up parser, shared with check_followups.py. This block used to carry its own regex,
    # which read a single LINE and so knew nothing about completion markers, `FOLLOWUP-DUE: none`,
    # or the warm-only policy. It disagreed with the real checker, and the banner is what you read
    # first: a closed-out thread left at `status:armed` showed a phantom 🔴 here while the checker
    # correctly printed 🟢. Delegate instead of re-implementing; a second parser is a second answer.
    try:
        import check_followups
        fdue, _upcoming, _undated = check_followups.scan(today, repo=REPO)
        if fdue:
            items.append(("🔴", f"{len(fdue)} follow-up(s) DUE",
                          [f"{d} · {c}" for d, c in fdue[:5]]))
    except Exception:
        # DEGRADES GRACEFULLY: a briefing that crashes blocks the session from opening, which costs
        # more than a missing line. check_followups.py also runs standalone.
        pass

    # An unconfirmed send on a live thread is the most expensive thing to forget.
    corr = rd("documents/correspondence-log.md")
    draft_flags = re.findall(r"^.*status:\s*DRAFT[^\n]*$", corr, re.M | re.I)
    if draft_flags:
        items.append(("🔴", f"{len(draft_flags)} message(s) marked DRAFT, confirm whether sent",
                      [d.strip()[:70] for d in draft_flags[:3]]))

    # Stale unsent send-log rows (2026-07-27). mail-draft.sh writes an UNSENT status on every row
    # because it creates a visible mail draft and cannot know whether Send was pressed. The flip to
    # "sent" is manual, so a missed flip leaves a real send invisible to rung_ladder.
    # ⛔ The spelling is `staged` in this tree and `drafted` in older rows; both are recognised via
    # log_linkedin_send.UNSENT_STATUSES. Asserting a single spelling here is what made the reader
    # dead: it matched a value nothing in this tree writes and the alert could never fire.
    # Reader lives in pair_brief, which the pair's decision table also reads: one store, one parser.
    try:
        import pair_brief
        _stale = pair_brief.stale_drafted(repo=REPO)
        if _stale:
            items.append(("🔴", f"{len(_stale)} send-log row(s) still 'drafted', confirm whether sent",
                          _stale[:3]))
    except Exception:
        pass  # DEGRADES GRACEFULLY: a briefing that crashes blocks the session from opening.

    # Real inbound replies that may still be unanswered. Raw scan: this line answers "what is on
    # record", a different question from the pair's P1 ("what is still owed an answer",
    # pair_brief.open_inbound).
    try:
        import pair_brief
        replies = pair_brief.inbound_rows(repo=REPO)
    except Exception:
        replies = re.findall(r"^##[^\n]*(?:📥|INBOUND)[^\n]*$", corr, re.M)
    if replies:
        items.append(("🟡", f"{len(replies)} inbound message(s) on record",
                      [r.strip()[:70] for r in replies[-2:]]))

    # NETWORK FRESHNESS in the briefing, not only in the Stop-hook sweep.
    # The 3-3-3 picks 3 PEOPLE off warm-network.md every morning, so a stale roster silently
    # narrows the daily pick to whoever was in the last export. The briefing is the surface an
    # operator actually reads, and the whole point is that the lag stops being invisible.
    try:
        import check_network_freshness as _nf
        _item = _freshness_item(_nf.scan(), _nf.WARN_DAYS_DEFAULT)
        if _item:
            items.append(_item)
    except Exception:
        pass  # DEGRADES GRACEFULLY: a briefing that crashes blocks the session from opening.

    # CLOSENESS COVERAGE in the briefing — the PRIMARY prompt surface for the levelling loop.
    # The warm rungs (5-7) run on stated relationships (documents/contact-closeness.json), and
    # check_preview REFUSES warm-shaped asks the store does not sanction. So a missing or thin
    # store is unfinished work with a next step, not background noise.
    try:
        import closeness as _cl
        _store = _cl.load()
        if _store is None:
            items.append(("🟠", "no closeness store yet — warm rungs stay LOCKED until you level "
                                "your network",
                          ["download your LinkedIn export: Settings → Data privacy → Get a copy "
                           "of your data",
                           "drop the .zip in Downloads, then run /level-network"]))
        else:
            import level_contacts as _lc
            _todo = _lc.pending()
            if _todo:
                items.append(("🟡", f"{len(_todo)} contact(s) still unlevelled "
                                    f"({len(_store)} in the closeness store)",
                              ["run /level-network — it resumes exactly where you left off"]))
            # Staleness against the newest export ON DISK, recomputed live — the stamp is a
            # convenience, the two sources are the authority.
            _swept = (_lc.load_raw() or {}).get("_last_swept_export")
            try:
                from parse_network import find_export as _fe
                _p, _ = _fe()
                _newest = os.path.basename(str(_p).split("::")[0]) if _p else None
            except Exception:
                _newest = None
            if _newest and _swept and _newest != _swept:
                items.append(("🟠", f"a newer export is on disk ({_newest}) than the last "
                                    f"levelling sweep ({_swept})",
                              ["run /level-network — it only asks about the delta"]))
    except Exception:
        pass  # DEGRADES GRACEFULLY: a briefing that crashes blocks the session from opening.

    # UPSTREAM FEEDBACK not yet sent to the kit maintainer. Read-only, no gh call — send_feedback.py
    # owns the single parser (its FEEDBACK/status:unsent header regex) and the actual send.
    try:
        import send_feedback
        _fb = send_feedback.unsent(repo=REPO)
        if _fb:
            items.append(("🟠", f"{len(_fb)} upstream-feedback entr(ies) not yet sent to the kit maintainer",
                          [e["slug"] for e in _fb[:3]] + ["send: python3 scripts/send_feedback.py"]))
    except Exception:
        pass  # DEGRADES GRACEFULLY: a briefing that crashes blocks the session from opening.

    states = sorted(glob.glob(os.path.join(REPO, "documents", "session-state-*.md")))
    if states:
        newest = os.path.basename(states[-1])
        items.append(("📄", f"newest handoff: {newest}", []))
    return items


# ── B. TODAY'S 3-3-3 ─────────────────────────────────────────────────────────────────────────
def sends_today():
    """Delegates to pair_brief, the ONE counter.

    The pair's decision table branches on this exact number, so a second copy here would let the
    briefing and the picker disagree about whether the day's loop is closed. Falls back to the local
    regex only if the import fails, because a briefing must degrade rather than crash.
    """
    try:
        import pair_brief
        return pair_brief.sends_today(repo=REPO)
    except Exception:
        log = rd("outreach_log.md")
        return len(re.findall(r"^##\s*" + re.escape(date.today().isoformat()), log, re.M))


def deal_breaker_blocked():
    """Companies excluded outright. Deal-breakers apply at EVERY rung, warm or cold."""
    names = set()
    for line in rd("documents/blocked-employers-list.md").splitlines():
        m = re.match(r"\s*-\s+([A-Z][\w&.\-' ]{1,40}?)\s*[\(—]", line)
        if m:
            names.add(m.group(1).strip().lower())
    return names


def contacted():
    names = set()
    try:
        p = os.path.join(REPO, "job_search_tracker.csv")
        if os.path.exists(p):
            for r in csv.reader(open(p, encoding="utf-8", errors="ignore")):
                if len(r) > 6 and r[6].strip().lower() in ("sent", "applied", "contacted", "interviewing"):
                    names.add(r[1].strip().lower())
    except Exception:
        pass
    return names


def pick_companies(blocked, done, n=3):
    """3 companies from the active board, then the warm-sourced list. Deal-breakers + your own past
    employers (kit_config.EXCLUDED_EMPLOYERS) are filtered out."""
    out = []
    for line in rd("documents/green-board.md").splitlines():
        if not line.strip().startswith("|") or line.count("|") < 8:
            continue
        cells = [c.strip().strip("*~ ") for c in line.split("|")]
        if len(cells) < 3:
            continue
        # green-board.md holds TWO tables: the numbered board (| # | Company | …) and a radar table
        # below it with NO '#' column, so radar cells sit one to the LEFT. Hardcoding index 2 would
        # read a radar row's LANE as its company name — the daily briefing would hand the operator
        # "Legaltech / citation + fact-verify AI (no hallucination)" as a target company. The same
        # defect is fixed the same way in the ranker's row_offset and the consistency check; this
        # third site was missed on the first pass and found by audit.
        off = 1 if len(cells) > 1 and cells[1].strip().isdigit() else 0
        co = cells[1 + off] if len(cells) > 1 + off else ""
        if not re.match(r"^[A-Z]", co) or co.startswith("~~"):
            continue
        # Skip the markdown table's own header/separator rows — "Company" was being picked as a
        # target on the first run, which is the kind of thing that erodes trust in a briefing fast.
        if co.lower() in ("company", "lane", "boss + email", "status", "culture (sub-ratings)"):
            continue
        low = co.lower()
        if low in blocked or low in done or is_excluded_employer(co) or "SENT" in line.upper():
            continue
        out.append((co, "board · cold-boss rung"))
    for line in rd("documents/warm-network.md").splitlines():
        if len(out) >= n * 3:
            break
        m = re.match(r"\|\s*\d+\s*\|\s*\*\*([^*]+)\*\*", line)
        if m:
            co = m.group(1).strip()
            low = co.lower()
            if (low not in blocked and low not in done and not is_excluded_employer(co)
                    and co not in [c for c, _ in out]):
                out.append((co, "warm network · warm rung"))
    return out[:n]


def pick_people(n=3):
    """3 people from the warm network. Contacts at your own past employers
    (kit_config.EXCLUDED_EMPLOYERS) are filtered out here."""
    out = []
    for line in rd("documents/warm-network.md").splitlines():
        m = re.match(r"\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if m and not line.strip().startswith("| |") and "**" not in m.group(1):
            name, title, co = (x.strip() for x in m.groups())
            if name and name.lower() not in ("name",) and len(name) > 3 and not is_excluded_employer(co):
                out.append((name, title[:34], co[:22]))
        if len(out) >= n:
            break
    return out


def main():
    print("=" * 72)
    print("  JOB ATTRACTOR — LaCivita flow.  3 companies · 3 people · 3 messages.")
    print("=" * 72)

    # 📰 WHAT CHANGED IN THE KIT, at the very top and before the work.
    # The kit updates itself, so scripts and rules move underneath you without being asked. A
    # silent update is indistinguishable from a bug: the briefing prints something new, the ranker
    # orders people differently, and "it broke" is the only explanation available. This line is the
    # difference between an update you can reason about and one you have to reverse-engineer.
    # DEGRADES GRACEFULLY, like every other block here: a briefing that crashes blocks the session.
    try:
        import release_notes
        _rn = release_notes.banner()
        if _rn:
            print()
            print(_rn)
    except Exception:
        pass

    items = unfinished()
    section("A. UNFINISHED WORK")
    if items:
        for icon, head, detail in items:
            print(f"  {icon} {head}")
            for d in detail:
                print(f"       {d}")
    else:
        print("  ✅ nothing outstanding")

    section(f"B. TODAY'S 3-3-3  ({date.today().isoformat()})")
    n = sends_today()
    print(f"  messages sent today: {n} / 3" + ("   ✅ loop closed" if n >= 3 else "   ⬅ not yet done"))
    # TWO COUNTERS, ONE NUMBER. This line counts `## <date>` write-ups in outreach_log.md;
    # consistency-check [13] and the pair's stamp count delivered send-log rows. Neither is broken,
    # they answer different questions, and which one IS the 3-3-3 is YOUR ruling. Printing the
    # disagreement is what stops it being invisible.
    try:
        import pair_brief
        _gap = pair_brief.counter_gap(repo=REPO)
        if _gap:
            print(f"  ⚠️ counters disagree: {_gap[0]} write-up(s) in outreach_log, {_gap[1]} "
                  f"delivered row(s) in send-log. The stamp uses the send-log count.")
    except Exception:
        pass  # DEGRADES GRACEFULLY: a briefing that crashes blocks the session from opening.

    blocked, done = deal_breaker_blocked(), contacted()
    # THE 3 COMPANIES ARE THE TOP OF A CRITERIA-RANKED 10 (design ruling: with only 3-3-3 to spend a
    # day, pick from the top 10 companies ranked by your criteria, not the first 3 in file order).
    # rank_criteria.py ranks the vetted board (topped up from discovery) against the criteria matrix
    # and prints the 10 with a per-criterion breakdown; the operator picks 3. Falls back to the old
    # first-3 picker only if the ranker cannot run, so a briefing never goes blank.
    ranked_ok = False
    try:
        import rank_criteria
        ranked, _skipped = rank_criteria.rank(10)
        if ranked:
            ranked_ok = True
            print("\n  TOP 10 COMPANIES BY YOUR CRITERIA — pick 3 to work today:")
            for i, c in enumerate(ranked, 1):
                tag = rank_criteria.TIER_LABEL[c["tier"]]
                print(f"    {i:2}. {c['company']:<22} {tag:<16} score {c['pts']:>4}  · {c['lane'][:32]}")
            print("    (culture-screen confidence folded into the score · full breakdown: "
                  "scripts/rank_criteria.py)")
    except Exception:
        ranked_ok = False
    cos = [] if ranked_ok else pick_companies(blocked, done)
    if cos:
        print("\n  3 COMPANIES (deal-breaker screened, not fully screened):")
        for co, src in cos:
            print(f"    • {co:<28} {src}")

    # THE 3 PEOPLE ARE THE TOP OF A RANKED 10 too (design ruling): rank the warm network by "who can
    # help first" — scoring v2 (2026-07-26) reads LIKELY-BOSS-NESS + RELATIONSHIP DISTANCE, the
    # boss-hunt method's own two axes, deal-breaker vetoes only. Re-run after each pick to re-rank
    # the rest. Falls back to the old first-3 picker if the ranker errors.
    # Scores are FLOATS under v2 (distance is +0.5/yr, capped), so the width below is :>5, not :>3.
    # A too-narrow field does not truncate in Python, it just stops aligning — the column silently
    # ragged is how a "44.5" reads as noise next to a "40".
    ppl_ranked = False
    try:
        import rank_criteria
        rpeople, _ = rank_criteria.rank_people(10)
        if rpeople:
            ppl_ranked = True
            print("\n  TOP 10 PEOPLE — who can help first (pick 3 to reach):")
            for i, c in enumerate(rpeople, 1):
                # 🔬 THE EVIDENCE TIER SHOWS PER ROW. The blanket disclaimer below is not a per-row
                # state: a whole top ten can be employers no source could place, and the list still
                # reads like a clean ranking.
                _ev = rank_criteria.contact_signals.EV_LABEL.get(
                    c.get("evtier", rank_criteria.contact_signals.EV_UNLOOKED), "")
                print(f"    {i:2}. {c['name']:<22} {rank_criteria.PERSON_BADGE[c['cat']]:<16} "
                      f"score {c['pts']:>5}  · {c['title'][:26]:<26} @ {c['company'][:22]}")
                print(f"        {_ev}")
                # ⛔ A ROLE THAT HAS ENDED PRINTS ON THE ROW ITSELF.
                # `contact_signals.role_tell` knows when a stored title was verified dead, and the
                # ranker puts that string in the row's reasons. This block used to render ONLY the
                # name and score, so the warning existed in the data and never reached the screen.
                # Cost when that happened upstream: a contact ranked #1 on a title they had left
                # SIX YEARS earlier, and the day's target was picked on it.
                # ⚠️ ROLE ENDED only, never the "title unverified" tell: that one fires on nearly
                # every row, and rank_criteria deliberately says it ONCE for that reason. A warning
                # printed ten times is a warning nobody reads.
                # ⚖️ The general lesson: a signal is not shipped when the function returns it. It is
                # shipped when the surface that drives the decision prints it. When wiring a new
                # signal, check EVERY renderer that shows that object.
                _ended = next((str(r) for r in c.get("reasons", []) if "ROLE ENDED" in str(r)), "")
                if _ended:
                    print(f"        {_ended[:150]}")
            print("    (likely-boss + relationship distance, scoring v2 2026-07-26; deal-breakers "
                  "only, culture waits · re-ranks after each pick)")
            # 🕰 The unverified-title count, said ONCE, mirroring rank_criteria's own summary line.
            # A connections export records a title as it stood on the CONNECT date, so a row can be
            # years stale and still read as current.
            _stale = sum(1 for c in rpeople
                         if any("title unverified" in str(r) for r in c.get("reasons", [])))
            if _stale:
                print(f"    🕰 {_stale} of {len(rpeople)} titles were never verified; the export "
                      f"froze them at the CONNECT date. Open the profile before building.")
            # The age of the learned weights, so a session can SEE whether the ordering it is
            # reading was computed off a log that has since moved. Guarded because a briefing must
            # never block a session: an unreadable weights store loses this line, not the picks.
            try:
                print(rank_criteria._weights_age_line())
            except Exception:
                pass

            # RECENT-CONNECTION LANE. Recent connections never surfaced. Two reasons: nothing
            # scored, and search-era contacts carry a deliberate penalty, because a two-week-old
            # connection is not a warm rung — warm-network.md's own legend says a search-era
            # contact must not receive a warm-rung ask. So the answer is not to promote them into
            # the warm list, which would re-create that defect. It is to give them their OWN lane
            # at the correct rung, where they are visible and correctly labelled instead of
            # invisible or mis-rung'd. (Fixed 2026-07-27: this lane had been mis-ported INTO the
            # exception handler below, where it was dead code on every successful ranking.)
            try:
                _recent = [c for c in rank_criteria.rank_people(400)[0]
                           if c.get("distance") == "search-era"][:5]
            except Exception:
                _recent = []
            if _recent:
                print("\n  🆕 RECENTLY CONNECTED — common-interest rung (1-2), NOT a warm ask:")
                for c in _recent:
                    print(f"      · {c['name']:<22} {c['title'][:26]:<26} @ {c['company'][:22]}")
                print("    (met during the search, so ask about THEIR work, never for an intro)")
    except Exception:
        ppl_ranked = False
    ppl = [] if ppl_ranked else pick_people()
    if ppl:
        print("\n  3 PEOPLE (warm network, excluded employers filtered at source):")
        for nm, ti, co in ppl:
            print(f"    • {nm:<24} {ti:<34} {co}")
    # Show the "no targets" prompt ONLY when nothing at all was surfaced — ranked OR fallback.
    # (Before people-ranking, ppl was always non-empty, which masked this; now both can be empty
    # precisely because the RANKED lists were shown, so check the ranked flags too.)
    if not (ranked_ok or cos or ppl_ranked or ppl):
        print("\n  No targets on file yet. Step one of the method:")
        print("    1. Build a target list (LaCivita's 12 steps).")
        print("    2. Identify a person per company: boss > teammate > recruiter > connection.")
        print("    3. Send 3 messages. Pick the rung first, then the template.")

    print("\n  Rung decides screen depth AND message shape:")
    print("    cold-boss  → full screen + sourced accomplishment + two-stage praise")
    print("    warm/refd  → deal-breakers only, no praise beat, --targets required")
    print("\n  Both lists above are SUGGESTIONS. Nothing is drafted or sent.")
    print("=" * 72)


# THE PAIR INSTRUCTION. Kept as a module constant so check_pair's block message, the consistency
# step and the tests all read the SAME string instead of three paraphrases of it.
#
# ⛔ NO BUILD VOCABULARY IN THE PICKER'S QUESTION OR HEADER. record_decision.classify_answer reads
# those two fields as BUILD CONTEXT, so a question phrased "draft the next step?" plus a "yes"
# would be promoted into a MAC-signed BUILD row: an authorization nobody gave, in the one store
# that exists to make authorization unforgeable. This picker is an audit-trail row and nothing more.
PAIR_INSTRUCTION = (
    "\n\nTHE PAIR. Open by showing the ladder summary above, then present the next-step picker: "
    "option 1 is the METHOD's derived default, NAMED as the method's, with its read in the "
    "description. The question and header must carry the literal marker NEXT-STEP and the LADDER "
    "stamp line, verbatim, or check_pair.py blocks the question. Recompute both with "
    "`python3 scripts/pair_brief.py` every time; never carry a ladder summary forward from an "
    "earlier message. The same pair is owed again whenever a piece of work reaches a stopping "
    "point, INCLUDING a status report, which is a finished task wearing a different hat. "
    "Phrase the question and header as 'next move' or 'what now' and keep build/draft/send "
    "vocabulary OUT of them.\n"
)


def pair_block(full=True):
    """The pair's own section of the briefing. Never raises: the caller is a session-open hook."""
    try:
        import pair_brief
        return "\n\n" + pair_brief.render(full=full)
    except Exception as e:
        return (f"\n\n[pair_brief] unavailable ({type(e).__name__}). Run "
                "`python3 scripts/rung_ladder.py` by hand and still show the pair.")


def as_hook(pair_only=False):
    """SessionStart hook mode: emit the briefing as additionalContext so it lands in model context.

    The runtime supports SessionStart with matchers startup / resume / clear / compact, and
    `hookSpecificOutput.additionalContext` is documented as "Text injected into model context."
    Plain stdout would only reach the transcript; the whole point is that the agent BEGINS the
    method rather than waiting to be told to.

    `--pair-only` is the COMPACT variant wired to the `compact` matcher. Compaction is one of the
    mechanisms by which a standing instruction silently stops applying: it happens unannounced,
    mid-work, precisely when the method context has just been summarized away. Re-injecting the
    whole briefing there would be noise; re-injecting the pair instruction plus a fresh stamp is
    the direct fix.
    """
    import io
    import json
    from contextlib import redirect_stdout
    if pair_only:
        brief = "COMPACTION RE-INJECTION: the standing pair rule, plus today's live numbers."
        brief += pair_block(full=False)
    else:
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                main()
            brief = buf.getvalue()
        except Exception as e:
            brief = (f"[session_start] briefing unavailable ({type(e).__name__}). "
                     "Run the method manually: 3 companies, 3 people, 3 messages.")
        brief += pair_block(full=True)
    instruction = (
        "\n\nThis is the Job Attractor pipeline. Its operating method is Andrew LaCivita's: "
        "3 companies, 3 people, 3 messages per day, on a never-ending loop. "
        f"Open by showing {OWNER_FIRST} BOTH the unfinished work and today's 3-3-3 above, then ask "
        "which is wanted. Do NOT draft or send anything before a choice is made. Pick each target's "
        f"RUNG first because the rung sets both the screen depth and the message shape — the rules "
        f"live in {RULES_DOC}. Re-read {RULES_DOC} from the file at every gate, never from memory.\n"
    ) if not pair_only else ""
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": brief + instruction + PAIR_INSTRUCTION,
    }}))


if __name__ == "__main__":
    try:
        if "--hook" in sys.argv:
            as_hook(pair_only="--pair-only" in sys.argv)
        else:
            main()
    except Exception as e:
        # A briefing that crashes must never block a session from opening.
        print(f"[session_start] briefing unavailable ({type(e).__name__}). "
              f"Run the method manually: 3 companies, 3 people, 3 messages.")
    sys.exit(0)
