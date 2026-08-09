#!/usr/bin/env python3
"""reconcile_findings.py — move captured agent verdicts into the files the pipeline actually reads.

WHY THIS EXISTS. `record_finding.py` makes a verdict durable. This makes it VISIBLE. Those are
different problems: a findings file nothing consumes is a terminal buffer with extra steps. When
the write-back is skipped, the ranker keeps offering companies an agent already disqualified.
Screening output that is not written back into the pool is not screening.

WHERE THINGS LAND, AND WHY THE DESTINATIONS DIFFER:

  • DROP     → documents/blocked-employers-list.md, automatically. Recording a disqualification is
               bookkeeping, not a judgment call, and every DROP arrives carrying a filter number
               and evidence because record_finding.py refuses one without them.

  • SURVIVOR → documents/banked-candidates-<date>.md, which rank_criteria.banked_topup() reads as a
               tier-1 pool tagged "CULTURE SCREEN STILL OWED". Deliberately NOT the active board.
               Banked means "worth screening", never "worth sending", and promotion to the active
               board stays a human decision. That is what keeps "a banked row is not build
               approval" true after automation.

  • UNVERIFIED / DEFERRED → neither. They are facts about an unfinished screen, and writing them
               anywhere authoritative would launder "we could not tell" into a verdict.

IDEMPOTENT TWO WAYS, because a reconciler that double-writes is worse than one that under-writes:
  1. CONTENT — a company already on the blocked list (by canon() key, so ", Inc." cannot dodge it)
     or already in the banked pool is skipped.
  2. SIDECAR — documents/findings/<run>.reconciled records the line count consumed. Re-running a
     fully-reconciled run is a no-op, and consistency-check.sh reads this sidecar to tell whether a
     run still owes a write-back.

Reuses `screen_sweep.canon()` and `screen_sweep.blocked_keys_from_list()` by IMPORT. Both carry
cases learned the hard way (the ", Inc." escape, the blocked list's two bullet shapes) and a forked
copy would drift.

Usage:
  scripts/reconcile_findings.py [--run <run-id>] [--dry-run]

Exit: 0 = reconciled (or nothing to do) · 1 = something was written and needs review · 2 = error
"""
import glob
import json
import os
import re
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
FINDINGS_DIR = os.path.join(REPO, "documents", "findings")
BLOCKED = os.path.join(REPO, "documents", "blocked-employers-list.md")

sys.path.insert(0, HERE)
try:
    from screen_sweep import canon, blocked_keys_from_list
except Exception:  # pragma: no cover - a broken import must not strand captured findings
    def canon(name):
        return re.sub(r"[^a-z0-9]+", "", (name or "").lower())

    def blocked_keys_from_list(path=None):
        return set()

# The hard filters, numbered as your discovery brief numbers them. Used only to give the
# blocked-list section a human heading; an unknown number still records, under "other".
FILTERS = {
    1: "Remote fail (hybrid, RTO, metro-locked, foreign-only, or excess travel)",
    2: "Defense or military mission",
    3: "Law-enforcement or policing customers",
    4: "Social media, gambling or crypto as the primary business",
    5: "Predatory lending",
    6: "DTC prescription telehealth marketing",
    7: "Not LGBTQIA+ friendly",
    8: "PE-owned",
    9: "Right-leaning company or leadership",
    10: "Foreign-anchored product org",
    11: "Comp cannot clear the $170K floor",
}


def _rows(path):
    out, bad = [], 0
    for line in open(path, encoding="utf-8", errors="ignore"):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            bad += 1
    return out, bad


def _sidecar(run):
    return os.path.join(FINDINGS_DIR, f"{run}.reconciled")


def _consumed(run):
    """Rows already reconciled for this run, per its sidecar. 0 when absent or unreadable."""
    try:
        return int(json.load(open(_sidecar(run), encoding="utf-8")).get("lines", 0))
    except Exception:
        return 0


def unreconciled():
    """[(run, total_rows, consumed_rows)] for every run whose sidecar is behind its findings file.

    consistency-check.sh step [17] calls this. Keep it cheap and non-destructive.
    """
    out = []
    for path in sorted(glob.glob(os.path.join(FINDINGS_DIR, "*.jsonl"))):
        run = os.path.basename(path)[:-len(".jsonl")]
        total = sum(1 for line in open(path, encoding="utf-8", errors="ignore") if line.strip())
        done = _consumed(run)
        if done < total:
            out.append((run, total, done))
    return out


def _banked_path():
    return os.path.join(REPO, "documents", f"banked-candidates-{date.today().isoformat()}.md")


def _already_banked_keys():
    """canon() keys already present in ANY banked file, so a survivor is banked once, not daily."""
    keys = set()
    for path in glob.glob(os.path.join(REPO, "documents", "banked-candidates-*.md")):
        for line in open(path, encoding="utf-8", errors="ignore"):
            if not line.strip() or line.lstrip().startswith(("#", ">", "|", "-")):
                continue
            for chunk in line.split("·"):
                co = chunk.strip().strip("*~ ").strip()
                if co:
                    keys.add(canon(co))
    return keys


