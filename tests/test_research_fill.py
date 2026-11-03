#!/usr/bin/env python3
"""research_fill.py: the engine half of BUG-305 and BUG-310. Every test builds a throwaway repo
(a card file, an export dir) so nothing touches the real tree. The suite is written against the
BROKEN world first: an item at try 14 must stop, an unverified value must never beat a sourced one,
an empty look must not read as a pass, and no write may land outside documents/state/research/.
Run: python3 -m unittest tests.test_research_fill"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SPEC = importlib.util.spec_from_file_location("research_fill", os.path.join(ROOT, "scripts", "research_fill.py"))
rf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rf)

D1, D2, D3 = "2026-09-21", "2026-09-22", "2026-09-23"


def card_text(company, unread=("dedup", "ownership", "product_team")):
    """A card whose gates in `unread` have no section (none) or an OWED line, the rest PASS."""
    heads = {"dedup": "Prior contact (DEDUP)", "blocked": "Blocked list", "news": "News & layoffs",
             "culture": "Culture", "leadership": "Leadership", "remote": "Remote",
             "ownership": "Ownership", "boss": "Boss", "product_team": "Product team",
             "live_req": "Live PM req"}
    out = ["# %s · Fintech · panel 80/80/80 · mean 80 · 2026-09-10" % company, ""]
    for key, head in heads.items():
        if key == "product_team" and key in unread:
            out += ["## %s" % head, "OWED: read not pulled", ""]
        elif key in unread:
            continue
        else:
            out += ["## %s" % head, "PASS. Checked.", ""]
    return "\n".join(out)


class World:
    def __init__(self, cards=None):
        self.root = tempfile.mkdtemp(prefix="rf_")
        self.state = os.path.join(self.root, "documents", "state")
        self.out = os.path.join(self.state, "research")
        os.makedirs(os.path.join(self.out, "exports"))
        for slug, txt in (cards if cards is not None else {"zzwidgets": card_text("Example Widgets (FAKE)")}).items():
            with open(os.path.join(self.state, "%s-card-2026-09-10.md" % slug), "w") as f:
                f.write(txt)

    def export(self, name, docs):
        with open(os.path.join(self.out, "exports", name), "w") as f:
            json.dump({"documents": docs}, f)

    def run(self, today=D1, cap=10, dry=False):
        return rf.run(self.root, today=today, cap=cap, dry_run=dry)

    def load(self, name):
        with open(os.path.join(self.out, name)) as f:
            return json.load(f)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def finding(slug="zzwidgets", item="ownership", value="Family owned", source="engine",
            url="https://example.org/a", conf="med", at="2026-09-21T10:00:00Z", **kw):
    d = {"slug": slug, "item": item, "value": value, "source": source, "confidence": conf, "at": at}
    if url:
        d["url"] = url
    d.update(kw)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.addCleanup(self.w.cleanup)


class UnreadGates(Base):
    def test_zzwidgets_has_three_unread_items(self):
        s = self.w.run(dry=True)
        self.assertEqual(s["unread_items"], 3)
        self.assertEqual({i["item"] for i in s["plan"]}, {"dedup", "ownership", "product_team"})

    def test_no_cards_is_a_refusal_not_a_pass(self):
        empty = World(cards={})
        self.addCleanup(empty.cleanup)
        with self.assertRaises(rf.NothingToLookAt):
            empty.run()


class DailyFill(Base):
    def test_each_item_is_tried_once_a_day(self):
        self.assertEqual(len(self.w.run(D1)["plan"]), 3)
        again = self.w.run(D1)
        self.assertEqual(len(again["plan"]), 3, "same day re-emits the same plan")
        st = self.w.load("state.json")["items"]
        self.assertTrue(all(v["tries"] == 1 and v["last_tried"] == D1 for v in st.values()), st)
        self.w.run(D2)
        st = self.w.load("state.json")["items"]
        self.assertTrue(all(v["tries"] == 2 and v["last_tried"] == D2 for v in st.values()), st)

    def test_dry_run_writes_nothing_and_counts_no_try(self):
        self.w.run(D1, dry=True)
        self.assertFalse(os.path.exists(os.path.join(self.w.out, "state.json")))

    def test_hard_cap_per_run(self):
        s = self.w.run(D1, cap=2)
        self.assertEqual(len(s["plan"]), 2)
        st = self.w.load("state.json")["items"]
        self.assertEqual(sum(1 for v in st.values() if v["tries"]), 2)
        # the third item is picked up the next day, and the same-day cap still binds
        self.assertEqual(len(self.w.run(D1, cap=2)["plan"]), 2)

    def test_item_at_try_14_stops_and_says_so(self):
        d = __import__("datetime").date(2026, 9, 21)
        last = None
        for n in range(14):
            day = (d + __import__("datetime").timedelta(days=n)).isoformat()
            s = self.w.run(day)
            last = day
            self.assertEqual(len(s["plan"]), 3, "try %d still emits" % (n + 1))
        st = self.w.load("state.json")["items"]
        self.assertTrue(all(v["tries"] == 14 for v in st.values()))
        nxt = (d + __import__("datetime").timedelta(days=14)).isoformat()
        s = self.w.run(nxt)
        self.assertEqual(s["plan"], [], "a fifteenth try must never be emitted")
        ref = self.w.load("refined.json")["records"]["zzwidgets:ownership"]
        self.assertEqual(ref["status"], "exhausted")
        self.assertEqual(ref["note"], "not found after 14 days (last tried %s)" % last)
        st = self.w.load("state.json")["items"]
        self.assertTrue(all(v["tries"] == 14 for v in st.values()), "tries never pass 14")

    def test_ask_retries_an_exhausted_item_by_hand_once(self):
        d = __import__("datetime").date(2026, 9, 21)
        for n in range(15):
            self.w.run((d + __import__("datetime").timedelta(days=n)).isoformat())
        self.w.export("requests.json", [{"id": "r1", "slug": "zzwidgets", "item": "ownership",
                                         "source": "ask", "at": "2026-10-06T09:00:00Z"}])
        day = "2026-10-06"
        s = self.w.run(day)
        self.assertEqual([i["item"] for i in s["plan"]], ["ownership"])
        self.assertTrue(s["plan"][0]["retry"])
        self.assertEqual(self.w.run("2026-10-07")["plan"], [], "the request is spent")

    def test_a_sourced_item_leaves_the_plan(self):
        self.w.export("findings.json", [finding()])
        s = self.w.run(D1)
        self.assertNotIn("ownership", {i["item"] for i in s["plan"]})

    def test_an_unverified_only_item_stays_due(self):
        self.w.export("findings.json", [finding(source="page-claude", url=None)])
        s = self.w.run(D1)
        self.assertIn("ownership", {i["item"] for i in s["plan"]})

    def test_order_awaiting_and_opened_first(self):
        w = World(cards={"aaa": card_text("Aaa"), "zzwidgets": card_text("Example Widgets (FAKE)")})
        self.addCleanup(w.cleanup)
        w.export("requests.json", [{"id": "r1", "slug": "zzwidgets", "item": "dedup", "source": "open",
                                    "at": "2026-09-21T08:00:00Z"}])
        plan = w.run(D1, cap=1)["plan"]
        self.assertEqual((plan[0]["slug"], plan[0]["item"]), ("zzwidgets", "dedup"))

    def test_a_cleared_gate_drops_out(self):
        w = World(cards={"zzwidgets": card_text("Example Widgets (FAKE)", unread=("dedup",))})
        self.addCleanup(w.cleanup)
        self.assertEqual([i["item"] for i in w.run(D1)["plan"]], ["dedup"])


def staged(company, status):
    return card_text(company).replace("· mean 80 ·", "· mean 80 · STATUS: %s ·" % status)


class Stages(unittest.TestCase):
    """BUILD is scheduled (he is about to write to that boss); PARK, DROP and SENT are skipped."""

    def world(self, **cards):
        w = World(cards=cards)
        self.addCleanup(w.cleanup)
        return w

    def test_build_is_scheduled(self):
        w = self.world(bld=staged("Bld", "BUILD"))
        self.assertEqual(len(w.run(D1)["plan"]), 3)

    def test_park_drop_and_sent_are_skipped(self):
        w = self.world(a=staged("A", "PARK"), b=staged("B", "DROP"), c=staged("C", "SENT"))
        s = w.run(D1)
        self.assertEqual((s["unread_items"], s["plan"]), (0, []))

    def test_a_request_schedules_a_parked_card(self):
        w = self.world(a=staged("A", "PARK"))
        w.export("requests.json", [{"id": "r1", "slug": "a", "item": "dedup", "source": "ask",
                                    "at": "2026-09-21T08:00:00Z"}])
        self.assertEqual([i["item"] for i in w.run(D1)["plan"]], ["dedup", "ownership", "product_team"])

    def test_order_is_awaiting_with_request_then_build_then_awaiting_then_radar(self):
        w = self.world(aaa=card_text("Aaa"), bld=staged("Bld", "BUILD"),
                       zzwidgets=card_text("Example Widgets (FAKE)"), rad=staged("Rad", "RADAR"))
        w.export("requests.json", [{"id": "r1", "slug": "zzwidgets", "item": "dedup", "source": "open",
                                    "at": "2026-09-21T08:00:00Z"}])
        plan = w.run(D1, cap=40)["plan"]
        first = [(i["slug"], i["item"]) for i in plan[:1]]
        self.assertEqual(first, [("zzwidgets", "dedup")])
        slugs = [i["slug"] for i in plan]
        self.assertLess(slugs.index("bld"), slugs.index("aaa"))
        self.assertLess(slugs.index("aaa"), slugs.index("rad"))


class Synthesis(Base):
    def rec(self, findings, item="ownership"):
        self.w.export("findings.json", findings)
        self.w.run(D1)
        return self.w.load("refined.json")["records"]["zzwidgets:" + item]

    def test_sourced_beats_unverified(self):
        r = self.rec([finding(source="page-claude", url=None, value="Public company", at="2026-09-21T12:00:00Z"),
                      finding(value="Family owned")])
        self.assertEqual(r["status"], "sourced")
        self.assertEqual(r["value"], "Family owned")
        self.assertFalse(r["unverified"])
        self.assertEqual([o["value"] for o in r["overridden"]], ["Public company"])

    def test_unverified_alone_is_shown_as_unverified(self):
        r = self.rec([finding(source="page-claude", url=None, value="Family owned")])
        self.assertEqual(r["status"], "unverified")
        self.assertTrue(r["unverified"])

    def test_page_claude_never_becomes_sourced_even_with_a_url(self):
        r = self.rec([finding(source="page-claude", value="Family owned")])
        self.assertEqual(r["status"], "unverified")

    def test_connector_without_url_or_record_is_unverified(self):
        r = self.rec([finding(source="connector:lusha", url=None)])
        self.assertEqual(r["status"], "unverified")

    def test_connector_naming_its_record_is_sourced(self):
        r = self.rec([finding(source="connector:lusha", url=None, record="company/12345")])
        self.assertEqual(r["status"], "sourced")
        self.assertEqual(r["source"], "connector:lusha")

    def test_engine_without_url_is_refused(self):
        # BUG-332/BUG-218: the unattended engine researches the web, so every finding it
        # records must carry the page it came from -- an engine finding with no url is now
        # refused outright rather than accepted as "unverified".
        self.w.export("findings.json", [finding(url=None)])
        s = self.w.run(D1)
        self.assertIn("ownership", {i["item"] for i in s["plan"]})

    def test_sourced_disagreement_is_kept_and_flagged_never_promoted(self):
        r = self.rec([finding(value="Family owned"),
                      finding(value="Private equity", url="https://example.org/b", at="2026-09-21T11:00:00Z")])
        self.assertEqual(r["status"], "disagree")
        self.assertIsNone(r["value"])
        self.assertEqual({c["value"] for c in r["candidates"]}, {"Family owned", "Private equity"})

    def test_same_value_twice_is_agreement(self):
        r = self.rec([finding(value="Family owned"),
                      finding(value="  family   OWNED ", url="https://example.org/b")])
        self.assertEqual(r["status"], "sourced")

    def test_nothing_is_invented(self):
        r = self.rec([])
        self.assertEqual(r["status"], "open")
        self.assertIsNone(r["value"])

    def test_bad_rows_are_skipped_and_counted(self):
        self.w.export("findings.json", [
            {"slug": "zzwidgets", "item": "ownership"},                      # no value
            finding(slug="nobody"),                                     # unknown card
            finding(item="vibes"),                                      # unknown item
            finding(source="rumor"),                                    # unknown source
            finding(at="yesterday"),                                    # unreadable time
            "not even a dict",
            finding(value="Family owned")])
        s = self.w.run(D1)
        self.assertEqual(s["rejected"], 6)
        r = self.w.load("refined.json")["records"]["zzwidgets:ownership"]
        self.assertEqual(r["status"], "sourced")

    def test_missing_exports_are_reported_not_hidden(self):
        s = self.w.run(D1)
        self.assertEqual(s["exports"], {"requests": "absent", "findings": "absent"})

    def test_unparseable_export_is_reported(self):
        with open(os.path.join(self.w.out, "exports", "findings.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(self.w.run(D1)["exports"]["findings"], "unreadable")


class RecordInterface(Base):
    def test_record_lands_in_the_engine_file_and_resolves_the_item(self):
        ok, why = rf.record(self.w.root, finding(), today=D1)
        self.assertTrue(ok, why)
        self.assertTrue(os.path.exists(os.path.join(self.w.out, "engine-findings.json")))
        r = self.w.load("refined.json")["records"]["zzwidgets:ownership"]
        self.assertEqual(r["status"], "sourced")

    def test_record_refuses_a_bad_finding(self):
        ok, why = rf.record(self.w.root, finding(item="vibes"), today=D1)
        self.assertFalse(ok)
        self.assertIn("item", why)
        self.assertFalse(os.path.exists(os.path.join(self.w.out, "engine-findings.json")))

    def test_record_is_idempotent(self):
        rf.record(self.w.root, finding(), today=D1)
        rf.record(self.w.root, finding(), today=D1)
        self.assertEqual(len(self.w.load("engine-findings.json")["documents"]), 1)


class WritesStayUnderTheResearchDir(Base):
    def test_a_write_outside_is_refused(self):
        with self.assertRaises(rf.OutsideResearchDir):
            rf._write_json(self.w.root, os.path.join(self.w.state, "escape.json"), {})
        with self.assertRaises(rf.OutsideResearchDir):
            rf._write_json(self.w.root, os.path.join(self.w.out, "..", "escape.json"), {})
        self.assertFalse(os.path.exists(os.path.join(self.w.state, "escape.json")))

    def test_a_full_run_touches_only_the_research_dir(self):
        before = set(os.listdir(self.w.state))
        self.w.export("findings.json", [finding()])
        self.w.run(D1)
        self.assertEqual(set(os.listdir(self.w.state)), before)
        self.assertEqual(sorted(os.listdir(self.w.out)),
                         ["exports", "plan.json", "refined.json", "state.json"])


class DatesAndMessages(Base):
    def test_an_impossible_today_is_refused_and_nothing_is_written(self):
        for bad in ("2026-09-35", "yesterday", "2026-9-1"):
            with self.subTest(bad=bad):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = rf.main(["--repo", self.w.root, "--today", bad])
                self.assertEqual(code, 3)
        self.assertFalse(os.path.exists(os.path.join(self.w.out, "state.json")))
        with self.assertRaises(rf.BadDate):
            rf.run(self.w.root, today="2026-09-35")

    def test_an_unknown_source_names_the_accepted_forms(self):
        ok, why = rf.record(self.w.root, finding(source="rumor"), today=D1)
        self.assertFalse(ok)
        for form in ("engine", "page-claude", "connector:<name>"):
            self.assertIn(form, why)


class EngineFindingsNeedAUrl(Base):
    """BUG-332/BUG-218: the unattended engine researches the web, so every finding it records
    must carry the page it came from. Scoped to source == "engine" only -- page-claude and a
    connector with no record stay accepted as "unverified", exactly as before."""

    def test_no_url_key_is_refused_naming_slug_and_item(self):
        ok, why = rf.record(self.w.root, finding(source="engine", url=None), today=D1)
        self.assertFalse(ok)
        self.assertIn("zzwidgets", why)
        self.assertIn("ownership", why)

    def test_empty_string_url_is_refused(self):
        ok, why = rf.record(self.w.root, finding(source="engine", url=""), today=D1)
        self.assertFalse(ok)

    def test_non_http_url_is_refused(self):
        ok, why = rf.record(self.w.root, finding(source="engine", url="ftp://example.org/a"), today=D1)
        self.assertFalse(ok)

    def test_a_real_http_url_still_passes(self):
        ok, why = rf.record(self.w.root, finding(source="engine", url="https://example.org/a"), today=D1)
        self.assertTrue(ok, why)

    def test_page_claude_with_no_url_is_still_accepted_unverified(self):
        # The scope is engine-only; this must NOT change.
        ok, why = rf.record(self.w.root, finding(source="page-claude", url=None), today=D1)
        self.assertTrue(ok, why)

    def test_connector_with_no_url_and_no_record_is_still_accepted_unverified(self):
        # Also unchanged: a connector without url or record stays "unverified", never refused.
        ok, why = rf.record(self.w.root, finding(source="connector:lusha", url=None), today=D1)
        self.assertTrue(ok, why)


class RequestStatus(Base):
    REQ = {"id": "r1", "slug": "zzwidgets", "item": "ownership", "source": "ask", "at": "2026-09-21T08:00:00Z"}

    def status(self, cap=10, day=D1):
        self.w.run(day, cap=cap)
        return self.w.load("refined.json")["records"]["zzwidgets:ownership"]["request"]

    def test_no_request_is_none(self):
        self.w.run(D1)
        self.assertIsNone(self.w.load("refined.json")["records"]["zzwidgets:ownership"]["request"])

    def test_picked_up_then_answered(self):
        self.w.export("requests.json", [self.REQ])
        r = self.status()
        self.assertEqual((r["id"], r["source"], r["status"]), ("r1", "ask", "picked_up"))
        rf.record(self.w.root, finding(at="2026-09-21T12:00:00Z"), today=D1)
        r = self.w.load("refined.json")["records"]["zzwidgets:ownership"]["request"]
        self.assertEqual(r["status"], "answered")

    def test_an_older_finding_does_not_answer_a_newer_request(self):
        self.w.export("findings.json", [finding(source="page-claude", url=None, at="2026-09-01T00:00:00Z")])
        self.w.export("requests.json", [self.REQ])
        self.assertEqual(self.status()["status"], "picked_up")

    def test_waiting_means_not_yet_in_a_plan(self):
        w = World(cards={"zzwidgets": card_text("Example Widgets (FAKE)")})
        self.addCleanup(w.cleanup)
        w.export("requests.json", [self.REQ])
        w.run(D1, cap=0)
        self.assertEqual(w.load("refined.json")["records"]["zzwidgets:ownership"]["request"]["status"], "waiting")


class RecordFileAgreesWithRecord(Base):
    """98's finding: --record fills in `at` (now) when it is missing, but --record-file refused the same row with
    "unreadable time". A batch row and a single row must be treated alike. Only a MISSING or blank `at` is filled;
    a present but unreadable one is still refused."""

    def batch(self, rows):
        path = os.path.join(self.w.root, "batch.json")
        with open(path, "w") as f:
            json.dump(rows, f)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rf.main(["--repo", self.w.root, "--today", D1, "--record-file", path])
        return code, buf.getvalue()

    def row(self, **kw):
        d = finding()
        d.pop("at")
        d.update(kw)
        return d

    def test_a_batch_row_with_no_at_is_recorded_like_a_single_record(self):
        code, out = self.batch([self.row()])
        self.assertEqual(code, 0, out)
        r = self.w.load("engine-findings.json")["documents"][0]
        self.assertRegex(r["at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_a_blank_at_is_filled_too(self):
        for blank in ("", "   ", None):
            with self.subTest(blank=blank):
                w = World()
                self.addCleanup(w.cleanup)
                self.w = w
                self.assertEqual(self.batch([self.row(at=blank)])[0], 0)

    def test_a_present_but_unreadable_at_is_still_refused(self):
        code, out = self.batch([self.row(at="yesterday")])
        self.assertEqual(code, 2)
        self.assertIn("unreadable time", out)
        self.assertFalse(os.path.exists(os.path.join(self.w.out, "engine-findings.json")))

    def test_the_single_record_path_still_fills_in_now(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rf.main(["--repo", self.w.root, "--today", D1, "--record", "--slug", "zzwidgets", "--item", "ownership",
                            "--value", "Family owned", "--source", "engine", "--url", "https://example.org/a"])
        self.assertEqual(code, 0, buf.getvalue())

    def test_a_batch_that_mixes_a_good_and_a_dateless_row_records_both(self):
        code, out = self.batch([finding(item="dedup", value="No prior contact"), self.row(item="ownership")])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.w.load("engine-findings.json")["documents"]), 2)


class Cli(Base):
    def test_summary_line_and_exit_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rf.main(["--repo", self.w.root, "--today", D1])
        self.assertEqual(code, 0)
        self.assertIn("unread 3", buf.getvalue())

    def test_no_cards_exits_nonzero(self):
        e = World(cards={})
        self.addCleanup(e.cleanup)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rf.main(["--repo", e.root, "--today", D1])
        self.assertEqual(code, 4)


if __name__ == "__main__":
    unittest.main()
