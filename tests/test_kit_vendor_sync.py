#!/usr/bin/env python3
"""Tests for scripts/kit_vendor_sync.py — BUG-217 (kit#57 shipped without committed coverage).

kit_vendor_sync.py is a `reset --hard`-capable-in-spirit tool: `--undo` runs `git reset --hard` on
the partner's own repo. Peer 74 verified it extensively ad-hoc before shipping (kit#57), but none of
that verification landed in the tree, which is exactly the "dark regression net" BUG-217 names —
a tool that can discard a partner's work, with nothing that runs automatically to prove it still
won't.

These tests build REAL, throwaway git repos (never the reference workspace or the kit's own repo)
and run the PRODUCTION script against them as a subprocess, reading its real JSON report and the
real state of the filesystem/git history afterward — never a reimplementation of its logic. Each
test that asserts a SAFETY property (a partner commit survives, a private file is untouched, undo
never rewinds history it shouldn't) is written to fail if that property is broken; see
`VendorSyncSafetyInvariantTests` for the ones that were verified RED against a deliberately broken
copy of the script before this file was committed.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.dirname(HERE)  # partner-starter/
SCRIPT = os.path.join(KIT_ROOT, "scripts", "kit_vendor_sync.py")


# ───────────────────────────── low-level git/file helpers ─────────────────────────────

def _run(cmd, cwd=None, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def _git(repo, *args):
    return _run(["git", *args], cwd=repo)


def git_out(repo, *args):
    return _git(repo, *args).stdout.strip()


def init_repo(path, branch="main"):
    os.makedirs(path, exist_ok=True)
    assert _git(path, "init", "-q", "-b", branch).returncode == 0
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    _git(path, "config", "tag.gpgsign", "false")
    return path


def write_file(repo, rel, content, mode=None):
    p = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if isinstance(content, bytes):
        with open(p, "wb") as fh:
            fh.write(content)
    else:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
    if mode is not None:
        os.chmod(p, mode)
    return p


def make_symlink(repo, rel, target):
    p = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.lexists(p):
        os.remove(p)
    os.symlink(target, p)
    return p


def commit_all(repo, message):
    _git(repo, "add", "-A")
    p = _git(repo, "commit", "-q", "-m", message)
    assert p.returncode == 0, p.stdout + p.stderr
    return git_out(repo, "rev-parse", "HEAD")


def add_remote(repo, name, url):
    _git(repo, "remote", "add", name, url)


def clone_repo(src, dest, branch="main"):
    """A REAL `git clone`, so `dest` shares merge-base history with `src` — used for the
    'behind'/'diverged' ancestry scenarios, unlike the independent-root-commit repos everywhere
    else in this file (which are deliberately unrelated)."""
    p = _run(["git", "clone", "-q", "--branch", branch, src, dest])
    assert p.returncode == 0, p.stdout + p.stderr
    _git(dest, "config", "user.email", "test@example.invalid")
    _git(dest, "config", "user.name", "Test")
    _git(dest, "config", "commit.gpgsign", "false")
    _git(dest, "config", "tag.gpgsign", "false")
    return dest


def run_vendor_sync(repo, *args, script=SCRIPT, env_overrides=None):
    """Run the PRODUCTION script (or an explicitly-substituted broken copy, for the discrimination
    proof in VendorSyncSafetyInvariantTests) against `repo`, always with --json for a structured
    report. Returns (CompletedProcess, report_dict_or_None)."""
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    p = _run([sys.executable, script, "--repo", repo, "--json", *args], env=env)
    try:
        report = json.loads(p.stdout)
    except json.JSONDecodeError:
        report = None
    return p, report


def is_exec(path):
    return bool(os.stat(path).st_mode & stat.S_IXUSR)


class TempReposMixin:
    """setUp gives each test its own throwaway kit repo + partner repo, so tests never share git
    state. Deliberately NOT one-sandbox-per-class: history mutation (commits, resets) makes
    per-test isolation the safer default for a tool whose whole job is mutating git history."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="kit-vendor-sync-test-")
        self.kit = init_repo(os.path.join(self._tmp, "kit-origin"))
        self.partner = init_repo(os.path.join(self._tmp, "partner-clone"))

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def fetch_partner_from_kit(self):
        add_remote(self.partner, "origin", self.kit)
        assert _git(self.partner, "fetch", "origin", "-q").returncode == 0


# ═══════════════════════════ 1. unrelated clone, full preservation ═══════════════════════════

