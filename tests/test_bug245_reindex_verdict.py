"""BUG-245 — `render_scorecard.py --reindex` read a card's ruled verdict from the HTML's
numeric panel-score div instead of the card's own STATUS tag.

Fixtures are entirely fictional (company "Widgetronics Capture", boss "Casey Doherty") —
never a real company or person from the private repo, per the PII rule this test suite
runs under. The shape (a hand-authored, pre-kit#88 scorecard template with a numeric
`<div class="big">` and the real verdict bolded inside `<div class="lbl">`) mirrors the
real Serbisyo Dash scorecard that surfaced this bug, without reusing any real content.
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))

import render_scorecard as rs  # noqa: E402


# A fictional card, ruled DROP, in the normal card-contract shape.
FICTIONAL_DROP_CARD = """# Widgetronics Capture · govtech (fictional capture-automation platform) · panel 66/64/62 mean 64 · STATUS: \U0001f534 DROP (fictional ruling, superseded by a fictional blocked-list entry) · boss Casey Doherty (Co-Founder/CEO) · remote CAUTION · 2026-09-09

Fictional company invented for this test only.

## 1. Blocked list / hard filters

Fictional blocked-list hit, superseding an earlier ruling.
"""

# A hand-authored, pre-kit#88 style scorecard HTML for the same company: the numeric
# panel mean sits in the "big" div (the legacy template's own convention), and the real
# ruled verdict is bolded inside the "lbl" div right next to it — exactly the Serbisyo Dash shape.
FICTIONAL_LEGACY_HTML = """<!doctype html>
<html><head><title>Widgetronics Capture</title></head>
<body>
<header>
  <h1>Widgetronics Capture</h1>
  <div class="verdict">
    <div class="big">64</div>
    <div class="lbl">Mean of three seats &middot; <b>DROP</b> (fictional ruling)</div>
  </div>
</header>
</body></html>
"""


class Bug245ReindexVerdictTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bug245-")
        self.out_dir = os.path.join(self.tmp, "scorecards")
        os.makedirs(self.out_dir, exist_ok=True)
        with open(os.path.join(self.tmp, "widgetronics-capture-card-2026-09-09.md"), "w", encoding="utf-8") as fh:
            fh.write(FICTIONAL_DROP_CARD)
        with open(os.path.join(self.out_dir, "widgetronics-capture-2026-09-09.html"), "w", encoding="utf-8") as fh:
            fh.write(FICTIONAL_LEGACY_HTML)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_reindex_reads_the_cards_status_tag_not_the_score_div(self):
        index_path, n = rs.build_index(self.out_dir, cards_dir=self.tmp)
        text = open(index_path, encoding="utf-8").read()
        self.assertIn("| Widgetronics Capture | DROP |", text)
        self.assertNotIn("| 64 |", text)
        self.assertEqual(n, 1)

    def test_b_falls_back_to_the_html_lbl_bold_word_when_no_card_file_matches(self):
        os.remove(os.path.join(self.tmp, "widgetronics-capture-card-2026-09-09.md"))
        index_path, _n = rs.build_index(self.out_dir, cards_dir=self.tmp)
        text = open(index_path, encoding="utf-8").read()
        self.assertIn("| Widgetronics Capture | DROP |", text)
        self.assertNotIn("| 64 |", text)

    def test_c_existing_index_rows_are_preserved_byte_for_byte_on_a_new_reindex(self):
        hand_curated = (
            "# Scorecard artifacts (hand-curated)\n\n"
            "| Company | Artifact | Page file |\n"
            "|---|---|---|\n"
            "| Widgetronics Capture — **DROP, not surfaced** (a fictional prior ruling) "
            "| on file, not handed to him: `abc123` | widgetronics-capture-2026-09-09.html |\n"
        )
        index_path = os.path.join(self.out_dir, "INDEX.md")
        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(hand_curated)

        with open(os.path.join(self.out_dir, "second-fictional-co-2026-09-09.html"), "w", encoding="utf-8") as fh:
            fh.write(FICTIONAL_LEGACY_HTML.replace("Widgetronics Capture", "Second Fictional Co"))
        with open(os.path.join(self.tmp, "second-fictional-co-card-2026-09-09.md"), "w", encoding="utf-8") as fh:
            fh.write(FICTIONAL_DROP_CARD.replace("Widgetronics Capture", "Second Fictional Co"))

        rs.build_index(self.out_dir, cards_dir=self.tmp)
        text = open(index_path, encoding="utf-8").read()
        self.assertIn("a fictional prior ruling", text)  # the old row, untouched
        self.assertIn("Second Fictional Co", text)  # the new row, appended
        self.assertNotIn("| Widgetronics Capture | DROP |", text)  # old row wasn't rewritten


if __name__ == "__main__":
    unittest.main()
