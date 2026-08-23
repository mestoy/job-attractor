#!/usr/bin/env python3
"""kit issue #8 / BUG-175: the warm-ask-naming carve-out was pinned to two literal phrases from
one template, so a company named to a connector in ANY other wording scored a strong
ALREADY-SEEN hit and became permanently unsendable as a cold-boss target.

⚖️ DESIGN NOTE, a deliberate deviation from the issue's literal suggested implementation (route
through documents/state/company.jsonl's disposition field). Investigated and NOT taken: that
store is an append-only EVENT LOG requiring a per-field reducer to read safely, it has been
SUPERSEDED as the blocked-status authority by documents/employers.jsonl (the registry), and its
"sent" disposition coverage is a few dozen rows at most — thinner than the gap the issue itself
warns about. Instead this generalizes the EXISTING carve-out mechanism from two hardcoded
phrases to an actual header comparison, scoped to outreach_log.md only, which structurally
avoids every failure mode a system-wide version would hit (no `## ` headers in
blocked-employers-list.md, no headers at all in job_search_tracker.csv — which was never
vulnerable to this bug because `_strong()` matches its dedicated company COLUMN).

⚠️ NEW FILE: consistent with earlier clusters' collision-avoidance convention.
"""
import importlib
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

check_dup = importlib.import_module("check_dup")


class WarmAskNamingGeneralizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kf2-disposition-")
        os.makedirs(os.path.join(self.tmp, "documents"), exist_ok=True)
        self._real_repo = check_dup.REPO
        check_dup.REPO = self.tmp
        self._write("outreach_log.md", "# Outreach Log\n")
        self._write("documents/blocked-employers-list.md", "# blocked\n")
        self._write("job_search_tracker.csv", "date,company,role\n")
        self._write("documents/employers.jsonl", "")

    def tearDown(self):
        import shutil
        check_dup.REPO = self._real_repo
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rel, text):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _run(self, *args):
        import io, contextlib
        buf = io.StringIO()
        old_argv = sys.argv
        sys.argv = ["check_dup.py"] + list(args)
        code = None
        try:
            with contextlib.redirect_stdout(buf):
                try:
                    check_dup.main()
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv = old_argv
        return code, buf.getvalue()

    # ── THE FIX ITSELF ──────────────────────────────────────────────────────────────────────
    def test_a_connector_naming_in_nontemplate_wording_is_demoted(self):
        self._write("outreach_log.md",
            "## 2026-08-20 · Example Consulting · Jane Doe — SENT [linkedin]\n"
            "**Verbatim as sent:**\n"
            "> OK, thank you! The two closest to your world are Athennian and "
            "Zzzdispositionbug Co.\n")
        code, out = self._run("--send-gate", "Zzzdispositionbug Co")
        self.assertEqual(code, 3, f"non-template connector naming must demote to weak:\n{out}")
        self.assertIn("🟡", out)

    def test_the_original_template_phrasing_still_works(self):
        self._write("outreach_log.md",
            "## 2026-08-20 · Example Consulting · Jane Doe — SENT [linkedin]\n"
            "**Verbatim as sent:**\n"
            "> Rather than send you a long list, I picked three: Athennian, "
            "Zzztemplatephrase Co, and a third.\n")
        code, out = self._run("--send-gate", "Zzztemplatephrase Co")
        self.assertEqual(code, 3, f"original template phrasing must still demote:\n{out}")

    def test_targets_named_metadata_still_demotes(self):
        self._write("outreach_log.md",
            "## 2026-08-20 · Example Consulting · Jane Doe — SENT [linkedin]\n"
            "**Targets named (now burned):** Athennian,Zzztargetsmeta Co\n"
            "**Verbatim as sent:**\n> Thanks for offering!\n")
        code, out = self._run("--send-gate", "Zzztargetsmeta Co")
        self.assertEqual(code, 3, f"Targets-named metadata must still demote:\n{out}")

    # ── DOES-NOT-WEAKEN ─────────────────────────────────────────────────────────────────────
    def test_a_genuine_prior_contact_still_reads_strong(self):
        self._write("outreach_log.md",
            "## 2026-08-20 · Zzzrealcontact Co · Peter Alouche — SENT [linkedin]\n"
            "**Verbatim as sent:**\n"
            "> Hi Peter, Zzzrealcontact Co's work on regulated workflow caught my eye.\n")
        code, out = self._run("--send-gate", "Zzzrealcontact Co")
        self.assertEqual(code, 1, f"a genuine prior contact must still block:\n{out}")
        self.assertIn("ALREADY-SEEN", out)

    def test_a_quoted_line_with_no_header_at_all_still_blocks(self):
        self._write("outreach_log.md",
            "> Just a stray quoted line mentioning Zzznoheaderco with no preceding header.\n")
        code, out = self._run("--send-gate", "Zzznoheaderco")
        self.assertEqual(code, 1, f"an unheadered quoted line must fail closed:\n{out}")

    # ── SCOPE ───────────────────────────────────────────────────────────────────────────────
    def test_blocked_employers_list_is_unaffected(self):
        self._write("documents/blocked-employers-list.md",
            "- **Zzzblockedstillworks Co** (culture, 2026-08-01): test fixture.\n")
        code, out = self._run("Zzzblockedstillworks Co")
        self.assertEqual(code, 1, f"the blocked list must be completely unaffected:\n{out}")
        self.assertIn("BLOCKED", out)

    def test_csv_company_column_still_blocks_notes_field_still_demotes(self):
        self._write("job_search_tracker.csv", "date,company,role\n2026-08-01,Zzzcsvco,PM\n")
        code, out = self._run("--send-gate", "Zzzcsvco")
        self.assertEqual(code, 1, f"a genuine tracker company-column row must still block:\n{out}")

        self._write("job_search_tracker.csv",
            "date,company,role\n2026-08-01,Zzzothercsvco,notes mention Zzznotesonlyco as a referral\n")
        code2, out2 = self._run("--send-gate", "Zzznotesonlyco")
        self.assertEqual(code2, 3, f"a notes-field-only mention must demote, never hard-block:\n{out2}")


if __name__ == "__main__":
    unittest.main()
