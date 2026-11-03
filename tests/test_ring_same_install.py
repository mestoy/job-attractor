#!/usr/bin/env python3
"""Signing merge design (2026-10-03), invariant 5: the ring widens KEYS, never INSTALLS.

Origin's ring (kit #149/#151) lets a person put a key they own back to work with `ledger_keys.py add`. On the
per-install model that must not reopen the cross-install hole: a ring entry carries the install it was added
in, the verifier consults the ring LAST, and a ring key verifies a row only when that entry was added in THIS
install, the row's `kid` is that key's id, and the key file sits outside the project tree.

Ported from origin's ring cases (add, list, stray, a ring key inside the project ignored) onto the
per-install key folder, plus the cross-install case that is new.
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_partner_authorization import _Installs  # noqa: E402


class _Ring(_Installs):
    def setUp(self):
        super().setUp()
        self.outside = os.path.join(self.tmp, "my-old-keys")
        os.makedirs(self.outside, mode=0o700)
        self.old_key = b"a" * 64
        self.old_keyfile = os.path.join(self.outside, "old.key")
        with open(self.old_keyfile, "wb") as fh:
            fh.write(self.old_key)
        os.chmod(self.old_keyfile, 0o600)

    def kid(self, key):
        import hashlib
        return hashlib.sha256(key).hexdigest()[:8]

    def lk(self, root, *args):
        env = self._env(root)
        return subprocess.run([sys.executable, os.path.join(root, "scripts", "ledger_keys.py"), *args],
                              capture_output=True, text=True, env=env, cwd=root)

    def old_row(self, company, key=None):
        key = key or self.old_key
        row = self.legacy_row(company, key)
        row["kid"] = self.kid(key)
        return row


class TestRingIsSameInstallOnly(_Ring):
    def test_a_key_added_in_this_install_verifies_its_rows_here(self):
        self.migrate(self.a)
        r = self.lk(self.a, "add", self.old_keyfile, "--label", "old laptop")
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.append(self.a, self.old_row("OldLaptopCo"))
        self.assertIn("oldlaptopco", self.rulings(self.a))

    def test_the_same_ring_entry_verifies_nothing_in_another_install_on_one_home(self):
        self.migrate(self.a)
        self.migrate(self.b)
        self.assertEqual(0, self.lk(self.a, "add", self.old_keyfile).returncode)
        row = self.old_row("OldLaptopCo")
        self.append(self.a, row)
        self.append(self.b, row)
        self.assertIn("oldlaptopco", self.rulings(self.a))
        self.assertNotIn("oldlaptopco", self.rulings(self.b), "a ring entry added in A verified a row in B")

    def test_an_entry_with_no_install_tag_verifies_nothing(self):
        """An origin-era manifest line (no `install`) widens nothing: it could have been added anywhere."""
        self.migrate(self.a)
        with open(os.path.join(self.keydir, "ring.json"), "w", encoding="utf-8") as fh:
            json.dump({"keys": [{"kid": self.kid(self.old_key), "path": self.old_keyfile, "label": "x"}]}, fh)
        self.append(self.a, self.old_row("OldLaptopCo"))
        self.assertNotIn("oldlaptopco", self.rulings(self.a))

    def test_a_ring_key_inside_the_project_tree_is_ignored(self):
        self.migrate(self.a)
        inside = os.path.join(self.a, "stolen.key")
        with open(inside, "wb") as fh:
            fh.write(self.old_key)
        r = self.lk(self.a, "add", inside)
        self.assertNotEqual(0, r.returncode, "the CLI accepted a key inside the project")
        # and a hand-written manifest cannot get around the CLI's refusal
        import hashlib
        a_id = hashlib.sha256(os.path.realpath(self.a).encode()).hexdigest()[:32]
        with open(os.path.join(self.keydir, "ring.json"), "w", encoding="utf-8") as fh:
            json.dump({"keys": [{"kid": self.kid(self.old_key), "path": inside, "install": a_id}]}, fh)
        self.append(self.a, self.old_row("InsideCo"))
        self.assertNotIn("insideco", self.rulings(self.a))

    def test_a_ring_key_whose_bytes_changed_after_it_was_added_is_ignored(self):
        self.migrate(self.a)
        self.assertEqual(0, self.lk(self.a, "add", self.old_keyfile).returncode)
        swapped = b"b" * 64
        with open(self.old_keyfile, "wb") as fh:
            fh.write(swapped)
        self.append(self.a, self.old_row("SwapCo", swapped))
        self.assertNotIn("swapco", self.rulings(self.a))

    def test_a_row_naming_a_different_kid_is_not_tried_against_the_ring_key(self):
        self.migrate(self.a)
        self.assertEqual(0, self.lk(self.a, "add", self.old_keyfile).returncode)
        row = self.old_row("WrongKidCo")
        row["kid"] = "00000000"
        self.append(self.a, row)
        self.assertNotIn("wrongkidco", self.rulings(self.a))

    def test_the_doctor_prints_one_ring_line_for_keys_added_here(self):
        """G10: one key section: this install's key status, then the ring line."""
        self.migrate(self.a)
        self.assertEqual(0, self.lk(self.a, "add", self.old_keyfile).returncode)
        p = subprocess.run([sys.executable, os.path.join(self.a, "scripts", "doctor.py")], cwd=self.a,
                           env=self._env(self.a), capture_output=True, text=True, timeout=180)
        sec = (p.stdout + p.stderr).split("[9] decision-ledger signing key", 1)[1].split("\n\n", 1)[0]
        self.assertIn("ring: 1 extra key added here", sec)
        self.assertEqual(1, sec.count("signing key ready"), sec)
        self.assertNotIn("decision ledger keys:", p.stdout + p.stderr, "the old per-HOME key report still prints")

    def test_an_install_key_is_never_listed_as_a_ring_stray(self):
        self.rule(self.a, "AlphaCo")
        r = self.lk(self.a, "list")
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertNotIn("STRAY", r.stdout, r.stdout)

    def test_the_ring_never_overrides_a_missing_install_key(self):
        """No install key means no verifier at all, ring or not: fail closed."""
        self.migrate(self.a)
        self.assertEqual(0, self.lk(self.a, "add", self.old_keyfile).returncode)
        self.append(self.a, self.old_row("OldLaptopCo"))
        for f in os.listdir(self.keydir):
            if f.endswith(".key"):
                os.remove(os.path.join(self.keydir, f))
        self.assertEqual(set(), self.rulings(self.a))


if __name__ == "__main__":
    unittest.main()
