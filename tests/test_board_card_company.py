"""board.card_company: the ONE place a card's company NAME is read from its header.

board.parse_header splits the H1 on the middle dot and used to keep the first piece whole, so a card titled with a
dash instead ("# Fakemonth (fakemonth.example) — card, 2026-09-04") carried the whole title as its company. 98's real /app run wrote
that string to the boss registry, the feed showed it on the card, and three more readers (both build_app_feed copies and
sector_sync) took it as the company. Fixed once, here, so every reader sees the name. Fixtures are the real headers.
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import board  # noqa: E402

TABLE = [
    ("Fakemonth (fakemonth.example) — card, 2026-09-04", "Fakemonth"),
    ("Fakecertco — resolution card, 2026-09-04", "Fakecertco"),
    ("FakePilotKit — resolution card (2026-09-04)", "FakePilotKit"),
    ("Fakedrop (fakedrop.example) — seat-path card, 2026-09-04", "Fakedrop"),
    ("Fakequorble Insights — verification refresh (2026-09-05)", "Fakequorble Insights"),
    ("Fake Payer Consortium (FPC) — resolve pass, 2026-09-04", "Fake Payer Consortium"),
    ("Examplo Labs card — Pat Example, Head of Product (2026-09-05)", "Examplo Labs"),
    ("FakeDonor (FakeParent)", "FakeDonor"),
    ("Fakenav (formerly Fake Solutions Group)", "Fakenav"),
    ("Fake Compliance, resolution card (2026-09-04, orchestrator job-attractor-kit-70; three read-only seats)",
     "Fake Compliance"),
    ("Fake Compliance, resolution card", "Fake Compliance"),
]
UNCHANGED = ["Fake Information Systems", "Fakezorb.ai", "FakeCARE Portal", "Zz&Q", "Fakeco Card", "Zqramp", "FakeRx, PBC",
             "FAKEE, Inc.", "Acme, LLC", "Foo, Ltd.", "Alpha card", "Zzyzx"]


class CardCompany(unittest.TestCase):
    def test_the_real_headers_reduce_to_the_company_name(self):
        for raw, want in TABLE:
            with self.subTest(raw=raw):
                self.assertEqual(board.card_company(raw), want)

    def test_a_plain_name_is_never_changed(self):
        for name in UNCHANGED:
            with self.subTest(name=name):
                self.assertEqual(board.card_company(name), name)

    def test_a_trailing_word_card_is_only_stripped_beside_a_dash_and_only_in_lowercase(self):
        self.assertEqual(board.card_company("Fakeco Card — resolution card, 2026-09-04"), "Fakeco Card")
        self.assertEqual(board.card_company("Alpha card — resolution card"), "Alpha")
        self.assertEqual(board.card_company("Alpha card"), "Alpha card")

    def test_nothing_to_keep_falls_back_to_the_raw_text_not_an_empty_company(self):
        self.assertEqual(board.card_company("(fakemonth.example) — card"), "(fakemonth.example) — card")
        self.assertEqual(board.card_company(""), "")
        self.assertEqual(board.card_company(None), "")

    def test_it_is_idempotent(self):
        for raw, want in TABLE:
            self.assertEqual(board.card_company(board.card_company(raw)), want)


class ParseHeaderReadsTheName(unittest.TestCase):
    def test_the_fakemonth_h1_gives_the_company_fakemonth(self):
        h = board.parse_header("# Fakemonth (fakemonth.example) — card, 2026-09-04")
        self.assertEqual(h["company"], "Fakemonth")

    def test_the_exact_fake_compliance_h1_gives_the_company_name(self):
        h = board.parse_header("# Fake Compliance, resolution card (2026-09-04, orchestrator job-attractor-kit-70; three "
                               "read-only seats) · STATUS: ○ RADAR (dd's 2026-09-09/10 re-verify: live PM req orphaned; was BUILD)")
        self.assertEqual(h["company"], "Fake Compliance")
        self.assertIn("RADAR", h["status"], "the rest of the header must still parse")

    def test_a_middle_dot_header_is_unchanged(self):
        h = board.parse_header("# Widgetronics · regulated-workflow · panel 80/74/78 mean 77.3 · STATUS: 🟡 RADAR · boss Casey Dohe")
        self.assertEqual((h["company"], h["segment"], h["boss"]), ("Widgetronics", "regulated-workflow", "Casey Dohe"))


class LoadCardsGivesTheName(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="bcc_")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.state = os.path.join(self.repo, "documents", "state")
        os.makedirs(self.state)

    def write(self, name, h1):
        with open(os.path.join(self.state, name), "w") as f:
            f.write(h1 + "\n\n## Boss\nUNRESOLVED.\n")

    def test_a_card_file_carries_the_clean_company(self):
        self.write("fakemonth-card-2026-09-04.md", "# Fakemonth (fakemonth.example) — card, 2026-09-04")
        self.assertEqual(board.load_cards(self.repo)["fakemonth"]["head"]["company"], "Fakemonth")

    def test_a_non_card_document_never_gets_a_company(self):
        self.write("fakemonth-card-2026-09-04.md", "# Fakemonth (fakemonth.example) — card, 2026-09-04")
        for name in ("pat-example-call-card-2026-09-08.md", "panel-calibration-card-2026-09-08.md",
                     "dedup-card-build-bug-draft-02-2026-09-09.md"):
            self.write(name, "# Pat Example — call card, Tue 09-08")
        self.assertEqual(sorted(board.load_cards(self.repo)), ["fakemonth"])


if __name__ == "__main__":
    unittest.main()
