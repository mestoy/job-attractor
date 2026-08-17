#!/usr/bin/env python3
"""T76: the SCREEN-GATE deal-breaker MATRIX and the HARD-INVARIANTS never-waived list must AGREE.

The matrix (documents/employer-criteria-matrix.md, section A) headers its rows "HARD VETOES — a NO on
any one is a NO, at every rung, never waived". The HARD-INVARIANTS never-waived line is the SHORT list
the warm (5-7) and referred (8-9) rungs actually screen against ("Deal-breakers ONLY"). If the matrix
names a hard veto the never-waived line omits, a warm or referred ask can be surfaced against a company
that trips a documented deal-breaker — the shorter list silently decides what those rungs are screened
against. scripts/check_rulings.py computes the divergence and exits 1 when the two lists disagree.

RED before the T76 reconciliation (three matrix rows — recurring layoffs, always-on culture, US hiring
in his function — are in the matrix's HARD VETOES but absent from the never-waived line). GREEN once the
two are reconciled per Michael's ruling (widen the never-waived list, or narrow the matrix's claim)."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


class ScreenGateVetoConsistency(unittest.TestCase):
    def test_matrix_hard_vetoes_and_never_waived_list_agree(self):
        r = subprocess.run(
            [sys.executable, os.path.join(REPO, "scripts", "check_rulings.py")],
            capture_output=True, text=True, cwd=REPO)
        self.assertEqual(
            r.returncode, 0,
            "SCREEN-GATE matrix HARD VETOES and the HARD-INVARIANTS never-waived list disagree "
            "(check_rulings.py exit %d). The warm/referred rungs screen 'Deal-breakers ONLY' against "
            "the shorter list, so any veto missing from it is unenforced at those rungs:\n%s%s"
            % (r.returncode, r.stdout, r.stderr))


if __name__ == "__main__":
    unittest.main()
