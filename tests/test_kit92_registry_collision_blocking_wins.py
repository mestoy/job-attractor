"""REAL BUG found by 3f (regression from 726c9c8's canon-the-key fix): canon()ing the key at
index time means two DECLARED rows that canon to the SAME key now collapse in `by_key`, and
the LAST one written wins regardless of status -- a blocked row overwritten by a later, unrelated
"ok" row (or the reverse order) makes a declared-blocked company read CLEAN. Fix: when two rows
collide on their canon key, the row whose status is BLOCKING wins, its aliases merged with the
loser's, and the collision is printed to stderr so a duplicate registry entry is visible.
"""
import contextlib
import importlib
import io
import json
import os
import _roots
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import screen_sweep  # noqa: E402
import employers  # noqa: E402


class TestRegistryCollisionBlockingWins(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.docs = os.path.join(self.tmp.name, "documents")
        os.makedirs(self.docs, exist_ok=True)
        with open(os.path.join(self.docs, "blocked-employers-list.md"), "w", encoding="utf-8") as fh:
            fh.write("# Blocked employers\n\n")
        self._restore_roots = _roots.set_roots(self.tmp.name)
        self._real_repo = screen_sweep.REPO
        screen_sweep.REPO = self.tmp.name
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        self.addCleanup(self._restore)
        self.employers = importlib.reload(employers)

    def _restore(self):
        self._restore_roots()
        screen_sweep.REPO = self._real_repo
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        importlib.reload(employers)

    def _seed(self, *rows):
        with open(os.path.join(self.docs, "employers.jsonl"), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        self.employers._CACHE.clear()
        self.employers._REG_INDEX = None

    def test_a_blocked_then_ok_same_canon_key_stays_blocked(self):
        # 3f's exact case: "boundless" and "Boundless" are two different raw keys, one canon
        # key. Blocked written FIRST.
        self._seed(
            {"key": "boundless", "display": "Boundless", "aliases": [], "status": "blocked"},
            {"key": "Boundless", "display": "Boundless One", "aliases": [], "status": "ok"},
        )
        self.assertTrue(self.employers.is_blocked("boundless"))
        self.assertTrue(self.employers.is_blocked("Boundless"))

    def test_b_ok_then_blocked_same_canon_key_stays_blocked(self):
        # Reverse write order -- must not matter which one landed last.
        self._seed(
            {"key": "Boundless", "display": "Boundless One", "aliases": [], "status": "ok"},
            {"key": "boundless", "display": "Boundless", "aliases": [], "status": "blocked"},
        )
        self.assertTrue(self.employers.is_blocked("boundless"))
        self.assertTrue(self.employers.is_blocked("Boundless"))

    def test_c_collision_is_printed_to_stderr(self):
        self._seed(
            {"key": "boundless", "display": "Boundless", "aliases": [], "status": "blocked"},
            {"key": "Boundless", "display": "Boundless One", "aliases": [], "status": "ok"},
        )
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            self.employers.registry()
        self.assertIn("boundless", buf.getvalue().lower())

    def test_d_northwind_case_from_726c9c8_stays_green(self):
        self._seed({"key": "northwind-holdings", "display": "Northwind Holdings",
                     "aliases": [], "status": "blocked"})
        self.assertTrue(self.employers.is_blocked("Northwind Holdings"))

    def test_e_two_blocked_rows_colliding_merge_aliases(self):
        self._seed(
            {"key": "boundless", "display": "Boundless", "aliases": ["BNDL"], "status": "blocked"},
            {"key": "Boundless", "display": "Boundless Two", "aliases": ["BND2"], "status": "blocked"},
        )
        self.assertTrue(self.employers.is_blocked("BNDL"))
        self.assertTrue(self.employers.is_blocked("BND2"))

    def test_f_two_blocked_rows_colliding_the_first_display_wins(self):
        # 3f's nit: the stderr message says "the first if neither/both are", so when BOTH
        # rows are blocked, the FIRST one's display/entity must win, not the last.
        self._seed(
            {"key": "boundless", "display": "Boundless", "aliases": [], "status": "blocked"},
            {"key": "Boundless", "display": "Boundless Two", "aliases": [], "status": "blocked"},
        )
        why = self.employers.why("Boundless")
        self.assertEqual((why or {}).get("entity", {}).get("display"), "Boundless")

    def test_g_ok_then_blocked_the_priors_own_alias_reads_blocked_too(self):
        # 3f's real safety bug: "boundless" ("ok", declares alias "OLDALIAS") is indexed and
        # its alias entry ("oldalias" -> the ok row) is banked BEFORE "Boundless" ("blocked")
        # is even read. When the blocked row wins the collision, the OLD alias entry still
        # points at the stale "ok" row object -- is_blocked("OLDALIAS") must not read False.
        self._seed(
            {"key": "boundless", "display": "Boundless", "aliases": ["OLDALIAS"], "status": "ok"},
            {"key": "Boundless", "display": "Boundless Two", "aliases": [], "status": "blocked"},
        )
        self.assertTrue(self.employers.is_blocked("OLDALIAS"))

    def test_h_blocked_then_ok_unaffected_by_the_fix(self):
        self._seed(
            {"key": "boundless", "display": "Boundless", "aliases": ["BNDL"], "status": "blocked"},
            {"key": "Boundless", "display": "Boundless Two", "aliases": ["OK2"], "status": "ok"},
        )
        self.assertTrue(self.employers.is_blocked("BNDL"))
        self.assertTrue(self.employers.is_blocked("OK2"))  # merged alias, blocked wins overall

    def test_i_both_blocked_unaffected_by_the_fix(self):
        self._seed(
            {"key": "boundless", "display": "Boundless", "aliases": ["BNDL"], "status": "blocked"},
            {"key": "Boundless", "display": "Boundless Two", "aliases": ["BND2"], "status": "blocked"},
        )
        self.assertTrue(self.employers.is_blocked("BNDL"))
        self.assertTrue(self.employers.is_blocked("BND2"))

    def test_j_neither_blocked_unaffected_by_the_fix(self):
        self._seed(
            {"key": "boundless", "display": "Boundless", "aliases": ["OK1"], "status": "ok"},
            {"key": "Boundless", "display": "Boundless Two", "aliases": ["OK2"], "status": "ok"},
        )
        self.assertFalse(self.employers.is_blocked("OK1"))
        self.assertFalse(self.employers.is_blocked("OK2"))

    def test_k_a_declared_key_colliding_with_an_earlier_rows_alias_never_repoints_that_row(self):
        # 3f's second real bug: Acme (ok, alias "Beta") is indexed first, banking "beta" as an
        # ALIAS entry pointing at Acme. Beta (blocked, a genuinely separate, later-declared
        # entity) then canon-collides with that ALIAS entry, not with a declared key. The old
        # single-pass repoint logic treated this as the SAME kind of collision as two declared
        # keys and repointed Acme's own declared "acme" key too, making is_blocked("Acme") True
        # for an entity that is actually "ok". Acme must stay ok; Beta must stay blocked; "Beta"
        # must resolve to the Beta row.
        self._seed(
            {"key": "acme", "display": "Acme", "aliases": ["Beta"], "status": "ok"},
            {"key": "beta", "display": "Beta", "aliases": [], "status": "blocked"},
        )
        self.assertFalse(self.employers.is_blocked("Acme"))
        self.assertTrue(self.employers.is_blocked("Beta"))
        why = self.employers.why("Beta")
        self.assertEqual((why or {}).get("entity", {}).get("display"), "Beta")

    def test_l_an_alias_claimed_by_two_rows_the_blocked_one_wins(self):
        # Two UNRELATED declared entities each list the same alias. The blocked claimant wins
        # the alias; the other stays a distinct, unaffected declared entity.
        self._seed(
            {"key": "gamma", "display": "Gamma", "aliases": ["Shared"], "status": "ok"},
            {"key": "delta", "display": "Delta", "aliases": ["Shared"], "status": "blocked"},
        )
        self.assertTrue(self.employers.is_blocked("Shared"))
        self.assertFalse(self.employers.is_blocked("Gamma"))
        self.assertTrue(self.employers.is_blocked("Delta"))


if __name__ == "__main__":
    unittest.main()
