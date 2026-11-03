"""Story S6 (2026-09-10): the depth-report generator counts stages from card headers and the
queue, reads the send log and the passive sampler summary, and lists each owed read once.

Fixtures are fictional companies in a temp repo; no live store is read or written.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))

import depth_report as dr  # noqa: E402

CARDS = {
    "widgetronics-card-2026-09-09.md": "# Widgetronics · fictional · panel 70/70/70 mean 70 · STATUS: 🟡 RADAR (ruled) · boss X\n\n## 5. Culture\nGlassdoor unavailable, read owed\n",
    "sprocketly-card-2026-09-09.md": "# Sprocketly · fictional · STATUS: 🟢 BUILD (ruled) · boss Y\n\n## 8. Boss\nOWED — run workflow-checklist.md step 7\n",
    "gearhouse-card-2026-09-08.md": "# Gearhouse · fictional · STATUS: 🔴 DROPPED 2026-09-08 filter 1\n\nbody\n",
    "cogworks-card-2026-09-08.md": "# Cogworks · fictional · panel 60/60/60 mean 60 · no ruling yet\n\n## 5. Culture\nOWED — not a BUILD or RADAR card so never listed\n",
    "flywheel-card-2026-09-08.md": "# Flywheel · fictional · STATUS: 🔵 PREP (stale header)\n\n## 5. Culture\nthe deep screen is still owed in prose, which is not a marker\n\n## Gate still owed\n- LinkedIn People tab for a product leader\n",
    "pulleyco-card-2026-09-07.md": "# Pulleyco · fictional · STATUS: ✅ SENT 2026-09-10\n",
    "TEMPLATE-card-2026-09-06.md": "# TEMPLATE · STATUS: BUILD\n",
}
QUEUE = "## 1 · Widgetronics (fictional) · STATUS: 🟡 RADAR\n\n## 2 · Beltline (fictional) · STATUS: NEW\n\n## 3 · Camshaft (fictional) · STATUS: NEW\n\n## 4 · Flywheel (fictional) · STATUS: 🟡 RADAR (queue synced)\n"


class DepthReportTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        st = os.path.join(self.repo, "documents", "state")
        os.makedirs(st)
        for name, text in CARDS.items():
            with open(os.path.join(st, name), "w", encoding="utf-8") as f:
                f.write(text)
        with open(os.path.join(self.repo, "documents", "outreach-queue.md"), "w", encoding="utf-8") as f:
            f.write(QUEUE)
        with open(os.path.join(self.repo, "documents", "send-log.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"date": "2026-09-10", "company": "Pulleyco", "replied": False}) + "\n")
            f.write(json.dumps({"date": "2026-09-10", "company": "Old Co", "replied": True}) + "\n")
            f.write(json.dumps({"date": "2026-09-01", "company": "Older", "replied": True}) + "\n")
        with open(os.path.join(st, "mac-time-summary.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"date": "2026-09-10", "minutes": {"find": 5, "screen": 40, "card_and_rule": 10, "build_and_send": 3, "other": 2}, "gap_minutes": 7, "samples": 60}) + "\n")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_stage_tokens(self):
        self.assertEqual(dr.card_stage("# A · STATUS: 🟡 RADAR (ruled)"), "RADAR")
        self.assertEqual(dr.card_stage("# A · STATUS: 🔴 DROPPED 2026-09-08"), "DROP")
        self.assertEqual(dr.card_stage("# A · STATUS: ✅ SENT (was BUILD)"), "SENT")
        self.assertEqual(dr.card_stage("# A · panel 60 · no ruling"), "carded_unruled")

    def test_counts_and_floors(self):
        stages, owed, skipped = dr.scan_cards(self.repo)
        c = dr.counts(stages)
        self.assertEqual((c["RADAR"], c["BUILD"], c["DROP"], c["SENT"], c["carded_unruled"]), (1, 1, 1, 1, 2))
        self.assertNotIn("TEMPLATE", stages)
        merged, disagree = dr.apply_queue(stages, dr.queue_statuses(self.repo))
        self.assertEqual(merged["flywheel"], "RADAR")  # the queue fills a header with no token
        self.assertEqual(disagree, [])
        text = dr.build(self.repo, "2026-09-10")
        self.assertIn("3 of 50 in BUILD or RADAR, gap 47", text)
        self.assertIn("BUILD 1 of 10, gap 9", text)

    def test_queue_new_without_card_counts_uncarded_only(self):
        stages, _, _ = dr.scan_cards(self.repo)
        self.assertEqual(dr.queue_new_without_card(self.repo, stages), 2)

    def test_send_log_today(self):
        self.assertEqual(dr.send_log_today(self.repo, "2026-09-10"), (2, 1))

    def test_hand_time_present_and_absent(self):
        self.assertEqual(dr.hand_time(self.repo, "2026-09-10")["minutes"]["screen"], 40)
        self.assertIsNone(dr.hand_time(self.repo, "2026-09-11"))
        self.assertIn("no samples for this date", dr.build(self.repo, "2026-09-11", write=False))

    def test_owed_reads_listed_once_and_only_on_build_radar(self):
        first = dr.build(self.repo, "2026-09-10")
        self.assertIn("3 open, 3 new", first)
        self.assertIn("widgetronics: Glassdoor unavailable, read owed", first)
        self.assertIn("flywheel: - LinkedIn People tab", first)
        self.assertNotIn("still owed in prose", first)
        self.assertNotIn("cogworks", first)
        second = dr.build(self.repo, "2026-09-10")
        self.assertIn("3 open, 0 new", second)
        # the read leaves the card: the key is dropped, a later re-appearance lists again
        p = os.path.join(self.repo, "documents", "state", "widgetronics-card-2026-09-09.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write("# Widgetronics · STATUS: 🟡 RADAR\n\n## 5. Culture\nread 2026-09-10, fine\n")
        third = dr.build(self.repo, "2026-09-10")
        self.assertIn("2 open, 0 new", third)

    def test_card_token_wins_and_disagreement_is_reported(self):
        p = os.path.join(self.repo, "documents", "state", "gearhouse-card-2026-09-08.md")
        with open(self.repo + "/documents/outreach-queue.md", "a", encoding="utf-8") as f:
            f.write("\n## 5 · Gearhouse (fictional) · STATUS: 🟡 RADAR (stale queue row)\n")
        text = dr.build(self.repo, "2026-09-10", write=False)
        self.assertIn("| Ruled RADAR | 2 |", text)          # gearhouse stays DROP by its card
        self.assertIn("gearhouse: card DROP, queue RADAR", text)
        self.assertTrue(os.path.exists(p))

    def test_print_mode_writes_nothing(self):
        dr.build(self.repo, "2026-09-10", write=False)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "documents", "state", "owed-seen.jsonl")))

    def test_unreadable_card_is_skipped_and_named(self):
        p = os.path.join(self.repo, "documents", "state", "empty-card-2026-09-10.md")
        open(p, "w").close()
        text = dr.build(self.repo, "2026-09-10", write=False)
        # The section was renamed when refused files began to be listed too (2026-09-21), and each
        # line now carries WHY. The protected behavior is unchanged: the file is named, never
        # dropped in silence. Asserting the reason as well makes it stronger, not looser.
        self.assertIn("Not read as cards, and why", text)
        self.assertIn("empty-card-2026-09-10.md: empty or unreadable", text)


if __name__ == "__main__":
    unittest.main()
