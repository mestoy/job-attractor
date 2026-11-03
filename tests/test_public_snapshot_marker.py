"""The public CLI copy carries a .public-snapshot marker (scripts/publish-public.sh in the AJS repo writes it). With it, doctor.py skips the
app check with one line instead of blocking on a missing app, and install.sh ends on the CLI next steps. Fixture dirs only."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = "/home/vscode/render" if os.path.isdir("/home/vscode/render") else None


def doctor_section(marker, head="[8] the app", nxt="[9]"):
    d = tempfile.mkdtemp(prefix="pubmark-", dir=SCRATCH)
    try:
        if marker:
            open(os.path.join(d, ".public-snapshot"), "w").write("0" * 40 + "\n")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=d)
        out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "doctor.py")], capture_output=True, text=True,
                             env=env, cwd=d, timeout=120).stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)
    a = out.index(head)
    return out[a:out.index(nxt, a)]


def doctor_app_section(marker):
    return doctor_section(marker)


class Marker(unittest.TestCase):
    def test_with_the_marker_doctor_skips_the_app_check_with_one_line(self):
        sec = doctor_app_section(True)
        self.assertIn("public CLI copy: the app is not part of this install", sec)
        self.assertNotIn("cannot be built", sec)

    def test_without_the_marker_a_missing_app_still_blocks(self):
        sec = doctor_app_section(False)
        self.assertIn("the app cannot be built here", sec)

    def test_with_the_marker_staying_current_says_reclone_and_names_no_private_repo(self):
        sec = doctor_section(True, "[7] staying current", "[8]")
        self.assertIn("reclone", sec)
        self.assertNotIn("job-attractor-kit", sec)

    def test_install_sh_parses_and_names_the_cli_steps_behind_the_marker(self):
        self.assertEqual(subprocess.run(["bash", "-n", os.path.join(ROOT, "install.sh")]).returncode, 0)
        s = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
        branch = s[s.index('if [ -f "$HERE/.public-snapshot" ]'):]
        branch = branch[:branch.index("\nelse\n")]
        self.assertIn("/setup", branch)
        self.assertNotRegex(branch, r"/app\b")


if __name__ == "__main__":
    unittest.main()
