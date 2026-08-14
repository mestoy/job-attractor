#!/usr/bin/env python3
"""check_job_liveness.py — a scheduled job that is LOADED is not a job that RAN.

WHY THIS EXISTS. `durability-check.sh` section 1 answers "is the job installed and mirrored",
which is a question about CONFIGURATION. Nothing answered "did it actually run", which is the
question about REALITY, and the two come apart silently: launchd reports a job as loaded whether it
fired last night or died months ago. A watcher that dies quietly leaves every check around it green.

⛔ THE FINDING THIS STEP EXISTS TO SURFACE is not "a job is late". It is that most jobs leave NO
WITNESS AT ALL. A job with no log and no stamp cannot be late, cannot be early, and cannot be
checked — it can only be assumed. Assumed-running is exactly the state a job was in upstream when it
turned out to be destroying data on every run.

HOW THE WITNESS IS FOUND, in order, and never invented:
  1. a stamp at documents/state/<label-tail>.json carrying `last_run`  (the strongest: the job
     wrote it ITSELF, at the end of its own run, so it proves completion and not merely launch)
  2. the `LOG="…"` path the job's own script declares, by mtime
  3. the plist's own StandardOutPath, by mtime
  4. nothing — reported as nothing

⚠️ THOSE THREE ARE NOT EQUAL AND THE OUTPUT SAYS WHICH ONE IT USED. A stamp proves the job reached
its own last line. A log or a StandardOutPath proves only that something was WRITTEN, so a job that
started, printed a banner and died reads as alive. StandardOutPath is weaker again because it lives
in /tmp, which macOS clears on reboot: a missing one means "rebooted", not "never ran", and it must
never be reported as silence. Ranking them is the point — an unlabelled "last seen" would flatten
three different strengths of evidence into one number nobody could act on.

⚖️ THE CADENCE IS READ FROM THE PLIST, never typed here. A weekday-only job is allowed a longer
silence than a daily one because a Saturday is not a failure, and typing that per job is how the
list in durability-check.sh went stale twice (BUG-148).

⚪ ADVISORY, deliberately, matching steps [18], [27] and [29]. A laptop closed overnight skips a
run and that is not drift. What this must never do is stay quiet, which is the thing it is for.

Exit: 0 always in the default mode (advisory) · 1 with --strict when any job is silent past its
      allowance · 3 = usage
"""
import json
import os
import plistlib
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
LAUNCHD_DIR = os.path.join(REPO, "scripts", "launchd")

# ⛔ THE KIT MUST NOT ASSUME WHOSE SEARCH IT IS RUNNING. The label prefix is the operator's own;
# hardcoding one would make every check here silently match nothing on their machine, which reads
# as "no jobs scheduled" rather than as a misconfiguration.
LAUNCHD_PREFIX = os.environ.get("JOBKIT_LAUNCHD_PREFIX") or "com.example.jobsearch"

# How much silence is normal, derived from the plist's own schedule. A weekday job that last ran
# Friday is fine on Monday morning, so the allowance has to clear a weekend plus the run itself.
WEEKDAY_ALLOWANCE_DAYS = 4.0
DAILY_ALLOWANCE_DAYS = 2.0


def _labels():
    """Every job we know about, from the mirrored plists unioned with the loaded labels.

    Same three-source derivation as durability-check.sh, and for the same reason: a typed list
    describes the jobs somebody remembered, which is never the risky set (BUG-148).
    """
    found = set()
    if os.path.isdir(LAUNCHD_DIR):
        found |= {f[:-len(".plist")] for f in os.listdir(LAUNCHD_DIR)
                  if f.endswith(".plist") and f.startswith(LAUNCHD_PREFIX + ".")}
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=30)
        found |= set(re.findall(re.escape(LAUNCHD_PREFIX) + r"\.[A-Za-z0-9._-]+",
                                out.stdout or ""))
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted(found)


def _plist(label):
    p = os.path.join(LAUNCHD_DIR, f"{label}.plist")
    try:
        with open(p, "rb") as fh:
            return plistlib.load(fh)
    except Exception:
        return None


def allowance_days(pl):
    """Silence budget in days, from the plist's own StartCalendarInterval.

    ⛔ A plist we cannot read gets the LONGER budget, not the shorter one. Guessing "daily" for an
    unknown schedule would manufacture a warning out of missing information, and a check that
    invents findings is one people stop reading.
    """
    if not pl:
        return WEEKDAY_ALLOWANCE_DAYS
    sched = pl.get("StartCalendarInterval")
    entries = sched if isinstance(sched, list) else ([sched] if isinstance(sched, dict) else [])
    if any("Weekday" in e for e in entries if isinstance(e, dict)):
        return WEEKDAY_ALLOWANCE_DAYS
    return DAILY_ALLOWANCE_DAYS


