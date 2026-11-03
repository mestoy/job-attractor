#!/usr/bin/env python3
"""Pre-launch audit F10: no python3 or git gate and no minimum version. install.sh must name what
it needs up front, in plain words, and stop before doing anything when python3 is older than 3.9
or git is missing; README's "What you need first" says the same."""
import os
import _roots
import shutil
import subprocess
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(KIT, "install.sh")
README = os.path.join(KIT, "README.md")


def _run_with_stub_python(version_line):
    root = tempfile.mkdtemp(prefix="kit-prereq-")
    try:
        shutil.copy(INSTALL, os.path.join(root, "install.sh"))
        stub = os.path.join(root, "bin"); os.makedirs(stub)
        with open(os.path.join(stub, "python3"), "w") as fh:
            fh.write("#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo \"%s\"; exit 0; fi\nexit 0\n" % version_line)
        os.chmod(os.path.join(stub, "python3"), 0o755)
        env = dict(os.environ); env["PATH"] = stub + os.pathsep + env["PATH"]; _roots.point_env(env, root)
        p = subprocess.run(["bash", "install.sh", "."], cwd=root, env=env, capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout + p.stderr, root
    finally:
        shutil.rmtree(root, True)


class TestInstallNamesItsPrerequisites(unittest.TestCase):
    def test_old_python_stops_the_install_in_plain_words(self):
        code, out, _ = _run_with_stub_python("Python 3.7.9")
        self.assertNotEqual(code, 0, out[-800:])
        self.assertIn("3.9 or newer", out)
        self.assertNotIn("DONE", out)

    def test_readme_names_python_and_git_up_front(self):
        text = open(README, encoding="utf-8").read()
        section = text.split("## What you need first", 1)[1].split("\n## ", 1)[0]
        self.assertIn("python3", section)
        self.assertIn("3.9", section)
        self.assertIn("git", section)
        self.assertIn("Claude Code", section)


if __name__ == "__main__":
    unittest.main()
