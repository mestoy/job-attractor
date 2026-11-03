#!/usr/bin/env python3
"""BUG-212 (kit #81): optional skills are OPT-IN, never enabled by a default install.

The kit ships three code-discipline skills (add-a-feature-safely, investigate-a-bug-first,
pre-launch-audit) under `optional-skills/<name>/SKILL.md`, a folder Claude Code does not load.
install.sh copies a skill into `.claude/skills/<name>/SKILL.md` ONLY when its name is listed in
`KIT_OPTIONAL_SKILLS` in scripts/kit_config.py. Two contracts, both in a throwaway sandbox:
  1. a default install (the shipped example config, empty list) enables NONE of them;
  2. an install whose kit_config.py lists one name enables that one and only that one.
"""
import os
import _roots
import shutil
import subprocess
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(KIT, "install.sh")
OPTIONAL = ("add-a-feature-safely", "investigate-a-bug-first", "pre-launch-audit")


# ⛔ install.sh NOW ENDS BY RUNNING doctor.py AND EXITING ON ITS VERDICT (K3, 114d2072). These
# sandboxes copy install.sh ALONE, so the kit they build has no scripts/ and no doctor, and the
# install correctly refuses. Asserting returncode 0 here would assert the OLD contract, in which
# the run ended on DONE whatever the checker would have said. What these tests are about is the
# seeding and the optional-skills wiring, so what they need is that the installer ran all the way
# through to its final step.
def _reached_the_end(case, p):
    out = p.stdout + p.stderr
    case.assertIn("Checking the install", out,
                  "install.sh did not reach its final step:\n" + out[-1500:])


def _run(cwd):
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    _roots.point_env(env, cwd)
    return subprocess.run(["bash", "install.sh", "."], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


class TestOptionalSkills(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit-optskills-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copy(INSTALL, os.path.join(self.tmp, "install.sh"))
        pd = os.path.join(self.tmp, "partner-docs")
        os.makedirs(pd)
        with open(os.path.join(pd, "PROFILE.md"), "w") as fh:
            fh.write("# PROFILE\n")
        for name in OPTIONAL:
            d = os.path.join(self.tmp, "optional-skills", name)
            os.makedirs(d)
            with open(os.path.join(d, "SKILL.md"), "w") as fh:
                fh.write(f"---\nname: {name}\n---\n# {name}\n")
        os.makedirs(os.path.join(self.tmp, "scripts"))
        with open(os.path.join(self.tmp, "scripts", "kit_config.example.py"), "w") as fh:
            fh.write("KIT_OPTIONAL_SKILLS = []\n")

    def _enabled(self):
        return {n for n in OPTIONAL
                if os.path.isfile(os.path.join(self.tmp, ".claude", "skills", n, "SKILL.md"))}

    def test_default_install_enables_none(self):
        p = _run(self.tmp)
        out = p.stdout + p.stderr
        _reached_the_end(self, p)
        self.assertEqual(self._enabled(), set(), out[-1500:])
        self.assertIn("KIT_OPTIONAL_SKILLS", out, "the install must say how to opt in")

    def test_opted_in_install_enables_exactly_the_listed_one(self):
        with open(os.path.join(self.tmp, "scripts", "kit_config.py"), "w") as fh:
            fh.write('KIT_OPTIONAL_SKILLS = ["pre-launch-audit"]\n')
        p = _run(self.tmp)
        out = p.stdout + p.stderr
        _reached_the_end(self, p)
        self.assertEqual(self._enabled(), {"pre-launch-audit"}, out[-1500:])
        self.assertIn("pre-launch-audit", out)

    def test_unknown_name_is_named_not_silent(self):
        with open(os.path.join(self.tmp, "scripts", "kit_config.py"), "w") as fh:
            fh.write('KIT_OPTIONAL_SKILLS = ["no-such-skill"]\n')
        p = _run(self.tmp)
        out = p.stdout + p.stderr
        _reached_the_end(self, p)
        self.assertEqual(self._enabled(), set())
        self.assertIn("no-such-skill", out, "an unknown opt-in must be named in the output")


if __name__ == "__main__":
    unittest.main()
