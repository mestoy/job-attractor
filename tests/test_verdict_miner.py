#!/usr/bin/env python3
"""Tests for scripts/verdict_miner.py — Phase 3 of the self-refining ranker.

Built 2026-08-14 (designed and built in one pass). The miner is a PURE RECOMPUTE: it reads the
target-impression store + the decision ledger + the send log and DERIVES, per surfaced target, one of
three labels — accepted / rejected-explicit / passed-over. Those become the training data the
experiment registry validates VALUE features against (the EV objective: who connects the user to their
next opportunity toward an offer — acceptance, not replies).

WHAT THESE PIN:
  1. Each label's derivation, and the PRECEDENCE when signals conflict (latest-dated wins).
  2. The date-guard leakage case: a send BEFORE the first impression is never acceptance (mirrors
     warm_path_lift's strictly-before rule).
  3. The pair-picker ledger trap avoided: a pair-marker row's ledger ruling is never the rejection.
  4. The negation vocabulary is IMPORTED from record_decision, never re-implemented.
  5. The registry integration: verdict_cells feed classify() as [accepted, total] cells.
  6. Genericity over injected non-owner impressions; fail-open on malformed rows.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import LIVE_REPO  # noqa: E402

sys.path.insert(0, os.path.join(LIVE_REPO, "scripts"))
import verdict_miner as vm  # noqa: E402
import record_decision as rd  # noqa: E402


def _imp(session, question, options, chosen, trigger="target-shaped-option",
         ts="2026-08-10T12:00:00+00:00", key=None):
    """A minimal impression row. options: list of (label, target_dict_or_None). chosen: dict."""
    opt_rows = [{"idx": i, "label": lab, "target": tgt, "is_default": i == 1}
                for i, (lab, tgt) in enumerate(options, 1)]
    return {"kind": "target-impression", "v": 1, "ts": ts, "session": session,
            "question": question, "header": "H", "trigger": trigger, "options": opt_rows,
            "chosen": chosen,
            "surfaced_top": (opt_rows[0]["target"] and
                             {"name": opt_rows[0]["target"]["name"],
                              "company": opt_rows[0]["target"].get("company")}) or None,
            "ledger_key": {"session": session, "question": question, "answer": chosen.get("answer", "")},
            "impression_key": key or f"{session}|{question}|{chosen.get('answer','')}"}


def _tgt(name, company=None, rung="8"):
    return {"name": name, "company": company, "rung": rung}


def _write(rows):
    fd, p = tempfile.mkstemp(suffix=".jsonl", prefix="imp-")
    os.close(fd)
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
    return p


def _chosen(answer, idx=None, off_list=False, resolved=None):
    return {"answer": answer, "resolved": resolved if resolved is not None else answer,
            "idx": idx, "off_list": off_list}


class VerdictLabelTests(unittest.TestCase):
    def _mine(self, rows, send_rows=None):
        p = _write(rows)
        try:
            return vm.mine_verdicts(impressions_path=p, ledger_path="/nonexistent",
                                    send_rows=send_rows or [])
        finally:
            os.unlink(p)

    def test_accepted_when_chosen_idx_points_at_the_target(self):
        row = _imp("s1", "who first?",
                   [("Priya Patel · CTO @ Northwind · rung 8", _tgt("Priya Patel", "Northwind")),
                    ("Refill", None)],
                   _chosen("Priya Patel · CTO @ Northwind · rung 8", idx=1))
        v = self._mine([row])["priyapatel"]
        self.assertEqual(v["label"], "accepted")
        self.assertEqual(v["basis"], "chosen")

    def test_accepted_when_contacted_after_the_impression(self):
        row = _imp("s1", "who?",
                   [("Priya Patel · CTO @ Northwind · rung 8", _tgt("Priya Patel", "Northwind")),
                    ("Refill", None)],
                   _chosen("Refill", idx=2))
        sends = [{"to_name": "Priya Patel", "status": "sent", "date": "2026-08-12", "replied": False}]
        v = self._mine([row], send_rows=sends)["priyapatel"]
        self.assertEqual(v["label"], "accepted")
        self.assertEqual(v["basis"], "sent-after")

    def test_passed_over_when_surfaced_and_not_chosen(self):
        row = _imp("s1", "who?",
                   [("Priya Patel · CTO @ Northwind · rung 8", _tgt("Priya Patel", "Northwind")),
                    ("Refill", None)],
                   _chosen("Refill", idx=2))
        v = self._mine([row])["priyapatel"]
        self.assertEqual(v["label"], "passed-over")
        self.assertEqual(v["counts"]["passed_over"], 1)

    def test_rejected_explicit_from_a_negating_answer(self):
        row = _imp("s1", "who?",
                   [("Priya Patel · CTO @ Northwind · rung 8", _tgt("Priya Patel", "Northwind")),
                    ("Refill", None)],
                   _chosen("not Priya, she moved on", off_list=True))
        v = self._mine([row])["priyapatel"]
        self.assertEqual(v["label"], "rejected-explicit")
        self.assertEqual(v["basis"], "negation")

    def test_pair_picker_ledger_ruling_is_never_the_rejection_source(self):
        # A pair-marker row whose answer is affirmative for ANOTHER option; the surfaced target must
        # be passed-over, never rejected — even though a joined ledger row might classify OTHER/SKIP.
        row = _imp("s1", "NEXT-STEP · what now?",
                   [("Start the next loop", _tgt("Priya Patel", "Northwind")),
                    ("Phase 2", None)],
                   _chosen("Phase 2", idx=2), trigger="pair-marker")
        v = self._mine([row])["priyapatel"]
        self.assertEqual(v["label"], "passed-over")

    def test_pre_impression_send_never_counts_as_acceptance(self):
        row = _imp("s1", "who?",
                   [("Priya Patel · CTO @ Northwind · rung 8", _tgt("Priya Patel", "Northwind")),
                    ("Refill", None)],
                   _chosen("Refill", idx=2), ts="2026-08-10T12:00:00+00:00")
        before = [{"to_name": "Priya Patel", "status": "sent", "date": "2026-08-01", "replied": False}]
        v = self._mine([row], send_rows=before)["priyapatel"]
        self.assertEqual(v["label"], "passed-over", "a send BEFORE the impression is not acceptance")
        self.assertEqual(v["evidence"]["pre_impression_sends"], 1)
        # same-day counts as after (send rows carry date, not time)
        sameday = [{"to_name": "Priya Patel", "status": "sent", "date": "2026-08-10", "replied": False}]
        v2 = self._mine([row], send_rows=sameday)["priyapatel"]
        self.assertEqual(v2["label"], "accepted")

    def test_precedence_latest_signal_wins_on_conflict(self):
        # rejected on the 10th, contacted on the 12th → behavior supersedes words → accepted.
        row = _imp("s1", "who?",
                   [("Priya Patel · CTO @ Northwind · rung 8", _tgt("Priya Patel", "Northwind")),
                    ("Refill", None)],
                   _chosen("not Priya", off_list=True), ts="2026-08-10T12:00:00+00:00")
        later = [{"to_name": "Priya Patel", "status": "sent", "date": "2026-08-12", "replied": False}]
        self.assertEqual(self._mine([row], send_rows=later)["priyapatel"]["label"], "accepted")

    def test_bounced_send_is_not_a_contact(self):
        row = _imp("s1", "who?",
                   [("Priya Patel · CTO @ Northwind · rung 8", _tgt("Priya Patel", "Northwind")),
                    ("Refill", None)],
                   _chosen("Refill", idx=2))
        bounced = [{"to_name": "Priya Patel", "status": "bounced", "date": "2026-08-12"}]
        self.assertEqual(self._mine([row], send_rows=bounced)["priyapatel"]["label"], "passed-over")

    def test_malformed_and_duplicate_rows_fail_open(self):
        good = _imp("s1", "who?",
                    [("Priya Patel · CTO @ Northwind · rung 8", _tgt("Priya Patel", "Northwind")),
                     ("Refill", None)],
                    _chosen("Refill", idx=2), key="K1")
        rows = ["not json {{{", json.dumps(good), json.dumps(good),  # duplicate impression_key
                json.dumps({"kind": "target-impression", "options": "not-a-list"})]
        out = self._mine(rows)
        self.assertIn("priyapatel", out)
        self.assertEqual(out["priyapatel"]["counts"]["surfaced"], 1, "the duplicate is deduped")


class ContractTests(unittest.TestCase):
    def test_negation_helpers_are_imported_not_reimplemented(self):
        self.assertIs(vm.NEGATION, rd.NEGATION)

    def test_verdict_cells_order_is_accepted_over_total(self):
        # 2 accepted of 3 flagged, 0 accepted of 1 unflagged. success = accepted; the denominator is
        # every verdict (passed-over and rejected sit in it).
        verdicts = {
            "a": {"key": "a", "name": "A", "company": "Northwind", "label": "accepted"},
            "b": {"key": "b", "name": "B", "company": "Northwind", "label": "accepted"},
            "c": {"key": "c", "name": "C", "company": "Northwind", "label": "passed-over"},
            "d": {"key": "d", "name": "D", "company": "Other", "label": "accepted"},
        }
        with_cell, without_cell, _un = vm.verdict_cells(r"Northwind", population="company",
                                                        verdicts=verdicts)
        self.assertEqual(with_cell, [2, 3], "[accepted, total] for the Northwind group")
        self.assertEqual(without_cell, [1, 1], "the Other-company group")

    def test_genericity_over_injected_impressions(self):
        row = _imp("sX", "who?",
                   [("Devon Msomi · VP @ Lumen Labs · rung 8", _tgt("Devon Msomi", "Lumen Labs")),
                    ("Refill", None)],
                   _chosen("Devon Msomi · VP @ Lumen Labs · rung 8", idx=1))
        p = _write([row])
        try:
            out = vm.mine_verdicts(impressions_path=p, ledger_path="/nonexistent", send_rows=[])
        finally:
            os.unlink(p)
        self.assertEqual(out["devonmsomi"]["label"], "accepted")
        self.assertEqual(out["devonmsomi"]["company"], "Lumen Labs")


class RegistryIntegrationTests(unittest.TestCase):
    def test_verdict_objective_join_runs_through_the_registry(self):
        import rank_experiments as rx
        # inject canned cells so the registry join is exercised without live stores
        orig = vm.verdict_cells
        vm.verdict_cells = lambda *a, **k: ([2, 9], [63, 240], 0)   # underpowered by n
        fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="exp-")
        os.close(fd); os.unlink(path)
        try:
            with redirect_stdout(io.StringIO()):
                rx.propose("targets at board companies get accepted more", "board-company",
                           join="verdict_objective", population="board", objective="value", path=path)
                ev = rx.run_experiment("EXP-000", path=path)
        finally:
            vm.verdict_cells = orig
            if os.path.exists(path):
                os.unlink(path)
        self.assertEqual(ev["verdict"], "underpowered", "n=9 < 15 floor is the honest verdict")
        self.assertEqual(ev["with"], [2, 9])


class Phase4PopulationTests(unittest.TestCase):
    """The value-feature populations (Phase 4). Each helper is monkeypatched with injected non-owner
    data, so these assert the MECHANISM over a configurable objective, never shipped defaults."""

    def _vd(self, key, company=None, company_key=None, name=None, label="accepted"):
        return {"key": key, "name": name or key, "company": company,
                "company_key": company_key, "rung": "8", "label": label}

    def test_banked_builtin_flags_by_company_key(self):
        verds = {"a": self._vd("a", company_key="ck1", label="accepted"),
                 "b": self._vd("b", company_key="ck2", label="passed-over")}
        orig = vm._banked_keys
        vm._banked_keys = lambda: {"ck1"}
        try:
            w, wo, _ = vm.verdict_cells(None, "banked", verds)
        finally:
            vm._banked_keys = orig
        self.assertEqual(w, [1, 1], "the banked+accepted target")
        self.assertEqual(wo, [0, 1], "the unbanked, passed-over target")

    def test_on_segment_reads_the_cache_not_the_patterns(self):
        cache = {"acme": {"segment": "payments"}, "beta": {"segment": "off-segment"}}
        orig = vm._segment_lookup
        vm._segment_lookup = lambda: (cache, (lambda c: c.lower()), "not-found")
        verds = {"a": self._vd("a", company="Acme"), "b": self._vd("b", company="Beta"),
                 "c": self._vd("c", company="Gamma")}  # not in cache
        try:
            flagged = vm._flag(None, "on-segment", verds)
        finally:
            vm._segment_lookup = orig
        self.assertEqual(flagged, {"a"}, "off-segment and not-in-cache are excluded")

    def test_shared_group_builtin(self):
        orig = vm._shared_group_names
        vm._shared_group_names = lambda: {"priyapatel"}
        verds = {"priyapatel": self._vd("priyapatel", name="Priya Patel"),
                 "devonmsomi": self._vd("devonmsomi", name="Devon Msomi")}
        try:
            flagged = vm._flag(None, "shared-group", verds)
        finally:
            vm._shared_group_names = orig
        self.assertEqual(flagged, {"priyapatel"})

    def test_bridge_populations_flag_company_and_person(self):
        orig = vm._bridge_sets
        vm._bridge_sets = lambda: ({"ck1"}, {"devonmsomi"})
        verds = {"a": self._vd("a", company_key="ck1", name="A"),
                 "devonmsomi": self._vd("devonmsomi", company_key="ck2", name="Devon Msomi")}
        try:
            self.assertEqual(vm._flag(None, "bridged-company", verds), {"a"})
            self.assertEqual(vm._flag(None, "is-bridge", verds), {"devonmsomi"})
        finally:
            vm._bridge_sets = orig

    def test_closeness_field_matches_predicate(self):
        orig = vm._closeness_by_norm
        vm._closeness_by_norm = lambda: {"priyapatel": "worked-together", "x": "never-spoke"}
        verds = {"priyapatel": self._vd("priyapatel"), "x": self._vd("x")}
        try:
            flagged = vm._flag(r"worked-together|classmate", "closeness", verds)
        finally:
            vm._closeness_by_norm = orig
        self.assertEqual(flagged, {"priyapatel"})

    def test_empty_store_flags_nothing_and_is_not_ratifiable(self):
        import rank_experiments as rx
        verds = {"a": self._vd("a", company_key="ck1", label="accepted")}
        orig = vm._banked_keys
        vm._banked_keys = lambda: set()
        try:
            w, wo, _ = vm.verdict_cells(None, "banked", verds)
        finally:
            vm._banked_keys = orig
        self.assertEqual(w, [0, 0], "an empty store flags nothing")
        verdict, _l, _x = rx.classify(w, wo)
        self.assertIn(verdict, ("no-cells", "underpowered"), "thin/empty data is never ratifiable")

    def test_builtin_populations_is_the_registry_contract(self):
        for p in ("board", "banked", "on-segment", "bridged-company", "is-bridge", "shared-group"):
            self.assertIn(p, vm.BUILTIN_POPULATIONS)


# NOTE: keep this the LAST thing in the file (the documented unittest.main()-ordering footgun).
if __name__ == "__main__":
    unittest.main()
