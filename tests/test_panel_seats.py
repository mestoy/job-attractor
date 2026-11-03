#!/usr/bin/env python3
"""PANEL_SEATS — the configurable panel, and the honesty rules around it.

His ask, 2026-09-11: "the Rise8 score is optional and specific to me. It would be great to
let others customize the scores that are meaningful to them."

The interesting cases are all failure cases. A scorecard renders a confident number whatever
happens underneath it, so every path here has to degrade to something TRUE rather than to
something that merely prints.
"""
import os as _os, sys as _sys  # BUG-736: seed kit_config first (bare checkout has only the example)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _kit_config_shim  # noqa: E402,F401
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import kit_config  # noqa: E402


class PanelSeatsDefault(unittest.TestCase):
    def test_ships_empty_and_falls_back_to_the_shipped_panel(self):
        """An unconfigured install scores by CPO/CTO/CEO, exactly as every card on file assumes."""
        self.assertEqual(kit_config.PANEL_SEATS, [], "PANEL_SEATS must ship empty")
        self.assertEqual([s["name"] for s in kit_config.panel_seats()], ["CPO", "CTO", "CEO"])

    def test_default_seats_are_plain_weight_and_not_optional(self):
        for seat in kit_config.panel_seats():
            self.assertEqual(seat["weight"], 1.0)
            self.assertIs(seat["optional"], False)


class PanelSeatsConfigured(unittest.TestCase):
    def setUp(self):
        self._saved = kit_config.PANEL_SEATS

    def tearDown(self):
        kit_config.PANEL_SEATS = self._saved

    def test_somebody_elses_seats_replace_the_default_entirely(self):
        kit_config.PANEL_SEATS = [{"name": "Mission"}, {"name": "Comp"}, {"name": "Growth"}]
        self.assertEqual([s["name"] for s in kit_config.panel_seats()],
                         ["Mission", "Comp", "Growth"])

    def test_a_bare_string_is_accepted_as_a_seat_name(self):
        kit_config.PANEL_SEATS = ["Mission", "Comp"]
        self.assertEqual([s["name"] for s in kit_config.panel_seats()], ["Mission", "Comp"])

    def test_an_optional_seat_is_recorded_as_optional(self):
        """A preference seat must stay distinguishable from a gate, or a low score on somebody's
        own taste reads as a failed gate."""
        kit_config.PANEL_SEATS = [{"name": "CPO"}, {"name": "Rise8", "optional": True}]
        seats = kit_config.panel_seats()
        self.assertIs(seats[0]["optional"], False)
        self.assertIs(seats[1]["optional"], True)

    def test_malformed_entries_are_dropped_not_guessed_at(self):
        kit_config.PANEL_SEATS = [{"name": "CPO"}, {"name": "   "}, 17, None, {"weight": 2}]
        self.assertEqual([s["name"] for s in kit_config.panel_seats()], ["CPO"])

    def test_a_wholly_unusable_config_falls_back_rather_than_scoring_by_nothing(self):
        for bad in ([], {}, "CPO", None, [None, 3, {"weight": 1}]):
            kit_config.PANEL_SEATS = bad
            self.assertEqual([s["name"] for s in kit_config.panel_seats()],
                             ["CPO", "CTO", "CEO"], "fell through on %r" % (bad,))

    def test_a_nonsense_weight_becomes_one_rather_than_zeroing_a_seat(self):
        kit_config.PANEL_SEATS = [{"name": "A", "weight": "heavy"}, {"name": "B", "weight": 0},
                                  {"name": "C", "weight": -4}]
        self.assertEqual([s["weight"] for s in kit_config.panel_seats()], [1.0, 1.0, 1.0])


class PanelMean(unittest.TestCase):
    def setUp(self):
        self._saved = kit_config.PANEL_SEATS

    def tearDown(self):
        kit_config.PANEL_SEATS = self._saved

    def test_plain_average_by_default(self):
        self.assertEqual(kit_config.panel_mean({"CPO": 82, "CTO": 70, "CEO": 58}), 70.0)

    def test_weights_are_honored(self):
        kit_config.PANEL_SEATS = [{"name": "A", "weight": 3}, {"name": "B", "weight": 1}]
        self.assertEqual(kit_config.panel_mean({"A": 80, "B": 40}), 70.0)

    def test_an_unscored_seat_is_skipped_not_counted_as_zero(self):
        """Counting a missing seat as 0 would drag the mean down and look like a judgment."""
        self.assertEqual(kit_config.panel_mean({"CPO": 80, "CTO": 70}), 75.0)

    def test_no_scores_at_all_is_None_never_zero(self):
        """A card with nothing scored has no mean. 0.0 would render as a real, terrible score."""
        self.assertIsNone(kit_config.panel_mean({}))
        self.assertIsNone(kit_config.panel_mean({"NotASeat": 90}))

    def test_unparseable_scores_are_skipped_rather_than_crashing_the_render(self):
        self.assertEqual(kit_config.panel_mean({"CPO": 80, "CTO": "n/a", "CEO": 70}), 75.0)

    def test_seats_not_in_the_configured_set_do_not_contribute(self):
        """A leftover score from a retired seat must not quietly re-enter the mean."""
        kit_config.PANEL_SEATS = [{"name": "CPO"}, {"name": "CTO"}]
        self.assertEqual(kit_config.panel_mean({"CPO": 80, "CTO": 60, "CEO": 0}), 70.0)


if __name__ == "__main__":
    unittest.main()
