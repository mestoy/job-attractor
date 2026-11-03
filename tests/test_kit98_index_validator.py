"""kit#98: the read-only validator a partner asked for and the owner confirmed does not exist yet.

His 09-20 comment scoped it precisely against `--reindex` (which only ADDS a missing row, never
corrects or removes one):
  1. one INDEX.md row per HTML page, both directions -- half covered by --reindex (adds a
     missing row; never catches a stale row with no page, or two rows for one page).
  2. a single numbering namespace with no collisions -- not covered at all.
  3. a sprint manifest that disagrees with INDEX.md's current state -- not covered at all.
He also asked for one more thing, stated as a hard requirement, not a suggestion: the check "must
prove it had something to look at, so an empty folder cannot pass as a clean one."

This file covers 1 and 2, fully specified by his comment and the kit's own known INDEX.md/HTML
shapes. Check 3 (the sprint manifest) needs a real manifest sample or a format ruling before it
can be built with confidence -- reported back rather than guessed at.

Fictional names throughout.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import render_scorecard as rs  # noqa: E402


def _index(*rows):
    lines = ["# Scorecard index", "", "| Company | Verdict | Page file |", "|---|---|---|"]
    lines.extend(rows)
    return "\n".join(lines) + "\n"


class TestValidateIndexProvesItHadSomethingToLook(unittest.TestCase):
    """His hard requirement: an empty folder must not read as clean."""

    def test_an_empty_directory_is_not_a_clean_pass(self):
        with tempfile.TemporaryDirectory() as d:
            problems, checked = rs.validate_index(d)
            self.assertEqual(checked, 0)
            self.assertTrue(
                any("nothing to check" in p.lower() or "no html" in p.lower() for p in problems),
                "an empty scorecards dir must say so explicitly, not silently report zero "
                "problems the same way a genuinely clean, populated one would",
            )

    def test_a_populated_clean_directory_passes_with_nonzero_checked(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "fakebank-2026-09-01.html"), "w").write("<h1>Fakebank</h1>")
            open(os.path.join(d, "INDEX.md"), "w").write(
                _index("| Fakebank | RADAR | fakebank-2026-09-01.html |"))
            problems, checked = rs.validate_index(d)
            self.assertEqual(problems, [])
            self.assertGreater(checked, 0)


class TestCoverageBothDirections(unittest.TestCase):
    """His check 1, the half --reindex does not cover."""

    def test_a_page_with_no_index_row_is_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "driftco-2026-09-01.html"), "w").write("<h1>Driftco</h1>")
            open(os.path.join(d, "INDEX.md"), "w").write(_index())
            problems, _ = rs.validate_index(d)
            self.assertTrue(any("driftco-2026-09-01.html" in p and "no INDEX" in p
                                for p in problems))

    def test_a_row_with_no_page_is_flagged(self):
        """The half --reindex structurally cannot catch: it only adds rows, never checks them."""
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "INDEX.md"), "w").write(
                _index("| Ghostworks | RADAR | ghostworks-2026-09-01.html |"))
            problems, _ = rs.validate_index(d)
            self.assertTrue(any("ghostworks-2026-09-01.html" in p and "no page" in p
                                for p in problems))

    def test_two_rows_for_one_page_is_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "duplico-2026-09-01.html"), "w").write("<h1>Duplico</h1>")
            open(os.path.join(d, "INDEX.md"), "w").write(_index(
                "| Duplico | RADAR | duplico-2026-09-01.html |",
                "| Duplico Holdings | BUILD | duplico-2026-09-01.html |",
            ))
            problems, _ = rs.validate_index(d)
            self.assertTrue(any("duplico-2026-09-01.html" in p and "2 row" in p
                                for p in problems))

    def test_a_template_file_is_never_treated_as_an_orphan(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "TEMPLATE-scorecard-2026-09-01.html"), "w").write("<h1>t</h1>")
            open(os.path.join(d, "realco-2026-09-01.html"), "w").write("<h1>Realco</h1>")
            open(os.path.join(d, "INDEX.md"), "w").write(
                _index("| Realco | RADAR | realco-2026-09-01.html |"))
            problems, _ = rs.validate_index(d)
            self.assertEqual(problems, [])


class TestNumberingCollision(unittest.TestCase):
    """His check 2. A leading `#<digits><optional letter>` token at the start of a row's Company
    cell is the numbering convention his comment describes ("plain, B and C" namespaces) --
    generic enough to find nothing on an install that doesn't use one (safe default), and to
    catch an exact duplicate identifier where it does."""

    def test_two_rows_sharing_the_same_leading_id_are_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "alpha-2026-09-01.html"), "w").write("<h1>a</h1>")
            open(os.path.join(d, "beta-2026-09-01.html"), "w").write("<h1>b</h1>")
            open(os.path.join(d, "INDEX.md"), "w").write(_index(
                "| #12 Alpha Robotics | RADAR | alpha-2026-09-01.html |",
                "| #12 Beta Systems | RADAR | beta-2026-09-01.html |",
            ))
            problems, _ = rs.validate_index(d)
            self.assertTrue(any("#12" in p and "more than one" in p for p in problems))

    def test_plain_and_lettered_ids_are_DIFFERENT_namespaces_not_a_collision(self):
        """#12 and #12B are distinct identifiers under his description of the (broken) three-
        namespace shape -- this check catches an EXACT duplicate id, not a plain/lettered
        mismatch, since deciding those two SHOULD be unified is the design question the issue
        itself raises, not a fact this check can assert on its own."""
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "alpha-2026-09-01.html"), "w").write("<h1>a</h1>")
            open(os.path.join(d, "beta-2026-09-01.html"), "w").write("<h1>b</h1>")
            open(os.path.join(d, "INDEX.md"), "w").write(_index(
                "| #12 Alpha Robotics | RADAR | alpha-2026-09-01.html |",
                "| #12B Beta Systems | RADAR | beta-2026-09-01.html |",
            ))
            problems, _ = rs.validate_index(d)
            self.assertEqual([p for p in problems if "#12" in p], [])

    def test_no_leading_id_at_all_is_not_flagged(self):
        """An install that never adopted the numbering convention must read clean, not
        pattern-match noise into a false collision."""
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "onlyco-2026-09-01.html"), "w").write("<h1>o</h1>")
            open(os.path.join(d, "INDEX.md"), "w").write(_index(
                "| Onlyco | RADAR | onlyco-2026-09-01.html |"))
            problems, _ = rs.validate_index(d)
            self.assertEqual(problems, [])

    def test_three_distinct_ids_are_clean(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("a", "b", "c"):
                open(os.path.join(d, f"{n}-2026-09-01.html"), "w").write(f"<h1>{n}</h1>")
            open(os.path.join(d, "INDEX.md"), "w").write(_index(
                "| #1 A Co | RADAR | a-2026-09-01.html |",
                "| #2 B Co | RADAR | b-2026-09-01.html |",
                "| #3 C Co | RADAR | c-2026-09-01.html |",
            ))
            problems, _ = rs.validate_index(d)
            self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
