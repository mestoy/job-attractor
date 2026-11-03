"""A real install of THIS tree must end with the enforcement hooks wired (K2).

⛔ WHY THIS TEST EXISTS BESIDE test_install_sh_hooks.py, WHICH ALREADY PASSES: that test builds
its sandbox by COPYING the shipped example into `.claude/settings.example.json` first. It proves
install.sh wires hooks GIVEN a file the real tree does not put there. The kit ships the example at
the repo ROOT, while install.sh and doctor.py both look under `.claude/`, so on a real install the
wiring block never fires. A test that manufactures the condition it is testing for cannot see that.

HOW IT LOOKED FROM THE OUTSIDE, before the fix, all of it printed by a real run:
  · install.sh never printed "enforcement hooks wired" and still ended on DONE
  · doctor.py said "no settings.example.json found — fix: re-run `bash install.sh .`", which is
    advice that cannot work: the re-run looks in the same place and finds the same nothing
  · README said the hooks "stay main-only" and ship unwired, which read as a design choice rather
    than a path that missed

So this runs the real installer, from the real tree, with nothing placed by hand.
"""
import json
import os
import sys
import shutil
import subprocess
import unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(REPO, "install.sh")
SANDBOX = os.path.join(scratch_root(), "test-install-hooks")
# ⛔ WHERE partner-starter KEEPS IT, AND WHY IT IS NOT UNDER .claude/. backup.sh:146 says
# "partner-starter carries no .claude/ by design", and its kit-sync maps this root file to
# `.claude/settings.example.json` in the shipped kit, which is where install.sh and doctor.py read
# it. So the kit is right and always was; partner-starter is the odd tree on purpose.
#
# I moved this file under .claude/ before reading that line, which would have broken the sync's
# source path. The lesson is the one this suite keeps teaching from the other side: a path that
# looks wrong may be a path with a rule behind it, and the rule lives in the script that ships.
#
# What the test holds instead: wherever the tree keeps it, a REAL install of that tree must end
# with the hooks wired. install.sh and doctor.py now read both locations, so both trees work.
EXAMPLE_CANDIDATES = (os.path.join(".claude", "settings.example.json"), "settings.example.json")


def _example():
    for rel in EXAMPLE_CANDIDATES:
        if os.path.exists(os.path.join(REPO, rel)):
            return rel
    return None


def _scripts(settings):
    """The script basenames a settings blob wires, so the comparison is about BEHAVIOR."""
    out = set()
    for items in (settings.get("hooks") or {}).values():
        for it in items:
            for hk in it.get("hooks", []):
                for tok in str(hk.get("command", "")).split():
                    tok = tok.strip('"').strip("'")
                    if tok.endswith(".py") or tok.endswith(".sh"):
                        out.add(os.path.basename(tok))
    return out


class TestTheExampleIsWhereTheCodeLooks(unittest.TestCase):
    def test_the_tree_ships_a_hook_example_somewhere_the_code_reads(self):
        self.assertIsNotNone(
            _example(),
            "this tree ships no hook example at either %s, so install.sh has nothing to wire the "
            "gates from and the doctor cannot tell a person why every gate is off."
            % " or ".join(EXAMPLE_CANDIDATES))


class TestARealInstallWiresTheHooks(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        self.home = os.path.join(SANDBOX, "home")
        self.target = os.path.join(SANDBOX, "target")
        os.makedirs(self.home)
        os.makedirs(self.target)
        env = dict(os.environ)
        env["HOME"] = self.home
        self.run = subprocess.run(["bash", INSTALL, self.target],
                                  capture_output=True, text=True, env=env, timeout=600)
        self.out = self.run.stdout + self.run.stderr

    def tearDown(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)

    def test_the_install_ran_to_its_end(self):
        """A guard. Nothing below means anything if the installer stopped early."""
        self.assertIn("Checking the install", self.out, self.out[-2000:])

    def test_the_live_settings_file_exists_after_installing(self):
        live = os.path.join(self.target, ".claude", "settings.json")
        self.assertTrue(os.path.exists(live),
                        "a fresh install left no .claude/settings.json, so every gate is off on "
                        "the person's first session. install.sh's own promise is 'every gate is "
                        "on from your first session, nothing to type'.\n" + self.out[-2000:])

    def test_it_wires_the_same_scripts_the_kit_ships(self):
        live = os.path.join(self.target, ".claude", "settings.json")
        if not os.path.exists(live):
            self.skipTest("no settings.json; the test above is the one to read")
        with open(live, encoding="utf-8") as fh:
            got = _scripts(json.load(fh))
        with open(os.path.join(REPO, _example()), encoding="utf-8") as fh:
            want = _scripts(json.load(fh))
        self.assertTrue(want, "the shipped example wires no hooks at all, so this proves nothing")
        self.assertEqual(want, got, "the wired hooks are not the ones the kit ships")

    def test_the_doctor_does_not_report_a_missing_example(self):
        self.assertNotIn("no settings.example.json found", self.out,
                         "the doctor cannot find the example the kit ships, and its fix "
                         "('re-run bash install.sh .') looks in the same place again")


if __name__ == "__main__":
    unittest.main()
