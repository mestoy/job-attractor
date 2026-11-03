#!/usr/bin/env python3
"""record_decision.extract_company() must stop at a sentence boundary (kit#99).

The general preposition-anchored fallback treated `.` as an ordinary name character and its
multi-word continuation only asked "is the next word capitalized", never "did a sentence just
end". Since the word after a period is almost always capitalized, the capture ran into the
NEXT sentence: "at Example Health Plan. Your ruling?" recorded company "Example Health Plan. Your" on a live
BUILD row, so the BUILD gate was not scoped to the company the human ruled on.

A second shape was missed outright: a scorecard whose header LEADS with the company and no
preposition ("ENDEAVOR4 SOLUTIONS SCORECARD · ...") recorded company "".

Pure-function tests. Nothing here touches a ledger; the module is loaded by file path and its
known-company list is stubbed so the regex paths are what is under test.
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "record_decision.py")


def _load(known=()):
    spec = importlib.util.spec_from_file_location("rd_extract_company_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._known_companies = lambda: set(k.lower() for k in known)
    return mod.extract_company


class SentenceBoundary(unittest.TestCase):
    """Issue examples, shaped like a live ledger, with invented names."""

    def test_period_then_capitalized_word_stops_at_the_period(self):
        ex = _load()
        self.assertEqual(ex("Scorecard 1 of 1, Alex Doe at Sample Design. Your ruling?", "", ""),
                         "Sample Design")

    def test_build_row_multiword_company(self):
        ex = _load()
        self.assertEqual(ex("Scorecard: Sam Roe at Example Health Plan. Your ruling?", "", ""),
                         "Example Health Plan")

    def test_single_token_before_period(self):
        ex = _load()
        self.assertEqual(ex("How do you know Pat Doe? He is a professor at XYZ. He helped me.", "", ""),
                         "XYZ")

    def test_pair_ladder_question_with_company_mid_sentence(self):
        ex = _load()
        q = ("NEXT-STEP · what now? LADDER 2026-09-12 · scorecard for Sample Design. "
             "Kuya Andy's default is option 1")
        self.assertEqual(ex(q, "", ""), "Sample Design")

    def test_newline_is_a_boundary(self):
        ex = _load()
        self.assertEqual(ex("Ruling for Acme Robotics\nNext line Starts Capitalized", "", ""),
                         "Acme Robotics")

    def test_middle_dot_and_question_mark_still_boundaries(self):
        ex = _load()
        self.assertEqual(ex("Build for Acme · LADDER 2026-09-12 · Andy default", "", ""), "Acme")
        self.assertEqual(ex("Build or skip for Example Health Plan? Second Sentence Here", "", ""),
                         "Example Health Plan")

    def test_internal_dot_brand_survives(self):
        ex = _load()
        self.assertEqual(ex("Build or skip for Booking.com? Your ruling", "", ""), "Booking.com")

    def test_for_marker_with_capitalized_company_never_blank(self):
        ex = _load()
        self.assertNotEqual(ex("Build for Northstar. Your call", "", ""), "")


class LeadingScorecardHeader(unittest.TestCase):
    def test_company_leads_the_scorecard_header(self):
        ex = _load()
        self.assertEqual(ex("ENDEAVOR4 SOLUTIONS SCORECARD · Microsoft Dynamics 365 CRM Product Owner",
                            "", ""), "ENDEAVOR4 SOLUTIONS")

    def test_known_name_still_wins_over_a_generic_leading_word(self):
        ex = _load(known=["Zzyzx"])
        self.assertEqual(ex("UPDATED SCORECARD · build for Zzyzx?", "", ""), "Zzyzx")


class Unchanged(unittest.TestCase):
    """The tightening must not widen: ordinary words after a preposition still resolve to nothing."""

    def test_common_words_resolve_to_nothing(self):
        ex = _load()
        self.assertEqual(ex("Which company should I screen next for the team?", "", ""), "")
        self.assertEqual(ex("Ready for a minute?", "", ""), "")

    def test_connector_name_unchanged(self):
        ex = _load()
        self.assertEqual(ex("Build or skip for Welcome to the Jungle?", "", ""), "Welcome to the Jungle")


if __name__ == "__main__":
    unittest.main()
