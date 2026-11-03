"""kit#30: `followup_due` is written onto every send-log row (mail-draft.sh, log_linkedin_send.py)
and `check_followups.py` never read it, so a deliberate bump (`--followup-due 2026-08-11`, or a
hand edit of the row) was silently inert and an already-overdue date still reported green.

The checker now reads `documents/send-log.jsonl` as well: a row with a `followup_due` date is
due when that date is today or earlier and nothing records a reply; a row without one falls back
to the existing outreach_log.md cadence rule. Every item says which rule fired, so "nothing is
due" and "I cannot see anything" stop printing the same sentence.

Fixtures are fictional.
"""
import importlib
import json
import os
import _roots
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
TODAY = "2026-09-12"


def _row(**kw):
    base = {"ts": "2026-09-01T09:00:00", "date": "2026-09-01", "channel": "LinkedIn",
            "status": "sent", "rung": "reunion", "to": "past@example.test",
            "to_name": "Past Person", "company": "PastCo", "targets": "", "subject": "",
            "followup_due": "2026-09-05", "segment": "", "replied": None}
    base.update(kw)
    return base


class TestFollowupDueIsRead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, "documents"))
        self.sendlog = os.path.join(self.tmp.name, "documents", "send-log.jsonl")
        sys.path.insert(0, SCRIPTS)
        self.cf = importlib.import_module("check_followups")
        importlib.reload(self.cf)

    def tearDown(self):
        sys.path[:] = [p for p in sys.path if p != SCRIPTS]
        self.tmp.cleanup()

    def _write(self, rows, narrative=None):
        with open(self.sendlog, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        if narrative is not None:
            with open(os.path.join(self.tmp.name, "outreach_log.md"), "w", encoding="utf-8") as fh:
                fh.write(narrative)

    def _scan(self):
        return self.cf.scan(today=TODAY, repo=self.tmp.name)

    def test_past_followup_due_on_a_send_row_is_due(self):
        """The issue's exact repro: an overdue date on a row, no narrative token, was green."""
        self._write([_row(followup_due="2026-09-05", company="PastCo")])
        due, _up, _un = self._scan()
        self.assertTrue(any("PastCo" in c for _d, c in due),
                        f"an overdue followup_due on a send-log row was ignored: {due}")

    def test_future_followup_due_is_upcoming_not_due(self):
        self._write([_row(followup_due="2026-12-01", company="FutureCo")])
        due, upcoming, _un = self._scan()
        self.assertFalse(any("FutureCo" in c for _d, c in due))
        self.assertTrue(any("FutureCo" in c for _d, c in upcoming))

    def test_reunion_rung_is_honoured_when_a_date_was_set_deliberately(self):
        """A rung outside WARM_RUNGS still counts: the explicit date IS the deliberate bump."""
        self._write([_row(rung="reunion", followup_due="2026-09-05", company="ReunionCo")])
        due, _up, _un = self._scan()
        self.assertTrue(any("ReunionCo" in c for _d, c in due))

    def test_a_replied_row_is_not_due(self):
        self._write([_row(followup_due="2026-09-05", company="AnsweredCo", replied=True)])
        due, _up, _un = self._scan()
        self.assertFalse(any("AnsweredCo" in c for _d, c in due))

    def test_row_without_followup_due_falls_back_to_the_cadence_rule(self):
        """No date on the row: the markdown cadence rule still decides, and its item says so."""
        self._write([_row(followup_due="", company="LegacyCo")],
                    narrative="# Outreach Log\n\n"
                              "## 2026-09-01 · LegacyCo (legacy.test) · Jane Doe — ✅ SENT\n"
                              "FOLLOWUP-DUE: 2026-09-05 | channel:email | status:armed\n---\n")
        due, _up, _un = self._scan()
        hits = [d for d in due if "LegacyCo" in d[1]]
        self.assertEqual(len(hits), 1, due)
        self.assertEqual(getattr(hits[0], "rule", None), "cadence")

    def test_each_item_names_the_rule_that_fired(self):
        self._write([_row(followup_due="2026-09-05", company="PastCo")])
        due, _up, _un = self._scan()
        hits = [d for d in due if "PastCo" in d[1]]
        self.assertEqual(getattr(hits[0], "rule", None), "followup_due")
        dd, comp = hits[0]  # 2-tuple unpacking must survive: session_start.py depends on it
        self.assertEqual(dd, "2026-09-05")

    def test_row_and_narrative_for_the_same_send_report_once(self):
        """log_linkedin_send writes the token into BOTH stores; one send is one item."""
        self._write([_row(followup_due="2026-09-05", company="BothCo")],
                    narrative="# Outreach Log\n\n"
                              "## 2026-09-01 · BothCo · Past Person — ✅ SENT [LinkedIn · rung reunion]\n"
                              "**Rung:** reunion (kind:boss) | channel:LinkedIn | status:sent"
                              " | FOLLOWUP-DUE: 2026-09-05\n\n")
        due, _up, _un = self._scan()
        self.assertEqual(len([d for d in due if "BothCo" in d[1]]), 1, due)

    def test_cli_goes_red_and_says_which_rule(self):
        self._write([_row(followup_due="2026-09-05", company="PastCo")])
        env = _roots.sandbox_env(self.tmp.name)
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_followups.py")],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("PastCo", p.stdout)
        self.assertIn("followup_due", p.stdout)


if __name__ == "__main__":
    unittest.main()
