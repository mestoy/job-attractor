"""kit#159: the send gate used to proceed on a partial store. `blocked_keys_from_list()` read
the blocked list inside `except Exception: return set()`, so a file that EXISTS but cannot be
read (permission denied, a directory in its place, mid-sync) returned the exact same empty set a
fresh install with no blocked list gets -- every company then reads NEW, safe to proceed. A
missing file is still a fresh install and stays an empty set; only "exists but unreadable" must
now refuse loudly. Fixtures are fictional; runs as a real, unprivileged user, so chmod 000 is
skipped under root (root ignores file permissions).

ROUND 2 (3f's catch, score 72/FAIL): the helper-level tests below proved blocked_key_hit() and
blocked_keys_from_list() were fixed, but never drove the REAL `check_dup.py --send-gate` CLI
entry point end to end. That entry point calls prior_contact() -> _scan() -> search_file() BEFORE
the guarded blocked_key_hit() ever runs, and search_file()'s own open() had no guard at all: a
chmod-000 blocked-employers-list.md raised an uncaught PermissionError there, Python exited 1,
and mail-draft.sh read exit 1 as "BLOCKED -- blocked-list or strong duplicate" -- fails closed,
but tells the person the wrong reason, and the new exit 5 never fired in the realistic case.

ROUND 3 (3f's catch again): the round-2 class locked only the blocked list. #159 itself asked to
"test each store". The generated SendGateStoreUnreadable_* classes below loop the same subprocess
drive over every path in check_dup.SEND_GATE_STORES, read from the module itself so this can never
silently drift from what the gate actually depends on.
"""
import os
import _roots
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)
import screen_sweep  # noqa: E402
import check_dup  # noqa: E402

RUNNING_AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


# kit#159 asked to "test each store": SEND_GATE_STORES itself, read from check_dup.py, so this
# loop can never silently drift from whatever the gate actually depends on. 3f's review found the
# prior version of this class locked only the blocked list.
SEND_GATE_STORE_PATHS = sorted(check_dup.SEND_GATE_STORES)


def _make_send_gate_case(store_rel_path):
    @unittest.skipIf(RUNNING_AS_ROOT, "root ignores file permissions; chmod 000 would not refuse")
    class _Case(unittest.TestCase):
        """Drives the real `python3 scripts/check_dup.py --send-gate` entry point as a subprocess,
        not the helper functions alone -- the exact gap 3f's review found, now looped over every
        SEND_GATE_STORES path, not just the blocked list."""

        def setUp(self):
            self.tmp = tempfile.mkdtemp(dir=os.environ.get("TMPDIR"))
            self.path = os.path.join(self.tmp, store_rel_path)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                f.write("- Acme Robotics (blocked 2026-01-01): reason\n")
            os.chmod(self.path, 0o000)

        def tearDown(self):
            if os.path.exists(self.path):
                os.chmod(self.path, 0o644)  # so the tempdir can be cleaned up

        def _run(self, company):
            env = _roots.sandbox_env(self.tmp, JOBSEARCH_TEST="1")
            return subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_dup.py"), "--send-gate", company],
                                   capture_output=True, text=True, env=env, cwd=SCRIPTS)

        def test_an_unreadable_store_exits_5_not_1(self):
            p = self._run("Some Random Co")
            self.assertEqual(p.returncode, 5, (store_rel_path, p.stdout, p.stderr))

        def test_the_message_names_cannot_verify_not_blocked(self):
            p = self._run("Some Random Co")
            out = p.stdout + p.stderr
            self.assertIn("CANNOT VERIFY", out, store_rel_path)
            self.assertNotIn("VERDICT: 🔴 BLOCKED", out, store_rel_path)

        def test_a_readable_store_still_works_normally(self):
            os.chmod(self.path, 0o644)
            p = self._run("Some Random Co")
            self.assertEqual(p.returncode, 0, (store_rel_path, p.stdout, p.stderr))

        def test_a_missing_store_still_reads_as_new_not_a_refusal(self):
            # kit#159 (b), evidence-backed: none of the four SEND_GATE_STORES ship with the kit,
            # have a template, or get scaffolded by install.sh (confirmed against origin/main and
            # .gitignore) -- a MISSING file is the genuine fresh-install state, distinct from
            # "exists but broken", and must NOT refuse.
            os.chmod(self.path, 0o644)
            os.remove(self.path)
            p = self._run("Some Random Co")
            self.assertEqual(p.returncode, 0, (store_rel_path, p.stdout, p.stderr))
            self.assertIn("VERDICT: 🟢 NEW", p.stdout, store_rel_path)

        def test_bad_encoding_refuses_the_same_way_as_unreadable(self):
            # kit#159 (a): 3f's repro -- errors="ignore" silently dropped undecodable bytes and
            # returned a clean 🟢 NEW. Overwrite the (currently chmod-000) fixture with raw
            # undecodable bytes under a permission that CAN be read, so this isolates the
            # encoding path from the permission path.
            os.chmod(self.path, 0o644)
            with open(self.path, "wb") as fb:
                fb.write(b"## header\n\xff\xfe garbage bytes not utf8\n")
            p = self._run("Some Random Co")
            self.assertEqual(p.returncode, 5, (store_rel_path, p.stdout, p.stderr))
            out = p.stdout + p.stderr
            self.assertIn("CANNOT VERIFY", out, store_rel_path)
            self.assertNotIn("VERDICT: 🔴 BLOCKED", out, store_rel_path)
            self.assertNotIn("VERDICT: 🟢 NEW", out, store_rel_path)

    _Case.__name__ = _Case.__qualname__ = "SendGateStoreUnreadable_" + re.sub(r"\W+", "_", store_rel_path)
    return _Case


