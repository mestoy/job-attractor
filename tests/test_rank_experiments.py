#!/usr/bin/env python3
"""Tests for scripts/rank_experiments.py — the self-refining ranker's EXPERIMENT REGISTRY.

Built 2026-08-14 alongside the script (designed and built in one pass), per the campaign rule
that a new mechanism without a test is how a defect hides. The registry formalizes the ad-hoc
EXP-000 / EXP-001 loop into propose / run / list / ratify over an append-only jsonl.

WHAT THESE PIN, in order of load-bearingness:
  1. The CELL-ORDER SWAP. `validate_signal` and `warm_path_lift` both return cells as
     [replies, sends]; `rank_criteria._lift` unpacks [sends, replies]. The classifier must swap, and
     `test_cell_order_swap_pins_the_bridge` fails loudly if it ever stops swapping — the un-swapped
     bug reads the sends count as the replies count and misreports separation as underpowered.
  2. APPEND-ONLY. A status change is a NEW row; no line is ever rewritten. Two tests assert the file
     grows by exactly one and prior bytes are untouched.
  3. RATIFICATION IS THE USER'S. `run` never writes a ratified/ruling event; only `ratify` does, and
     the evidence lane refuses a verdict the data cannot carry.
  4. GENERICITY. The mechanism measures whatever the CURRENT USER'S data expresses — a test injects a
     non-owner dataset and asserts the cells derive from it, and no built-in predicate is reachable.

Fixtures are synthetic and written to a tempfile registry; the sandbox-backed suites run the real
script in a harness sandbox, so nothing here touches the live board or state.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import SandboxTest, LIVE_REPO  # noqa: E402

sys.path.insert(0, os.path.join(LIVE_REPO, "scripts"))
import rank_experiments as rx  # noqa: E402
import rank_criteria as rc  # noqa: E402


def _tmp():
    fd, p = tempfile.mkstemp(suffix=".jsonl", prefix="experiments-")
    os.close(fd)
    os.unlink(p)  # start ABSENT — first propose must create it
    return p


def _lines(path):
    if not os.path.exists(path):
        return []
    return [l for l in open(path, encoding="utf-8").read().splitlines() if l.strip()]


class SchemaRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.path = _tmp()

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_propose_appends_one_parseable_row(self):
        with redirect_stdout(io.StringIO()):
            eid = rx.propose("warm path predicts replies", "warm-path",
                             join="warm_path_lift", path=self.path)
        lines = _lines(self.path)
        self.assertEqual(len(lines), 1, "propose writes exactly one line")
        rec = json.loads(lines[0])
        self.assertEqual(rec["event"], "proposed")
        self.assertEqual(rec["id"], "EXP-000")
        self.assertEqual(eid, "EXP-000")
        for field in ("event", "id", "ts", "hypothesis", "signal", "join",
                      "predicate", "population", "objective"):
            self.assertIn(field, rec, f"proposed row must carry {field!r}")

    def test_ids_derive_from_existing_records_not_a_clock(self):
        # Seed out-of-order ids; the next mint is max+1, never a timestamp or count.
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "proposed", "id": "EXP-000"}) + "\n")
            fh.write(json.dumps({"event": "proposed", "id": "EXP-007"}) + "\n")
        with redirect_stdout(io.StringIO()):
            eid = rx.propose("h", "s", predicate=r"\bx\b", path=self.path)
        self.assertEqual(eid, "EXP-008", "next id is max(existing)+1, padded to 3 digits")


class AppendOnlyProjectionTests(unittest.TestCase):
    def setUp(self):
        self.path = _tmp()

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _seed_run(self, verdict="separation"):
        # A hand-built proposed+run pair for one id, so list()/project() have something to fold.
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "proposed", "id": "EXP-000", "signal": "warm-path",
                                 "join": "warm_path_lift", "predicate": None,
                                 "population": None}) + "\n")
            fh.write(json.dumps({"event": "run", "id": "EXP-000", "verdict": verdict,
                                 "with": [14, 60], "without": [36, 257], "lift": 1.67}) + "\n")

    def test_latest_event_wins(self):
        self._seed_run()
        with redirect_stdout(io.StringIO()):
            rx.ratify("EXP-000", lane="evidence", note="ship it", path=self.path)
        proj = rx.project(self.path)
        self.assertIn("EXP-000", proj)
        self.assertIsNotNone(proj["EXP-000"]["decision"])
        self.assertEqual(proj["EXP-000"]["decision"]["lane"], "evidence")
        # all three events persist on disk
        self.assertEqual(len(_lines(self.path)), 3)

    def test_status_change_never_mutates_a_prior_row(self):
        self._seed_run()
        before = _lines(self.path)
        with redirect_stdout(io.StringIO()):
            rx.ratify("EXP-000", lane="ruling", note="judgment", path=self.path)
        after = _lines(self.path)
        self.assertEqual(after[:2], before, "prior rows are byte-identical after a new event")
        self.assertEqual(len(after), len(before) + 1, "exactly one row appended")


class VerdictClassifierTests(unittest.TestCase):
    """classify(with_cell, without_cell) with cells in [replies, sends] order (the join contract).
    Reuses rank_criteria._lift after swapping into its [sends, replies] order."""

    def test_underpowered_below_the_floor(self):
        v, _lift, _x = rx.classify([2, 9], [63, 240])  # EXP-001 shape, n=9 < 15
        self.assertEqual(v, "underpowered")

    def test_no_separation_flat_lift(self):
        v, lift, _x = rx.classify([20, 100], [20, 100])  # lift 1.0
        self.assertEqual(v, "no-separation")
        self.assertAlmostEqual(lift, 1.0, places=3)

    def test_separation_positive(self):
        v, lift, direction = rx.classify([30, 100], [15, 100])  # 2.0, clamped, >= band-hi
        self.assertEqual(v, "separation")
        self.assertEqual(direction, "+")

    def test_separation_negative(self):
        v, lift, direction = rx.classify([5, 100], [15, 100])  # 0.33 -> clamp 0.5 <= band-lo
        self.assertEqual(v, "separation")
        self.assertEqual(direction, "-")

    def test_base_rate_unformable_is_underpowered(self):
        v, lift, reason = rx.classify([5, 20], [0, 100])  # b_r == 0 -> _lift None, but n>=15
        self.assertEqual(v, "underpowered")
        self.assertIsNone(lift)

    def test_zero_cells_is_no_cells(self):
        v, _lift, _x = rx.classify([0, 0], [10, 100])
        self.assertEqual(v, "no-cells")

    def test_cell_order_swap_pins_the_bridge(self):
        # Illustrative shape: with=[14 replies, 60 sends]. Correct swap feeds _lift a_s=60 (>=15)
        # and yields lift ~1.67 -> separation. The un-swapped bug would feed a_s=14 (<15) and
        # misreport underpowered. Asserting separation is the swap's tripwire.
        v, lift, direction = rx.classify([14, 60], [36, 257])
        self.assertEqual(v, "separation",
                         "with=[14,60] must read n=60 (sends), not n=14 (replies) — the swap")
        self.assertEqual(direction, "+")
        self.assertGreater(lift, 1.41)


class LeakageTests(unittest.TestCase):
    def setUp(self):
        self.path = _tmp()

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_propose_refuses_a_leaky_predicate(self):
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(rx.ExpError):
                rx.propose("h", "leak", predicate=r"replied|founder", path=self.path)
        self.assertEqual(_lines(self.path), [], "a leaky propose appends nothing")

    def test_run_records_a_leaky_refusal(self):
        # Defense in depth: LEAKY_FIELDS may grow after propose, so run logs a leaky refusal.
        with redirect_stdout(io.StringIO()):
            rx.propose("h", "sig", predicate=r"\bx\b", population="titles", path=self.path)
        orig = rc.validate_signal
        rc.validate_signal = lambda *a, **k: {"error": "leaky", "fields": ["replied"]}
        try:
            with redirect_stdout(io.StringIO()):
                ev = rx.run_experiment("EXP-000", path=self.path)
        finally:
            rc.validate_signal = orig
        self.assertEqual(ev["verdict"], "leaky")
        self.assertIn("replied", ev.get("reason", ""))


class RatifyTests(unittest.TestCase):
    def setUp(self):
        self.path = _tmp()

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _propose_and_run(self, sig_return):
        with redirect_stdout(io.StringIO()):
            rx.propose("h", "sig", predicate=r"\bx\b", population="titles", path=self.path)
        orig = rc.validate_signal
        rc.validate_signal = lambda *a, **k: sig_return
        try:
            with redirect_stdout(io.StringIO()):
                return rx.run_experiment("EXP-000", path=self.path)
        finally:
            rc.validate_signal = orig

    def test_run_never_ratifies(self):
        self._propose_and_run({"signal": "sig", "with": [30, 100], "without": [15, 100],
                               "unjoined": 0})
        proj = rx.project(self.path)
        self.assertEqual(proj["EXP-000"]["last_run"]["verdict"], "separation")
        self.assertIsNone(proj["EXP-000"]["decision"], "run alone leaves no decision")
        for line in _lines(self.path):
            self.assertNotIn(json.loads(line)["event"], ("ratified", "ruling"))

    def test_ratify_appends_judgment_per_lane(self):
        self._propose_and_run({"signal": "sig", "with": [30, 100], "without": [15, 100],
                               "unjoined": 0})
        with redirect_stdout(io.StringIO()):
            ev = rx.ratify("EXP-000", lane="evidence", note="corroborated", path=self.path)
        self.assertEqual(ev["event"], "ratified")
        self.assertIsNotNone(ev.get("weight"), "evidence lane defaults weight to the run's lift")

    def test_evidence_ratify_refused_under_the_floor_ruling_allowed(self):
        self._propose_and_run({"signal": "sig", "with": [2, 9], "without": [63, 240],
                               "unjoined": 0})  # underpowered
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(rx.ExpError):
                rx.ratify("EXP-000", lane="evidence", note="too soon", path=self.path)
        # nothing appended by the refused evidence ratify
        self.assertNotIn("ratified", "".join(_lines(self.path)))
        # but the ruling lane is always open — that is its purpose
        with redirect_stdout(io.StringIO()):
            ev = rx.ratify("EXP-000", lane="ruling", note="surfacing consult", path=self.path)
        self.assertEqual(ev["event"], "ruling")


class GenericityTests(unittest.TestCase):
    """The mechanism must measure whatever the CURRENT USER'S data expresses, with zero owner-
    specific predicates in code. [[the-kit-must-not-assume-whose-search-it-is-running]]"""

    def setUp(self):
        self.path = _tmp()

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_mechanism_over_an_injected_objective(self):
        # An invented, non-owner dataset. If the loop is generic, the cells derive from THIS.
        # predicate \bwidgets?\b below matches both "Widgets" and "Widget" (the optional s), so both
        # widget-titled recipients flag; a bare \bwidget\b would miss the plural "Widgets".
        people = [("Alpha One", "Head of Widgets", "WidgetCo", "", ""),
                  ("Beta Two", "Chief Widget Officer", "WidgetCo", "", ""),
                  ("Gamma Three", "Sales Lead", "OtherCo", "", "")]
        sends = [{"to_name": "Alpha One", "status": "sent", "replied": True},
                 {"to_name": "Beta Two", "status": "sent", "replied": True},
                 {"to_name": "Gamma Three", "status": "sent", "replied": False}]
        import rung_ladder
        _pr, _ld = rc._people_rows, rung_ladder.load
        rc._people_rows = lambda: iter(people)
        rung_ladder.load = lambda *a, **k: list(sends)
        try:
            with redirect_stdout(io.StringIO()):
                rx.propose("widget titles reply", "widget", predicate=r"\bwidgets?\b",
                           population="titles", path=self.path)
                ev = rx.run_experiment("EXP-000", path=self.path)
        finally:
            rc._people_rows = _pr
            rung_ladder.load = _ld
        # 2 widget-title recipients (both replied) vs 1 non-widget (no reply) — from the INJECTED set.
        self.assertEqual(ev["with"], [2, 2], "cells derive from the injected dataset, not the owner's")
        self.assertEqual(ev["without"], [0, 1])

    def test_no_builtin_predicate_fallback(self):
        # A validate_signal-join record with no predicate must ERROR, never fall through to the
        # built-in `known` signal dict inside validate_signal.
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(rx.ExpError):
                rx.propose("h", "founder", predicate=None, join="validate_signal", path=self.path)


# ⛔ ReproductionTests NOT PORTED TO THE KIT (2026-08-16). The reference workspace carries a
# ReproductionTests class that reproduces the OWNER'S specific EXP-000/EXP-001 verdicts
# ("separation" / "underpowered") end to end over the OWNER'S live send log. A partner kit ships
# with empty stores, so those runs return "no-cells" and the assertions can never hold — they assert
# a data outcome, not the mechanism. The mechanism itself is covered portably by GenericityTests
# (injects a synthetic dataset and asserts the cells derive from it) and BuiltinPopulationProposeTests
# below. [[the-kit-must-not-assume-whose-search-it-is-running]]


class BuiltinPopulationProposeTests(unittest.TestCase):
    """Phase 4: a verdict_objective experiment may name a built-in boolean population with no
    predicate; a field population still requires one. The built-in list is IMPORTED from verdict_miner
    (the registry never keeps its own copy)."""

    def _tmp(self):
        fd, p = tempfile.mkstemp(suffix=".jsonl", prefix="exp-")
        os.close(fd)
        os.unlink(p)
        return p

    def test_builtin_population_needs_no_predicate(self):
        p = self._tmp()
        try:
            with redirect_stdout(io.StringIO()):
                eid = rx.propose("banked desirability", "banked", join="verdict_objective",
                                 population="banked", objective="value", path=p)
            self.assertEqual(eid, "EXP-000")
        finally:
            if os.path.exists(p):
                os.unlink(p)

    def test_field_population_still_needs_a_predicate(self):
        p = self._tmp()
        try:
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(rx.ExpError):
                    rx.propose("closeness feature", "close", join="verdict_objective",
                               population="closeness", objective="value", path=p)
        finally:
            if os.path.exists(p):
                os.unlink(p)


# NOTE: keep this the LAST thing in the file — the documented footgun at the bottom of
# tests/test_rank_criteria.py (unittest.main() running before later classes are defined).
if __name__ == "__main__":
    unittest.main()
