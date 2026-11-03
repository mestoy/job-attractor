#!/usr/bin/env python3
"""The kit ships the MECHANISM, never anybody's values.

His question, 2026-09-11, on reading the onboarding copy: "why are we shipping my
defaults?" He was right to ask. Until that day `partner-starter` shipped
POLITICS_DISQUAL populated with his own politics, INDUSTRY_VETO with his ethical
vetoes, and COMP_FLOOR at 150000 — all three ACTIVE on a fresh install, screening
companies out on a stranger's values before the install's owner had answered anything.

The line this file defends:

  MECHANISM detects what a posting SAYS. "Does this text name an LBO", "does this text
  say hybrid" — the answer is the same regardless of who is asking, so it ships populated
  and an empty one is a silent-pass bug.

  A VALUE decides what someone WILL NOT ACCEPT. Nobody else's answer is a sane default,
  so it ships empty. An empty value list screens on nothing and says so, which is the
  honest failure mode; a populated one screens on somebody else's conscience, silently.

This is not style. A comp floor and a politics filter shipped on by default fall hardest
on the people with the least room to argue with them.
"""
import os as _os, sys as _sys  # BUG-736: seed kit_config first (bare checkout has only the example)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _kit_config_shim  # noqa: E402,F401
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import kit_config  # noqa: E402


class ValuesShipEmpty(unittest.TestCase):
    """Each of these encodes a person's conscience, wallet or ethics. None has a sane default."""

    def test_politics_ships_empty(self):
        self.assertEqual(kit_config.POLITICS_DISQUAL, [],
                         "POLITICS_DISQUAL must ship empty: it is a value, not a mechanism")
        self.assertEqual(kit_config.POLITICS_CLEAR, [],
                         "POLITICS_CLEAR pairs with DISQUAL; with nothing disqualifying there is "
                         "nothing to clear")

    def test_industry_veto_ships_empty(self):
        self.assertEqual(kit_config.INDUSTRY_VETO, [],
                         "INDUSTRY_VETO must ship empty: whose industries are vetoed is the "
                         "user's answer, not the kit's")

    def test_comp_floor_ships_at_zero(self):
        """0 means 'do not screen on comp'. check_revisits already falls back to 0 on
        ImportError, so the codebase has always treated it as a valid no-floor value."""
        self.assertEqual(kit_config.COMP_FLOOR, 0,
                         "COMP_FLOOR must ship at 0: a stranger's pay floor silently removes "
                         "companies the owner never ruled on")

    def test_no_shipped_value_list_carries_the_authors_own_filters(self):
        """A regression guard with teeth: the specific strings that shipped until 2026-09-11."""
        his = ("right[- ]lean", "conservative[- ]lean", r"\bdefense\b", r"\bmilitary\b",
               r"\bweapons?\b", "public trust")
        for lst_name in ("POLITICS_DISQUAL", "POLITICS_CLEAR", "INDUSTRY_VETO"):
            body = " ".join(getattr(kit_config, lst_name)).lower()
            for pattern in his:
                self.assertNotIn(pattern.lower(), body,
                                 "%s has re-acquired the author's own filter %r"
                                 % (lst_name, pattern))


class MechanismShipsPopulated(unittest.TestCase):
    """These detect what a posting says. Blanking one does not screen nothing loudly —
    it passes everything silently, which is the failure the tooling exists to catch."""

    def test_pe_detection_ships_populated(self):
        self.assertTrue(kit_config.PE_FLAG,
                        "PE_FLAG detects whether a posting names PE ownership. Whether that "
                        "disqualifies is the user's call; the detection is not")

    def test_remote_detection_ships_populated(self):
        self.assertTrue(kit_config.REMOTE_DISQUAL)
        self.assertTrue(kit_config.REMOTE_CONFIRM)

    def test_mechanism_patterns_are_about_the_posting_not_the_person(self):
        """Every mechanism pattern should be a thing a job ad SAYS."""
        import re
        for pat in kit_config.PE_FLAG + kit_config.REMOTE_DISQUAL + kit_config.REMOTE_CONFIRM:
            re.compile(pat)  # must be a valid regex, or the gate dies at import


class TheDoctrineIsWrittenDown(unittest.TestCase):
    def test_the_file_explains_the_distinction(self):
        """The next person to add a list has to be able to tell which kind it is without
        asking. The docstring carries the rule; if it is gone, the rule will not survive."""
        # BUG-736: a bare checkout ships only the example, which carries the same doctrine header.
        _scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
        _cfg = os.path.join(_scripts, "kit_config.py")
        if not os.path.isfile(_cfg):
            _cfg = os.path.join(_scripts, "kit_config.example.py")
        src = open(_cfg, encoding="utf-8").read()
        head = src[:src.index("import os")]
        self.assertIn("MECHANISM", head)
        self.assertIn("VALUE", head)
        self.assertIn("ship EMPTY", head)




class AnEmptyValueScreenSaysSo(unittest.TestCase):
    """The obligation the doctrine created, and the reason the old test was right.

    "Empty" and "clean" produce the same silence at a gate. 22 veto patterns once shipped
    dead for weeks and every card sailed through green, which is why
    test_the_installed_list_is_not_empty existed. Shipping value lists empty is only
    defensible if the empty state ANNOUNCES itself.
    """

    def _gate(self):
        import importlib
        return importlib.import_module("check_screen_gate")

    def test_every_unset_value_screen_is_named(self):
        names = {n for n, _ in self._gate().unset_value_screens()}
        self.assertEqual(names, {"INDUSTRY_VETO", "POLITICS_DISQUAL", "COMP_FLOOR"},
                         "a value screen that is unset must be reported by name")

    def test_each_one_states_its_consequence_not_just_its_name(self):
        """'INDUSTRY_VETO is empty' tells a reader nothing. 'No company can fail on its
        industry' tells them what it means for the cards in front of them."""
        for name, consequence in self._gate().unset_value_screens():
            self.assertGreater(len(consequence), 25, "%s has no stated consequence" % name)

    def test_a_configured_screen_drops_off_the_unset_list(self):
        gate = self._gate()
        saved = gate.INDUSTRY_VETO
        try:
            gate.INDUSTRY_VETO = [r"\bdefense\b"]
            names = {n for n, _ in gate.unset_value_screens()}
            self.assertNotIn("INDUSTRY_VETO", names)
        finally:
            gate.INDUSTRY_VETO = saved

    def test_the_gate_reports_unset_screens_on_a_GREEN_run_too(self):
        """A green run is exactly where silence is dangerous: the card passed, and the
        reader has no way to know a whole screen never ran."""
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts", "check_screen_gate.py"), encoding="utf-8").read()
        tail = src[src.index("decision-ready — all screen layers"):]
        self.assertIn("_say_unset()", tail,
                      "the green path must report unset value screens as well as the red path")


if __name__ == "__main__":
    unittest.main()
