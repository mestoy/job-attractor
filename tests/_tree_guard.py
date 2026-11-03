"""The kit-tree fence (BUG-733 option B, slice 2): a test process fails if anything under <kit>/documents/ changed while it ran.

WHY. A partner test that isolates with only one of the two data-root variables (CLAUDE_PROJECT_DIR and JOBSEARCH_DATA_ROOT), or that leaves
the session variable unset, can read or WRITE the shipped tree at partner-starter/documents/. run_all.sh already fingerprints it, but a
seat that runs one file with `python3 -m unittest tests.test_x` (every builder brief) never went through run_all.sh. This guard is
installed by tests/__init__.py (and by harness.py) at import, snapshots <kit>/documents/** (sha256 per file), and compares at interpreter
exit. A change prints the paths and ends the process with status 3.

KNOWN GAP. tests/__init__.py installs the guard, so it covers `python3 -m unittest tests.test_x` and `unittest discover`. A DIRECT run
(`python3 tests/test_x.py`) of a file that does not import harness.py never imports the package, so it is NOT covered; run_all.sh's
fingerprint is the backstop for that. tests/test_bug733_slice2_isolation.py states the same gap.

HOW IT EXITS, and why not sys.exit. Measured on Python 3.11.2: sys.exit(3) inside an atexit handler is swallowed ("Exception ignored in
atexit callback") and the process exits 0, so the guard would fail open. os._exit(3) is the only way to set the status from there. It skips
atexit handlers that have not run yet, so the guard (a) is installed BEFORE tmp_cleanup registers its handler (atexit is last in, first
out, so tmp_cleanup's handler runs first and the guard last), and (b) calls tmp_cleanup.remove_mine() itself before os._exit, so no /tmp
sandbox of this process is left behind (/tmp is RAM).

ONE EXEMPTION SET. EXEMPT is read by run_all.sh's fingerprint() as well (a one-line python3 -c), so the two guards cannot disagree about
the witness file that rewrites itself by design (rank_criteria._stamp_derivation).

LIMIT. A parallel writer in the same checkout (/sync-kit, another seat's run) is indistinguishable from the test, so the message says the
tree "changed during this run". Run builders in worktrees. A file run directly as a script (python3 tests/test_x.py) does not import the
package and is not covered; run_all.sh covers the whole suite. Standard library only."""
import atexit
import hashlib
import os
import sys

EXEMPT = {"documents/state/weights-derive.json"}
_MARK = "_ja_tree_guard_installed"
_ROOT = os.environ.get("JA_TREE_GUARD_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the env var is for the probe only


# Data files the kit keeps at its ROOT, outside documents/. A test that logged a send into the shipped tree wrote outreach_log.md (found
# 2026-10-28: test_kf2_contactcard set only JOBSEARCH_DATA_ROOT), and a documents/-only guard could not see it.
ROOT_FILES = ("outreach_log.md", "job_search_tracker.csv", "prospect_queue.md")


def snapshot(root, exempt=None):
    """{relative path: sha256} for every file under <root>/documents/ plus the ROOT_FILES, minus the exempt names."""
    exempt = EXEMPT if exempt is None else exempt
    out = {}
    for rel in ROOT_FILES:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                out[rel] = hashlib.sha256(fh.read()).hexdigest()
    for d, dirs, files in os.walk(os.path.join(root, "documents")):
        dirs.sort()
        for name in sorted(files):
            p = os.path.join(d, name)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if rel in exempt:
                continue
            try:
                with open(p, "rb") as fh:
                    out[rel] = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                out[rel] = "unreadable"
    return out


def diff(before, after):
    """Sorted paths that were added, removed or changed."""
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def check(before, root, leave=os._exit):
    """Compare now against `before`; on a change print the paths, clean up this process's temp dirs and leave with status 3."""
    changed = diff(before, snapshot(root))
    if not changed:
        return []
    msg = ("tree guard: %s/documents changed during this run (a test wrote or deleted these; the kit tree must stay as shipped):\n  %s\n"
           % (os.path.basename(os.path.abspath(root)), "\n  ".join(changed)))
    try:
        sys.stderr.write(msg)
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    cleanup = sys.modules.get("tmp_cleanup")
    if cleanup is not None:
        try:
            cleanup.remove_mine()
        except Exception:
            pass
    leave(3)
    return changed


# BUG-784: the tell of a test that wrote the owner's REAL logs. These three strings only ever come from a fixture send (mail-draft tests), never
# from the owner's own record. Read-only: the real files are scanned, never hashed, because a live seat legitimately appends to them mid-run.
FIXTURE_STRINGS = ("SomeCo", "jane@example.test", "Jane Doe")
REAL_LOGS = ("documents/send-log.jsonl", "documents/correspondence-log.md", "outreach_log.md")


def fixture_leaks(kit_root):
    """Paths (relative to the real install above <kit_root>) whose text carries a fixture string. [] when this kit is not inside an install."""
    real = os.path.dirname(os.path.abspath(kit_root))
    if not os.path.isfile(os.path.join(real, "documents", "send-log.jsonl")):
        return []
    out = []
    for rel in REAL_LOGS:
        p = os.path.join(real, rel)
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        if any(s in text for s in FIXTURE_STRINGS):
            out.append(rel)
    return out


def check_fixture_leaks(kit_root, leave=os._exit):
    """At exit: a fixture send in the owner's real logs fails the run with status 3, before cleanup, naming the file."""
    found = fixture_leaks(kit_root)
    if not found:
        return []
    try:
        sys.stderr.write("tree guard: the real install carries a fixture send (SomeCo / jane@example.test / Jane Doe) in:\n  %s\n"
                         "a test wrote the owner's logs outside its sandbox (BUG-784); remove the rows and find the test.\n" % "\n  ".join(found))
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    cleanup = sys.modules.get("tmp_cleanup")
    if cleanup is not None:
        try:
            cleanup.remove_mine()
        except Exception:
            pass
    leave(3)
    return found


def install():
    if getattr(sys, _MARK, False):
        return
    setattr(sys, _MARK, True)
    before = snapshot(_ROOT)
    atexit.register(check, before, _ROOT)
    atexit.register(check_fixture_leaks, _ROOT)


install()