for _p in SEND_GATE_STORE_PATHS:
    _cls = _make_send_gate_case(_p)
    globals()[_cls.__name__] = _cls
del _p, _cls


@unittest.skipIf(RUNNING_AS_ROOT, "root ignores file permissions; chmod 000 would not refuse")
class BlockedListUnreadableRefusesLoudly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=os.environ.get("TMPDIR"))
        self.path = os.path.join(self.tmp, "blocked-employers-list.md")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("- Acme Robotics (blocked 2026-01-01): reason\n")
        os.chmod(self.path, 0o000)
        screen_sweep._BLOCKED_KEYS_CACHE.clear()

    def tearDown(self):
        os.chmod(self.path, 0o644)  # so the tempdir can be cleaned up

    def test_a_missing_file_still_returns_an_empty_set(self):
        missing = os.path.join(self.tmp, "does-not-exist.md")
        self.assertEqual(screen_sweep.blocked_keys_from_list(missing), set())

    def test_an_unreadable_existing_file_raises_instead_of_returning_empty(self):
        with self.assertRaises(screen_sweep.BlockedListUnreadable):
            screen_sweep.blocked_keys_from_list(self.path)

    def test_bulleted_content_that_parses_to_zero_warns_on_stderr(self):
        # kit#159 (c), #23's precedent: a store that READS FINE but parses to zero is a different
        # fact from a genuinely empty/missing one, and must be reported separately.
        os.chmod(self.path, 0o644)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("- this bullet is only reason words like blocked culture layoff always-on and more\n")
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        p = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {SCRIPTS!r}); import screen_sweep; "
             f"print(screen_sweep.blocked_keys_from_list({self.path!r}))"],
            capture_output=True, text=True)
        self.assertEqual(p.stdout.strip(), "set()")
        self.assertIn("zero blocked keys were extracted", p.stderr)

    def test_prose_only_content_with_no_bullets_does_not_warn(self):
        # A blank blocked list (headers/prose, no bullets yet) is a legitimate fresh-install shape,
        # not a parsing failure, and must not warn.
        os.chmod(self.path, 0o644)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("# Blocked employers\nNothing blocked yet.\n")
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        p = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {SCRIPTS!r}); import screen_sweep; "
             f"print(screen_sweep.blocked_keys_from_list({self.path!r}))"],
            capture_output=True, text=True)
        self.assertEqual(p.stdout.strip(), "set()")
        self.assertNotIn("zero blocked keys", p.stderr)

    def test_bad_encoding_raises_instead_of_silently_dropping_bytes(self):
        os.chmod(self.path, 0o644)
        with open(self.path, "wb") as fb:
            fb.write(b"- Acme Robotics (blocked): \xff\xfe not utf8\n")
        screen_sweep._BLOCKED_KEYS_CACHE.clear()
        with self.assertRaises(screen_sweep.BlockedListUnreadable):
            screen_sweep.blocked_keys_from_list(self.path)

    def test_check_dup_blocked_key_hit_propagates_the_refusal(self):
        real_bkfl = screen_sweep.blocked_keys_from_list

        def _boom(path=None):
            raise screen_sweep.BlockedListUnreadable("synthetic: permission denied")

        screen_sweep.blocked_keys_from_list = _boom
        try:
            with self.assertRaises(screen_sweep.BlockedListUnreadable):
                check_dup.blocked_key_hit("Acme Robotics")
        finally:
            screen_sweep.blocked_keys_from_list = real_bkfl


class MailDraftStopsOnAnyCheckDupRefusal(unittest.TestCase):
    """osascript/Mail do not exist on Linux, so this asserts the shell source directly, the same
    way tests/test_mail_draft_exit_codes.py does for mail-draft.sh's other exit codes."""

    def test_a_nonzero_check_dup_exit_other_than_1_or_3_now_stops_the_send(self):
        with open(os.path.join(SCRIPTS, "mail-draft.sh"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('"$_dc" != "0"', src)
        self.assertIn('"$_dc" != "1"', src)
        self.assertIn('"$_dc" != "3"', src)

    def test_bash_still_accepts_it(self):
        r = subprocess.run(["bash", "-n", os.path.join(SCRIPTS, "mail-draft.sh")],
                            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
