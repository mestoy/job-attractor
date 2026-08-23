#!/usr/bin/env python3
"""contact_card.py — the CONTACT scorecard that must be shown before any co-creation.

WHY THIS EXISTS (the upstream operator ruled it 2026-08-11): *"Why is <that person> the highest
ranked? You should give me a scorecard on a contact before starting the co-creation picker. This
should be our operating model."*

🔴 THE HOLE IT CLOSES. The BUILD gate demands a scorecard before any COMPANY or BOSS work. A rung
1-2 note rides the `RUNG12` exemption in `check_preview.py`, which skips the scorecard entirely, so
three notes were co-created on 2026-08-11 with the owner never shown who the person was or why them.
The exemption is correct about AUTHORIZATION (a zero-ask note needs no build ruling) and was wrong
about INFORMATION.

📊 THE RECEIPT THAT PROVOKED IT. `rank_criteria --pool people` offered a named contact at "score
39.6" as the day's pick. FIVE more rows also scored **39.6**, and the stated reasoning was
byte-identical across five of the six: `🏢 senior exec · reply-evidence ×1.28 (6/28 joined sends) · known 2.4y
(+1.2) · ⚠️ title unverified`. Not one of those terms is about the PERSON — two are a category
average and one is a connect date. That contact was not the highest ranked. They were first in a
six-way tie, broken by connect date, presented as a #1 pick.
⚖️ Same family as [[a-uniform-penalty-cannot-break-a-tie]]: a term every candidate shares cannot
order them, and a display that hides the tie turns an arbitrary pick into an apparent verdict.

WHAT THE CARD MUST CARRY (his ruling, all four):
  1. WHY THEM, and WHO ELSE TIED — the ranker's own reasoning plus everyone within 0.1, with the
     tiebreak named out loud.
  2. LIVE-VERIFIED TITLE — checked against the profile, never the export, with the snapshot age
     shown. An export freezes a title at the connect date; one contact's had moved two years.
  3. RUNG, CLOSENESS AND WHAT IT SANCTIONS — the stated tier, the evidence behind it, and what the
     rung forbids.
  4. DEAL-BREAKER SCREEN ON THE EMPLOYER — at the depth the rung requires.

⭐ AND A FIFTH, STANDING (the operator's words): *"the ranker should evolve according to the best
method at the time."* This card is therefore also an INSTRUMENT: by printing what the ranker used,
it makes a weak signal visible. On day one it showed the whole top band separated by nothing, while
a recruiter-titled contact further down carried a reply rate the ranker cannot see.
Ties: [[ranker-weights-learn-continuously]] · [[validate-a-signal-against-outcomes-before-scoring-it]]

⛔ THIS CARD IS INFORMATION, NOT AUTHORIZATION. It carries no MAC and cannot promote itself, exactly
like `record_scorecard.py`. It records that the owner was SHOWN who this person is. Presenting it is
the requirement; their ruling remains theirs.

Usage:
    scripts/contact_card.py "Full Name"          # print the card
    scripts/contact_card.py "Full Name" --record # print it AND stamp that it was shown
    scripts/contact_card.py --shown "Full Name"  # was a card shown for them this session?

Stdlib only. Exit: 0 ok · 2 contact not found · 3 usage
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
SHOWN = os.path.join(REPO, "documents", "state", "contact-cards-shown.jsonl")


def _shown_path():
    """The store path, resolved at CALL time from the environment.

    ⛔ NOT the module-level `SHOWN` constant alone. `REPO` is computed at IMPORT from
    `CLAUDE_PROJECT_DIR`, so anything that redirects that variable AFTER this module is first
    imported (a test harness, a sandboxed run, a second project in one process) keeps writing to
    and reading from the first path the module ever saw. That is the same frozen-at-import defect
    as a `def load(path=STORE)` default, one level up, and it was caught the same way: by a test
    that set the env var in setUp and watched the gate answer from the wrong file.
    ⚖️ `SHOWN` stays as the module default so anything that patches it directly still works.
    """
    repo = os.environ.get("CLAUDE_PROJECT_DIR")
    if repo and os.path.dirname(os.path.dirname(SHOWN)) != repo:
        return os.path.join(repo, "documents", "state", "contact-cards-shown.jsonl")
    return SHOWN
TIE_BAND = 0.1     # the ranker's own tie width; anyone inside it is not distinguishable

# ⏳ A CARD IS GOOD FOR THE CALENDAR DAY IT WAS SHOWN.
# ⛔ WHY THIS DIVERGES FROM record_scorecard, on purpose. The company scorecard AUTHORIZES a build,
# so it must age fast (a 2h window) and be spent per picker — one ruling cannot open an unbounded
# build. This card AUTHORIZES NOTHING (it carries no MAC); it records only that the human was SHOWN
# who a person is. An information token is not "spent": being shown who someone is once covers every
# beat of that same note. An earlier cut copied BOTH authorization halves — a 120-min TTL and
# one-picker consumption — and both were category errors here. Co-construction runs the WHOLE
# message beat by beat (many pickers over a long build), so the 2h TTL lapsed mid-build and the next
# beat false-blocked; and the consumption half was dead code no caller ever wrote to. The property
# worth keeping is STALENESS: a card shown on a PRIOR day may name a rank/title/screen that has
# since moved, so it must not satisfy. The calendar day is exactly that line — one showing spans a
# whole note-build, while yesterday's card blocks. consume() is retired with this change: an
# unreferenced "check" reads like a working gate and is worse than none.



def _reason_terms(why):
    """A reason string reduced to its SCORING terms, provenance stripped.

    ⛔ DELEGATES TO `rank_criteria.reason_terms`, which is now the ONE definition of "the same
    reason" (lifted there 2026-08-11 so the ranker's tie tripwire and the QA tie-rate metric share
    it). The local fallback exists only for an install where the ranker will not import; it is a
    copy of the same expression and must be changed with it, never instead of it.

    `🔬 employer resolved (<url>)` is provenance, not a term that ordered anything, and leaving it
    in makes every row look unique. Shared with the ranker's own tie tripwire so there is one
    definition of "the same reason" rather than two that drift.
    """
    try:
        sys.path.insert(0, HERE)
        import rank_criteria
        return rank_criteria.reason_terms(why)
    except Exception:
        return " ".join(re.sub(r"·?\s*🔬 employer resolved \([^)]*\)", "", why or "").split())


def _closeness():
    sys.path.insert(0, HERE)
    import closeness
    return closeness


def _store():
    path = os.path.join(REPO, "documents", "contact-closeness.json")
    try:
        return json.load(open(path, encoding="utf-8")).get("contacts", {})
    except Exception:
        return {}


def _row_for(name):
    cl, store = _closeness(), _store()
    idx = {cl.normalize_name(k): k for k in store}
    key = idx.get(cl.normalize_name(name))
    return (key, store.get(key)) if key else (None, None)


def _ranked(limit=40):
    """[(rank, name, score, why, ask)] from the people ranker, or [] when it cannot run.

    Parsed from the ranker's own OUTPUT rather than re-implemented. Re-deriving the score here
    would create a second writer of one fact, and the two would drift the first time either moved
    ([[never-measure-a-tree-with-two-writers]]).
    """
    import subprocess
    try:
        out = subprocess.run([sys.executable, os.path.join(HERE, "rank_criteria.py"),
                              "--pool", "people", "--n", str(limit)],
                             capture_output=True, text=True, timeout=180, cwd=REPO).stdout
    except Exception:
        return []
    rows, cur = [], None
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\.\s+(.+?)\s+[·🏢📇🎯].*?score\s+([\d.]+)", line)
        if m:
            cur = {"rank": int(m.group(1)), "name": m.group(2).strip(),
                   "score": float(m.group(3)), "why": "", "ask": ""}
            rows.append(cur)
            continue
        if cur is not None:
            s = line.strip()
            if s.startswith("why:"):
                cur["why"] = s[4:].strip()
            elif s.startswith("ask:"):
                cur["ask"] = s[4:].strip()
    return rows


def _groups(name):
    try:
        sys.path.insert(0, HERE)
        import mutual_groups
        return mutual_groups.groups_for(name)
    except Exception:
        return None


def _strongest_inbound(name):
    try:
        sys.path.insert(0, HERE)
        import level_contacts
        return level_contacts._evidence_for(name, level_contacts._inbound_evidence())
    except Exception:
        return None


def _blocked(company):
    if not company:
        return None
    try:
        sys.path.insert(0, HERE)
        import rank_criteria
        return company.strip().lower() in rank_criteria.blocked_set()
    except Exception:
        return None


# ⭐ HOW LONG YOUR OWN VERIFICATION STAYS TRUSTED before this card falls back to the
# unconditional export-frozen warning again (kit issue #60). A live check is a stronger signal
# than the export snapshot, but it is not permanent — a role recorded 8 months ago is no more
# trustworthy than the export it was meant to supersede. Set generously relative to
# check_network_freshness.py's own 7/14-day export thresholds, because a human opened a profile
# and read it, which is a materially stronger claim than an unmaintained CSV's age.
ROLE_VERIFICATION_FRESH_DAYS = 90


def _verified_role(key):
    """The newest human-checked role for this contact, or None. Reads `contact_signals.ROLE_CACHE`
    (kit issue #60): `record_role.py` writes here and nothing was reading it, so a verification
    could never satisfy the gate that demanded it."""
    try:
        sys.path.insert(0, HERE)
        import contact_signals
        return contact_signals.verified_role(key)
    except Exception:
        return None


def _role_is_fresh(verified):
    if not verified or not verified.get("verified_on"):
        return False
    try:
        when = datetime.date.fromisoformat(verified["verified_on"])
    except (ValueError, TypeError):
        return False
    return (datetime.date.today() - when).days <= ROLE_VERIFICATION_FRESH_DAYS


_EXPORT_ROWS = None


def _export_role(key):
    """(company, title) for this contact from the newest LinkedIn export on disk, or ("", "").

    Kit issue #55 #1: the card used to regex a free-text `note` field for the employer and
    reported `unknown` on 83 of 83 real contacts checked, even though the export holds a Company
    AND a Position column for every one of them. Join to the export instead of parsing prose.
    """
    global _EXPORT_ROWS
    if _EXPORT_ROWS is None:
        _EXPORT_ROWS = {}
        try:
            sys.path.insert(0, HERE)
            import parse_network as pn
            cl = _closeness()
            _path, text = pn.find_export()
            if text:
                for r in pn.parse_rows(text):
                    who = f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip()
                    if who:
                        _EXPORT_ROWS[cl.normalize_name(who)] = (
                            (r.get("Company") or "").strip(), (r.get("Position") or "").strip())
        except Exception:
            pass
    cl = _closeness()
    return _EXPORT_ROWS.get(cl.normalize_name(key), ("", ""))


def card(name, limit=40):
    key, row = _row_for(name)
    if row is None:
        print(f"🔴 {name}: no closeness row. The pipeline does not know this person; "
              f"level them first (scripts/level_contacts.py --name \"{name}\").")
        return 2
    cl = _closeness()
    note = row.get("note") or ""
    company = ""
    m = re.search(r"\|\s*([^.|]+?)\s*\.\s*Connected", note) or re.search(r"\|\s*(.+)$", note)
    if m:
        company = m.group(1).strip()

    ranked = _ranked(limit)
    me = next((r for r in ranked if cl.normalize_name(r["name"]) == cl.normalize_name(key)), None)
    ties = [r for r in ranked if me and abs(r["score"] - me["score"]) <= TIE_BAND] if me else []

    print(f"\n╔══ CONTACT SCORECARD · {key}")
    print(f"║  {note or '(no note on file)'}")
    print("╠══ 1. WHY THEM")
    if me:
        print(f"║  rank {me['rank']} · score {me['score']}")
        print(f"║  the ranker's own words: {me['why'] or '(none given)'}")
        if len(ties) > 1:
            others = [t["name"] for t in ties if t is not me]
            print(f"║  ⚠️  TIED AT {me['score']} WITH {len(ties) - 1} OTHER(S): {', '.join(others[:6])}")
            # ⛔ REPORT THE MODAL REASON, NEVER DEMAND UNANIMITY. Two cuts of this failed before
            # the third worked, and both failures are the same mistake in different clothes:
            #   1. compared the WHOLE `why` string — every row ends with a `🔬 employer resolved
            #      (<url>)` provenance clause and the URL differs per person, so six identical
            #      scores read as six different reasons.
            #   2. stripped that clause and still required ALL tied rows to match — 5 of the 6 do
            #      and the 6th carries an extra govtech tag, so one odd row silenced the warning
            #      about the other five.
            # The question is not "are they all identical", it is "how many of them is the ranker
            # failing to tell apart", and the answer is a COUNT. Same family as
            # [[a-check-must-measure-the-thing-not-a-proxy]].
            counts = collections.Counter(_reason_terms(t["why"]) for t in ties)
            modal, n_modal = counts.most_common(1)[0]
            if n_modal > 1:
                print(f"║  🔴 {n_modal} OF THESE {len(ties)} CARRY THE IDENTICAL REASON, so the ranker is not")
                print("║     telling them apart. The order here is the TIEBREAK (older connect date")
                print("║     first), never a verdict. Picking the top row is picking a coin flip.")
                print(f"║     shared reason: {modal[:150]}")
        else:
            print("║  ✅ not tied — this row is separated from the next on its own merits")
    else:
        print("║  ⚪ not in the ranked pool (already contacted, held, or blocked employer)")

    print("╠══ 2. TITLE AND EMPLOYER")
    # Preference order for the employer this card acts on: your own live-profile check (kit
    # issue #60) > the newest LinkedIn export's Company column (kit issue #55 #1, a real join,
    # not a note regex) > the export note's free-text parse above, kept as a last resort for a
    # contact who predates both stores.
    verified = _verified_role(key)
    export_company, export_title = _export_role(key)
    if verified and verified.get("company"):
        company = verified["company"]
        source_label = "verified"
    elif export_company:
        company = export_company
        source_label = "export (Company column)"
    else:
        source_label = "export note" if company else "unresolved"
    print(f"║  employer ({source_label}): {company or 'unknown'}")
    b = _blocked(company)
    print(f"║  blocked-list: {'🔴 BLOCKED' if b else '✅ not blocked' if b is False else '⚪ unknown'}")
    fresh = _role_is_fresh(verified)
    if verified and verified.get("still_there") is False:
        print(f"║  ⛔ ROLE ENDED — verified {verified['verified_on']} ({verified.get('source_type', 'unverified')}): "
              f"{verified.get('note') or 'no longer in the stored role'}")
    elif verified and fresh:
        title = verified.get("title") or export_title or "?"
        print(f"║  ✅ verified {verified['verified_on']} ({verified.get('source_type', 'unverified')}) "
              f"— {title} @ {verified.get('company') or company or '?'}")
    else:
        # ⛔ THE WARNING IS CONDITIONAL, NOT UNCONDITIONAL (kit issue #60). It used to fire on
        # every run regardless of whether a verification existed, so your own recorded check
        # could never satisfy the gate that demanded it — an unfalsifiable instruction is worse
        # than no instruction, because it trains the reader to skim past a real ⛔.
        if verified:
            print(f"║  ⚠️  last verified {verified['verified_on']}, over {ROLE_VERIFICATION_FRESH_DAYS}d ago — "
                  "treat as export-frozen again")
        print("║  ⛔ TITLE IS FROM THE EXPORT AND IS FROZEN AT THE CONNECT DATE. Verify it on")
        print("║     the live profile before writing anything. One contact's had moved two years.")

    print("╠══ 3. RUNG AND WHAT IT SANCTIONS")
    tier = row.get("closeness") or "unset"
    held = cl.is_held(row)
    rung = cl.rung_for(row, "other")
    print(f"║  closeness: {tier}   (source: {row.get('source') or '-'})")
    if row.get("how_known"):
        print(f"║  his words: {row['how_known'][:150]}")
    if held:
        print(f"║  ⛔ HELD: {held}")
    print(f"║  sanctioned band: {rung[1]}")
    print(f"║  the ask: {rung[2]}")

    print("╠══ 4. EVIDENCE BEHIND THE TIER")
    hit = _strongest_inbound(key)
    if hit:
        print(f'║  💬 [{hit[0]}] them: "{hit[1][:150]}{"…" if len(hit[1]) > 150 else ""}"')
    else:
        print("║  💬 nothing substantive from them (pleasantries only, or no thread)")
    g = _groups(key)
    if g:
        print(f"║  👥 shares: {'; '.join(g)}")
    elif g is None:
        print("║  👥 groups not checked — scripts/mutual_groups.py --queue")
    else:
        print("║  👥 checked, no shared groups")
    # ── 5. THE BOSS/COMPANY HALF, merged in per the owner's 2026-08-11 ruling ──────────────────────────
    # ⭐ "Every contact, all rungs, card MERGED with the boss card" — one artifact per outreach at
    # any rung, so there is never a contact card AND a separate scorecard to reconcile.
    # ⚖️ It appears only when an employer resolves, because a rung 1-2 note to someone at a company
    # you will never apply to does not need a company screen, and printing an empty one would train
    # the reader to skip the section on the day it matters.
    if company:
        print("╠══ 5. THE COMPANY, if this becomes a boss ask")
        if b:
            print("║  🔴 DROP — on the blocked list. A rung 3-4 'work directly for you' ask is dead")
            print("║     here; the PERSON moves sideways to rungs 5-7 as a connector, never off the")
            print("║     ladder. Rung 7 needs three named LIVE targets so this company never appears.")
        else:
            print("║  ⚪ UNVERIFIED for a boss ask. Not blocked, and that is ALL this line says.")
            print(f'║     Before any rungs 3-4 ask: python3 scripts/check_ats.py "{company}"')
            print("║     confirm from the JD text: remote + travel, comp band, seniority, reporting")
            print("║     line, lane. A 🟡 no-live-role verdict FORCES the radar register and forbids")
            print("║     live-role framing. Then the six gates and the deep culture screen.")
        print("║  ⛔ THIS CARD DOES NOT CLEAR THE BUILD GATE for a boss ask. A rung 3-4 approach")
        print("║     still needs its own scorecard and an explicit build ruling.")

    print("╚══ ⚖️  INFORMATION, NOT AUTHORIZATION. The ruling stays yours.\n")
    return 0


def record_shown(name):
    p = _shown_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "contact-card-shown", "name": name,
                             "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                            ensure_ascii=False) + "\n")
    return 0


def _rows_for(name):
    """Every row about this contact, oldest first. Malformed lines are skipped, never rewritten."""
    p = _shown_path()
    if not os.path.exists(p):
        return []
    cl = _closeness()
    want = cl.normalize_name(name)
    out = []
    for line in open(p, encoding="utf-8"):
        try:
            row = json.loads(line)
            if cl.normalize_name(row.get("name", "")) == want:
                out.append(row)
        except Exception:
            continue
    return out


def _same_day(ts, now=None):
    """True when ISO timestamp `ts` falls on the same calendar day as `now`, in the MACHINE's local
    timezone.

    Local, not UTC: a UTC day would roll over mid-afternoon for a user west of Greenwich and
    re-introduce the exact mid-build false-block this fix removes. `now` is injectable so a test can
    pin the clock without a real midnight to wait for. Fails CLOSED (False) on any parse error: an
    unreadable stamp is not a card shown today.
    """
    try:
        when = datetime.datetime.fromisoformat(ts)
    except Exception:
        return False
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        return when.astimezone().date() == now.astimezone().date()
    except Exception:
        return False


def was_shown(name, now=None):
    """True when a card was shown for this contact on the CURRENT calendar day.

    The card is INFORMATION, not authorization — it records that the human was shown who this person
    is, carries no MAC, and clears no BUILD ruling. It was first modeled on record_scorecard's
    AUTHORIZATION semantics (a 120-min TTL plus one-picker consumption), which is a category error:
    co-construction runs the WHOLE message beat by beat (many pickers over a long build), so a note
    with research routinely outlived the 2h TTL and the next beat's picker false-blocked.

    THE FIX, both halves (see the TTL note above):
      1. THE CONSUMPTION CLAUSE IS GONE. Information is not "spent" per picker — being shown who a
         person is once covers every beat of that same note. It was also dead: nothing in production
         ever wrote a `contact-card-consumed` row.
      2. VALIDITY IS THE CURRENT CALENDAR DAY. One showing spans a whole note-build, while a card
         shown on a PRIOR day still blocks — the real point of the old stale check.

    ⛔ A NEGATIVE AGE IS NEVER FRESH. A row stamped in the future (clock skew, a hand-edited file)
    could otherwise land on today's date and satisfy the gate; guarded against the same clock the
    day check uses. `now` is injectable for tests.
    """
    rows = _rows_for(name)
    shown = [r for r in rows if r.get("kind") == "contact-card-shown"]
    if not shown:
        return False
    latest = shown[-1]
    try:
        when = datetime.datetime.fromisoformat(latest.get("ts"))
    except Exception:
        return False
    ref = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        if (ref - when).total_seconds() < 0:
            return False
    except Exception:
        return False
    return _same_day(latest.get("ts"), now)


def main():
    ap = argparse.ArgumentParser(description="the contact scorecard shown before co-creation")
    ap.add_argument("name", nargs="?")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--shown", metavar="NAME")
    ap.add_argument("--n", type=int, default=40)
    a = ap.parse_args()
    if a.shown:
        ok = was_shown(a.shown)
        print(f"{a.shown}: card {'SHOWN' if ok else 'NOT shown'}")
        return 0 if ok else 2
    if not a.name:
        ap.print_help()
        return 3
    rc = card(a.name, a.n)
    if rc == 0 and a.record:
        record_shown(a.name)
    return rc


if __name__ == "__main__":
    sys.exit(main())
