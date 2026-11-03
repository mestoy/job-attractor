#!/usr/bin/env python3
"""Kit issue #121: a BUILD ruling signed in a partner's OWN install authorizes a send from it.

One kit install per partner. Each test builds real installs (a copy of scripts/ plus documents/)
in a temp dir and drives them the way production does: the PostToolUse hook runs as a subprocess
with CLAUDE_PROJECT_DIR set by the harness, and the send-side check imports the install's
check_preview exactly as mail-draft.sh's BUILD gate heredoc does.

What went wrong before the fix, each reproduced in a scratch clone on 2026-09-15:
  1. The ledger path came from CLAUDE_PROJECT_DIR first, so a send run from a session rooted
     anywhere else read THAT root's ledger and refused the partner's own ruling.
  2. The same precedence let another install's ledger authorize this install's send.
  3. The HMAC key sat at one path per HOME, so a signed row copied from one install's ledger into
     another's verified there.

HOME, the key directory and the legacy key file all point into the temp dir, so no real key is
ever read or created. The one exception is the opt-in live check at the bottom, which reads a
real ledger and key only when both are named in the environment.
"""
import hashlib
import hmac
import json
import os
import _roots
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

LEGACY_FIELDS = ("ts", "session", "question", "header", "answer", "ruling", "company", "source")


