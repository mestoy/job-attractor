#!/usr/bin/env python3
"""BUG-709 class A: the prior-contact gate never copies a third party's address into the card's `why`.
Fictional fixtures only. Same helper as the AJS copy (AJS tests/test_local_gates_mask_parity.py compares them)."""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("lg_mask_under_test", os.path.join(os.path.dirname(HERE), "scripts", "local_gates.py"))
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)
STORE = "documents/state/send-log.jsonl"


def _why(text):
    check = lambda c: {"strong": [{"store": STORE, "line": 12, "text": text}], "weak": []}
    return lg.gate_dedup("fake-co", "Fake Co", ["fake-co"], check, "2026-10-22", True)["why"]


class Mask(unittest.TestCase):
    def test_address_inside_the_cut(self):
        w = _why("2026-08-01 Pat, pat@zzfake-mail.invalid, hello")
        self.assertNotIn("@", w)
        self.assertIn("[address in send-log.jsonl]", w)

    def test_address_straddling_the_120_cut(self):
        w = _why("x" * 110 + "pat@zzfake-mail.invalid " + "y" * 60)
        self.assertNotIn("@", w)
        self.assertIn("L12", w)

    def test_bare_fragments(self):
        for t in ("Product @zzfakeco", "VP @ Zzfake Corp"):
            self.assertNotIn("@", _why("2026-08-02 " + t))


if __name__ == "__main__":
    unittest.main()
