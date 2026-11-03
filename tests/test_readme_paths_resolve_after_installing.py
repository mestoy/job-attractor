"""Every relative path the shipping docs point at must exist on a real install (K2).

⛔ WHY IT IS CHECKED AFTER INSTALLING, not against the repo: half these paths are things the
installer CREATES — documents/, .claude/settings.json, the seeded templates. Checking the source
tree produces a long list of failures that are not failures, and a list like that gets ignored,
which is worse than no check.

⛔ AND WHY ONLY TOKENS CONTAINING A SLASH: the docs also backtick bare script names in table
cells, `doctor.py` and `check_dup.py` and a dozen more, meaning "the script called that". Those
are names, not paths. Treating them as paths is how a check becomes noise.

WHAT IT CAUGHT when it was written: the README sent a new person to `partner-docs/HANDOFF.md` and
`partner-docs/HOW-WE-WORK.md`. After installing, those files are in `documents/`. The folder named
exists only in the shipped kit, so a reader following that line found nothing where they looked.

The allowlist is short and every entry says why. An entry there is a promise that the path is
absent ON PURPOSE, not a way to make a red test green.
"""
import os
import sys
import re
import shutil
import subprocess
import unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX = os.path.join(scratch_root(), "test-doc-paths")
DOCS = ("README.md", "QUICKSTART.md")

TOKEN = re.compile(r"`([^`\n]+)`")

ALLOWED = {
    # Written the first time a scorecard is rendered, so a fresh install has none.
    "documents/state/scorecards/INDEX.md":
        "created by render_scorecard.py on first use, not shipped",
    # The kit's name for the template layer. The source tree calls it docs/ and install.sh seeds
    # from either, so the person's copies land in documents/ under both names.
    "partner-docs/":
        "the shipped kit's name for the template folder; the installed copies live in documents/",
}


def _candidates(text):
    """Backticked tokens that are really relative paths: a slash, no spaces, no placeholder."""
    out = []
    for m in TOKEN.finditer(text):
        t = m.group(1).strip()
        if " " in t or t.startswith("/") or "://" in t or "<" in t or "*" in t:
            continue
        if "/" not in t:
            continue
        out.append(t)
    return out


class TestDocPathsResolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        cls.home = os.path.join(SANDBOX, "home")
        cls.target = os.path.join(SANDBOX, "target")
        os.makedirs(cls.home)
        os.makedirs(cls.target)
        env = dict(os.environ)
        env["HOME"] = cls.home
        cls.proc = subprocess.run(["bash", os.path.join(REPO, "install.sh"), cls.target],
                                 capture_output=True, text=True, env=env, timeout=600)
        cls.out = cls.proc.stdout + cls.proc.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(SANDBOX, ignore_errors=True)

    def test_the_install_ran_to_its_end(self):
        self.assertIn("Checking the install", self.out, self.out[-1500:])

    def test_there_are_paths_to_check(self):
        """A control. An empty candidate list passes every assertion below without looking at
        anything, which is the failure this suite keeps finding elsewhere."""
        total = 0
        for doc in DOCS:
            with open(os.path.join(self.target, doc), encoding="utf-8") as fh:
                total += len(_candidates(fh.read()))
        self.assertGreater(total, 5, "found almost no paths to check; the pattern has stopped "
                                     "matching and this test is now decoration")

    def test_every_allowlisted_path_carries_a_reason(self):
        for path, why in ALLOWED.items():
            self.assertTrue(why and len(why) > 20,
                            "%s is allowlisted without a real reason" % path)

    def test_every_path_resolves_on_a_real_install(self):
        broken = {}
        for doc in DOCS:
            with open(os.path.join(self.target, doc), encoding="utf-8") as fh:
                for t in _candidates(fh.read()):
                    if t in ALLOWED:
                        continue
                    if not os.path.exists(os.path.join(self.target, t.rstrip("/"))):
                        broken.setdefault(doc, []).append(t)
        self.assertEqual(
            {}, broken,
            "the shipping docs point at paths that do not exist after installing. Either fix the "
            "pointer, make the installer create the file, or allowlist it WITH A REASON:\n%s"
            % "\n".join("  %s -> %s" % (d, ", ".join(sorted(set(v)))) for d, v in broken.items()))


if __name__ == "__main__":
    unittest.main()
