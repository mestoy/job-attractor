#!/usr/bin/env python3
"""The backlog filer must read the backlog that EXISTS, not the one it was written against.

`scripts/file_backlog_issues.py` shipped with a section map that read only "## 1." and "## 2.",
and a docstring asserting "## 3. is excluded by scope" — both true on the day they were written.
The backlog was then restructured into §1 Shipped, §2 Current, §3 Intended (file as open),
§4 Future (file as open), §4b Also shipped (file as already-fixed) and §5 Deliberately NOT
GitHub issues. The parser kept running, kept exiting 0, and silently dropped every row that had
been promoted to "file as open". Nothing was red; the output was simply short.

Two things this file pins down, because the obvious fix gets both wrong:

  DISPOSITION IS NOT INCLUSION. §1 and §4b are already fixed — they are filed and closed. §3 and
  §4 are filed as open. §5 must never reach the tracker at all. "Read §1 through §4" is not the
  rule; the rule is a per-section table.

  "## 4b." IS NOT "## 4.". The old heading pattern was `^## (\\d)\\.`, which does not match a
  letter suffix, so §4b's rows fell through under the previous section's number. Widening the
  read without widening the heading pattern would have filed three ALREADY-FIXED accessibility
  bugs as fresh open defects against the public repo.

The fixture below is INLINE on purpose. Pointing these assertions at the real
`.github/ISSUE_BACKLOG.md` would make them a test of today's contents — the file moves weekly,
and a test that moves with it cannot catch the thing that actually happened here.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import file_backlog_issues as filer  # noqa: E402


BACKLOG = """\
# GitHub issue backlog — fixture

Preamble prose that is not an item.

## Work states

A heading with no number at all. Nothing here may be filed.

**[bug] A row stranded in the unnumbered preamble** · `BUG-000`
- this must never be collected

## 1. Shipped — file and close, or file as already-fixed

**[bug] A shipped defect** · `BUG-101`
- kind: script-error
- fixed: yes

**[enhancement] A shipped improvement**
- shipped in the same pass

## 2. Current — in flight

**[bug] Something being worked on right now** · `BUG-202`
- state: current

## 3. Intended — file as open

**[bug] Ruled, scheduled, not started** · `BUG-303`
- state: intended

## 4. Future — file as open, no date

**[enhancement] Wanted eventually, no date**
- state: future

## 4b. Also shipped — the accessibility pass, file as already-fixed

**[bug] A contrast defect found and fixed in the audit**
- fixed: yes, in the accessibility pass

## 5. Deliberately NOT GitHub issues

Excluded by the template scope rule — specific to one job search.

**[bug] A private-repo concern that must never be filed publicly** · `BUG-500`
- belongs in BUG-LOG.md, not the tracker
"""


def parse_text(text):
    """parse() takes a path; the fixture is a string. Bridge them in a temp dir."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "ISSUE_BACKLOG.md")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return filer.parse(p)


class EverySectionIsReachable(unittest.TestCase):
    """The original failure: rows promoted to 'file as open' became unreachable in silence."""

    def setUp(self):
        self.items = parse_text(BACKLOG)
        self.by_section = {}
        for it in self.items:
            self.by_section.setdefault(it["section"], []).append(it)

    def test_each_filed_section_is_parsed(self):
        self.assertEqual(sorted(self.by_section), ["1", "2", "3", "4", "4b"],
                         "a section named in the backlog was not reached by the parser")

    def test_section_3_and_4_rows_are_not_dropped(self):
        """These are the exact rows the shipped parser silently discarded."""
        titles = {it["title"] for it in self.items}
        self.assertIn("Ruled, scheduled, not started", titles,
                      "§3 says 'file as open' and the parser must reach it")
        self.assertIn("Wanted eventually, no date", titles,
                      "§4 says 'file as open' and the parser must reach it")

    def test_a_letter_suffixed_heading_is_its_own_section(self):
        """'## 4b.' must not read as a continuation of '## 4.' — they disagree on disposition."""
        self.assertEqual(len(self.by_section["4"]), 1,
                         "§4b's rows leaked into §4; the heading pattern is too narrow")
        self.assertEqual([it["title"] for it in self.by_section["4b"]],
                         ["A contrast defect found and fixed in the audit"])


