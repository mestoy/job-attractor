"""An unresolved owner makes the PII gate refuse, loudly, never pass.

The owner's own email and phone are literals every scan blocks. With JOBKIT_OWNER_* unset and no
project card to read them from, the gate used to run with none and read clean by knowing nothing
(found 2026-09-21 in the development container). Both entry points now refuse and say why.
"""
import os
import _roots
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from harness import scratch_root  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "pii_gate.py")
SANDBOX = os.path.join(scratch_root(), "test-pii-owner-fails-loud")
CARD = "# Assistant for Sam River\n\n- **Sam River** · sam@riverfake.dev · 212.555.0142 · riverfake.dev\n"


class OwnerFailsLoud(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        os.makedirs(os.path.join(SANDBOX, "tree"))
        with open(os.path.join(SANDBOX, "tree", "a.md"), "w") as fh:
            fh.write("nothing here\n")

    def tearDown(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)

    def run_scan(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("JOBKIT_OWNER_")}
        _roots.point_env(env, SANDBOX)
        return subprocess.run([sys.executable, SCRIPT, "--scan", os.path.join(SANDBOX, "tree")],
                              capture_output=True, text=True, env=env)

    def test_no_owner_anywhere_refuses_and_says_owner(self):
        p = self.run_scan()
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("owner", (p.stdout + p.stderr).lower())

    def test_a_card_contact_line_resolves_the_owner(self):
        with open(os.path.join(SANDBOX, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write(CARD)
        p = self.run_scan()
        self.assertNotIn("owner's own email", p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