def _write_blocked(drops, dry):
    """Append DROP rows to the blocked list, grouped by filter, newest section last."""
    if not drops:
        return 0
    by_filter = {}
    for r in drops:
        by_filter.setdefault(r.get("filter") or 0, []).append(r)
    today = date.today().isoformat()
    # ⚠️ KEEP THIS HEADER MINIMAL. Prose written into the blocked list becomes MATCH SURFACE for
    # check_dup.py, which greps this file for company names. A verbose rationale block here made a
    # freshly-invented test name return a soft hit on a common word inside an explanatory sentence.
    # Documentation that describes a gap can end up satisfying the check for that gap. Reasoning
    # belongs in this script, where people read it; the data file gets provenance and nothing else.
    lines = ["", "---", "",
             f"# 🤖 Agent findings reconciled {today}", "",
             "> Written by `scripts/reconcile_findings.py` from `documents/findings/*.jsonl`.", ""]
    for num in sorted(by_filter):
        label = FILTERS.get(num, "other, filter number not recognized")
        lines.append(f"**⛔ Filter {num}: {label}**")
        for r in sorted(by_filter[num], key=lambda x: x["company"].lower()):
            ev = (r.get("evidence") or "").strip()
            lane = r.get("lane", "")
            lines.append(f"- **{r['company']}** ({lane}, {r.get('ts', today)[:10]}). {ev}")
        lines.append("")
    if not dry:
        with open(BLOCKED, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return len(drops)


def _write_banked(survivors, dry):
    """Append SURVIVOR names in the dot-separated shape rank_criteria.banked_topup() parses.

    ⚠️ Format contract. banked_topup() skips any line starting with #, >, | or -, and splits the
    rest on '·'. screen_sweep.bank() carries the same warning: "do not 'improve' it into a table
    without changing that reader." A table here would write a file that looks correct to a human
    and bank nothing at all.
    """
    if not survivors:
        return 0
    path = _banked_path()
    names = [r["company"] for r in survivors]
    fresh = not os.path.exists(path)
    lines = []
    if fresh:
        lines += [f"# Banked candidates — {date.today().isoformat()}", "",
                  "> Written by `reconcile_findings.py` from agent findings.",
                  "> Passed an AGENT screen (remote, ownership, industry, comp). "
                  "**STILL OWED on every name: the deep culture screen and a boss.**",
                  "> A name here means *worth screening*, never *worth sending*.", "",
                  "## Passes", ""]
    else:
        lines += ["", f"## Passes (reconciled from agent findings, {date.today().isoformat()})", ""]
    for i in range(0, len(names), 6):
        lines.append(" · ".join(names[i:i + 6]) + " ·")
    if not dry:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return len(names)


def reconcile(only_run=None, dry=False):
    if not os.path.isdir(FINDINGS_DIR):
        print("🟢 no findings directory yet — nothing to reconcile")
        return 0
    pending = [t for t in unreconciled() if only_run in (None, t[0])]
    if not pending:
        print("🟢 every findings run is reconciled")
        return 0

    # ⛔ OWN COPY, so the `blocked_keys.add(k)` below mutates nothing shared. Safe today only
    # because the kit's screen_sweep has no cache; the maintainer's does, and there the identical
    # `.add` poisoned the cached set for every later reader (2026-08-08). Fixing it here too means
    # the cache can be synced into the kit later without carrying the defect across with it.
    blocked_keys = set(blocked_keys_from_list())
    banked_keys = _already_banked_keys()
    all_drops, all_survivors, skipped, other = [], [], [], 0
    seen = set()

    for run, total, done in pending:
        rows, bad = _rows(os.path.join(FINDINGS_DIR, f"{run}.jsonl"))
        if bad:
            print(f"   ⚠️  {run}: {bad} unparseable line(s), skipped")
        for r in rows:
            co = (r.get("company") or "").strip()
            k = canon(co)
            if not co or not k or k in seen:
                continue
            seen.add(k)
            v = r.get("verdict")
            if v == "DROP":
                if k in blocked_keys:
                    skipped.append(f"{co} (already blocked)")
                    continue
                all_drops.append(r)
                blocked_keys.add(k)
            elif v == "SURVIVOR":
                if k in blocked_keys:
                    # A survivor that is already blocked is a real contradiction, never silent.
                    skipped.append(f"{co} (SURVIVOR but already on the blocked list — check this)")
                    continue
                if k in banked_keys:
                    skipped.append(f"{co} (already banked)")
                    continue
                all_survivors.append(r)
                banked_keys.add(k)
            else:
                other += 1

    n_drop = _write_blocked(all_drops, dry)
    n_surv = _write_banked(all_survivors, dry)

    tag = "(dry-run) would write" if dry else "wrote"
    print(f"{'🔎' if dry else '✅'} {tag}: {n_drop} DROP(s) → documents/blocked-employers-list.md · "
          f"{n_surv} SURVIVOR(s) → {os.path.relpath(_banked_path(), REPO)}")
    if other:
        print(f"   ⏸️  {other} UNVERIFIED/DEFERRED row(s) left in place — an unfinished screen is "
              f"not a verdict")
    if skipped:
        print(f"   ⏭️  {len(skipped)} skipped as already recorded:")
        for s in skipped[:8]:
            print(f"      • {s}")
        if len(skipped) > 8:
            print(f"      (+{len(skipped) - 8} more)")

    if not dry:
        for run, total, _done in pending:
            os.makedirs(FINDINGS_DIR, exist_ok=True)
            json.dump({"lines": total,
                       "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                      open(_sidecar(run), "w", encoding="utf-8"))
        print(f"   📌 sidecar written for {len(pending)} run(s); "
              f"consistency-check step [17] will now pass")
        if n_surv:
            print("   ↻ re-run scripts/rank_criteria.py to see the new names in the pool")
    return 1 if (n_drop or n_surv) else 0


def main():
    dry = "--dry-run" in sys.argv
    run = None
    if "--run" in sys.argv:
        i = sys.argv.index("--run")
        if i + 1 >= len(sys.argv):
            print("usage: reconcile_findings.py [--run <run-id>] [--dry-run]")
            return 2
        run = sys.argv[i + 1]
    try:
        return reconcile(run, dry)
    except Exception as e:  # pragma: no cover
        print(f"🔴 reconcile failed ({type(e).__name__}: {e})")
        return 2


if __name__ == "__main__":
    sys.exit(main())
