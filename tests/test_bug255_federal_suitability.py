"""BUG-255 (seat 98's third hit on the writer-path class of bug, after BUG-246/BUG-247):
seed_employers.py had no keyword category for a federal-suitability/Public-Trust/security-
clearance drop reason, so a card like Tanggulan Federal's (a categorical hard filter per the owner's ruling
on the Tanggulan Federal VA req, HARD-INVARIANTS.md 2026-09-10) fell through every keyword tier and
inherited whatever stale section heading it happened to sit under (filter 8 "PE-owned").

Also checked, per the ask, whether the SCREENING path (catching a NEW candidate before it
ever reaches the blocked list) had the same gap: `check_screen_gate.INDUSTRY_VETO` had no
clearance/suitability terms at all -- a real, separate gap, now closed alongside the writer.

Fixtures are fictional (never a real company from the private repo, per the PII rule this
test suite runs under).
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(KIT, "scripts"))

import seed_employers  # noqa: E402
import check_screen_gate  # noqa: E402
import reconcile_findings  # noqa: E402


FIXTURE = """\
**⛔ Filter 8: PE-owned**

- **FictionalIntegrator** (govtech/federal, 2026-09-10). DROP, a fictional ruling: the Sr \
Product Manager VA role requires Public Trust and the candidate would not qualify for a \
federal suitability determination. Applies to any federal req, not the company's \
commercial work.
- **FictionalContractor** (govtech/federal, 2026-09-10). DROP: the role requires an active \
security clearance at the Secret level.
"""


class Bug255SeedEmployersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        )
        self.tmp.write(FIXTURE)
        self.tmp.close()
        self._orig_src = seed_employers.SRC
        seed_employers.SRC = self.tmp.name

    def tearDown(self):
        seed_employers.SRC = self._orig_src
        os.unlink(self.tmp.name)

    def test_a_public_trust_federal_suitability_reads_filter_13_not_pe(self):
        entities, _notes, _parked = seed_employers.scan()
        row = entities["fictionalintegrator"]
        self.assertEqual(row["filter"], 13)
        self.assertNotEqual(row["filter"], 8)
        self.assertIn("Federal suitability", row["filter_label"])

    def test_b_security_clearance_wording_also_reads_filter_13(self):
        entities, _notes, _parked = seed_employers.scan()
        row = entities["fictionalcontractor"]
        self.assertEqual(row["filter"], 13)


class Bug255FiltersLabelTests(unittest.TestCase):
    def test_filter_13_exists_with_a_real_label(self):
        self.assertIn(13, reconcile_findings.FILTERS)
        self.assertIn("Federal suitability", reconcile_findings.FILTERS[13])


class Bug255ScreenGateVetoTests(unittest.TestCase):
    """The SCREENING path (a candidate not yet on the blocked list) -- checked per the ask
    rather than assumed clean, and found to have no clearance/suitability terms at all.

    ⚠️ 2026-09-11: INDUSTRY_VETO now ships EMPTY. His ruling -- the kit ships the mechanism,
    never anybody's values -- and a clearance requirement is a value: plenty of people WANT
    federal work. So these tests supply the clearance patterns and prove the MECHANISM still
    catches them, which is what BUG-255 was actually about. The patterns themselves are kept
    in kit_config as the documented worked example, and the last test here proves they are
    still there, so the fix survives as content even though it no longer fires by default.
    """

    CLEARANCE = [r"public trust", r"federal suitability", r"security clearance"]

    def setUp(self):
        self._saved = check_screen_gate.INDUSTRY_VETO
        check_screen_gate.INDUSTRY_VETO = self.CLEARANCE

    def tearDown(self):
        check_screen_gate.INDUSTRY_VETO = self._saved

    def test_a_public_trust_is_caught_at_screen_time(self):
        hits = check_screen_gate.veto_hits(
            "Fictional Federal Co", "the role requires Public Trust clearance"
        )
        self.assertTrue(hits)

    def test_b_federal_suitability_is_caught_at_screen_time(self):
        hits = check_screen_gate.veto_hits(
            "Fictional Federal Co", "candidates must pass a federal suitability review"
        )
        self.assertTrue(hits)

    def test_c_security_clearance_is_caught_at_screen_time(self):
        hits = check_screen_gate.veto_hits(
            "Fictional Federal Co", "an active security clearance is required"
        )
        self.assertTrue(hits)

    def test_d_a_company_with_none_of_the_terms_is_unaffected(self):
        hits = check_screen_gate.veto_hits(
            "Fictional Fabrics Co", "a remote-first fictional textiles company"
        )
        self.assertFalse(hits)

    def test_e_the_clearance_patterns_survive_as_the_documented_example(self):
        """BUG-255's real content is the PATTERNS and the reasoning behind them. They no
        longer ship active, so they have to survive as the worked example -- otherwise a copy
        ruling quietly deletes a fix, which is the thing this whole change refused to do."""
        import os
        cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "scripts", "kit_config.py")
        with open(cfg, encoding="utf-8") as fh:
            src = fh.read()
        low = src.lower()
        for term in ("public trust", "clearance"):
            self.assertIn(term, low,
                          "BUG-255's %r pattern is gone from kit_config entirely -- it was "
                          "meant to move to the worked example, not to be deleted" % term)
        self.assertIn("BUG-255", src,
                      "the reasoning that distinguishes a federal-suitability seat from a "
                      "defense mission must stay findable")


if __name__ == "__main__":
    unittest.main()
