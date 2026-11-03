"""BUG-256 (seat 98's find, filed by e4): the stat core (n=/median/Q1/Q3) was never the
whole staleness story -- sector_sync.py had no way to refresh a stale/incomplete baseline
(--apply just refused, correctly, with no path forward), and the per-card "ranks N of M
(mean Z)" clause was never resynced at all, even by --apply, so it kept a superseded mean
after any re-panel (Sibol GRC: mean 76 vs. a real 74.7; Ilawan Health Exchange: 61 vs. 60; Ugnay Health: 70.3 vs.
81 -- all cited live).

Fixtures are fictional, per this test suite's own PII rule."""
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

### Applied-ai (n=3)

| Stat | Mean | CPO | CTO | CEO |
|---|---|---|---|---|
| median | 74.0 | 78.0 | 74.0 | 72.0 |
| q1 | 70.0 | 74.0 | 70.0 | 68.0 |
| q3 | 80.0 | 82.0 | 78.0 | 76.0 |

| Company | CPO | CTO | CEO | Mean | Date | vs median |
|---|---|---|---|---|---|---|
| Fictional Fabrics Co | 82.0 | 78.0 | 76.0 | 78.7 | 2026-09-08 | above |
| Fictional Furnishing Co | 78.0 | 74.0 | 72.0 | 74.7 | 2026-09-05 | above |
| Widget Sprockets Inc | 70.0 | 68.0 | 66.0 | 68.0 | 2026-09-01 | below |
"""


class RankClauseRepanelTests(unittest.TestCase):
    """A re-panelled card's rank/mean clause must move alongside the stat core."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bug256-")
        self.baseline_path = os.path.join(self.tmp, "sector-score-baseline-2026-09-09.md")
        with open(self.baseline_path, "w", encoding="utf-8") as fh:
            fh.write(BASELINE)
        self.baseline = ss.parse_baseline(self.baseline_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_a_stats_block_and_rank_clause_both_move_on_repanel(self):
        # The card's own header carries the FRESH re-panel score (74.7, was 78.7 before);
        # its baseline row is stale at 78.7. n was stale too (of 5, real is 3).
        card = self._write("fictional-fabrics-card-2026-09-09.md", (
            "# Fictional Fabrics Co · applied-ai · STATUS: RADAR · panel 78/74/72 mean "
            "74.7 (re-panel complete 2026-09-09) · 2026-09-09\n\n"
            "**Sector:** applied-ai (n=5) · median 70 · Q1 65 · Q3 75 · this card ranks "
            "1 of 5 (mean 78.7) · per-seat medians CPO 74 / CTO 70 / CEO 68.\n"
        ))
        touched, missing = ss.sync_tree(self.tmp, self.baseline, apply=True)
        self.assertEqual(missing, [])
        after = open(card, encoding="utf-8").read()
        self.assertIn("n=3", after)               # stat core still resyncs, as before
        self.assertIn("median 74", after)
        # Fictional Furnishing Co ties this card's fresh mean (74.7 vs 74.7) -- a tie
        # never counts as "above" (strict greater-than, standard ranking convention), so
        # only Widget Sprockets Inc (68.0) sits below and this card still reads rank 1.
        self.assertIn("this card ranks 1 of 3 (mean 74.7)", after)

    def test_b_header_mean_wins_over_a_stale_mean_quoted_in_the_cards_own_prose(self):
        # BUG-256 (Sibol GRC, confirmed live): a re-panelled card's own ruling narrative
        # can quote the OLD mean as history ("the panel score (mean 78.7) predates..."),
        # sitting EARLIER in the body than the header. A naive whole-body mean search
        # would grab that stale number; the header field must win.
        card = self._write("fictional-furnishing-card-2026-09-09.md", (
            "# Fictional Furnishing Co · applied-ai · STATUS: RADAR · panel 78/74/72 "
            "mean 74.7 · 2026-09-09\n\n"
            "## Ruling\nReturns to RADAR -- the panel score (mean 78.7) predates the "
            "re-panel. Re-panel complete: CPO 78 / CTO 74 / CEO 72, mean 74.7.\n\n"
            "**Sector:** applied-ai (n=5) · median 70 · Q1 65 · Q3 75 · this card ranks "
            "1 of 5 (mean 78.7) · per-seat medians CPO 74 / CTO 70 / CEO 68.\n"
        ))
        ss.sync_tree(self.tmp, self.baseline, apply=True)
        after = open(card, encoding="utf-8").read()
        # Fictional Fabrics Co (78.7) sits above this card's real 74.7; Widget Sprockets
        # Inc (68.0) below -- rank 2 of 3. If the stale 78.7 had won instead, this would
        # read "ranks 1 of 3" (nothing left above a tie with itself).
        self.assertIn("this card ranks 2 of 3 (mean 74.7)", after)
        self.assertNotIn("this card ranks 1 of 3", after)

    def test_c_extract_card_mean_prefers_header_over_body_prose(self):
        text = (
            "# Fictional Co · applied-ai · STATUS: RADAR · panel 78/74/72 mean 74.7 · "
            "2026-09-09\n\nThe old panel score (mean 78.7) is superseded.\n"
        )
        self.assertEqual(ss._extract_card_mean(text), 74.7)

    def test_d_bare_verdict_field_card_still_extracts_a_mean(self):
        # 45 real cards carry the verdict as a bare word with no "STATUS:" key at all
        # (e4's second flagged shape) -- extraction must not depend on that key existing.
        text = (
            "# Fictional Co · applied-ai · RADAR · panel 78/74/72 mean 74.7 · 2026-09-09\n"
        )
        self.assertEqual(ss._extract_card_mean(text), 74.7)


class BuildBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bug256-build-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, text):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_a_a_scored_card_is_grouped_by_segment(self):
        self._write("fictional-fabrics-card-2026-09-09.md", (
            "# Fictional Fabrics Co · applied-ai (fictional sub-tag) · STATUS: RADAR · "
            "panel 82/78/76 mean 78.7 · 2026-09-08\n"
        ))
        segments, excluded, needs_review = ss.build_baseline(self.tmp)
        self.assertIn("applied-ai", segments)
        self.assertEqual(segments["applied-ai"][0]["company"], "Fictional Fabrics Co")
        self.assertEqual(segments["applied-ai"][0]["mean"], 78.7)
        self.assertEqual(excluded, [])
        self.assertEqual(needs_review, [])

    def test_b_a_recognized_out_of_scope_card_is_excluded_not_flagged(self):
        self._write("fictional-dropout-card-2026-09-09.md", (
            "# Fictional Dropout Co · applied-ai · DROP · 2026-09-09\n\n"
            "Remote hard-fail at gate 5. Stopping here per the recipe; no panel, no card.\n"
        ))
        segments, excluded, needs_review = ss.build_baseline(self.tmp)
        self.assertEqual(segments, {})
        self.assertEqual(len(excluded), 1)
        self.assertEqual(needs_review, [])

    def test_c_an_unrecognized_no_score_card_is_flagged_for_review_not_guessed(self):
        # BUG-256 stop condition (e4): a card that doesn't reduce to has-a-score-or-not,
        # and isn't obviously out of scope, must be flagged, never silently included or
        # silently dropped.
        self._write("fictional-mystery-card-2026-09-09.md", (
            "# Fictional Mystery Co · applied-ai · RADAR · 2026-09-09\n\n"
            "## Ruling\nStill under review, no panel run yet, reason not yet documented.\n"
        ))
        segments, excluded, needs_review = ss.build_baseline(self.tmp)
        self.assertEqual(segments, {})
        self.assertEqual(excluded, [])
        self.assertEqual(len(needs_review), 1)
        self.assertEqual(needs_review[0][1], "Fictional Mystery Co")

    def test_d_a_calibration_or_call_card_is_excluded_by_filename(self):
        self._write("panel-calibration-card-2026-09-09.md", "# Panel calibration\n\nMeta.\n")
        segments, excluded, needs_review = ss.build_baseline(self.tmp)
        self.assertEqual(len(excluded), 1)
        self.assertEqual(needs_review, [])

    def test_e_refresh_baseline_writes_a_new_dated_file_never_overwriting_history(self):
        self._write("fictional-fabrics-card-2026-09-09.md", (
            "# Fictional Fabrics Co · applied-ai · STATUS: RADAR · panel 82/78/76 mean "
            "78.7 · 2026-09-08\n"
        ))
        old_baseline = os.path.join(self.tmp, "sector-score-baseline-2026-09-08.md")
        with open(old_baseline, "w", encoding="utf-8") as fh:
            fh.write(BASELINE)
        out_path, segments, excluded, needs_review = ss.refresh_baseline(
            self.tmp, as_of="2026-09-10"
        )
        self.assertTrue(os.path.exists(out_path))
        self.assertNotEqual(out_path, old_baseline)
        self.assertTrue(os.path.exists(old_baseline))  # never mutated
        old_text_after = open(old_baseline, encoding="utf-8").read()
        self.assertEqual(old_text_after, BASELINE)
        new_text = open(out_path, encoding="utf-8").read()
        self.assertIn("Fictional Fabrics Co", new_text)
        self.assertIn("### Applied-ai (n=1)", new_text)


if __name__ == "__main__":
    unittest.main()