def _script_for(pl):
    """The script a plist runs, as a repo-relative path when it points inside the repo."""
    args = (pl or {}).get("ProgramArguments") or []
    for a in args[1:]:
        if isinstance(a, str) and a.endswith((".sh", ".py")):
            return a
    return None


def _declared_log(script_path):
    """The log the job's own script declares via LOG="…". Read from the script, never assumed."""
    if not script_path:
        return None
    local = script_path
    if not os.path.exists(local):
        local = os.path.join(REPO, "scripts", os.path.basename(script_path))
    try:
        src = open(local, encoding="utf-8", errors="ignore").read()
    except Exception:
        return None
    m = re.search(r'^LOG="([^"]+)"', src, re.M)
    if not m:
        return None
    log = m.group(1).replace("$PROJECT/", "").replace("${PROJECT}/", "")
    return log if os.path.isabs(log) else os.path.join(REPO, log)


def _stamp_age_days(label, now):
    """Age of a self-written completion stamp, or None. The tail of the label names the file."""
    tail = label.rsplit(".", 1)[-1]
    for name in (tail, tail.replace("check", "-check"), "daily-rank" if tail == "dailyrank" else tail):
        p = os.path.join(REPO, "documents", "state", f"{name}.json")
        if not os.path.exists(p):
            continue
        try:
            raw = json.load(open(p, encoding="utf-8"))
            ts = raw.get("last_run")
            if not ts:
                continue
            when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return (now - when).total_seconds() / 86400.0, os.path.relpath(p, REPO)
        except Exception:
            continue
    return None


def scan(now=None):
    """Pure scan. Returns a list of per-job dicts; prints nothing."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for label in _labels():
        pl = _plist(label)
        script = _script_for(pl)
        allow = allowance_days(pl)

        age, witness, kind = None, None, "none"
        stamped = _stamp_age_days(label, now)
        if stamped:
            age, witness, kind = stamped[0], stamped[1], "stamp"
        else:
            log = _declared_log(script)
            std = (pl or {}).get("StandardOutPath")
            if log and os.path.exists(log):
                age = (now.timestamp() - os.path.getmtime(log)) / 86400.0
                witness, kind = os.path.relpath(log, REPO), "log"
            elif std and os.path.exists(std):
                age = (now.timestamp() - os.path.getmtime(std)) / 86400.0
                witness, kind = std, "stdout"

        rows.append({
            "label": label,
            "script": os.path.basename(script) if script else None,
            "allowance_days": allow,
            "age_days": age,
            "witness": witness,
            "witness_kind": kind,
            "silent": bool(age is not None and age > allow),
        })
    return rows


def main():
    args = sys.argv[1:]
    if any(a not in ("--strict", "--quiet") for a in args):
        print("usage: check_job_liveness.py [--strict] [--quiet]")
        return 3
    strict, quiet = "--strict" in args, "--quiet" in args

    rows = scan()
    if not rows:
        if not quiet:
            print("⚪ no scheduled jobs found — nothing to check")
        return 0

    silent = [r for r in rows if r["silent"]]
    blind = [r for r in rows if r["witness_kind"] == "none"]

    if not quiet:
        for r in rows:
            if r["witness_kind"] == "none":
                print(f"   ⚪ {r['label']}  NO WITNESS — neither a stamp nor a declared log, so "
                      f"whether it ran cannot be checked, only assumed")
            elif r["silent"]:
                print(f"   ⚠️  {r['label']}  last ran {r['age_days']:.1f}d ago "
                      f"(allowed {r['allowance_days']:.0f}d) · {r['witness']}")
            else:
                # Name the EVIDENCE, not just the age: "stamp" means it finished, "log"/"stdout"
                # mean only that it wrote something before possibly dying.
                print(f"   ✅ {r['label']}  ran {r['age_days']:.1f}d ago · "
                      f"{r['witness']} ({r['witness_kind']})")
        weak = [r for r in rows if r["witness_kind"] == "stdout"]
        if weak:
            print(f"   ⚪ {len(weak)} job(s) are witnessed only by a /tmp StandardOutPath, which "
                  f"proves output, not completion, and is cleared on reboot.")
        if blind:
            print(f"   ⚪ {len(blind)} of {len(rows)} scheduled job(s) leave no evidence they ran.")
            print("      A job with no witness cannot go late; it can only go unnoticed. Give it a")
            print("      completion stamp under documents/state/ the way daily-rank.sh does.")
        if silent:
            print(f"   ⚠️  {len(silent)} job(s) silent past their own schedule's allowance.")

    return 1 if (strict and silent) else 0


if __name__ == "__main__":
    sys.exit(main())
