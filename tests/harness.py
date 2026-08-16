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
        e = dict(os.environ)
        e["HOME"] = self.home
        e["CLAUDE_PROJECT_DIR"] = self.root      # kit scripts write their state under here
        e["JOBSEARCH_MEMORY_DIR"] = self.mem
        e.pop("GIT_DIR", None)
        e.update(extra)
        return e

    def path(self, rel):
        return os.path.join(self.root, rel)

    def read(self, rel):
        p = self.path(rel)
        return open(p, encoding="utf-8", errors="ignore").read() if os.path.exists(p) else ""

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
