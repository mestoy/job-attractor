#!/usr/bin/env python3
"""Kit #229 (plan-kit229-send-gate-tracker-status-2026-11-02.md rev 3): the send gate reads the tracker row's STATUS.

A tracker row blocks a first send only when its status says a contact happened. A Build decision, a discovery, a scorecard, a banked row or a research
row is a research note: the gate prints it as one and lets the send through. Anything the gate does not recognize stays a contact and blocks, so the
change can only open the gate for the five named research words, never for an unknown one. The plain (non send-gate) check does not change.
Fixtures live in this test's own tmp dir; every company and person is obviously fake.

Run:  python3 -m unittest tests.test_check_dup_tracker_status
"""
import csv
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _roots  # noqa: E402

ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

check_dup = importlib.import_module("check_dup")

HEADER = ["date", "company", "sector", "role", "role_type", "channel", "status", "contact_person", "fit_rating", "notes", "cv_file", "cover_letter_file", "source"]
CO = "Zorblat Quasar"

# the twelve status spellings in his real tracker (192 rows): every one is a contact or an outcome word
MICHAELS_TWELVE = ["skipped", "contacted", "SENT", "applied", "reached out", "rejected", "sent", "no response",
                   "Email (boss-hunt, résumé self-attached, To+2 Bcc hedge)", "interviewing", "rejected 2026-09-08", "contacted (LinkedIn note)"]


def _csv_text(rows, header=HEADER):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if header is not None:
        w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def _row(status, notes="", company=CO, person="", channel="", **kw):
    d = {"date": "2026-10-01", "company": company, "sector": "Fake Sector", "role": "Fake Role", "role_type": "Product Manager", "channel": channel,
         "status": status, "contact_person": person, "fit_rating": "", "notes": notes, "cv_file": "", "cover_letter_file": "", "source": ""}
    d.update(kw)
    return [d[h] for h in HEADER]


class _Install(tempfile.TemporaryDirectory):
    """A tmp install holding only a tracker, so check_dup reads nothing else."""

    def __init__(self, rows=None, header=HEADER, text=None):
        super().__init__(prefix="kit229-")
        self._rows, self._header, self._text = rows or [], header, text

    def __enter__(self):
        os.makedirs(os.path.join(self.name, "documents"), exist_ok=True)
        body = self._text if self._text is not None else _csv_text(self._rows, self._header)
        with open(os.path.join(self.name, "job_search_tracker.csv"), "w", encoding="utf-8") as fh:
            fh.write(body)
        self._real = check_dup.REPO
        check_dup.REPO = self.name
        self._restore = _roots.set_roots(self.name)
        return self

    def __exit__(self, *a):
        self._restore()
        check_dup.REPO = self._real
        return super().__exit__(*a)

    def env(self):
        e = dict(os.environ)
        e.update({"CLAUDE_PROJECT_DIR": self.name, "JOBSEARCH_DATA_ROOT": self.name, "JOBSEARCH_TEST": "1"})
        return e


def verdict(rows=None, header=HEADER, text=None, company=CO):
    with _Install(rows, header, text):
        return check_dup.prior_contact(company)


class TheResearchRows(unittest.TestCase):
    def test_build_row_is_research(self):
        pc = verdict([_row("build")])
        self.assertEqual("yellow", pc["verdict"])
        self.assertEqual([], pc["strong"])
        self.assertEqual("research row (build), not a contact", pc["weak"][0]["status"])
        self.assertEqual("job_search_tracker.csv", pc["weak"][0]["store"])

    def test_build_row_exits_3_at_the_send_gate_never_1(self):
        with _Install([_row("build")]) as d:
            p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_dup.py"), "--send-gate", CO], cwd=d.name, env=d.env(), capture_output=True, text=True)
        self.assertEqual(3, p.returncode, p.stdout + p.stderr)
        self.assertIn("research row (build), not a contact", p.stdout)

    def test_discovery_and_scorecard_rows_are_research(self):
        for status, word in (("discover→Zorblat Quasar", "discover"), ("discover → Zorblat Quasar", "discover"), ("scorecard(Zorblat Quasar card)", "scorecard"),
                             ("Scorecard", "scorecard"), ("banked", "banked"), ("research", "research"), ("  BUILD  ", "build")):
            with self.subTest(status=status):
                pc = verdict([_row(status)])
                self.assertEqual("yellow", pc["verdict"], pc)
                self.assertEqual("research row (%s), not a contact" % word, pc["weak"][0]["status"])


