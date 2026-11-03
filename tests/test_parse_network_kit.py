#!/usr/bin/env python3
"""test_parse_network_kit.py -- slice A commit 4 (parse half): the LinkedIn Connections.csv parse, (b) and (a2).

Every fixture opens with the three-line "Notes:" preamble LinkedIn writes above the real header (MUST 4); a fixture without it is its own case.
All people and companies are invented (example.invalid). A real export is never copied here.
"""
import csv
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import parse_network as pn  # noqa: E402

PREAMBLE = 'Notes:\n"This is an invented preamble in the shape of the real one. See https://example.invalid/help for more."\n\n'
HEADER = "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"


def export(*rows, preamble=PREAMBLE, header=HEADER):
    return preamble + header + "".join(r + "\n" for r in rows)


class ParseRows(unittest.TestCase):
    def test_the_fixture_with_its_preamble_gives_the_rows(self):
        rows = pn.parse_rows(export(
            "Zzqana,Testperson,https://example.invalid/in/zzqana-testperson,,Zzqco Fake Works,Product Lead,08 Oct 2026",
            "Zzqbo,Otherperson,https://example.invalid/in/zzqbo-otherperson,,Zzqdo Other Works,Engineer,01 Sep 2026"))
        self.assertEqual([r["First Name"] for r in rows], ["Zzqana", "Zzqbo"])
        self.assertEqual(rows[0]["Company"], "Zzqco Fake Works")

    def test_a_company_with_a_comma_and_quotes(self):
        rows = pn.parse_rows(export('Zzqana,Testperson,https://example.invalid/in/a,,"Zzqco, ""Fake"" Works, Inc.",Lead,08 Oct 2026'))
        self.assertEqual(rows[0]["Company"], 'Zzqco, "Fake" Works, Inc.')

    def test_a_row_with_no_company_and_a_row_with_no_url_are_kept(self):
        rows = pn.parse_rows(export("Zzqana,Testperson,https://example.invalid/in/a,,,Lead,08 Oct 2026",
                                    "Zzqbo,Otherperson,,,Zzqdo Other Works,Lead,08 Oct 2026"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Company"], "")
        self.assertEqual(rows[1]["URL"], "")

    def test_a_utf8_bom_in_front_of_the_preamble_is_fine_once_decoded(self):
        text = ("﻿" + export("Zzqana,Testperson,https://example.invalid/in/a,,Zzqco,Lead,08 Oct 2026")).encode("utf-8").decode("utf-8-sig")
        self.assertEqual(len(pn.parse_rows(text)), 1)

    def test_a_file_with_a_header_and_no_rows_gives_zero(self):
        self.assertEqual(pn.parse_rows(export()), [])

    def test_a_file_with_no_header_line_gives_zero_rows(self):
        self.assertEqual(pn.parse_rows("Notes:\nnothing here\n\nName,Thing\nx,y\n"), [])

    def test_a_fixture_without_the_preamble_is_a_second_case_not_the_main_one(self):
        rows = pn.parse_rows(export("Zzqana,Testperson,https://example.invalid/in/a,,Zzqco,Lead,08 Oct 2026", preamble=""))
        self.assertEqual(len(rows), 1)


class SpreadsheetSafety(unittest.TestCase):
    """(a2) A cell that starts with = + - or @ is a formula to a spreadsheet. It is kept as TEXT (a leading apostrophe) the moment it is parsed, so no
    output made from the rows (the markdown view, the saved csv, the contact store) can carry a live formula."""

    def test_each_formula_lead_is_neutralized_in_every_cell(self):
        for lead in ("=", "+", "-", "@"):
            evil = lead + "cmd|' /c calc'!A0"
            rows = pn.parse_rows(export("%s,Testperson,https://example.invalid/in/a,,%s Works,%s Lead,08 Oct 2026" % (evil.replace(",", ";"), evil.replace(",", ";"), evil.replace(",", ";"))))
            for key in ("First Name", "Company", "Position"):
                self.assertTrue(rows[0][key].startswith("'" + lead), "%s %r" % (key, rows[0][key]))

    def test_an_ordinary_cell_is_untouched(self):
        rows = pn.parse_rows(export("Zzqana,Testperson,https://example.invalid/in/a,,Zzqco - Fake Works,Lead (interim),08 Oct 2026"))
        self.assertEqual(rows[0]["Company"], "Zzqco - Fake Works")
        self.assertEqual(rows[0]["Position"], "Lead (interim)")

    def test_a_leading_space_does_not_hide_a_formula(self):
        rows = pn.parse_rows(export('Zzqana,Testperson,https://example.invalid/in/a,," =1+1",Lead,08 Oct 2026'))
        self.assertTrue(rows[0]["Company"].startswith("'"), rows[0]["Company"])


if __name__ == "__main__":
    unittest.main()
