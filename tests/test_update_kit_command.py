#!/usr/bin/env python3
"""Tests for "Update Kit.command"'s pull + circuit-breaker path (BUG-040, kit#56, workspace #95).

kit#56: a partner who has only ever taken kit updates via `git merge kit/main` (the pre-fix
workaround) accumulates merge commits the published kit never has. The circuit breaker counted
those as "your own work at risk" forever, so the guard could never clear itself — Matthew's real
clone: 68 commits ahead of kit/main, 43 non-merge, the rest literally
"Merge remote-tracking branch 'kit/main'".

workspace #95: the published kit's history was rebuilt once (a hard reset to a fresh root), so
every pre-rebuild clone's own commits — real kit history, not partner edits — also count as
"local-only" forever, for a structurally identical reason: git cannot see WHY a commit is not an
ancestor of upstream, only that it is not.

These tests build REAL, throwaway git repos (never the reference workspace or the deployed kit)
and run the PRODUCTION "Update Kit.command" against them as a subprocess, exactly like a partner's
double-click would, reading the real exit code / stdout / git state afterward. install.sh is
stubbed to a no-op so these stay scoped to the pull + circuit-breaker logic (steps 2-3 of the
script), not the full installer.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.dirname(HERE)  # partner-starter/
UPDATE_KIT_SRC = os.path.join(KIT_ROOT, "Update Kit.command")


# ───────────────────────────── low-level git/file helpers (mirrors test_kit_vendor_sync.py) ─────

def _run(cmd, cwd=None, env=None, input_text=""):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, input=input_text)


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


def write_file(repo, rel, content):
    p = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(content)
    return p


def commit_all(repo, message):
    _git(repo, "add", "-A")
    p = _git(repo, "commit", "-q", "-m", message)
    assert p.returncode == 0, p.stdout + p.stderr
    return git_out(repo, "rev-parse", "HEAD")


def clone_repo(src, dest, branch="main"):
    p = _run(["git", "clone", "-q", "--branch", branch, src, dest])
    assert p.returncode == 0, p.stdout + p.stderr
    for k, v in (("user.email", "test@example.invalid"), ("user.name", "Test"),
                 ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
        _git(dest, "config", k, v)
    return dest


def _stub_install_sh(repo):
    """A no-op install.sh, so these tests stay scoped to the pull + circuit-breaker logic."""
    p = write_file(repo, "install.sh", "#!/usr/bin/env bash\nexit 0\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)


def _install_update_kit_command(repo):
    dest = os.path.join(repo, "Update Kit.command")
    shutil.copy(UPDATE_KIT_SRC, dest)
    os.chmod(dest, os.stat(dest).st_mode | stat.S_IXUSR)
    _stub_install_sh(repo)


def run_update_kit(repo):
    """Runs the PRODUCTION script exactly as a double-click would. `read -n1` at the end blocks
    on a real TTY; feeding empty stdin makes every `read` in the script hit EOF and return
    immediately, so this never hangs."""
    return _run(["bash", "Update Kit.command"], cwd=repo, input_text="")


class TempReposMixin:
    """One throwaway kit repo + partner repo per test — history mutation makes per-test isolation
    the safer default here, same reasoning as test_kit_vendor_sync.py's TempReposMixin."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="update-kit-command-test-")
        # The dir name itself must carry "job-attractor-kit" so Update Kit.command's own
        # remote-detection logic (KIT_CANONICAL / *job-attractor-kit* match) picks the right
        # remote deterministically, the same signal a partner's real clone carries in its URL.
        self.kit = init_repo(os.path.join(self._tmp, "job-attractor-kit-origin"))
        write_file(self.kit, "scripts/tool.py", "print('v1')\n")
        self.kit_head_v1 = commit_all(self.kit, "kit v1")
        self.partner = clone_repo(self.kit, os.path.join(self._tmp, "partner-clone"))
        _git(self.partner, "remote", "rename", "origin", "kit")
        _git(self.partner, "branch", "--set-upstream-to=kit/main", "main")
        _install_update_kit_command(self.partner)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _advance_kit(self, content, msg):
        write_file(self.kit, "scripts/tool.py", content)
        return commit_all(self.kit, msg)

    def _merge_kit_into_partner(self, round_n):
        """The pre-fix workaround kit#56 names: `git merge kit/main` by hand. `--no-ff` forces a
        real merge commit even when the partner made no commits of their own in between (a plain
        `git merge` would otherwise just fast-forward and create nothing to reproduce) -- this
        matches issue #56's own "better still, take the update with `git merge --no-ff kit/main`"
        line, and it is also the shape a partner gets for free the moment they have ANY commit of
        their own sitting between two kit updates, which is the realistic case."""
        assert _git(self.partner, "fetch", "kit", "-q").returncode == 0
        p = _git(self.partner, "merge", "--no-ff", "kit/main", "-q", "-m",
                 f"Merge remote-tracking branch 'kit/main' round {round_n}")
        assert p.returncode == 0, p.stdout + p.stderr


