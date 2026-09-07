"""Red-green for the 2026-09-05 Neighborly miss: a blocked-list row annotated 'EXONERATED <date> (Michael's ruling)'
was still read as a block by check_dup and seed_employers because exoneration.EXONERATED only matched the
older literals ('not blocked', 'entry corrected', ...). The word the seats actually write must clear too."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import exoneration  # noqa: E402


class ExonerationPhrase(unittest.TestCase):
    def test_exonerated_word_clears(self):
        row = "- **Neighborly Software** (govtech, 2026-07-25). remote fail ⚖️ **EXONERATED 2026-09-05 (Michael's ruling):** own Ashby board says Remote"
        self.assertTrue(exoneration.EXONERATED.search(row.lower()))

    def test_older_literals_still_clear(self):
        for s in ("not blocked as of 2026-09-05", "entry corrected", "deferred", "⏭️ skipped"):
            self.assertTrue(exoneration.EXONERATED.search(s.lower()), s)

    def test_plain_block_does_not_clear(self):
        for s in ("- **Acme** (payments, 2026-07-25). remote fail", "corrected the CEO name, still blocked"):
            self.assertFalse(exoneration.EXONERATED.search(s.lower()), s)


if __name__ == "__main__":
    unittest.main()
