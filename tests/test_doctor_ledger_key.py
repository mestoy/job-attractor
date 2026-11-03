#!/usr/bin/env python3
"""doctor.py section [9]: the decision-ledger signing key (kit #121, second security review N4).

A key problem stops every ruling write and blocks every gated send, so doctor has to name it: a
green line when the key is ready, a one-line --migrate fix when it is missing, and a one-line
permissions fix when the key folder or file is unsafe. It never prints key material.

Each sandbox carries its own COPY of record_decision.py with KEYDIR pinned inside the sandbox, so
no run reads or creates the real account's key folder.
"""
import hashlib
import os
import _roots
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(KIT, "scripts")
SECTION = "[9] decision-ledger signing key"


def _sandbox():
    root = tempfile.mkdtemp(prefix="doctor-ledger-key-")
    os.makedirs(os.path.join(root, "scripts"))
    os.makedirs(os.path.join(root, "documents"))
    kc = os.path.join(SCRIPTS, "kit_config.py")
    if not os.path.exists(kc):
        kc = os.path.join(SCRIPTS, "kit_config.example.py")
    shutil.copy(kc, os.path.join(root, "scripts", "kit_config.py"))
    shutil.copy(os.path.join(SCRIPTS, "doctor.py"), os.path.join(root, "scripts", "doctor.py"))
    # record_decision.py imports origin's ledger libraries (never-mint state, write-once append); a sandbox
    # without them cannot even load it, so they ship with it.
    for lib in ("ledger_keys.py", "ledger_write.py"):
        shutil.copy(os.path.join(SCRIPTS, lib), os.path.join(root, "scripts", lib))
    keydir = os.path.join(root, "keys")
    with open(os.path.join(SCRIPTS, "record_decision.py"), encoding="utf-8") as fh:
        src = fh.read()
    src = re.sub(r"(?m)^KEYDIR = .*$", "KEYDIR = " + repr(keydir), src, count=1)
    with open(os.path.join(root, "scripts", "record_decision.py"), "w", encoding="utf-8") as fh:
        fh.write(src)
    kid = hashlib.sha256(os.path.realpath(root).encode("utf-8")).hexdigest()[:32]
    return root, keydir, kid


def _env(root):
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    _roots.point_env(env, root)
    return env


def _doctor(root):
    p = subprocess.run([sys.executable, os.path.join(root, "scripts", "doctor.py")], cwd=root,
                       env=_env(root), capture_output=True, text=True, timeout=120)
    return p.stdout + p.stderr


def _section(out):
    return out.split(SECTION, 1)[1].split("\n\n", 1)[0] if SECTION in out else ""


def _migrate(root):
    return subprocess.run([sys.executable, os.path.join(root, "scripts", "record_decision.py"), "--migrate"],
                          input="", cwd=root, env=_env(root), capture_output=True, text=True, timeout=60)


class TestDoctorLedgerKey(unittest.TestCase):
    def setUp(self):
        self.root, self.keydir, self.kid = _sandbox()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_ready_is_green_and_never_prints_the_key(self):
        self.assertEqual(0, _migrate(self.root).returncode)
        out = _doctor(self.root)
        sec = _section(out)
        self.assertIn("✅", sec)
        key = open(os.path.join(self.keydir, self.kid + ".key"), "rb").read().strip().decode()
        self.assertNotIn(key, out, "doctor printed key material")

    def test_missing_names_migrate_in_one_line(self):
        sec = _section(_doctor(self.root))
        self.assertIn("⚠️", sec)
        self.assertIn("record_decision.py --migrate", sec)
        self.assertFalse(os.path.exists(self.keydir), "doctor created the key folder")

    def test_a_loose_key_folder_is_unsafe_with_a_chmod_fix(self):
        os.makedirs(self.keydir)
        os.chmod(self.keydir, 0o777)
        sec = _section(_doctor(self.root))
        self.assertIn("🔴", sec)
        self.assertIn("chmod 700", sec)
        self.assertEqual([], os.listdir(self.keydir), "doctor wrote into an unsafe folder")

    def test_a_symlinked_key_folder_is_unsafe(self):
        target = tempfile.mkdtemp(prefix="doctor-ledger-target-")
        self.addCleanup(shutil.rmtree, target, True)
        os.chmod(target, 0o700)
        os.symlink(target, self.keydir)
        sec = _section(_doctor(self.root))
        self.assertIn("🔴", sec)
        self.assertIn("symlink", sec)

    def test_a_readable_key_file_is_unsafe_with_a_chmod_fix(self):
        self.assertEqual(0, _migrate(self.root).returncode)
        kf = os.path.join(self.keydir, self.kid + ".key")
        os.chmod(kf, 0o644)
        out = _doctor(self.root)
        sec = _section(out)
        self.assertIn("🔴", sec)
        self.assertIn("chmod 600", sec)
        self.assertNotIn(open(kf, "rb").read().strip().decode(), out)


if __name__ == "__main__":
    unittest.main()