# ═══════════════════════ 1. kit#56 — merge-noise self-reinforcement ═══════════════════════

class MergeNoiseAutoResyncTests(TempReposMixin, unittest.TestCase):
    """Reproduces Matthew's exact shape at reduced scale: a partner clone that shares real
    ancestry with the kit (a genuine `git clone`, not an independent root — unlike the
    vendor-sync 'unrelated' fixtures), with ONLY merge commits standing between it and upstream,
    zero real edits. `git pull --ff-only` must fail the same structural way Matthew's did."""

    def test_pure_merge_history_resyncs_without_stopping(self):
        # Five rounds of "kit advances, partner takes it the old way" — the exact self-reinforcing
        # loop kit#56 describes, just five iterations instead of Matthew's dozens.
        for i in range(5):
            self._advance_kit(f"print('v{i + 2}')\n", f"kit v{i + 2}")
            self._merge_kit_into_partner(i)
        # Confirms the fixture actually reproduces the defect's PRECONDITION before asserting the
        # fix: at this point every local-only commit on the partner side is a merge.
        raw = int(git_out(self.partner, "rev-list", "--count", "kit/main..HEAD"))
        no_merges = int(git_out(self.partner, "rev-list", "--no-merges", "--count", "kit/main..HEAD"))
        self.assertGreater(raw, 0, "fixture did not actually diverge — test proves nothing")
        self.assertEqual(no_merges, 0, "fixture leaked a non-merge commit — not pure merge noise")

        # One more kit advance the partner has never merged, so `--ff-only` must fail.
        self._advance_kit("print('vFinal')\n", "kit vFinal")

        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 0, f"stdout:\n{p.stdout}\nstderr:\n{p.stderr}")
        self.assertNotIn("STOPPED", p.stdout, "pure merge-noise history must not trip the guard")
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(), "print('vFinal')\n",
            "the partner did not actually land the kit's latest content")

    def test_a_single_manual_merge_also_resyncs_cleanly(self):
        """The minimal case: exactly one prior manual sync, not Matthew's whole history."""
        self._advance_kit("print('v2')\n", "kit v2")
        self._merge_kit_into_partner(0)
        self._advance_kit("print('v3')\n", "kit v3")

        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 0, f"stdout:\n{p.stdout}\nstderr:\n{p.stderr}")
        self.assertNotIn("STOPPED", p.stdout)


# ═══════════════════════ 2. the invariant that must survive: real edits still stop ═══════════

