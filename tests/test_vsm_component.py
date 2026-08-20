#!/usr/bin/env python3
"""Issue #65 — the VSM co-construction step is a repeatable pipeline step, not a from-memory redo.

Pins the deterministic spine:
  • the calibrated lens REJECTS internal-ops/scale/breadth numbers and KEEPS a customer time/cost-to-value one,
  • the panel gate presents ONLY candidates whose lowest voice is >=95,
  • the picker puts the panel default at option 1,
  • the final plain-words sentence is gated SHOW-DON'T-TELL (no coined term, never labeled "value stream"),
  • the step is REQUIRED for boss-hunt rungs and OPTIONAL for warm/reply/thank-you/other.
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)


class VsmLensTests(unittest.TestCase):
    def setUp(self):
        import vsm_component
        importlib.reload(vsm_component)
        self.v = vsm_component

    def test_internal_ops_number_is_off_lens(self):
        ok, reasons = self.v.validate_lens({"kind": "internal-ops", "unit": "tickets"})
        self.assertFalse(ok)
        self.assertTrue(any("off-lens" in r for r in reasons))

    def test_scale_breadth_number_is_off_lens(self):
        ok, _ = self.v.validate_lens({"kind": "scale", "unit": "customers"})
        self.assertFalse(ok)

    def test_customer_time_to_value_is_on_lens(self):
        ok, reasons = self.v.validate_lens(
            {"kind": "time", "unit": "days", "voice": "customer"})
        self.assertTrue(ok, reasons)

    def test_cost_to_value_is_on_lens(self):
        ok, _ = self.v.validate_lens({"kind": "core-promise", "unit": "%", "voice": "customer"})
        self.assertTrue(ok)

    def test_number_with_no_time_or_cost_signal_is_off_lens(self):
        ok, reasons = self.v.validate_lens({"kind": "", "unit": "logins"})
        self.assertFalse(ok)
        self.assertTrue(any("time-or-cost" in r for r in reasons))


class VsmPanelTests(unittest.TestCase):
    def setUp(self):
        import vsm_component
        importlib.reload(vsm_component)
        self.v = vsm_component

    def test_panel_below_floor_fails(self):
        self.assertFalse(self.v.panel_ok({"panel": {"ceo": 96, "cto": 94, "cpo": 97}}))

    def test_panel_at_floor_passes(self):
        self.assertTrue(self.v.panel_ok({"panel": {"ceo": 95, "cto": 95, "cpo": 95}}))

    def test_unvetted_candidate_never_passes(self):
        self.assertFalse(self.v.panel_ok({}))
        self.assertFalse(self.v.panel_ok({"panel": {}}))

    def test_eligible_keeps_only_lens_and_panel_survivors(self):
        cands = [
            {"name": "cycle", "kind": "time", "unit": "days", "voice": "customer",
             "panel": {"ceo": 96, "cto": 95, "cpo": 97}},
            {"name": "opsbrag", "kind": "internal-ops", "unit": "tickets",
             "panel": {"ceo": 99, "cto": 99, "cpo": 99}},            # off-lens
            {"name": "unvetted", "kind": "time", "unit": "days", "panel": {"ceo": 80}},  # low panel
        ]
        kept, dropped = self.v.eligible(cands)
        self.assertEqual([c["name"] for c in kept], ["cycle"])
        self.assertEqual(len(dropped), 2)

    def test_panel_default_is_option_one(self):
        cands = [
            {"name": "runnerup", "kind": "time", "unit": "days", "voice": "customer",
             "panel": {"ceo": 99, "cto": 99, "cpo": 99}},
            {"name": "thedefault", "kind": "time", "unit": "days", "voice": "customer",
             "default": True, "panel": {"ceo": 95, "cto": 95, "cpo": 95}},
        ]
        kept, _ = self.v.eligible(cands)
        self.assertEqual(kept[0]["name"], "thedefault",
                         "the panel default must lead the picker even with a lower score")


class VsmShowDontTellTests(unittest.TestCase):
    def setUp(self):
        import vsm_component
        importlib.reload(vsm_component)
        self.v = vsm_component

    def test_plain_sentence_is_clean(self):
        s = "how long from a parent's intent to give until the school actually has the money"
        self.assertEqual(self.v.show_dont_tell_violations(s), [])

    def test_value_stream_label_is_flagged(self):
        issues = self.v.show_dont_tell_violations("this is the value stream number that matters")
        self.assertTrue(any("value stream" in i.lower() for i in issues))

    def test_coined_metric_term_is_flagged(self):
        issues = self.v.show_dont_tell_violations("your Intent To Settled Rate is the one to watch")
        self.assertTrue(issues)

    def test_company_name_is_not_a_coined_term(self):
        s = "how long a Acme School Fund parent waits before the money lands"
        self.assertEqual(self.v.show_dont_tell_violations(s, company="Acme School Fund"), [])


class VsmRequiredRungTests(unittest.TestCase):
    def setUp(self):
        import vsm_component
        importlib.reload(vsm_component)
        self.v = vsm_component

    def test_boss_hunt_rung_requires_it(self):
        self.assertTrue(self.v.is_required("cold-boss"))

    def test_warm_reply_thankyou_are_optional(self):
        for r in ("warm", "reply", "thank-you", "off-ladder"):
            self.assertFalse(self.v.is_required(r), f"{r} must be optional")


class VsmCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {**os.environ, "CLAUDE_PROJECT_DIR": self.tmp.name}

    def _cli(self, *args, stdin=None):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "vsm_component.py"), *args],
                           capture_output=True, text=True, input=stdin, env=self.env)
        return r.returncode, (r.stdout + r.stderr)

    def test_present_then_pick_happy_path(self):
        cands = json.dumps([
            {"name": "cycle", "plain": "how long from intent to give until the school has the money",
             "kind": "time", "unit": "days", "voice": "customer", "default": True,
             "panel": {"ceo": 96, "cto": 95, "cpo": 97}},
        ])
        rc, out = self._cli("present", "--company", "Acme School Fund", stdin=cands)
        self.assertEqual(rc, 0, out)
        self.assertIn("1.", out)
        rc, out = self._cli(
            "pick", "--option", "1",
            "--sentence", "how long from intent to give until the school has the money")
        self.assertEqual(rc, 0, out)
        self.assertIn("locked", out)

    def test_present_rejects_when_nothing_clears_the_gate(self):
        cands = json.dumps([
            {"name": "opsbrag", "kind": "internal-ops", "unit": "tickets",
             "panel": {"ceo": 99, "cto": 99, "cpo": 99}},
        ])
        rc, out = self._cli("present", "--company", "X", stdin=cands)
        self.assertEqual(rc, 3, out)

    def test_pick_blocks_a_show_dont_tell_violation(self):
        cands = json.dumps([
            {"name": "cycle", "plain": "how long until the money lands", "kind": "time",
             "unit": "days", "voice": "customer", "default": True,
             "panel": {"ceo": 96, "cto": 95, "cpo": 97}},
        ])
        self._cli("present", "--company", "X", stdin=cands)
        rc, out = self._cli("pick", "--option", "1",
                            "--sentence", "the value stream number you should track")
        self.assertEqual(rc, 3, out)
        self.assertIn("SHOW-DON'T-TELL", out)

    def test_require_required_flag(self):
        rc, out = self._cli("--require-required", "cold-boss")
        self.assertEqual(rc, 0)
        self.assertIn("yes", out)
        rc, out = self._cli("--require-required", "reply")
        self.assertIn("no", out)


if __name__ == "__main__":
    unittest.main()
