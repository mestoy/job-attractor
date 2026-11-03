"""BUG-264 — emphasis ran over BACKTICK CODE SPANS, so an underscore inside one was consumed.

The sibling of BUG-258. That fix parked finished ANCHORS behind a placeholder so `_MD_ITALIC`
could not match from one into the next; code spans got no such protection. Live on
fakko-2026-09-10.html, whose card carries two separate `check_dup.py ...` spans: italic matched
from the underscore in the first to the underscore in the second and rendered `check<i>dup.py`.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import render_scorecard as rs


class CodeSpanEmphasisTest(unittest.TestCase):
    def test_underscore_inside_a_code_span_is_not_emphasis(self):
        """The exact live shape: two code spans, each carrying an underscore."""
        src = 'Ran `check_dup.py "Ligtas Cover"` and `check_dup.py "Eric"` today.'
        out = rs._esc_md(src)
        self.assertNotIn("<i>", out)
        self.assertIn("check_dup.py", out)

    def test_emphasis_outside_code_spans_still_works(self):
        """The guard: parking code spans must not disable emphasis everywhere else."""
        out = rs._esc_md("**bold** and _slanted_ beside `a_b`")
        self.assertIn("<b>bold</b>", out)
        self.assertIn("<i>slanted</i>", out)
        self.assertIn("a_b", out)

    def test_a_link_with_an_underscore_still_survives(self):
        """BUG-258's own case must stay fixed."""
        out = rs._esc_md("see [x](https://e.invalid/Series_A_round) now")
        self.assertIn("https://e.invalid/Series_A_round", out)
        self.assertNotIn("Series<i>A</i>round", out)

    def test_real_html_in_a_code_span_is_still_escaped(self):
        out = rs._esc_md("run `<script>alert(1)</script>`")
        self.assertNotIn("<script>", out)


if __name__ == "__main__":
    unittest.main()
