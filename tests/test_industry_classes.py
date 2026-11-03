#!/usr/bin/env python3
"""#24 task 2: EX.INDUSTRY_CLASSES, the map from source codes to a class, as data.

The plan's two example QIDs were wrong on live Wikidata (Q806750 is "banking services", Q1200752 is
a Chinese county), so the shipped map uses QIDs read from the live API on 2026-10-04 and a test pins
that the two bad ones never map to a veto family.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, HERE)

import importlib.util  # noqa: E402
import industry_lookup as il  # noqa: E402
from industry_fixture import FakeTransport  # noqa: E402

# The SHIPPED defaults live in kit_config.example.py. The person's own scripts/kit_config.py is theirs
# (it may predate the map, or carry their edits), so these tests read the example, never that file.
_spec = importlib.util.spec_from_file_location("kit_config_example_for_test",
                                               os.path.join(REPO, "scripts", "kit_config.example.py"))
EX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(EX)


def ex_cfg(**over):
    cfg = {"wikidata": dict(EX.INDUSTRY_CLASSES["wikidata"]), "sic": list(EX.INDUSTRY_CLASSES["sic"]),
           "user_filters": list(EX.INDUSTRY_USER_FILTERS), "veto_words": list(EX.INDUSTRY_VETO)}
    cfg.update(over)
    return cfg

# verified against the live API 2026-10-04: weapons industry, law enforcement, gambling industry,
# cryptocurrency industry, payday loan
VERIFIED_VETO_QIDS = {"Q392933": "defense", "Q44554": "law-enforcement", "Q61054412": "gambling",
                      "Q100269062": "crypto", "Q1967434": "predatory-lending",
                      # labels read live 2026-10-04: defence industry, defense
                      # contractor, sports betting, bookmaker, daily fantasy sports, cryptocurrency exchange
                      "Q16955053": "defense", "Q1934969": "defense", "Q1506462": "gambling",
                      "Q664702": "gambling", "Q5209256": "gambling", "Q25401607": "crypto"}
# neither veto nor resolve (labels read live: mass surveillance, surveillance, online
# pharmacy, telehealth)
HOLD_QIDS = ["Q1425056", "Q334401", "Q3081320", "Q4923501"]
HOLD_SICS = [3812, 3720, 3729, 3730, 3732, 6141, 7359, 7990, 7993, 7011, 6199]


def setUpModule():
    from industry_fixture import set_setup_email
    globals()["_old_email"] = set_setup_email()


def tearDownModule():
    from industry_fixture import set_setup_email
    set_setup_email(globals()["_old_email"])


class TestShippedMap(unittest.TestCase):
    def test_config_carries_the_map_and_the_user_filter_list(self):
        self.assertIn("wikidata", EX.INDUSTRY_CLASSES)
        self.assertIn("sic", EX.INDUSTRY_CLASSES)
        self.assertEqual(EX.INDUSTRY_USER_FILTERS, [])   # ships empty: the families derive from the persons INDUSTRY_VETO words

    def test_a_qid_in_each_verifiable_veto_family_maps_to_it(self):
        for qid, fam in VERIFIED_VETO_QIDS.items():
            self.assertEqual(EX.INDUSTRY_CLASSES["wikidata"].get(qid), fam, qid)
            self.assertIn(fam, il.FAMILY_CLASSES)

    def test_s1_hold_qids_and_sics_map_to_hold_which_neither_vetoes_nor_resolves(self):
        cfg = ex_cfg()
        for q in HOLD_QIDS:
            self.assertEqual(EX.INDUSTRY_CLASSES["wikidata"].get(q), "hold", q)
        for s in HOLD_SICS:
            self.assertEqual(il._class_for_sic(str(s), cfg), "hold", s)
        self.assertFalse(il.vetoes("hold", cfg))
        self.assertIsNone(il.ingest_row("X", {"matched_by": "edgar", "class": "hold", "industry": "x",
                                              "source": "https://www.sec.gov/x"}))

    def test_a_veto_beats_hold_beats_a_resolving_class(self):
        cfg = ex_cfg()
        self.assertEqual(il._class_for_wikidata(["Q837171", "Q334401"], [], cfg), "hold")
        # a person who listed "defense" as THEIR deal-breaker: it beats hold
        mine = dict(cfg, user_filters=["defense"])
        self.assertEqual(il._class_for_wikidata(["Q837171", "Q334401", "Q16955053"], [], mine), "defense")

    def test_the_kit_ships_no_vetoing_class_so_a_family_only_vetoes_when_the_person_lists_it(self):
        # The family names are not the kit's values: another person may work in defense. The family
        # names are only labels until the person puts them in INDUSTRY_USER_FILTERS.
        cfg = ex_cfg()
        for fam in il.FAMILY_CLASSES:
            self.assertFalse(il.vetoes(fam, cfg), fam)
            self.assertTrue(il.vetoes(fam, dict(cfg, user_filters=[fam])), fam)
        self.assertTrue(il.vetoes("veto-term", cfg))      # a label that trips the person's own INDUSTRY_VETO

    def test_the_plans_two_wrong_qids_never_map_to_a_veto_family(self):
        for bad in ("Q806750", "Q1200752"):
            self.assertNotIn(EX.INDUSTRY_CLASSES["wikidata"].get(bad), il.FAMILY_CLASSES, bad)

    def test_every_mapped_class_is_a_known_class(self):
        known = set(il.FAMILY_CLASSES) | set(il.segments()) | {"off-segment", "financial-services", "hold"}
        classes = set(EX.INDUSTRY_CLASSES["wikidata"].values()) | \
            {c for _, _, c in EX.INDUSTRY_CLASSES["sic"]}
        self.assertEqual(classes - known, set())

    def test_sic_6021_to_6099_is_financial_services_and_9711_is_defense(self):
        cfg = ex_cfg()
        for sic in ("6021", "6022", "6099"):
            self.assertEqual(il._class_for_sic(sic, cfg), "financial-services", sic)
        self.assertEqual(il._class_for_sic("9711", cfg), "defense")
        self.assertEqual(il._class_for_sic("7372", cfg), "off-segment")     # unmapped, label kept
        self.assertEqual(il._class_for_sic("", cfg), "off-segment")

    def test_financial_services_vetoes_only_when_the_user_sets_that_filter(self):
        # Out of the box nothing vetoes: financial services resolves as off-segment.
        self.assertFalse(il.vetoes("financial-services", ex_cfg()))
        mine = ex_cfg(user_filters=["financial-services"])
        self.assertTrue(il.vetoes("financial-services", mine))
        il.reset_memo()
        r = il.lookup("Alder Bank", transport=FakeTransport(), cfg=mine)
        self.assertEqual(r["class"], "financial-services")
        self.assertTrue(il.vetoes(r["class"], mine))

    def test_shipped_map_classifies_a_fake_bank_by_edgar(self):
        il.reset_memo()
        r = il.lookup("Birch Financial", transport=FakeTransport(), cfg=ex_cfg())
        self.assertEqual((r["matched_by"], r["class"]), ("edgar", "financial-services"))
        self.assertFalse(il.vetoes(r["class"], ex_cfg()))

    def _fams(self, *words):
        return il.derived_families(ex_cfg(veto_words=list(words), user_filters=[]))

    def test_145_each_family_is_derived_from_the_persons_veto_words(self):
        # Proxy 166: a family vetoes when the person's veto words ask for it; the filter list only ADDS.
        probes = {"defense": r"\bdefense\b", "law-enforcement": r"\bpolice\b", "gambling": r"\bsports bett",
                  "crypto": r"\bcrypto\b", "predatory-lending": r"payday (loan|lend)",
                  "dtc-rx-telehealth": r"\bketamine\b"}
        for fam, word in probes.items():
            mine = ex_cfg(veto_words=[word], user_filters=[])
            self.assertTrue(il.vetoes(fam, mine), (fam, word))
            for other in il.FAMILY_CLASSES:
                if other != fam:
                    self.assertFalse(il.vetoes(other, mine), (fam, word, other))
        self.assertFalse(any(il.vetoes(f, ex_cfg(veto_words=[], user_filters=[])) for f in il.FAMILY_CLASSES))

    def test_145b_the_reviewers_five_regex_shapes_each_derive_their_family(self):
        # Proxy 171: the person's regexes are COMPILED and run against sample phrases, so a pattern
        # that never spells the family word literally still derives it.
        shapes = {r"\bdefen[cs]e\b": "defense", r"sports? bett": "gambling", r"gambl(e|ing)": "gambling",
                  r"pay ?day": "predatory-lending", r"polic(e|ing)": "law-enforcement"}
        for rx, fam in shapes.items():
            self.assertIn(fam, self._fams(rx), rx)

    def test_145b_the_kit_example_sample_derives_every_family(self):
        sample = [r"\bdefen[cs]e\b", r"\bpolice\b", r"\bcasino\b", r"\bcrypto\b", r"payday (loan|lend)",
                  r"\bketamine\b"]
        self.assertEqual(self._fams(*sample), set(il.FAMILY_CLASSES))

    def test_145b_substring_lookalikes_derive_nothing(self):
        # "defined" holds "defi", "nftables" holds "nft", "dodge" holds "dod", "pharmaceutical" holds
        # "pharmac": none of them is a deal-breaker word, so no family is derived.
        for rx in (r"defined contribution", r"nftables", r"dodge", r"pharmaceutical", r"\bundefined\b"):
            self.assertEqual(self._fams(rx), set(), rx)

    def test_145b_each_family_phrase_set_is_pinned_by_a_single_word_pattern(self):
        # A mutation that drops "military" or "weapon" from the defense phrases must turn this red.
        for rx in (r"\bmilitary\b", r"\bweapons?\b", r"\bwarfighter"):
            self.assertIn("defense", self._fams(rx), rx)
        pairs = ((r"\bsportsbook\b", "gambling"), (r"\bweb3\b", "crypto"), (r"\bnft\b", "crypto"),
                 (r"\bdefi\b", "crypto"), (r"\bsubprime\b", "predatory-lending"),
                 (r"lease[- ]to[- ]own", "predatory-lending"), (r"merchant cash advance", "predatory-lending"),
                 (r"law[- ]enforcement", "law-enforcement"),
                 (r"direct[- ]to[- ]consumer (rx|pharmac|prescri|telehealth)", "dtc-rx-telehealth"),
                 (r"telehealth[^.]{0,40}\b(prescri|\brx\b|pharmac)", "dtc-rx-telehealth"))
        for rx, fam in pairs:
            self.assertIn(fam, self._fams(rx), rx)

    def test_145b_a_regex_that_will_not_compile_derives_nothing_and_is_reported(self):
        cfg = ex_cfg(veto_words=["(unclosed", r"\bcasino\b"], user_filters=[])
        self.assertEqual(il.derived_families(cfg), {"gambling"})
        self.assertEqual(il.bad_patterns(cfg), ["(unclosed"])

    def test_173_missing_words_each_derive_their_family(self):
        # Proxy 173: words pre-#24 name matching caught, which the first phrase set missed.
        pairs = ((r"\barms\b", "defense"), (r"\bmunitions?\b", "defense"), (r"\bbitcoin\b", "crypto"),
                 (r"\bblockchain\b", "crypto"), (r"\blottery\b", "gambling"), (r"\bpoker\b", "gambling"),
                 (r"pawn ?shop", "predatory-lending"), (r"\bsurveillance\b", "law-enforcement"))
        for rx, fam in pairs:
            self.assertIn(fam, self._fams(rx), rx)

    def test_173_filler_words_derive_nothing(self):
        # Each sample phrase's only distinctive word is its family word, so a pattern for a filler
        # word (agency, contractor, department, platform, online, industry) derives no family.
        for rx in (r"\bagency\b", r"\bcontractor\b", r"\bdepartment\b", r"\bplatform\b", r"\bonline\b",
                   r"\bindustry\b", r"\bmanufacturer\b", r"\bexchange\b", r"\bmarketplace\b"):
            self.assertEqual(self._fams(rx), set(), rx)

    def test_173_a_catastrophic_regex_is_cut_off_derives_nothing_and_is_reported(self):
        import time
        il.reset_memo()
        bad = r"((\w+)+\s?)+!"
        cfg = ex_cfg(veto_words=[bad, r"\bcasino\b"], user_filters=[])
        t0 = time.time()
        fams = il.derived_families(cfg)
        self.assertLess(time.time() - t0, 3.0)
        self.assertEqual(fams, {"gambling"})
        self.assertIn(bad, il.slow_patterns(cfg))

    def test_173_derivation_is_memoized_per_regex_set(self):
        il.reset_memo()
        cfg = ex_cfg(veto_words=[r"\bcasino\b"], user_filters=[])
        calls = []
        real = il._analyze_uncached
        il._analyze_uncached = lambda words: (calls.append(1), real(words))[1]
        try:
            il.derived_families(cfg)
            il.derived_families(cfg)
            il.vetoes("gambling", cfg)
            self.assertEqual(len(calls), 1)
            il.derived_families(ex_cfg(veto_words=[r"\bpoker\b"], user_filters=[]))
            self.assertEqual(len(calls), 2)                 # a different regex set is analyzed afresh
        finally:
            il._analyze_uncached = real

    def test_184_no_static_classifier_a_group_with_alternation_is_usable(self):
        # Proxy 184: the static catastrophic / nested-quantifier / alternation classifier is gone. A
        # perfectly good pattern like (casino|gaming)+ resort is usable; only a regex that will not
        # compile, or that runs past the time budget, holds the source.
        il.reset_memo()
        cfg = ex_cfg(veto_words=[r"(casino|gaming)+ resort", r"\bcasino\b"], user_filters=[])
        self.assertEqual(il.unusable_patterns(cfg), [])
        self.assertFalse(hasattr(il, "nested_quantifier_patterns"))
        self.assertFalse(hasattr(il, "usable_words"))

    def test_184_unusable_is_a_pattern_that_will_not_compile_or_blows_the_derivation_budget(self):
        il.reset_memo()
        cfg = ex_cfg(veto_words=["(unclosed", r"((\w+)+\s?)+!", r"(casino|gaming)+ resort", r"\bcasino\b"], user_filters=[])
        self.assertEqual(set(il.unusable_patterns(cfg)), {"(unclosed", r"((\w+)+\s?)+!"})

    def test_184_check_text_compiles_first_and_names_a_pattern_that_will_not(self):
        hits, held = il.check_text([r"\bcasino\b", "(unclosed"], "a casino")
        self.assertEqual(hits, ["casino"])           # the working pattern still vetoes
        self.assertIn("(unclosed", held)
        self.assertIn("does not compile", held)

    def test_184_check_text_time_boxes_one_call_and_holds_on_a_timeout(self):
        import time
        slow = r"\s*\s*\s*\s*\s*\s*\s*\s*\s*\s*x"
        t0 = time.time()
        hits, held = il.check_text([r"\bcasino\b", slow], " " * 200)
        self.assertLess(time.time() - t0, 4.0)
        self.assertEqual(hits, [])
        self.assertIn("took too long to check", held)
        self.assertEqual(il.check_text([r"\bcasino\b", slow], "a casino"), (["casino"], ""))

    def test_184_the_time_box_holds_off_the_main_thread_too(self):
        # serve.py's request threads cannot use SIGALRM; the call then runs in a child process with a
        # hard kill, and still holds.
        import threading
        import time
        slow = r"\s*\s*\s*\s*\s*\s*\s*\s*\s*\s*x"
        out = {}

        def work():
            t0 = time.time()
            out["res"] = il.check_text([slow], " " * 200)
            out["fine"] = il.check_text([r"\bcasino\b"], "a casino")
            out["secs"] = time.time() - t0
        th = threading.Thread(target=work)
        th.start()
        th.join(40)
        self.assertFalse(th.is_alive())
        self.assertEqual(out["res"][0], [])
        self.assertIn("took too long to check", out["res"][1])
        self.assertEqual(out["fine"], (["casino"], ""))
        self.assertLess(out["secs"], 10.0)

    def test_145d_analysis_off_the_main_thread_does_not_rely_on_sigalrm(self):
        # The derivation likewise runs in a child process off the main thread, and still holds the source.
        import threading
        import time
        il.reset_memo()
        cfg = ex_cfg(veto_words=[r"((\w+)+\s?)+!", r"\bcasino\b"], user_filters=[])
        out = {}

        def work():
            t0 = time.time()
            out["fams"] = il.derived_families(cfg)
            out["unusable"] = il.unusable_patterns(cfg)
            out["secs"] = time.time() - t0
        th = threading.Thread(target=work)
        th.start()
        th.join(30)
        self.assertFalse(th.is_alive())
        self.assertEqual(out["fams"], {"gambling"})
        self.assertEqual(out["unusable"], [r"((\w+)+\s?)+!"])
        self.assertLess(out["secs"], 8.0)


if __name__ == "__main__":
    unittest.main()
