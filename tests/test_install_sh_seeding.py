"""BUG-045 (kit #60): install.sh's seeding step must never no-op in silence.

A partner ran `bash install.sh .` from a checkout with no partner-docs/ folder. The seeding loop is
`for f in "$HERE"/partner-docs/*.md`, which iterates zero times when the folder is gone, so the run
printed `DONE.` and a list of installed CLIs while employer-criteria-matrix.md and segments.md were
never written. doctor.py then told him to run install.sh again: a loop with no exit.

The contract these tests hold:
  1. no partner-docs/ and no git history to fall back on: say SEEDING SKIPPED loudly, name the
     files that stay absent, name a next step that works without the folder, and exit non-zero;
  2. partner-docs/ present: report what was seeded and exit 0 (and a tree with no .agents/skills/
     must not die on the portal enumeration, which is what the first sandbox run hit);
  3. partner-docs/ gone from the WORKING TREE but present on the kit remote's main: seed from git
     history and say so, because the fix that resolved it by hand was exactly `git show`.
Every run happens in a throwaway sandbox; the real tree is never the target.
"""
import os
import _roots
import shutil
import subprocess
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(KIT, "install.sh")
GIT_ID = ["-c", "user.email=t@example.com", "-c", "user.name=t"]


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


class TestInstallSeeding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit-install-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copy(INSTALL, os.path.join(self.tmp, "install.sh"))

    def test_missing_partner_docs_is_loud_named_and_non_zero(self):
        p = _run(self.tmp)
        out = p.stdout + p.stderr
        self.assertIn("SEEDING SKIPPED", out, out[-1500:])
        self.assertIn("partner-docs", out)
        self.assertIn("git show", out, "the next step must work without the folder")
        self.assertNotEqual(p.returncode, 0, "a skipped seed must not exit 0:\n" + out[-1500:])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "documents", "PROFILE.md")))
        # the skip is repeated where the eye lands, after DONE, not only mid-scroll
        self.assertIn("SEEDING SKIPPED", out.split("DONE")[-1])

    def test_present_partner_docs_reports_the_count_and_exits_zero(self):
        pd = os.path.join(self.tmp, "partner-docs")
        os.makedirs(pd)
        for name in ("PROFILE.md", "segments.md"):
            with open(os.path.join(pd, name), "w") as fh:
                fh.write(f"# {name}\n")
        with open(os.path.join(self.tmp, "documents", "segments.md") if os.path.isdir(
                os.path.join(self.tmp, "documents")) else os.devnull, "w"):
            pass
        p = _run(self.tmp)
        out = p.stdout + p.stderr
        _reached_the_end(self, p)
        self.assertNotIn("SEEDING SKIPPED", out)
        self.assertRegex(out, r"seeded 2 ")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "documents", "PROFILE.md")))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "documents", "segments.md")))

    def test_missing_folder_falls_back_to_the_kit_remotes_history(self):
        # a bare "kit" whose main carries partner-docs/, and a clone that lost the folder
        bare = os.path.join(self.tmp, "job-attractor-kit.git")
        src = os.path.join(self.tmp, "src")
        os.makedirs(os.path.join(src, "partner-docs"))
        with open(os.path.join(src, "partner-docs", "PROFILE.md"), "w") as fh:
            fh.write("# profile from history\n")
        subprocess.run(["git", "init", "-q", "-b", "main", src], check=True)
        subprocess.run(["git", "-C", src, "add", "."], check=True)
        subprocess.run(["git", "-C", src, *GIT_ID, "commit", "-q", "-m", "seed"], check=True)
        subprocess.run(["git", "clone", "-q", "--bare", src, bare], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.tmp], check=True)
        subprocess.run(["git", "-C", self.tmp, "remote", "add", "kit", bare], check=True)
        subprocess.run(["git", "-C", self.tmp, "fetch", "-q", "kit"], check=True)
        self.assertFalse(os.path.isdir(os.path.join(self.tmp, "partner-docs")))
        p = _run(self.tmp)
        out = p.stdout + p.stderr
        _reached_the_end(self, p)
        self.assertNotIn("SEEDING SKIPPED", out)
        self.assertIn("kit/main", out, "must say the seed came from git history")
        with open(os.path.join(self.tmp, "documents", "PROFILE.md")) as fh:
            self.assertEqual(fh.read(), "# profile from history\n")


if __name__ == "__main__":
    unittest.main()
