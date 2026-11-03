#!/usr/bin/env python3
"""BUG-744: pii_gate._resolve_owner drops only a WHOLE template value from the owner's identity, never a real one that starts like one.

The old filter was the prefix regex ^(your|you@|...|jane|john|...): an owner named "John Fixtureson" (first name "John", email johnfixtureson@...) dropped
out of the identity vocabulary, so the gate never searched for him (a fail-open for any owner named John or Jane). The rule is now the same whole-value
one as BUG-737's check_store_data._PLACEHOLDER. The file works unchanged in the main, partner-starter and kit trees: it runs a clean interpreter on a
temp copy of this tree's scripts, with a kit_config from the shipped example when the tree has none. Names are invented.
   python3 -m unittest tests.test_bug744_owner_whole -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHILD = "import json, sys; sys.path.insert(0, sys.argv[1]); import pii_gate; print(json.dumps(pii_gate._resolve_owner()))"

REAL = [
    {"JOBKIT_OWNER_NAME": "John Fixtureson", "JOBKIT_OWNER_EMAIL": "johnfixtureson@mcfixture.invalid"},
    {"JOBKIT_OWNER_NAME": "Jane Testcase", "JOBKIT_OWNER_EMAIL": "jane.testcase@mcfixture.invalid"},
    {"JOBKIT_OWNER_NAME": "Yourvale Fixture", "JOBKIT_OWNER_EMAIL": "yourvale@mcfixture.invalid"},
    {"JOBKIT_OWNER_NAME": "Pat Smith [she/her]", "JOBKIT_OWNER_EMAIL": "pat@mcfixture.invalid", "JOBKIT_OWNER_SITE": "https://acmefixture.io"},
]
TEMPLATE = [
    {"JOBKIT_OWNER_NAME": "Your Name", "JOBKIT_OWNER_EMAIL": "you@example.com", "JOBKIT_OWNER_SITE": "yoursite.example",
     "JOBKIT_OWNER_PHONE": "555-0100"},
    {"JOBKIT_OWNER_NAME": "Your Name", "JOBKIT_OWNER_EMAIL": "your.name@example.com", "JOBKIT_OWNER_SITE": "https://yoursite.com",
     "JOBKIT_OWNER_PHONE": "+1 555-0100"},
    {"JOBKIT_OWNER_NAME": "Your Name", "JOBKIT_OWNER_EMAIL": "<you@example.com>", "JOBKIT_OWNER_SITE": "www.example.com",
     "JOBKIT_OWNER_PHONE": "(555) 010-0100"},
    {"JOBKIT_OWNER_NAME": "Jane Doe", "JOBKIT_OWNER_EMAIL": "[YOUR EMAIL ADDRESS]"},
    {"JOBKIT_OWNER_NAME": "John Doe", "JOBKIT_OWNER_EMAIL": "[YOUR EMAIL ADDRESS]"},
]


class OwnerFilterIsWhole(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="b744-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(os.path.join(ROOT, "scripts"), os.path.join(self.tmp, "scripts"), ignore=shutil.ignore_patterns("__pycache__"))
        partner = os.path.join(ROOT, "partner-starter", "scripts")
        if os.path.isdir(partner):
            shutil.copytree(partner, os.path.join(self.tmp, "partner-starter", "scripts"), ignore=shutil.ignore_patterns("__pycache__"))
        for d in (os.path.join(self.tmp, "scripts"), os.path.join(self.tmp, "partner-starter", "scripts")):
            ex, cfg = os.path.join(d, "kit_config.example.py"), os.path.join(d, "kit_config.py")
            if os.path.isdir(d) and os.path.exists(ex) and not os.path.exists(cfg):
                shutil.copy(ex, cfg)

    def _owner(self, env_extra):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR" and not k.startswith("JOBKIT_OWNER_")}
        env.update(env_extra)
        p = subprocess.run([sys.executable, "-c", CHILD, os.path.join(self.tmp, "scripts")], capture_output=True, text=True,
                           env=env, cwd=self.tmp, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr[-1500:])
        return json.loads(p.stdout.strip().splitlines()[-1])

    def test_a_real_owner_who_starts_like_a_template_word_is_kept(self):
        for env in REAL:
            with self.subTest(owner=env["JOBKIT_OWNER_NAME"]):
                owner = self._owner(env)
                self.assertEqual(owner.get("name"), env["JOBKIT_OWNER_NAME"])
                self.assertEqual(owner.get("email"), env["JOBKIT_OWNER_EMAIL"])
                self.assertEqual(owner.get("first"), env["JOBKIT_OWNER_NAME"].split()[0])

    def test_template_values_are_still_skipped(self):
        for env in TEMPLATE:
            with self.subTest(owner=env["JOBKIT_OWNER_NAME"]):
                owner = self._owner(env)
                for kind, key in (("name", "JOBKIT_OWNER_NAME"), ("email", "JOBKIT_OWNER_EMAIL"), ("site", "JOBKIT_OWNER_SITE"),
                                  ("phone", "JOBKIT_OWNER_PHONE")):
                    if key in env:
                        self.assertNotEqual(owner.get(kind), env[key], "%s %r is a template value and must be skipped" % (kind, env[key]))
                self.assertNotIn(owner.get("first"), ("Your", "Jane", "John"), "a template first name must be skipped too")


if __name__ == "__main__":
    unittest.main()
