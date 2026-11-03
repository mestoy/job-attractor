"""BUG-250 (the owner's ruling, "Render plus owed boxes"): render_scorecard.py emits the
approved template's section names/shape — "Three seats on the thesis fit" (seat prose, the
history table, and the sector line folded into one section), "Thesis fit against the
record", the four-part Lead-with/Own-plainly/What-would-change/Owed-before-any-note notes,
and "Recommended path" — instead of the old "Panel"/"Sector"/"Score history"/"Fit read"
layout. The three sections with no corresponding 13-slot card content render as clearly
marked OWED boxes rather than fabricating a table, notes, or an action list a human never
wrote. Dedup also moves from a note box into a real gate tile, and every gate gets a real
pill reading instead of the constant "FOUND".

Fixtures are entirely fictional (never a real company or person from the private repo, per
the PII rule this test suite runs under).
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


FULL_CARD_WITH_PROSE = """# Fictional Fabrics Co · applied-ai · RADAR · panel 80/78/82 mean 80.0 · GOOD FIT/IN · 2026-09-09

A remote-first fictional textiles-AI company, invented for this test only.

## 0. Dedup check

CLEAN. check_dup.py reports NEW, no prior record.

## 1. Blocked list / hard filters

CLEAN, confirmed no PE, no defense exposure.

## 2. Industry news & layoffs (12 mo)

None found.

## 3. Culture

UNPROVEN — Glassdoor base too thin for a real read at this size.

## 4. Leadership & retention

Jordan Rivers, fictional Co-Founder & CEO, no churn signal.

## 5. Remote reality

PASS, "remote-first" per the fictional careers page.

## 6. Ownership

Fictional Series A, venture-backed, not PE.

## 7. Boss

Jordan Rivers, fictional CEO, fallback boss.

## 8. Live PM req

RADAR register — no live req found, fictional Head of Product function only.

## Product team

3 named, fictional roster.

## 9. Current Direction

2026-09-01 — fictional funding announcement.

## 10. Fit read

STRONG. Fictional process-mapping overlap.

## 11. Panel

- **CPO seat** 80 — a fictional reasoning sentence about the CPO seat.
- **CTO seat** 78 — a fictional reasoning sentence about the CTO seat.
- **CEO seat** 82 — a fictional reasoning sentence about the CEO seat.
- Mean 80.0 -> GOOD FIT/IN

## 12. Score history

| Date | Mean |
|---|---|
| 2026-09-09 | 80.0 |

## Sources, with links

- [Company site](https://example.invalid/fictional-fabrics/about)
"""


class Bug250TemplateFormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bug250-")
        self.card_path = os.path.join(self.tmp, "fictional-fabrics-card-2026-09-09.md")
        with open(self.card_path, "w", encoding="utf-8") as fh:
            fh.write(FULL_CARD_WITH_PROSE)
        self.out_dir = os.path.join(self.tmp, "scorecards")
        with open(rs.TEMPLATE_PATH, encoding="utf-8") as fh:
            self.template_text = fh.read()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _render(self):
        out_path = rs.render_one(self.card_path, self.out_dir, self.template_text, quiet=True)
        return open(out_path, encoding="utf-8").read()

    def test_a_dedup_renders_as_a_gate_tile_not_a_note(self):
        html_text = self._render()
        self.assertIn('<div class="name">Dedup check</div>', html_text)
        # 10 gates now: the 9 pre-existing plus dedup
        self.assertEqual(html_text.count('<div class="gate">'), 10)

    def test_b_gate_pills_reflect_each_gates_real_reading(self):
        html_text = self._render()
        self.assertIn('<span class="pill good">PASS</span><div class="name">Blocked list', html_text)
        self.assertIn('<span class="pill warn">UNPROVEN</span><div class="name">Culture', html_text)
        self.assertIn('<span class="pill acc">RADAR</span><div class="name">Live PM req', html_text)

    def test_c_seats_section_is_renamed_and_folds_history_and_sector_in(self):
        html_text = self._render()
        self.assertIn("<h2>Three seats on the thesis fit</h2>", html_text)
        self.assertNotIn("<h2>Panel</h2>", html_text)
        self.assertNotIn("<h2>Sector</h2>", html_text)
        self.assertNotIn("<h2>Score history</h2>", html_text)
        # the seat's own reasoning sentence is carried, not just the number
        self.assertIn("a fictional reasoning sentence about the CPO seat", html_text)
        # history table and sector line both live inside the same section now
        seats_start = html_text.index("<h2>Three seats on the thesis fit</h2>")
        seats_section_end = html_text.index("</section>", seats_start)
        seats_block = html_text[seats_start:seats_section_end]
        self.assertIn('<div class="histwrap">', seats_block)
        self.assertIn('class="sectorline pending"', seats_block)

    def test_d_thesis_fit_section_renders_the_real_fit_read_plus_an_owed_marker(self):
        html_text = self._render()
        self.assertIn("<h2>Thesis fit against the record</h2>", html_text)
        self.assertIn("STRONG. Fictional process-mapping overlap.", html_text)
        self.assertIn("not yet part of this card&#x27;s contract", html_text)

    def test_e_recommended_path_is_always_an_owed_box(self):
        html_text = self._render()
        self.assertIn("<h2>Recommended path</h2>", html_text)
        self.assertIn('<span class="pill warn">OWED</span> A structured next-step sequence', html_text)

    def test_f_theme_toggle_is_preserved(self):
        html_text = self._render()
        self.assertIn('<div class="theme-toggle"', html_text)
        self.assertIn('data-set-theme="light"', html_text)
        self.assertIn('data-set-theme="dark"', html_text)
        self.assertIn('data-set-theme="system"', html_text)


if __name__ == "__main__":
    unittest.main()
