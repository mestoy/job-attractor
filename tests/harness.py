"""Minimal test harness for the kit's script-level suites.

The two ranker suites (test_rank_experiments, test_log_impression) were written against the reference
workspace's SandboxTest. The kit does not carry that (it is rsync-based and owner-specific), so this
is a small, generic stand-in that gives them what they actually use: a throwaway sandbox whose
CLAUDE_PROJECT_DIR the scripts honor, so a run writes its state into the sandbox and never the real
tree. It is deliberately tiny: only the `sb` methods the suites call (path/read/lines/script/hook)
and LIVE_REPO. Kit scripts are executed from the kit's own scripts/ dir, so their sibling imports
resolve; only their DATA is redirected into the sandbox.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _tree_guard  # noqa: E402,F401  (BEFORE tmp_cleanup: atexit is last in, first out, so the guard compares after the temp dirs are gone)
import _roots  # noqa: E402
_roots.scrub_ambient()   # BUG-784: a test that imports the harness never inherits the session's data root
import tmp_cleanup  # noqa: E402,F401  (removes this process's /tmp sandboxes on exit, on SIGTERM, and sweeps dead owners')

# The kit root (this file lives in <kit>/tests/). The reference workspace calls it LIVE_REPO, so the
# copied suites' `sys.path.insert(0, os.path.join(LIVE_REPO, "scripts"))` keeps working unchanged.
LIVE_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(LIVE_REPO, "scripts")


class _Sandbox:
    def __init__(self, root):
        self.root = root
        self.home = os.path.join(root, "home")
        self.mem = os.path.join(root, "mem")
        os.makedirs(self.home, exist_ok=True)
        os.makedirs(self.mem, exist_ok=True)

    def env(self, **extra):
        # both roots through the one writer of the rule: kit scripts write their state under CLAUDE_PROJECT_DIR, and check_dup resolves its stores
        # from its install unless JOBSEARCH_DATA_ROOT is set (kit #156)
        e = _roots.sandbox_env(self.root, HOME=self.home)
        e["JOBSEARCH_TEST"] = "1"                # the redirect above is legal only inside a test: check_dup --send-gate refuses it otherwise
        e["JOBSEARCH_MEMORY_DIR"] = self.mem
        e.pop("GIT_DIR", None)
        e.update(extra)
        return e

    def path(self, rel):
        return os.path.join(self.root, rel)

    def read(self, rel):
        p = self.path(rel)
        return open(p, encoding="utf-8", errors="ignore").read() if os.path.exists(p) else ""

    def write(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(text)
        return p

    def lines(self, rel):
        return [ln for ln in self.read(rel).splitlines() if ln.strip()]

    def script(self, name, *args, stdin=None, **extra_env):
        """Run <kit>/scripts/<name> with the sandbox environment. Returns CompletedProcess."""
        cmd = [sys.executable, os.path.join(_SCRIPTS, name)] + [str(a) for a in args]
        return subprocess.run(cmd, cwd=self.root, env=self.env(**extra_env),
                              input=stdin, capture_output=True, text=True)

    def hook(self, name, payload: dict):
        """Run a hook script the way the runtime does: JSON on stdin."""
        return self.script(name, stdin=json.dumps(payload))


class SandboxTest(unittest.TestCase):
    """Base class: ONE throwaway sandbox per test CLASS (matching the reference harness contract, so
    the copied suites' own setUp can clear state via self.sb without calling super). Generic, no
    owner data; the sandbox dir is removed after the class finishes."""

    @classmethod
    def setUpClass(cls):
        cls._root = tempfile.mkdtemp(prefix="kit-sandbox-")
        os.makedirs(os.path.join(cls._root, "documents", "state"), exist_ok=True)
        cls.sb = _Sandbox(cls._root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._root, ignore_errors=True)

    def probe(self, module, body):
        """Run a snippet against the kit's scripts dir, out of process, and return its stdout (a
        subprocess so importing a module never leaves its scripts/ on this process's sys.path)."""
        src = "import sys; sys.path.insert(0, %r)\nimport %s\n%s" % (_SCRIPTS, module, body)
        r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def assertExit(self, res, code, msg=""):
        self.assertEqual(
            res.returncode, code,
            f"{msg}\nexpected exit {code}, got {res.returncode}\n"
            f"--- stdout ---\n{res.stdout[-1500:]}\n--- stderr ---\n{res.stderr[-1500:]}",
        )


# ── WHERE THE HOOK EXAMPLE LIVES, and why it takes a function ───────────────────────────────────
# ⛔ backup.sh:146: "partner-starter carries no .claude/ by design". Its kit-sync maps the ROOT
# `settings.example.json` to `.claude/settings.example.json` in the shipped kit, which is where
# install.sh and doctor.py read it. So the two trees keep the same file in two places on purpose.
#
# Every test that needed it used to resolve `.claude/` and FALL BACK to the root, then copy the
# file into `.claude/` inside its own sandbox. The fallback was silently the only branch ever
# taken, and the copy meant each test proved the wiring GIVEN a file the tree had not put there.
# Three of them stayed green through a period when no install wired a single hook.
#
# One resolver, used by all of them, so the answer cannot differ between tests, and it RAISES
# rather than returning a guess: a test that cannot find the example must stop, not carry on
# against a path that does not exist.
HOOK_EXAMPLE_CANDIDATES = (os.path.join(".claude", "settings.example.json"),
                           "settings.example.json")


def hook_example(root=None):
    """Absolute path to this tree's shipped hook example. Raises if the tree ships none."""
    root = root or LIVE_REPO
    for rel in HOOK_EXAMPLE_CANDIDATES:
        p = os.path.join(root, rel)
        if os.path.exists(p):
            return p
    raise AssertionError(
        "this tree ships no hook example at %s, so install.sh has nothing to wire the gates from"
        % " or ".join(HOOK_EXAMPLE_CANDIDATES))


# ── WHERE A TEST'S THROWAWAY FILES GO ─────────────────────────────────────────────────────────────
# ⛔ Nine tests used to hardcode /home/vscode/render, the maintainer's container. On anyone else's
# machine, a Mac included, that folder does not exist and /home cannot be written, so every one of
# them errored before testing anything. The container folder is still preferred where it exists,
# because /tmp there is memory and test leftovers have killed sessions; elsewhere the system's own
# temporary folder is used.
def scratch_root():
    import tempfile
    here = "/home/vscode/render"
    return here if os.path.isdir(here) and os.access(here, os.W_OK) else tempfile.gettempdir()
