#!/usr/bin/env python3
"""BUG-718 Slice C1: the partner send-log READERS see a spooled change (sendlog_lock.open_lines), driven through the CALLERS, not the port's own CLI.

A writer that could not get the lock spools its change to send-log.pending.jsonl. The spool line is written here by hand (no import of the port), so this test fails
before the port exists and passes only when each reader goes through sendlog_lock:
  * check_dup.prior_contact: a spooled delivered row makes the company red (the dedup gate sees it before the fold)
  * rung_ladder.load: the spooled row is in the ladder's rows
  * pair_brief.ladder_counts: the 3-3-3 ladder counts the spooled row
Plus the B3 check: every file landed from the BUG-718 ports is imported by at least one other partner file.
Run (the gate's way): cd partner-starter/tests && python3 -m unittest test_sendlog_lock_readers
"""
import importlib
import json
import os
import _roots
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

check_dup = importlib.import_module("check_dup")
rung_ladder = importlib.import_module("rung_ladder")
pair_brief = importlib.import_module("pair_brief")

SPOOLED = {"date": "2026-10-20", "company": "Zzyx Spoolco", "to": "Skylar Fake", "rung": "cold-boss", "status": "sent", "subject": "fake subject"}


class SpooledReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents"))
        self.log = os.path.join(self.tmp.name, "documents", "send-log.jsonl")
        with open(self.log, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"date": "2026-10-01", "company": "Other Co", "to": "Pat Fake", "rung": "cold-boss", "status": "sent"}) + "\n")
        entry = {"spool_id": "a" * 32, "at": "2026-10-20T10:00:00+00:00", "op": "append", "key": {}, "fields": SPOOLED, "writer": "mail-draft"}
        with open(os.path.join(self.tmp.name, "documents", "send-log.pending.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        self._repo = check_dup.REPO
        check_dup.REPO = self.tmp.name
        _roots.patch_roots(self, self.tmp.name)
        self.addCleanup(lambda: setattr(check_dup, "REPO", self._repo))

    def test_check_dup_sees_a_spooled_delivered_row(self):
        pc = check_dup.prior_contact("Zzyx Spoolco", "Skylar Fake")
        self.assertEqual(pc["verdict"], "red")

    def test_rung_ladder_load_includes_the_spooled_row(self):
        rows = rung_ladder.load(self.log)
        self.assertIn("Zzyx Spoolco", [r.get("company") for r in rows])

    def test_pair_brief_ladder_counts_the_spooled_row(self):
        rows = rung_ladder.load(self.log)
        self.assertEqual(len(rows), 2)
        tally = pair_brief.ladder_counts(self.tmp.name)
        self.assertTrue(tally)


class UpdateApplies(SpooledReader):
    """BUG-718 C1b landed (2026-11-03): this kit copy has log_linkedin_send's matching functions, so a spooled UPDATE (set_stage,
    mark_replied, confirm_sent) and a spooled RESEND apply, with the live writer's own matching. The old fail-closed refusal is gone."""
    def _entry(self, writer, to="Pat Fake", **kw):
        return dict({"spool_id": "b" * 32, "at": "2026-10-21T10:00:00+00:00", "op": "update", "key": {"to": to},
                     "fields": {}, "writer": writer}, **kw)

    def test_set_stage_applies_to_the_newest_row(self):
        sl = sys.modules["sendlog_lock"]
        items = [{"to": "Pat Fake", "status": "sent", "date": "2026-10-01"}, {"to": "Pat Fake", "status": "sent", "date": "2026-10-20"}]
        state, why = sl.apply_entry(items, self._entry("set_stage", fields={"stage": "replied", "stage_at": "2026-10-21"}))
        self.assertEqual((state, why), ("applied", ""))
        self.assertEqual(items[1].get("stage"), "replied")
        self.assertFalse(items[0].get("stage"))

    def test_a_move_backwards_is_still_refused_with_the_writers_sentence(self):
        sl = sys.modules["sendlog_lock"]
        items = [{"to": "Pat Fake", "status": "sent", "stage": "onsite"}]
        state, why = sl.apply_entry(items, self._entry("set_stage", fields={"stage": "replied", "stage_at": "2026-10-21"}))
        self.assertEqual(state, "refused")
        self.assertIn("BACKWARDS", why)
        self.assertEqual(items[0]["stage"], "onsite")

    def test_no_row_for_the_person_is_nomatch_not_a_write(self):
        sl = sys.modules["sendlog_lock"]
        items = [{"to": "Someone Else", "status": "sent"}]
        state, _ = sl.apply_entry(items, self._entry("mark_replied"))
        self.assertEqual(state, "nomatch")
        self.assertNotIn("replied", items[0])

    def test_confirm_sent_flips_only_a_drafted_row(self):
        sl = sys.modules["sendlog_lock"]
        items = [{"to": "Pat Fake", "status": "drafted", "company": "Zzyx Spoolco", "subject": "Hello"}]
        state, _ = sl.apply_entry(items, self._entry("confirm_sent", fields={"status": "sent"}, key={"to": "Pat Fake", "company": "Zzyx Spoolco", "subject": "Hello"}))
        self.assertEqual(state, "applied")
        self.assertEqual(items[0]["status"], "sent")


class EveryLandedPortHasAPartnerImporter(unittest.TestCase):
    """B3 (rev 3 M1): a port with no partner importer is dead code. Each name below was landed by BUG-718; each must be imported by another partner file."""
    LANDED = ["sendlog_lock"]

    def test_each_landed_port_is_imported(self):
        files = [f for f in os.listdir(SCRIPTS) if f.endswith((".py", ".sh"))]
        for name in self.LANDED:
            self.assertTrue(os.path.isfile(os.path.join(SCRIPTS, name + ".py")), name + " is not in partner-starter/scripts")
            pat = re.compile(r"(import\s+%s\b|from\s+%s\s+import|\"%s\.py\")" % (name, name, name))
            users = [f for f in files if f != name + ".py" and pat.search(open(os.path.join(SCRIPTS, f), encoding="utf-8", errors="ignore").read())]
            self.assertTrue(users, name + " has no partner importer")


if __name__ == "__main__":
    unittest.main()
