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
    """The closed segment vocabulary, read from documents/segments.md.

    Parses the slug column of the segments table. Falls back to the hardcoded tuple when the file
    is missing, so a fresh install records findings rather than refusing them.
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
    return tuple(sorted(found)) if found else _FALLBACK_LANES


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
