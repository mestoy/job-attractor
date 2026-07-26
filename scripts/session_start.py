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
def unfinished():
    items, today = [], date.today().isoformat()

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

    # Real inbound replies that may still be unanswered.
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
        _s = _nf.scan()
        if _s["newest_connection"] and _s["data_lag_days"] is not None:
            _lag = _s["data_lag_days"]
            if _s["parse_is_behind_export"]:
                items.append(("🟠", f"warm-network is behind an export on disk "
                                    f"(parsed {_s['newest_connection']}, available "
                                    f"{_s['export_newest_connection']})",
                              ["fix: python3 scripts/parse_network.py"]))
            elif _lag >= _nf.WARN_DAYS_DEFAULT:
                items.append(("🟠", f"warm-network data is {_lag} days old",
                              [f"newest connection on file: {_s['newest_connection']}",
                               "anyone connected since then is invisible to today's 3 people",
                               "fix: download a fresh LinkedIn export, then parse_network.py"]))
    except Exception:
        pass  # DEGRADES GRACEFULLY: a briefing that crashes blocks the session from opening.

    states = sorted(glob.glob(os.path.join(REPO, "documents", "session-state-*.md")))
    if states:
        newest = os.path.basename(states[-1])
        items.append(("📄", f"newest handoff: {newest}", []))
    return items


# ── B. TODAY'S 3-3-3 ─────────────────────────────────────────────────────────────────────────
def sends_today():
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
    # help first" (relationship + role), LaCivita's method, deal-breaker vetoes only. Re-run after
    # each pick to re-rank the rest. Falls back to the old first-3 picker if the ranker errors.
    ppl_ranked = False
    try:
        import rank_criteria
        rpeople, _ = rank_criteria.rank_people(10)
        if rpeople:
            ppl_ranked = True
            print("\n  TOP 10 PEOPLE — who can help first (pick 3 to reach):")
            for i, c in enumerate(rpeople, 1):
                print(f"    {i:2}. {c['name']:<22} {rank_criteria.PERSON_BADGE[c['cat']]:<16} "
                      f"score {c['pts']:>3}  · {c['title'][:26]:<26} @ {c['company'][:22]}")
            print("    (relationship+role, deal-breakers only, culture waits · re-ranks after each pick)")
    except Exception:
            # RECENT-CONNECTION LANE. Recent connections never surfaced. Two reasons: nothing scored, and search-era contacts carry a deliberate -2
            # because a two-week-old connection is not a warm rung — warm-network.md's own legend says a search-era contact
            # must not receive a warm-rung ask. So the answer is not to promote them into the warm list, which would
            # re-create that defect. It is to give them their OWN lane at the correct rung, where
            # they are visible and correctly labelled instead of invisible or mis-rung'd.
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


def as_hook():
    """SessionStart hook mode: emit the briefing as additionalContext so it lands in model context.

    The runtime supports SessionStart with matchers startup / resume / clear / compact, and
    `hookSpecificOutput.additionalContext` is documented as "Text injected into model context."
    Plain stdout would only reach the transcript; the whole point is that the agent BEGINS the
    method rather than waiting to be told to.
    """
    import io
    import json
    from contextlib import redirect_stdout
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            main()
        brief = buf.getvalue()
    except Exception as e:
        brief = (f"[session_start] briefing unavailable ({type(e).__name__}). "
                 "Run the method manually: 3 companies, 3 people, 3 messages.")
    instruction = (
        "\n\nThis is the Job Attractor pipeline. Its operating method is Andrew LaCivita's: "
        "3 companies, 3 people, 3 messages per day, on a never-ending loop. "
        f"Open by showing {OWNER_FIRST} BOTH the unfinished work and today's 3-3-3 above, then ask "
        "which is wanted. Do NOT draft or send anything before a choice is made. Pick each target's "
        f"RUNG first because the rung sets both the screen depth and the message shape — the rules "
        f"live in {RULES_DOC}. Re-read {RULES_DOC} from the file at every gate, never from memory.\n"
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": brief + instruction,
    }}))


if __name__ == "__main__":
    try:
        if "--hook" in sys.argv:
            as_hook()
        else:
            main()
    except Exception as e:
        # A briefing that crashes must never block a session from opening.
        print(f"[session_start] briefing unavailable ({type(e).__name__}). "
              f"Run the method manually: 3 companies, 3 people, 3 messages.")
    sys.exit(0)
