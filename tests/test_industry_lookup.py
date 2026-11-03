#!/usr/bin/env python3
"""#24 task 1: scripts/industry_lookup.py, a maintained public classification source.

Offline, with recorded Wikidata and SEC EDGAR fixtures for the seven companies in kit issue #24 and
obviously fake items (`Example Widgets (FAKE)`, fake QIDs) for the cases a real company cannot stage.
Invariants 1, 2, 3, 5, 6 and the lookup half of 1b from documents/state/outbox/2026-10-04-industry-source-plan.md.
"""
import ast
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, HERE)

from industry_fixture import FakeTransport, fake_entity, set_setup_email  # noqa: E402

_saved_email = []


def setUpModule():
    _saved_email.append(set_setup_email())      # proxy 142: EDGAR runs only with a setup email


def tearDownModule():
    set_setup_email(_saved_email.pop())

# A config the tests own, so this file does not depend on the shipped kit_config defaults (step 2).
CFG = {
    "wikidata": {"Q837171": "financial-services", "Q57774188": "financial-services",
                 "Q22687": "financial-services", "Q43183": "financial-services",
                 "Q1548025": "financial-services", "Q43015": "financial-services",
                 "Q4290": "financial-services", "Q806718": "financial-services",
                 "QFAKEARMS": "defense", "QFAKESOFT": "off-segment", "QFAKESURV": "hold"},
    "sic": [(6021, 6099, "financial-services"), (6300, 6399, "financial-services"),
            (9711, 9711, "defense"), (3812, 3812, "hold")],
    # The kit ships NO vetoing class: each person lists the classes that are THEIR deal-breakers in
    # kit_config.INDUSTRY_USER_FILTERS. These tests act as a person who listed the six below.
    "veto_words": [r"\bdefen[cs]e\b", r"\bmilitary\b", r"\bweapons?\b"],   # the person's INDUSTRY_VETO
    "user_filters": ["defense", "law-enforcement", "gambling", "crypto", "predatory-lending",
                     "dtc-rx-telehealth"],
}
TMP_ROOT = None
BANK_DOMAINS = {"Alder Bank": "alder-bank.example.invalid", "Birch Financial": "birch-financial.example.invalid",
                "Gorse Credit": "gorse-credit.example.invalid", "Dune Capital": "dune-capital.example.invalid",
                "Elm Mutual": "elm-mutual.example.invalid", "Quokka Savings": "quokka-savings.example.invalid"}


def load():
    import industry_lookup
    industry_lookup.reset_memo()
    return industry_lookup


class TestSevenBanks(unittest.TestCase):
    def test_six_of_seven_resolve_by_domain(self):
        # Invariant 1. Plover Trust has no Wikidata item and no EDGAR row (a private holding),
        # so the seventh is the honest absence tested below, not a classification.
        il = load()
        for name, dom in BANK_DOMAINS.items():
            t = FakeTransport()
            r = il.lookup(name, domain=dom, transport=t, cfg=CFG, today=date(2026, 10, 4))
            self.assertIsNotNone(r, name)
            self.assertEqual(r["matched_by"], "domain", name)
            self.assertEqual(r["class"], "financial-services", name)
            self.assertTrue(r["code"].startswith("wikidata:Q"), name)
            self.assertIn("wikidata.org", r["source"], name)
            self.assertEqual(r["checked"], "2026-10-04")

    def test_plover_is_absent_from_both_sources(self):
        il = load()
        r, detail = il.lookup_ex("Plover Trust", transport=FakeTransport(), cfg=CFG)
        self.assertIsNone(r)
        self.assertIn("not in Wikidata or EDGAR", detail)

    def test_no_domain_edgar_resolves_the_public_names(self):
        il = load()
        got = {}
        for name in ("Alder Bank", "Gorse Credit", "Birch Financial"):
            r = il.lookup(name, transport=FakeTransport(), cfg=CFG)
            got[name] = r
            self.assertEqual(r["matched_by"], "edgar", name)
            self.assertTrue(r["code"].startswith("sic:6"), name)
            self.assertEqual(r["class"], "financial-services", name)
            self.assertIn("sec.gov", r["source"])

    def test_no_domain_a_sole_label_match_is_label_only(self):
        # Synthetic data shaped like the measured cases: Dune Capital and Quokka Savings have a single business item whose label
        # equals the name, but no EDGAR name equal to it, so without a domain they are label-only.
        il = load()
        for name in ("Dune Capital", "Quokka Savings"):
            r = il.lookup(name, transport=FakeTransport(), cfg=CFG)
            self.assertEqual(r["matched_by"], "label", name)

    def test_elm_mutual_name_is_not_a_label_match(self):
        # Wikidata labels the parent "Elm National Corporation"; "Elm Mutual Field" is a
        # stadium. Without the domain this stays unclassified, never the first hit.
        il = load()
        r, detail = il.lookup_ex("Elm Mutual", transport=FakeTransport(), cfg=CFG)
        self.assertIsNone(r)


