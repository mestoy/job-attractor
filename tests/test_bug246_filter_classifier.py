"""BUG-246: `seed_employers.py` used to read an entry's `filter`/`filter_label` entirely from the
last `**⛔ Filter N: ...**` heading it had walked past, never from the entry's own text. A single
stale heading left undeclared for a long stretch of a real blocked list mislabeled every entry in
between with whatever reason the PREVIOUS heading named.

Fixtures are entirely fictional (never a real company from the private repo, per the PII rule
this test suite runs under), shaped after the real rows that surfaced this bug: a remote-fail
entry that had been reading as PE-owned, an entry stating its own correct filter number inline
that the old code overrode anyway, a values-fail entry with no filter code before this bug, and a
cleared/PASS entry that should carry no filter number at all.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))
import seed_employers  # noqa: E402


FIXTURE = """\
**⛔ Filter 8: PE-owned**

- **AlphaCorp** (payments, PE-owned by a control-buyout shop, 2026-09-01).
- **BetaClinic** (DROP, remote hard fail: betaclinic.example/careers states verbatim "Work \
in-person 3 days per week," a hybrid fixed-office requirement, 2026-09-10).
- **GammaLend** (DROP on hard filter (predatory-lending/subprime-collections adjacent, filter \
3): licensed as a collections agency in all 50 states, 2026-09-09).
- **DeltaHealth** (DROP, values fail per an earlier precedent: directly prices and \
underwrites health insurance, the same "dollar value on a human life" mechanism, 2026-09-09).
- **EpsilonCo** (PASS by the owner 2026-09-02, LAW-ENFORCEMENT CUSTOMERS). Fresh seed, clean \
investors, but the company's own site names police departments as customers; NOT blocked \
pending a live-req check.
- **ZetaWidgets** (applied-ai, off-scale funding note, 2026-09-04). No recognizable reason \
vocabulary in this fixture on purpose, to exercise the section-heading fallback.
- **EtaVoice** (speech-AI API platform, clean VC) — DROP, culture: a culture sweep found n=43 \
Glassdoor reviews with a recurring, corroborated toxic-leadership theme across independent \
reviewers, 2026-09-10. Shaped after the real Tinig AI/Liwanag Health entries that surfaced \
BUG-247's culture-keyword gap.
"""


class Bug246FilterClassifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        )
        self.tmp.write(FIXTURE)
        self.tmp.close()
        self._orig_src = seed_employers.SRC
        seed_employers.SRC = self.tmp.name

    def tearDown(self):
        seed_employers.SRC = self._orig_src
        os.unlink(self.tmp.name)

    def test_a_genuine_pe_row_still_reads_8(self):
        entities, _notes, _parked = seed_employers.scan()
        row = entities["alphacorp"]
        self.assertEqual(row["filter"], 8)
        self.assertEqual(row["filter_label"], "PE-owned")

    def test_b_remote_fail_row_is_no_longer_mislabeled_pe(self):
        entities, _notes, _parked = seed_employers.scan()
        row = entities["betaclinic"]
        self.assertEqual(row["filter"], 1)
        self.assertNotEqual(row["filter"], 8)

    def test_c_inline_filter_tag_wins_over_the_stale_heading(self):
        entities, _notes, _parked = seed_employers.scan()
        row = entities["gammalend"]
        self.assertEqual(row["filter"], 3)
        self.assertEqual(row["filter_label"], "Law-enforcement or policing customers")

    def test_d_values_fail_reads_the_new_filter_12(self):
        entities, _notes, _parked = seed_employers.scan()
        row = entities["deltahealth"]
        self.assertEqual(row["filter"], 12)
        self.assertIn("Values", row["filter_label"])

    def test_d2_the_precedent_branch_alone_reads_filter_12(self):
        """The classifier's own precedent phrase, with none of the other filter-12 words, so this
        branch is exercised by something and cannot lose its coverage unnoticed."""
        pattern = next(p for n, p in seed_employers.FILTER_KEYWORDS if n == 12)
        self.assertTrue(pattern.search("dropped per the FAKE-precedent-12 ruling"))
        self.assertFalse(pattern.search("dropped per the earlier ruling"))

    def test_e_cleared_pass_row_carries_no_filter_number_at_all(self):
        entities, _notes, _parked = seed_employers.scan()
        row = entities["epsilonco"]
        self.assertEqual(row["status"], "cleared")
        self.assertIsNone(row["filter"])
        self.assertIsNone(row["filter_label"])

    def test_f_no_keyword_match_falls_back_to_section_heading(self):
        entities, _notes, _parked = seed_employers.scan()
        row = entities["zetawidgets"]
        self.assertEqual(row["filter"], 8)  # the only remaining source: the section state
        self.assertEqual(row["filter_label"], "PE-owned")

    def test_g_culture_fail_reads_filter_0_not_the_stale_pe_heading(self):
        # BUG-247 live find (98, on Tinig AI/Liwanag Health): a culture-fail DROP under a
        # stale "Filter 8: PE-owned" heading used to inherit filter 8 verbatim, since the
        # keyword tier had no culture vocabulary at all.
        entities, _notes, _parked = seed_employers.scan()
        row = entities["etavoice"]
        self.assertEqual(row["filter"], 0)
        self.assertNotEqual(row["filter"], 8)
        self.assertIsNotNone(row["filter_label"])


if __name__ == "__main__":
    unittest.main()
