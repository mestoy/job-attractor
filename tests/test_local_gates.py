#!/usr/bin/env python3
"""Slice 3a/3b: local_gates.py carries a `counts` boolean on every gate result, and the blocked
gate also rides the person's own INDUSTRY_VETO/VETO_EMPLOYERS words (plan-app-onboarding-
parity-2026-10-07.md, §0b B1, §0c C1/C2). Red-first, each test named for the invariant it pins.
Run: python3 -m unittest tests.test_local_gates
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))
import local_gates as lg   # noqa: E402


def _clean(_company):
    return ("CLEAN", "")


def _blocked(_company):
    return ("BLOCKED", "declined: culture, layoffs")


def _raises(_company):
    raise RuntimeError("boom")


def _no_hits(_company):
    return {"strong": [], "weak": []}


class GateBlockedCountsTests(unittest.TestCase):
    """3a: an empty blocked list AND an untouched INDUSTRY_VETO give "not asked yet", counts
    False, never pass -- whatever the underlying check would otherwise have answered."""

    def test_both_empty_refuses_a_clean_verdict_as_not_asked_yet(self):
        e = lg.gate_blocked("Zzyzx Sprockets", _clean, "2026-10-07T00:00:00Z", counts=False)
        self.assertEqual(e["state"], "unresolved")
        self.assertFalse(e["counts"])
        self.assertEqual(e["why"], lg.NOT_ASKED_YET)

    def test_a_blocked_hit_counts_true_and_fails_once_counts_is_true(self):
        e = lg.gate_blocked("Zzyzx Sprockets", _blocked, "2026-10-07T00:00:00Z", counts=True)
        self.assertEqual(e["state"], "fail")
        self.assertTrue(e["counts"])
        self.assertIn("blocked list", e["why"])

    def test_a_clean_company_counts_true_passes_when_counts_is_true(self):
        e = lg.gate_blocked("Zzyzx Sprockets", _clean, "2026-10-07T00:00:00Z", counts=True)
        self.assertEqual(e["state"], "pass")
        self.assertTrue(e["counts"])

    def test_an_industry_veto_word_fails_a_clean_company_by_name(self):
        """3b: the blocked gate also matches INDUSTRY_VETO words against the company's own
        name -- no eleventh row, counts True because the veto list itself has content."""
        e = lg.gate_blocked("Zzquark Casino Holdings", _clean, "2026-10-07T00:00:00Z", counts=True,
                            industry_patterns=[r"\bcasino\b"])
        self.assertEqual(e["state"], "fail")
        self.assertTrue(e["counts"])
        self.assertIn("casino", e["why"])

    def test_a_veto_employers_entry_fails_a_clean_company_by_name(self):
        e = lg.gate_blocked("Zzquark Holdings", _clean, "2026-10-07T00:00:00Z", counts=True,
                            employer_patterns=[r"zzquark holdings"])
        self.assertEqual(e["state"], "fail")
        self.assertTrue(e["counts"])

    def test_a_failed_check_never_counts_even_when_counts_was_true(self):
        e = lg.gate_blocked("Zzyzx Sprockets", _raises, "2026-10-07T00:00:00Z", counts=True)
        self.assertEqual(e["state"], "unresolved")
        self.assertFalse(e["counts"])


class GateDedupCountsTests(unittest.TestCase):
    """3a: an empty send log and no contact store give "not asked yet", counts False."""

    def test_counts_false_refuses_a_clean_verdict_as_not_asked_yet(self):
        e = lg.gate_dedup("zzyzx-sprockets", "Zzyzx Sprockets", ["zzyzx-sprockets"], _no_hits,
                          "2026-10-07T00:00:00Z", counts=False)
        self.assertEqual(e["state"], "unresolved")
        self.assertFalse(e["counts"])
        self.assertEqual(e["why"], lg.NOT_ASKED_YET)

    def test_counts_true_passes_on_no_hits(self):
        e = lg.gate_dedup("zzyzx-sprockets", "Zzyzx Sprockets", ["zzyzx-sprockets"], _no_hits,
                          "2026-10-07T00:00:00Z", counts=True)
        self.assertEqual(e["state"], "pass")
        self.assertTrue(e["counts"])

    def test_a_failed_check_never_counts_even_when_counts_was_true(self):
        e = lg.gate_dedup("zzyzx-sprockets", "Zzyzx Sprockets", ["zzyzx-sprockets"], _raises,
                          "2026-10-07T00:00:00Z", counts=True)
        self.assertEqual(e["state"], "unresolved")
        self.assertFalse(e["counts"])


class OverlayGatesCountsTests(unittest.TestCase):
    def test_counts_rides_along_when_a_local_result_fills_an_unresolved_gate(self):
        gates = [{"key": "blocked", "state": "unresolved", "why": "none", "name": "Blocked list"}]
        entry = {"blocked": lg._entry("fail", "on the blocked list: Zzyzx", "2026-10-07T00:00:00Z", True)}
        out = lg.overlay_gates(gates, entry)
        self.assertEqual(out[0]["state"], "fail")
        self.assertTrue(out[0]["counts"])

    def test_a_gate_the_card_already_read_is_untouched_by_a_pass_or_unresolved_local_result(self):
        gates = [{"key": "blocked", "state": "good", "why": "cleared on the card", "name": "Blocked list"}]
        entry = {"blocked": lg._entry("pass", "not on the blocked list", "2026-10-07T00:00:00Z", True)}
        out = lg.overlay_gates(gates, entry)
        self.assertEqual(out[0]["state"], "good")
        self.assertEqual(out[0]["why"], "cleared on the card")


class DefaultCountsSourceTests(unittest.TestCase):
    """The real (non-injected) readers run() falls back to when no override is given."""

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp(prefix="lg-counts-")
        os.makedirs(os.path.join(self.d, "documents"), exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)
        sys.modules.pop("kit_config", None)
        if self.d in sys.path:
            sys.path.remove(self.d)

    def test_blocked_list_nonempty_is_false_on_a_missing_file(self):
        self.assertFalse(lg.blocked_list_nonempty(self.d))

    def test_blocked_list_nonempty_is_true_once_a_real_bullet_is_written(self):
        with open(os.path.join(self.d, "documents", "blocked-employers-list.md"), "w", encoding="utf-8") as f:
            f.write("# Blocked employers\n\n- Zzquark Holdings (declined, culture)\n")
        self.assertTrue(lg.blocked_list_nonempty(self.d))

    def test_industry_veto_patterns_is_empty_with_no_kit_config(self):
        ind, emp = lg.industry_veto_patterns(self.d)
        self.assertEqual(ind, [])
        self.assertEqual(emp, [])

    def test_industry_veto_patterns_reads_a_real_kit_config(self):
        with open(os.path.join(self.d, "kit_config.py"), "w", encoding="utf-8") as f:
            f.write("INDUSTRY_VETO = [r'\\bcasino\\b']\nVETO_EMPLOYERS = [r'zzquark holdings']\n")
        ind, emp = lg.industry_veto_patterns(self.d)
        self.assertEqual(ind, [r"\bcasino\b"])
        self.assertEqual(emp, [r"zzquark holdings"])

    def test_dedup_sources_nonempty_is_false_with_nothing_on_disk(self):
        self.assertFalse(lg.dedup_sources_nonempty(self.d))

    def test_dedup_sources_nonempty_is_true_once_the_send_log_has_a_row(self):
        with open(os.path.join(self.d, "documents", "send-log.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"company": "Zzquark Holdings", "status": "sent"}) + "\n")
        self.assertTrue(lg.dedup_sources_nonempty(self.d))

    def test_dedup_sources_nonempty_is_false_when_warm_network_only_names_someone(self):
        """BUG-601: this used to assert True, the bug itself. A warm-network.md says who the person knows, not whom they have written to."""
        with open(os.path.join(self.d, "documents", "warm-network.md"), "w", encoding="utf-8") as f:
            f.write("# Warm network\n\n| Name | Company |\n|---|---|\n| Dax Holloway | Zzquark Holdings |\n")
        self.assertFalse(lg.dedup_sources_nonempty(self.d))

    def test_dedup_sources_nonempty_is_false_on_a_header_only_warm_network_file(self):
        """Review 187 SHOULD(a): a table with only its header/separator row, or the generated
        preamble line, must never count as a real contact."""
        with open(os.path.join(self.d, "documents", "warm-network.md"), "w", encoding="utf-8") as f:
            f.write("> Generated by scripts/build_warm_network.py\n\n| Name | Company |\n|---|---|\n")
        self.assertFalse(lg.dedup_sources_nonempty(self.d))

    def test_blocked_list_nonempty_is_false_on_the_shipped_starter_list(self):
        """Review 187 MUST2: install.sh seeds partner-docs/blocked-employers-list.md into every
        fresh install. Its own "How to use" instructions and bracketed example row must never
        read as a real company."""
        starter = (
            "# Blocked / Declined Employers\n\n"
            "## How to use\n"
            "- When you decline a company, add a line here with the reason.\n\n"
            "## Your list\n"
            "| Company | Date | Reason |\n|---|---|---|\n"
            "| _[Example Co]_ | _2026-01-01_ | _always-on culture_ |\n"
        )
        with open(os.path.join(self.d, "documents", "blocked-employers-list.md"), "w", encoding="utf-8") as f:
            f.write(starter)
        self.assertFalse(lg.blocked_list_nonempty(self.d))

    def test_dedup_sources_nonempty_is_false_when_contact_closeness_only_has_an_entry(self):
        """BUG-601: a stated closeness is a relationship, not a contact attempt; it used to count as dedup history."""
        with open(os.path.join(self.d, "documents", "contact-closeness.json"), "w", encoding="utf-8") as f:
            json.dump({"dax-holloway": {"closeness": "strong"}}, f)
        self.assertFalse(lg.dedup_sources_nonempty(self.d))


def _write_card(repo, slug, company):
    path = os.path.join(repo, "documents", "state", "%s-card-2026-10-07.md" % slug)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# %s · applied-ai · panel 80/80/80\n\nNothing else matters for this fixture.\n" % company)
    return path


class RunEndToEndCountsTests(unittest.TestCase):
    """3b(b): Setup pressed straight through with every default leaves zero counting gates."""

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp(prefix="lg-run-")
        os.makedirs(os.path.join(self.d, "documents", "state"), exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)
        sys.modules.pop("kit_config", None)
        if self.d in sys.path:
            sys.path.remove(self.d)

    def test_three_named_cards_with_every_default_count_on_nothing(self):
        for slug, company in (("zzyzx-sprockets", "Zzyzx Sprockets"),
                              ("zzquark-gears", "Zzquark Gears"),
                              ("quorbex-labs", "Quorbex Labs")):
            _write_card(self.d, slug, company)
        r = lg.run(self.d, blocked_check=_clean, prior_check=_no_hits, today="2026-10-07", dry_run=True)
        self.assertEqual(r["cards"], 3)
        # dry_run=True computes but writes nothing; re-run for real to inspect per-card counts
        # in the written file.
        lg.run(self.d, blocked_check=_clean, prior_check=_no_hits, today="2026-10-07")
        with open(os.path.join(self.d, "documents", "state", "local-gates.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)
        for entry in data.values():
            self.assertFalse(entry["blocked"]["counts"], entry["blocked"])
            self.assertFalse(entry["dedup"]["counts"], entry["dedup"])
            self.assertEqual(entry["blocked"]["state"], "unresolved")
            self.assertEqual(entry["dedup"]["state"], "unresolved")

    def test_a_populated_blocked_list_makes_the_blocked_gate_count(self):
        _write_card(self.d, "zzquark-holdings", "Zzquark Holdings")
        with open(os.path.join(self.d, "documents", "blocked-employers-list.md"), "w", encoding="utf-8") as f:
            f.write("# Blocked employers\n\n- Zzquark Holdings (declined, culture)\n")
        lg.run(self.d, blocked_check=_blocked, prior_check=_no_hits, today="2026-10-07")
        with open(os.path.join(self.d, "documents", "state", "local-gates.json"), encoding="utf-8") as f:
            data = json.load(f)
        entry = data["zzquark-holdings"]
        self.assertTrue(entry["blocked"]["counts"])
        self.assertEqual(entry["blocked"]["state"], "fail")
        self.assertFalse(entry["dedup"]["counts"])  # the send log is still empty


if __name__ == "__main__":
    unittest.main()
