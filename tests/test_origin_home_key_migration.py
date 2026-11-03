#!/usr/bin/env python3
"""Signing merge design (2026-10-03), section 4 and DoD G8, G11: a partner's rulings signed under origin's
per-HOME key keep verifying after ONE `--migrate`, nothing is re-signed, and the doctor says to keep the old
key file because the tagged rows verify THROUGH it.

The fixture is origin's world: a ledger of N BUILD rows MACed under a scratch per-HOME key (half carry origin's
`kid`, half are older rows without one) plus 3 unsigned records. HOME, the key folder and the legacy key all
point into the scratch dir, so no real key is read or made.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_partner_authorization import _Installs  # noqa: E402

SECTION = "[9] decision-ledger signing key"
COMPANIES = ["Alpha Co", "Beta Co", "Gamma Co", "Delta Co", "Epsilon Co", "Zeta Co"]
UNSIGNED = ["Unsigned One", "Unsigned Two", "Unsigned Three"]


class TestOriginHomeKeyMigration(_Installs):
    def setUp(self):
        super().setUp()
        self.legacy_key = os.urandom(32).hex().encode()
        self.write_legacy()
        os.makedirs(os.path.dirname(self.ledger(self.a)), exist_ok=True)
        kid = hashlib.sha256(self.legacy_key).hexdigest()[:8]
        for i, co in enumerate(COMPANIES):
            row = self.legacy_row(co, self.legacy_key)
            if i % 2 == 0:
                row["kid"] = kid                      # origin writes kid on rows since #149; older rows have none
            self.append(self.a, row)
        for co in UNSIGNED:
            self.append(self.a, {"ts": "2026-09-30T00:00:00+00:00", "session": "x", "question": f"{co} SCORECARD",
                                 "header": "Ruling", "answer": "Build it", "ruling": "BUILD", "company": co,
                                 "source": "posttooluse-hook", "key_state": "unsigned: no key"})

    def write_legacy(self):
        with open(self.legacy_keyfile, "wb") as fh:
            fh.write(self.legacy_key)

    def doctor_key_section(self, root):
        p = subprocess.run([sys.executable, os.path.join(root, "scripts", "doctor.py")], cwd=root,
                           env=self._env(root), capture_output=True, text=True, timeout=180)
        out = p.stdout + p.stderr
        return out.split(SECTION, 1)[1].split("\n\n", 1)[0] if SECTION in out else out

    def folder(self):
        return sorted(os.listdir(self.keydir))

    def test_one_migrate_keeps_every_origin_signed_ruling_and_ignores_the_unsigned(self):
        self.migrate(self.a)
        files = self.folder()
        self.assertEqual(3, len(files), files)
        self.assertEqual([".json", ".key", ".migrated"], sorted(os.path.splitext(f)[1] for f in files))
        self.assertEqual({c.lower() for c in COMPANIES}, self.rulings(self.a))
        sec = self.doctor_key_section(self.a)
        self.assertIn("✅", sec)
        self.assertIn("keep ~/.jobsearch-ledger-key", sec)
        self.assertIn("%d of your earlier rulings verify through it" % len(COMPANIES), sec)

    def test_a_second_migrate_changes_nothing_and_nothing_is_re_signed(self):
        self.migrate(self.a)
        before = {f: open(os.path.join(self.keydir, f), "rb").read() for f in self.folder()}
        ledger_before = open(self.ledger(self.a), "rb").read()
        self.migrate(self.a)
        self.assertEqual(before, {f: open(os.path.join(self.keydir, f), "rb").read() for f in self.folder()})
        self.assertEqual(ledger_before, open(self.ledger(self.a), "rb").read(), "a migrate rewrote the ledger")
        self.assertEqual({c.lower() for c in COMPANIES}, self.rulings(self.a))

    def test_without_the_legacy_key_file_the_tagged_rows_stop_verifying_and_the_doctor_says_so(self):
        self.migrate(self.a)
        os.remove(self.legacy_keyfile)
        self.assertEqual(set(), self.rulings(self.a), "tagged rows verified without the legacy key's bytes")
        sec = self.doctor_key_section(self.a)
        self.assertIn("🔴", sec)
        self.assertIn("~/.jobsearch-ledger-key is gone", sec)
        self.assertIn("%d earlier rulings no longer verify" % len(COMPANIES), sec)
        self.assertIn("restore", sec.lower())
        ledger_before = open(self.ledger(self.a), "rb").read()
        self.write_legacy()                           # restoring the file brings every one back, with no re-sign
        self.assertEqual({c.lower() for c in COMPANIES}, self.rulings(self.a))
        self.assertEqual(ledger_before, open(self.ledger(self.a), "rb").read())

    def test_a_ruling_given_after_the_migration_signs_with_the_install_key(self):
        self.migrate(self.a)
        r = self.run_hook(self.a, "NewCo")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual({c.lower() for c in COMPANIES} | {"newco"}, self.rulings(self.a))
        last = self.rows(self.a)[-1]
        self.assertTrue(last.get("mac") and last.get("kid"), last)

    def test_the_cross_install_twin_refuses_every_row(self):
        """Another install on the same HOME, migrated BEFORE the ledger is copied in, believes none of them."""
        shutil.rmtree(os.path.dirname(self.ledger(self.b)), ignore_errors=True)
        os.makedirs(os.path.dirname(self.ledger(self.b)))
        self.migrate(self.b)
        shutil.copy(self.ledger(self.a), self.ledger(self.b))
        self.assertEqual(set(), self.rulings(self.b))
        self.migrate(self.a)
        self.assertEqual({c.lower() for c in COMPANIES}, self.rulings(self.a))
        self.assertEqual(set(), self.rulings(self.b), "install B believed rulings tagged in install A")


if __name__ == "__main__":
    unittest.main()