class TheContactRows(unittest.TestCase):
    def test_michaels_twelve_statuses_stay_contact(self):
        for status in MICHAELS_TWELVE:
            with self.subTest(status=status):
                pc = verdict([_row(status)])
                self.assertEqual("red", pc["verdict"], pc)
                self.assertTrue(pc["strong"])

    def test_unknown_and_empty_status_block(self):
        cases = {"zzz": [_row("zzz")], "empty": [_row("")]}
        for name, rows in cases.items():
            with self.subTest(case=name):
                self.assertEqual("red", verdict(rows)["verdict"])

    def test_a_row_shorter_than_the_header_blocks(self):
        short = _csv_text([], HEADER) + "2026-10-01,%s,Fake Sector,Fake Role,Product Manager,,build\n" % CO
        self.assertEqual("red", verdict(text=short)["verdict"])

    def test_a_row_longer_than_the_header_blocks(self):
        long_ = _csv_text([], HEADER) + "2026-10-01,%s,Fake Sector,Fake Role,Product Manager,,build,,,,,,,extra\n" % CO
        self.assertEqual("red", verdict(text=long_)["verdict"])

    def test_no_header_and_no_status_column_block(self):
        self.assertEqual("red", verdict([_row("build")], header=None)["verdict"])
        no_status = [h for h in HEADER if h != "status"]
        rows = [[v for h, v in zip(HEADER, _row("build")) if h != "status"]]
        self.assertEqual("red", verdict(rows, header=no_status)["verdict"])

    def test_radar_and_screening_stay_contact_by_first_token(self):
        for status in ("radar", "RADAR sent 10-02", "screening call", "screened by HR", "screen", "build sent 10-02", "research then emailed the CEO",
                       "builder", "researched", "banker"):
            with self.subTest(status=status):
                self.assertEqual("red", verdict([_row(status)])["verdict"], status)

    def test_quoted_comma_in_notes_does_not_shift_the_column(self):
        self.assertEqual("yellow", verdict([_row("build", notes="Fit looks good, ruling pending")])["verdict"])
        self.assertEqual("red", verdict([_row("contacted", notes="Fit looks good, ruling pending")])["verdict"])

    def test_research_row_with_a_contact_word_elsewhere_stays_red(self):
        cases = [("notes", _row("build", notes="sent intro 09-29"), "notes: sen[dt]"),
                 ("contact_person", _row("build", person="emailed Dana Fakename"), "contact_person: e-?mail"),
                 ("channel", _row("build", channel="InMail"), "channel: inmail"),
                 ("rest of status", _row("build sent 10-02"), "status: sen[dt]")]
        for name, row, shown in cases:
            with self.subTest(col=name):
                pc = verdict([row])
                self.assertEqual("red", pc["verdict"], pc)
                self.assertIn(shown, pc["strong"][0]["status"])

    def test_a_built_from_the_posting_note_is_not_a_contact_word(self):
        self.assertEqual("yellow", verdict([_row("build", notes="built from the posting")])["verdict"])

    def test_a_contact_row_beside_a_research_row_still_blocks(self):
        pc = verdict([_row("build"), _row("contacted")])
        self.assertEqual("red", pc["verdict"])
        self.assertTrue(any(h["store"] == "job_search_tracker.csv" for h in pc["weak"]), "the research row still prints, as a weak hit")


PROBES = ["e-mailed the CEO", "pinged on LinkedIn", "wrote to the VP", "spoke with recruiter", "DM'd him", "followed up 10-03", "email out 10-02", "interviewed 10-05"]


