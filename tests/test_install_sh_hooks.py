#!/usr/bin/env python3
"""The rehearsal's red (documents/state/rehearsal-e2e-2026-09-14.md, row 9): nothing on the /app
path wired the enforcement hooks, so every gate was off after a clean install, and the only fix
was a terminal command the person was promised they would not need.

The contract these tests hold, each in a throwaway sandbox with partner-docs/ present:
  1. a first install with the shipped example and no live settings creates .claude/settings.json
     as a copy of the example and says so in plain words;
  2. a second install changes nothing and does not call the file hand-edited;
  3. a hand-edited live file is kept, as before.
"""
import os
import _roots
import sys
import shutil
import subprocess
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(KIT, "install.sh")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import hook_example  # noqa: E402

EXAMPLE = hook_example(KIT)


def _reached_the_end(case, p):
    """install.sh now ends by RUNNING doctor.py and exiting on its verdict (K3), so a bare sandbox
    with no identity and no profile legitimately exits non-zero. These tests are about the WIRING,
    so what they need is that the installer ran all the way through, not that it approved of the
    sandbox. Asserting returncode 0 here would assert the old contract, in which the install ended
    on DONE whatever the doctor would have said."""
    out = p.stdout + p.stderr
    case.assertIn("Checking the install", out,
                  "install.sh did not reach its final step:\n" + out[-1500:])


def _run(cwd):
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    _roots.point_env(env, cwd)
    return subprocess.run(["bash", "install.sh", "."], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


class TestInstallWiresTheHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit-hooks-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copy(INSTALL, os.path.join(self.tmp, "install.sh"))
        pd = os.path.join(self.tmp, "partner-docs")
        os.makedirs(pd)
        for name in ("PROFILE.md", "segments.md"):
            with open(os.path.join(pd, name), "w") as fh:
                fh.write(f"# {name}\n")
        os.makedirs(os.path.join(self.tmp, ".claude"))
        shutil.copy(EXAMPLE, os.path.join(self.tmp, ".claude", "settings.example.json"))
        self.live = os.path.join(self.tmp, ".claude", "settings.json")

    def test_first_install_creates_the_live_settings_from_the_example(self):
        self.assertFalse(os.path.exists(self.live))
        p = _run(self.tmp)
        out = p.stdout + p.stderr
        _reached_the_end(self, p)
        self.assertTrue(os.path.exists(self.live), "settings.json must exist after a clean install")
        with open(self.live) as a, open(EXAMPLE) as b:
            self.assertEqual(a.read(), b.read())
        self.assertIn("hooks wired", out.lower())
        self.assertNotIn("hand-edited", out)

    def test_second_install_changes_nothing(self):
        _run(self.tmp)
        before = open(self.live).read()
        p = _run(self.tmp)
        out = p.stdout + p.stderr
        _reached_the_end(self, p)
        self.assertEqual(open(self.live).read(), before)
        self.assertNotIn("hand-edited", out)

    def test_hand_edited_live_file_is_kept(self):
        with open(self.live, "w") as fh:
            fh.write('{"hooks": {}, "mine": true}\n')
        p = _run(self.tmp)
        out = p.stdout + p.stderr
        _reached_the_end(self, p)
        self.assertIn('"mine": true', open(self.live).read())
        self.assertIn("KEPT YOURS", out)


if __name__ == "__main__":
    unittest.main()