class DispositionIsExplicitPerSection(unittest.TestCase):
    """Inclusion and disposition are different questions, and only the second can file a
    shipped fix as a live bug against the public repo."""

    def setUp(self):
        self.items = parse_text(BACKLOG)
        self.disp = {it["section"]: it["disposition"] for it in self.items}

    def test_shipped_sections_are_file_and_close(self):
        self.assertEqual(self.disp["1"], "shipped",
                         "§1 is already fixed: file it, then close it as completed")
        self.assertEqual(self.disp["4b"], "shipped",
                         "§4b is the accessibility pass, already shipped — filing it OPEN would "
                         "report three fixed defects as live bugs on the public tracker")

    def test_intended_and_future_sections_are_filed_open(self):
        self.assertEqual(self.disp["2"], "open")
        self.assertEqual(self.disp["3"], "open")
        self.assertEqual(self.disp["4"], "open")

    def test_the_mapping_is_a_table_not_a_number_range(self):
        """'sections 1 through 4' cannot express §1 close / §3 open / §4b close. A reader adding
        §6 must find one place that says what happens to it."""
        self.assertEqual(filer.SECTION_DISPOSITION.get("1"), "shipped")
        self.assertEqual(filer.SECTION_DISPOSITION.get("4b"), "shipped")
        self.assertEqual(filer.SECTION_DISPOSITION.get("3"), "open")
        self.assertIsNone(filer.SECTION_DISPOSITION.get("5"),
                          "§5 must carry an explicit never-file disposition, not be absent")


class SectionFiveIsNeverFiled(unittest.TestCase):
    """The scope rule in `.github/ISSUE_TEMPLATE/` is a hard gate, not a preference."""

    def test_no_section_5_row_is_collected(self):
        items = parse_text(BACKLOG)
        self.assertNotIn("5", {it["section"] for it in items})
        titles = {it["title"] for it in items}
        self.assertNotIn("A private-repo concern that must never be filed publicly", titles)

    def test_rows_above_the_first_numbered_heading_are_not_collected(self):
        """Preamble prose is where a stray bolded row is likeliest to sit."""
        titles = {it["title"] for it in parse_text(BACKLOG)}
        self.assertNotIn("A row stranded in the unnumbered preamble", titles)


class AnUnrecognizedBacklogFailsLoudly(unittest.TestCase):
    """The failure mode that made this bug invisible for weeks: a short list looks like success.

    A parser that returns 17 items when the file holds 26 is indistinguishable, at the terminal,
    from a parser that is working. The only defense is refusing to guess.
    """

    def test_an_unknown_section_number_raises(self):
        text = BACKLOG + "\n## 6. A section nobody has ruled on\n\n**[bug] New row**\n- x\n"
        with self.assertRaises(ValueError) as ctx:
            parse_text(text)
        self.assertIn("6", str(ctx.exception))

    def test_a_renumbered_backlog_raises_rather_than_silently_shrinking(self):
        """The real-world shape of this: someone renumbers the sections. The old parser would
        have returned a shorter list and exited 0."""
        text = BACKLOG.replace("## 3. Intended", "## 7. Intended")
        with self.assertRaises(ValueError):
            parse_text(text)

    def test_a_file_with_no_numbered_sections_raises(self):
        text = "# Notes\n\n**[bug] Something** · `BUG-999`\n- not in any section\n"
        with self.assertRaises(ValueError) as ctx:
            parse_text(text)
        self.assertIn("section", str(ctx.exception).lower())

    def test_the_error_names_the_file_so_the_reader_can_act(self):
        text = BACKLOG.replace("## 4b.", "## 9c.")
        with self.assertRaises(ValueError) as ctx:
            parse_text(text)
        self.assertIn("ISSUE_BACKLOG.md", str(ctx.exception))


class TheScriptDoesNotLieAboutItself(unittest.TestCase):
    """Docstrings are the only map a reader has before running a thing that writes to a public
    tracker. The shipped one said '## 3. is excluded by scope' long after §3 had become
    'file as open', and that sentence is why the bug survived review."""

    def test_the_module_docstring_does_not_still_claim_sections_1_and_2_only(self):
        doc = filer.__doc__ or ""
        self.assertNotIn("Sections 1 and 2 only", doc)
        self.assertNotIn("Section 3 is deliberately excluded", doc)

    def test_the_module_docstring_names_the_excluded_section(self):
        doc = filer.__doc__ or ""
        self.assertIn("Section 5", doc,
                      "the docstring must say which section is out of scope, and it is §5")

    def test_the_parse_docstring_no_longer_describes_the_old_two_section_map(self):
        doc = filer.parse.__doc__ or ""
        self.assertNotIn("'## 3.' is excluded", doc)


if __name__ == "__main__":
    unittest.main()