class UnrelatedCloneSyncTests(TempReposMixin, unittest.TestCase):
    """The exact motivating scenario (BUG-040): a partner clone whose history shares NO merge-base
    with the kit's, because the kit's history was rebuilt upstream. The old path here was
    `git reset --hard`, which would have deleted the partner's own commits outright."""

    def setUp(self):
        super().setUp()
        # Kit origin: its own independent root commit, unrelated to the partner's.
        write_file(self.kit, "scripts/tool.py", "print('kit v1')\n")
        write_file(self.kit, "README.md", "kit v1\n")
        self.kit_head_v1 = commit_all(self.kit, "kit v1")

        # Partner clone: a SEPARATE root commit (never derived from the kit's), carrying private
        # files, an edited copy of a kit file, and the partner's OWN commits on top.
        write_file(self.partner, "documents/notes.md", "my private research\n")
        write_file(self.partner, "scripts/kit_config.py", "MY_SETTING = 42\n")
        write_file(self.partner, "scripts/tool.py", "print('my own edit of tool.py')\n")
        self.partner_head_1 = commit_all(self.partner, "partner: initial private setup")
        write_file(self.partner, "documents/notes.md", "my private research, updated\n")
        self.partner_head_2 = commit_all(self.partner, "partner: more private notes")

        self.fetch_partner_from_kit()

        # Kit gains a new version of tool.py, a brand-new file, and drops nothing.
        write_file(self.kit, "scripts/tool.py", "print('kit v2')\n")
        write_file(self.kit, "scripts/new_feature.py", "print('brand new in v2')\n")
        write_file(self.kit, "README.md", "kit v2\n")
        self.kit_head_v2 = commit_all(self.kit, "kit v2")
        _git(self.kit, "update-ref", "refs/heads/main", self.kit_head_v2)

    def test_ancestry_is_classified_unrelated(self):
        _git(self.partner, "fetch", "origin", "-q")
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(report["ancestry"]["state"], "unrelated")

    def test_partner_commits_survive_the_sync(self):
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        # Both original partner commits are still reachable from the new HEAD.
        for sha in (self.partner_head_1, self.partner_head_2):
            anc = _git(self.partner, "merge-base", "--is-ancestor", sha, "HEAD")
            self.assertEqual(anc.returncode, 0, f"{sha} is no longer an ancestor of HEAD")

    def test_private_files_are_untouched(self):
        run_vendor_sync(self.partner)
        self.assertEqual(
            open(os.path.join(self.partner, "documents", "notes.md")).read(),
            "my private research, updated\n")
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "kit_config.py")).read(),
            "MY_SETTING = 42\n")

    def test_partners_edit_is_backed_up_and_kit_version_applied(self):
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(),
            "print('kit v2')\n")
        backup_dir = os.path.join(self.partner, report["backup_dir"])
        backed_up_tool = os.path.join(backup_dir, "scripts", "tool.py")
        self.assertTrue(os.path.isfile(backed_up_tool), report)
        self.assertEqual(open(backed_up_tool).read(), "print('my own edit of tool.py')\n")

    def test_new_kit_file_is_added(self):
        run_vendor_sync(self.partner)
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "new_feature.py")).read(),
            "print('brand new in v2')\n")

    def test_sync_is_reported_via_a_single_pathspec_scoped_commit(self):
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(report["commit"])
        # The commit exists, is on HEAD, and its parent is the partner's own pre-sync HEAD — never
        # a commit that relates to the kit's independent history.
        self.assertEqual(git_out(self.partner, "rev-parse", "HEAD"), report["commit"])
        parent = git_out(self.partner, "rev-parse", "HEAD~1")
        self.assertEqual(parent, self.partner_head_2)


