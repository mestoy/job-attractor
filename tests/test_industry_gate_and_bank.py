#!/usr/bin/env python3
"""#24 tasks 3 and 4: the screen gate reads the lookup cache, and `screen_sweep.py --bank` feeds it.

Plan invariants 1 (gate half), 1b, 1c, 3 (bank half), 4, 5 (bank half) and 7. Every path is
redirected to a temp dir, so nothing here touches the live caches or the live banked file.
"""
import os as _os, sys as _sys  # BUG-736: seed kit_config first (bare checkout has only the example)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _kit_config_shim  # noqa: E402,F401
import json
import os
import _roots
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, HERE)

import contact_signals as cs  # noqa: E402
import industry_lookup as il  # noqa: E402
import resolve_employers as rs  # noqa: E402
import screen_sweep as ss  # noqa: E402
import check_screen_gate as gate  # noqa: E402
from industry_fixture import FakeTransport, fake_entity, set_setup_email  # noqa: E402

TMP_ROOT = "/home/vscode/render" if os.path.isdir("/home/vscode/render") else None
SIX = ["defense", "law-enforcement", "gambling", "crypto", "predatory-lending", "dtc-rx-telehealth"]


def ingest_add(rows, **kw):
    """The kit's ingest rejects an employer outside the people pool unless add_employer is set; the
    bank pass sets it (a swept company has no contacts yet), and so do these tests."""
    return rs.ingest_rows(rows, add_employer=True, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=TMP_ROOT)
        os.makedirs(os.path.join(self.tmp, "documents", "state"))
        self.lcache = os.path.join(self.tmp, "documents", "state", "industry-lookup-cache.jsonl")
        self.seg = os.path.join(self.tmp, "documents", "state", "employer-segments.jsonl")
        self._saved = (il.CACHE, cs.EMPLOYER_CACHE, rs.CACHE, cs._EMPLOYER_CACHE, ss.REPO,
                       ss._register_banked_identity)
        il.CACHE, cs.EMPLOYER_CACHE, rs.CACHE, cs._EMPLOYER_CACHE = self.lcache, self.seg, self.seg, None
        ss.REPO = self.tmp
        _roots.patch_roots(self, self.tmp)
        ss._register_banked_identity = lambda *a, **k: None
        il.reset_memo()
        self._old_email = set_setup_email()
        # a person who listed the six families as THEIR deal-breakers; the kit ships none
        import importlib
        self._kc = importlib.import_module("kit_config")
        self._old_filters = self._kc.INDUSTRY_USER_FILTERS
        self._kc.INDUSTRY_USER_FILTERS = list(SIX)
        self._old_pool = rs.pool_employers
        rs.pool_employers = lambda: __import__("collections").Counter()

    def tearDown(self):
        rs.pool_employers = self._old_pool
        self._kc.INDUSTRY_USER_FILTERS = self._old_filters
        set_setup_email(self._old_email)
        (il.CACHE, cs.EMPLOYER_CACHE, rs.CACHE, cs._EMPLOYER_CACHE, ss.REPO,
         ss._register_banked_identity) = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def seg_rows(self):
        try:
            return [json.loads(x) for x in open(self.seg, encoding="utf-8") if x.strip()]
        except OSError:
            return []

    def banked_text(self):
        from datetime import date
        p = os.path.join(self.tmp, "documents", "banked-candidates-%s.md" % date.today().isoformat())
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def armsco_transport(**kw):
    return FakeTransport(
        extra_search={"Armsco": [{"id": "QFAKE4", "label": "Armsco", "description": ""}]},
        extra_entities={"QFAKE4": fake_entity("Armsco", p452=("Q392933",),
                                              p856=("https://www.armsco.example.invalid/",))},
        extra_labels={"Q392933": "weapons industry"}, **kw)


