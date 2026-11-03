"""One writer of the data-root rule for the partner tests (BUG-733 option B, slice 2).

Two variables name the install a kit script reads and writes: CLAUDE_PROJECT_DIR (the session's) and JOBSEARCH_DATA_ROOT (check_dup,
board, check_outreach and others read it first). A test that redirects only one is blind the day a module reads the other, and a test
that leaves the session variable unset resolves dirname(HERE), which IS the shipped kit tree. So a test sets BOTH, to the same temp root,
through these helpers, and tests/test_bug733_slice2_isolation.py fails any site that does not.

  sandbox_env(root, **extra)  a copy of os.environ for a SUBPROCESS, both variables set, HOME under the root unless given
  set_roots(root)             set both in THIS process; returns a restore() that puts back (or removes) what was there
  patch_roots(test, root)     set_roots + test.addCleanup(restore)
  data_root_unset()           context manager: JOBSEARCH_DATA_ROOT removed for one in-process call, CLAUDE_PROJECT_DIR kept. check_dup's
                              send gate REFUSES when JOBSEARCH_DATA_ROOT names anything but its own install (kit #156), so an in-process
                              --send-gate call runs inside this, with check_dup.REPO patched to the temp root
  scrub_ambient()             remove both variables from THIS process. Run once, when the tests package (or harness) is imported, so a test that
                              forgets to set its own roots resolves its sandbox copy and never the session's install (BUG-784)
  point_env(env, root)        set both on an env dict the caller already built (PATH stubs, popped GIT_DIR); returns it
Standard library only."""
import contextlib
import os

KEYS = ("CLAUDE_PROJECT_DIR", "JOBSEARCH_DATA_ROOT")


def scrub_ambient():
    """BUG-784: the session exports CLAUDE_PROJECT_DIR (and a seat may export JOBSEARCH_DATA_ROOT) naming the owner's REAL install, and
    mail-draft.sh follows them (BUG-773), so a test that copies a script and inherits them writes the owner's logs. A test that wants a root
    sets BOTH itself (sandbox_env, set_roots); none may borrow the session's."""
    for k in KEYS:
        os.environ.pop(k, None)


def sandbox_env(root, **extra):
    env = dict(os.environ)
    for k in KEYS:
        env[k] = str(root)
    env.setdefault("HOME", os.path.join(str(root), "home"))
    env.update(extra)
    return env


def point_env(env, root):
    for k in KEYS:
        env[k] = str(root)
    return env


def set_roots(root):
    prev = {k: os.environ.get(k) for k in KEYS}
    for k in KEYS:
        os.environ[k] = str(root)

    def restore():
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return restore


def patch_roots(test, root):
    restore = set_roots(root)
    test.addCleanup(restore)
    return restore


@contextlib.contextmanager
def data_root_unset():
    prev = os.environ.pop("JOBSEARCH_DATA_ROOT", None)
    try:
        yield
    finally:
        if prev is not None:
            os.environ["JOBSEARCH_DATA_ROOT"] = prev
