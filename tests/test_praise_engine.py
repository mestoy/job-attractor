"""Tests for scripts/praise_engine.py -- the shared accomplishment allowlist.

Cross-checked against the kit's own build.py (_card_praise_candidates) on every real card in
documents/state/app-feed.json: zero mismatches across all 101 cards. These tests cover the
allowlist rules directly, plus the real-feed shape (a card that genuinely has nothing).
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import praise_engine as P  # noqa: E402


class PraiseSentences(unittest.TestCase):
    def test_a_shipped_product_sentence_survives(self):
        out = P.praise_sentences("The team launched a new AI-native underwriting product in 2026.")
        self.assertEqual(len(out), 1)
        self.assertIn("launched", out[0])

    def test_a_bare_appointment_line_is_rejected(self):
        out = P.praise_sentences("Ron Longo appointed CEO 2025-09-23, succeeding the founder.")
        self.assertEqual(out, [])

    def test_a_risk_check_negative_result_is_rejected(self):
        out = P.praise_sentences("No layoff signal found in any source. No adverse press found.")
        self.assertEqual(out, [])

    def test_a_red_flag_sentence_is_rejected_even_with_a_verb(self):
        out = P.praise_sentences("The company launched amid a leadership exodus and turnover.")
        self.assertEqual(out, [])

    def test_a_funding_fact_survives_but_ranks_behind_a_shipped_fact(self):
        text = "The company raised a $20M Series B. The team shipped a new mobile app."
        out = P.praise_sentences(text)
        self.assertEqual(len(out), 2)
        self.assertIn("shipped", out[0])  # rank 0 (impact) sorts before rank 1 (funding)

    def test_founder_led_is_not_mistaken_for_the_verb_led(self):
        out = P.praise_sentences("A founder-led company with steady leadership.")
        self.assertEqual(out, [])

    def test_a_research_process_sentence_is_rejected(self):
        out = P.praise_sentences("Identity resolved this pass, closing the prior pass's gap.")
        self.assertEqual(out, [])

    def test_citation_and_outlet_metadata_is_stripped_from_the_kept_sentence(self):
        out = P.praise_sentences("The company launched a new platform (PR Newswire, 2026-07-15).")
        self.assertEqual(len(out), 1)
        self.assertNotIn("PR Newswire", out[0])


class PraiseCandidates(unittest.TestCase):
    def test_a_card_with_only_risk_screening_text_yields_nothing(self):
        card = {
            "research": {},
            "gates": [
                {"key": "leadership", "why": "Ron Longo appointed CEO 2025-09-23, succeeding the founder."},
                {"key": "news", "why": "No layoff signal found. No adverse press found."},
            ],
        }
        self.assertEqual(P.praise_candidates(card), [])
        self.assertIsNone(P.praise_source(card))

    def test_research_praise_is_checked_before_gates(self):
        card = {
            "research": {"praise": {"status": "sourced", "value": "The team shipped a new product.",
                                     "source": "LinkedIn", "url": "https://example.com"}},
            "gates": [{"key": "leadership", "why": "The company launched a second product line too."}],
        }
        out = P.praise_candidates(card)
        self.assertEqual(out[0]["source"], "LinkedIn")

    def test_a_genuine_accomplishment_in_gate_text_is_recovered(self):
        card = {"research": {}, "gates": [
            {"key": "news", "why": "No layoff signal found. The company launched a new AI product in 2026."},
        ]}
        out = P.praise_candidates(card)
        self.assertEqual(len(out), 1)
        self.assertIn("launched", out[0]["text"])

    def test_praise_sources_never_returns_more_than_three(self):
        card = {"research": {}, "gates": [
            {"key": "leadership", "why": "Shipped A. Launched B. Released C. Built D."},
        ]}
        self.assertLessEqual(len(P.praise_sources(card)), 3)


class OutletAsideIsDropped(unittest.TestCase):
    """Every outlet in the known-outlet list has its "(per <outlet>)" aside dropped from a praise sentence."""

    def test_each_listed_outlet_is_stripped(self):
        self.assertGreater(len(P._PRAISE_KNOWN_OUTLETS), 5, "the list had names to check")
        for outlet in P._PRAISE_KNOWN_OUTLETS:
            with self.subTest(outlet=outlet):
                self.assertEqual("Shipped it.", P._PRAISE_OUTLET_LIST.sub("", "Shipped it. (per %s)" % outlet).strip())

if __name__ == "__main__":
    unittest.main()
