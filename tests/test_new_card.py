"""new_card.py — scaffolds a card in the shape render_scorecard.py already reads.

Fictional fixtures only (never a real company from the private repo)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
import io

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))

import new_card as nc  # noqa: E402
import render_scorecard as rs  # noqa: E402


class NewCardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="new-card-")
        self.out_dir = os.path.join(self.tmp, "state")
        self.findings_dir = os.path.join(self.tmp, "findings")
        self.employers_path = os.path.join(self.tmp, "employers.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_employer(self, key, **fields):
        os.makedirs(os.path.dirname(self.employers_path), exist_ok=True)
        row = {"key": key, **fields}
        with open(self.employers_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def _write_finding(self, run, company, **fields):
        os.makedirs(self.findings_dir, exist_ok=True)
        row = {"run": run, "company": company, "verdict": "SURVIVOR", "lane": "applied-ai", **fields}
        with open(os.path.join(self.findings_dir, f"{run}.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def test_a_refuses_to_scaffold_a_blocked_company(self):
        self._write_employer("fictionalblockedco", status="blocked")
        old_argv = sys.argv
        old_stderr = sys.stderr
        try:
            sys.argv = ["new_card.py", "Fictional Blocked Co",
                        "--out", self.out_dir, "--findings-dir", self.findings_dir,
                        "--employers-path", self.employers_path]
            sys.stderr = io.StringIO()
            rc = nc.main()
            err = sys.stderr.getvalue()
        finally:
            sys.argv = old_argv
            sys.stderr = old_stderr
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", err)
        self.assertFalse(os.path.isdir(self.out_dir))

    def test_b_skeleton_has_every_required_slot_the_renderer_matches(self):
        """The core acceptance test: a fresh, unfilled skeleton for a company with no
        finding/employer data at all must already satisfy every required slot's keyword
        match, before any human fills anything in."""
        text = nc.render_skeleton("Fictional Fresh Co", None, None)
        path = os.path.join(self.tmp, "fictional-fresh-co-card-2026-09-09.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        card = rs.ParsedCard(path)
        self.assertEqual(card.missing_required(), [])

    def test_c_scaffolded_card_renders_with_zero_warnings(self):
        text = nc.render_skeleton("Fictional Fresh Co", None, None)
        path = os.path.join(self.tmp, "fictional-fresh-co-card-2026-09-09.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        with open(rs.TEMPLATE_PATH, encoding="utf-8") as fh:
            template_text = fh.read()
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            rs.render_one(path, os.path.join(self.tmp, "scorecards"), template_text)
            printed = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertNotIn("WARN", printed)

    def test_d_prefill_from_a_real_finding_row(self):
        self._write_finding("run1", "Fictional Fund Co", remote="PASS, nationwide",
                             ownership="Series A, venture", pm_req="live, confirmed",
                             evidence="https://example.invalid quote")
        finding = nc.load_finding("Fictional Fund Co", self.findings_dir)
        self.assertIsNotNone(finding)
        text = nc.render_skeleton("Fictional Fund Co", finding, None)
        self.assertIn("PASS, nationwide", text)
        self.assertIn("Series A, venture", text)
        self.assertIn("documents/findings/run1.jsonl", text)

    def test_e_gate_order_matches_workflow_checklist_step_numbers(self):
        keys = [k for k, _h, _s, _n in nc.SKELETON_SECTIONS]
        self.assertEqual(keys, [
            "dedup", "blocked_hardfilter", "news_layoffs", "ownership", "live_req",
            "culture", "leadership_retention", "remote_reality", "boss",
            "current_direction", "fit_read", "panel", "score_history", "sources",
        ])

    def test_f_unfilled_slot_placeholder_names_its_owed_gate_step(self):
        text = nc.render_skeleton("Fictional Fresh Co", None, None)
        self.assertIn("OWED", text)
        self.assertIn("workflow-checklist.md", text)

    def test_g_main_writes_the_expected_filename(self):
        old_argv = sys.argv
        try:
            sys.argv = ["new_card.py", "Fictional Fresh Co",
                        "--out", self.out_dir, "--findings-dir", self.findings_dir,
                        "--employers-path", self.employers_path]
            rc = nc.main()
        finally:
            sys.argv = old_argv
        self.assertEqual(rc, 0)
        import datetime
        today = datetime.date.today().isoformat()
        self.assertTrue(os.path.exists(
            os.path.join(self.out_dir, f"fictional-fresh-co-card-{today}.md")))


if __name__ == "__main__":
    unittest.main()
