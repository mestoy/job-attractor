"""BUG-265 — a card header could carry TWO contradicting verdict words and the reader took the
first, silently.

Found 2026-09-11 (seat 46) on nine cards, all the same shape: `· RADAR · ... · PARK ·`. Because
none carried a `STATUS:` key, `card_stage()` returned `carded_unruled` and `apply_queue()` then
filled RADAR from the queue, while `scorecards/INDEX.md` recorded PARK with a reason. The owner
ruled INDEX authoritative, ruled all nine PARK, and ruled that the reader must REFUSE a header
carrying two verdicts rather than resolve it by position — the same discipline `rule_card.py`
already applies when it refuses on 0 or 2+ queue matches.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import depth_report as dr


class VerdictConflictTest(unittest.TestCase):
    def test_two_bare_verdict_fields_refuse(self):
        """The exact live shape of all nine."""
        h = "# Fictional Co · payments · RADAR · panel 60/58/52 mean 57 · PARK · boss none · 2026-09-06"
        self.assertEqual(dr.card_stage(h), "verdict_conflict")

    def test_status_contradicted_by_a_bare_field_refuses(self):
        h = "# Fictional Co · STATUS: RADAR · panel 70 · PARK · 2026-09-06"
        self.assertEqual(dr.card_stage(h), "verdict_conflict")

    def test_remote_pass_is_not_a_verdict(self):
        """The guard that matters most: PASS is a stage token, and 'remote PASS' appears in a
        great many headers beside a real verdict. It is not a bare verdict field and must not
        trip the refusal."""
        h = "# Fictional Co · applied-ai · panel 74 · STATUS: RADAR · boss A B · remote PASS · 2026-09-06"
        self.assertEqual(dr.card_stage(h), "RADAR")

    def test_a_single_status_token_is_unchanged(self):
        h = "# Fictional Co · STATUS: BUILD (ruled) · remote PASS · 2026-09-06"
        self.assertEqual(dr.card_stage(h), "BUILD")

    def test_no_verdict_at_all_is_still_carded_unruled(self):
        """45 of 107 real cards carry no STATUS key. They must keep falling through to the queue,
        never become a conflict and never become unruled-by-a-new-rule."""
        h = "# Fictional Co · payments · panel 60 · boss none · remote PASS · 2026-09-06"
        self.assertEqual(dr.card_stage(h), "carded_unruled")

    def test_the_same_verdict_twice_is_not_a_conflict(self):
        h = "# Fictional Co · PARK · panel 60 · PARK · 2026-09-06"
        self.assertNotEqual(dr.card_stage(h), "verdict_conflict")


if __name__ == "__main__":
    unittest.main()
