"""BUG-721: the PII gate must read a name split across string pieces or lines.

A reviewer found `"lists Pat " + "Fakename as CEO"` shaped text in a published fixture; the plain scan read the body
`lists Pat "<newline>  "Fakename`, which is not `pat fakename`. `joined_items` adds, per file, the joined string constants (.py)
and short windows at seams where a quote, `+`, `,` or `(` was stripped. The vocabulary here is invented: `Pat Fakename`.
The same file runs in AJS tests/, partner-starter/tests/ and the kit tests/ (it finds ../scripts/pii_gate.py).
"""
import inspect
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import pii_gate as pg  # noqa: E402

FULL = {"Pat Fakename"}

BODY_IMPLICIT = 'x = ("first-party company content: lists Pat "\n     "Fakename as CEO.\\n")\n'
BODY_PLUS = 'x = "lists Pat " + "Fakename as CEO"\n'
BODY_PLUS_NL = 'x = ("lists Pat " +\n     "Fakename as CEO")\n'
BODY_PROSE_MD = "The team page lists Pat\nFakename as CEO.\n"
BODY_FSTRING = 'x = (f"lists Pat "\n     f"Fakename as CEO")\n'
BODY_PLAIN = 'x = "lists Pat Fakename as CEO"\n'
BODY_BROKEN = 'def (:\n  "lists Pat "\n  "Fakename"\n'
BODY_SLUG = 'u = ("https://x.test/"\n     "zaraquibberdane")\n'
BODY_CRLF = 'x = ("lists Pat "\r\n     "Fakename as CEO")\r\n'
BODY_TRIPLE = 'x = ("""lists Pat """\n     """Fakename as CEO""")\n'
BODY_SAMELINE = 'x = ("lists Pat " "Fakename as CEO")\n'
BODY_COMMENT = 'x = ("lists Pat "  # who\n     "Fakename as CEO")\n'


def run(items, **kw):
    return pg.scan_items(pg.joined_items(items), FULL, set(), set(), **kw)


class SplitNamesBlock(unittest.TestCase):
    def blocks(self, rel, body):
        b, _ = run([(rel, body)])
        return [(r, h, why) for r, h, why in b]

    def named(self, rel, body):
        return any(h == "Pat Fakename" or "patfakename" in h.lower() for _, h, _ in self.blocks(rel, body))

    def test_the_plain_scan_misses_the_split_and_the_joined_scan_blocks(self):
        plain, _ = pg.scan_items([("t.py", BODY_IMPLICIT)], FULL, set(), set())
        self.assertEqual(plain, [])
        self.assertIn(("t.py (joined)", "Pat Fakename", "contact full name"), self.blocks("t.py", BODY_IMPLICIT))

    def test_an_explicit_plus_join_blocks(self):
        self.assertTrue(self.named("t.py", BODY_PLUS))

    def test_a_plus_at_the_end_of_a_line_blocks(self):
        self.assertTrue(self.named("t.py", BODY_PLUS_NL))

    def test_a_prose_name_split_across_lines_blocks_on_the_plain_body_and_adds_no_item(self):
        plain, _ = pg.scan_items([("notes.md", BODY_PROSE_MD)], FULL, set(), set())
        self.assertEqual([(h, w) for _, h, w in plain], [("Pat Fakename", "contact full name")])
        self.assertEqual(len(pg.joined_items([("notes.md", BODY_PROSE_MD)])), 1)  # nothing stripped at the seam

    def test_an_f_string_seam_blocks(self):
        self.assertTrue(self.named("t.py", BODY_FSTRING))

    def test_a_py_file_that_does_not_parse_still_gets_seams(self):
        self.assertTrue(self.named("t.py", BODY_BROKEN))

    def test_a_triple_quoted_implicit_concat_at_the_seam_blocks(self):
        self.assertTrue(self.named("t.py", BODY_TRIPLE))

    def test_an_implicit_concat_on_one_line_blocks(self):
        self.assertTrue(self.named("t.py", BODY_SAMELINE))

    def test_a_comment_at_the_seam_blocks(self):
        self.assertTrue(self.named("t.py", BODY_COMMENT))

    def test_a_non_py_file_gets_seams(self):
        self.assertTrue(self.named("t.txt", BODY_IMPLICIT))

    @unittest.skipUnless(hasattr(pg, "name_forms"), "this copy has no slug-form tier (copy drift, BUG-718)")
    def test_a_slug_split_at_a_seam_blocks(self):
        # "Pat" is a common word (no slug form), so this case uses a second invented name
        b, _ = pg.scan_items(pg.joined_items([("t.py", BODY_SLUG)]), {"Zara Quibberdane"}, set(), set())
        self.assertTrue(any(h.lower() == "zaraquibberdane" for _, h, _ in b))

    def test_crlf_seams(self):
        self.assertTrue(self.named("t.txt", BODY_CRLF))

    def test_a_name_already_found_in_the_body_is_not_reported_twice(self):
        b, _ = run([("t.py", BODY_PLAIN)])
        self.assertEqual(len(pg.dedupe_joined(b)), 1)
        self.assertEqual(pg.dedupe_joined(b)[0][0], "t.py")

    def test_dedupe_drops_a_joined_hit_the_plain_body_already_has_and_keeps_new_ones(self):
        hits = [("a.py", "X", "w"), ("a.py (joined)", "X", "w"), ("a.py (joined)", "Y", "w")]
        self.assertEqual(pg.dedupe_joined(hits), [("a.py", "X", "w"), ("a.py (joined)", "Y", "w")])

    def test_a_clean_file_adds_no_hits(self):
        self.assertEqual(self.blocks("t.py", 'x = ("alpha "\n     "beta")\n'), [])

    def test_seam_windows_are_bounded(self):
        body = ('a' * 500 + '"\n"') * 50 + "\n"
        joined = [t for r, t in pg.joined_items([("big.txt", body)]) if r.endswith("(joined)")]
        self.assertEqual(len(joined), 1)
        self.assertLess(len(joined[0]), 50 * 90)

    def test_owner_name_split_at_a_seam_downgrades_like_the_body(self):
        owner = {"name": "Pat Fakename"}
        b, w = run([("t.py", BODY_IMPLICIT)], owner=owner, downgrade_owner=True)
        self.assertEqual(b, [])
        self.assertTrue(any(h == "Pat Fakename" for _, h, _ in w))


class Wiring(unittest.TestCase):
    def test_scan_blocks_a_planted_split_in_a_temp_tree(self):
        root = tempfile.mkdtemp(prefix="pii721-")
        try:
            with open(os.path.join(root, "fixture.py"), "w", encoding="utf-8") as fh:
                fh.write(BODY_IMPLICIT)
            blocks, _, n = pg.scan(root, FULL, set(), set())
            self.assertEqual(n, 1)
            self.assertIn(("fixture.py (joined)", "Pat Fakename", "contact full name"), blocks)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_both_call_sites_are_wired(self):
        for fn in (pg.scan, pg.push_guard):
            src = inspect.getsource(fn)
            self.assertIn("joined_items(", src, fn.__name__)
            self.assertIn("dedupe_joined(", src, fn.__name__)


if __name__ == "__main__":
    unittest.main()
