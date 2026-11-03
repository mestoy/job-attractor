"""kit #96 (2026-09-12): the upstream watcher must FAIL LOUD. A fetch that fails is exit 2 plus a
stderr line naming the remote and git's own error, never a quiet log line and exit 0.

Fixtures are local bare clones in a temp dir; no network, no live store is read or written.
"""
import os
import _roots
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPT = os.path.join(KIT, "scripts", "watch_kit.py")

LOCK_ERR = ("error: cannot lock ref 'refs/remotes/kit/main': is at "
            "4562dd1000000000000000000000000000000000 but expected "
            "30ecd98000000000000000000000000000000000")


def git(cwd, *args):
    return subprocess.run(("git",) + args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class WatchKitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.up = os.path.join(self.tmp, "job-attractor-kit.git")
        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        git(seed, "init", "-q", "-b", "main")
        git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "one")
        git(seed, "clone", "-q", "--bare", seed, self.up)
        self.user = os.path.join(self.tmp, "user")
        git(self.tmp, "clone", "-q", "-o", "kit", self.up, self.user)
        os.makedirs(os.path.join(self.user, "documents", "state"))
        self.env = _roots.sandbox_env(self.user)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_watch(self, *args, env=None):
        return subprocess.run([sys.executable, SCRIPT, "--repo", self.user, *args],
                              capture_output=True, text=True, env=env or self.env)

    def test_dead_remote_is_exit_2_and_names_what_failed(self):
        git(self.user, "remote", "set-url", "kit", os.path.join(self.tmp, "gone-job-attractor-kit.git"))
        r = self.run_watch()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("git fetch kit failed", r.stderr)
        self.assertIn("does not appear to be a git repository", r.stderr)

    def test_ref_lock_error_is_exit_2_and_stderr_carries_the_git_error(self):
        # A fake git on PATH that fails a fetch the way the 09-08 log did, and passes everything else through.
        shim = os.path.join(self.tmp, "bin")
        os.makedirs(shim)
        real = shutil.which("git")
        p = os.path.join(shim, "git")
        with open(p, "w") as f:
            f.write("#!/bin/sh\nfor a in \"$@\"; do [ \"$a\" = fetch ] && { echo \"%s\" >&2; exit 1; }; done\n"
                    "exec %s \"$@\"\n" % (LOCK_ERR, real))
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        env = dict(self.env, PATH=shim + os.pathsep + self.env["PATH"])
        r = self.run_watch(env=env)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("cannot lock ref", r.stderr)
        alert = os.path.join(self.user, "documents", "state", "kit-watch-alert.txt")
        self.assertTrue(os.path.exists(alert), "a failed fetch must leave a distinct alert state")

    def test_behind_upstream_is_exit_1_and_current_is_exit_0(self):
        r = self.run_watch()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        w = os.path.join(self.tmp, "writer")
        git(self.tmp, "clone", "-q", self.up, w)
        git(w, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "two")
        git(w, "push", "-q", "origin", "main")
        r = self.run_watch()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("1 commit", r.stdout)
        self.assertEqual(r.stderr, "")
        self.assertFalse(os.path.exists(os.path.join(self.user, "documents", "state", "kit-watch-alert.txt")))


if __name__ == "__main__":
    unittest.main()
