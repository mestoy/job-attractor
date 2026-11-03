"""BUG-247: `blocked-employers-list.md` occasionally uses a heading shaped
`**⛔ Filter N: other, filter number not recognized**` with an Example Co 07, arbitrary N (12, 13, 16
seen in the wild) instead of the already-established 99 "other" sentinel. Left alone, an entry
with no inline tag and no recognizable reason-vocabulary sitting under one of these headings
inherited that arbitrary N verbatim — which numerically collided with BUG-246's new base filter
12 ("Values") in `employers.jsonl`, discovered live: 13 "not recognized" rows and 10 real
"Values" rows both read `filter: 12`.

Fixtures are fictional (never a real company from the private repo, per the PII rule this test
suite runs under).
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))
import seed_employers  # noqa: E402
import build_employer_notes  # noqa: E402


FIXTURE = """\
**⛔ Filter 14: other, filter number not recognized**

- **OmegaCorp** (applied-ai, off-scale funding note, 2026-09-04). No recognizable reason \
vocabulary in this fixture on purpose, to exercise the unrecognized-heading sentinel.
- **SigmaInc** (PASS by the owner 2026-09-02, off-scale). NOT blocked pending a live-req check.
"""


class Bug247SentinelSeedEmployersTests(unittest.TestCase):
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

    def test_a_unrecognized_heading_redirects_to_the_99_sentinel_not_its_own_printed_number(self):
        entities, _notes, _parked = seed_employers.scan()
        row = entities["omegacorp"]
        self.assertEqual(row["filter"], 99)
        self.assertNotEqual(row["filter"], 14)
        self.assertEqual(row["filter_label"], "Other, filter number not recognized")

    def test_b_cleared_row_under_the_same_heading_still_gets_no_filter_number(self):
        entities, _notes, _parked = seed_employers.scan()
        row = entities["sigmainc"]
        self.assertEqual(row["status"], "cleared")
        self.assertIsNone(row["filter"])


class Bug247SentinelBuildEmployerNotesTests(unittest.TestCase):
    """kit#? 'one parser' extension: build_employer_notes.py reuses seed_employers._resolve_filter
    rather than re-deriving the same stale-heading logic a second time."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        )
        self.tmp.write(FIXTURE)
        self.tmp.close()
        self._orig_src = build_employer_notes.SRC
        build_employer_notes.SRC = self.tmp.name

    def tearDown(self):
        build_employer_notes.SRC = self._orig_src
        os.unlink(self.tmp.name)

    def test_a_notes_row_redirects_to_99_not_the_headings_own_number(self):
        rows = build_employer_notes.rows()
        omega = [r for r in rows if r["key"] == "omegacorp"]
        self.assertEqual(len(omega), 1)
        self.assertEqual(omega[0]["filter"], 99)
        self.assertNotEqual(omega[0]["filter"], 14)

    def test_b_exonerated_note_carries_no_filter_number(self):
        rows = build_employer_notes.rows()
        sigma = [r for r in rows if r["key"] == "sigmainc"]
        self.assertEqual(len(sigma), 1)
        self.assertTrue(sigma[0]["exonerated"])
        self.assertIsNone(sigma[0]["filter"])


if __name__ == "__main__":
    unittest.main()
