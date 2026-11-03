"""Installing from a tree that keeps its templates in `docs/` must still seed `documents/` (K2).

⛔ WHAT HAPPENS WITHOUT THIS: install.sh seeds only from `partner-docs/`. partner-starter does not
have that folder — its template layer is `docs/`, which backup.sh reads and ships to the kit AS
partner-docs/. So an install from partner-starter's own tree prints

    [!] SEEDING SKIPPED: .../partner-docs/ is missing (or holds no .md), and no kit remote

and copies nothing, and then the doctor reports PROFILE.md missing, the criteria matrix missing,
segments missing and writing-samples missing — four blocking or degrading items, all of which the
tree was carrying the whole time under a different folder name.

The skip message is honest and loud, which is why this is a gap rather than a silent failure. But
telling somebody to fetch from a remote what is already on their disk is not the right answer.

Copy-if-absent, like every other seed here: a file already in documents/ is kept as theirs.
"""
import os
import sys
import shutil
import subprocess
import unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX = os.path.join(scratch_root(), "test-install-seeding")
# Named individually: these are the four the doctor calls for by name.
WANTED = ("PROFILE.md", "employer-criteria-matrix.md", "segments.md", "writing-samples.md")


def _templates():
    """The template folder this tree actually carries, and what is in it."""
    for name in ("partner-docs", "docs"):
        d = os.path.join(REPO, name)
        if os.path.isdir(d):
            md = [f for f in os.listdir(d) if f.endswith(".md")]
            if md:
                return name, sorted(md)
    return None, []


class TestSeedingFindsThisTreesTemplates(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        self.home = os.path.join(SANDBOX, "home")
        self.target = os.path.join(SANDBOX, "target")
        os.makedirs(self.home)
        os.makedirs(self.target)
        env = dict(os.environ)
        env["HOME"] = self.home
        self.run = subprocess.run(["bash", os.path.join(REPO, "install.sh"), self.target],
                                  capture_output=True, text=True, env=env, timeout=600)
        self.out = self.run.stdout + self.run.stderr

    def tearDown(self):
        shutil.rmtree(SANDBOX, ignore_errors=True)

    def test_this_tree_carries_templates_at_all(self):
        """A control. With no templates anywhere, 'nothing was seeded' is the correct outcome and
        the assertions below would be blaming the installer for an empty folder."""
        name, md = _templates()
        self.assertIsNotNone(name, "this tree carries no template folder, so nothing can be seeded")
        self.assertTrue(md, "the template folder %s holds no .md files" % name)

    def test_the_install_ran_to_its_end(self):
        self.assertIn("Checking the install", self.out, self.out[-1500:])

    def test_it_did_not_report_seeding_skipped(self):
        self.assertNotIn("SEEDING SKIPPED", self.out,
                         "install.sh skipped seeding while this tree carries its templates in "
                         "%s/\n%s" % (_templates()[0], self.out[-1500:]))

    def test_the_files_the_doctor_asks_for_are_there(self):
        _name, md = _templates()
        missing = [w for w in WANTED
                   if w in md and not os.path.exists(os.path.join(self.target, "documents", w))]
        self.assertEqual([], missing,
                         "these templates are in this tree and did not reach documents/: %s"
                         % ", ".join(missing))


if __name__ == "__main__":
    unittest.main()