class TestGateReadsTheLookupCache(Base):
    def test_domain_matched_veto_family_is_vetoed_with_the_source_named(self):
        r = il.lookup_cached("Armsco (FAKE)", domain="armsco.example.invalid", transport=armsco_transport())
        self.assertEqual(r["class"], "defense")
        verdict, detail = gate.industry_resolution("Armsco (FAKE)")
        self.assertEqual(verdict, "vetoed")
        self.assertIn("Wikidata: weapons industry", detail)
        self.assertIn("wikidata.org/wiki/QFAKE4", detail)

    def test_m1_label_only_veto_family_vetoes_and_says_label_match_only(self):
        il.lookup_cached("Armsco (FAKE)", transport=armsco_transport())      # no domain: label match
        verdict, detail = gate.industry_resolution("Armsco (FAKE)")
        self.assertEqual(verdict, "vetoed")
        self.assertIn("label match only", detail)

    def test_m1_label_only_non_veto_is_unknown_never_resolved(self):
        il.lookup_cached("Dune Capital", transport=FakeTransport())                # label-only, financial
        verdict, detail = gate.industry_resolution("Dune Capital")
        self.assertEqual(verdict, "unknown")
        self.assertIn("label match only", detail)
        self.assertEqual(self.seg_rows(), [])                               # and nothing was ingested

    def test_a_bare_unknown_name_stays_unknown(self):
        self.assertEqual(gate.industry_resolution("Nonexistent Holdings (FAKE)"), ("unknown", None))

    def test_a_stale_veto_still_vetoes(self):
        from datetime import date, timedelta
        il.lookup_cached("Armsco (FAKE)", transport=armsco_transport(), today=date.today() - timedelta(days=400))
        self.assertEqual(gate.industry_resolution("Armsco (FAKE)")[0], "vetoed")

    def test_m2_a_resolved_software_row_clears_nothing_about_customers(self):
        # A source-resolved "software" row, then card text that names police departments as customers.
        ingest_add([{"employer": "Example Widgets (FAKE)", "segment": "off-segment", "industry": "software",
                         "source": "https://www.wikidata.org/wiki/QFAKE1"}])
        cs._EMPLOYER_CACHE = None
        self.assertEqual(gate.industry_resolution("Example Widgets (FAKE)")[0], "resolved")
        text = "Our customers include police departments across the country"
        old_words = gate.INDUSTRY_VETO
        gate.INDUSTRY_VETO = [r"\bpolice\b"]          # the person's own INDUSTRY_VETO (the kit ships it empty)
        try:
            self.assertIn("police", gate.veto_hits("Example Widgets (FAKE)", text))
            self.assertEqual(gate.industry_resolution("Example Widgets (FAKE)", text)[0], "vetoed")
        finally:
            gate.INDUSTRY_VETO = old_words


class TestIngestRows(Base):
    def test_ingest_rows_is_the_validator_and_rejects_an_uncited_source(self):
        good, bad = ingest_add([{"employer": "A (FAKE)", "segment": "off-segment", "industry": "x",
                                     "source": "well-known company"}])
        self.assertEqual((len(good), len(bad)), (0, 1))
        self.assertEqual(self.seg_rows(), [])

    def test_the_kits_pool_gate_still_rejects_an_employer_outside_the_pool(self):
        # The kit's ingest keeps its own rule: an employer unknown to the people pool is rejected
        # unless add_employer is passed (the bank pass passes it).
        good, bad = rs.ingest_rows([{"employer": "A (FAKE)", "segment": "off-segment", "industry": "x",
                                     "source": "https://www.sec.gov/cgi-bin/browse-edgar?CIK=1"}])
        self.assertEqual((len(good), len(bad)), (0, 1))
        self.assertIn("pool", str(bad[0][1]))

    def test_ingest_rows_dry_run_writes_nothing(self):
        good, _ = ingest_add([{"employer": "A (FAKE)", "segment": "off-segment", "industry": "x",
                                   "source": "https://www.sec.gov/cgi-bin/browse-edgar?CIK=1"}], dry_run=True)
        self.assertEqual(len(good), 1)
        self.assertEqual(self.seg_rows(), [])