class GenuinePartnerEditStillStopsTests(TempReposMixin, unittest.TestCase):
    """BUG-040's whole reason to exist. A real edit to a kit-shipped file — mixed in alongside
    merge-noise, so the fix cannot be 'ignore all local-only commits' — must still stop the
    update rather than being silently discarded. THE RED-TEAM PROOF for this file: everything
    below is written to demonstrate the fix CANNOT drop a partner commit, not just that it fixes
    the reported bugs."""

    def test_a_real_edit_alongside_merge_noise_still_stops(self):
        self._advance_kit("print('v2')\n", "kit v2")
        self._merge_kit_into_partner(0)
        # A genuine partner edit, not a merge, not vendor-sync-authored.
        write_file(self.partner, "scripts/tool.py", "print('MY OWN FIX, do not lose me')\n")
        partner_commit = commit_all(self.partner, "partner: fix a real bug in tool.py")
        self._advance_kit("print('v3')\n", "kit v3")

        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 1, f"a real edit must stop the update\nstdout:\n{p.stdout}")
        self.assertIn("STOPPED", p.stdout)
        # The partner's real commit is STILL reachable somewhere in the repo (nothing was deleted;
        # `git gc` has not run) -- the strongest thing this test can prove without a GC pass, which
        # matches the safety property BUG-040 exists to guarantee: the object is never destroyed.
        cat = _git(self.partner, "cat-file", "-e", partner_commit)
        self.assertEqual(cat.returncode, 0, "the partner's own commit object no longer exists")
        # And it is reachable from the safety branch the STOP path creates.
        branches = git_out(self.partner, "branch", "--list", "kit-backup-*")
        self.assertTrue(branches, "no kit-backup-* safety branch was created")
        safety_branch = branches.splitlines()[0].strip().lstrip("* ").strip()
        anc = _git(self.partner, "merge-base", "--is-ancestor", partner_commit, safety_branch)
        self.assertEqual(anc.returncode, 0,
                         "the partner's real commit is not reachable from the safety branch")

    def test_a_commit_that_merely_CLAIMS_to_be_a_vendor_sync_still_stops(self):
        """RED-TEAM PROOF. An earlier draft of this fix excluded local-only commits by MATCHING
        THEIR MESSAGE against the fixed string kit_vendor_sync.py stamps on its own commits, on
        the theory that using that tool once shouldn't re-trip this guard next run. This is the
        adversarial case that killed that approach: a commit carrying REAL, ARBITRARY content and
        that exact message text — never actually produced by kit_vendor_sync.py — must still be
        treated as a genuine local commit and must still stop the update. If this test ever goes
        red, a message-matching exclusion has been reintroduced; see the REJECTED APPROACH comment
        in Update Kit.command."""
        self._advance_kit("print('v2')\n", "kit v2")
        write_file(self.partner, "scripts/tool.py", "print('ATTACKER PAYLOAD, not a real sync')\n")
        forged_commit = commit_all(self.partner, "Kit sync fake: pretend this is safe\n\n"
                                    "Applied by kit_vendor_sync.py (BUG-040). Prior state tagged "
                                    "kit-sync-pre-* and bundled;\nreplaced files backed up under "
                                    "documents/.superseded/. Reversible via Undo Kit Sync.command.")
        self._advance_kit("print('v3')\n", "kit v3")

        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 1,
                         f"a forged vendor-sync-shaped message must not exempt a real commit\n"
                         f"stdout:\n{p.stdout}")
        self.assertIn("STOPPED", p.stdout)
        cat = _git(self.partner, "cat-file", "-e", forged_commit)
        self.assertEqual(cat.returncode, 0, "the forged-message commit object no longer exists")
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(),
            "print('ATTACKER PAYLOAD, not a real sync')\n",
            "the working tree content was overwritten despite the stop")

    def test_the_stop_message_names_sync_kit_as_the_way_forward(self):
        """workspace #95 / kit#56's shared ask: the STOP message must say what to do next, not
        just that it stopped."""
        self._advance_kit("print('v2')\n", "kit v2")
        write_file(self.partner, "scripts/tool.py", "print('my edit')\n")
        commit_all(self.partner, "partner: edit")
        self._advance_kit("print('v3')\n", "kit v3")

        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 1)
        self.assertIn("Sync Kit.command", p.stdout,
                      "the STOP message must name the safe next step, not dead-end")

    def test_uncommitted_local_edit_to_a_tracked_kit_file_still_stops(self):
        """A DIFFERENT failure shape from local commits: an UNCOMMITTED edit to a file the kit
        also ships. `git pull --ff-only` fails for this reason too, and `_local_only` reads 0
        (nothing is committed), so this must fall to the 'you edited a tracked file' branch,
        never to an auto-reset that would discard the uncommitted edit."""
        write_file(self.partner, "scripts/tool.py", "print('uncommitted edit')\n")
        self._advance_kit("print('v2')\n", "kit v2")

        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 1, f"stdout:\n{p.stdout}\nstderr:\n{p.stderr}")
        self.assertNotIn("STOPPED", p.stdout,
                         "this is the 'edited a tracked file' branch, not the commit-count branch")
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(),
            "print('uncommitted edit')\n",
            "an uncommitted edit was silently discarded")


