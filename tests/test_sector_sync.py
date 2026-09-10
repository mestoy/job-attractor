"""sector_sync.py — keeps a card's/HTML's Sector: line stat core in sync with the
latest baseline, without ever touching the descriptive clause. Fictional fixtures only."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))

import sector_sync as ss  # noqa: E402


BASELINE = """# Sector score baseline, 2026-09-09 (fictional fixture)

### Applied-ai (n=6)

| Stat | Mean | CPO | CTO | CEO |
|---|---|---|---|---|
| median | 76.0 | 82.0 | 79.0 | 75.0 |
| q1 | 70.0 | 75.0 | 72.0 | 68.0 |
| q3 | 82.0 | 86.0 | 83.0 | 80.0 |

| Company | CPO | CTO | CEO | Mean | Date | vs median |
|---|---|---|---|---|---|---|
| Fictional Fabrics Co | 80.0 | 78.0 | 82.0 | 80.0 | 2026-09-09 | above |
| Widget Sprockets Inc | 70.0 | 72.0 | 68.0 | 70.0 | 2026-09-08 | below |
"""

CARD_STALE = """# Fictional Fabrics Co · applied-ai · RADAR · 2026-09-09

**Sector:** applied-ai (n=5) · median 74 · Q1 68 · Q3 79 · this card ranks 1 of 5 (mean 80.0) · per-seat medians CPO 80 / CTO 76 / CEO 73.

## 11. Panel

- CPO 80
- CTO 78
- CEO 82
"""


class ParseBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sector-sync-")
        self.baseline_path = os.path.join(self.tmp, "sector-score-baseline-2026-09-09.md")
        with open(self.baseline_path, "w", encoding="utf-8") as fh:
            fh.write(BASELINE)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_parses_segment_stats(self):
        baseline = ss.parse_baseline(self.baseline_path)
        seg = baseline["appliedai"]
        self.assertEqual(seg["n"], 6)
        self.assertEqual(seg["median"], 76.0)
        self.assertEqual(seg["q1"], 70.0)
        self.assertEqual(seg["q3"], 82.0)
        self.assertEqual(seg["cpo_median"], 82.0)
        self.assertEqual(seg["cto_median"], 79.0)
        self.assertEqual(seg["ceo_median"], 75.0)

    def test_b_parses_company_list(self):
        baseline = ss.parse_baseline(self.baseline_path)
        seg = baseline["appliedai"]
        self.assertIn("Fictional Fabrics Co", seg["companies"])
        self.assertIn("Widget Sprockets Inc", seg["companies"])


class RewriteStatCoreTests(unittest.TestCase):
    def setUp(self):
        self.baseline = ss.parse_baseline_from_text = None  # placeholder, unused
        self.tmp = tempfile.mkdtemp(prefix="sector-sync-")
        self.baseline_path = os.path.join(self.tmp, "sector-score-baseline-2026-09-09.md")
        with open(self.baseline_path, "w", encoding="utf-8") as fh:
            fh.write(BASELINE)
        self.baseline = ss.parse_baseline(self.baseline_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_stat_core_is_rewritten(self):
        new_text, changes = ss.rewrite_stat_core(CARD_STALE, self.baseline)
        self.assertEqual(len(changes), 1)
        self.assertIn("n=6", new_text)
        self.assertIn("median 76", new_text)
        self.assertIn("Q1 70", new_text)
        self.assertIn("Q3 82", new_text)

    def test_b_descriptive_clause_survives_byte_for_byte(self):
        """The whole point: 'this card ranks 1 of 5 (mean 80.0)' must NOT be touched by
        the stat-core rewrite, even though the stats around it changed."""
        new_text, _changes = ss.rewrite_stat_core(CARD_STALE, self.baseline)
        self.assertIn("this card ranks 1 of 5 (mean 80.0)", new_text)

    def test_c_per_seat_medians_rewritten_separately(self):
        new_text, _ = ss.rewrite_stat_core(CARD_STALE, self.baseline)
        seg = self.baseline["appliedai"]
        new_text = ss.rewrite_per_seat(new_text, seg)
        self.assertIn("per-seat medians CPO 82 / CTO 79 / CEO 75", new_text)

    def test_d_unknown_segment_left_untouched(self):
        text = "**Sector:** off-segment (n=1) · median 50 · Q1 50 · Q3 50 · foo · per-seat medians CPO 50 / CTO 50 / CEO 50."
        new_text, changes = ss.rewrite_stat_core(text, self.baseline)
        self.assertEqual(changes, [])
        self.assertEqual(new_text, text)


class SyncTreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sector-sync-tree-")
        self.baseline_path = os.path.join(self.tmp, "sector-score-baseline-2026-09-09.md")
        with open(self.baseline_path, "w", encoding="utf-8") as fh:
            fh.write(BASELINE)
        self.card_path = os.path.join(self.tmp, "fictional-fabrics-card-2026-09-09.md")
        with open(self.card_path, "w", encoding="utf-8") as fh:
            fh.write(CARD_STALE)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_dry_run_writes_nothing(self):
        baseline = ss.parse_baseline(self.baseline_path)
        before = open(self.card_path, encoding="utf-8").read()
        touched, missing = ss.sync_tree(self.tmp, baseline, apply=False)
        after = open(self.card_path, encoding="utf-8").read()
        self.assertEqual(before, after)
        self.assertEqual(len(touched), 1)
        self.assertEqual(missing, [])

    def test_b_apply_writes_the_stat_core_only(self):
        baseline = ss.parse_baseline(self.baseline_path)
        touched, missing = ss.sync_tree(self.tmp, baseline, apply=True)
        self.assertEqual(missing, [])
        after = open(self.card_path, encoding="utf-8").read()
        self.assertIn("n=6", after)
        self.assertIn("this card ranks 1 of 5 (mean 80.0)", after)

    def test_c_missing_company_is_reported(self):
        unknown_card = os.path.join(self.tmp, "unknown-co-card-2026-09-09.md")
        with open(unknown_card, "w", encoding="utf-8") as fh:
            fh.write(CARD_STALE.replace("Fictional Fabrics Co", "Unknown Co"))
        baseline = ss.parse_baseline(self.baseline_path)
        touched, missing = ss.sync_tree(self.tmp, baseline, apply=False)
        missing_files = [os.path.basename(p) for p, _c in missing]
        self.assertIn("unknown-co-card-2026-09-09.md", missing_files)

    def test_d_refuses_apply_via_main_when_a_company_is_missing(self):
        unknown_card = os.path.join(self.tmp, "unknown-co-card-2026-09-09.md")
        with open(unknown_card, "w", encoding="utf-8") as fh:
            fh.write(CARD_STALE.replace("Fictional Fabrics Co", "Unknown Co"))
        old_argv = sys.argv
        try:
            sys.argv = ["sector_sync.py", self.tmp, "--apply"]
            rc = ss.main()
        finally:
            sys.argv = old_argv
        self.assertEqual(rc, 2)
        # The KNOWN card must still be untouched (refusal blocks the whole apply, not
        # just the missing one).
        after = open(self.card_path, encoding="utf-8").read()
        self.assertIn("n=5", after)  # stale value, unchanged


if __name__ == "__main__":
    unittest.main()