def legacy_mac(row, key):
    """An INDEPENDENT copy of the pre-#121 scheme, so the tests do not grade production with itself."""
    payload = json.dumps({f: row.get(f, "") for f in LEGACY_FIELDS},
                         sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


GATE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from check_preview import _build_rulings
print(json.dumps(sorted(_build_rulings())))
"""


class _Installs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kit121-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.keydir = os.path.join(self.home, ".jobsearch-ledger-keys")
        self.legacy_keyfile = os.path.join(self.home, ".jobsearch-ledger-key")
        self.a = self._install("a")
        self.b = self._install("b")

    def _install(self, name):
        root = os.path.join(self.tmp, name)
        shutil.copytree(SCRIPTS, os.path.join(root, "scripts"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        # The key dir is pinned by editing the KEYDIR line in this sandbox COPY, the only override
        # production honors (security review L1). The JOBKIT_LEDGER_KEYDIR env set in _env is ignored
        # by the fixed code; it only keeps a run against the pre-fix code inside the scratch HOME.
        rd = os.path.join(root, "scripts", "record_decision.py")
        with open(rd, encoding="utf-8") as fh:
            src = fh.read()
        src = re.sub(r"(?m)^KEYDIR = .*$", "KEYDIR = " + repr(self.keydir), src, count=1)
        with open(rd, "w", encoding="utf-8") as fh:
            fh.write(src)
        kc = os.path.join(root, "scripts", "kit_config.py")
        if not os.path.exists(kc):
            shutil.copy(os.path.join(SCRIPTS, "kit_config.example.py"), kc)
        os.makedirs(os.path.join(root, "documents"))
        return root

    def _env(self, project_dir=None):
        env = dict(os.environ, HOME=self.home, JOBKIT_LEDGER_KEYDIR=self.keydir,
                   JOBKIT_LEDGER_KEYFILE=self.legacy_keyfile)
        env.pop("JOBKIT_LEDGER_PATH", None)
        env.pop("CLAUDE_PROJECT_DIR", None)
        if project_dir:
            _roots.point_env(env, project_dir)
        return env

    def ledger(self, root):
        return os.path.join(root, "documents", "decision-ledger.jsonl")

    def rows(self, root):
        p = self.ledger(root)
        if not os.path.exists(p):
            return []
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

    def migrate(self, root):
        """install.sh's step: `record_decision.py --migrate` creates THIS install's key once and takes the
        one-shot legacy snapshot. Signing merge design (2026-10-03), invariant 3: the hook and the gate
        never create a key, so every install in these tests is migrated the way install.sh does it."""
        r = subprocess.run([sys.executable, os.path.join(root, "scripts", "record_decision.py"), "--migrate"],
                           input="", capture_output=True, text=True, env=self._env())
        self.assertEqual(0, r.returncode, r.stderr)
        return r

    def assert_unsigned_record(self, row, reason_has):
        """Proxy 70 (2026-10-03): a ruling given with no usable key is RECORDED, never an authorization.
        The shape is fixed: no `mac` field at all, no `kid`, and an `unsigned_reason` sentence."""
        self.assertNotIn("mac", row, row)
        self.assertNotIn("kid", row, row)
        self.assertIn(reason_has.lower(), str(row.get("unsigned_reason", "")).lower(), row)

    def run_hook(self, root, company, session_root=None):
        """The harness firing THIS install's PostToolUse hook on a real picker answer."""
        q = f"{company} SCORECARD · Senior PM. Build or skip?"
        payload = {"session_id": "s-" + company, "tool_name": "AskUserQuestion",
                   "tool_input": {"questions": [{"question": q, "header": "Ruling",
                                                 "options": [{"label": "Build it", "description": "x"},
                                                             {"label": "Skip", "description": "y"}]}]},
                   "tool_response": {"answers": {q: "Build it"}}}
        return subprocess.run([sys.executable, os.path.join(root, "scripts", "record_decision.py")],
                              input=json.dumps(payload), capture_output=True, text=True,
                              env=self._env(session_root or root))

    def rule(self, root, company, session_root=None):
        self.migrate(root)                  # the key exists before the first ruling, as after install.sh
        r = self.run_hook(root, company, session_root)
        self.assertEqual(0, r.returncode, r.stderr)
        rows = [json.loads(l) for l in open(self.ledger(root), encoding="utf-8") if l.strip()]
        self.assertEqual(company, rows[-1]["company"], "fixture: the hook did not scope the ruling")
        return rows[-1]

    def rulings(self, root, session_root=None, extra_env=None):
        """What `root`'s send gate authorizes, run the way mail-draft.sh runs it."""
        env = self._env(session_root)
        env.update(extra_env or {})
        r = subprocess.run([sys.executable, "-c", GATE, os.path.join(root, "scripts")],
                           capture_output=True, text=True, env=env)
        self.assertEqual(0, r.returncode, r.stderr)
        return set(json.loads(r.stdout.strip().splitlines()[-1]))

    def append(self, root, row):
        with open(self.ledger(root), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def legacy_row(self, company, key):
        row = {"ts": "2026-08-01T00:00:00+00:00", "session": "old", "question": f"{company} SCORECARD",
               "header": "Ruling", "answer": "Build it", "ruling": "BUILD", "company": company,
               "source": "posttooluse-hook"}
        row["mac"] = legacy_mac(row, key)
        return row


class TestOwnInstallAuthorizes(_Installs):
    def test_a_ruling_signed_in_a_fresh_install_authorizes_a_send_there(self):
        self.rule(self.a, "AlphaCo")
        self.assertIn("alphaco", self.rulings(self.a))

    def test_the_send_still_sees_its_own_ruling_from_a_session_rooted_elsewhere(self):
        """THE #121 SYMPTOM. mail-draft.sh run from a Claude session rooted at another folder."""
        self.rule(self.a, "AlphaCo")
        self.assertIn("alphaco", self.rulings(self.a, session_root=self.b))

    def test_the_hook_writes_to_its_own_install_whatever_the_session_root(self):
        self.rule(self.a, "AlphaCo", session_root=self.b)
        self.assertFalse(os.path.exists(self.ledger(self.b)), "the ruling landed in another install")
        self.assertIn("alphaco", self.rulings(self.a))


class TestForeignAndForgedRulingsRefused(_Installs):
    def test_another_installs_ledger_never_authorizes_this_install(self):
        self.rule(self.b, "BetaCo")
        self.assertNotIn("betaco", self.rulings(self.a, session_root=self.b))

    def test_a_signed_row_copied_between_installs_on_one_home_is_refused(self):
        row = self.rule(self.b, "BetaCo")
        self.rule(self.a, "AlphaCo")          # A has a key of its own and a genuine ruling
        self.append(self.a, row)
        got = self.rulings(self.a)
        self.assertIn("alphaco", got)
        self.assertNotIn("betaco", got)

    def test_a_forged_row_is_refused(self):
        self.rule(self.a, "AlphaCo")
        row = dict(self.legacy_row("GammaCo", b"0" * 64), mac="deadbeef")
        self.append(self.a, row)
        self.assertNotIn("gammaco", self.rulings(self.a))

    def test_a_row_signed_with_a_guessed_key_is_refused(self):
        self.rule(self.a, "AlphaCo")
        self.append(self.a, self.legacy_row("GammaCo", b"0" * 64))
        self.assertNotIn("gammaco", self.rulings(self.a))

    def test_deleting_the_install_key_fails_closed(self):
        self.rule(self.a, "AlphaCo")
        for f in os.listdir(self.keydir):
            os.remove(os.path.join(self.keydir, f))
        self.assertEqual(set(), self.rulings(self.a))

    def test_each_install_has_its_own_key_outside_the_install(self):
        self.rule(self.a, "AlphaCo")
        self.rule(self.b, "BetaCo")
        keys = sorted(f for f in os.listdir(self.keydir) if f.endswith(".key"))
        self.assertEqual(2, len(keys), keys)
        blobs = {open(os.path.join(self.keydir, k), "rb").read() for k in keys}
        self.assertEqual(2, len(blobs), "two installs share one key")
        for k in keys:
            mode = stat.S_IMODE(os.stat(os.path.join(self.keydir, k)).st_mode)
            self.assertEqual(0o600, mode, oct(mode))
        for root in (self.a, self.b):
            self.assertFalse(os.path.realpath(self.keydir).startswith(os.path.realpath(root) + os.sep))


class TestLegacyRulingsStayVerifiable(_Installs):
    def setUp(self):
        super().setUp()
        self.legacy_key = os.urandom(32).hex().encode()
        with open(self.legacy_keyfile, "wb") as fh:
            fh.write(self.legacy_key)

    def test_rulings_signed_with_the_old_home_key_still_authorize(self):
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        self.migrate(self.a)                  # Update Kit: the snapshot is taken while the legacy key is present
        self.assertIn("oldco", self.rulings(self.a))
        self.rule(self.a, "AlphaCo")          # a new ruling after migration
        self.assertEqual({"oldco", "alphaco"}, self.rulings(self.a))

    def test_a_legacy_row_copied_in_after_migration_is_refused(self):
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        self.migrate(self.a)                                # migration snapshot taken here
        self.assertIn("oldco", self.rulings(self.a))
        self.append(self.a, self.legacy_row("LateCo", self.legacy_key))
        self.assertNotIn("lateco", self.rulings(self.a))

    def test_a_tampered_snapshot_accepts_nothing_new(self):
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        self.migrate(self.a)
        self.rulings(self.a)
        late = self.legacy_row("LateCo", self.legacy_key)
        self.append(self.a, late)
        snaps = [f for f in os.listdir(self.keydir) if f.endswith(".legacy.json")]
        self.assertEqual(1, len(snaps), snaps)
        p = os.path.join(self.keydir, snaps[0])
        doc = json.load(open(p, encoding="utf-8"))
        doc["macs"].append(late["mac"])
        json.dump(doc, open(p, "w", encoding="utf-8"))
        got = self.rulings(self.a)
        self.assertNotIn("lateco", got)
        self.assertNotIn("oldco", got, "a snapshot whose tag no longer verifies must be ignored whole")


class TestChatRulingResolvesThisInstallsBoard(_Installs):
    """record_chat_ruling.py scoped a typed ruling against the board under CLAUDE_PROJECT_DIR while
    writing it to its own install's ledger, so a session opened in another folder matched the
    wrong board: this install's company resolved to nothing, and a company from the other
    folder's board could scope a signed BUILD row here."""

    def _board(self, root, company, boss):
        with open(os.path.join(root, "documents", "green-board.md"), "w", encoding="utf-8") as fh:
            fh.write("| # | Company | Boss | Lane |\n|---|---|---|---|\n"
                     f"| 1 | {company} | {boss} | fintech |\n")

    def chat(self, root, text, session_root):
        self.migrate(root)
        r = subprocess.run([sys.executable, os.path.join(root, "scripts", "record_chat_ruling.py")],
                           input=json.dumps({"session_id": "s-chat", "prompt": text}),
                           capture_output=True, text=True, env=self._env(session_root))
        self.assertEqual(0, r.returncode, r.stderr)
        p = self.ledger(root)
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []

    def setUp(self):
        super().setUp()
        self._board(self.a, "Acme Corp", "Jane Doe")
        self._board(self.b, "Globex", "Hank Scorpio")

    def test_a_session_opened_elsewhere_matches_this_installs_board(self):
        rows = self.chat(self.a, "build the email to Acme Corp", session_root=self.b)
        self.assertTrue(rows, "the typed ruling wrote no row")
        self.assertEqual(("BUILD", "Acme Corp"), (rows[-1]["ruling"], rows[-1]["company"]))
        self.assertIn("acme corp", self.rulings(self.a))

    def test_the_other_folders_board_never_scopes_a_ruling_here(self):
        self.chat(self.a, "build the email to Globex", session_root=self.b)
        self.assertNotIn("globex", self.rulings(self.a))
        self.assertFalse(os.path.exists(self.ledger(self.b)), "the ruling landed in another install")


class TestSecurityReviewFindings(_Installs):
    """Non-author security review of ff58fed (2026-09-15), each finding driven as its reproduction."""

    def setUp(self):
        super().setUp()
        self.legacy_key = os.urandom(32).hex().encode()
        with open(self.legacy_keyfile, "wb") as fh:
            fh.write(self.legacy_key)

    @staticmethod
    def _id(root):
        return hashlib.sha256(os.path.realpath(root).encode("utf-8")).hexdigest()[:32]

    def _kd(self, suffix, root=None):
        return os.path.join(self.keydir, self._id(root or self.a) + suffix)

    def _private_keydir(self):
        os.makedirs(self.keydir, exist_ok=True)
        os.chmod(self.keydir, 0o700)

    def _late_legacy_row_after_migration(self):
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        self.migrate(self.a)                                      # snapshot taken here
        self.assertIn("oldco", self.rulings(self.a))
        self.rule(self.a, "NewCo")
        self.append(self.a, self.legacy_row("LateCo", self.legacy_key))
        self.assertNotIn("lateco", self.rulings(self.a))

    # M2: the snapshot is taken at most once per install; a recreated key never re-takes it.
    def test_m2_deleting_only_the_key_never_re_admits_a_late_legacy_row(self):
        self._late_legacy_row_after_migration()
        os.remove(self._kd(".key"))
        got = self.rulings(self.a)
        self.assertNotIn("lateco", got)
        self.assertNotIn("newco", got, "a ruling signed under the deleted key still verified")

    def test_m2_deleting_the_key_and_the_snapshot_never_re_snapshots(self):
        self._late_legacy_row_after_migration()
        os.remove(self._kd(".key"))
        os.remove(self._kd(".legacy.json"))
        got = self.rulings(self.a)
        self.assertNotIn("lateco", got)
        self.assertNotIn("oldco", got)

    # M1 (window shrunk, limit documented): install.sh takes the snapshot at update time.
    def test_m1_migrate_takes_the_snapshot_before_any_session_runs(self):
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        r = subprocess.run([sys.executable, os.path.join(self.a, "scripts", "record_decision.py"),
                            "--migrate"], input="", capture_output=True, text=True, env=self._env())
        self.assertEqual(0, r.returncode, r.stderr)
        self.append(self.a, self.legacy_row("LateCo", self.legacy_key))
        got = self.rulings(self.a)
        self.assertIn("oldco", got)
        self.assertNotIn("lateco", got)

    def test_a_legacy_key_swapped_after_migration_verifies_nothing(self):
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        self.migrate(self.a)
        self.assertIn("oldco", self.rulings(self.a))
        chosen = os.urandom(32).hex().encode()
        with open(self.legacy_keyfile, "wb") as fh:
            fh.write(chosen)
        self.append(self.a, self.legacy_row("EvilCo", chosen))
        got = self.rulings(self.a)
        self.assertNotIn("evilco", got)
        self.assertNotIn("oldco", got, "the snapshot must be pinned to the legacy key it was taken with")

    # L1: no environment variable chooses the key a send is verified with.
    def test_l1_the_key_dir_env_var_grants_nothing(self):
        self.rule(self.a, "AlphaCo")
        evil = os.path.join(self.tmp, "evil-keys")
        os.makedirs(evil, mode=0o700)
        chosen = b"f" * 64
        with open(os.path.join(evil, self._id(self.a) + ".key"), "wb") as fh:
            fh.write(chosen)
        os.chmod(os.path.join(evil, self._id(self.a) + ".key"), 0o600)
        self.append(self.a, self.legacy_row("EvilCo", chosen))
        got = self.rulings(self.a, extra_env={"JOBKIT_LEDGER_KEYDIR": evil})
        self.assertNotIn("evilco", got)
        self.assertIn("alphaco", got)

    # L2: the key dir must be a real, private directory owned by this account.
    def test_l2_a_symlinked_key_dir_is_refused(self):
        loose = os.path.join(self.tmp, "loose")
        os.makedirs(loose)
        os.chmod(loose, 0o777)
        os.symlink(loose, self.keydir)
        self.run_hook(self.a, "AlphaCo")
        self.assertEqual([], os.listdir(loose), "key material was written through the symlink")
        self.assertEqual(set(), self.rulings(self.a))
        # --migrate, the one place a key is created, refuses the symlinked folder too.
        m = subprocess.run([sys.executable, os.path.join(self.a, "scripts", "record_decision.py"), "--migrate"],
                           input="", capture_output=True, text=True, env=self._env())
        self.assertNotEqual(0, m.returncode, "--migrate created a key through a symlinked folder")
        self.assertEqual([], os.listdir(loose), "--migrate wrote key material through the symlink")

    def test_l2_a_group_or_world_writable_key_dir_is_refused(self):
        os.makedirs(self.keydir)
        os.chmod(self.keydir, 0o777)
        self.run_hook(self.a, "AlphaCo")
        self.assertEqual([], os.listdir(self.keydir))
        self.assertEqual(set(), self.rulings(self.a))

    def test_l2_a_new_key_dir_is_created_private(self):
        self.rule(self.a, "AlphaCo")
        self.assertEqual(0o700, stat.S_IMODE(os.lstat(self.keydir).st_mode))

    # L3: the snapshot temp file never follows a planted symlink.
    def test_l3_a_planted_snapshot_temp_symlink_is_not_followed(self):
        self._private_keydir()
        victim = os.path.join(self.tmp, "victim.txt")
        with open(victim, "w", encoding="utf-8") as fh:
            fh.write("original")
        os.symlink(victim, self._kd(".legacy.json.tmp"))
        self.append(self.a, self.legacy_row("OldCo", self.legacy_key))
        self.migrate(self.a)
        self.assertIn("oldco", self.rulings(self.a))
        self.assertEqual("original", open(victim, encoding="utf-8").read())
        self.assertFalse(os.path.islink(self._kd(".legacy.json")))

    # L4: an empty key file stops SIGNING with a plain message. UPDATED under proxy 70 (2026-10-03,
    # signing merge design, invariant 2): the ruling is still RECORDED, unsigned and with the reason, so
    # no decision is lost silently; it carries no mac at all, so it can never satisfy a gate.
    def test_l4_an_empty_key_file_stops_ruling_writes_with_a_message(self):
        self._private_keydir()
        kf = self._kd(".key")
        open(kf, "wb").close()
        os.chmod(kf, 0o600)
        with open(os.path.join(self.a, "documents", "green-board.md"), "w", encoding="utf-8") as fh:
            fh.write("| # | Company | Boss | Lane |\n|---|---|---|---|\n| 1 | Acme Corp | Jane Doe | fintech |\n")
        r = self.run_hook(self.a, "AlphaCo")
        c = subprocess.run([sys.executable, os.path.join(self.a, "scripts", "record_chat_ruling.py")],
                           input=json.dumps({"session_id": "s", "prompt": "build the email to Acme Corp"}),
                           capture_output=True, text=True, env=self._env(self.a))
        for res in (r, c):
            self.assertNotEqual(0, res.returncode)
            self.assertIn("recorded UNSIGNED", res.stderr)
            self.assertIn("authorizes nothing", res.stderr)
            self.assertIn("empty", res.stderr)
        rows = self.rows(self.a)
        self.assertEqual(["AlphaCo", "Acme Corp"], [x["company"] for x in rows], rows)
        for row in rows:
            self.assert_unsigned_record(row, "empty")
            self.assertEqual("BUILD", row["ruling"])
        self.assertEqual(set(), self.rulings(self.a), "an unsigned record authorized a send")
        self.assertEqual(0, os.path.getsize(kf), "the empty key file was overwritten")


PWD_FAIL = ("import pwd\n"
            "def _no_entry(*a, **k):\n"
            "    raise KeyError('getpwuid(): uid not found')\n"
            "pwd.getpwuid = _no_entry\n")
RUN_SCRIPT = ("import runpy, sys\n"
              "sys.argv = sys.argv[1:]\n"
              "runpy.run_path(sys.argv[0], run_name='__main__')\n")


class TestSecondReviewFindings(_Installs):
    """Second non-author security review of 44facf6 (2026-09-15): N1 and N3."""

    def setUp(self):
        super().setUp()
        self.legacy_key = os.urandom(32).hex().encode()
        with open(self.legacy_keyfile, "wb") as fh:
            fh.write(self.legacy_key)

    @staticmethod
    def _id(root):
        return hashlib.sha256(os.path.realpath(root).encode("utf-8")).hexdigest()[:32]

    # N1: no passwd entry means no key folder at all. Never HOME, never a relative "~".
    def _unpinned(self, name):
        """An install whose record_decision.py keeps `KEYDIR = None`, so the account-home lookup runs.
        Every process that touches it patches pwd.getpwuid to raise first, so the real home is never
        consulted; HOME is scratch or unset."""
        root = os.path.join(self.tmp, name)
        shutil.copytree(SCRIPTS, os.path.join(root, "scripts"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        kc = os.path.join(root, "scripts", "kit_config.py")
        if not os.path.exists(kc):
            shutil.copy(os.path.join(SCRIPTS, "kit_config.example.py"), kc)
        os.makedirs(os.path.join(root, "documents"))
        return root

    def _no_pwd(self, root, env, cwd, hook_payload=None):
        if hook_payload is None:
            cmd = [sys.executable, "-c", PWD_FAIL + GATE, os.path.join(root, "scripts")]
            return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)
        cmd = [sys.executable, "-c", PWD_FAIL + RUN_SCRIPT,
               os.path.join(root, "scripts", "record_decision.py")]
        return subprocess.run(cmd, input=json.dumps(hook_payload), capture_output=True, text=True,
                              env=env, cwd=cwd)

    @staticmethod
    def _payload(company):
        q = f"{company} SCORECARD · Senior PM. Build or skip?"
        return {"session_id": "s-" + company, "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": q, "header": "Ruling",
                                              "options": [{"label": "Build it", "description": "x"}]}]},
                "tool_response": {"answers": {q: "Build it"}}}

    def _assert_refused(self, root, env, cwd):
        """No home entry: the gate authorizes nothing and the writer SIGNS nothing. UPDATED under proxy 70
        (2026-10-03, signing merge design, invariant 2): the ruling is recorded unsigned with the reason,
        never dropped silently, and that record satisfies no gate."""
        before = self.rows(root)
        g = self._no_pwd(root, env, cwd)
        self.assertEqual(0, g.returncode, g.stderr)
        self.assertEqual([], json.loads(g.stdout.strip().splitlines()[-1]), "the gate authorized without a home entry")
        h = self._no_pwd(root, env, cwd, hook_payload=self._payload("AlphaCo"))
        self.assertNotEqual(0, h.returncode, "the writer signed without a home entry")
        self.assertIn("recorded UNSIGNED", h.stderr)
        self.assertIn("home", h.stderr.lower())
        after = self.rows(root)
        self.assertEqual(len(before) + 1, len(after), "the ruling was not recorded")
        self.assertEqual("AlphaCo", after[-1]["company"])
        self.assert_unsigned_record(after[-1], "home")
        g2 = self._no_pwd(root, env, cwd)
        self.assertEqual([], json.loads(g2.stdout.strip().splitlines()[-1]), "an unsigned record authorized a send")

    def test_n1_no_passwd_entry_with_home_set_never_uses_home(self):
        root = self._unpinned("nopwd-home")
        evil_home = os.path.join(self.tmp, "evil-home")
        kd = os.path.join(evil_home, ".jobsearch-ledger-keys")
        os.makedirs(kd)
        os.chmod(kd, 0o700)
        chosen = b"e" * 64
        kf = os.path.join(kd, self._id(root) + ".key")
        with open(kf, "wb") as fh:
            fh.write(chosen)
        os.chmod(kf, 0o600)
        self.append(root, self.legacy_row("EvilCo", chosen))
        env = self._env()
        env["HOME"] = evil_home
        self._assert_refused(root, env, cwd=self.tmp)
        self.assertEqual([self._id(root) + ".key"], os.listdir(kd), "files were created under HOME")

    def test_n1_no_passwd_entry_with_home_unset_never_creates_a_relative_tilde(self):
        root = self._unpinned("nopwd-nohome")
        cwd = os.path.join(self.tmp, "cwd")
        os.makedirs(cwd)
        env = self._env()
        env.pop("HOME", None)
        self._assert_refused(root, env, cwd=cwd)
        self.assertFalse(os.path.exists(os.path.join(cwd, "~")), "a relative ~ key folder was created")
        self.assertFalse(os.path.exists(os.path.join(root, "scripts", "~")))

    # N3: a key without its marker gets the marker from --migrate, never a snapshot.
    def test_n3_migrate_backfills_a_missing_marker_without_re_snapshotting(self):
        os.makedirs(self.keydir, exist_ok=True)
        os.chmod(self.keydir, 0o700)
        kid = self._id(self.a)
        kf = os.path.join(self.keydir, kid + ".key")
        with open(kf, "wb") as fh:
            fh.write(os.urandom(32).hex().encode())
        os.chmod(kf, 0o600)
        self.append(self.a, self.legacy_row("LateCo", self.legacy_key))
        r = subprocess.run([sys.executable, os.path.join(self.a, "scripts", "record_decision.py"), "--migrate"],
                           input="", capture_output=True, text=True, env=self._env())
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.keydir, kid + ".migrated")),
                        "--migrate left a key without its marker")
        self.assertFalse(os.path.exists(os.path.join(self.keydir, kid + ".legacy.json")),
                         "the backfill took a snapshot")
        os.remove(kf)
        self.assertNotIn("lateco", self.rulings(self.a))


