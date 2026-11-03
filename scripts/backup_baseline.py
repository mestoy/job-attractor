#!/usr/bin/env python3
"""backup_baseline.py — the clean-baseline marker for BUG-218a Layer 2 (the UNATTENDED case).

WHY (#87/#91). Layer 1 (backup_hold.py) protects work only if a human REMEMBERS to set a hold
before the timer fires. The launchd backup timer's real threat model is the opposite: nobody is
present to remember anything. An unattended run (the auto-sweep cron, or the backup timer itself)
can WebFetch text the fetched company controls, Write files, and then backup.sh pushes the result
— with no human anywhere in that chain to catch an injected write before it goes out.

This closes the gap on the PUBLISH side. A human, after reviewing the tree (a diff, the gates,
whatever "reviewed" means that day), VOUCHES the current commit as clean:

    scripts/backup_baseline.py set [--note "..."]

That records documents/state/.backup-baseline = {"sha": <HEAD then>, "ts": ..., "note": ...}.

On an UNATTENDED run (JOBSEARCH_UNATTENDED=1, set only by the launchd plist — never by an
interactive/chat-invoked run) backup.sh asks `check`: does anything OUTSIDE documents/state/
differ from that vouched SHA, either already committed since it or sitting uncommitted right now?
`documents/state/` is excluded on purpose — BUG-218's companion fix already restricts what an
unattended agent's Write/Edit tools may touch to that one directory, so routine state churn from a
normal unattended run is expected and does not itself need a fresh vouch. Anything else — an
injected write that escaped the tool scoping, a human's own mid-review work the timer's
`git add -A` swept in, a merge — does.

⚖️ NO BASELINE RECORDED IS TREATED AS DRIFT, deliberately the opposite direction from
backup_hold's own fail-safe. backup_hold fails TOWARD backing up (a forgotten hold must not wedge
the LOCAL commit forever — durability). This gate fails TOWARD withholding PUBLISH (an unknown
state must not go out just because nobody ever ran `set` — the local commit still happens either
way, so nothing is lost, only delayed until a human looks).

An INTERACTIVE run (JOBSEARCH_UNATTENDED unset) is exempt from this check entirely — a present
human or terminal invoking backup.sh directly IS the review, the same reasoning backup_hold.py
uses for why a hold only needs to be set for UNATTENDED-adjacent work.

  backup_baseline.py set [--note "..."]   # vouch HEAD as clean (after a human reviews it)
  backup_baseline.py status                # human-readable current baseline + drift, if any
  backup_baseline.py check                 # exit 0 = clean outside documents/state/ · 1 = drift

Stdlib only. Kit-portable (no owner-specific paths; REPO resolves the same way every other
script in this file does).
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
BASELINE = os.path.join(REPO, "documents", "state", ".backup-baseline")

# The one directory an unattended run's Write/Edit tools may touch (BUG-218 item 3). Drift inside
# it is expected and never blocks publish; drift outside it always does.
EXEMPT_PREFIX = "documents/state/"

# ⛔ RED-TEAM FINDING (2026-08-22), fixed here rather than shipped broken. `.backup-baseline` and
# `.backup-hold` (Layer 1) both live INSIDE documents/state/, the one directory this gate treats as
# exempt. Naively exempting the whole directory means a compromised agent with Write access could
# overwrite `.backup-baseline` to SELF-VOUCH: point the recorded `sha` at the very commit it just
# produced, and `drift()` would trivially read that forged file back and report "clean". `_sentinel_
# tampered()` below closes this: either sentinel's ON-DISK bytes must match what HEAD already has
# committed, or the run is treated as drift regardless of what the sentinel claims. In the real
# flow this is never a false positive — `set` is run interactively, and the SAME session's own
# `!backup` (or any later commit, including this script's own routine one) commits the file before
# the next UNATTENDED run ever consults it. An uncommitted sentinel at check() time therefore means
# something wrote it OUTSIDE the normal human-set-then-commit cycle, which is exactly the shape of
# the attack this closes.
_NEVER_EXEMPT_BASENAMES = {".backup-baseline", ".backup-hold"}


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _git(args):
    try:
        r = subprocess.run(["git", "-C", REPO] + args, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return 1, "", str(e)
    return r.returncode, r.stdout, r.stderr


def read():
    """The current baseline dict, or None if never set / unreadable."""
    if not os.path.exists(BASELINE):
        return None
    try:
        with open(BASELINE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _outside_state(paths):
    return sorted({p for p in paths if p and not p.startswith(EXEMPT_PREFIX)})


def _uncommitted_paths():
    """Every path with staged, unstaged, or untracked changes right now (porcelain v1)."""
    rc, out, _ = _git(["status", "--porcelain=v1"])
    if rc != 0:
        return None
    paths = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        p = line[3:]
        if " -> " in p:            # a rename: "old -> new"; the new path is what exists now
            p = p.split(" -> ", 1)[1]
        paths.append(p.strip('"'))
    return paths


def _committed_since(sha):
    """Paths changed between `sha` and HEAD, or None if `sha` cannot be resolved (bad/rewritten)."""
    rc, out, _ = _git(["diff", "--name-only", f"{sha}..HEAD"])
    if rc != 0:
        return None
    return [l for l in out.splitlines() if l.strip()]


def _committed_content(rel_path, ref="HEAD"):
    """Bytes `rel_path` holds at `ref` per git, or None if it does not exist there."""
    rc, out, _ = _git(["show", f"{ref}:{rel_path}"])
    return out if rc == 0 else None


def _sentinel_tampered():
    """(True, rel_path) if a sentinel's ON-DISK content differs from what HEAD has committed.

    The self-vouch closer: a legitimate `set` is followed, sooner or later, by SOME commit (the
    same interactive session's own publish, or this script's own routine one) before the next
    UNATTENDED run ever calls `check()`. A sentinel sitting uncommitted, or committed but then
    edited again without a matching commit, at the moment an unattended run checks it means
    something wrote it OUTSIDE that normal cycle — treated as drift, no exceptions.
    """
    for name in sorted(_NEVER_EXEMPT_BASENAMES):
        rel = f"documents/state/{name}"
        disk_path = os.path.join(REPO, rel)
        on_disk = None
        if os.path.exists(disk_path):
            try:
                with open(disk_path, encoding="utf-8") as fh:
                    on_disk = fh.read()
            except Exception:
                on_disk = "<unreadable>"
        if on_disk != _committed_content(rel):
            return True, rel
    return False, None


def drift():
    """(clean: bool, reason: str, changed_paths: list[str]).

    clean=True means: a baseline is on record AND nothing outside documents/state/ has changed
    since it, either committed or sitting uncommitted right now. Anything else is drift.
    """
    b = read()
    if not b or not b.get("sha"):
        return False, "no baseline recorded — run `backup_baseline.py set` after a reviewed clean state", []
    tampered, which = _sentinel_tampered()
    if tampered:
        return False, f"{which} is uncommitted or edited outside the normal set-then-commit " \
                       f"cycle — treated as tampering, not a vouch", [which]
    sha = b["sha"]
    committed = _committed_since(sha)
    if committed is None:
        return False, f"baseline sha {sha[:12]} not found in history (rewritten/rebased?) — re-vouch with `set`", []
    uncommitted = _uncommitted_paths()
    if uncommitted is None:
        return False, "could not read git status — treating as drift (fail toward withholding publish)", []
    changed = sorted(set(_outside_state(committed)) | set(_outside_state(uncommitted)))
    if changed:
        return False, f"{len(changed)} path(s) changed outside {EXEMPT_PREFIX} since the baseline", changed
    return True, "clean", []


def cmd_set(note):
    rc, sha, _ = _git(["rev-parse", "HEAD"])
    sha = sha.strip()
    if rc != 0 or not sha:
        print("🔴 could not resolve HEAD — is this a git repo?", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
    row = {"sha": sha, "ts": _now().isoformat(), "note": (note or "").strip()}
    with open(BASELINE, "w", encoding="utf-8") as fh:
        json.dump(row, fh)
    print(f"✅ baseline vouched: {sha[:12]}" + (f" — {row['note']}" if row["note"] else ""))
    return 0


def cmd_status():
    b = read()
    if not b:
        print("⚪ no baseline recorded yet — an unattended run will withhold publish until one is set")
        return 0
    clean, reason, changed = drift()
    when = b.get("ts", "?")
    note = f" — {b['note']}" if b.get("note") else ""
    print(f"baseline: {b.get('sha', '?')[:12]} vouched {when}{note}")
    if clean:
        print("✅ clean: nothing outside documents/state/ has changed since the baseline")
    else:
        print(f"🔴 drift: {reason}")
        for p in changed[:15]:
            print(f"   · {p}")
        if len(changed) > 15:
            print(f"   … +{len(changed) - 15} more")
    return 0


def cmd_check():
    clean, _reason, _changed = drift()
    return 0 if clean else 1


def main():
    ap = argparse.ArgumentParser(description="clean-baseline marker for the unattended backup gate")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("set")
    s.add_argument("--note", default="")
    sub.add_parser("status")
    sub.add_parser("check")
    a = ap.parse_args()

    if a.cmd == "set":
        return cmd_set(a.note)
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "check":
        return cmd_check()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
