"""BUG-774: extract_company must not guess when the question names two or more known companies.

It used to keep the LONGEST known name in the first text that had any, so a question naming two companies could scope a BUILD
ruling to the one the question only mentioned. Now two or more distinct known companies in one text are ambiguous: a later text (the
header, then the selected option's label) settles it only by naming exactly one of them, and otherwise the result is "" (no company),
which check_preview refuses to honor. Single-word known names count only where a company sits, as before. Names are invented."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import record_decision as rd  # noqa: E402

KNOWN = {"alpha co", "beta inc", "gamma labs", "acme", "acme corp", "company", "gate", "remote"}


class ExtractCompanyAmbiguity(unittest.TestCase):
    def setUp(self):
        self._orig = rd._known_companies
        rd._known_companies = lambda: set(KNOWN)

    def tearDown(self):
        rd._known_companies = self._orig

    def ex(self, *texts):
        return rd.extract_company(*texts)

    def test_two_companies_in_the_question_and_nothing_settles_it_gives_no_company(self):
        self.assertEqual("", self.ex("Build the outreach for Alpha Co or Beta Inc?", "Build gate", "Build it"))

    def test_the_header_settles_it_by_naming_exactly_one(self):
        self.assertEqual("Alpha Co", self.ex("Build the outreach for Alpha Co or Beta Inc?", "Alpha Co", "Build it"))

    def test_a_header_naming_both_does_not_settle_it(self):
        self.assertEqual("", self.ex("Build the outreach for Alpha Co or Beta Inc?", "Alpha Co / Beta Inc", "Build it"))

    def test_the_answer_label_settles_it(self):
        self.assertEqual("Beta Inc", self.ex("Build the outreach for Alpha Co or Beta Inc?", "Build gate", "Build for Beta Inc"))

    def test_a_header_naming_a_third_company_does_not_settle_it(self):
        self.assertEqual("", self.ex("Build the outreach for Alpha Co or Beta Inc?", "Gamma Labs", "Build it"))

    def test_one_company_is_unchanged(self):
        self.assertEqual("Alpha Co", self.ex("Build the outreach for Alpha Co?", "Build gate", "Build it"))
        self.assertEqual("Alpha Co", self.ex("Build gate", "Alpha Co"))

    def test_a_name_nested_in_a_longer_one_counts_once(self):
        self.assertEqual("Acme Corp", self.ex("Build the outreach for Acme Corp?", "Build gate"))

    def test_list_pollution_never_makes_a_text_ambiguous(self):
        self.assertEqual("Alpha Co", self.ex("Which company clears the remote gate? Build for Alpha Co", "Build gate"))

    def test_an_unknown_company_still_uses_the_heuristic(self):
        self.assertEqual("Zed Industries", self.ex("Build the outreach for Zed Industries?", "Build gate"))

    def test_an_ambiguous_question_does_not_fall_through_to_the_heuristic(self):
        """The preposition heuristic would pick the first name; the ambiguity must win."""
        self.assertEqual("", self.ex("Build for Alpha Co, and Beta Inc too?", "Build gate"))

    def test_an_ambiguous_question_then_a_one_name_header_in_a_later_text_only(self):
        self.assertEqual("Beta Inc", self.ex("Alpha Co and Beta Inc are both live.", "Build gate", "Beta Inc"))


class AmbiguousIsADistinctOutcome(unittest.TestCase):
    def setUp(self):
        self._orig = rd._known_companies
        rd._known_companies = lambda: set(KNOWN) | {"zzalpha", "zzbeta"}

    def tearDown(self):
        rd._known_companies = self._orig

    def test_ambiguous_is_a_marker_that_still_equals_empty(self):
        got = rd.extract_company("Build the outreach for Alpha Co or Beta Inc?", "Build gate")
        self.assertEqual("", got)
        self.assertFalse(got)
        self.assertIsInstance(got, rd._Ambiguous)

    def test_no_company_found_is_not_marked_ambiguous(self):
        got = rd.extract_company("Confirm the build so I can record it?", "Build gate")
        self.assertEqual("", got)
        self.assertNotIsInstance(got, rd._Ambiguous)

    def test_single_word_companies_in_a_list_are_ambiguous(self):
        self.assertIsInstance(rd.extract_company("Build for ZZAlpha or ZZBeta?", "Build gate"), rd._Ambiguous)
        self.assertIsInstance(rd.extract_company("Build for ZZAlpha, ZZBeta?", "Build gate"), rd._Ambiguous)

    def test_polluted_single_words_in_prose_are_not_a_list(self):
        got = rd.extract_company("Is it remote or the gate for ZZAlpha?", "Build gate")
        self.assertEqual("ZZAlpha", got)


if __name__ == "__main__":
    unittest.main()
