#!/usr/bin/env python3
"""H4: pii_gate.py gains a tier for the owner's own BARE first name (WARN) and for facts on the
owner's own honesty/RETIRED list (BLOCK) when they appear in shipped files.

Both tiers are fed from the resolved owner/retired dicts the same way the existing owner-identity
tier already is (`owner=...` / `retired=...` passed straight into `scan_items()`/`scan()`), never
from anything hardcoded in this module — see `_resolve_owner()` and `_resolve_retired_facts()` in
pii_gate.py, which read `kit_config.OWNER_FIRST` / `kit_config.RETIRED` / `kit_config.RETIRED_PATTERNS`
at gate time. All fixtures below use fictional, generic values (a made-up first name, a made-up
retired claim) so this file itself ships clean through the gate it tests."""
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("pii_gate_under_test",
                                                os.path.join(REPO, "scripts", "pii_gate.py"))
pg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pg)

OWNER = {"name": "Aldric Ashgrove", "first": "Aldric"}
RETIRED = (["$9.9M unicorns served"], [(r"\b100x\s+faster\b", "retired 100x claim")])


def _tree(**files):
    d = tempfile.mkdtemp()
    for name, body in files.items():
        with open(os.path.join(d, name), "w") as fh:
            fh.write(body)
    return d


def _scan(tree, owner=None, retired=None, full=None):
    # scan(root, full, tokens, companies, owner, retired) — empty vocab isolates the H4 tiers
    return pg.scan(tree, full or set(), set(), set(), owner=owner, retired=retired)


def _whys(hits):
    return {why for _rel, _hit, why in hits}


class BareFirstName(unittest.TestCase):
    def test_bare_first_name_warns_when_confirmed_private(self):
        tree = _tree(**{"notes.md": "Aldric ruled 2026-09-10: ship it.\n"})
        blocks, warns = pg.scan_items([("notes.md", open(os.path.join(tree, "notes.md")).read())],
                                      set(), set(), set(), owner=OWNER, downgrade_owner=True)
        self.assertIn("owner's own first name (private fork; would BLOCK if public)", _whys(warns))
        self.assertEqual([], blocks, "confirmed private: a bare first name WARNs")

    def test_bare_first_name_blocks_when_public(self):
        tree = _tree(**{"notes.md": "Aldric ruled 2026-09-10: ship it.\n"})
        blocks, warns, _ = _scan(tree, owner=OWNER)
        self.assertIn("owner's own first name", _whys(blocks))
        self.assertEqual([], [w for w in warns if "first name" in w[2]])

    def test_full_name_still_blocks_and_is_not_double_counted_as_a_warn(self):
        tree = _tree(**{"notes.md": "Aldric Ashgrove ruled 2026-09-10: ship it.\n"})
        blocks, warns, _ = _scan(tree, owner=OWNER, full={"Aldric Ashgrove"})
        self.assertIn("contact full name", _whys(blocks))
        # the "Aldric" inside "Aldric Ashgrove" is already counted as the full-name BLOCK; the
        # first-name WARN tier must not also fire on that same occurrence (kept usable — see the
        # bigram_starts scoping in scan_items()).
        first_name_warns = [w for w in warns if w[1] == "Aldric"]
        self.assertEqual([], first_name_warns)

    def test_a_second_bare_mention_in_the_same_file_still_flags(self):
        tree = _tree(**{"notes.md": "Aldric Ashgrove ruled it. Aldric confirmed again later.\n"})
        blocks, warns, _ = _scan(tree, owner=OWNER)
        self.assertIn("owner's own first name", _whys(blocks))

    def test_no_owner_first_configured_means_no_hits(self):
        tree = _tree(**{"notes.md": "Aldric ruled 2026-09-10: ship it.\n"})
        blocks, warns, _ = _scan(tree, owner={"name": "Aldric Ashgrove", "first": ""})
        self.assertEqual([], [w for w in warns if "first name" in w[2]])

    def test_a_clean_file_carries_no_first_name_hit(self):
        tree = _tree(**{"notes.md": "The pipeline ran clean today, nothing to report.\n"})
        blocks, warns, _ = _scan(tree, owner=OWNER)
        self.assertEqual([], [w for w in warns if "first name" in w[2]])


class RetiredFacts(unittest.TestCase):
    def test_retired_literal_blocks(self):
        tree = _tree(**{"sweep.sh": "# background: $9.9M unicorns served, per the old deck\n"})
        blocks, warns, _ = _scan(tree, retired=RETIRED)
        self.assertIn("owner's own retired/honesty-guardrail fact", _whys(blocks))

    def test_retired_pattern_blocks(self):
        tree = _tree(**{"copy.md": "the new pipeline runs 100x faster than before\n"})
        blocks, warns, _ = _scan(tree, retired=RETIRED)
        whys = _whys(blocks)
        self.assertTrue(any("retired 100x claim" in w for w in whys))

    def test_no_retired_facts_configured_means_no_hits(self):
        tree = _tree(**{"copy.md": "the new pipeline runs 100x faster than before\n"})
        blocks, warns, _ = _scan(tree, retired=([], []))
        self.assertEqual([], blocks)

    def test_a_clean_file_carries_no_retired_hit(self):
        tree = _tree(**{"copy.md": "the new pipeline is faster than before\n"})
        blocks, warns, _ = _scan(tree, retired=RETIRED)
        self.assertEqual([], blocks)


if __name__ == "__main__":
    unittest.main()
