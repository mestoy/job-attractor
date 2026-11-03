"""Installing mints NO per-HOME key and NO ring, and creates THIS install's key only inside the account key folder.

Signing merge (2026-10-03, design section 5, adapted from origin's "install mints no key"): V49's install.sh
runs `record_decision.py --migrate` at install and update time, so the install key and the one-shot legacy
snapshot exist before the first ruling. What must still never happen at install:
  * a per-HOME key (~/.jobsearch-ledger-key) is made, or a stray *.key appears in HOME or the install folder;
  * a key appears beside an unreadable or signed ledger it could orphan (that is `--migrate`'s refusal, pinned
    in tests/test_signing_never_mint.py).

⛔ WHY THIS IS PROVEN BY RUNNING AND NOT BY READING: a mint that MOVED is not a mint that WENT. This runs the
real installer with the account home redirected into a sandbox and then looks for the keys that should, and
should not, exist. The account home comes from the system user list, never from HOME, so the sandbox patches
pwd.getpwuid through a test-only sitecustomize on PYTHONPATH. WITHOUT that the install would write its key into
the REAL account folder (it did, once, before this test patched it; 3 files were removed by hand).

⛔ AN EMPTY CHECK PASSES, so two things hold this test up:
  * a CONTROL that plants a key in the same sandbox and requires the detector to find it.
  * an assertion that the install RAN TO ITS END, and that the install's own key DID appear where it belongs:
    an installer that aborts on line 10 also leaves nothing behind.
"""
import os
import shutil
import subprocess
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import scratch_root  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(REPO, "install.sh")
SANDBOX_ROOT = os.path.join(scratch_root(), "test-install-nomint")
KEY_NAME = ".jobsearch-ledger-key"
RING_NAME = ".jobsearch-ledger-keys"


def _key_artifacts(root):
    """Every signing-key artifact under `root` that is NOT the account key folder: the per-HOME key, any
    *.key file elsewhere. Deliberately WIDER than the one path the installer might have used."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        if RING_NAME in dirnames:
            dirnames.remove(RING_NAME)            # the account key folder is checked on its own, below
        for f in filenames:
            if f == KEY_NAME or f.endswith(".key"):
                found.append(os.path.join(dirpath, f))
    return sorted(found)


SHIM = (
    "import os, pwd\n"
    "class _E:\n"
    "    pw_dir = os.environ['JOBKIT_TEST_ACCOUNT_HOME']\n"
    "pwd.getpwuid = lambda uid: _E()\n"
)


class TestInstallMintsNoKey(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SANDBOX_ROOT, ignore_errors=True)
        self.home = os.path.join(SANDBOX_ROOT, "home")
        self.target = os.path.join(SANDBOX_ROOT, "target")
        os.makedirs(self.home)
        os.makedirs(self.target)

    def tearDown(self):
        # /tmp is RAM here and leftovers have killed sessions; this lives on disk and still goes.
        shutil.rmtree(SANDBOX_ROOT, ignore_errors=True)

    def _install(self):
        env = dict(os.environ)
        env["HOME"] = self.home
        shim = os.path.join(SANDBOX_ROOT, "shim")
        os.makedirs(shim, exist_ok=True)
        with open(os.path.join(shim, "sitecustomize.py"), "w", encoding="utf-8") as fh:
            fh.write(SHIM)
        env["JOBKIT_TEST_ACCOUNT_HOME"] = self.home          # test-only: the product reads no such variable
        env["PYTHONPATH"] = shim + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(["bash", INSTALL, self.target],
                              capture_output=True, text=True, env=env, timeout=600)

    def test_the_detector_finds_a_key_that_is_there(self):
        """CONTROL. Plant a key the way the keyring would and require the detector to see it.

        If this ever fails, the no-mint result below means nothing: it is a detector looking at
        nothing and reporting all clear."""
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        try:
            import ledger_keys
        finally:
            sys.path.pop(0)
        planted = os.path.join(self.home, KEY_NAME)
        ledger_keys.mint_key(planted)
        self.assertTrue(os.path.exists(planted), "the control could not plant a key to look for")
        self.assertIn(planted, _key_artifacts(self.home),
                      "the detector missed a real key sitting in the sandbox HOME")

    def test_a_fresh_install_makes_its_own_key_and_no_per_home_key(self):
        r = self._install()
        # The install RAN TO ITS END. Without this, an early abort would pass the checks below.
        self.assertIn("Checking the install", r.stdout + r.stderr,
                      "the installer did not reach its final step, so an absent key proves nothing:\n"
                      + (r.stdout + r.stderr)[-2000:])
        for root, what in ((self.home, "the person's HOME"), (self.target, "the install folder")):
            self.assertEqual(
                [], _key_artifacts(root),
                "installing left a signing key outside the account key folder in %s. Only the per-install "
                "key, in the account key folder, may exist after an install." % what)
        self.assertFalse(os.path.exists(os.path.join(self.home, KEY_NAME)), "install minted a per-HOME key")
        keydir = os.path.join(self.home, RING_NAME)
        names = sorted(os.listdir(keydir)) if os.path.isdir(keydir) else []
        self.assertEqual([".json", ".key", ".migrated"], sorted(os.path.splitext(n)[1] for n in names),
                         "install did not create exactly this install's key, marker and snapshot: %s" % names)
        self.assertEqual(1, len({n.split(".")[0] for n in names}), "files for more than one install: %s" % names)
        self.assertFalse(os.path.exists(os.path.join(keydir, "ring.json")), "install created a key ring")


if __name__ == "__main__":
    unittest.main()
