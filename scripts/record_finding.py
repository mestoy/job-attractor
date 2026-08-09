#!/usr/bin/env python3
"""record_finding.py — a discovery agent's verdict becomes durable the MOMENT it is decided.

WHY THIS EXISTS. A research agent that reports only at the end is one interruption away from
losing everything it found. A terminal restart, a transient API error, a context limit: any of
them turns thirty minutes of screening into nothing, and the only recovery is to re-run the whole
sweep and re-spend the tokens. Findings must not live in a single message that either arrives or
does not.

THE SECOND FAILURE, SAME SHAPE. Even when the report DOES arrive, its verdicts have to be
transcribed into the blocked list before anything downstream can see them. Skip that and the
ranker keeps offering companies an agent already killed, which reads to the user as the pipeline
being broken. Screening output that is not written back into the pool is not screening.

WHAT THIS IS. The agent-facing counterpart to `screen_sweep.py --bank`, which states the same
principle for MECHANICAL gates. This covers the JUDGMENT gates screen_sweep deliberately leaves to
a human or an agent: remote verification, ownership, customer base, values screen, comp reality.

WHAT THIS IS NOT. It is not authorization and carries no HMAC. Recording that a company was
screened grants nothing; `reconcile_findings.py` promotes DROPs to the blocked list and SURVIVORs
to the banked pool, and a banked row is still not build approval.

CRASH-SAFETY COMES FROM THE WRITE SHAPE, NOT A COMMIT STEP. One append per call, one JSON line,
flushed and fsync'd before the process returns. There is no buffer to lose and no "save at the
end." An interruption costs the call in flight and nothing else.

Usage:
  scripts/record_finding.py --run <run-id> --lane <segment-slug> --company "<name>" \
      --verdict SURVIVOR|DROP|UNVERIFIED|DEFERRED [--filter N] [--evidence "quote + URL"] \
      [--remote "quote + URL"] [--ownership "..."] [--pm-req "..."] [--comp "..."] [--note "..."]

  scripts/record_finding.py --run <run-id> --summary     # what has this run captured so far?

Exit: 0 = recorded · 2 = validation failure (nothing written) · 3 = usage
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
# CLAUDE_PROJECT_DIR first, __file__ second, so the test harness can point this at a sandbox root
# and a relocated checkout still resolves.
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
FINDINGS_DIR = os.path.join(REPO, "documents", "findings")

VERDICTS = ("SURVIVOR", "DROP", "UNVERIFIED", "DEFERRED")

# Fallback only. The live list is parsed from documents/segments.md so this file can never drift
# from the closed vocabulary mail-draft.sh enforces — that file says so itself: "This file is the
# single source of truth for segment names."
_FALLBACK_LANES = ("payments", "applied-ai", "ai-enablement", "regulated-workflow", "govtech",
                   "off-segment")


def lanes():
    """The closed segment vocabulary: documents/segments.md UNIONED with kit_config.SEGMENT_SLUGS.

    Parses the slug column of the segments table. Falls back to the hardcoded tuple when neither
    source has anything, so a fresh install records findings rather than refusing them.

    ⛔ BUG-103 (reported by a partner install, FIXED 2026-08-09). This read segments.md ALONE, so on
    any install where that file is still the shipped template, `--lane` rejected the user's REAL
    segments. Those lanes are defined in `kit_config.SEGMENT_SLUGS`, which `mail-draft.sh`,
    `screen_sweep.py` and `sweep_segments.sh` all already honor, so this was the only script in the
    pipeline that did not know what your segments were. ⚠️ It failed in the direction that looks
    like user error: the message named the lanes it WOULD take, and every one of them belonged to
    somebody else.

    ⚖️ UNION, NOT REPLACE. segments.md stays authoritative where it is filled in, and the config is
    added rather than substituted, so an install that has both keeps working with either name.
    """
    path = os.path.join(REPO, "documents", "segments.md")
    found = set()
    try:
        for line in open(path, encoding="utf-8", errors="ignore"):
            if not line.lstrip().startswith("|"):
                continue
            m = re.match(r"\s*\|\s*`([a-z][a-z-]{2,30})`\s*\|", line)
            if m:
                found.add(m.group(1))
    except Exception:
        pass
    # ⛔ THE FALLBACK IS THE BASE WHEN segments.md IS UNFILLED, and getting this wrong broke the
    # kit's own suite for an hour on 2026-08-09. The first version of this union simply added the
    # config slugs to `found`. On a FRESH install `segments.md` is still the shipped template, so
    # `found` was empty until the config slugs arrived — and the config ships POPULATED WITH
    # PLACEHOLDERS. That made `found` non-empty, the fallback never applied, and a brand-new kit
    # rejected its own documented `payments` lane. 4 tests went red that had been green.
    # ⚠️ Placeholder slugs are filtered for the same reason: a template value is not a declaration.
    _PLACEHOLDERS = {"segment-a", "segment-b", "segment-c"}
    # Per-name guard, never a tuple import: a tuple import of one absent name raises for the WHOLE
    # tuple, which is how BUG-100 blanked every résumé guardrail at once.
    declared = set()
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        if _here not in sys.path:
            sys.path.insert(0, _here)
        from kit_config import SEGMENT_SLUGS
        declared = {s.strip() for s in SEGMENT_SLUGS
                    if isinstance(s, str) and s.strip() and s.strip() not in _PLACEHOLDERS}
    except Exception:
        pass
    if not found:
        found = set(_FALLBACK_LANES)
    found |= declared
    found.add("off-segment")   # always available; it is the "not one of mine" verdict
    return tuple(sorted(found))


def _safe_run_id(raw):
    """Filesystem-safe run id. A run id becomes a FILENAME, so it cannot carry path separators.

    Rejecting rather than sanitizing would be stricter, but this runs inside an agent loop where a
    refused call means a LOST finding. Coerce, and report what it became.
    """
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (raw or "").strip()).strip("-.")
    return s[:80] or "unnamed-run"


def record(args):
    verdict = (args.verdict or "").upper()
    lane = (args.lane or "").strip().lower()
    company = (args.company or "").strip()
    valid = lanes()
    errs = []

    if verdict not in VERDICTS:
        errs.append(f"--verdict must be one of {'|'.join(VERDICTS)} (got {args.verdict!r})")
    if lane not in valid:
        errs.append(f"--lane must be one of {'|'.join(valid)} (got {args.lane!r}). "
                    f"The vocabulary is closed; see documents/segments.md")
    if not company:
        errs.append("--company is required and cannot be blank")

    # A DROP permanently excludes a company, so it is the verdict that must carry its receipts.
    # The blocked list is append-only in practice, so a wrong DROP is expensive and quiet, and an
    # unevidenced kill is a name nobody can re-audit later. It cannot be recorded.
    if verdict == "DROP":
        if args.filter is None:
            errs.append("a DROP requires --filter N (which hard filter it hit)")
        if not (args.evidence or "").strip():
            errs.append("a DROP requires --evidence (the quote or fact, with a URL where there is one)")

    # A CLAIMED CULTURE PEEK MUST CITE BOTH PLATFORMS. The rule is to check Indeed at the same
    # time as Glassdoor, in parallel; see HARD-INVARIANTS §60-SECOND CULTURE PEEK.
    #
    # WHY THIS IS ENFORCED AT WRITE TIME rather than left as prose. A company was once recorded
    # with "CULTURE PEEK PASSED" citing Glassdoor alone, and the row asserted "newest review over 2
    # months old, review velocity low" — true of Glassdoor only. Indeed's newest was FOUR DAYS old,
    # from a remote engineer rather than a frontline worker, and it also carried the sole signal
    # for the frontline pay picture. The rule had been written down and nothing checked it, which is
    # the inversion the RULE-EDIT GUARD names. A one-eyed peek wearing a two-eyed badge is worse
    # than no peek, because it gets recorded as a verdict and read later as settled.
    #
    # ⛔ SCOPE IS DELIBERATELY NARROW: this fires only on a row CLAIMING the peek passed. Recording
    # a single-source observation is still fine — say what you saw. What cannot be recorded is the
    # CONCLUSION drawn from half the evidence.
    # ⚠️ IT LOOKS FOR A READING, NOT FOR THE PLATFORM'S NAME, and the difference is the whole check.
    # The first version tested `re.search("indeed", note)`. The row that provoked this rule PASSED
    # that test, because its note said "Indeed cross-source still owed" — a sentence declaring the
    # Indeed read MISSING satisfied a check for the Indeed read being PRESENT. "Indeed" is also an
    # ordinary English adverb. Testing for the name is a proxy; testing for a rating beside the name
    # measures the thing ([[a-check-must-measure-the-thing-not-a-proxy]]).
    blob = " ".join(str(v or "") for v in (args.note, args.evidence))
    if re.search(r"(culture\s+)?peek\s+(passed|clean|clear)", blob, re.I):
        # ⚠️ THE RATING SHAPE IS EXPLICIT, because a loose one is how this check lied TWICE.
        # v2 ended its alternation with `|\b`, which matches ANY digit within 60 chars — so
        # "Indeed cross-source ... over 2 months old" satisfied it on the strength of the "2".
        # A rating is a decimal ("3.6"), or an integer qualified as a scale ("4/5", "4 out of 5").
        # A bare integer is NOT a rating: review counts, dates and month spans are all bare
        # integers, and every one of them sits near these words.
        _RATING = r"(?:\d\.\d+|\d\s*(?:/\s*5|out of\s+5))"

        def _has_reading(platform):
            return re.search(platform + r".{0,60}?" + _RATING, blob, re.I | re.S) is not None
        seen = [name for name, key in (("Glassdoor", "glassdoor"), ("Indeed", "indeed"))
                if _has_reading(key)]
        if len(seen) < 2:
            missing = ", ".join(n for n in ("Glassdoor", "Indeed") if n not in seen)
            errs.append(
                f"this row claims a culture peek passed but carries a READING from "
                f"{', '.join(seen) if seen else 'neither platform'}. The peek is BOTH platforms in "
                f"parallel, so {missing} is missing. Naming the platform is not citing it: a note "
                f"saying 'Indeed still owed' is a record of its ABSENCE. Fetch it (Indeed is the "
                f"assistant's half; Glassdoor needs your logged-in session), or drop the "
                f"'peek passed' "
                f"wording and record what you actually saw.")

    if errs:
        print("🔴 not recorded:")
        for e in errs:
            print(f"   • {e}")
        return 2

    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": _safe_run_id(args.run),
        "lane": lane,
        "company": company,
        "verdict": verdict,
    }
    for key, val in (("filter", args.filter), ("evidence", args.evidence),
                     ("remote", args.remote), ("ownership", args.ownership),
                     ("pm_req", args.pm_req), ("comp", args.comp), ("note", args.note)):
        if val is not None and str(val).strip() != "":
            row[key] = val

    os.makedirs(FINDINGS_DIR, exist_ok=True)
    path = os.path.join(FINDINGS_DIR, f"{row['run']}.jsonl")
    # Append-only, one line, flushed. See the crash-safety note in the module docstring.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    badge = {"SURVIVOR": "🟢", "DROP": "⛔", "UNVERIFIED": "⚪", "DEFERRED": "⏸️"}[verdict]
    extra = f" (filter {row['filter']})" if "filter" in row else ""
    print(f"{badge} {verdict}{extra}  {company}  [{lane}] → "
          f"{os.path.relpath(path, REPO)}")
    return 0


def summary(run):
    path = os.path.join(FINDINGS_DIR, f"{_safe_run_id(run)}.jsonl")
    if not os.path.exists(path):
        print(f"(no findings recorded yet for run {run!r})")
        return 0
    counts, bad = {}, 0
    for line in open(path, encoding="utf-8", errors="ignore"):
        if not line.strip():
            continue
        try:
            v = json.loads(line).get("verdict", "?")
        except Exception:
            bad += 1
            continue
        counts[v] = counts.get(v, 0) + 1
    total = sum(counts.values())
    print(f"run {run}: {total} finding(s) → {os.path.relpath(path, REPO)}")
    for v in VERDICTS:
        if counts.get(v):
            print(f"   {v:<11} {counts[v]}")
    if bad:
        # Never silent. A malformed line is a real data loss and the operator has to know.
        print(f"   ⚠️  {bad} unparseable line(s) — inspect the file")
    return 0


def main():
    p = argparse.ArgumentParser(add_help=True, description=__doc__.split("\n")[0])
    p.add_argument("--run", required=True)
    p.add_argument("--lane")
    p.add_argument("--company")
    p.add_argument("--verdict")
    p.add_argument("--filter", type=int)
    p.add_argument("--evidence")
    p.add_argument("--remote")
    p.add_argument("--ownership")
    p.add_argument("--pm-req", dest="pm_req")
    p.add_argument("--comp")
    p.add_argument("--note")
    p.add_argument("--summary", action="store_true")
    try:
        args = p.parse_args()
    except SystemExit:
        return 3
    if args.summary:
        return summary(args.run)
    return record(args)


if __name__ == "__main__":
    sys.exit(main())
