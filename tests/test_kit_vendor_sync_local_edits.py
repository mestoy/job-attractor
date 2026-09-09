#!/usr/bin/env python3
"""Kit #80 (Matthew, 2026-09-05 and 2026-09-08): kit_vendor_sync silently clobbered a partner's own
fixes to kit-owned files. Five real fixes were dead for a week; a sixth was reverted forty minutes
after it was committed; the changelog lost fourteen dated lines.

The guard: a partner copy that differs from the LAST kit version of the file (the ref the previous
sync recorded, else the merge-base) carries the partner's own edit and is HELD, named in the report
with the commits that touched it. `--merge` tries a three-way merge and holds only on conflict.
`--replace-local` takes the kit's version on request. `--check-clobber` is the retrospective audit.
The changelog is seeded once and never replaced.

Same harness as test_kit_vendor_sync.py: real git repos in a temp dir, the PRODUCTION script run as
a subprocess, its JSON report read back.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_kit_vendor_sync import (_git, clone_repo, commit_all, init_repo, run_vendor_sync,  # noqa: E402
                                  write_file, TempReposMixin)


def _read(repo, rel):
    with open(os.path.join(repo, rel), encoding="utf-8") as fh:
        return fh.read()


class SharedHistoryLocalEditTests(unittest.TestCase):
    """A real clone: the merge-base gives the last kit version, so the guard fires on the first sync."""

    def setUp(self):
        import shutil
        import tempfile
        self._tmp = tempfile.mkdtemp(prefix="kit-80-shared-")
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        self.kit = init_repo(os.path.join(self._tmp, "kit-origin"))
        write_file(self.kit, "scripts/tool.py", "a = 1\nb = 2\nc = 3\n")
        commit_all(self.kit, "v1")
        self.partner = clone_repo(self.kit, os.path.join(self._tmp, "partner-clone"))

    def test_partners_committed_fix_is_held_and_named(self):
        write_file(self.partner, "scripts/tool.py", "a = 1\nb = 2\nc = 3  # my fix\n")
        fix = commit_all(self.partner, "partner: fix c")
        write_file(self.kit, "scripts/tool.py", "a = 10\nb = 2\nc = 3\n")
        commit_all(self.kit, "v2")

        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)     # partial: something needs the partner
        self.assertEqual(_read(self.partner, "scripts/tool.py"), "a = 1\nb = 2\nc = 3  # my fix\n",
                         "the partner's edited file was replaced")
        held = report["held"]
        self.assertEqual([h["file"] for h in held], ["scripts/tool.py"])
        self.assertIn(fix[:7], [c["sha"] for c in held[0]["commits"]])
        self.assertIn("partner: fix c", [c["subject"] for c in held[0]["commits"]])
        self.assertFalse(any(o["file"] == "scripts/tool.py" for o in report["outcomes"]))

    def test_a_merely_behind_file_is_still_updated(self):
        write_file(self.kit, "scripts/tool.py", "a = 10\nb = 2\nc = 3\n")
        commit_all(self.kit, "v2")
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(_read(self.partner, "scripts/tool.py"), "a = 10\nb = 2\nc = 3\n")
        self.assertEqual(report["held"], [])

    def test_merge_flag_merges_a_non_overlapping_edit(self):
        write_file(self.partner, "scripts/tool.py", "a = 1\nb = 2\nc = 3  # my fix\n")
        commit_all(self.partner, "partner: fix c")
        write_file(self.kit, "scripts/tool.py", "a = 10\nb = 2\nc = 3\n")
        commit_all(self.kit, "v2")
        p, report = run_vendor_sync(self.partner, "--merge")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(_read(self.partner, "scripts/tool.py"), "a = 10\nb = 2\nc = 3  # my fix\n")
        self.assertEqual([m["file"] for m in report["merged_files"]], ["scripts/tool.py"])
        self.assertEqual(report["held"], [])

    def test_merge_flag_holds_on_a_conflict(self):
        write_file(self.partner, "scripts/tool.py", "a = 1\nb = 2\nc = 30\n")
        commit_all(self.partner, "partner: c is 30")
        write_file(self.kit, "scripts/tool.py", "a = 1\nb = 2\nc = 40\n")
        commit_all(self.kit, "v2")
        p, report = run_vendor_sync(self.partner, "--merge")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(_read(self.partner, "scripts/tool.py"), "a = 1\nb = 2\nc = 30\n")
        self.assertEqual([h["file"] for h in report["held"]], ["scripts/tool.py"])
        self.assertNotIn("<<<<", _read(self.partner, "scripts/tool.py"))

    def test_replace_local_takes_the_kit_version_on_request_with_a_backup(self):
        write_file(self.partner, "scripts/tool.py", "a = 1\nb = 2\nc = 30\n")
        commit_all(self.partner, "partner: c is 30")
        write_file(self.kit, "scripts/tool.py", "a = 1\nb = 2\nc = 40\n")
        commit_all(self.kit, "v2")
        p, report = run_vendor_sync(self.partner, "--replace-local", "scripts/tool.py")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(_read(self.partner, "scripts/tool.py"), "a = 1\nb = 2\nc = 40\n")
        backed = os.path.join(self.partner, report["backup_dir"], "scripts", "tool.py")
        self.assertEqual(open(backed).read(), "a = 1\nb = 2\nc = 30\n")

    def test_check_clobber_names_a_fix_that_is_no_longer_live_and_clears_a_live_one(self):
        write_file(self.partner, "scripts/tool.py", "a = 1\nb = 2\nc = 30\n")
        commit_all(self.partner, "partner: c is 30")
        write_file(self.partner, "scripts/mine.py", "print('live')\n")
        commit_all(self.partner, "partner: my own script")
        write_file(self.kit, "scripts/tool.py", "a = 1\nb = 2\nc = 40\n")
        write_file(self.kit, "scripts/mine.py", "print('kit took it over')\n")
        commit_all(self.kit, "v2")
        p, _ = run_vendor_sync(self.partner, "--replace-local", "all")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p, report = run_vendor_sync(self.partner, "--check-clobber")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        suspect = {(f["file"], f["subject"]) for f in report["suspect"]}
        self.assertIn(("scripts/tool.py", "partner: c is 30"), suspect)
        self.assertIn(("scripts/mine.py", "partner: my own script"), suspect)
        # Put one fix back by hand: the audit must now report it live.
        write_file(self.partner, "scripts/mine.py", "print('live')\n")
        commit_all(self.partner, "partner: restore my script")
        p, report = run_vendor_sync(self.partner, "--check-clobber")
        live = {(f["file"], f["subject"]) for f in report["findings"] if f["live"]}
        self.assertIn(("scripts/mine.py", "partner: my own script"), live)


class UnrelatedCloneSecondSyncTests(TempReposMixin, unittest.TestCase):
    """The common partner shape: no merge-base at all. The FIRST sync has no last kit version and
    replaces with a backup (unchanged behaviour, noted per file). From the second sync on, the
    manifest's recorded ref is the last kit version, and the guard fires."""

    def setUp(self):
        super().setUp()
        write_file(self.kit, "scripts/tool.py", "a = 1\nb = 2\n")
        write_file(self.kit, "JOB-ATTRACTOR-CHANGELOG.md", "# Changelog\n\nkit seed line\n")
        commit_all(self.kit, "kit v1")
        write_file(self.partner, "documents/notes.md", "mine\n")
        write_file(self.partner, "scripts/tool.py", "a = 1\nb = 2\n")
        commit_all(self.partner, "partner initial")
        self.fetch_partner_from_kit()

    def test_second_sync_holds_a_fix_made_after_the_first(self):
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)          # first sync: seeds the changelog
        write_file(self.partner, "scripts/tool.py", "a = 1\nb = 2  # my fix\n")
        fix = commit_all(self.partner, "partner: fix b")
        write_file(self.kit, "scripts/tool.py", "a = 100\nb = 2\n")
        commit_all(self.kit, "kit v2")
        _git(self.partner, "fetch", "origin", "-q")
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(_read(self.partner, "scripts/tool.py"), "a = 1\nb = 2  # my fix\n")
        self.assertEqual([h["file"] for h in report["held"]], ["scripts/tool.py"])
        self.assertIn(fix[:7], [c["sha"] for c in report["held"][0]["commits"]])
        self.assertTrue(report["baseline"]["last_synced_ref"])

    def test_first_sync_with_no_baseline_replaces_with_a_backup_and_says_so(self):
        write_file(self.partner, "scripts/tool.py", "a = 1\nb = 2  # my fix\n")
        commit_all(self.partner, "partner: fix b")
        write_file(self.kit, "scripts/tool.py", "a = 100\nb = 2\n")
        commit_all(self.kit, "kit v2")
        _git(self.partner, "fetch", "origin", "-q")
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(_read(self.partner, "scripts/tool.py"), "a = 100\nb = 2\n")
        notes = {n["file"]: n for n in report["notes"]}
        self.assertEqual(notes["scripts/tool.py"]["action"], "replaced")
        self.assertIn("no last kit version", notes["scripts/tool.py"]["why"])

    def test_changelog_is_seeded_once_and_never_replaced(self):
        run_vendor_sync(self.partner)
        self.assertEqual(_read(self.partner, "JOB-ATTRACTOR-CHANGELOG.md"), "# Changelog\n\nkit seed line\n")
        write_file(self.partner, "JOB-ATTRACTOR-CHANGELOG.md", "# Changelog\n\nkit seed line\n\n2026-09-08 my own story\n")
        commit_all(self.partner, "partner: changelog")
        write_file(self.kit, "JOB-ATTRACTOR-CHANGELOG.md", "# Changelog\n\nkit seed line, reworded\n")
        write_file(self.kit, "scripts/tool.py", "a = 100\nb = 2\n")
        commit_all(self.kit, "kit v2")
        _git(self.partner, "fetch", "origin", "-q")
        p, report = run_vendor_sync(self.partner)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("2026-09-08 my own story", _read(self.partner, "JOB-ATTRACTOR-CHANGELOG.md"))
        self.assertEqual([k["file"] for k in report["kept"]], ["JOB-ATTRACTOR-CHANGELOG.md"])
        self.assertEqual(_read(self.partner, "scripts/tool.py"), "a = 100\nb = 2\n")


if __name__ == "__main__":
    unittest.main()
