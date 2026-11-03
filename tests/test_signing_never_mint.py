#!/usr/bin/env python3
"""Signing merge design (2026-10-03), invariants 2 and 3: a key is created ONLY by `--migrate`, never by a
gate read or by the hook's write, and never beside a signed ledger whose key is gone; a ruling given with
no usable key is RECORDED unsigned (proxy 70), authorizes nothing, is counted nowhere, and is never signed
later.

Why this is proven by running: the 2026-09-27 mint (3ab14c77) was a gate READ that created a fresh key
next to a signed ledger and orphaned every earlier ruling. V49's own verifier did the same through
`install_key(create=True)`. Each case below plants the state that produced that harm and requires that
no file appears under the key folder.

Ported from origin's keyring tests onto the per-install key path (kit #149, #151): never-mint on an
unreadable ledger, never-mint beside signed rows, the unsigned-row record with its loud line, and the
unwritable-key-folder case.
"""
import json
import os
import stat
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_partner_authorization import _Installs, legacy_mac  # noqa: E402


class _Signed(_Installs):
    """An install whose ledger already holds rows signed under a legacy per-HOME key."""

    def setUp(self):
        super().setUp()
        self.legacy_key = os.urandom(32).hex().encode()

    def write_legacy_keyfile(self):
        with open(self.legacy_keyfile, "wb") as fh:
            fh.write(self.legacy_key)

    def migrate_raw(self, root):
        return subprocess.run([sys.executable, os.path.join(root, "scripts", "record_decision.py"), "--migrate"],
                              input="", capture_output=True, text=True, env=self._env())

    def key_folder_files(self):
        return sorted(os.listdir(self.keydir)) if os.path.exists(self.keydir) else []

    def install_keyfile(self, root):
        import hashlib
        return os.path.join(self.keydir, hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:32] + ".key")


class TestNeverMint(_Signed):
    # (a) a signed ledger, no key folder, no legacy key: a gate READ creates nothing and authorizes nothing.
    def test_a_gate_read_never_creates_a_key_beside_a_signed_ledger(self):
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        self.assertEqual(set(), self.rulings(self.a))
        self.assertEqual([], self.key_folder_files(), "a gate read minted a key")
        self.assertFalse(os.path.exists(self.keydir), "a gate read created the key folder")

    # (b) --migrate on the same state creates nothing and says what to restore.
    def test_b_migrate_refuses_beside_a_signed_ledger_without_the_legacy_key(self):
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        r = self.migrate_raw(self.a)
        self.assertNotEqual(0, r.returncode, "--migrate minted beside signed rulings with no legacy key")
        self.assertIn("orphan", r.stderr)
        self.assertIn("restore", r.stderr.lower())
        self.assertIn(self.legacy_keyfile, r.stderr)
        self.assertEqual([], self.key_folder_files(), "--migrate created key material it then refused")

    # (c) --migrate with the legacy key present mints ONCE and tags; a second run changes nothing.
    def test_c_migrate_with_the_legacy_key_mints_once_and_a_second_run_changes_nothing(self):
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        self.write_legacy_keyfile()
        r = self.migrate_raw(self.a)
        self.assertEqual(0, r.returncode, r.stderr)
        files = self.key_folder_files()
        self.assertEqual(3, len(files), files)                       # .key, .migrated, .legacy.json
        self.assertEqual({".key", ".migrated", ".json"}, {os.path.splitext(f)[1] for f in files})
        before = {f: open(os.path.join(self.keydir, f), "rb").read() for f in files}
        self.assertIn("oldco", self.rulings(self.a))
        r2 = self.migrate_raw(self.a)
        self.assertEqual(0, r2.returncode, r2.stderr)
        self.assertEqual(files, self.key_folder_files())
        self.assertEqual(before, {f: open(os.path.join(self.keydir, f), "rb").read() for f in files},
                         "a second --migrate rewrote key material or the snapshot")
        self.assertIn("oldco", self.rulings(self.a))

    # (c2) the legacy key file is present but verifies NONE of the signed rows: still no mint.
    def test_c2_a_legacy_key_that_verifies_nothing_does_not_unlock_the_mint(self):
        self.append(self.a, self.legacy_row("OldCo", os.urandom(32).hex().encode()))
        self.write_legacy_keyfile()                                   # a different key than the rows'
        r = self.migrate_raw(self.a)
        self.assertNotEqual(0, r.returncode, "--migrate minted beside rows the legacy key does not verify")
        self.assertEqual([], self.key_folder_files())

    # (d) a ledger with one damaged line that mentions a mac: --migrate creates nothing (origin's never-mint).
    def test_d_a_damaged_line_mentioning_a_mac_stops_the_mint(self):
        os.makedirs(os.path.dirname(self.ledger(self.a)), exist_ok=True)
        with open(self.ledger(self.a), "a", encoding="utf-8") as fh:
            fh.write('{"ts": "2026-08-01", "ruling": "BUILD", "company": "TornCo", "mac": "abc\n')
        self.write_legacy_keyfile()
        r = self.migrate_raw(self.a)
        self.assertNotEqual(0, r.returncode, "--migrate minted beside a ledger it could not read in full")
        self.assertIn("cannot read every line", r.stderr)
        self.assertEqual([], self.key_folder_files())
        self.assertEqual(set(), self.rulings(self.a))

    # (e) the hook's own write never mints either: a first-ever ruling with no key is recorded unsigned.
    def test_e_the_hooks_write_never_mints_on_an_empty_ledger(self):
        r = self.run_hook(self.a, "FirstCo")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("recorded UNSIGNED", r.stderr)
        self.assertIn("--migrate", r.stderr)
        self.assertEqual([], self.key_folder_files(), "the hook minted a key")
        rows = self.rows(self.a)
        self.assertEqual(1, len(rows), rows)
        self.assert_unsigned_record(rows[0], "key")
        self.assertEqual(set(), self.rulings(self.a))