class TheOpenSideOfTheContactList(unittest.TestCase):
    """2e F1: a closed list of contact words is closed on the wrong side. Stems, any case, over every column but date, company and the link and file columns."""

    def test_the_eight_probes_in_the_notes_stay_red(self):
        for note in PROBES:
            with self.subTest(note=note):
                self.assertEqual("red", verdict([_row("build", notes=note)])["verdict"], note)

    def test_the_same_probes_in_the_rest_of_the_status_stay_red(self):
        for note in PROBES:
            with self.subTest(note=note):
                self.assertEqual("red", verdict([_row("build " + note)])["verdict"], note)

    def test_case_does_not_matter(self):
        for note in ("EMAILED the CEO", "Reached Out on 10-02", "FOLLOW-UP sent"):
            self.assertEqual("red", verdict([_row("Build", notes=note)])["verdict"], note)

    def test_a_link_or_file_column_is_not_a_contact(self):
        pc = verdict([_row("build", source="https://www.linkedin.com/jobs/view/123", cv_file="cv/main_applied_intro.tex")])
        self.assertEqual("yellow", pc["verdict"], pc)

    def test_the_company_and_date_columns_are_not_scanned(self):
        pc = verdict([_row("build", company="Zorblat Quasar Met Calls", date="2026-10-01")], company="Zorblat Quasar Met Calls")
        self.assertEqual("yellow", pc["verdict"], pc)


class TheChannelColumn(unittest.TestCase):
    """2e F2: a non-empty channel records how a contact went, so a research row carrying one is a contact."""

    def test_a_build_row_with_a_channel_is_red(self):
        for ch in ("email", "LinkedIn", "Company website (Greenhouse)", "Referral"):
            with self.subTest(channel=ch):
                pc = verdict([_row("build", channel=ch)])
                self.assertEqual("red", pc["verdict"], pc)
                self.assertIn("channel: " + ch.lower(), pc["strong"][0]["status"])

    def test_no_channel_values_stay_research(self):
        for ch in ("", "  ", "n/a", "N/A", "none", " None ", "(screen only)", "(Screen only)"):
            with self.subTest(channel=ch):
                self.assertEqual("yellow", verdict([_row("build", channel=ch)])["verdict"], repr(ch))


class ThePlainCheckAndTheCallers(unittest.TestCase):
    def test_plain_check_unchanged_for_a_build_row(self):
        with _Install([_row("build")]) as d:
            p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_dup.py"), CO], cwd=d.name, env=d.env(), capture_output=True, text=True)
        self.assertEqual(1, p.returncode, p.stdout + p.stderr)
        self.assertIn("CONTACTED / applied / skipped", p.stdout)

    def test_boss_registry_prints_the_research_line_and_does_not_refuse(self):
        with _Install([_row("build")]) as d:
            os.makedirs(os.path.join(d.name, "documents", "state"), exist_ok=True)
            p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "boss_registry.py"), "add", "--company", CO, "--person", "Fake Person", "--verdict", "candidate",
                                "--boss-read", "direct-boss", "--verified", "unverified", "--role-status", "unverified"],
                               cwd=d.name, env=d.env(), capture_output=True, text=True)
        self.assertNotIn("⛔ BLOCKED", p.stderr)
        self.assertIn("research row (build), not a contact", p.stdout)

    def _mail_draft(self, status):
        with _Install([_row(status)]) as d:
            body = os.path.join(d.name, "body.txt")
            with open(body, "w", encoding="utf-8") as fh:
                fh.write("Hi Fake,\n\nA fake note.\n")
            p = subprocess.run(["bash", os.path.join(SCRIPTS, "mail-draft.sh"), "--repo", d.name, "--to", "fake@zorblat.example", "--subject", "Hi", "--body-file", body,
                                "--rung", "cold-boss", "--company", CO, "--no-resume", "--segment", "payments"], cwd=d.name, env=d.env(), capture_output=True, text=True, timeout=120)
        return p.stdout + p.stderr

    def test_mail_draft_passes_the_dedup_gate_for_a_build_row_and_stops_at_it_for_a_contact_row(self):
        self.assertNotIn("check_dup returned 🔴", self._mail_draft("build"))
        self.assertIn("check_dup returned 🔴", self._mail_draft("contacted"))


