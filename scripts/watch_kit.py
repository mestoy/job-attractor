#!/usr/bin/env python3
"""watch_kit.py — notice when new kit commits land upstream, and FAIL LOUD when it cannot look.

WHY THIS EXISTS (kit #96, 2026-09-12). The mechanism that tells a kit user "something shipped" was
a local 33-line watcher that ran `git fetch kit`, appended one log line on failure, and exited 0.
From 2026-09-08 every run failed with

    error: cannot lock ref 'refs/remotes/kit/main': is at 4562dd1... but expected 30ecd98...

and nothing surfaced it. That error is git refusing a ref update because ANOTHER process moved the
same ref between the read and the write: two fetches of the kit remote running at once (reproduced
in a sandbox with `git fetch kit & git fetch kit & wait`). The updater and a scheduled watcher are
exactly that pair. This script takes a lock so it never races itself, and it treats every fetch
failure as an alarm.

⛔ SILENCE IS NEVER A PASS. A watcher that fails closed and quiet is worse than no watcher, because
the user reads the silence as "nothing new". So a failed fetch is: a stderr line naming the remote
and git's own error, a distinct alert file under documents/state/, and exit 2. Only a fetch that
ran to completion may report "up to date".

Exit: 0 = up to date · 1 = new kit commit(s) fetched, run Update Kit.command · 2 = could NOT fetch
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime

KIT_URL_MARK = "job-attractor-kit"


def git(repo, *args, timeout=60):
    return subprocess.run(("git",) + args, cwd=repo, capture_output=True, text=True, timeout=timeout)


def kit_remote(repo):
    """The remote whose URL IS the kit, whatever it is named (same rule as kit_update.kit_remote)."""
    names = (git(repo, "remote").stdout or "").split()
    for r in names:
        if KIT_URL_MARK in (git(repo, "remote", "get-url", r).stdout or ""):
            return r
    return "origin"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.environ.get("CLAUDE_PROJECT_DIR")
                    or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    state = os.path.join(repo, "documents", "state")
    os.makedirs(state, exist_ok=True)
    alert = os.path.join(state, "kit-watch-alert.txt")
    log = os.path.join(state, "kit-watch.log")
    lock = os.path.join(state, ".kit-watch.lock")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def note(line):
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{stamp} {line}\n")

    def fail(what):
        msg = f"watch_kit: {what}"
        note(f"[!!] {what}")
        with open(alert, "w", encoding="utf-8") as f:
            f.write(f"{stamp}\n{what}\n")
        print(msg, file=sys.stderr)
        return 2

    remote = kit_remote(repo)
    # mkdir is the atomic lock everywhere; a second watcher racing the first is the exact cause of
    # the 09-08 "cannot lock ref" error, so the second one waits for the next tick instead.
    try:
        os.mkdir(lock)
    except FileExistsError:
        return fail(f"another watcher holds {lock}; if none is running, remove it")
    try:
        try:
            r = git(repo, "fetch", remote, "--quiet")
        except Exception as e:  # git missing, timeout
            return fail(f"git fetch {remote} failed: {e}")
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip().replace("\n", " | ") or f"exit {r.returncode}"
            return fail(f"git fetch {remote} failed: {err}")
    finally:
        os.rmdir(lock)

    if os.path.exists(alert):
        os.remove(alert)
    behind = git(repo, "rev-list", "--count", f"HEAD..{remote}/main")
    if behind.returncode != 0:
        return fail(f"fetched {remote} but cannot read {remote}/main: {behind.stderr.strip()}")
    n = int(behind.stdout.strip() or 0)
    if n:
        s = "" if n == 1 else "s"
        print(f"{n} commit{s} landed on the kit since your last update. Run 'Update Kit.command'.")
        note(f"[>>] {n} commit(s) behind {remote}/main")
        return 1
    print("kit is up to date.")
    note("[ok] up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
