#!/usr/bin/env python3
"""scripts/nextstep_scores.py ships in the kit, byte-equal to the AJS partner-starter copy's contract:
it imports on its own, and the kit's SCORES_TIMEZONE ships unset (the machine's own zone)."""
import ast
import os
import sys
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "scripts"))


class NextstepScoresShips(unittest.TestCase):
    def test_the_example_config_ships_the_zone_unset(self):
        with open(os.path.join(KIT, "scripts", "kit_config.example.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        vals = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "SCORES_TIMEZONE" for t in n.targets)]
        self.assertEqual(vals, [""])

    def test_it_imports_and_reads_the_machine_zone_when_unset(self):
        import nextstep_scores as ns
        self.assertTrue(callable(ns.attach_scores))
        self.assertIsNotNone(ns._zone())

    def test_a_missing_sidecar_attaches_nothing(self):
        import tempfile
        import nextstep_scores as ns
        with tempfile.TemporaryDirectory() as td:
            out = ns.attach_scores({"default": {"label": "x"}, "alternates": []}, repo=td, today="2026-11-02")
        self.assertNotIn("scores", out["default"])


if __name__ == "__main__":
    unittest.main()
