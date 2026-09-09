"""kit #88 — scripts/render_scorecard.py turns a card markdown into an HTML scorecard.

Fixtures are entirely fictional (company "Fictional Fabrics Co", boss "Jordan Rivers",
etc.) — never a real company or person from the private repo, per the PII rule this test
suite runs under. Shapes (section set, verdict placement, thin DROP cards) mirror the
patterns documents/state/scorecard-contract-survey-53-2026-09-09.md found across the 67
real cards, without reusing any real content.
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


FULL_CARD = """# Fictional Fabrics Co · applied-ai · RADAR · panel 80/78/82 mean 80.0 · GOOD FIT/IN · 2026-09-09

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

Jordan Rivers, fictional CEO, fallback boss.

## 8. Live PM req

CONFIRMED LIVE, fictional Head of Product req.

## 9. Current Direction

2026-09-01 — fictional funding announcement.

## 10. Fit read

STRONG. Fictional process-mapping overlap.

## 11. Panel

- CPO 80
- CTO 78
- CEO 82
- Mean 80.0 -> GOOD FIT/IN

## Score history

| Date | Seats | Mean |
|---|---|---|
| 2026-09-09 | 80/78/82 | 80.0 |

## Product team

3 named, fictional roster.

## Ask register suggestion

Direct application-track ask, fictional.

## Sources, with links

