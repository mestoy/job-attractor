#!/usr/bin/env python3
"""kit_update.py — let the human choose WHEN a pending kit update is applied.

WHY THIS EXISTS
---------------
Updating the kit means double-clicking `Update Kit.command`, which pulls and re-runs `install.sh`.
That takes a while, and until now it was all-or-nothing at whatever moment you happened to run it.
Two things went wrong with that:

  1. You update at the start of a session, then wait, and the work you sat down to do is delayed.
  2. Sometimes you deliberately need to work on the kit you already have, and there was no way to
     say "not now" other than never running the updater and forgetting about it.

So this offers three answers, ONCE per session: **now**, **at the end of this session**, or
**skip this session**.

⛔ DESIGN CONSTRAINTS, all of them learned the hard way
------------------------------------------------------
· **OFFLINE AND FAST.** `session_start.py` runs inside the SessionStart hook and must not reach the
  network; a briefing that hangs delays every session open. The check below is `git rev-list
  HEAD..@{upstream}`, which reads refs ALREADY on disk from the last fetch. It therefore reports
  what your last fetch knew, never what the remote holds right now. That is the correct trade:
  a stale "no update" costs one session, a network call in a hook costs every session.
· **NEVER RAISES.** Every entry point catches and degrades to "no update pending". A crash here
  would block a session from opening, which costs more than a missed notice.
· **THE ANSWER IS PER SESSION, not per day.** Sessions are the unit the human experiences; a
  per-day stamp would go unasked after a morning "skip" even though the afternoon is new work.
· **THIS FILE CANNOT REACH AN INSTALL THAT HAS NOT UPDATED YET.** It arrives WITH a pull, so the
  first time you see the choice is the session AFTER the update that delivers it. Same chicken and
  egg as `Update Kit.command` itself; nothing here can fix that, and pretending otherwise would be
  the third time this kit has shipped a fix that could not reach the installs needing it.

State lives in `documents/state/kit-update.json`, which is git-ignored like the rest of
`documents/`, so it never travels between installs.
"""
import json
import os
import subprocess
import sys

REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(REPO, "documents", "state", "kit-update.json")
CHOICES = ("now", "defer", "skip")


def _git(*args):
    """Run a git command in the kit and return stdout, or '' on any failure.

    Deliberately swallows everything: not a git clone, no upstream configured, git missing from
    PATH. Each of those means "cannot tell whether an update is pending", and the honest answer to
    that is silence rather than a scary line in the briefing.
    """
    try:
        r = subprocess.run(("git",) + args, cwd=REPO, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def kit_remote():
    """The remote whose URL IS the kit, whatever it is named. Falls back to 'origin'.

    ⛔ NEVER ASSUME `origin` (2026-08-03). A partner who forked the kit into their own account has
    `origin` pointing at THEIR repo. One real install carried three remotes (`origin` theirs, plus
    `kit` and `upstream` both pointing at the kit) with the branch tracking `origin/main`, so every
    update pulled from their own repo and reported success. This function is the same resolution
    `Update Kit.command` now does, kept in step with it deliberately: two answers to "which remote is
    the kit" is how the two would drift apart.
    """
    for r in (_git("remote") or "").split():
        if "job-attractor-kit" in (_git("remote", "get-url", r) or ""):
            return r
    return "origin"


def commits_behind():
    """How many kit commits are already fetched and not yet merged. 0 when unknown.

    ⚠️ NO FETCH. See the module docstring: this is what the last fetch learned. The fetch happens in
    `--stop` mode, and `Update Kit.command` refreshes it too.

    Counts against the KIT remote's branch rather than `@{upstream}`, because a branch that tracks
    the wrong remote would otherwise report 0 forever, and "no update pending" would be a lie told
    confidently. Falls back to `@{upstream}` only when the kit branch cannot be resolved.
    """
    remote = kit_remote()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "main"
    for ref in (f"{remote}/{branch}", f"{remote}/main"):
        out = _git("rev-list", "--count", f"HEAD..{ref}")
        if out:
            try:
                return int(out)
            except ValueError:
                pass
    out = _git("rev-list", "--count", "HEAD..@{upstream}")
    try:
        return int(out)
    except (TypeError, ValueError):
        return 0


def _read():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def choice_for(session_id):
    """The answer already given for THIS session, or '' if it has not been asked yet."""
    row = _read()
    if session_id and row.get("session_id") == session_id and row.get("choice") in CHOICES:
        return row["choice"]
    return ""


def record(session_id, choice):
    """Persist the answer. Returns True on success, False on any write failure."""
    if choice not in CHOICES:
        return False
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"session_id": session_id or "", "choice": choice,
                       "behind": commits_behind()}, fh, indent=1)
        os.replace(tmp, STATE)
        return True
    except Exception:
        return False