class AutoResyncPathAlwaysTakesABackupTests(TempReposMixin, unittest.TestCase):
    """RED-TEAM FINDING, DEFENSE IN DEPTH. `--no-merges` is a structural, unspoofable-by-message
    filter, but it is not a content guarantee: `git merge --no-ff --no-commit` followed by a
    hand-edit puts arbitrary content into a merge commit's tree with ZERO non-merge commits
    anywhere in the local-only range, which reads as `_local_only == 0` and routes to the
    auto-reset path. That is deliberate, expert git use no normal partner workflow produces, so
    reproducing it here is the adversarial case, not the ordinary one -- and the fix is not to
    out-clever the detector, it is to make the ONE thing this file exists to guarantee hold
    unconditionally: nothing this script does is ever unrecoverable. The auto-reset path must
    always take a `kit-backup-*` branch first, exactly like the STOP path, so injected content
    survives the reset even when the "safe" classification turns out to be wrong."""

    def test_content_injected_via_a_no_commit_merge_survives_the_auto_reset(self):
        # Partner never makes a single ordinary commit -- pure fast-forward clone -- so there is
        # nothing for `--no-merges` to see, and this is deliberately reached via `--no-commit`,
        # never a real conflict.
        self._advance_kit("print('v2')\n", "kit v2")
        assert _git(self.partner, "fetch", "kit", "-q").returncode == 0
        p = _git(self.partner, "merge", "--no-ff", "--no-commit", "kit/main", "-q")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        write_file(self.partner, "scripts/tool.py", "print('INJECTED, no real conflict ever')\n")
        _git(self.partner, "add", "-A")
        p = _git(self.partner, "commit", "-q", "-m",
                 "Merge remote-tracking branch 'kit/main'")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        injected_commit = git_out(self.partner, "rev-parse", "HEAD")
        no_merges = int(git_out(self.partner, "rev-list", "--no-merges", "--count", "kit/main..HEAD"))
        self.assertEqual(no_merges, 0, "fixture did not reproduce the zero-non-merge-commits shape")

        self._advance_kit("print('v3')\n", "kit v3")
        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 0, f"stdout:\n{p.stdout}\nstderr:\n{p.stderr}")
        self.assertNotIn("STOPPED", p.stdout, "this shape is classified safe and auto-resyncs")
        # The auto-reset DID happen -- HEAD now carries the kit's content, not the injected line.
        self.assertEqual(
            open(os.path.join(self.partner, "scripts", "tool.py")).read(), "print('v3')\n")
        # But the injected commit is NOT gone: a kit-backup-* branch was taken before the reset,
        # and it is still reachable from that branch.
        branches = git_out(self.partner, "branch", "--list", "kit-backup-*")
        self.assertTrue(branches, "the auto-reset path did not take a safety branch")
        safety_branch = branches.splitlines()[0].strip().lstrip("* ").strip()
        anc = _git(self.partner, "merge-base", "--is-ancestor", injected_commit, safety_branch)
        self.assertEqual(anc.returncode, 0,
                         "the injected content is not reachable from the safety branch — LOST")


# ═══════════════════════ 3. workspace #95 — rebuilt/unrelated history ═══════════════════════

class UnrelatedHistoryStopsSafelyTests(unittest.TestCase):
    """A clone whose history shares no merge-base with upstream at all (the exact workspace #95
    shape: an upstream rewrite). merge-noise filtering cannot help here -- the local-only commits
    are ordinary, non-merge commits -- so this must still stop, but the message must point at the
    safe path (Sync Kit.command) rather than resetting blind or dead-ending."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="update-kit-command-unrelated-")
        self.kit = init_repo(os.path.join(self._tmp, "job-attractor-kit-origin"))
        write_file(self.kit, "scripts/tool.py", "print('rebuilt kit v1')\n")
        commit_all(self.kit, "kit v1 (post-rebuild)")

        # An UNRELATED root commit: simulates a clone made before the kit's history was rebuilt.
        self.partner = init_repo(os.path.join(self._tmp, "partner-clone"))
        write_file(self.partner, "scripts/tool.py", "print('old kit content')\n")
        write_file(self.partner, "scripts/legacy_only.py", "print('old kit file')\n")
        self.stranded_commit = commit_all(self.partner, "old kit history, pre-rebuild")
        _git(self.partner, "remote", "add", "kit", self.kit)
        _git(self.partner, "fetch", "kit", "-q")
        _git(self.partner, "branch", "--set-upstream-to=kit/main", "main")
        _install_update_kit_command(self.partner)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_unrelated_history_stops_and_names_sync_kit(self):
        self.assertEqual(git_out(self.partner, "merge-base", "kit/main", "HEAD"), "",
                         "fixture is not actually unrelated -- shares a merge-base")
        p = run_update_kit(self.partner)
        self.assertEqual(p.returncode, 1, f"stdout:\n{p.stdout}\nstderr:\n{p.stderr}")
        self.assertIn("STOPPED", p.stdout)
        self.assertIn("Sync Kit.command", p.stdout)
        # Nothing was destroyed: the stranded commit is still reachable.
        cat = _git(self.partner, "cat-file", "-e", self.stranded_commit)
        self.assertEqual(cat.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
