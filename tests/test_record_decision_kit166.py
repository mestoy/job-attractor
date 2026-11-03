"""kit #166: four company/ruling extraction bugs, all confirmed against live ledger rows.

1. "Build (Recommended)" classified as OTHER, not BUILD (the "(Recommended)" suffix on the
   picker's default option is display framing, never consulted by classify()).
2. The preposition pass grabbed a proper noun from the QUESTION body ("remote with Florida
   eligible" -> "Florida") even when the HEADER separately named the real company.
3. "<Company> Radar/Build/Drop" headers were not recognized by the SCORECARD-header extractor,
   which matched only the literal word "SCORECARD".
4. A bare unknown-company header ("Zorbex", not yet in _known_companies()) returned "".

Pure-function tests, loaded by file path with the known-company list stubbed, same convention
as tests/test_record_decision_extract_company.py.
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "record_decision.py")


def _load(known=()):
    spec = importlib.util.spec_from_file_location("rd_kit166_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._known_companies = lambda: set(k.lower() for k in known)
    return mod


class Bug1BuildRecommendedSuffix(unittest.TestCase):
    def setUp(self):
        self.classify = _load().classify

    def test_build_recommended_classifies_as_build(self):
        self.assertEqual(self.classify("Build (Recommended)"), "BUILD")

    def test_build_recommended_lowercase_and_spacing_variants(self):
        for answer in ("build (recommended)", "Build(Recommended)", "Build ( Recommended )"):
            self.assertEqual(self.classify(answer), "BUILD", answer)

    def test_a_negation_after_the_stripped_suffix_still_skips(self):
        # the strip must not widen BUILD_EXACT into eating a real refusal
        self.assertEqual(self.classify("don't build (Recommended)"), "SKIP")


class Bug2HeaderOutranksQuestionBodyInThePrepositionPass(unittest.TestCase):
    def setUp(self):
        self.extract_company = _load().extract_company

    def test_a_geographic_noun_in_the_question_no_longer_wins_over_the_header(self):
        qtext = "Plinth Health -- remote with Florida eligible, build the outreach?"
        header = "Plinth Health Build"
        # call order matches the real call site: extract_company(qtext, header, _for_class)
        self.assertEqual(self.extract_company(qtext, header, ""), "Plinth Health")

    def test_the_preposition_pass_still_works_with_no_header(self):
        self.assertEqual(self.extract_company("draft the note to Vic at Acme", ""), "Acme")


class Bug3RulingKeywordHeadersAreRecognised(unittest.TestCase):
    def setUp(self):
        self.extract_company = _load().extract_company

    def test_radar_header(self):
        self.assertEqual(self.extract_company("", "Zorbex Radar", ""), "Zorbex")

    def test_build_header(self):
        self.assertEqual(self.extract_company("", "Quillmark Build", ""), "Quillmark")

    def test_multiword_build_header(self):
        self.assertEqual(self.extract_company("", "Plinth Health Build", ""), "Plinth Health")

    def test_drop_park_skip_headers(self):
        for kw, company in (("Drop", "Acme"), ("Park", "Acme"), ("Skip", "Acme")):
            self.assertEqual(self.extract_company("", "%s %s" % (company, kw), ""), company, kw)

    def test_the_literal_scorecard_keyword_still_works(self):
        self.assertEqual(self.extract_company("", "Northwind Health SCORECARD", ""), "Northwind Health")


class Bug4BareUnknownCompanyHeader(unittest.TestCase):
    def setUp(self):
        self.extract_company = _load().extract_company

    def test_a_bare_header_that_is_only_a_company_name_resolves(self):
        self.assertEqual(self.extract_company("", "Zorbex", ""), "Zorbex")

    def test_a_bare_multiword_company_name_resolves(self):
        self.assertEqual(self.extract_company("", "Plinth Health", ""), "Plinth Health")

    def test_a_full_sentence_never_qualifies_as_a_bare_header(self):
        self.assertEqual(self.extract_company("Which company should I screen next?", ""), "")

    def test_a_lowercase_leading_header_never_qualifies(self):
        self.assertEqual(self.extract_company("", "remote roles", ""), "")


if __name__ == "__main__":
    unittest.main()
