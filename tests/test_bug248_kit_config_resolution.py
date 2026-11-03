"""BUG-248: `render_scorecard.py` resolved `kit_config` relative to its OWN directory
(`sys.path.insert(0, HERE)` + a bare `import kit_config`), never relative to `REPO` (the
project whose docs are actually being rendered). Every other script in this codebase is
always invoked in place, next to the matching `kit_config.py`, so this was invisible
everywhere else — this script is the one asked to run cross-directory (rendering a project
that carries no copy of this script itself), and doing so silently loaded the wrong,
empty-default config with no error.

Fixtures are fictional two-directory setups (never a real company or path from the private
repo, per the PII rule this test suite runs under).
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))

import render_scorecard as rs  # noqa: E402


class Bug248KitConfigResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bug248-")
        self.project_dir = os.path.join(self.tmp, "project")
        self.project_scripts = os.path.join(self.project_dir, "scripts")
        self.script_dir = os.path.join(self.tmp, "script")
        os.makedirs(self.project_scripts)
        os.makedirs(self.script_dir)
        self._orig_repo, self._orig_here = rs.REPO, rs.HERE

    def tearDown(self):
        rs.REPO, rs.HERE = self._orig_repo, self._orig_here
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, value):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"SCORECARD_SURFACED_VERDICTS = {value!r}\n")

    def test_a_repos_own_kit_config_wins_over_the_script_directorys(self):
        self._write(os.path.join(self.project_scripts, "kit_config.py"), ["ONLY_THIS"])
        self._write(os.path.join(self.script_dir, "kit_config.py"), ["WRONG_ONE"])
        rs.REPO, rs.HERE = self.project_dir, self.script_dir
        mod, path = rs._resolve_kit_config()
        self.assertEqual(mod.SCORECARD_SURFACED_VERDICTS, ["ONLY_THIS"])
        self.assertEqual(path, os.path.join(self.project_scripts, "kit_config.py"))

    def test_b_falls_back_to_the_script_directorys_own_kit_config_when_repo_has_none(self):
        self._write(os.path.join(self.script_dir, "kit_config.py"), ["SHIPPED_EXAMPLE"])
        rs.REPO, rs.HERE = self.project_dir, self.script_dir
        mod, path = rs._resolve_kit_config()
        self.assertEqual(mod.SCORECARD_SURFACED_VERDICTS, ["SHIPPED_EXAMPLE"])
        self.assertEqual(path, os.path.join(self.script_dir, "kit_config.py"))

    def test_c_neither_directory_has_one_returns_none_none(self):
        rs.REPO, rs.HERE = self.project_dir, self.script_dir
        mod, path = rs._resolve_kit_config()
        self.assertIsNone(mod)
        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
