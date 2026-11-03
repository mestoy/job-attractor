"""kit#168/#172: cli_call() only checked `command -v timeout`, and stock macOS ships neither
GNU `timeout` nor Homebrew's `gtimeout` -- SWEEP_TIMEOUT silently became a no-op with zero
message. Fix: also try `gtimeout`; if neither exists, print a one-time stderr warning naming
the gap. No watchdog (bash background+sleep+kill) -- warning-only, per the go.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPT = os.path.join(KIT, "scripts", "sweep_segments.sh")


class TheSweepWarnsWhenNoTimeoutBinaryExists(unittest.TestCase):
    def tree(self, td):
        """A repo with the sweep script and a bin/ dir that has bun but NEITHER timeout binary --
        PATH is set to bin/ + /usr/bin + /bin, and this fixture never adds `timeout`/`gtimeout`
        symlinks into bin/, so `command -v` genuinely finds neither on a real Linux/macOS box.
        We can't strip a REAL host's own /usr/bin/timeout, so this only proves the code path;
        the "no binary at all" case is exercised by a direct PATH override below instead.
        """
        repo = os.path.join(td, "tree")
        os.makedirs(os.path.join(repo, "scripts"), exist_ok=True)
        os.makedirs(os.path.join(repo, "documents"), exist_ok=True)
        os.makedirs(os.path.join(repo, "bin"), exist_ok=True)
        shutil.copyfile(SCRIPT, os.path.join(repo, "scripts", "sweep_segments.sh"))
        bun = '#!/usr/bin/env bash\necho \'{"results":[]}\'\n'
        path = os.path.join(repo, "bin", "bun")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(bun)
        os.chmod(path, 0o755)
        return repo

    def sweep(self, repo, path_override):
        e = {"PATH": path_override, "HOME": os.environ.get("HOME", "/tmp")}
        e["SWEEP_PAUSE"] = "0"
        e["SWEEP_BACKOFF"] = "0"
        return subprocess.run(["bash", os.path.join(repo, "scripts", "sweep_segments.sh"), "payments"],
                              cwd=repo, env=e, capture_output=True, text=True, timeout=60)

    def test_a_no_timeout_or_gtimeout_prints_a_warning_once(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.tree(td)
            # A PATH carrying ONLY bin/ (bun, python3, bash's own builtins) and /bin for coreutils
            # minus a coreutils dir that has timeout -- simplest real way to guarantee neither
            # `timeout` nor `gtimeout` resolves is a curated PATH with just what's needed.
            minimal = os.path.join(td, "minimal-bin")
            os.makedirs(minimal, exist_ok=True)
            for srcdir in ("/usr/bin", "/bin"):
                if not os.path.isdir(srcdir):
                    continue
                for name in os.listdir(srcdir):
                    if name in ("timeout", "gtimeout"):
                        continue
                    dest = os.path.join(minimal, name)
                    if os.path.exists(dest):
                        continue
                    try:
                        os.symlink(os.path.join(srcdir, name), dest)
                    except OSError:
                        pass
            path_override = os.path.join(repo, "bin") + os.pathsep + minimal
            done = self.sweep(repo, path_override)
            said = done.stdout + done.stderr
            self.assertRegex(said, r"(?i)no timeout.*(binary|available)|SWEEP_TIMEOUT.*not enforced")
            # exactly one warning line, not one per call
            self.assertEqual(said.lower().count("not enforced"), 1, said)


if __name__ == "__main__":
    unittest.main()