class SharedHistoryAncestryTests(unittest.TestCase):
    """`classify_ancestry()` names four states; every other class in this file only ever produces
    'unrelated' (two independent-root-commit repos never share a merge-base). These tests use a
    REAL `git clone` so the partner and kit genuinely share history, covering 'behind' (a plain
    fast-forward case) and 'diverged' (the script's own docstring calls this "partner-with-own-
    fixes", arguably the most common real case) — the two states nothing else here reaches."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="kit-vendor-sync-shared-history-")
        self.kit = init_repo(os.path.join(self._tmp, "kit-origin"))
        write_file(self.kit, "scripts/tool.py", "print('v1')\n")
        commit_all(self.kit, "v1")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_behind_partner_with_no_own_commits_is_classified_behind_and_fast_forwards_cleanly(self):
        partner = clone_repo(self.kit, os.path.join(self._tmp, "partner-clone"))
        write_file(self.kit, "scripts/tool.py", "print('v2')\n")
        commit_all(self.kit, "v2")

        p, report = run_vendor_sync(partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(report["ancestry"]["state"], "behind")
        self.assertEqual(report["ancestry"]["local_only"], 0)
        self.assertEqual(
            open(os.path.join(partner, "scripts", "tool.py")).read(), "print('v2')\n")

    def test_diverged_partner_with_own_commits_is_classified_diverged_and_both_sides_survive(self):
        partner = clone_repo(self.kit, os.path.join(self._tmp, "partner-clone"))
        write_file(partner, "scripts/partner_only.py", "print('mine')\n")
        partner_commit = commit_all(partner, "partner: my own fix on top of a shared history")
        write_file(self.kit, "scripts/tool.py", "print('v2')\n")
        commit_all(self.kit, "v2")

        p, report = run_vendor_sync(partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(report["ancestry"]["state"], "diverged")
        self.assertGreaterEqual(report["ancestry"]["local_only"], 1)
        # Partner's own commit survives...
        anc = _git(partner, "merge-base", "--is-ancestor", partner_commit, "HEAD")
        self.assertEqual(anc.returncode, 0)
        # ...and the partner's own file, and the kit's update, are both present.
        self.assertEqual(
            open(os.path.join(partner, "scripts", "partner_only.py")).read(), "print('mine')\n")
        self.assertEqual(
            open(os.path.join(partner, "scripts", "tool.py")).read(), "print('v2')\n")


# ═══════════════════════════════ 2. undo, both modes ═══════════════════════════════

class UndoHistoryModeTests(TempReposMixin, unittest.TestCase):
    """Undo mode 'history': safe because the partner made no commits after the sync, so rewinding
    to the pre-sync tag can only discard the sync commit itself."""

    def setUp(self):
        super().setUp()
        write_file(self.kit, "scripts/tool.py", "print('kit v1')\n")
        commit_all(self.kit, "kit v1")
        write_file(self.partner, "scripts/tool.py", "print('partner original')\n")
        write_file(self.partner, "documents/notes.md", "private\n")
        self.partner_head = commit_all(self.partner, "partner initial")
        self.fetch_partner_from_kit()
        write_file(self.kit, "scripts/tool.py", "print('kit v2')\n")
        commit_all(self.kit, "kit v2")

    def test_undo_restores_original_file_and_removes_the_sync_commit(self):
        p, _ = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(), "print('kit v2')\n")

        up, ureport = run_vendor_sync(self.partner, "--undo")
        self.assertEqual(up.returncode, 0, up.stdout + up.stderr)
        self.assertEqual(ureport["mode"], "history")
        self.assertEqual(git_out(self.partner, "rev-parse", "HEAD"), self.partner_head)
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(),
            "print('partner original')\n")

    def test_undo_backs_up_uncommitted_tracked_edits_before_the_hard_reset(self):
        """A `git reset --hard` silently drops uncommitted tracked edits. Undo must rescue them
        first — verified by making an uncommitted edit AFTER the sync and confirming it survives
        as a backup, not just as a discarded diff."""
        run_vendor_sync(self.partner)
        write_file(self.partner, "scripts/tool.py", "print('mid-flight uncommitted edit')\n")
        up, ureport = run_vendor_sync(self.partner, "--undo")
        self.assertEqual(up.returncode, 0, up.stdout + up.stderr)
        self.assertEqual(ureport["mode"], "history")
        saved = ureport.get("saved_uncommitted") or []
        self.assertTrue(saved, ureport)
        backup_path = os.path.join(self.partner, saved[0])
        self.assertTrue(os.path.isfile(backup_path))
        self.assertEqual(open(backup_path).read(), "print('mid-flight uncommitted edit')\n")
        # And the reset still happened: the working tree now matches the pre-sync commit, not the
        # uncommitted edit that would otherwise have been silently lost.
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(),
            "print('partner original')\n")


class UndoFilesOnlyModeTests(TempReposMixin, unittest.TestCase):
    """Undo mode 'files-only': the partner committed MORE work after the sync, so rewinding history
    would destroy that commit. Undo must restore the replaced files from backup and leave every
    commit — sync included — exactly where it is."""

    def setUp(self):
        super().setUp()
        write_file(self.kit, "scripts/tool.py", "print('kit v1')\n")
        commit_all(self.kit, "kit v1")
        write_file(self.partner, "scripts/tool.py", "print('partner original')\n")
        self.partner_head = commit_all(self.partner, "partner initial")
        self.fetch_partner_from_kit()
        write_file(self.kit, "scripts/tool.py", "print('kit v2')\n")
        commit_all(self.kit, "kit v2")

    def test_undo_restores_files_but_leaves_history_intact(self):
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        sync_commit = report["commit"]
        write_file(self.partner, "docs-partner-only.md", "new work after the sync\n")
        after_sync_commit = commit_all(self.partner, "partner: new work after the sync")

        up, ureport = run_vendor_sync(self.partner, "--undo")
        self.assertEqual(up.returncode, 0, up.stdout + up.stderr)
        self.assertEqual(ureport["mode"], "files-only")

        # History untouched: HEAD is still the partner's post-sync commit, and both the sync
        # commit and the partner's later commit remain exactly where they were.
        self.assertEqual(git_out(self.partner, "rev-parse", "HEAD"), after_sync_commit)
        for sha in (self.partner_head, sync_commit, after_sync_commit):
            anc = _git(self.partner, "merge-base", "--is-ancestor", sha, "HEAD")
            self.assertEqual(anc.returncode, 0, f"{sha} missing from history after files-only undo")

        # But the replaced file is back to the partner's own version.
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(),
            "print('partner original')\n")


class UndoDryRunTests(TempReposMixin, unittest.TestCase):
    """`--undo --dry-run` must preview without touching history, the working tree, or backups, in
    BOTH modes — untested by every other class in this file."""

    def setUp(self):
        super().setUp()
        write_file(self.kit, "scripts/tool.py", "print('kit v1')\n")
        commit_all(self.kit, "kit v1")
        write_file(self.partner, "scripts/tool.py", "print('partner original')\n")
        self.partner_head = commit_all(self.partner, "partner initial")
        self.fetch_partner_from_kit()
        write_file(self.kit, "scripts/tool.py", "print('kit v2')\n")
        commit_all(self.kit, "kit v2")

    def test_history_mode_dry_run_previews_without_resetting(self):
        p, _ = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        post_sync_head = git_out(self.partner, "rev-parse", "HEAD")

        up, ureport = run_vendor_sync(self.partner, "--undo", "--dry-run")
        self.assertEqual(up.returncode, 0, up.stdout + up.stderr)
        self.assertEqual(ureport["mode"], "history")
        self.assertTrue(ureport["ok"])
        # Nothing actually reset: HEAD and the working file are exactly as the sync left them.
        self.assertEqual(git_out(self.partner, "rev-parse", "HEAD"), post_sync_head)
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(), "print('kit v2')\n")

    def test_files_only_mode_dry_run_previews_without_restoring(self):
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        write_file(self.partner, "docs-partner-only.md", "more work\n")
        after_sync_commit = commit_all(self.partner, "partner: more work after the sync")

        up, ureport = run_vendor_sync(self.partner, "--undo", "--dry-run")
        self.assertEqual(up.returncode, 0, up.stdout + up.stderr)
        self.assertEqual(ureport["mode"], "files-only")
        # Nothing restored yet, and nothing committed/reset.
        self.assertEqual(git_out(self.partner, "rev-parse", "HEAD"), after_sync_commit)
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(), "print('kit v2')\n")
        # ⚠️ Regression guard for a real bug this test caught during review: `restored_files` must
        # report NOTHING actually restored (dry-run never calls `_restore_file`); the preview goes
        # in the SEPARATE `would_restore_files` list. An earlier version populated `restored_files`
        # itself even in dry-run mode, which `render_undo()` would have read as "Restored N
        # file(s)... from the backup" despite nothing having happened.
        self.assertEqual(ureport["restored_files"], [])
        self.assertEqual(ureport.get("would_restore_files"), ["scripts/tool.py"])


class VendorSyncSafetyInvariantTests(TempReposMixin, unittest.TestCase):
    """⛔ THE HARD SAFETY INVARIANT: undo must NEVER delete a partner commit or a private/ignored
    file, in either mode. This class proves the invariant two ways: (a) directly, against the real
    production script, and (b) by deliberately breaking the guard in a throwaway copy of the
    script and confirming the SAME test goes red — the discrimination proof the assignment asked
    for, so this isn't a test that would pass no matter what the code does."""

    def setUp(self):
        super().setUp()
        write_file(self.kit, "scripts/tool.py", "print('kit v1')\n")
        commit_all(self.kit, "kit v1")
        write_file(self.partner, "scripts/tool.py", "print('partner original')\n")
        write_file(self.partner, "documents/private-secret.md", "never touch me\n")
        self.partner_head = commit_all(self.partner, "partner initial")
        self.fetch_partner_from_kit()
        write_file(self.kit, "scripts/tool.py", "print('kit v2')\n")
        commit_all(self.kit, "kit v2")

    def _sync_then_commit_more_then_undo(self, script):
        p, report = run_vendor_sync(self.partner, script=script)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        sync_commit = report["commit"]
        write_file(self.partner, "docs-partner-only.md", "work the partner did after the sync\n")
        later_commit = commit_all(self.partner, "partner: more work after the sync")
        up, ureport = run_vendor_sync(self.partner, "--undo", script=script)
        return up, ureport, sync_commit, later_commit

    def test_undo_never_deletes_a_partner_commit_made_after_the_sync(self):
        """Against the REAL script: the invariant holds."""
        up, ureport, sync_commit, later_commit = self._sync_then_commit_more_then_undo(SCRIPT)
        self.assertEqual(up.returncode, 0, up.stdout + up.stderr)
        for sha in (self.partner_head, sync_commit, later_commit):
            anc = _git(self.partner, "merge-base", "--is-ancestor", sha, "HEAD")
            self.assertEqual(anc.returncode, 0, f"{sha} was deleted by undo — SAFETY INVARIANT BROKEN")

    def test_undo_never_deletes_a_private_file(self):
        run_vendor_sync(self.partner)
        write_file(self.partner, "docs-partner-only.md", "more work\n")
        commit_all(self.partner, "partner: more work")
        run_vendor_sync(self.partner, "--undo")
        self.assertEqual(
            open(os.path.join(self.partner, "documents", "private-secret.md")).read(),
            "never touch me\n")

    def test_the_invariant_test_goes_red_when_the_guard_is_broken(self):
        """DISCRIMINATION PROOF. Copy the production script, break the exact guard that decides
        history-mode is unsafe (`head == sync_commit`, kit_vendor_sync.py's own comment: "a
        partner commit made after the sync must not be discarded"), and confirm the safety test
        above ACTUALLY FAILS against the broken copy — proving it is not a test that would pass no
        matter what the code does. Then confirm the real script still passes."""
        broken_dir = tempfile.mkdtemp(prefix="kit-vendor-sync-broken-")
        try:
            broken_script = os.path.join(broken_dir, "kit_vendor_sync.py")
            src = open(SCRIPT, encoding="utf-8").read()
            needle = 'if tag_sha and sync_commit and head == sync_commit:'
            self.assertIn(needle, src,
                          "the guard this test targets has moved; update the needle")
            # Force history-mode (the unsafe branch) UNCONDITIONALLY whenever a restore tag
            # exists, exactly the shape of the pre-BUG-040 defect this whole script exists to fix.
            broken = src.replace(needle, "if tag_sha and True:  # BROKEN ON PURPOSE FOR A TEST")
            self.assertNotEqual(src, broken, "replacement did not apply")
            open(broken_script, "w", encoding="utf-8").write(broken)

            up, ureport, sync_commit, later_commit = self._sync_then_commit_more_then_undo(
                broken_script)
            lost = [sha for sha in (self.partner_head, sync_commit, later_commit)
                    if _git(self.partner, "merge-base", "--is-ancestor", sha, "HEAD").returncode != 0]
            self.assertTrue(lost, "expected the broken guard to lose at least one commit, but "
                                   "the invariant held anyway — the needle may no longer be load-"
                                   "bearing, or the break did not take effect")
            self.assertEqual(ureport.get("mode"), "history",
                              "expected the broken copy to force history-mode")
        finally:
            shutil.rmtree(broken_dir, ignore_errors=True)


