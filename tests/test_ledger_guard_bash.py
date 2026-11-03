#!/usr/bin/env python3
"""Retro parking-lot item (2026-09-13): twice today a seat ran `git checkout --` on
documents/decision-ledger.jsonl as side-effect cleanup and discarded hook-signed rulings that
cannot be restored. check_ledger_guard.py only sees Write/Edit/MultiEdit — it never sees a Bash
tool call, so a shell git command sailed straight past it. This is the sibling PreToolUse hook
wired on the Bash matcher: it DENIES (exit 2) a shell command that would discard or overwrite a
protected ledger via git checkout/restore/reset/stash/clean or a raw redirection/truncation, and
ALLOWS (exit 0) everything else, including read-only git commands and edits to unrelated files."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import _roots

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
HOOK = os.path.join(KIT, "scripts", "check_ledger_guard_bash.py")


# BUG-733 slice 2: the hook only inspects paths, so the tests run it against a TEMP project root (both data roots point there), never the shipped tree.
REPO = tempfile.mkdtemp(prefix="ledger-guard-")
os.makedirs(os.path.join(REPO, "documents", "state"))


def tearDownModule():
    shutil.rmtree(REPO, ignore_errors=True)


def _run(command, project_dir=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    env = _roots.sandbox_env(project_dir or REPO)
    r = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, cwd=REPO)
    return r.returncode, (r.stdout + r.stderr)


def _run_raw(stdin_text):
    env = _roots.sandbox_env(REPO)
    r = subprocess.run([sys.executable, HOOK], input=stdin_text,
                       capture_output=True, text=True, env=env, cwd=REPO)
    return r.returncode, (r.stdout + r.stderr)


LEDGER = "documents/decision-ledger.jsonl"
BUDGET = "documents/state/run-budget.jsonl"


class LedgerGuardBashDenies(unittest.TestCase):
    def test_git_checkout_dashdash_ledger_is_denied(self):
        rc, out = _run(f"git checkout -- {LEDGER}")
        self.assertEqual(rc, 2, "git checkout -- <ledger> must be denied")
        self.assertIn("BLOCKED", out)

    def test_git_checkout_no_dashdash_ledger_is_denied(self):
        rc, _ = _run(f"git checkout {LEDGER}")
        self.assertEqual(rc, 2)

    def test_git_checkout_bare_dot_sweep_is_denied(self):
        rc, _ = _run("git checkout -- .")
        self.assertEqual(rc, 2, "a bare '.' pathspec sweeps the whole tree, including the ledger")

    def test_git_checkout_dot_no_dashdash_is_denied(self):
        rc, _ = _run("git checkout .")
        self.assertEqual(rc, 2)

    def test_git_restore_ledger_is_denied(self):
        rc, _ = _run(f"git restore {LEDGER}")
        self.assertEqual(rc, 2)

    def test_git_restore_bare_dot_is_denied(self):
        rc, _ = _run("git restore .")
        self.assertEqual(rc, 2, "git restore . with no narrower pathspec sweeps everything")

    def test_git_restore_no_pathspec_is_denied(self):
        rc, _ = _run("git restore")
        self.assertEqual(rc, 2)

    def test_git_reset_hard_is_denied(self):
        rc, _ = _run("git reset --hard")
        self.assertEqual(rc, 2, "git reset --hard sweeps the working tree unconditionally")

    def test_git_reset_hard_with_ref_is_denied(self):
        rc, _ = _run("git reset --hard HEAD~1")
        self.assertEqual(rc, 2)

    def test_git_stash_bare_is_denied(self):
        rc, _ = _run("git stash")
        self.assertEqual(rc, 2, "a bare git stash hides all uncommitted changes, ledger included")

    def test_git_stash_push_no_pathspec_is_denied(self):
        rc, _ = _run("git stash push")
        self.assertEqual(rc, 2)

    def test_git_stash_targeting_ledger_is_denied(self):
        rc, _ = _run(f"git stash push -- {LEDGER}")
        self.assertEqual(rc, 2)

    def test_git_clean_force_no_pathspec_is_denied(self):
        rc, _ = _run("git clean -fd")
        self.assertEqual(rc, 2, "git clean -f with no pathspec sweeps untracked files")

    def test_redirection_truncates_ledger_is_denied(self):
        rc, _ = _run(f"echo '{{}}' > {LEDGER}")
        self.assertEqual(rc, 2, "a raw redirection into the ledger must be denied")

    def test_append_redirection_to_ledger_is_denied(self):
        rc, _ = _run(f"echo '{{}}' >> {LEDGER}")
        self.assertEqual(rc, 2)

    def test_truncate_command_on_ledger_is_denied(self):
        rc, _ = _run(f"truncate -s 0 {LEDGER}")
        self.assertEqual(rc, 2)

    def test_heredoc_write_to_ledger_is_denied(self):
        rc, _ = _run(f"cat > {LEDGER} <<'EOF'\n{{}}\nEOF")
        self.assertEqual(rc, 2, "a here-doc that overwrites the ledger must be denied")

    def test_run_budget_ledger_is_also_protected_from_sweep(self):
        rc, _ = _run(f"git checkout -- {BUDGET}")
        self.assertEqual(rc, 2, "git commands sweep the whole tree, so the other ledger is at "
                                "the same risk and must be protected too")

    def test_chained_command_with_and_is_denied(self):
        rc, _ = _run(f"git status && git checkout -- {LEDGER}")
        self.assertEqual(rc, 2, "a dangerous command chained after && must still be caught")

    def test_chained_command_with_semicolon_is_denied(self):
        rc, _ = _run(f"echo hi; git checkout -- {LEDGER}")
        self.assertEqual(rc, 2)

    def test_relative_path_from_documents_dir_is_denied(self):
        rc, _ = _run("git checkout -- decision-ledger.jsonl", project_dir=REPO)
        self.assertEqual(rc, 2, "a bare filename pathspec matching the ledger's basename must "
                                "be caught")

    def test_glob_pathspec_matching_ledger_is_denied(self):
        rc, _ = _run("git checkout -- documents/decision-ledger.*")
        self.assertEqual(rc, 2, "a glob that would match the ledger must be caught even though "
                                "the shell never expands it for us")

    def test_quoted_path_is_denied(self):
        rc, _ = _run(f'git checkout -- "{LEDGER}"')
        self.assertEqual(rc, 2)


class LedgerGuardBashAllows(unittest.TestCase):
    def test_git_diff_is_allowed(self):
        rc, _ = _run(f"git diff {LEDGER}")
        self.assertEqual(rc, 0, "reads must never be blocked")

    def test_git_log_is_allowed(self):
        rc, _ = _run(f"git log -- {LEDGER}")
        self.assertEqual(rc, 0)

    def test_git_show_is_allowed(self):
        rc, _ = _run(f"git show HEAD:{LEDGER}")
        self.assertEqual(rc, 0)

    def test_cat_is_allowed(self):
        rc, _ = _run(f"cat {LEDGER}")
        self.assertEqual(rc, 0)

    def test_tail_is_allowed(self):
        rc, _ = _run(f"tail -5 {LEDGER}")
        self.assertEqual(rc, 0)

    def test_grep_is_allowed(self):
        rc, _ = _run(f"grep foo {LEDGER}")
        self.assertEqual(rc, 0)

    def test_git_checkout_of_unrelated_file_is_allowed(self):
        rc, _ = _run("git checkout -- documents/outreach-queue.md")
        self.assertEqual(rc, 0, "checkout of an unrelated file must not be blocked")

    def test_git_checkout_branch_switch_is_allowed(self):
        rc, _ = _run("git checkout main")
        self.assertEqual(rc, 0, "switching branches is not a ledger sweep")

    def test_git_stash_pop_is_allowed(self):
        rc, _ = _run("git stash pop")
        self.assertEqual(rc, 0, "restoring a stash is not what discards the ledger")

    def test_git_stash_list_is_allowed(self):
        rc, _ = _run("git stash list")
        self.assertEqual(rc, 0)

    def test_git_clean_dry_run_is_allowed(self):
        rc, _ = _run("git clean -nd")
        self.assertEqual(rc, 0, "clean without -f is a dry run by default, nothing is removed")

    def test_git_clean_force_specific_unrelated_file_is_allowed(self):
        rc, _ = _run("git clean -f documents/some-scratch-file.tmp")
        self.assertEqual(rc, 0)

    def test_similarly_named_unrelated_file_is_allowed(self):
        rc, _ = _run("git checkout -- documents/decision-ledger-backup.jsonl")
        self.assertEqual(rc, 0, "a similarly named but distinct file must never be blocked")

    def test_similarly_named_backup_suffix_is_allowed(self):
        rc, _ = _run(f"git checkout -- {LEDGER}.bak")
        self.assertEqual(rc, 0)

    def test_redirection_to_unrelated_file_is_allowed(self):
        rc, _ = _run("echo hi > documents/scratch.txt")
        self.assertEqual(rc, 0)

    def test_non_bash_tool_is_ignored(self):
        env = _roots.sandbox_env(REPO)
        payload = {"tool_name": "Write", "tool_input": {"file_path": LEDGER}}
        r = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                           capture_output=True, text=True, env=env, cwd=REPO)
        self.assertEqual(r.returncode, 0, "this hook only inspects Bash calls")

    def test_empty_command_is_allowed(self):
        rc, _ = _run("")
        self.assertEqual(rc, 0)

    def test_malformed_payload_fails_open(self):
        rc, out = _run_raw("not json")
        self.assertEqual(rc, 0, "an unparseable payload must fail open, never wedge Bash calls")

    def test_missing_command_key_fails_open(self):
        env = _roots.sandbox_env(REPO)
        payload = {"tool_name": "Bash", "tool_input": {}}
        r = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                           capture_output=True, text=True, env=env, cwd=REPO)
        self.assertEqual(r.returncode, 0)

    def test_non_string_command_fails_open(self):
        env = _roots.sandbox_env(REPO)
        payload = {"tool_name": "Bash", "tool_input": {"command": 12345}}
        r = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                           capture_output=True, text=True, env=env, cwd=REPO)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