@unittest.skipUnless(os.environ.get("JOBKIT_LIVE_LEDGER") and os.environ.get("JOBKIT_LIVE_KEYFILE"),
                     "live check: set JOBKIT_LIVE_LEDGER and JOBKIT_LIVE_KEYFILE to run it")
class TestAnExistingLiveLedgerStillVerifies(_Installs):
    """Reads a real ledger and its real key READ-ONLY. The ledger is copied into a temp install and
    the key is only read; the new per-install key and snapshot are created in the temp HOME."""

    def test_the_same_companies_verify_before_and_after(self):
        src, keyfile = os.environ["JOBKIT_LIVE_LEDGER"], os.environ["JOBKIT_LIVE_KEYFILE"]
        key = open(keyfile, "rb").read().strip()
        before = set()
        for line in open(src, encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            if (row.get("ruling") == "BUILD" and (row.get("company") or "").strip()
                    and row.get("source") in ("posttooluse-hook", "userpromptsubmit-hook")
                    and hmac.compare_digest(legacy_mac(row, key), str(row.get("mac", "")))):
                before.add(row["company"].strip().lower())
        shutil.copy(src, self.ledger(self.a))
        self.legacy_keyfile = keyfile
        after = self.rulings(self.a)
        self.assertTrue(before, "the live ledger verified nothing under the old scheme")
        self.assertEqual(before, after, f"{len(before)} before, {len(after)} after")


if __name__ == "__main__":
    unittest.main()
