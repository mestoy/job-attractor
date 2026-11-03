#!/usr/bin/env python3
"""BUG-687: the change the spool's fold applies equals the change the live writer makes.

ONE fixture log of twelve rows (two recipients with unsent drafts for two companies, a sent row, a bounced one, a replied one, one with a stage). For each writer
(set_stage, mark_replied, confirm_sent with and without company/subject, mark_bounced) the change is run LIVE on a copy of the fixture, and the same change is spooled and folded on a
second copy; the two logs must be byte-identical once the fold's own bookkeeping (`spool_id`, `spool_ids`) is removed. A backwards set_stage is refused live and the folded update lands in
send-log.pending.refused.jsonl with the SAME sentence; an update for a recipient with no row is reported and stays in the spool, as the live writer reports it.
Run: python3 -m unittest tests.test_sendlog_match_parity
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import sendlog_lock as sl   # noqa: E402
import log_linkedin_send as lls   # noqa: E402

TMP = os.environ.get("SJ_TMP") or os.path.join(os.path.expanduser("~"), "render", "sendlog-tmp")  # never /tmp and never a sibling of the tree
os.makedirs(TMP, exist_ok=True)


def r(to, date, ts, status="sent", **kw):
    return dict({"ts": ts, "date": date, "channel": "email", "status": status, "rung": "cold-boss", "to": to, "to_name": "", "company": "", "subject": "", "replied": None}, **kw)


FIXTURE = [
    r("pat@zz.example", "2026-10-01", "2026-10-01T09:00:00", "staged", company="Zz One", subject="One"),
    r("pat@zz.example", "2026-10-02", "2026-10-02T09:00:00", "staged", company="Zz Two", subject="Two"),
    r("lee@zz.example", "2026-10-02", "2026-10-02T10:00:00", "sent", company="Zz Three", subject="Three", sent_ts="2026-10-02T10:05:00+00:00"),
    r("kim@zz.example", "2026-10-03", "2026-10-03T09:00:00", "bounced", company="Zz Four", subject="Four", bounced_at="2026-10-04"),
    r("linkedin:zzyx-widgets-fake-0001", "2026-10-03", "2026-10-03T10:00:00", "sent", channel="linkedin", stage="conversation", stage_at="2026-10-04"),
    r("joe@zz.example", "2026-10-04", "2026-10-04T09:00:00", "sent", company="Zz Five", subject="Five", replied=True, replied_note="marked replied 2026-10-05"),
    r("sam@zz.example", "2026-10-05", "2026-10-05T09:00:00", "drafted", company="Zz Six", subject="Six"),
    r("sam@zz.example", "2026-10-05", "2026-10-05T11:00:00", "staged", company="Zz Six", subject="Six two"),
    r("uma@zz.example", "2026-10-06", "2026-10-06T09:00:00", "sent", company="Zz Seven", subject="Seven"),
    r("vic@zz.example", "2026-10-06", "2026-10-06T10:00:00", "staged", company="Zz Eight", subject="Eight"),
    r("wes@zz.example", "2026-10-07", "2026-10-07T09:00:00", "sent", company="Zz Nine", subject="Nine"),
    r("xia@zz.example", "2026-10-07", "2026-10-07T10:00:00", "discarded", company="Zz Ten", subject="Ten"),
]
SENT = {"status": "sent", "sent_ts": "2026-10-08T12:00:00+00:00", "sent_confirmed_by": lls.OWNER_FIRST.lower()}   # the live writer stamps the owner word from kit_config; a clean clone has "your"


def strip(text):
    out = []
    for line in text.splitlines():
        o = json.loads(line)
        o.pop("spool_id", None)
        o.pop("spool_ids", None)
        out.append(json.dumps(o, ensure_ascii=False))
    return "\n".join(out) + "\n"


class Parity(unittest.TestCase):
    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        self.base = tempfile.mkdtemp(prefix="parity-", dir=TMP)
        self.addCleanup(shutil.rmtree, self.base, True)
        for name in ("live", "fold"):
            d = os.path.join(self.base, name, "documents")
            os.makedirs(d)
            with open(os.path.join(d, "send-log.jsonl"), "w", encoding="utf-8") as fh:
                for row in FIXTURE:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.live = os.path.join(self.base, "live", "documents", "send-log.jsonl")
        self.fold = os.path.join(self.base, "fold", "documents", "send-log.jsonl")
        for attr in ("OUTREACH_LOG", "CORRESPONDENCE_LOG"):                 # the live writer's markdown stores stay out of the real tree
            old = getattr(lls, attr)
            setattr(lls, attr, os.path.join(self.base, "none", attr))
            self.addCleanup(setattr, lls, attr, old)

    def folded(self, writer, key, fields):
        sl.spool(self.fold, "update", writer, key, fields)
        sl.fold(os.path.join(self.base, "fold"))
        return open(self.fold, encoding="utf-8").read()

    def same(self):
        self.assertEqual(strip(open(self.live, encoding="utf-8").read()), strip(open(self.fold, encoding="utf-8").read()))

    def test_set_stage_forward(self):
        row, err = lls.set_stage("lee@zz.example", "replied", self.live, when="2026-10-09", note="they wrote back")
        self.assertIsNone(err)
        self.folded("set_stage", {"to": "lee@zz.example"}, {"stage": "replied", "stage_at": "2026-10-09", "stage_note": "they wrote back"})
        self.same()

    def test_set_stage_picks_the_linkedin_row_by_either_spelling(self):
        lls.set_stage("https://www.linkedin.example/in/zzyx-widgets-fake-0001/", "interview", self.live, when="2026-10-09")
        self.folded("set_stage", {"to": "https://www.linkedin.example/in/zzyx-widgets-fake-0001/"}, {"stage": "interview", "stage_at": "2026-10-09"})
        self.same()

    def test_a_backwards_stage_is_refused_live_and_lands_in_the_refused_file_with_the_same_sentence(self):
        row, err = lls.set_stage("linkedin:zzyx-widgets-fake-0001", "sent", self.live, when="2026-10-09")
        self.assertIsNone(row)
        before = open(self.fold, encoding="utf-8").read()
        self.folded("set_stage", {"to": "linkedin:zzyx-widgets-fake-0001"}, {"stage": "sent", "stage_at": "2026-10-09"})
        self.assertEqual(strip(before), strip(open(self.fold, encoding="utf-8").read()))
        refused = [json.loads(l) for l in open(sl.spool_paths(self.fold)[2], encoding="utf-8")]
        self.assertEqual([err], [x["refusal"] for x in refused])
        self.same()

    def test_mark_replied(self):
        lls.mark_replied("wes@zz.example", self.live, when="2026-10-09")
        self.folded("mark_replied", {"to": "wes@zz.example"}, {"replied_note": "marked replied 2026-10-09"})
        self.same()

    def test_confirm_sent_with_company_and_subject_flips_the_row_meant(self):
        lls.confirm_sent("pat@zz.example", self.live, company="Zz One", subject="One", sent_at=SENT["sent_ts"])
        self.folded("confirm_sent", {"to": "pat@zz.example", "company": "Zz One", "subject": "One"}, SENT)
        self.same()
        self.assertEqual("staged", [json.loads(l) for l in open(self.fold)][1]["status"])     # the other draft stayed a draft

    def test_confirm_sent_without_them_flips_the_newest_unsent(self):
        lls.confirm_sent("sam@zz.example", self.live, sent_at=SENT["sent_ts"])
        self.folded("confirm_sent", {"to": "sam@zz.example", "company": "", "subject": ""}, SENT)
        self.same()

    def test_mark_bounced(self):
        row, err = lls.mark_bounced("uma@zz.example", self.live, when="2026-10-09")
        self.assertIsNone(err)
        self.folded("mark_bounced", {"to": "uma@zz.example"}, {"bounced_at": "2026-10-09"})
        self.same()

    def test_a_bounce_on_an_already_bounced_row_is_refused_in_both(self):
        row, err = lls.mark_bounced("kim@zz.example", self.live, when="2026-10-09")
        self.assertIsNone(row)
        self.folded("mark_bounced", {"to": "kim@zz.example"}, {"bounced_at": "2026-10-09"})
        refused = [json.loads(l) for l in open(sl.spool_paths(self.fold)[2], encoding="utf-8")]
        self.assertEqual([err], [x["refusal"] for x in refused])
        self.same()

    def test_a_recipient_with_no_row_is_reported_live_and_stays_in_the_spool_when_folded(self):
        row, err = lls.set_stage("nobody@zz.example", "replied", self.live)
        self.assertEqual("no send-log row for 'nobody@zz.example'", err)
        self.folded("set_stage", {"to": "nobody@zz.example"}, {"stage": "replied", "stage_at": "2026-10-09"})
        self.assertEqual(1, len([l for l in open(sl.spool_paths(self.fold)[0]) if l.strip()]))
        self.assertEqual(["set_stage, nobody@zz.example"], sl.orphans(os.path.join(self.base, "fold")))
        self.same()


class EveryPureFunctionIsUsed(unittest.TestCase):
    def test_each_of_the_five_is_called_by_a_writer_and_by_the_fold(self):
        live = open(os.path.join(SCRIPTS, "log_linkedin_send.py"), encoding="utf-8").read()
        fold = open(os.path.join(SCRIPTS, "sendlog_lock.py"), encoding="utf-8").read()
        for name in ("match_newest", "match_unsent", "current_stage", "stage_refusal"):
            self.assertIn(name + "(", live.split("def mark_bounced")[0] + live.split("def mark_bounced")[1], name)
            self.assertIn("lls." + name + "(", fold, name)
        self.assertIn("match_status(", live)                       # match_unsent is match_status over the unsent statuses
        self.assertIn("return match_status(rows, to, UNSENT_STATUSES", live)


if __name__ == "__main__":
    unittest.main()