def sweep_rows(*names):
    return [{"company": n, "segment": "payments", "title": "Product Manager", "salary": "not stated",
             "location": "Remote", "url": "https://example.invalid/" + n.replace(" ", ""), "n": 1} for n in names]


class TestBankHook(Base):
    def test_bank_classifies_ingests_and_withholds_a_vetoed_company(self):
        t = FakeTransport(
            extra_search={"Armsco": [{"id": "QFAKE4", "label": "Armsco", "description": ""}]},
            extra_entities={"QFAKE4": fake_entity("Armsco", p452=("Q392933",))},
            extra_labels={"Q392933": "weapons industry"})
        keep = sweep_rows("Alder Bank", "Armsco (FAKE)", "Plover Trust", "Dune Capital")
        ss.bank(keep, [], [], "fixture.jsonl", industry_transport=t)
        banked = self.banked_text()
        # the EDGAR-resolved bank is banked and now resolves through the segment cache
        self.assertIn("Alder Bank", banked)
        self.assertEqual(gate.industry_resolution("Alder Bank")[0], "resolved")
        # the label-only veto-family company is vetoed and withheld from the pool, and said so
        self.assertEqual(gate.industry_resolution("Armsco (FAKE)")[0], "vetoed")
        names_line = [l for l in banked.splitlines() if l and not l.startswith((">", "#"))]
        self.assertFalse(any("Armsco" in l for l in names_line))
        self.assertIn("industry-vetoed", banked)
        # unknown and label-only names still bank (the kit rule: unknown ranks, marked)
        self.assertIn("Plover Trust", banked)
        self.assertIn("Dune Capital", banked)
        self.assertEqual(gate.industry_resolution("Plover Trust")[0], "unknown")
        self.assertEqual(gate.industry_resolution("Dune Capital")[0], "unknown")
        # the segment cache gained a row ONLY through the validator, and only the resolving match
        emps = [r["employer"] for r in self.seg_rows()]
        self.assertEqual(emps, ["Alder Bank"])
        self.assertTrue(all(r["source"].startswith("https://") for r in self.seg_rows()))

    def test_bank_with_the_network_down_still_banks_and_resolves_nothing(self):
        # Invariant 3, bank half.
        ss.bank(sweep_rows("Alder Bank", "Dune Capital"), [], [], "fixture.jsonl",
                industry_transport=FakeTransport(down=True))
        banked = self.banked_text()
        self.assertIn("Alder Bank", banked)
        self.assertIn("Dune Capital", banked)
        self.assertEqual(self.seg_rows(), [])
        self.assertEqual(gate.industry_resolution("Alder Bank")[0], "unknown")
        self.assertFalse(os.path.exists(self.lcache))        # an outage is not recorded as a verdict

    def test_bank_without_the_industry_option_makes_no_request(self):
        # Callers that never asked for the lookup (every existing bank test) stay offline; only
        # `--bank` from the command line turns it on. The gate-side cache read still applies.
        made = []

        def boom(url, headers):
            made.append(url)
            raise OSError("no network in this test")
        saved = il.default_transport
        il.default_transport = boom
        try:
            ss.bank(sweep_rows("Alder Bank"), [], [], "fixture.jsonl")
        finally:
            il.default_transport = saved
        self.assertEqual(made, [])
        self.assertIn("Alder Bank", self.banked_text())
        self.assertFalse(os.path.exists(self.lcache))
        self.assertEqual(self.seg_rows(), [])

    def test_second_bank_makes_zero_requests(self):
        # Invariant 5, bank half.
        t = FakeTransport()
        ss.bank(sweep_rows("Alder Bank", "Plover Trust"), [], [], "fixture.jsonl", industry_transport=t)
        n = len(t.calls)
        self.assertGreater(n, 0)
        ss.bank(sweep_rows("Alder Bank", "Plover Trust"), [], [], "fixture.jsonl", industry_transport=t)
        self.assertEqual(len(t.calls), n)

    def test_per_run_cap_of_20_lookups_and_the_next_run_moves_past_it(self):
        # S5 lowers the cap to 20. M2: absent answers are cached, so run 2 looks up names 21-25 and
        # never re-queries the first 20 (the old starvation: the same first 40 forever).
        self.assertEqual(ss.INDUSTRY_LOOKUP_CAP, 20)
        t = FakeTransport()
        names = ["Fakeco %03d (FAKE)" % i for i in range(25)]
        ss.bank(sweep_rows(*names), [], [], "fixture.jsonl", industry_transport=t)
        looked = [json.loads(l)["name"] for l in open(self.lcache, encoding="utf-8") if l.strip()]
        self.assertEqual(len(set(looked)), 20)
        self.assertEqual(sum(1 for n in names if n in self.banked_text()), 25)   # all 25 still bank
        ss.bank(sweep_rows(*names), [], [], "fixture.jsonl", industry_transport=t)
        looked2 = [json.loads(l)["name"] for l in open(self.lcache, encoding="utf-8") if l.strip()]
        self.assertEqual(len(looked2), 25)
        self.assertEqual(len(set(looked2)), 25)                                   # no name looked up twice

    def test_m3_weapons_company_with_wikidata_down_is_never_resolved_or_ingested(self):
        t = FakeTransport(wd_down=True,
                          extra_tickers=[{"cik_str": 9, "title": "ARMSCO (FAKE) INC"}],
                          extra_submissions={"0000000009": {"sic": "3812", "sicDescription": "Search, Detection, Navigation"}})
        ss.bank(sweep_rows("Armsco (FAKE)"), [], [], "fixture.jsonl", industry_transport=t)
        self.assertEqual(self.seg_rows(), [])
        self.assertEqual(gate.industry_resolution("Armsco (FAKE)")[0], "unknown")
        # Wikidata comes back: the company is looked up again (nothing pinned) and is held, not resolved.
        t2 = FakeTransport(extra_tickers=[{"cik_str": 9, "title": "ARMSCO (FAKE) INC"}],
                           extra_submissions={"0000000009": {"sic": "3812", "sicDescription": "Search, Detection, Navigation"}})
        ss.bank(sweep_rows("Armsco (FAKE)"), [], [], "fixture.jsonl", industry_transport=t2)
        self.assertGreater(len(t2.calls), 0)
        self.assertEqual(self.seg_rows(), [])
        verdict, detail = gate.industry_resolution("Armsco (FAKE)")
        self.assertEqual(verdict, "unknown")
        self.assertIn("held", detail)

    def test_142b_a_lookup_ingested_row_whose_code_becomes_hold_stops_resolving(self):
        from datetime import date
        ingest_add([{"employer": "Armsco (FAKE)", "segment": "off-segment", "industry": "Search",
                         "source": "https://www.sec.gov/cgi-bin/browse-edgar?CIK=9",
                         "note": "industry_lookup edgar sic:3812 class=off-segment"}])
        cs._EMPLOYER_CACHE = None
        row = {"name": "Armsco (FAKE)", "status": "match", "matched_by": "edgar", "code": "sic:3812",
               "industry": "Search, Detection, Navigation", "class": "off-segment",
               "source": "https://www.sec.gov/x", "checked": date.today().isoformat()}
        with open(self.lcache, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        verdict, detail = gate.industry_resolution("Armsco (FAKE)")
        self.assertEqual(verdict, "unknown")
        self.assertIn("held", detail)
        # a resolver's row for the same name still stands
        ingest_add([{"employer": "Armsco (FAKE)", "segment": "off-segment", "industry": "civil avionics",
                         "source": "https://example.invalid/resolver-page"}])
        cs._EMPLOYER_CACHE = None
        self.assertEqual(gate.industry_resolution("Armsco (FAKE)")[0], "resolved")

    def test_145_veto_words_derive_the_family_so_an_empty_filter_list_still_vetoes(self):
        # Review 145's probe: the person's INDUSTRY_VETO says "defense", INDUSTRY_USER_FILTERS is
        # empty, a domain-matched "weapons industry" company must be vetoed and never resolved.
        old_words = self._kc.INDUSTRY_VETO
        self._kc.INDUSTRY_USER_FILTERS = []
        self._kc.INDUSTRY_VETO = [r"\bdefense\b"]
        try:
            r = il.lookup_cached("Armsco (FAKE)", domain="armsco.example.invalid", transport=armsco_transport())
            self.assertEqual(r["class"], "defense")
            self.assertEqual(gate.industry_resolution("Armsco (FAKE)")[0], "vetoed")
            self.assertIsNone(il.ingest_row("Armsco (FAKE)", r))
            # and through the bank pass: withheld, nothing ingested as resolved
            import shutil as _sh
            _sh.rmtree(os.path.dirname(self.lcache)); os.makedirs(os.path.dirname(self.lcache))
            rows = sweep_rows("Armsco (FAKE)")
            rows[0]["domain"] = "armsco.example.invalid"
            ss.bank(rows, [], [], "fixture.jsonl", industry_transport=armsco_transport())
            self.assertEqual(self.seg_rows(), [])
            names_line = [l for l in self.banked_text().splitlines() if l and not l.startswith((">", "#"))]
            self.assertFalse(any("Armsco" in l for l in names_line))
        finally:
            self._kc.INDUSTRY_VETO = old_words

    def test_145b_the_kit_example_regex_defen_c_s_e_vetoes_end_to_end(self):
        old_words = self._kc.INDUSTRY_VETO
        self._kc.INDUSTRY_USER_FILTERS = []
        self._kc.INDUSTRY_VETO = [r"\bdefen[cs]e\b"]
        try:
            r = il.lookup_cached("Armsco (FAKE)", domain="armsco.example.invalid", transport=armsco_transport())
            self.assertEqual(gate.industry_resolution("Armsco (FAKE)")[0], "vetoed")
            self.assertIsNone(il.ingest_row("Armsco (FAKE)", r))
        finally:
            self._kc.INDUSTRY_VETO = old_words

    SLOW = r"((\w+)+\s?)+!"       # blows the derivation budget on the sample phrases: holds the source
    TEN_SPACES = r"\s*\s*\s*\s*\s*\s*\s*\s*\s*\s*x"   # polynomial blow-up on a run of spaces

    def test_145d_one_unusable_veto_regex_holds_everything_source_resolved(self):
        # Proxy 178: while ANY veto regex is unusable the industry source resolves NOTHING. A domain-
        # matched non-veto company reads held/unknown; the control (regex removed) resolves.
        old_words = self._kc.INDUSTRY_VETO
        self._kc.INDUSTRY_USER_FILTERS = []
        rows = sweep_rows("Alder Bank")
        rows[0]["domain"] = "alder-bank.example.invalid"
        try:
            self._kc.INDUSTRY_VETO = [self.SLOW, r"\bdefense\b"]
            il.reset_memo()
            ss.bank(rows, [], [], "fixture.jsonl", industry_transport=FakeTransport())
            self.assertEqual(self.seg_rows(), [])
            verdict, detail = gate.industry_resolution("Alder Bank")
            self.assertEqual(verdict, "unknown")
            self.assertIn("held", detail)
            # a veto that still works still vetoes
            r = il.lookup_cached("Armsco (FAKE)", domain="armsco.example.invalid", transport=armsco_transport())
            self.assertEqual(gate.industry_resolution("Armsco (FAKE)")[0], "vetoed")
            self.assertIsNone(il.ingest_row("Alder Bank", il.cached("Alder Bank")))
            # control: with the slow regex removed, the same company resolves
            self._kc.INDUSTRY_VETO = [r"\bdefense\b"]
            il.reset_memo()
            import shutil as _sh
            _sh.rmtree(os.path.dirname(self.lcache)); os.makedirs(os.path.dirname(self.lcache))
            ss.bank(rows, [], [], "fixture.jsonl", industry_transport=FakeTransport())
            self.assertEqual(gate.industry_resolution("Alder Bank")[0], "resolved")
        finally:
            self._kc.INDUSTRY_VETO = old_words
            il.reset_memo()

    def test_184_a_group_with_alternation_vetoes_a_casino_resort(self):
        old = gate.INDUSTRY_VETO
        gate.INDUSTRY_VETO = [r"(casino|gaming)+ resort"]
        il.reset_memo()
        try:
            self.assertIn("casino resort", gate.veto_hits("Plover Corp (FAKE)", "a casino resort operator"))
            self.assertEqual(gate.industry_resolution("Plover Corp (FAKE)", "a casino resort operator")[0], "vetoed")
        finally:
            gate.INDUSTRY_VETO = old
            il.reset_memo()

    def test_184_a_slow_regex_on_200_spaces_holds_that_card_in_under_4_seconds(self):
        import time
        old = gate.INDUSTRY_VETO
        gate.INDUSTRY_VETO = [self.TEN_SPACES, r"\bpolice\b"]
        il.reset_memo()
        try:
            t0 = time.time()
            verdict, detail = gate.industry_resolution("Plover Corp (FAKE)", " " * 200)
            self.assertLess(time.time() - t0, 4.0)
            self.assertEqual(verdict, "unknown")
            self.assertIn("took too long to check", detail)
            hits = gate.veto_hits("Plover Corp (FAKE)", " " * 200)
            self.assertTrue(any("took too long" in h for h in hits))       # never silently passed
            # a normal card still vetoes and a clean card is not held
            self.assertEqual(gate.industry_resolution("Plover Corp (FAKE)", "police customers")[0], "vetoed")
            self.assertEqual(gate.industry_resolution("Plover Corp (FAKE)", "makes widgets")[0], "unknown")
            self.assertNotIn("took too long", str(gate.industry_resolution("Plover Corp (FAKE)", "makes widgets")[1]))
        finally:
            gate.INDUSTRY_VETO = old
            il.reset_memo()

    def test_184_a_regex_that_will_not_compile_holds_every_card_and_is_never_dropped(self):
        old = gate.INDUSTRY_VETO
        gate.INDUSTRY_VETO = ["(unclosed", r"\bpolice\b"]
        il.reset_memo()
        try:
            for text in ("makes widgets", "police customers", ""):
                hits = gate.veto_hits("Plover Corp (FAKE)", text)
                self.assertTrue(any("(unclosed" in h and "does not compile" in h for h in hits), (text, hits))
            verdict, detail = gate.industry_resolution("Plover Corp (FAKE)", "makes widgets")
            self.assertEqual(verdict, "unknown")
            self.assertIn("(unclosed", detail)
            # the working pattern still vetoes
            self.assertEqual(gate.industry_resolution("Plover Corp (FAKE)", "police customers")[0], "vetoed")
        finally:
            gate.INDUSTRY_VETO = old
            il.reset_memo()

    def test_184_the_sweeps_title_filter_holds_on_a_timeout_and_does_not_skip(self):
        old = ss.INDUSTRY_VETO
        ss.INDUSTRY_VETO = [self.TEN_SPACES, r"\bpolice\b"]
        il.reset_memo()
        try:
            term, held = ss._industry_veto_check(" " * 200)
            self.assertIsNone(term)
            self.assertIn("took too long to check", held)
            self.assertEqual(ss._industry_veto_check("police customers"), ("police", ""))
            self.assertEqual(ss._industry_veto_check("makes widgets"), (None, ""))
        finally:
            ss.INDUSTRY_VETO = old
            il.reset_memo()

    def test_145_control_veto_words_without_defense_leave_that_company_unvetoed(self):
        old_words = self._kc.INDUSTRY_VETO
        self._kc.INDUSTRY_USER_FILTERS = []
        self._kc.INDUSTRY_VETO = [r"\bgambling\b"]
        try:
            rows = sweep_rows("Armsco (FAKE)")
            rows[0]["domain"] = "armsco.example.invalid"          # a domain match, so it can resolve
            ss.bank(rows, [], [], "fixture.jsonl", industry_transport=armsco_transport())
            self.assertEqual(gate.industry_resolution("Armsco (FAKE)")[0], "resolved")
            self.assertEqual([r["employer"] for r in self.seg_rows()], ["Armsco (FAKE)"])
        finally:
            self._kc.INDUSTRY_VETO = old_words

    def test_145_the_user_filter_list_only_adds_it_never_removes_a_derived_family(self):
        old_words = self._kc.INDUSTRY_VETO
        self._kc.INDUSTRY_VETO = [r"\bdefense\b"]
        self._kc.INDUSTRY_USER_FILTERS = ["gambling"]
        try:
            self.assertTrue(il.vetoes("defense"))       # derived from the words
            self.assertTrue(il.vetoes("gambling"))      # added by the filter list
            self.assertFalse(il.vetoes("crypto"))
        finally:
            self._kc.INDUSTRY_VETO = old_words

    def test_s2_a_source_ingested_row_is_looked_at_again_when_its_lookup_row_is_stale(self):
        from datetime import date, timedelta
        t = FakeTransport()
        il.lookup_cached("Alder Bank", transport=t, today=date.today() - timedelta(days=120))
        ingest_add([il.ingest_row("Alder Bank", il.cached("Alder Bank"))])
        n = len(t.calls)
        ss.bank(sweep_rows("Alder Bank"), [], [], "fixture.jsonl", industry_transport=t)
        self.assertGreater(len(t.calls), n)               # stale, so asked again despite the segment row

    def test_s4_with_the_gate_import_broken_a_cached_veto_still_withholds(self):
        il.lookup_cached("Armsco (FAKE)", domain="armsco.example.invalid", transport=armsco_transport())
        import importlib
        real = importlib.import_module

        def broken(name, *a, **k):
            if name == "check_screen_gate":
                raise ImportError("fixture: gate import broken")
            return real(name, *a, **k)
        importlib.import_module = broken
        try:
            ss.bank(sweep_rows("Armsco (FAKE)", "Plover Trust"), [], [], "fixture.jsonl")
        finally:
            importlib.import_module = real
        names_line = [l for l in self.banked_text().splitlines() if l and not l.startswith((">", "#"))]
        self.assertFalse(any("Armsco" in l for l in names_line))
        self.assertTrue(any("Plover Trust" in l for l in names_line))

    def test_s3_the_withheld_message_does_not_claim_a_cleared_verdict_reverses_it(self):
        import io
        from contextlib import redirect_stdout
        il.lookup_cached("Armsco (FAKE)", transport=armsco_transport())
        buf = io.StringIO()
        with redirect_stdout(buf):
            ss.bank(sweep_rows("Armsco (FAKE)"), [], [], "fixture.jsonl")
        self.assertIn("not banked", buf.getvalue())
        self.assertNotIn("CLEARED", buf.getvalue())

    def test_a_domain_on_the_row_is_used_to_disambiguate(self):
        t = FakeTransport()
        rows = sweep_rows("Elm Mutual")
        rows[0]["domain"] = "elm-mutual.example.invalid"
        ss.bank(rows, [], [], "fixture.jsonl", industry_transport=t)
        self.assertEqual([r["employer"] for r in self.seg_rows()], ["Elm Mutual"])
        self.assertEqual(gate.industry_resolution("Elm Mutual")[0], "resolved")


if __name__ == "__main__":
    unittest.main()