class TheWordLists(unittest.TestCase):
    # one fixture note per contact stem: a stem cannot ship without a row that hits it
    STEM_NOTES = {"e-?mail": "e-mailed her", "sen[dt]": "sent a note", "wrote/writ": "wrote to him", "ping": "pinged him", "dm": "DM'd him", "messag": "messaged her",
                  "inmail": "InMail out", "linkedin": "on LinkedIn", "call": "called twice", "spoke/speak": "spoke with her", "met/meet": "met on Zoom",
                  "interview": "interviewed 10-05", "follow": "followed up", "outreach": "outreach started", "reach out": "reached out 10-02",
                  "contact": "contacted him", "repl": "replied 10-04", "apply/applied": "applied online", "intro": "intro via a friend", "connect": "connected with her"}

    def test_the_lists_are_the_planned_ones(self):
        self.assertEqual(("build", "discover", "scorecard", "banked", "research"), check_dup.TRACKER_RESEARCH_STATUSES)
        self.assertEqual(("n/a", "none", "(screen only)"), check_dup.TRACKER_NO_CHANNEL)
        self.assertEqual(sorted(self.STEM_NOTES), sorted(name for name, _ in check_dup.TRACKER_CONTACT_STEMS))

    def test_every_listed_word_has_a_fixture_row_in_this_file(self):
        """A new word cannot ship untested: each research word is run as a status, each contact stem as a note on a build row."""
        for w in check_dup.TRACKER_RESEARCH_STATUSES:
            self.assertEqual("yellow", verdict([_row(w)])["verdict"], w)
        for stem, note in self.STEM_NOTES.items():
            pc = verdict([_row("build", notes=note)])
            self.assertEqual("red", pc["verdict"], stem)
            self.assertIn("notes: " + stem, pc["strong"][0]["status"])


class TheHelpers(unittest.TestCase):
    def test_tracker_row_status_reads_the_status_by_header_name(self):
        head = ",".join(HEADER)
        line = '2026-10-01,Zorblat Quasar,Fake,Fake,PM,,Build ,,,"a, b",,,'
        self.assertEqual("build", check_dup.tracker_row_status(head, line))
        self.assertIsNone(check_dup.tracker_row_status("date,company,notes", "2026-10-01,Zorblat Quasar,x"))
        self.assertIsNone(check_dup.tracker_row_status(head, "2026-10-01,Zorblat Quasar"))


PARTNER_SCRIPTS = os.path.join(ROOT, "partner-starter", "scripts")


@unittest.skipUnless(os.path.isdir(PARTNER_SCRIPTS), "no partner-starter copy beside this one")
class TheTwoCopiesAgree(unittest.TestCase):
    """Plan test 10: the same rows through both check_dup copies give the same verdicts, statuses and hit lines."""

    CODE = ("import json, sys; sys.path.insert(0, sys.argv[1]); import check_dup; r = check_dup.prior_contact(sys.argv[2]); "
            "print(json.dumps({'v': r['verdict'], 's': [[h['store'], h['status'], h['line']] for h in r['strong']], 'w': [[h['store'], h['status'], h['line']] for h in r['weak']]}))")

    def through(self, scripts, rows, header=HEADER):
        with _Install(rows, header) as d:
            p = subprocess.run([sys.executable, "-c", self.CODE, scripts, CO], cwd=d.name, env=d.env(), capture_output=True, text=True)
        return json.loads(p.stdout)

    def test_the_same_rows_give_the_same_answer_in_both_copies(self):
        cases = [[_row("build")], [_row("discover→Zorblat Quasar")], [_row("scorecard(Zorblat Quasar card)")], [_row("zzz")], [_row("")],
                 [_row("build sent 10-02")], [_row("build", notes="sent intro 09-29")], [_row("build"), _row("contacted")]] + [[_row(s)] for s in MICHAELS_TWELVE] + \
                [[_row("build", notes=n)] for n in PROBES] + [[_row("build", channel=c)] for c in ("email", "LinkedIn", "n/a", "none", "(screen only)", "")]
        for rows in cases:
            with self.subTest(status=rows[0][6]):
                self.assertEqual(self.through(SCRIPTS, rows), self.through(PARTNER_SCRIPTS, rows))


if __name__ == "__main__":
    unittest.main()
