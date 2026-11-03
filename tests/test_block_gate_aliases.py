#!/usr/bin/env python3
"""kit#92 (narrow half, PROXY P7 2026-09-22): the hard block gate (filter_blocked.py, via
check_dup.blocked_key_hit) is alias-blind. It matches canon(company) against the blocked list's
own keys with exact equality only, and never consults kit_config.COMPANY_ALIASES, so a company
blocked under an abbreviation (e.g. a drop under "FHAZ") reads clean when a scout
later screens it under its full ATS-facing name ("Fakeco Health of Arizona").

Scope, deliberately narrow (his ruling): union the EXISTING alias data
(kit_config.COMPANY_ALIASES) into blocked_key_hit() at exact canon()-equality only. No fuzzy
matching, no automatic parenthetical expansion of prose. This can only ADD refusals, never
remove one -- the safe direction for a hard gate. The auto-expansion heuristic and the separate
common-word false-positive the owner found while testing are held for him as Q29.

Run:  python3 -m unittest tests.test_block_gate_aliases
"""
import importlib
import os
import _roots
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

check_dup = importlib.import_module("check_dup")
screen_sweep = importlib.import_module("screen_sweep")


class TestBlockGateConsultsCompanyAliases(unittest.TestCase):
    """Fictional names throughout: Fakebank Regional Alliance / FBRA is a stand-in for the
    abbreviation vs full-name shape (FHAZ / "Fakeco Health of Arizona") reported on #92."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents"), exist_ok=True)
        with open(os.path.join(self.tmp.name, "documents", "blocked-employers-list.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("# blocked\n- FBRA (blocked 2026-08-09, culture): a real drop.\n")
        self._real_repo = check_dup.REPO
        check_dup.REPO = self.tmp.name
        self.addCleanup(lambda: setattr(check_dup, "REPO", self._real_repo))
        # Same sandbox shape as test_filter_blocked_contacted.py: blocked_key_hit reaches the
        # list through screen_sweep.REPO (module constant), not the environment.
        self._restore_roots = _roots.set_roots(self.tmp.name)
        self._real_ss_repo = screen_sweep.REPO
        screen_sweep.REPO = self.tmp.name
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        importlib.reload(importlib.import_module("employers"))
        self._real_aliases = check_dup.ALIASES
        self.addCleanup(self._restore_sandbox)

    def _restore_sandbox(self):
        self._restore_roots()
        screen_sweep.REPO = self._real_ss_repo
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        check_dup.ALIASES = self._real_aliases
        importlib.reload(importlib.import_module("employers"))

    def test_a_registered_alias_of_a_blocked_abbreviation_is_caught_under_its_full_name(self):
        check_dup.ALIASES = [{"fbra", "fakebank regional alliance"}]
        self.assertEqual(
            check_dup.blocked_key_hit("Fakebank Regional Alliance"), "fbra",
            "a company blocked under 'FBRA' with 'Fakebank Regional Alliance' registered as its "
            "alias must be caught under the full name",
        )

    def test_the_abbreviation_itself_still_matches_unchanged(self):
        check_dup.ALIASES = [{"fbra", "fakebank regional alliance"}]
        self.assertEqual(check_dup.blocked_key_hit("FBRA"), "fbra")

    def test_no_alias_registered_still_misses_the_full_name(self):
        """This is the state before the fix, and it must remain true for any company with NO
        registered alias -- the fix adds refusals for aliased entries, it does not invent
        linguistic knowledge for ones nobody has aliased."""
        check_dup.ALIASES = []
        self.assertIsNone(check_dup.blocked_key_hit("Fakebank Regional Alliance"))

    def test_a_name_sharing_one_ordinary_word_with_a_blocked_entry_is_not_newly_blocked(self):
        """Control. Exact canon()-equality is the point: a name that merely SHARES a word with a
        blocked entry, or with an alias group, must not become newly blocked."""
        check_dup.ALIASES = [{"fbra", "fakebank regional alliance"}]
        self.assertIsNone(check_dup.blocked_key_hit("Regional Alliance Partners"))

    def test_an_alias_group_the_blocked_key_is_not_in_authorizes_nothing(self):
        """A COMPANY_ALIASES group that has NOTHING to do with a blocked key must not leak a
        block onto an unrelated company just because it shares a group with something else."""
        check_dup.ALIASES = [{"examplecloud", "exampledata"}]
        self.assertIsNone(check_dup.blocked_key_hit("ExampleCloud"))

    def test_every_block_that_fired_before_still_fires(self):
        """Regression: the exact, unaliased match this gate already made must be unaffected."""
        check_dup.ALIASES = [{"fbra", "fakebank regional alliance"}]
        self.assertEqual(check_dup.blocked_key_hit("FBRA Holdings LLC"), "fbra")


if __name__ == "__main__":
    unittest.main()
