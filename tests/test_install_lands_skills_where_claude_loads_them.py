"""Installing must leave the kit's skills where Claude Code actually loads them (K2).

⛔ THE THIRD FOLDER-NAME GAP IN THE SAME INSTALLER, after the hook example and the doc templates.
Claude Code loads `.claude/skills/<name>/SKILL.md`. The shipped kit carries them in exactly that
shape. The tree they are maintained in carries them FLAT, as `skills/<name>.md`, and backup.sh
does the conversion on the way out:

    _kitsync "skills/$_sk.md"   ".claude/skills/$_sk/SKILL.md"

install.sh copies the tree across wholesale and never does that conversion. So an install from the
source tree lands 23 skills in a folder Claude Code does not read. Nothing reports it. The gates
are wired, the templates are seeded, the doctor is happy, and `/apply`, `/matrix-hunt` and the
house style simply are not there.

⚖️ Copy-if-absent, like every other seed in this installer: a skill already in `.claude/skills/`
is left exactly as it is, because that is the person's own copy or a newer one.
"""
import os
import sys
import shutil
import subprocess
import unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX = os.path.join(scratch_root(), "test-install-skills")
LOADED = os.path.join(".claude", "skills")


def _flat_skills():
    d = os.path.join(REPO, "skills")
    if not os.path.isdir(d):
        return []
    return sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md"))


def _nested_skills(root):
    d = os.path.join(root, LOADED)
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d)
                  if os.path.exists(os.path.join(d, n, "SKILL.md")))


class TestSkillsReachTheLoadedPath(unittest.TestCase):
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

    def test_this_tree_carries_skills_at_all(self):
        """A control. With no skills in the tree, an empty .claude/skills/ is correct and the
        assertion below would be blaming the installer for an empty folder."""
        self.assertTrue(_flat_skills() or _nested_skills(REPO),
                        "this tree carries no skills in either shape, so nothing can be checked")

    def test_the_install_ran_to_its_end(self):
        self.assertIn("Checking the install", self.out, self.out[-1500:])

    def test_every_skill_this_tree_carries_is_loadable_after_installing(self):
        want = set(_flat_skills()) | set(_nested_skills(REPO))
        got = set(_nested_skills(self.target))
        missing = sorted(want - got)
        self.assertEqual(
            [], missing,
            "%d skill(s) did not reach %s/<name>/SKILL.md, which is the only place Claude Code "
            "reads them: %s\n%s"
            % (len(missing), LOADED, ", ".join(missing[:8]), self.out[-1200:]))


if __name__ == "__main__":
    unittest.main()
