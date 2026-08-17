#!/usr/bin/env python3
"""Tests for scripts/bridge_sweep.py — the referral-path (network bridge) store.

Mirrors the mutual_groups conventions: append-only, an unchecked company is a DIFFERENT state from a
checked-and-none company, and path=None is late-bound (never frozen at import). Stdlib only.
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import LIVE_REPO  # noqa: E402

sys.path.insert(0, os.path.join(LIVE_REPO, "scripts"))
import bridge_sweep as bs  # noqa: E402


class BridgeSweepTests(unittest.TestCase):
    def setUp(self):
        fd, self.p = tempfile.mkstemp(suffix=".jsonl", prefix="bridges-")
        os.close(fd)
        os.unlink(self.p)
        self._orig = bs.STORE
        bs.STORE = self.p          # redirect the append target for the record() path

    def tearDown(self):
        bs.STORE = self._orig
        if os.path.exists(self.p):
            os.unlink(self.p)

    def test_record_appends_named_bridges(self):
        with redirect_stdout(io.StringIO()):
            bs.record(["Acme=Jane Doe;John Smith"])
        store = bs.load(self.p)
        self.assertIn("acme", store)
        self.assertEqual(store["acme"]["bridges"], ["Jane Doe", "John Smith"])

    def test_unchecked_is_not_checked_none(self):
        self.assertIsNone(bs.bridges_for("Nobody", bs.load(self.p)), "absent company = NOT CHECKED")
        with redirect_stdout(io.StringIO()):
            bs.record(["Beta=NONE"])
        self.assertEqual(bs.bridges_for("Beta", bs.load(self.p)), [], "checked-and-none is []")

    def test_load_path_is_late_bound_not_frozen(self):
        with redirect_stdout(io.StringIO()):
            bs.record(["Gamma=Ada Lovelace"])
        self.assertIn("gamma", bs.load(), "load() with no arg reads the (patched) STORE, not a frozen default")

    def test_append_only_prior_row_preserved(self):
        with redirect_stdout(io.StringIO()):
            bs.record(["Acme=Jane"])
            bs.record(["Acme=Jane;Bob"])
        lines = [l for l in open(self.p, encoding="utf-8").read().splitlines() if l.strip()]
        self.assertEqual(len(lines), 2, "append-only: the first row is never rewritten")
        self.assertEqual(bs.load(self.p)["acme"]["bridges"], ["Jane", "Bob"], "last write wins on read")


if __name__ == "__main__":
    unittest.main()
