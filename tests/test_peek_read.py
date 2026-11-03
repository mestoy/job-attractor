#!/usr/bin/env python3
"""Slice B: the Glassdoor and LinkedIn paste is read and scored by the CLI's own functions (rank_applications.culture_score, size_adjustment,
instability_assessment, and the culture peek's 6-month leadership tripwire). All text here is invented.
Run: PYTHONSAFEPATH=1 PYTHONPATH=. python3 -m unittest tests.test_peek_read
"""
import datetime
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))
import _fake_repo_sB as R  # noqa: E402
import peek_read  # noqa: E402
import rank_applications as ra  # noqa: E402

TODAY = datetime.date(2026, 10, 13)

GOOD = """FAKE-GD Co (NOT REAL) Reviews
4.2 ★ overall rating
1,250 reviews

Great place to work
Sep 2, 2026
5.0 ★ Supportive team and clear product direction.
"""

TRIPWIRE = """FAKE-GD Co (NOT REAL)
3.4 ★ rating, 800 reviews

Current employee, Aug 20, 2026
1.0 ★ FAKE-REVIEW-TEXT: the fake leadership team changes the fake plan every fake week.

Older note
Jan 5, 2025
2.0 ★ Poor management and a toxic culture.
"""

OLD_NEGATIVE = """4.0 ★ rating, 600 reviews

Former employee, Mar 3, 2025
1.0 ★ Poor leadership and no vision.
"""

THIN = "FAKE-GD Co\n4.9 ★ rating\n6 reviews\n"

LI_OK = "FAKE-LI Co (NOT REAL)\nSoftware Development · 51-200 employees\n120 on LinkedIn\n"
LI_SMALL = "FAKE-LI Co\nSoftware Development · 11-50 employees\n"
LI_VETO = "FAKE-LI Games\nOnline Gambling · 201-500 employees\n"
LI_LAYOFF = "FAKE-LI Co\nSoftware Development · 51-200 employees\nThe company announced layoffs this spring.\n"


class Glassdoor(unittest.TestCase):
    def test_a_good_paste_is_scored_by_culture_score(self):
        out = peek_read.read("glassdoor", GOOD, today=TODAY)
        self.assertEqual(out["state"], "clear")
        want, low, _t = ra.culture_score(glassdoor={"score": 4.2, "reviews": 1250})
        self.assertEqual(out["facts"]["culture_score"], round(want, 1))
        self.assertFalse(out["facts"]["low_confidence"])
        self.assertIn("4.2", out["reason"])
        self.assertIn("1,250", out["reason"])

    def test_a_thin_paste_is_marked_low_confidence_not_bad(self):
        out = peek_read.read("glassdoor", THIN, today=TODAY)
        self.assertTrue(out["facts"]["low_confidence"])
        self.assertEqual(out["state"], "clear")
        self.assertIn("thin evidence", out["reason"])

    def test_a_fresh_negative_review_naming_leadership_stops_the_screen(self):
        out = peek_read.read("glassdoor", TRIPWIRE, today=TODAY)
        self.assertEqual(out["state"], "blocked")
        self.assertIn("Stopped by the culture peek", out["reason"])
        self.assertEqual(out["facts"]["newest_negative_leadership"], "2026-08-20")

    def test_an_old_negative_review_does_not_stop_it(self):
        out = peek_read.read("glassdoor", OLD_NEGATIVE, today=TODAY)
        self.assertNotEqual(out["state"], "blocked")
        self.assertIn("older than 6 months", out["reason"])

    def test_a_paste_with_nothing_readable_scores_nothing_and_says_when(self):
        out = peek_read.read("glassdoor", "hello there, nothing useful", today=TODAY)
        self.assertEqual(out["state"], "unknown")
        self.assertTrue(out["known"])
        self.assertNotIn("culture_score", out["facts"])


class Mutations(unittest.TestCase):
    """Each of these fails if one condition in peek_read.py is dropped or flipped (the tripwire's "names leadership", the instability verdict)."""
    NOT_LEADERSHIP = "4.0 \u2605 rating, 600 reviews\n\nCurrent employee, Oct 1, 2026\n1.0 \u2605 FAKE-REVIEW-TEXT: the fake parking lot is bad and the fake coffee is poor.\n"
    LAYOFFS = "4.0 \u2605 rating, 600 reviews\n\nFAKE-REVIEW-TEXT: the fake company announced layoffs and a reorg this spring.\n"

    def test_a_fresh_negative_review_that_does_not_name_leadership_does_not_stop_it(self):
        out = peek_read.read("glassdoor", self.NOT_LEADERSHIP, today=TODAY)
        self.assertNotEqual(out["state"], "blocked")
        self.assertNotIn("newest_negative_leadership", out["facts"])

    def test_an_instability_mention_is_never_a_clear(self):
        out = peek_read.read("glassdoor", self.LAYOFFS, today=TODAY)
        self.assertEqual(out["state"], "unknown")
        self.assertIn("instability", out["facts"])


class LinkedIn(unittest.TestCase):
    def setUp(self):
        self.repo = R.make_repo()
        self.addCleanup(R.drop, self.repo)

    def test_size_is_scored_by_size_adjustment(self):
        out = peek_read.read("linkedin", LI_OK, self.repo)
        self.assertEqual(out["state"], "clear")
        self.assertEqual(out["facts"]["size_adjustment"], ra.size_adjustment(125))
        self.assertEqual(out["facts"]["headcount"], 125)
        small = peek_read.read("linkedin", LI_SMALL, self.repo)
        self.assertGreater(small["facts"]["size_adjustment"], out["facts"]["size_adjustment"])
        self.assertIn("never a gate", out["reason"])

    def test_an_industry_matching_the_persons_veto_is_a_deal_breaker(self):
        out = peek_read.read("linkedin", LI_VETO, self.repo)
        self.assertEqual(out["state"], "blocked")
        self.assertIn("Deal-breaker industry", out["reason"])

    def test_a_layoff_mention_is_not_judged_by_the_app(self):
        out = peek_read.read("linkedin", LI_LAYOFF, self.repo)
        self.assertEqual(out["state"], "unknown")
        self.assertIn("layoff", out["reason"])

    def test_an_unreadable_paste_is_unknown(self):
        out = peek_read.read("linkedin", "just some words", self.repo)
        self.assertEqual(out["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
