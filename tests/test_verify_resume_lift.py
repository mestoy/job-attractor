"""Slice I commit 1: banned_hits and role_imply_hits are lifted out of verify_resume.check().

unittest shape (the kit runner is `unittest discover`). All names and lists below are
obviously fake test data.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import verify_resume as vr  # noqa: E402


class BannedHits(unittest.TestCase):
    def setUp(self):
        self._b, self._d = vr.BANNED, vr._LISTS_DEGRADED
        vr.BANNED, vr._LISTS_DEGRADED = ["leverage", "delve"], ""

    def tearDown(self):
        vr.BANNED, vr._LISTS_DEGRADED = self._b, self._d

    def test_clean_line(self):
        self.assertEqual(vr.banned_hits("Shipped the fake dashboard."), ([], False))

    def test_one_banned_word(self):
        self.assertEqual(vr.banned_hits("We LEVERAGE the fake stack."), (["leverage"], False))

    def test_substring_is_not_a_hit(self):
        self.assertEqual(vr.banned_hits("Leveraged and delved."), ([], False))

    def test_degraded_flag_is_reported(self):
        vr._LISTS_DEGRADED = "fake degraded"
        self.assertEqual(vr.banned_hits("clean"), ([], True))
        self.assertEqual(vr.banned_hits("delve"), (["delve"], True))


class RoleImplyHits(unittest.TestCase):
    def setUp(self):
        self._r = vr.ROLE_IMPLY
        vr.ROLE_IMPLY = [r"software engineer at"]

    def tearDown(self):
        vr.ROLE_IMPLY = self._r

    def test_clean(self):
        self.assertEqual(vr.role_imply_hits("Product manager at Fake Co"), [])

    def test_planted(self):
        self.assertEqual(vr.role_imply_hits("Software Engineer at Fake Co"), [r"software engineer at"])

    def test_empty_list_gives_empty(self):
        vr.ROLE_IMPLY = []
        self.assertEqual(vr.role_imply_hits("software engineer at"), [])


if __name__ == "__main__":
    unittest.main()
