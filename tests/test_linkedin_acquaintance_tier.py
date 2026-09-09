#!/usr/bin/env python3
"""Kit #43 item 2 — the `linkedin-acquaintance` closeness tier.

"Connected on LinkedIn and exchanged pleasantries, but no real relationship" is a LABEL, not a
new score: it must carry never-spoke's tuple byte for byte (rung 1-2, zero-ask hello), be accepted
as a stated tier (so --record takes it), and be documented in the seed's own `_scale`. Standard
library only, no network, no mutation of the live tree.
"""
import importlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

closeness = importlib.import_module("closeness")
level_contacts = importlib.import_module("level_contacts")


class LinkedinAcquaintanceTier(unittest.TestCase):
    def test_tuple_matches_never_spoke_byte_for_byte(self):
        self.assertIn("linkedin-acquaintance", closeness.TIERS,
                       "RED: the tier is absent from closeness.TIERS")
        self.assertEqual(closeness.TIERS["linkedin-acquaintance"], closeness.TIERS["never-spoke"],
                         "a labelling change must carry never-spoke's tuple exactly, not a new score")
        self.assertEqual(closeness.TIERS["linkedin-acquaintance"], (None, None, None, "none"))

    def test_accepted_as_a_stated_tier(self):
        self.assertIn("linkedin-acquaintance", level_contacts.STATED_TIERS,
                       "RED: --record must accept this tier")

    def test_seeded_in_the_scale_documentation(self):
        self.assertIn("linkedin-acquaintance", level_contacts._SEED["_scale"],
                       "RED: the self-documenting seed must explain the new tier")

    def test_rank_criteria_rung_is_cold_rung_1_2_no_warm_lift(self):
        """Same treatment as never-spoke: cold floor, rung 1-2, no bonus, IDENTICAL to never-spoke's
        own rung_for() output — the tuple sameness must survive the live code path, not just the
        table entry."""
        never_spoke = closeness.rung_for({"closeness": "never-spoke", "source": "stated-by-owner"},
                                         "other")
        acquaintance = closeness.rung_for(
            {"closeness": "linkedin-acquaintance", "source": "stated-by-owner"}, "other")
        self.assertEqual(acquaintance, never_spoke,
                         "RED: linkedin-acquaintance must resolve to the exact never-spoke verdict")
        rung_key, band, _ask, bonus, _flag = acquaintance
        self.assertEqual(rung_key, "cold-stranger")
        self.assertEqual(band, "rung 1-2")
        self.assertEqual(bonus, 0.0, "no warm lift for an honestly-labelled never-spoke")


if __name__ == "__main__":
    unittest.main()
