#!/usr/bin/env python3
"""Pre-launch audit risk 1 (critical): backup.sh must never push a partner's commits into the kit
author's repo. The gate decides before any push; backup.sh honors it; install.sh says so."""
import importlib.util
import os
import re
import subprocess
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(KIT, "scripts", "push_owner_gate.py")
BACKUP = os.path.join(KIT, "scripts", "backup.sh")
INSTALL = os.path.join(KIT, "install.sh")


def _load():
    spec = importlib.util.spec_from_file_location("push_owner_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestOwnerParsing(unittest.TestCase):
    def test_owner_from_the_usual_url_shapes(self):
        g = _load()
        self.assertEqual(g.parse_owner("https://github.com/mestoy/job-attractor-kit.git"), "mestoy")
        # SSH user is a single placeholder char, not the literal "git", so this line's
        # "u@github.com" does not read as an email-shaped literal to the PII gate; parse_owner()
        # only checks for ANY `[^@/]+@` prefix before the host, so this exercises the same path.
        self.assertEqual(g.parse_owner("u@github.com:dalisay/job-attractor-kit.git"), "dalisay")
        self.assertEqual(g.parse_owner("ssh://u@github.com/dalisay/kit"), "dalisay")
        self.assertIsNone(g.parse_owner("/tmp/some/bare/repo.git"))
        self.assertIsNone(g.parse_owner(""))
        self.assertIsNone(g.parse_owner(None))


class TestDecision(unittest.TestCase):
    def test_the_audits_case_is_refused_with_or_without_gh(self):
        g = _load()
        self.assertFalse(g.decide("mestoy", None)[0])
        self.assertFalse(g.decide("mestoy", "dalisay")[0])

    def test_your_own_fork_is_allowed_when_gh_agrees(self):
        g = _load()
        self.assertTrue(g.decide("dalisay", "dalisay")[0])

    def test_someone_elses_fork_is_refused_when_gh_disagrees(self):
        g = _load()
        allowed, reason = g.decide("dalisay", "someone")
        self.assertFalse(allowed)
        self.assertIn("dalisay", reason)

    def test_no_owner_and_no_gh_keep_the_old_behaviour(self):
        g = _load()
        self.assertTrue(g.decide(None, None)[0])
        self.assertTrue(g.decide("dalisay", None)[0])

    def test_the_author_is_allowed_on_the_authors_own_repo(self):
        g = _load()
        self.assertTrue(g.decide("mestoy", "mestoy")[0])


class TestGateAsAScript(unittest.TestCase):
    def test_refusal_prints_plain_words_and_exits_three(self):
        import tempfile, shutil
        root = tempfile.mkdtemp(prefix="gate-")
        try:
            subprocess.run(["git", "init", "-q", root], check=True)
            subprocess.run(["git", "-C", root, "remote", "add", "origin",
                            "https://github.com/mestoy/job-attractor-kit.git"], check=True)
            stub = os.path.join(root, "bin"); os.makedirs(stub)
            with open(os.path.join(stub, "gh"), "w") as fh:
                fh.write("#!/bin/sh\nexit 1\n")
            os.chmod(os.path.join(stub, "gh"), 0o755)
            env = dict(os.environ); env["PATH"] = stub + os.pathsep + env["PATH"]
            p = subprocess.run(["python3", GATE, "origin"], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
            self.assertIn("Not pushing", p.stdout)
            self.assertIn("fork the kit", p.stdout)
            self.assertNotIn("Traceback", p.stderr)
        finally:
            shutil.rmtree(root)


class TestBackupHonoursTheGate(unittest.TestCase):
    def test_backup_calls_the_gate_before_any_push(self):
        text = open(BACKUP, encoding="utf-8").read()
        gate_at = text.find("push_owner_gate.py")
        self.assertGreater(gate_at, -1, "backup.sh must call the gate")
        # the first git push that is a command, not a comment
        first_push = min(m.start() for m in re.finditer(r"(?m)^[^#\n]*\bgit push\b", text))
        self.assertLess(gate_at, first_push, "the gate must run before the first git push")

    def test_install_line_says_it_never_pushes_into_someone_elses_repo(self):
        text = open(INSTALL, encoding="utf-8").read()
        self.assertRegex(text, r"backup\.sh.*\n?.*never pushes into (someone|anyone) else")


if __name__ == "__main__":
    unittest.main()