class TestUnsignedRecordNeverAuthorizes(_Signed):
    # PORTED (origin: test_signed_rows_and_no_key_never_mints_writes_an_unsigned_row_and_says_so).
    def test_signed_rows_and_no_key_never_mints_and_writes_an_unsigned_row_and_says_so(self):
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        r = self.run_hook(self.a, "NewCo")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("recorded UNSIGNED", r.stderr)
        self.assertIn("authorizes nothing", r.stderr)
        self.assertEqual([], self.key_folder_files(), "the hook minted beside signed rulings")
        rows = self.rows(self.a)
        self.assertEqual(["OldCo", "NewCo"], [x["company"] for x in rows])
        self.assertIn("mac", rows[0], "the earlier signed row was altered")
        self.assert_unsigned_record(rows[1], "key")
        self.assertEqual(set(), self.rulings(self.a))

    # PORTED (origin: test_an_unwritable_key_folder_gives_an_explicit_unsigned_row_and_a_loud_line).
    @unittest.skipIf(os.geteuid() == 0, "root writes through any folder mode")
    def test_an_unwritable_key_folder_gives_an_explicit_unsigned_row_and_a_loud_line(self):
        os.makedirs(self.keydir)
        os.chmod(self.keydir, 0o500)                                   # private, but nothing can be created
        self.addCleanup(os.chmod, self.keydir, 0o700)
        m = self.migrate_raw(self.a)
        self.assertNotEqual(0, m.returncode, "--migrate reported success with no key written")
        self.assertIn("could not create", m.stderr)
        self.assertEqual([], os.listdir(self.keydir))
        r = self.run_hook(self.a, "NewCo")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("recorded UNSIGNED", r.stderr)
        rows = self.rows(self.a)
        self.assertEqual(1, len(rows), rows)
        self.assert_unsigned_record(rows[0], "key")
        self.assertEqual(set(), self.rulings(self.a))

    def _signed_then_unsigned_then_restored(self):
        """A healthy install, one signed BUILD, then a BUILD recorded while the key was away, then the key back.
        Returns (install keyfile, rows)."""
        self.rule(self.a, "AlphaCo")
        kf = self.install_keyfile(self.a)
        key = open(kf, "rb").read()
        os.remove(kf)
        r = self.run_hook(self.a, "GhostCo")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("recorded UNSIGNED", r.stderr)
        fd = os.open(kf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
        rows = self.rows(self.a)
        self.assertEqual(["AlphaCo", "GhostCo"], [x["company"] for x in rows])
        self.assert_unsigned_record(rows[1], "key")
        return kf, rows

    # NEW: a plain BUILD for a named company, unsigned, is present, authorizes nothing and is counted nowhere.
    def test_an_unsigned_build_is_recorded_never_authorizing_and_never_counted(self):
        kf, rows = self._signed_then_unsigned_then_restored()
        self.assertEqual("BUILD", rows[1]["ruling"])
        self.assertEqual({"alphaco"}, self.rulings(self.a), "the unsigned BUILD authorized a send")
        sys.path.insert(0, os.path.join(self.a, "scripts"))
        try:
            import importlib
            lk = importlib.import_module("ledger_keys")
            rep = lk.ledger_report(self.ledger(self.a), kf)
        finally:
            sys.path.pop(0)
            sys.modules.pop("ledger_keys", None)
        self.assertEqual(1, rep["hook_rows"], rep)
        self.assertEqual(0, rep["unverified"], rep)
        self.assertEqual(1, rep["build_hook_rows"], rep)
        self.assertEqual(1, rep["build_verified"], rep)
        self.assertEqual(1, rep["unsigned"], rep)

    # NEW: a rewrite can never sign an unsigned record later (a-signed-field-can-never-be-backfilled).
    def test_a_rewrite_refuses_to_add_a_mac_to_an_unsigned_record(self):
        kf, rows = self._signed_then_unsigned_then_restored()
        ledger = self.ledger(self.a)
        before = open(ledger, "rb").read()
        key = open(kf, "rb").read()
        sys.path.insert(0, os.path.join(self.a, "scripts"))
        try:
            import importlib
            lw = importlib.import_module("ledger_write")

            def sign_the_ghost(rs):
                for r in rs:
                    if r.get("company") == "GhostCo":
                        r["mac"] = legacy_mac(r, key)
                        r.pop("unsigned_reason", None)
                return rs
            with self.assertRaises(lw.WriteOnceError):
                lw.guarded_rewrite(ledger, kf, sign_the_ghost)
        finally:
            sys.path.pop(0)
            for m in ("ledger_write", "ledger_keys"):
                sys.modules.pop(m, None)
        self.assertEqual(before, open(ledger, "rb").read(), "the refused rewrite touched the ledger")
        self.assertEqual({"alphaco"}, self.rulings(self.a))


if __name__ == "__main__":
    unittest.main()
