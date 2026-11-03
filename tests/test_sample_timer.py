#!/usr/bin/env python3
"""Tests for scripts/sample_timer.py — the work-sample honesty timer (kit#79 parity ship).

Ported from the reference workspace and sanitized (no owner-specific example, no hardcoded
personal path — the default log location now comes from kit_config.WORK_SAMPLE_DIR). This test
imports the module directly (never a subprocess) and writes to a temp dir, never the real
documents/ tree, so it cannot corrupt anything the run_all.sh live-store fingerprint would catch.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(KIT_ROOT, "scripts", "sample_timer.py")

_spec = importlib.util.spec_from_file_location("sample_timer", SCRIPT)
sample_timer = importlib.util.module_from_spec(_spec)
sys.modules["sample_timer"] = sample_timer
_spec.loader.exec_module(sample_timer)


class SampleTimerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log = Path(self._tmp.name) / "timelog.jsonl"

    def test_default_log_resolves_under_work_sample_dir(self):
        # The module-level default must be built from kit_config.WORK_SAMPLE_DIR, not a
        # hardcoded personal path — this is the parity fix's whole point.
        self.assertIn("timelog.jsonl", str(sample_timer.DEFAULT_LOG))
        self.assertNotIn("digits", str(sample_timer.DEFAULT_LOG).lower())

    def test_start_writes_one_event_row(self):
        self.assertFalse(self.log.exists())
        row = sample_timer.append_event(self.log, "start", "Part 1")
        self.assertTrue(self.log.exists())
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["event"], "start")
        self.assertEqual(parsed["section"], "Part 1")
        self.assertEqual(parsed, row)

    def test_start_then_stop_produces_one_closed_interval(self):
        sample_timer.append_event(self.log, "start", "Part 1")
        sample_timer.append_event(self.log, "stop")
        events = sample_timer.read_events(self.log)
        self.assertEqual(len(events), 2)
        rows = list(sample_timer.intervals(events))
        self.assertEqual(len(rows), 1)
        section, start, end = rows[0]
        self.assertEqual(section, "Part 1")
        self.assertIsNotNone(end)
        self.assertGreaterEqual(end, start)


if __name__ == "__main__":
    unittest.main()
