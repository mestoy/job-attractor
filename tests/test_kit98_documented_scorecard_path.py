"""kit#98 (a partner): the writer existed and could not be found where the rules said to look.

He grepped scripts/ for `documents/state/scorecards` and found no writer, so he filed that the
step rested on agent discipline rather than a script. He was right to: render_scorecard.py wrote
to a `scorecards` folder beside whatever it was handed, never to the documented path.

HIS GREP IS THE FIRST TEST. It fails before the change and passes after.
"""
import os
import subprocess
import sys
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(REPO, "scripts", "render_scorecard.py")
sys.path.insert(0, os.path.join(REPO, "scripts"))
import render_scorecard as rs  # noqa: E402


class TestHisGrepFindsAWriter(unittest.TestCase):
    def test_his_grep_finds_the_renderer(self):
        """The check he ran. Before the change it returned nothing for this file."""
        r = subprocess.run(["grep", "-rn", "documents/state/scorecards", SCRIPT],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0,
                         "grep for the documented path must find render_scorecard.py")

    def test_the_path_constant_is_the_documented_one(self):
        self.assertEqual(rs.DOCUMENTED_CARDS_DIR,
                         os.path.join("documents", "state", "scorecards"))


class TestTheDefaultIsTheDocumentedPath(unittest.TestCase):
    def _repo(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "scripts"))
        os.makedirs(os.path.join(root, "cards"))
        # _repo_root_for looks for scripts/kit_config.py, so a bare one marks the root.
        with open(os.path.join(root, "scripts", "kit_config.py"), "w") as fh:
            fh.write("OWNER_SITE = ''\n")
        card = os.path.join(root, "cards", "x-card-2026-09-20.md")
        with open(card, "w") as fh:
            fh.write("# x\n")
        return root, card

    def test_a_card_inside_an_install_lands_in_the_documented_path(self):
        root, card = self._repo()
        self.assertEqual(rs.default_out_dir(card),
                         os.path.join(root, "documents", "state", "scorecards"))

    def test_a_card_outside_any_install_still_lands_beside_itself(self):
        """The old behavior survives where there is no repo, so nothing fails on a loose card."""
        loose = tempfile.mkdtemp(dir=os.path.dirname(REPO))   # outside this checkout: run_all.sh puts TMPDIR inside it, and a card there finds this install
        self.addCleanup(shutil.rmtree, loose, True)
        card = os.path.join(loose, "y-card-2026-09-20.md")
        with open(card, "w") as fh:
            fh.write("# y\n")
        self.assertEqual(rs.default_out_dir(card), os.path.join(loose, "scorecards"))

    def test_help_says_where_the_default_is(self):
        r = subprocess.run([sys.executable, SCRIPT, "--help"],
                           capture_output=True, text=True, cwd=REPO)
        out = r.stdout + r.stderr
        self.assertIn("documents/state/scorecards", out,
                      "--help must say where cards land now, since the default moved")


if __name__ == "__main__":
    unittest.main()


class TestTheMovedDefaultIsAnnounced(unittest.TestCase):
    """kit#98: a default that changes under an existing install must say so, or a person's cards
    move and they find out later."""

    def test_the_default_path_announces_itself(self):
        out = []
        rs.announce_default("/repo/documents/state/scorecards", used_out_flag=False)
        # captured by pytest; assert the source carries both halves rather than the stream
        src = open(SCRIPT, encoding="utf-8").read()
        self.assertIn("the default moved to the documented path", src)
        self.assertIn("pass --out to choose another", src)

    def test_an_explicit_out_says_nothing(self):
        """A person who chose the directory does not need to be told the default moved."""
        import io as _io
        import contextlib
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rs.announce_default("/anywhere", used_out_flag=True)
        self.assertEqual(buf.getvalue(), "")

    def test_the_default_case_does_print(self):
        import io as _io
        import contextlib
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rs.announce_default("/repo/documents/state/scorecards", used_out_flag=False)
        self.assertIn("/repo/documents/state/scorecards", buf.getvalue())
        self.assertIn("default moved", buf.getvalue())