- [Fictional Fabrics Co, About](https://example.invalid/fictional-fabrics/about) — company overview.
- [Jordan Rivers, LinkedIn](https://example.invalid/in/jordan-rivers) — boss profile.
"""

THIN_DROP_CARD = """# Widget Sprockets Inc · DROP · 2026-09-09

Invented fixture, fails the first gate.

## 1. Blocked list / hard filters

BLOCKED — fictional defense-sector exposure, gate fails here, card stops.
"""

NOT_A_CARD = """# Draft notes, not a company

This is a bug-draft scratch file, not a real screened company.
"""

RESOLUTION_CARD = """# Gizmo Werks — resolution card (2026-09-09)

**VERDICT: BUILD-READY (radar/value-reach, no live req).** Invented fixture, a different
document genre from a fit card: no Panel, Score history, or Sources section at all.

## 1. Remote posture — STILL UNSTATED

Fictional, no ATS exists.

## 2. Ownership and politics — CLEAN

Fictional seed round, not PE.

## 3. Boss

Jordan Rivers, fictional founder.
"""

NO_VERDICT_CARD = """# Anonymized Aerostructures · applied-ai · 2026-09-09

Invented fixture with no verdict token of any kind anywhere in the file.

## 1. Blocked list / hard filters

CLEAN, fictional.
"""


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit88-scorecard-")
        self.card_path = os.path.join(self.tmp, "fictional-fabrics-card-2026-09-09.md")
        with open(self.card_path, "w", encoding="utf-8") as fh:
            fh.write(FULL_CARD)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_full_card_matches_every_required_slot(self):
        card = rs.ParsedCard(self.card_path)
        missing = card.missing_required()
        self.assertEqual(missing, [], f"unexpectedly missing: {missing}")

    def test_b_header_wording_variants_still_match_the_same_slot(self):
        # The survey's headline finding: header TEXT varies, the SLOT is what's stable.
        variant = FULL_CARD.replace(
            "## 11. Panel", "## 11. Panel (calibration addendum applied verbatim)"
        )
        path = os.path.join(self.tmp, "variant-card-2026-09-09.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(variant)
        card = rs.ParsedCard(path)
        found = card.slot(rs.REQUIRED_SLOTS[10][2])  # panel
        self.assertIsNotNone(found)

    def test_c_verdict_extracted_from_title_line(self):
        card = rs.ParsedCard(self.card_path)
        self.assertEqual(card.verdict, "RADAR")

    def test_d_company_name_extracted_from_title_line(self):
        card = rs.ParsedCard(self.card_path)
        self.assertEqual(card.company, "Fictional Fabrics Co")


class VerdictAwareValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit88-verdict-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_a_thin_drop_card_is_not_flagged_as_broken(self):
        # A DROP card stopping after gate 1 is BY DESIGN (survey's thin-card cluster),
        # not a defect — is_not_a_card() must not treat it as a non-card, and a real
        # render must succeed even though most required slots are absent.
        path = self._write("widget-sprockets-card-2026-09-09.md", THIN_DROP_CARD)
        self.assertIsNone(rs.is_not_a_card(path))
        card = rs.ParsedCard(path)
        self.assertEqual(card.verdict, "DROP")
        self.assertGreater(len(card.missing_required()), 0)

    def test_b_not_a_card_file_is_skipped(self):
        path = self._write("dedup-card-build-bug-draft-02-2026-09-09.md", NOT_A_CARD)
        reason = rs.is_not_a_card(path)
        self.assertIsNotNone(reason)
        self.assertIn("non-card pattern", reason)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit88-render-")
        self.card_path = os.path.join(self.tmp, "fictional-fabrics-card-2026-09-09.md")
        with open(self.card_path, "w", encoding="utf-8") as fh:
            fh.write(FULL_CARD)
        self.out_dir = os.path.join(self.tmp, "scorecards")
        with open(rs.TEMPLATE_PATH, encoding="utf-8") as fh:
            self.template_text = fh.read()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_render_writes_html_with_company_and_verdict(self):
        out_path = rs.render_one(self.card_path, self.out_dir, self.template_text, quiet=True)
        self.assertTrue(os.path.exists(out_path))
        html_text = open(out_path, encoding="utf-8").read()
        self.assertIn("Fictional Fabrics Co", html_text)
        self.assertIn("RADAR", html_text)
        self.assertIn("example.invalid", html_text)  # sourced link carried through

    def test_a2_bulleted_panel_shape_renders_the_seats_section(self):
        """scorecard-parity-fix-53-2026-09-09.md: most real cards write seat scores as a
        bulleted list ("- CPO 82 ... - CTO 75 ... - CEO 78"), not a slash-triple, and the
        old regex silently rendered NO seats section at all for that shape. FULL_CARD's own
        Panel section is already bulleted (see fixture above) — this asserts the seats
        actually appear, not just that the render doesn't crash."""
        out_path = rs.render_one(self.card_path, self.out_dir, self.template_text, quiet=True)
        html_text = open(out_path, encoding="utf-8").read()
        self.assertIn('class="seats"', html_text)
        self.assertIn("CPO seat", html_text)
        self.assertIn(">80<", html_text)  # the CPO score from the fixture
        self.assertIn(">78<", html_text)  # CTO
        self.assertIn(">82<", html_text)  # CEO

    def test_a3_slash_triple_panel_shape_still_renders(self):
        """Regression guard: the original slash-triple shape ("80/78/82") must still work
        after adding the bulleted-list fallback."""
        slash_card = FULL_CARD.replace(
            "## 11. Panel\n\n- CPO 80\n- CTO 78\n- CEO 82\n- Mean 80.0 -> GOOD FIT/IN\n",
            "## 11. Panel\n\nSeats 80/78/82, mean 80.0 -> GOOD FIT/IN\n",
        )
        self.assertNotEqual(slash_card, FULL_CARD)  # the replace actually matched something
        path = os.path.join(self.tmp, "slash-triple-card-2026-09-09.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(slash_card)
        out_path = rs.render_one(path, self.out_dir, self.template_text, quiet=True)
        html_text = open(out_path, encoding="utf-8").read()
        self.assertIn('class="seats"', html_text)
        self.assertIn(">80<", html_text)

    def test_b_render_carries_the_canonical_css(self):
        out_path = rs.render_one(self.card_path, self.out_dir, self.template_text, quiet=True)
        html_text = open(out_path, encoding="utf-8").read()
        self.assertIn("--accent:#22507A", html_text)

    def test_b2_render_carries_the_light_dark_toggle_and_both_token_blocks(self):
        """Michael's ruling, 2026-09-09: the scorecard should offer light and dark mode. The
        template already carries the light tokens on bare :root and the dark override guarded
        by :root:not([data-theme="light"]) plus :root[data-theme="dark"]; a rendered card must
        carry all of that PLUS the inline toggle (no external script, no CDN)."""
        out_path = rs.render_one(self.card_path, self.out_dir, self.template_text, quiet=True)
        html_text = open(out_path, encoding="utf-8").read()
        # both token blocks
        self.assertIn(":root{", html_text)
        self.assertIn(':root:not([data-theme="light"])', html_text)
        self.assertIn(':root[data-theme="dark"]', html_text)
        # the toggle itself: three buttons, no external script tag
        self.assertIn('class="theme-toggle"', html_text)
        self.assertIn('data-set-theme="light"', html_text)
        self.assertIn('data-set-theme="dark"', html_text)
        self.assertIn('data-set-theme="system"', html_text)
        self.assertNotRegex(html_text, r'<script[^>]+src=')
        # persists via localStorage, wrapped so a blocked/absent store never breaks the page
        self.assertIn("localStorage", html_text)
        self.assertIn("try {", html_text)
        self.assertIn("catch (e)", html_text)

    def test_b3_gates_grid_holds_only_true_gate_slots(self):
        """scorecard-parity-fix follow-up (2026-09-09): the gates grid must hold exactly the
        9 true gate-shaped slots — current-direction/fit-read/score-history/sources etc. get
        their own sections instead of being dumped in as generic 'FOUND' tiles."""
        out_path = rs.render_one(self.card_path, self.out_dir, self.template_text, quiet=True)
        html_text = open(out_path, encoding="utf-8").read()
        self.assertEqual(html_text.count('<div class="gate">'), 9)

    def test_b4_score_history_renders_as_a_real_table(self):
        out_path = rs.render_one(self.card_path, self.out_dir, self.template_text, quiet=True)
        html_text = open(out_path, encoding="utf-8").read()
        self.assertIn('<div class="histwrap">', html_text)
        self.assertIn("<th>Date</th>", html_text)
        self.assertIn("<td>2026-09-09</td>", html_text)

    def test_b5_sector_section_is_honestly_pending_not_fabricated(self):
        """No sector-sync data source is shipped yet — the renderer must say so, never invent
        n/median/Q1/Q3 numbers it has no way to compute."""
        out_path = rs.render_one(self.card_path, self.out_dir, self.template_text, quiet=True)
        html_text = open(out_path, encoding="utf-8").read()
        self.assertIn('class="sectorline pending"', html_text)
        self.assertNotRegex(html_text, r"median\s*\d")

    def test_b6_sources_carry_typed_tags(self):
        # PII gate note: a LinkedIn profile-slug URL shape always blocks, fictional or not — so
        # this uses a linkedin.com URL the gate's own pattern doesn't match, which still
        # exercises the real "boss" heuristic (it keys on the linkedin.com domain, not on any
        # particular path shape).
        self.assertEqual(rs._source_tag("Jordan Rivers, LinkedIn",
                                         "https://linkedin.com/company/fictional-fabrics"), "boss")
        self.assertEqual(rs._source_tag("Fictional Fabrics Co, careers",
                                         "https://boards.greenhouse.io/fictionalfabrics"), "req")
        self.assertEqual(rs._source_tag("Fictional Fabrics Co, About",
                                         "https://example.invalid/fictional-fabrics/about"), "company")

    def test_b7_notes_section_uses_the_slots_real_label_not_invented_framing(self):
        """Lead-with/Own-plainly framing is curated analysis with no source slot in the
        13-slot contract; the renderer must not invent it. It uses the real slot's own
        label (e.g. 'Current Direction') instead."""
        out_path = rs.render_one(self.card_path, self.out_dir, self.template_text, quiet=True)
        html_text = open(out_path, encoding="utf-8").read()
        self.assertIn("<h3>Current Direction</h3>", html_text)
        self.assertNotIn("Lead with", html_text)
        self.assertNotIn("Own plainly", html_text)

    def test_c_thin_drop_card_still_renders_without_crashing(self):
        drop_path = os.path.join(self.tmp, "widget-sprockets-card-2026-09-09.md")
        with open(drop_path, "w", encoding="utf-8") as fh:
            fh.write(THIN_DROP_CARD)
        out_path = rs.render_one(drop_path, self.out_dir, self.template_text, quiet=True)
        self.assertTrue(os.path.exists(out_path))

    def test_d_not_a_card_file_produces_no_html(self):
        bad_path = os.path.join(self.tmp, "panel-calibration-card-2026-09-09.md")
        with open(bad_path, "w", encoding="utf-8") as fh:
            fh.write(NOT_A_CARD)
        result = rs.render_one(bad_path, self.out_dir, self.template_text, quiet=True)
        self.assertIsNone(result)


class BackfillAndIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit88-backfill-")
        with open(os.path.join(self.tmp, "fictional-fabrics-card-2026-09-09.md"), "w", encoding="utf-8") as fh:
            fh.write(FULL_CARD)
        with open(os.path.join(self.tmp, "widget-sprockets-card-2026-09-09.md"), "w", encoding="utf-8") as fh:
            fh.write(THIN_DROP_CARD)
        with open(os.path.join(self.tmp, "dedup-card-build-bug-draft-02-2026-09-09.md"), "w", encoding="utf-8") as fh:
            fh.write(NOT_A_CARD)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_backfill_renders_real_cards_and_skips_non_cards(self):
        old_stdout = sys.stdout
        try:
            import io
            sys.stdout = io.StringIO()
            rs.main.__globals__["sys"].argv = ["render_scorecard.py", "--backfill", self.tmp]
            rs.main()
        finally:
            sys.stdout = old_stdout
        out_dir = os.path.join(self.tmp, "scorecards")
        files = [f for f in os.listdir(out_dir) if f.endswith(".html")]
        self.assertEqual(len(files), 2)  # fictional-fabrics + widget-sprockets, not the draft

    def test_b_backfill_is_idempotent_on_a_second_run(self):
        rs.main.__globals__["sys"].argv = ["render_scorecard.py", "--backfill", self.tmp]
        rs.main()
        out_dir = os.path.join(self.tmp, "scorecards")
        before = sorted(os.listdir(out_dir))
        rs.main()
        after = sorted(os.listdir(out_dir))
        self.assertEqual(before, after)

    def test_c_reindex_builds_index_md_from_rendered_html(self):
        rs.main.__globals__["sys"].argv = ["render_scorecard.py", "--backfill", self.tmp]
        rs.main()
        out_dir = os.path.join(self.tmp, "scorecards")
        rs.main.__globals__["sys"].argv = ["render_scorecard.py", "--reindex", out_dir]
        rs.main()
        index_path = os.path.join(out_dir, "INDEX.md")
        self.assertTrue(os.path.exists(index_path))
        index_text = open(index_path, encoding="utf-8").read()
        self.assertIn("Fictional Fabrics Co", index_text)
        self.assertIn("Widget Sprockets Inc", index_text)

    def test_d_reindex_respects_surfaced_verdicts_filter(self):
        rs.main.__globals__["sys"].argv = ["render_scorecard.py", "--backfill", self.tmp]
        rs.main()
        out_dir = os.path.join(self.tmp, "scorecards")
        old = rs.SURFACED_VERDICTS
        try:
            rs.SURFACED_VERDICTS = ["RADAR", "BUILD"]
            index_path, _n = rs.build_index(out_dir)
            index_text = open(index_path, encoding="utf-8").read()
            self.assertIn("not surfaced", index_text)  # the DROP card
        finally:
            rs.SURFACED_VERDICTS = old


class Kit88DryRunFollowupTests(unittest.TestCase):
    """kit #88 dry-run findings, 2026-09-09: backfill discovery gap, resolution-card
    genre, and silent-UNKNOWN-verdict cards. Fictional fixtures only."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit88-followup-")
        with open(rs.TEMPLATE_PATH, encoding="utf-8") as fh:
            self.template_text = fh.read()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    # (1) backfill discovery regex now accepts a "-card-<anything>-YYYY-MM-DD.md" tail,
    # so the skip list (not a silent glob miss) is what decides a non-card file's fate.
    def test_a_backfill_discovery_accepts_a_non_date_adjacent_card_tail(self):
        self._write(
            "dedup-card-build-bug-draft-02-2026-09-09.md",
            NOT_A_CARD,
        )
        old_stdout = sys.stdout
        try:
            import io
            sys.stdout = io.StringIO()
            rs.main.__globals__["sys"].argv = ["render_scorecard.py", "--backfill", self.tmp]
            rs.main()
            printed = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertIn("SKIP dedup-card-build-bug-draft-02-2026-09-09.md", printed)
        self.assertIn("non-card pattern", printed)

    # (2) a resolution-card genre file renders with one INFO line, not a WARN stack.
    def test_b_resolution_card_genre_is_named_not_warned(self):
        path = self._write("gizmo-werks-card-2026-09-09.md", RESOLUTION_CARD)
        card = rs.ParsedCard(path)
        self.assertTrue(card.is_resolution_genre())

        old_stdout = sys.stdout
        try:
            import io
            sys.stdout = io.StringIO()
            rs.render_one(path, os.path.join(self.tmp, "scorecards"), self.template_text)
            printed = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertIn("resolution card, not a fit card", printed)
        self.assertNotIn("WARN", printed)

    def test_c_a_fit_card_missing_its_core_trio_but_no_resolution_title_still_warns(self):
        # Guard against over-matching: a normal fit-shaped title must not get the
        # resolution pass just because it also happens to lack Panel/Score-history/Sources.
        thin_but_not_resolution = THIN_DROP_CARD.replace("DROP", "BUILD")
        path = self._write("widget-sprockets-card-2026-09-09.md", thin_but_not_resolution)
        card = rs.ParsedCard(path)
        self.assertFalse(card.is_resolution_genre())

    # (3) a card with no verdict token anywhere prints one INFO line naming the file.
    def test_d_no_verdict_token_prints_one_info_line(self):
        path = self._write("anonymized-aerostructures-card-2026-09-09.md", NO_VERDICT_CARD)
        old_stdout = sys.stdout
        try:
            import io
            sys.stdout = io.StringIO()
            rs.render_one(path, os.path.join(self.tmp, "scorecards"), self.template_text)
            printed = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertIn(
            "INFO anonymized-aerostructures-card-2026-09-09.md: no verdict token", printed
        )


if __name__ == "__main__":
    unittest.main()
