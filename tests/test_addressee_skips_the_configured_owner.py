#!/usr/bin/env python3
"""check_preview._addressee skips the install owner's own first name, read from kit_config.OWNER_FIRST.

BUG-787 slice 1 shipped three first names as a literal in that skip list. The list now comes from the install's own config,
so no person's name rides in the kit, and an unconfigured install excludes nothing. Names here are made up.
"""
import os
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import check_preview as cp  # noqa: E402


def picker(*greetings):
    return {"questions": [{"question": "Which opener?", "header": "Draft",
                           "options": [{"label": "A", "description": "x", "preview": "\n\n".join(greetings)}]}]}


def config(owner_first):
    mod = types.ModuleType("kit_config")
    if owner_first is not None:
        mod.OWNER_FIRST = owner_first
    return mock.patch.dict(sys.modules, {"kit_config": mod})


class AddresseeSkipsTheOwner(unittest.TestCase):
    def test_the_configured_owner_is_not_the_addressee(self):
        with config("Zzqana"):
            self.assertEqual(cp._addressee(picker("Hi Zzqana,\nbody", "Hi Yyqtor,\nbody")), "Yyqtor")

    def test_the_skip_ignores_case_and_surname_position(self):
        with config("zzqana"):
            self.assertEqual(cp._addressee(picker("Hi Zzqana,\nbody")), None)

    def test_unconfigured_excludes_nothing(self):
        for cfg in (None, "", "You", "Your"):
            with self.subTest(owner_first=cfg), config(cfg):
                self.assertEqual(cp._own_first_names(), set())
                self.assertEqual(cp._addressee(picker("Hi Zzqana,\nbody")), "Zzqana")

    def test_no_kit_config_excludes_nothing(self):
        with mock.patch.dict(sys.modules, {"kit_config": None}):
            self.assertEqual(cp._own_first_names(), set())

    def test_ube_is_still_skipped(self):
        with config(None):
            self.assertEqual(cp._addressee(picker("Hi Ube,\nbody")), None)

    def test_no_first_name_literal_in_the_skip_logic(self):
        import re
        src = open(os.path.join(os.path.dirname(HERE), "scripts", "check_preview.py"), encoding="utf-8").read()
        body = src[src.index("def _own_first_names"):src.index("def _norm(")]
        quoted = set(re.findall(r'"([A-Za-z_]+)"', body))
        self.assertLessEqual(quoted, {"OWNER_FIRST", "you", "your", "ube"}, "a name literal rides in the skip logic")


if __name__ == "__main__":
    unittest.main()