def pending_notice(session_id):
    """The briefing line, or None. Consumed by session_start.py.

    None in three cases, and they are different on purpose: nothing fetched to apply, the human
    already answered this session, or git could not tell us anything.
    """
    try:
        n = commits_behind()
        if n <= 0 or choice_for(session_id):
            return None
        return (f"{n} kit update(s) ready to apply",
                ["ask BEFORE doing other work: apply now, at the end of this session, or skip it",
                 "applying runs 'Update Kit.command' (a pull plus install.sh) and takes a few minutes",
                 "record the answer: python3 scripts/kit_update.py --record <now|defer|skip>"])
    except Exception:
        return None


def run_update():
    """Apply the update by handing off to the same updater a double-click runs.

    ⛔ Deliberately NOT a reimplementation of the pull. `Update Kit.command` carries the config
    preservation, the superseded-file backups and the stranded-clone recovery, and a second copy of
    that logic would drift from it. One updater, called two ways.
    """
    cmd = os.path.join(REPO, "Update Kit.command")
    if not os.path.exists(cmd):
        print("⚠️  'Update Kit.command' is missing; cannot apply the update automatically.")
        return 1
    try:
        return subprocess.call(["bash", cmd], cwd=REPO)
    except Exception as e:
        print(f"⚠️  could not run the updater ({type(e).__name__}).")
        return 1


def main(argv):
    session_id = ""
    if "--session" in argv:
        i = argv.index("--session")
        session_id = argv[i + 1] if i + 1 < len(argv) else ""
    if not session_id:
        session_id = os.environ.get("CLAUDE_SESSION_ID", "")

    if "--check" in argv:
        n = commits_behind()
        answered = choice_for(session_id)
        print(f"kit updates ready to apply: {n}")
        print(f"this session's answer: {answered or '(not asked yet)'}")
        return 0

    if "--record" in argv:
        i = argv.index("--record")
        pick = argv[i + 1] if i + 1 < len(argv) else ""
        if pick not in CHOICES:
            print(f"usage: kit_update.py --record <{'|'.join(CHOICES)}> [--session <id>]")
            return 2
        if not record(session_id, pick):
            print("⚠️  could not save the answer; it will be asked again next session.")
            return 1
        print(f"✅ recorded: {pick}")
        if pick == "now":
            return run_update()
        if pick == "defer":
            print("   the update will run when this session ends.")
        else:
            print("   skipped for this session; you will be asked again next time.")
        return 0

    # Stop-hook mode: apply a DEFERRED update, and nothing else. Silent in every other case, because
    # a Stop hook that prints on an ordinary turn is noise the human learns to ignore.
    if "--stop" in argv:
        if choice_for(session_id) == "defer" and commits_behind() > 0:
            print("▶  Applying the kit update you deferred…")
            run_update()
        # REFRESH THE REFS *HERE*, never at session start. The offline check above reads what the
        # last fetch learned, so without this the count would sit at 0 forever and the choice would
        # never be offered — the feature would look like it worked while telling you nothing.
        # A Stop hook is the right home: the turn is already over, so a slow network costs nobody
        # anything, and the answer is ready before the next session opens. Quiet and best-effort;
        # no upstream, no network and no git are all just "we learn nothing this time".
        _git("fetch", kit_remote(), "--quiet")
        return 0

    notice = pending_notice(session_id)
    print(notice[0] if notice else "kit is up to date with what has been fetched.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:
        # Never take a session down over an update notice.
        print(f"[kit_update] unavailable ({type(e).__name__}).")
        sys.exit(0)
