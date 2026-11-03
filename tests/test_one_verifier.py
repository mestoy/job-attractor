#!/usr/bin/env python3
"""Signing merge design (2026-10-03), invariants 6 and 7, and the plain-words diagnosis (G1, G7, G10 path).

7. ONE VERIFIER. `check_preview` has one authorization path: `record_decision.ledger_verifier`, bound to this
   install. Two verifiers are two ideas of who authorized what, so the origin-side `_ledger_keys` and
   `_mac_ok_any` are gone and no caller of either remains.
6. NO ENVIRONMENT VARIABLE reaches the gate. JOBKIT_LEDGER_KEYFILE and JOBKIT_LEDGER_KEYRING name an
   attacker's key and ring; a BUILD signed under them is refused.

Also pinned: `gate_empty_reason()` and `build_ruling_diagnosis()` exist (their callers in check_preview.py
and mail-draft.sh had lost the definitions in the merge), never return an empty sentence, and name the REAL
cause in terms of THIS install's key, never the pre-merge per-HOME key.
"""
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_partner_authorization import _Installs, legacy_mac  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

DIAG = r"""
import sys
sys.path.insert(0, sys.argv[1])
import check_preview as cp
print(repr(cp.build_ruling_diagnosis()))
print(repr(cp.gate_empty_reason()))
"""


class TestOneVerifier(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(SCRIPTS, "check_preview.py"), encoding="utf-8") as fh:
            self.src = fh.read()

    def test_the_second_verifier_is_gone(self):
        """G1. `grep -c "_mac_ok_any\\|_ledger_keys()" scripts/check_preview.py` is 0."""
        self.assertEqual(0, len(re.findall(r"_mac_ok_any|_ledger_keys\(\)", self.src)))
        self.assertNotRegex(self.src, r"(?m)^def _(ledger_key|mac_ok)\(")

    def test_every_authorization_goes_through_the_install_verifier(self):
        self.assertIn("_rd.ledger_verifier(", self.src)
        self.assertEqual(1, len(re.findall(r"ledger_verifier\(LEDGER", self.src)),
                         "more than one place builds a verifier: that is the second path again")

    def test_the_diagnosis_functions_exist_for_their_callers(self):
        self.assertRegex(self.src, r"(?m)^def gate_empty_reason\(")
        self.assertRegex(self.src, r"(?m)^def build_ruling_diagnosis\(")
        with open(os.path.join(SCRIPTS, "mail-draft.sh"), encoding="utf-8") as fh:
            self.assertIn("build_ruling_diagnosis", fh.read())


class TestNoEnvironmentVariableReachesTheGate(_Installs):
    def test_g7_an_attackers_keyfile_and_ring_in_the_environment_authorize_nothing(self):
        self.rule(self.a, "AlphaCo")
        evil = os.path.join(self.tmp, "evil")
        os.makedirs(evil, mode=0o700)
        chosen = b"c" * 64
        kf = os.path.join(evil, "attacker.key")
        with open(kf, "wb") as fh:
            fh.write(chosen)
        os.chmod(kf, 0o600)
        ring = os.path.join(evil, "ring")
        os.makedirs(ring)
        row = self.legacy_row("EvilCo", chosen)
        row["kid"] = "deadbeef"
        self.append(self.a, row)
        with open(os.path.join(ring, "ring.json"), "w", encoding="utf-8") as fh:
            json.dump({"keys": [{"kid": "deadbeef", "path": kf, "label": "evil"}]}, fh)
        got = self.rulings(self.a, extra_env={"JOBKIT_LEDGER_KEYFILE": kf, "JOBKIT_LEDGER_KEYRING": ring,
                                              "JOBKIT_LEDGER_KEYDIR": evil})
        self.assertNotIn("evilco", got)
        self.assertEqual({"alphaco"}, got)


class TestDiagnosisNamesTheRealCause(_Installs):
    def diag(self, root):
        r = subprocess.run([sys.executable, "-c", DIAG, os.path.join(root, "scripts")],
                           capture_output=True, text=True, env=self._env())
        self.assertEqual(0, r.returncode, r.stderr)
        lines = r.stdout.strip().splitlines()
        return eval(lines[-2]), eval(lines[-1])

    def test_a_healthy_install_with_a_matching_ruling_has_no_key_diagnosis(self):
        self.rule(self.a, "AlphaCo")
        key_diag, why = self.diag(self.a)
        self.assertEqual("", key_diag)
        self.assertTrue(why)

    def test_no_ledger_yet_is_the_normal_new_install_sentence(self):
        _diag, why = self.diag(self.a)
        self.assertIn("no ledger yet", why.lower())

    def test_rulings_signed_in_another_install_are_named_as_such(self):
        self.rule(self.b, "BetaCo")
        self.migrate(self.a)                       # A has its own key before B's rows are copied in
        with open(self.ledger(self.a), "w", encoding="utf-8") as fh:
            fh.write(open(self.ledger(self.b), encoding="utf-8").read())
        key_diag, why = self.diag(self.a)
        self.assertIn("another install", key_diag)
        self.assertIn("none verify", key_diag)
        self.assertNotIn("ledger_keys.py list", key_diag, "the diagnosis still points at the per-HOME key tool")
        self.assertEqual(key_diag, why)

    def test_a_missing_key_is_named_with_this_installs_fix(self):
        self.rule(self.a, "AlphaCo")
        for f in os.listdir(self.keydir):
            if f.endswith(".key"):
                os.remove(os.path.join(self.keydir, f))
        key_diag, why = self.diag(self.a)
        self.assertIn("signing key", key_diag)
        self.assertIn("--migrate", key_diag)
        self.assertEqual(key_diag, why)

    def test_unsigned_records_are_named_never_counted_as_rulings(self):
        r = self.run_hook(self.a, "FirstCo")                 # no key yet: recorded unsigned
        self.assertNotEqual(0, r.returncode)
        self.migrate(self.a)
        key_diag, why = self.diag(self.a)
        self.assertIn("unsigned", key_diag.lower())
        self.assertIn("authorize nothing", key_diag)
        self.assertEqual(set(), self.rulings(self.a))


if __name__ == "__main__":
    unittest.main()
