"""Story S30 (2026-09-10): scorecard_repalette.py swaps only the six state tokens per theme block
and adds the glyph rules, leaves every other byte alone, and is idempotent."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import scorecard_repalette as rp  # noqa: E402

PAGE = """<style>
:root{ --paper:#F3F5F7; %s --bar-track:#E3E8EE; }
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){ %s } }
:root[data-theme="dark"]{ %s }
.pill.good{background:var(--good-soft);color:var(--good)}
%s
</style><section class="path"><h2>Recommended path</h2><ol><li>hand-written, must survive</li></ol></section>
""" % (rp.LIGHT_OLD, rp.DARK_OLD, rp.DARK_OLD, rp.GLYPH_ANCHOR)


class RepaletteTest(unittest.TestCase):
    def test_tokens_swapped_glyphs_added_content_kept(self):
        new, changed, notes = rp.repalette(PAGE)
        self.assertTrue(changed)
        self.assertNotIn("#2E7D5B", new)
        self.assertNotIn("#7CC9A3", new)
        self.assertEqual(new.count(rp.DARK_NEW), 2)
        self.assertIn('.pill.good::before{content:"\\2713"}', new)
        self.assertIn("hand-written, must survive", new)
        self.assertIn("light tokens x1", notes)
        self.assertIn("dark tokens x2", notes)

    def test_viewport_meta_added_once(self):
        new, changed, notes = rp.repalette("<title>X</title>" + PAGE)
        self.assertIn("viewport added", notes)
        self.assertEqual(new.count('name="viewport"'), 1)
        again, changed2, notes2 = rp.repalette(new)
        self.assertEqual(again.count('name="viewport"'), 1)
        self.assertFalse(changed2)

    def test_wrap_backfilled_once_and_only_on_the_body_rule(self):
        page = "<style>" + rp.BODY_OLD + "</style>" + PAGE
        new, changed, notes = rp.repalette(page)
        self.assertIn("wrap added", notes)
        self.assertIn("overflow-wrap:anywhere", new)
        self.assertEqual(new.count("overflow-wrap:anywhere"), 1)
        again, changed2, _ = rp.repalette(new)
        self.assertEqual(again.count("overflow-wrap:anywhere"), 1)  # never doubles
        self.assertFalse(changed2)

    def test_page_without_the_body_rule_is_left_alone(self):
        new, _, notes = rp.repalette(PAGE)
        self.assertNotIn("wrap added", notes)
        self.assertNotIn("overflow-wrap", new)

    def test_caption_contrast_fixed_once_and_dark_theme_untouched(self):
        page = "<style>:root{" + rp.INK3_OLD + "}" + "@media(prefers-color-scheme:dark){--ink-3:#8290A2;}</style>" + PAGE
        out, _changed, notes = rp.repalette(page)
        self.assertIn("caption contrast fixed", notes)
        self.assertIn("--ink-3:#657181;", out)
        self.assertIn("#8290A2", out)          # the dark theme already passes; never touched
        again, changed2, _ = rp.repalette(out)
        self.assertEqual(again.count("--ink-3:#657181;"), 1)
        self.assertFalse(changed2)

    def test_idempotent(self):
        once, _, _ = rp.repalette(PAGE)
        twice, changed, notes = rp.repalette(once)
        self.assertFalse(changed)
        self.assertEqual(once, twice)

    def test_one_unwritable_file_does_not_abort_the_batch(self):
        import os, shutil, tempfile
        d = tempfile.mkdtemp()
        try:
            for n in ("a-2026-09-01.html", "b-2026-09-01.html", "c-2026-09-01.html"):
                with open(os.path.join(d, n), "w", encoding="utf-8") as f:
                    f.write("<title>x</title>" + PAGE)
            os.chmod(os.path.join(d, "b-2026-09-01.html"), 0o400)
            rc = rp.main([d, "--apply"])
            self.assertEqual(rc, 1)                       # blocked files are reported, not hidden
            with open(os.path.join(d, "c-2026-09-01.html"), encoding="utf-8") as f:
                self.assertIn('name="viewport"', f.read())  # the later file still got patched
        finally:
            os.chmod(os.path.join(d, "b-2026-09-01.html"), 0o600)
            shutil.rmtree(d, ignore_errors=True)

    def test_unknown_variant_is_flagged_not_rewritten(self):
        odd = PAGE.replace(rp.LIGHT_OLD, "--good:#2E7D5B; --good-soft:#AAAAAA;")
        new, changed, notes = rp.repalette(odd)
        self.assertTrue(any("still present" in n for n in notes))


if __name__ == "__main__":
    unittest.main()
