"""kit#167/#169: sweep_segments.sh's segment dispatch was five hard-coded bash arrays and a
`case "$SEG"` list, closed to the owner's own five segment names. A partner's real segments.md/
kit_config.SEGMENTS lanes (e.g. "product-owner-healthcare") always hit "unknown segment", even
though kit_config.py already ships `--segments` and `--segment-queries <slug>` CLI modes meant
for exactly this (mail-draft.sh already reads kit_config.py the same direct way).

sweep_segments.sh shells out to `bun`, which this container may not have, so these tests replace
the CLI with a one-line bash stub (same pattern test_app_sync.py's TheSweepSurvivesAFailure uses)
and check that the segment DISPATCH works, not that a real network call happens.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPT = os.path.join(KIT, "scripts", "sweep_segments.sh")

FICTIONAL_KIT_CONFIG = '''
SEGMENT_SLUGS = ["product-owner-healthcare"]
SEGMENTS = {"product-owner-healthcare": ["product owner healthcare claims",
                                          "product owner prior authorization"]}


def _as_shell():
    return ""


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--segments":
        print("\\n".join(SEGMENT_SLUGS))
    elif len(sys.argv) > 2 and sys.argv[1] == "--segment-queries":
        print("\\n".join(SEGMENTS.get(sys.argv[2], [])))
    else:
        print(_as_shell())
'''


class TheSweepReadsPartnerSegments(unittest.TestCase):
    def tree(self, td, kit_config=None):
        repo = os.path.join(td, "tree")
        os.makedirs(os.path.join(repo, "scripts"), exist_ok=True)
        os.makedirs(os.path.join(repo, "documents"), exist_ok=True)
        os.makedirs(os.path.join(repo, "bin"), exist_ok=True)
        shutil.copyfile(SCRIPT, os.path.join(repo, "scripts", "sweep_segments.sh"))
        if kit_config is not None:
            with open(os.path.join(repo, "scripts", "kit_config.py"), "w", encoding="utf-8") as fh:
                fh.write(kit_config)
        bun = ('#!/usr/bin/env bash\n'
               'echo "$@" >> "$CALLS_LOG"\n'
               'echo \'{"results":[]}\'\n')
        path = os.path.join(repo, "bin", "bun")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(bun)
        os.chmod(path, 0o755)
        return repo

    def sweep(self, repo, segment, calls_log):
        e = dict(os.environ)
        e["PATH"] = os.path.join(repo, "bin") + os.pathsep + "/usr/bin" + os.pathsep + "/bin"
        e["SWEEP_PAUSE"] = "0"
        e["SWEEP_BACKOFF"] = "0"
        e["CALLS_LOG"] = calls_log
        return subprocess.run(["bash", os.path.join(repo, "scripts", "sweep_segments.sh"), segment],
                              cwd=repo, env=e, capture_output=True, text=True, timeout=60)

    def test_a_partner_segment_slug_is_no_longer_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.tree(td, kit_config=FICTIONAL_KIT_CONFIG)
            calls_log = os.path.join(td, "calls.txt")
            open(calls_log, "w").close()
            done = self.sweep(repo, "product-owner-healthcare", calls_log)
            said = done.stdout + done.stderr
            self.assertNotIn("unknown segment", said, said)
            self.assertEqual(done.returncode, 0, said)

    def test_b_the_partner_segments_own_queries_are_used(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.tree(td, kit_config=FICTIONAL_KIT_CONFIG)
            calls_log = os.path.join(td, "calls.txt")
            open(calls_log, "w").close()
            self.sweep(repo, "product-owner-healthcare", calls_log)
            with open(calls_log, encoding="utf-8") as fh:
                calls = fh.read()
            self.assertIn("product owner healthcare claims", calls)
            self.assertIn("product owner prior authorization", calls)

    def test_c_with_no_kit_config_the_owners_own_segments_still_work(self):
        # No regression: absent a kit_config.py (or one without --segments), the original
        # five hard-coded segments must still dispatch exactly as before.
        with tempfile.TemporaryDirectory() as td:
            repo = self.tree(td, kit_config=None)
            calls_log = os.path.join(td, "calls.txt")
            open(calls_log, "w").close()
            done = self.sweep(repo, "payments", calls_log)
            said = done.stdout + done.stderr
            self.assertNotIn("unknown segment", said, said)
            self.assertEqual(done.returncode, 0, said)
            with open(calls_log, encoding="utf-8") as fh:
                calls = fh.read()
            self.assertIn("product manager payments", calls)


if __name__ == "__main__":
    unittest.main()