# ═══════════════════════════════ 3. offline ═══════════════════════════════

class OfflineTests(TempReposMixin, unittest.TestCase):
    def test_unreachable_remote_reports_offline_not_up_to_date(self):
        # Point the remote at a path that does not exist — `git fetch` fails deterministically,
        # with no network required and no flakiness.
        add_remote(self.partner, "origin", os.path.join(self._tmp, "does-not-exist"))
        write_file(self.partner, "scripts/tool.py", "print('partner')\n")
        commit_all(self.partner, "partner initial")
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(report["error"], "offline")
        self.assertFalse(report.get("ok"))
        self.assertNotIn("ancestry", report)  # never even got far enough to compare — no false "current"


class RemoteSelectionTests(unittest.TestCase):
    """`find_kit_remote()` and `kit_ref()` have branches no other class in this file exercises:
    every other test's remote is a plain `origin` whose URL matches none of the special cases, so
    it always falls through to the trivial last line of `find_kit_remote()`. These tests force the
    canonical-match, kit-named-vs-decoy, and master-branch-fallback branches instead."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="kit-vendor-sync-remote-")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_a_remote_matching_the_canonical_owner_repo_wins_over_a_kit_named_decoy(self):
        # A path containing "job-attractor-kit" but NOT the full canonical "acme/job-attractor-kit"
        # — this is the "kit-named but not canonical" branch — added FIRST, as the decoy.
        decoy = init_repo(os.path.join(self._tmp, "job-attractor-kit-mirror"))
        write_file(decoy, "scripts/tool.py", "print('DECOY - should never be chosen')\n")
        commit_all(decoy, "decoy v1")

        canonical_dir = os.path.join(self._tmp, "acme", "job-attractor-kit")
        canonical = init_repo(canonical_dir)
        write_file(canonical, "scripts/tool.py", "print('canonical kit content')\n")
        commit_all(canonical, "canonical v1")

        partner = init_repo(os.path.join(self._tmp, "partner-clone"))
        write_file(partner, "scripts/tool.py", "print('partner original')\n")
        commit_all(partner, "partner initial")
        add_remote(partner, "kit_named_decoy", decoy)
        add_remote(partner, "the_real_kit", canonical)

        p, report = run_vendor_sync(partner, env_overrides={"JOBKIT_CANONICAL": "acme/job-attractor-kit"})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(report["remote"], "the_real_kit")
        self.assertEqual(
            open(os.path.join(partner, "scripts", "tool.py")).read(), "print('canonical kit content')\n")

    def test_master_branch_kit_falls_back_correctly_when_main_does_not_exist(self):
        kit = init_repo(os.path.join(self._tmp, "kit-origin"), branch="master")
        write_file(kit, "scripts/tool.py", "print('master-branch kit v1')\n")
        commit_all(kit, "v1")
        partner = init_repo(os.path.join(self._tmp, "partner-clone"))
        write_file(partner, "scripts/tool.py", "print('partner original')\n")
        commit_all(partner, "partner initial")
        add_remote(partner, "origin", kit)

        p, report = run_vendor_sync(partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(report["ref"], "origin/master")
        self.assertEqual(
            open(os.path.join(partner, "scripts", "tool.py")).read(), "print('master-branch kit v1')\n")

    def test_a_kit_named_remote_that_is_not_the_tracked_upstream_wins_the_disambiguation(self):
        """`find_kit_remote()`'s tie-break: `if not kit_named or (kit_named == track_remote and
        r != track_remote): kit_named = r`. With two remotes whose URL both contain
        "job-attractor-kit" and neither matching the exact canonical string, the one that is NOT
        the currently-tracked upstream must win — the tracked remote is assumed to be the wrong
        one to trust for "what does the kit look like now", by design."""
        tracked_kit = init_repo(os.path.join(self._tmp, "job-attractor-kit-tracked"))
        write_file(tracked_kit, "scripts/tool.py", "print('WRONG - the tracked remote, stale')\n")
        commit_all(tracked_kit, "tracked v1")

        other_kit = init_repo(os.path.join(self._tmp, "job-attractor-kit-other"))
        write_file(other_kit, "scripts/tool.py", "print('correct - the untracked kit-named remote')\n")
        commit_all(other_kit, "other v1")

        partner = init_repo(os.path.join(self._tmp, "partner-clone"))
        write_file(partner, "scripts/tool.py", "print('partner original')\n")
        commit_all(partner, "partner initial")
        add_remote(partner, "tracked_remote", tracked_kit)
        add_remote(partner, "other_remote", other_kit)
        assert _git(partner, "fetch", "tracked_remote", "-q").returncode == 0
        assert _git(partner, "branch", "--set-upstream-to=tracked_remote/main", "main").returncode == 0

        p, report = run_vendor_sync(partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(report["remote"], "other_remote")
        self.assertEqual(
            open(os.path.join(partner, "scripts", "tool.py")).read(),
            "print('correct - the untracked kit-named remote')\n")


class UnreadableExistingFileTests(TempReposMixin, unittest.TestCase):
    """`vendor()`'s explicit 'existing file unreadable; left untouched' branch — a partner file
    that cannot be read (permissions, in this test) must be skipped as a FAILURE, never silently
    deleted, and must never be reported as successfully written."""

    def setUp(self):
        super().setUp()
        write_file(self.kit, "scripts/locked.py", "print('kit new content')\n")
        write_file(self.kit, "scripts/normal.py", "print('kit normal v2')\n")
        commit_all(self.kit, "kit v1")
        self.locked_path = write_file(
            self.partner, "scripts/locked.py", "print('partner content, unreadable')\n")
        write_file(self.partner, "scripts/normal.py", "print('partner normal v1')\n")
        commit_all(self.partner, "partner initial")
        self.fetch_partner_from_kit()

    def test_unreadable_file_is_left_untouched_and_reported_as_failed(self):
        os.chmod(self.locked_path, 0o000)
        try:
            p, report = run_vendor_sync(self.partner)
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)  # "partial": one succeeded, one failed
            self.assertEqual(report["error"], "partial")
            failed = [f for f in report["failures"] if f["file"] == "scripts/locked.py"]
            self.assertEqual(len(failed), 1, report["failures"])
            self.assertIsNone(failed[0]["backed_up"])
            # The other file still synced correctly despite the failure.
            self.assertEqual(
                open(os.path.join(self.partner, "scripts", "normal.py")).read(),
                "print('kit normal v2')\n")
        finally:
            os.chmod(self.locked_path, 0o644)  # so tearDown's rmtree can clean up unconditionally


class WriteFailureRollbackTests(TempReposMixin, unittest.TestCase):
    """`vendor()`'s OSError path: if a file's containing directory cannot be written to (backup
    already succeeded, but the actual replace fails), the failure must be recorded, nothing of the
    partner's may be reported as changed, and the pre-existing file must be left exactly as it
    was — never deleted with nothing put back."""

    def setUp(self):
        super().setUp()
        write_file(self.kit, "locked_dir/tool.py", "print('kit v2')\n")
        commit_all(self.kit, "kit v1")
        write_file(self.partner, "locked_dir/tool.py", "print('partner original')\n")
        self.locked_dir = os.path.dirname(
            os.path.join(self.partner, "locked_dir", "tool.py"))
        commit_all(self.partner, "partner initial")
        self.fetch_partner_from_kit()
        write_file(self.kit, "locked_dir/tool.py", "print('kit v2, changed')\n")
        commit_all(self.kit, "kit v2")

    def test_write_failure_is_recorded_and_original_file_survives(self):
        os.chmod(self.locked_dir, 0o555)  # read+execute, no write: os.remove()/create in it fails
        try:
            p, report = run_vendor_sync(self.partner)
            # Every planned file lived in the locked directory, so nothing could be written at all.
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            self.assertEqual(report["error"], "none_written")
            self.assertTrue(report["failures"])
            self.assertEqual(report["failures"][0]["file"], "locked_dir/tool.py")
        finally:
            os.chmod(self.locked_dir, 0o755)
        # The partner's original file is exactly as it was — never left deleted with nothing put
        # back, even though a backup copy was created before the failed remove was attempted.
        self.assertEqual(
            open(os.path.join(self.partner, "locked_dir", "tool.py")).read(),
            "print('partner original')\n")


# ═══════════════════════════════ 4. dry-run ═══════════════════════════════

class DryRunTests(TempReposMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        write_file(self.kit, "scripts/tool.py", "print('kit v1')\n")
        commit_all(self.kit, "kit v1")
        write_file(self.partner, "scripts/tool.py", "print('partner original')\n")
        commit_all(self.partner, "partner initial")
        self.fetch_partner_from_kit()
        write_file(self.kit, "scripts/tool.py", "print('kit v2')\n")
        commit_all(self.kit, "kit v2")

    def test_dry_run_previews_without_writing_committing_or_tagging(self):
        pre_head = git_out(self.partner, "rev-parse", "HEAD")
        p, report = run_vendor_sync(self.partner, "--dry-run")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(report["dry_run"])
        self.assertTrue(any(o["action"].endswith("(dry-run)") for o in report["outcomes"]))
        # Nothing actually changed: file content, HEAD, and tag state are all untouched.
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(),
            "print('partner original')\n")
        self.assertEqual(git_out(self.partner, "rev-parse", "HEAD"), pre_head)
        tags = git_out(self.partner, "tag", "--list", "kit-sync-pre-*")
        self.assertEqual(tags, "")


# ═══════════════════════════════ 5. idempotent no-op ═══════════════════════════════

class IdempotentTests(TempReposMixin, unittest.TestCase):
    def test_running_sync_twice_is_a_clean_no_op_the_second_time(self):
        write_file(self.kit, "scripts/tool.py", "print('kit v1')\n")
        commit_all(self.kit, "kit v1")
        write_file(self.partner, "scripts/tool.py", "print('partner original')\n")
        commit_all(self.partner, "partner initial")
        self.fetch_partner_from_kit()
        write_file(self.kit, "scripts/tool.py", "print('kit v2')\n")
        commit_all(self.kit, "kit v2")

        p1, r1 = run_vendor_sync(self.partner)
        self.assertEqual(p1.returncode, 0, p1.stdout + p1.stderr)
        head_after_first = git_out(self.partner, "rev-parse", "HEAD")

        _git(self.partner, "fetch", "origin", "-q")
        p2, r2 = run_vendor_sync(self.partner)
        self.assertEqual(p2.returncode, 0, p2.stdout + p2.stderr)
        self.assertTrue(r2["ok"])
        # ⚠️ Ancestry state stays "unrelated" forever here, by SHA — the sync's own commit is a
        # NEW commit on the partner's side, so HEAD can never become sha-equal to the kit's ref in
        # an unrelated-history sync, even once every file matches. Idempotency is decided by
        # `_differs()` over the FILES, not by ancestry state, so that's what this test checks: the
        # second run's plan is empty and nothing changes, regardless of what `ancestry.state` says.
        self.assertIn(r2["ancestry"]["state"], ("unrelated", "up_to_date"))
        self.assertEqual(r2["outcomes"], [])
        self.assertEqual(git_out(self.partner, "rev-parse", "HEAD"), head_after_first)
        self.assertIsNone(r2.get("error"))


# ═══════════════════════════════ 6. symlink / non-ASCII / exec-bit fidelity ═══════════════════════════════

class FidelityTests(TempReposMixin, unittest.TestCase):
    """Symlinks, non-ASCII paths, and the executable bit are exactly the kinds of thing a naive
    text-based file copy silently mangles. These already EXIST in the partner's repo (kit updates
    them), so sync backs the originals up and the files-only/history undo paths both get exercised
    for restoring them faithfully."""

    NONASCII_REL = "docs/résumé-checklist.md"

    def setUp(self):
        super().setUp()
        # Kit v1: a trivial, unrelated placeholder commit — the real symlink/exec/non-ASCII
        # content is added only in v2 below, so v1 -> v2 is a genuine diff, not a no-op commit.
        write_file(self.kit, "README.md", "kit v1\n")
        commit_all(self.kit, "kit v1")

        write_file(self.partner, "scripts/run.sh", "#!/bin/sh\necho partner-version\n", mode=0o644)
        make_symlink(self.partner, "scripts/link.py", "some-other-target.py")
        write_file(self.partner, self.NONASCII_REL, "partner's own content\n")
        self.partner_head = commit_all(self.partner, "partner initial")
        self.fetch_partner_from_kit()

        # Kit's REAL v2: exec bit set, symlink pointing at run.sh, non-ASCII path present.
        write_file(self.kit, "scripts/run.sh", "#!/bin/sh\necho kit-v2\n", mode=0o755)
        make_symlink(self.kit, "scripts/link.py", "run.sh")
        write_file(self.kit, self.NONASCII_REL, "kit v2 content\n")
        commit_all(self.kit, "kit v2")

    def _paths(self, root):
        return {
            "run": os.path.join(root, "scripts", "run.sh"),
            "link": os.path.join(root, "scripts", "link.py"),
            "nonascii": os.path.join(root, self.NONASCII_REL),
        }

    def test_sync_applies_exec_bit_symlink_target_and_nonascii_content_faithfully(self):
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        paths = self._paths(self.partner)
        self.assertTrue(is_exec(paths["run"]), "kit's exec bit was not applied")
        self.assertTrue(os.path.islink(paths["link"]))
        self.assertEqual(os.readlink(paths["link"]), "run.sh")
        self.assertEqual(open(paths["nonascii"], encoding="utf-8").read(), "kit v2 content\n")

    def test_undo_restores_exec_bit_symlink_target_and_nonascii_content_faithfully(self):
        """files-only mode (the partner commits again after the sync), so `_restore_file`'s
        symlink/exec-bit fidelity path is what's under test, not a plain git reset."""
        p, _ = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        write_file(self.partner, "docs-partner-only.md", "more work\n")
        commit_all(self.partner, "partner: more work after sync")

        up, ureport = run_vendor_sync(self.partner, "--undo")
        self.assertEqual(up.returncode, 0, up.stdout + up.stderr)
        self.assertEqual(ureport["mode"], "files-only")

        paths = self._paths(self.partner)
        self.assertFalse(is_exec(paths["run"]), "partner's original (non-exec) file must come back")
        self.assertTrue(os.path.islink(paths["link"]))
        self.assertEqual(os.readlink(paths["link"]), "some-other-target.py")
        self.assertEqual(open(paths["nonascii"], encoding="utf-8").read(), "partner's own content\n")


if __name__ == "__main__":
    unittest.main()