class TestFailClosed(unittest.TestCase):
    def test_ambiguous_label_returns_none(self):
        # Invariant 2.
        il = load()
        t = FakeTransport(
            extra_search={"Example Widgets": [
                {"id": "QFAKE1", "label": "Example Widgets", "description": ""},
                {"id": "QFAKE2", "label": "Example Widgets", "description": ""}]},
            extra_entities={"QFAKE1": fake_entity("Example Widgets", p452=("QFAKESOFT",)),
                            "QFAKE2": fake_entity("Example Widgets", p452=("QFAKEARMS",))})
        r, detail = il.lookup_ex("Example Widgets (FAKE)", transport=t, cfg=CFG)
        self.assertIsNone(r)
        self.assertIn("ambiguous (2 items)", detail)

    def test_a_domain_disambiguates_two_same_label_items(self):
        il = load()
        t = FakeTransport(
            extra_search={"Example Widgets": [
                {"id": "QFAKE1", "label": "Example Widgets", "description": ""},
                {"id": "QFAKE2", "label": "Example Widgets", "description": ""}]},
            extra_entities={
                "QFAKE1": fake_entity("Example Widgets", p452=("QFAKESOFT",), p856=("https://www.example-widgets.test/",)),
                "QFAKE2": fake_entity("Example Widgets", p452=("QFAKEARMS",), p856=("https://widgets.example.invalid/",))},
            extra_labels={"QFAKESOFT": "software", "QFAKEARMS": "arms"})
        r = il.lookup("Example Widgets (FAKE)", domain="example-widgets.test", transport=t, cfg=CFG)
        self.assertEqual(r["matched_by"], "domain")
        self.assertEqual(r["class"], "off-segment")
        self.assertEqual(r["industry"], "software")

    def test_non_business_items_are_ignored(self):
        # "Dune Capital" the family name has P31 human-name class Q101352, not a business class.
        il = load()
        t = FakeTransport()
        r = il.lookup("Dune Capital", transport=t, cfg=CFG)
        self.assertIn("QFAKED1", r["code"])

    def test_network_down_is_none_never_resolved(self):
        # Invariant 3 (lookup half).
        il = load()
        r, detail = il.lookup_ex("Alder Bank", transport=FakeTransport(down=True), cfg=CFG)
        self.assertIsNone(r)
        self.assertIn("source unreachable", detail)

    def test_edgar_two_ciks_with_one_name_is_ambiguous(self):
        il = load()
        t = FakeTransport(extra_tickers=[{"cik_str": 1, "title": "EXAMPLE WIDGETS (FAKE) INC"},
                                         {"cik_str": 2, "title": "EXAMPLE WIDGETS (FAKE) CORP"}],
                          extra_submissions={"0000000001": {"sic": "7372", "sicDescription": "x"},
                                             "0000000002": {"sic": "7372", "sicDescription": "x"}})
        r, detail = il.lookup_ex("Example Widgets (FAKE)", transport=t, cfg=CFG)
        self.assertIsNone(r)
        self.assertIn("ambiguous", detail)

    def test_item_without_industry_and_no_edgar_is_none(self):
        il = load()
        t = FakeTransport(
            extra_search={"Noindustry": [{"id": "QFAKE3", "label": "Noindustry", "description": ""}]},
            extra_entities={"QFAKE3": fake_entity("Noindustry")})
        r, detail = il.lookup_ex("Noindustry (FAKE)", transport=t, cfg=CFG)
        self.assertIsNone(r)
        self.assertIn("no industry", detail)

    def test_label_only_veto_family_is_returned_as_label(self):
        # Invariant 1b, lookup half: the veto family rides on a label-only result, flagged as label.
        il = load()
        t = FakeTransport(
            extra_search={"Armsco": [{"id": "QFAKE4", "label": "Armsco", "description": ""}]},
            extra_entities={"QFAKE4": fake_entity("Armsco", p452=("QFAKEARMS",))},
            extra_labels={"QFAKEARMS": "arms industry"})
        r = il.lookup("Armsco (FAKE)", transport=t, cfg=CFG)
        self.assertEqual((r["matched_by"], r["class"]), ("label", "defense"))

    def test_a_veto_family_label_match_beats_a_resolving_match(self):
        # Fail closed when two sources disagree: the stricter class is the one reported.
        il = load()
        t = FakeTransport(
            extra_search={"Both": [{"id": "QFAKE5", "label": "Both", "description": ""}]},
            extra_entities={"QFAKE5": fake_entity("Both", p452=("QFAKEARMS",))},
            extra_labels={"QFAKEARMS": "arms industry"},
            extra_tickers=[{"cik_str": 5, "title": "BOTH (FAKE) INC"}],
            extra_submissions={"0000000005": {"sic": "7372", "sicDescription": "software"}})
        r = il.lookup("Both (FAKE)", transport=t, cfg=CFG)
        self.assertEqual(r["class"], "defense")


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir="/home/vscode/render") if os.path.isdir("/home/vscode/render") else tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "industry-lookup-cache.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_run_makes_zero_requests(self):
        # Invariant 5.
        il = load()
        t = FakeTransport()
        a = il.lookup_cached("Alder Bank", transport=t, cfg=CFG, cache_path=self.path)
        n = len(t.calls)
        self.assertGreater(n, 0)
        b = il.lookup_cached("Alder Bank", transport=t, cfg=CFG, cache_path=self.path)
        self.assertEqual(len(t.calls), n)
        self.assertEqual(a["code"], b["code"])

    def test_a_negative_answer_is_cached_too(self):
        il = load()
        t = FakeTransport()
        il.lookup_cached("Plover Trust", transport=t, cfg=CFG, cache_path=self.path)
        n = len(t.calls)
        r = il.lookup_cached("Plover Trust", transport=t, cfg=CFG, cache_path=self.path)
        self.assertIsNone(r)
        self.assertEqual(len(t.calls), n)

    def test_unreachable_is_not_cached_as_a_verdict(self):
        # A dead network must not write "not found" for 90 days.
        il = load()
        il.lookup_cached("Alder Bank", transport=FakeTransport(down=True), cfg=CFG, cache_path=self.path)
        t = FakeTransport()
        r = il.lookup_cached("Alder Bank", transport=t, cfg=CFG, cache_path=self.path)
        self.assertIsNotNone(r)
        self.assertGreater(len(t.calls), 0)

    def test_label_only_with_edgar_down_is_not_cached_so_it_can_still_resolve(self):
        # Measured on 2026-10-04: SEC answers 403 to a User-Agent with no contact email. A partial
        # answer (Wikidata label-only, EDGAR unreachable) must not pin "cannot resolve" for 90 days.
        il = load()
        r = il.lookup_cached("Dune Capital", transport=FakeTransport(sec_down=True), cfg=CFG, cache_path=self.path)
        self.assertIsNone(r)                      # M3: a partial answer is not handed on at all
        self.assertIsNone(il.cached("Dune Capital", path=self.path))
        # EDGAR comes back: the next run asks again
        t = FakeTransport()
        il.lookup_cached("Dune Capital", transport=t, cfg=CFG, cache_path=self.path)
        self.assertGreater(len(t.calls), 0)

    def test_a_label_only_veto_is_cached_even_with_edgar_down(self):
        # The veto must survive an outage, because the gate reads only the cache.
        il = load()
        t = FakeTransport(
            sec_down=True,
            extra_search={"Armsco": [{"id": "QFAKE4", "label": "Armsco", "description": ""}]},
            extra_entities={"QFAKE4": fake_entity("Armsco", p452=("QFAKEARMS",))},
            extra_labels={"QFAKEARMS": "arms industry"})
        il.lookup_cached("Armsco (FAKE)", transport=t, cfg=CFG, cache_path=self.path)
        self.assertEqual(il.cached("Armsco (FAKE)", path=self.path)["class"], "defense")

    def test_m2_absent_and_label_only_non_veto_are_cached_when_edgar_is_skipped(self):
        # With no setup email EDGAR is skipped (not unreachable), so the answer is complete and is
        # cached with the same 90-day refresh: a re-run makes no request for either name.
        il = load()
        old = set_setup_email(None)
        try:
            t = FakeTransport()
            self.assertIsNone(il.lookup_cached("Plover Trust", transport=t, cfg=CFG, cache_path=self.path))
            r = il.lookup_cached("Dune Capital", transport=t, cfg=CFG, cache_path=self.path)
            self.assertEqual(r["matched_by"], "label")
            self.assertEqual(il.cached("Plover Trust", path=self.path)["status"], "none")
            self.assertEqual(il.cached("Dune Capital", path=self.path)["matched_by"], "label")
            n = len(t.calls)
            il.lookup_cached("Plover Trust", transport=t, cfg=CFG, cache_path=self.path)
            il.lookup_cached("Dune Capital", transport=t, cfg=CFG, cache_path=self.path)
            self.assertEqual(len(t.calls), n)
        finally:
            set_setup_email(old)

    def test_m3_a_partial_answer_never_resolves_a_weapons_company(self):
        # Wikidata down, EDGAR says SIC 3812 (search and navigation, the defense primes' code).
        # With the real shipped map and with a map that does not know 3812, the result is never a
        # resolving match, and nothing is cached as a verdict.
        il = load()
        extra = dict(extra_tickers=[{"cik_str": 9, "title": "ARMSCO (FAKE) INC"}],
                     extra_submissions={"0000000009": {"sic": "3812", "sicDescription": "Search, Detection, Navigation"}})
        for cfg in (CFG, {"wikidata": {}, "sic": [], "user_filters": []}):
            p = self.path + str(id(cfg))
            r = il.lookup_cached("Armsco (FAKE)", transport=FakeTransport(wd_down=True, **extra), cfg=cfg, cache_path=p)
            self.assertIsNone(r)
            self.assertIsNone(il.cached("Armsco (FAKE)", path=p))
            r2, detail = il.lookup_ex("Armsco (FAKE)", transport=FakeTransport(wd_down=True, **extra), cfg=cfg)
            self.assertIsNone(r2)
            self.assertIn("unreachable", detail)

    def test_m3_a_veto_may_be_kept_from_a_partial_answer(self):
        il = load()
        t = FakeTransport(
            sec_down=True,
            extra_search={"Armsco": [{"id": "QFAKE4", "label": "Armsco", "description": ""}]},
            extra_entities={"QFAKE4": fake_entity("Armsco", p452=("QFAKEARMS",), p856=("https://armsco.example.invalid",))},
            extra_labels={"QFAKEARMS": "arms industry"})
        r = il.lookup_cached("Armsco (FAKE)", domain="armsco.example.invalid", transport=t, cfg=CFG, cache_path=self.path)
        self.assertEqual(r["class"], "defense")

    def test_s1_hold_class_never_resolves_and_is_not_ingested(self):
        il = load()
        r = il.lookup("Armsco (FAKE)", transport=FakeTransport(
            extra_tickers=[{"cik_str": 9, "title": "ARMSCO (FAKE) INC"}],
            extra_submissions={"0000000009": {"sic": "3812", "sicDescription": "Search, Detection, Navigation"}}), cfg=CFG)
        self.assertEqual((r["matched_by"], r["class"]), ("edgar", "hold"))
        self.assertFalse(il.vetoes("hold", CFG))
        self.assertIsNone(il.ingest_row("Armsco (FAKE)", r))

    def test_s2_the_class_is_worked_out_at_read_time_from_the_stored_codes(self):
        # A row cached under an old map (class off-segment) reads as a veto once the map knows it.
        il = load()
        row = {"name": "Armsco (FAKE)", "status": "match", "matched_by": "domain", "code": "wikidata:QFAKE4",
               "industry": "arms industry", "industry_codes": ["QFAKEARMS"], "class": "off-segment",
               "source": "https://www.wikidata.org/wiki/QFAKE4", "checked": date.today().isoformat()}
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        self.assertEqual(il.reclass(row, CFG), "defense")
        self.assertEqual(il.gate_read("Armsco (FAKE)", path=self.path, cfg=CFG)[0], "vetoed")
        sic = dict(row, code="sic:3812", industry_codes=None, matched_by="edgar", industry="Search")
        self.assertEqual(il.reclass(sic, CFG), "hold")

    def test_m4_the_looked_up_industry_label_is_checked_against_the_veto_words(self):
        # An industry QID the map does not know, whose LABEL trips a veto word (Wikidata spells it
        # "defence"), still vetoes.
        il = load()
        t = FakeTransport(
            extra_search={"Labelco": [{"id": "QFAKE6", "label": "Labelco", "description": ""}]},
            extra_entities={"QFAKE6": fake_entity("Labelco", p452=("QUNMAPPED",), p856=("https://labelco.example.invalid",))},
            extra_labels={"QUNMAPPED": "defence industry"})
        r = il.lookup("Labelco (FAKE)", domain="labelco.example.invalid", transport=t, cfg=CFG)
        self.assertTrue(il.vetoes(r["class"], CFG), r)

    def test_142b_a_veto_caught_only_by_the_4th_label_survives_read_back(self):
        # "Zedd": domain match, six industries, only the 4th label ("military technology") trips a veto
        # word. The stored row must keep EVERY label the check saw, so the veto is still there on read.
        il = load()
        qs = ["QZ%d" % i for i in range(6)]
        labels = {"QZ0": "software", "QZ1": "analytics", "QZ2": "consulting", "QZ3": "military technology",
                  "QZ4": "logistics", "QZ5": "research"}
        t = FakeTransport(
            extra_search={"Zedd": [{"id": "QFAKEZ", "label": "Zedd", "description": ""}]},
            extra_entities={"QFAKEZ": fake_entity("Zedd", p452=tuple(qs), p856=("https://zed.example.invalid",))},
            extra_labels=labels)
        r = il.lookup_cached("Zedd", domain="zed.example.invalid", transport=t, cfg=CFG, cache_path=self.path)
        self.assertTrue(il.vetoes(r["class"], CFG), r)
        self.assertEqual(len(il.cached("Zedd", path=self.path)["industry_labels"]), 6)
        self.assertEqual(il.gate_read("Zedd", path=self.path, cfg=CFG)[0], "vetoed")     # read-back
        self.assertIsNone(il.ingest_row("Zedd", r))                             # and never ingested as resolved
        self.assertIsNone(il.ingest_row("Zedd", {"matched_by": "domain", "class": "defense", "industry": "x",
                                                "source": "https://www.wikidata.org/wiki/Q1"}, cfg=CFG))

    def test_142b_adding_a_domain_bypasses_the_cache_for_that_company(self):
        il = load()
        t = FakeTransport()
        a = il.lookup_cached("Dune Capital", transport=t, cfg=CFG, cache_path=self.path)
        self.assertEqual(a["matched_by"], "label")
        n = len(t.calls)
        il.lookup_cached("Dune Capital", transport=t, cfg=CFG, cache_path=self.path)
        self.assertEqual(len(t.calls), n)                                      # same ask: cached
        b = il.lookup_cached("Dune Capital", domain="dune-capital.example.invalid", transport=t, cfg=CFG, cache_path=self.path)
        self.assertGreater(len(t.calls), n)                                    # a new domain: asked again
        self.assertEqual(b["matched_by"], "domain")
        n2 = len(t.calls)
        il.lookup_cached("Dune Capital", domain="dune-capital.example.invalid", transport=t, cfg=CFG, cache_path=self.path)
        self.assertEqual(len(t.calls), n2)

    def test_a_row_older_than_90_days_refreshes(self):
        il = load()
        t = FakeTransport()
        old = date.today() - timedelta(days=91)
        il.lookup_cached("Alder Bank", transport=t, cfg=CFG, cache_path=self.path, today=old)
        n = len(t.calls)
        il.lookup_cached("Alder Bank", transport=t, cfg=CFG, cache_path=self.path)
        self.assertGreater(len(t.calls), n)

    def test_newest_row_wins_and_the_file_is_append_only(self):
        il = load()
        t = FakeTransport()
        old = date.today() - timedelta(days=91)
        il.lookup_cached("Alder Bank", transport=t, cfg=CFG, cache_path=self.path, today=old)
        il.lookup_cached("Alder Bank", transport=t, cfg=CFG, cache_path=self.path)
        rows = [json.loads(x) for x in open(self.path, encoding="utf-8") if x.strip()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(il.cached("Alder Bank", path=self.path)["checked"], date.today().isoformat())


class TestStructure(unittest.TestCase):
    SRC = os.path.join(REPO, "scripts", "industry_lookup.py")

    def test_imports_stdlib_only(self):
        # Invariant 6. kit_config is the one repo module allowed, because it carries the map as data.
        tree = ast.parse(open(self.SRC, encoding="utf-8").read())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])
        outside = {m for m in mods if m not in sys.stdlib_module_names and m != "kit_config"}
        self.assertEqual(outside, set())

    def test_names_only_wikidata_and_sec_hosts(self):
        import re
        src = open(self.SRC, encoding="utf-8").read()
        hosts = set(re.findall(r"https?://([A-Za-z0-9.-]+)", src))
        allowed = {"www.wikidata.org", "www.sec.gov", "data.sec.gov"}
        # doc URLs in the docstring cite the two policies; anything else is a new host.
        extra = {h for h in hosts if h not in allowed and not h.endswith("wikidata.org") and not h.endswith("sec.gov")
                 and h not in {"github.com", "example.com"}}
        self.assertEqual(extra, set())

    def test_never_writes_employer_segments(self):
        # Invariant 4, structural half: the only writer of the segment cache is resolve_employers.
        src = open(self.SRC, encoding="utf-8").read()
        self.assertNotIn("employer-segments", src)
        self.assertNotIn("EMPLOYER_CACHE", src)
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "open" and len(n.args) > 1:
                mode = getattr(n.args[1], "value", "")
                if isinstance(mode, str) and ("w" in mode or "a" in mode):
                    # the one permitted writer opens the LOOKUP cache path, never a segment path
                    self.assertIn("path", ast.unparse(n.args[0]).lower())

    def test_proxy_142_setup_email_goes_in_the_sec_header_only(self):
        il = load()
        sentinel = "owner-sentinel@example.invalid"
        old = set_setup_email(sentinel)
        try:
            t = FakeTransport()
            il.lookup("Alder Bank", transport=t, cfg=CFG)
            self.assertGreater(len(t.sec_calls()), 0)
            for url, headers in t.calls:
                self.assertTrue(headers["User-Agent"].startswith("Job Attractor kit"))
                self.assertNotIn(sentinel, url)
                if url.split("/")[2].endswith("sec.gov"):
                    self.assertIn(sentinel, headers["User-Agent"])
                else:
                    self.assertNotIn(sentinel, json.dumps(headers))   # no Wikidata request carries it
            self.assertEqual(t.hosts(), {"www.wikidata.org", "www.sec.gov", "data.sec.gov"})
            self.assertIn(sentinel, il.user_agent(email=sentinel))
            self.assertNotIn("@", il.user_agent(email=""))
        finally:
            set_setup_email(old)

    def test_proxy_142_no_setup_email_skips_edgar_entirely(self):
        # No request to sec.gov, and EDGAR is not counted as unreachable: Wikidata alone answers.
        il = load()
        old = set_setup_email(None)
        try:
            t = FakeTransport()
            r, detail = il.lookup_ex("Alder Bank", domain="alder-bank.example.invalid", transport=t, cfg=CFG)
            self.assertEqual(r["matched_by"], "domain")
            self.assertEqual(detail, "")                      # not "partial: a source was unreachable"
            self.assertEqual(t.sec_calls(), [])
            r2, d2 = il.lookup_ex("Plover Trust", transport=t, cfg=CFG)
            self.assertIsNone(r2)
            self.assertNotIn("unreachable", d2)
            self.assertEqual(t.sec_calls(), [])
        finally:
            set_setup_email(old)

    def test_the_kits_feedback_address_never_reaches_a_header(self):
        # The kit already has kit_config.MAINTAINER_EMAIL for mailto feedback; the lookup must not read
        # it. Only the person's own setup email goes in SEC's header, and nothing in Wikidata's.
        self.assertNotIn("MAINTAINER_EMAIL", open(self.SRC, encoding="utf-8").read())
        import importlib
        kc = importlib.import_module("kit_config")
        old = getattr(kc, "MAINTAINER_EMAIL", None)
        kc.MAINTAINER_EMAIL = "maint-sentinel@example.invalid"
        try:
            il = load()
            t = FakeTransport()
            il.lookup("Alder Bank", transport=t, cfg=CFG)
            self.assertNotIn("maint-sentinel", json.dumps(t.calls))
        finally:
            kc.MAINTAINER_EMAIL = old

    def test_the_kit_placeholder_owner_email_counts_as_no_email(self):
        # kit_config.example.py ships OWNER_EMAIL = "you@example.com"; that is not a contact and SEC
        # would be sent a fake one. It is treated as unset, so EDGAR is skipped.
        import importlib
        kc = importlib.import_module("kit_config")
        old_env = set_setup_email(None)
        old = getattr(kc, "OWNER_EMAIL", None)
        kc.OWNER_EMAIL = "you@example.com"
        try:
            il = load()
            self.assertEqual(il.owner_email(), "")
            t = FakeTransport()
            il.lookup("Alder Bank", transport=t, cfg=CFG)
            self.assertEqual(t.sec_calls(), [])
            kc.OWNER_EMAIL = "real-person@example.invalid"      # the person's own kit_config value
            self.assertEqual(il.owner_email(), "real-person@example.invalid")
            self.assertGreater(len(il.lookup_ex("Alder Bank", transport=t, cfg=CFG) and t.sec_calls()), 0)
        finally:
            kc.OWNER_EMAIL = old
            set_setup_email(old_env)

    def test_the_kit_example_sample_veto_words_spell_defence_both_ways(self):
        src = open(os.path.join(REPO, "scripts", "kit_config.example.py"), encoding="utf-8").read()
        self.assertIn("defen[cs]e", src)

    def test_142c_the_veto_message_names_the_label_that_tripped_it(self):
        il = load()
        row = {"name": "Quillon Zedd (FAKE)", "status": "match", "matched_by": "domain", "code": "wikidata:QFAKEZ",
               "industry": "software, analytics, consulting", "industry_codes": ["QZ0", "QZ1", "QZ2", "QZ3"],
               "industry_labels": ["software", "analytics", "consulting", "military technology"],
               "class": "veto-term", "source": "https://www.wikidata.org/wiki/QFAKEZ",
               "checked": date.today().isoformat()}
        path = os.path.join(tempfile.mkdtemp(dir=TMP_ROOT), "c.jsonl")
        open(path, "w", encoding="utf-8").write(json.dumps(row) + "\n")
        verdict, detail = il.gate_read("Quillon Zedd (FAKE)", path=path, cfg=dict(CFG, veto_words=[r"\bmilitary\b"]))
        self.assertEqual(verdict, "vetoed")
        self.assertIn("military technology", detail)
        self.assertIn("matched", detail)


if __name__ == "__main__":
    unittest.main()
