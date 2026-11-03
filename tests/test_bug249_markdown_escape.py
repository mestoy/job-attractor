"""BUG-249: gate "why" text, note-box snippets, and table snippet/empty-note fields echoed a
card's own `**bold**`/`*italic*`/`[text](url)` markdown as literal characters instead of real
HTML — `_esc()` only ever HTML-escaped, never converted. Confirmed live on a real scorecard's
"Boss" and "Live PM req" gates.

Fixtures are fictional (never a real company or person from the private repo, per the PII rule
this test suite runs under).
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


class EscMdUnitTests(unittest.TestCase):
    def test_a_bold_converts_to_a_real_tag(self):
        self.assertEqual(rs._esc_md("plain **bold** text"), "plain <b>bold</b> text")

    def test_b_italic_converts_to_a_real_tag(self):
        self.assertEqual(rs._esc_md("plain *italic* text"), "plain <i>italic</i> text")
        self.assertEqual(rs._esc_md("plain _italic_ text"), "plain <i>italic</i> text")

    def test_c_link_converts_to_a_real_anchor(self):
        out = rs._esc_md("see [the source](https://example.com/page)")
        self.assertEqual(
            out,
            'see <a href="https://example.com/page" target="_blank" rel="noopener">the source</a>',
        )

    def test_d_all_three_together_plus_a_stray_asterisk(self):
        raw = "**Jordan Rivers** ([profile](https://example.com/jordan)) is *credible*, per one voice — a stray * on its own."
        out = rs._esc_md(raw)
        self.assertIn("<b>Jordan Rivers</b>", out)
        self.assertIn('<a href="https://example.com/jordan" target="_blank" rel="noopener">profile</a>', out)
        self.assertIn("<i>credible</i>", out)
        self.assertIn("a stray * on its own", out)  # unmatched lone asterisk stays literal

    def test_e_real_html_in_source_text_still_comes_out_escaped_not_live(self):
        out = rs._esc_md("a **bold** claim <script>alert(1)</script>")
        self.assertIn("<b>bold</b>", out)
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_f_short_structured_fields_are_untouched_by_the_markdown_pass(self):
        # BUG-249 Q1 default: only the three free-prose call sites route through _esc_md.
        # A company name containing a literal asterisk must pass through plain _esc()
        # unconverted at every other call site.
        self.assertEqual(rs._esc("Foo* Inc"), "Foo* Inc")


FULL_CARD_WITH_MARKDOWN = """# Fictional Fabrics Co · applied-ai · RADAR · panel 80/78/82 mean 80.0 · GOOD FIT/IN · 2026-09-09

A remote-first fictional textiles-AI company, invented for this test only.

## 1. Blocked list / hard filters

CLEAN, no PE, no defense exposure.

## 2. Industry news & layoffs (12 mo)

None found.

## 3. Culture

Glassdoor reads well, invented for this fixture.

## 4. Leadership & retention

Jordan Rivers, fictional Co-Founder & CEO, no churn signal.

## 5. Remote reality

PASS, "remote-first" per the fictional careers page.

## 6. Ownership

Fictional Series A, venture-backed, not PE.

## 7. Boss

**Jordan Rivers** ([company bio](https://example.com/jordan)), *fictional* CEO, fallback boss.

## 8. Live PM req

**CONFIRMED LIVE**, fictional Head of Product req.

## 9. Current Direction

2026-09-01 — fictional funding announcement.

## 10. Fit read

STRONG. Fictional process-mapping overlap.

## 11. Panel

- CPO 80
- CTO 78
- CEO 82
- Mean 80.0

## 12. Score history

| Date | Mean |
|---|---|
| 2026-09-09 | 80.0 |

## Sources

- [Company site](https://example.com)
"""


class Bug249RenderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bug249-")
        self.card_path = os.path.join(self.tmp, "fictional-fabrics-card-2026-09-09.md")
        with open(self.card_path, "w", encoding="utf-8") as fh:
            fh.write(FULL_CARD_WITH_MARKDOWN)
        with open(rs.TEMPLATE_PATH, encoding="utf-8") as fh:
            self.template_text = fh.read()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_boss_gate_shows_real_bold_and_a_real_link_not_asterisks(self):
        card = rs.ParsedCard(self.card_path)
        html_out = rs.render_card_html(card, self.template_text)
        self.assertIn("<b>Jordan Rivers</b>", html_out)
        self.assertIn('<a href="https://example.com/jordan" target="_blank" rel="noopener">company bio</a>', html_out)
        self.assertIn("<i>fictional</i>", html_out)
        self.assertNotIn("**Jordan Rivers**", html_out)

    def test_b_live_req_gate_shows_real_bold(self):
        card = rs.ParsedCard(self.card_path)
        html_out = rs.render_card_html(card, self.template_text)
        self.assertIn("<b>CONFIRMED LIVE</b>", html_out)
        self.assertNotIn("**CONFIRMED LIVE**", html_out)


if __name__ == "__main__":
    unittest.main()
