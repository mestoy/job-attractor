"""One rule for a card's company name: depth_report.card_companies() must agree with board's header.

depth_report kept its own clean-up (parentheses and dashes only), so "Fake Compliance, resolution card"
stayed a whole title there while board.card_company read "Fake Compliance". The ledger and queue
matches key on this name, so a disagreement silently misses a decision.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import board  # noqa: E402
import depth_report  # noqa: E402


class CardCompanyOneRule(unittest.TestCase):
    def test_both_readers_agree_on_every_real_card(self):
        cards = board.load_cards(REPO)
        if not cards:
            self.skipTest("no cards in this install")
        names = depth_report.card_companies(REPO)
        diff = {s: (names.get(s), c["head"]["company"]) for s, c in cards.items()
                if names.get(s) != c["head"]["company"]}
        self.assertEqual(diff, {})
        self.assertGreater(len(names), 0, "an empty comparison passes")


if __name__ == "__main__":
    unittest.main()
