#!/usr/bin/env python3
"""check_revisits.py — a company was not rejected, it was rejected UNTIL something changes.

WHY THIS EXISTS
---------------
Verdicts in your queues carry a revisit CONDITION rather than a flat status:

    "Trigger to revisit: a dated 🔬 probe showing the leadership thread is stale, **or a live
     remote product seat with a band above the floor**."
    "DROPPED THIS RUN (20) — reason each, do not re-surface without the stated trigger."

Nothing has ever evaluated one. In the pipeline this was ported from, ~55 such conditions were
written carefully, stored durably, and then read by no code and no human — which makes a conditional
block indistinguishable from a permanent one. **One company's trigger was met and nothing noticed.**
The whole point of writing a condition instead of a rejection is that somebody comes back when it
fires, and nobody did.

That is the storage defect one layer up: not "the data is stale" but "the data encodes a promise to
re-check, and the re-check was never wired to anything."

WHAT IS AND IS NOT MECHANICALLY CHECKABLE, AND WHY THAT LINE IS DRAWN HONESTLY
-----------------------------------------------------------------------------
Two kinds of trigger live in these files, and collapsing them would be the failure mode
`check_network_freshness.py` warns about (a check that cannot tell you what to do next):

  • LIVE-ROLE     "a confirmed remote-US product req", "a US-anchored req above the floor",
                  "a live remote product seat with a band above the floor"
                  → a script CAN answer this, by asking the company's own ATS. That is the class
                    the missed company fell into, and the class this script evaluates.

  • HUMAN-PROBE   "a dated probe showing the leadership thread is stale",
                  "revisit only if leadership improves"
                  → no API answers this. It is reported and counted, never guessed at, because a
                    script that pretended to evaluate it would be worse than one that declines.

NETWORK USE IS OPT-IN. The default run classifies and reports without touching the network, so it is
safe in a sweep and in tests. `--live` is what actually probes the ATS boards.

Usage:  scripts/check_revisits.py [--live] [--company NAME] [--json] [--quiet]
Exit:   0 = nothing newly met · 1 = at least one condition is NOW MET · 2 = unreadable source
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

SOURCES = [
    "documents/outreach-queue.md",
    "documents/prospect_queue.md",
    "documents/blocked-employers-list.md",
]

# Your own first name appears in triggers that name YOU as the one who must judge ("confirmed by
# <you>"). Imported in its OWN try/except: folding a new name into an existing multi-name import
# makes the whole import fail on an older kit_config and silently fall back to placeholders.
try:
    from kit_config import OWNER_FIRST
except Exception:
    OWNER_FIRST = "you"

# Your comp floor, for triggers that say "above the floor".
try:
    from kit_config import COMP_FLOOR
except Exception:
    COMP_FLOOR = 0

# The trigger sentence, however it is phrased. Anchored on the words that actually recur in a real
# corpus rather than on one canonical spelling, because six different phrasings are already in use.
_TRIGGER = re.compile(
    r"(?:trigger to revisit|revisit only if|revisit if|re-?surface (?:only )?(?:if|when)|"
    r"do not re-?surface without)\s*:?\s*(.{0,220})", re.I)

# A trigger an ATS can answer: it asks for a ROLE to exist, with remote and/or comp qualifiers.
_LIVE_ROLE = re.compile(
    r"\b(req|role|seat|opening|posting|position)\b", re.I)
_NEEDS_REMOTE = re.compile(r"\bremote\b|\bus-?anchored\b|\bus-?timezone\b|\bus-remote\b", re.I)
_NEEDS_BAND = re.compile(r"\bband\b|\bfloor\b|\babove the floor\b|\bcomp\b|\bsalary\b", re.I)
# A trigger only a human can settle. Deliberately broad on QUALITATIVE change words: an earlier cut
# listed only "probe" and "leadership improves", which left 29 conditions "unknown" — and an unknown
# condition does nothing at all, which is the state this whole script exists to end. "sentiment
# recovers", "ownership/pace change" and "summit cadence drops" are all real triggers that fell
# through that narrower list.
_HUMAN = re.compile(
    r"\bprobe\b|\bstale\b|\breview base\b|\bglassdoor\b|\bconfirm(?:ed)? by\b|"
    + re.escape(OWNER_FIRST.lower()) + r"|"
    r"\bimproves?\b|\bstabili[sz]es?\b|\brecovers?\b|\bsentiment\b|\bownership\b|\bculture\b|"
    r"\bcadence\b|\bturn positive\b|\bcloses\b|\bin seat\b|\bholds the seat\b|\bmonths\b", re.I)

# A drop list often heads its section with "do not re-surface without the stated trigger". That is a
# SECTION HEADER telling the reader each row carries its own trigger, not a condition on any company
# — and it was being extracted five times as a phantom condition with no company attached.
_NOT_A_TRIGGER = re.compile(r"^(the stated trigger|both turn positive\)?:?)$", re.I)

# "X, or Y" fires on either branch. "X AND Y" needs both, so a live role alone must NOT fire it.
# ⚠️ `+` IS A CONJUNCTION TOO, and missing it caused a live false fire. A trigger reading "a specific
# role + a real WLB signal warrant it" had the ATS prove the role half while nothing proved the WLB
# half, and the run reported it as MET. Re-surfacing a blocked company on half a condition is the
# precise harm these triggers exist to prevent.
#
# ⚠️ THE `+` MUST BE SPACE-DELIMITED. A bare `\+` also matches the one in "sentiment recovers
# 12+ months", turning a numeric qualifier into a conjunction and splitting a single human-probe
# condition into two clauses. Caught by the test that asserts qualitative triggers stay human-probe,
# which is the whole reason to write the assertion in terms of the OUTCOME rather than the regex.
#
# ⬆️ ONE PATTERN, TWO USES. This was written out twice, once compiled for the "is there a
# conjunction" test and once inline in `classify()`'s `re.split`. A break-test proved that made the
# guard unfalsifiable: reverting either copy alone still passed, because the other copy carried the
# behaviour. Two spellings of one rule is a forked-matcher defect, and here it also meant a
# break-test that reported a guard it was not testing.
_CONJ_AND_SRC = r"\band\b|\s\+\s|\balong with\b|\bas well as\b|\bplus\b"
_CONJ_AND = re.compile(_CONJ_AND_SRC, re.I)
_CONJ_OR = re.compile(r"\bor\b", re.I)

# Trigger qualifiers an ATS listing cannot settle by itself. When one is present, a positive result
# is reported as MET-VERIFY rather than MET: the role exists, but the specific restriction the
# trigger names has not been proven absent. "without the CA-residency restriction" is the live
# example — "Remote" in a location field is not proof of that.
_UNVERIFIABLE_QUALIFIER = re.compile(
    r"residency|restriction|without the\b|visa|clearance|citizen|state-specific", re.I)

_COMPANY_IN_BULLET = re.compile(r"^\s*[-*]\s+\**\[?([^*\[\]()—:]{2,60}?)\**\s*[\(\)—:]")


def _comp_top(comp):
    """Top of a scraped band in dollars, or None if unparseable.

    ⚠️ KIT DEVIATION, and the reason it is not an import. The upstream script calls
    `check_ats.comp_top`, which this kit's lighter `check_ats` does not define — it ships
    `comp_from_text`, which returns the band as a STRING. That lighter variant is a standing design
    decision, so the parse lives here rather than growing the kit's check_ats.

    FAILS CLOSED on purpose. Returning None makes `band_ok` False for any trigger that asks for a
    band, so an unparseable band means the condition does NOT fire. Under-firing costs a re-read;
    over-firing re-surfaces a company on a test it never passed.
    """
    if not comp:
        return None
    nums = []
    for m in re.finditer(r"(\d[\d,]*\.?\d*)\s*([kK])?", comp):
        raw, k = m.group(1).replace(",", ""), m.group(2)
        try:
            v = float(raw)
        except ValueError:
            continue
        if k:
            v *= 1000
        if v >= 1000:
            nums.append(v)
    return max(nums) if nums else None


def _read(rel):
    p = os.path.join(REPO, rel)
    try:
        return open(p, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return None


def classify(trigger):
    """live-role · human-probe · mixed · unknown. Never guesses, and `mixed` is a real answer.

    `mixed` matters: a trigger reading *"a dated probe showing the leadership thread is stale, OR a
    live remote product seat with a band above the floor"* is fired by EITHER branch. Treating that
    as human-probe would keep it invisible, which is precisely what happened to the one that was
    missed.
    """
    live = bool(_LIVE_ROLE.search(trigger))
    human = bool(_HUMAN.search(trigger))

    # ⚠️ CLAUSE-LEVEL CHECK, and it has to come first. Keying only on "does any human-ish word
    # appear" is not enough: a trigger reading "a specific role + a real WLB signal warrant it" has
    # no word from the human list in its second clause, so the whole thing read as pure live-role
    # and FIRED on the role alone in a live run. The general rule is stronger than any keyword list
    # — in a conjunction, EVERY clause must be ATS-answerable before a board result can settle the
    # whole condition.
    if _CONJ_AND.search(trigger) and not _CONJ_OR.search(trigger):
        clauses = [c for c in re.split(_CONJ_AND_SRC, trigger, flags=re.I) if c.strip()]
        if len(clauses) > 1 and not all(_LIVE_ROLE.search(c) for c in clauses):
            return "mixed-and"

    if live and human:
        # ⚠️ THE CONJUNCTION DECIDES WHETHER A LIVE ROLE IS ENOUGH ON ITS OWN.
        #   OR-form : "a dated probe showing the leadership thread is stale, OR a live remote
        #             product seat with a band above the floor"  → either branch fires it.
        #   AND-form: "a US-based product req appears AND a CEO holds the seat 12+ months"
        #             → a req alone proves half the condition. Firing on it would re-surface a
        #               company on a test it has not passed, which is worse than staying silent.
        if _CONJ_OR.search(trigger):
            return "mixed"
        if _CONJ_AND.search(trigger):
            return "mixed-and"
        return "mixed"
    if live:
        return "live-role"
    if human:
        return "human-probe"
    return "unknown"


def extract(company_filter=None):
    out = []
    for rel in SOURCES:
        lines = _read(rel)
        if lines is None:
            continue
        for i, raw in enumerate(lines, 1):
            m = _TRIGGER.search(raw)
            if not m:
                continue
            trigger = re.sub(r"\s+", " ", m.group(1)).strip(" .*_`")
            if not trigger or _NOT_A_TRIGGER.match(trigger):
                continue
            cm = _COMPANY_IN_BULLET.match(raw)
            company = re.sub(r"[*`~]", "", cm.group(1)).strip() if cm else ""
            if company_filter and company_filter.lower() not in company.lower():
                continue
            kind = classify(trigger)
            out.append({"company": company, "trigger": trigger, "kind": kind,
                        "source_file": rel, "source_line": i,
                        "needs_remote": bool(_NEEDS_REMOTE.search(trigger)),
                        "needs_band": bool(_NEEDS_BAND.search(trigger))})
    return out


def evaluate_live(cond):
    """Ask the company's OWN ATS whether the role the trigger asks for exists now.

    Reuses `check_ats`'s probes rather than re-implementing them: token derivation and the PM-title
    matcher are both hard-won, and a forked copy of either drifts from the original the first time
    one side is fixed.
    """
    try:
        import check_ats
    except Exception as e:
        return {"verdict": "ERROR", "detail": f"check_ats unavailable: {e}"}
    if not cond["company"]:
        return {"verdict": "NO-COMPANY", "detail": "trigger has no company attached"}

    # Every probe returns (provider, token, total_jobs, roles) or None. Unpacking it as a list or a
    # dict raises, which is what the first cut did — the shape is a contract worth reading rather
    # than assuming.
    roles, boards = [], []
    for tok in check_ats.tokens_from(cond["company"])[:4]:
        for probe in (check_ats.probe_greenhouse, check_ats.probe_ashby, check_ats.probe_lever):
            try:
                r = probe(tok)
            except Exception:
                r = None
            if not r:
                continue
            provider, tk, total, found = r
            boards.append(f"{provider}:{tk} ({total} reqs)")
            roles.extend(found)
    if not boards:
        return {"verdict": "NO-BOARD", "detail": "no public ATS board found for this name"}
    if not roles:
        return {"verdict": "NO-PM-REQ", "detail": f"board(s) found ({'; '.join(boards[:2])}) "
                                                  f"but no product reqs open"}

    hits = []
    for r in roles:
        loc = str(r.get("loc", ""))
        comp = str(r.get("comp", ""))
        remote_ok = (not cond["needs_remote"]) or bool(
            re.search(r"remote", loc, re.I) and not re.search(r"canada only|emea|uk only", loc, re.I))
        top = _comp_top(comp) if comp else None
        band_ok = (not cond["needs_band"]) or (top is not None and top >= COMP_FLOOR)
        if remote_ok and band_ok:
            hits.append({"title": r.get("title", ""), "loc": loc, "comp": comp})
    if hits:
        verdict = "MET-VERIFY" if _UNVERIFIABLE_QUALIFIER.search(cond["trigger"]) else "MET"
        return {"verdict": verdict, "roles": hits[:4], "boards": boards[:2],
                "caveat": ("the trigger names a restriction an ATS listing cannot prove absent; "
                           "confirm on the JD before acting")
                          if verdict == "MET-VERIFY" else ""}
    return {"verdict": "NOT-MET",
            "detail": f"{len(roles)} PM req(s) found, none satisfying the trigger"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    live = "--live" in argv
    as_json = "--json" in argv
    quiet = "--quiet" in argv
    company = None
    if "--company" in argv:
        i = argv.index("--company")
        company = argv[i + 1] if i + 1 < len(argv) else None

    conds = extract(company)
    if not conds:
        print("⚪ no revisit conditions found")
        return 0

    by_kind = {}
    for c in conds:
        by_kind.setdefault(c["kind"], []).append(c)

    met = []
    if live:
        for c in conds:
            if c["kind"] in ("live-role", "mixed"):
                c["result"] = evaluate_live(c)
                if c["result"]["verdict"] in ("MET", "MET-VERIFY"):
                    met.append(c)

    if as_json:
        print(json.dumps({"conditions": conds, "met": met}, ensure_ascii=False, indent=2))
        return 1 if met else 0

    checkable = len(by_kind.get("live-role", [])) + len(by_kind.get("mixed", []))
    blocked_by_and = len(by_kind.get("mixed-and", []))
    if not quiet:
        print(f"── revisit conditions: {len(conds)} found ──")
        print(f"   {checkable} mechanically checkable (live-role or mixed) · "
              f"{len(by_kind.get('human-probe', []))} need a human probe · "
              f"{blocked_by_and} need BOTH a role and a human check · "
              f"{len(by_kind.get('unknown', []))} unclassified")
    if not live:
        print("   (classification only — pass --live to probe the ATS boards)")
        for c in conds[:8]:
            if c["kind"] in ("live-role", "mixed"):
                print(f"   🔎 {c['company'][:26]:<26} {c['kind']:<10} {c['trigger'][:70]}")
        return 0

    if met:
        print(f"\n🟢 {len(met)} CONDITION(S) NOW MET — these were held pending exactly this:")
        for c in met:
            mark = "✅" if c["result"]["verdict"] == "MET" else "🟡"
            print(f"   {mark} {c['company']}"
                  + ("  (VERIFY)" if c["result"]["verdict"] == "MET-VERIFY" else ""))
            if c["result"].get("caveat"):
                print(f"      ⚠️  {c['result']['caveat']}")
            print(f"      trigger: \"{c['trigger'][:150]}\"")
            print(f"      recorded at {c['source_file']}:{c['source_line']}")
            for r in c["result"]["roles"]:
                print(f"      → {r['title']} · {r['loc']} · {r['comp'] or 'comp unpublished'}")
        return 1
    if not quiet:
        print("\n⚪ no revisit condition is newly met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
