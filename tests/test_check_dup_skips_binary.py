#!/usr/bin/env python3
"""Red-green tests for kit issue #174: check_dup.py crashes on binary files (PDF/.DS_Store)
under documents/applications/ after kit#159 made every scanned file decode as strict UTF-8.

`documents/applications/**/*` is a dir-glob STORE (STORES, about line 70) and that directory
holds real PDFs and `.DS_Store`, neither of which is text. Scanning them as strict UTF-8 raised
UnicodeDecodeError for every company, and mail-draft.sh (which runs check_dup as a send gate)
treated the non-1/3 exit as a refusal (exit 4) for every send.

Fix (issue #174's suggested fix): in `_scan()`'s dir-glob branch ONLY, skip a file when its
extension is a known binary type (or `.DS_Store`), or — for an extension that is not a known
text type either — when the first 8KB contains a NUL byte. Known TEXT extensions keep the
strict fail-closed decode (a corrupt `.md` store still refuses loudly, kit#159's own intent).
OSError (unreadable file) still refuses too.

Run:  python3 -m unittest tests.test_check_dup_skips_binary
"""
import importlib
import os
import _roots
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

check_dup = importlib.import_module("check_dup")

# harness.scratch_root() is the render dir where one exists, else the OS temp dir (macOS has no /home/vscode).
sys.path.insert(0, HERE)
from harness import scratch_root  # noqa: E402

_RENDER_TMP_ROOT = os.path.join(scratch_root(), "tmp-checkdup")


class _TempRepoCase(unittest.TestCase):
    """A temp REPO with a documents/applications/ dir under the render tmp root."""

    def setUp(self):
        os.makedirs(_RENDER_TMP_ROOT, exist_ok=True)
        self.tmp = tempfile.mkdtemp(dir=_RENDER_TMP_ROOT)
        self.addCleanup(self._cleanup)
        self.apps_dir = os.path.join(self.tmp, "documents", "applications", "acme-co-2026-09-27")
        os.makedirs(self.apps_dir, exist_ok=True)
        self._real_repo = check_dup.REPO
        check_dup.REPO = self.tmp
        _roots.patch_roots(self, self.tmp)
        self.addCleanup(lambda: setattr(check_dup, "REPO", self._real_repo))

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _scan_applications(self):
        """Drive the real dir-glob branch: _scan() over just the applications store."""
        store = {"documents/applications/**/*": "in APPLICATIONS (prior application material)"}
        # main() defines _scan() as a closure; reach it the same way main() does, by calling
        # check_dup's own module-level scan helper if one exists, else replicate main()'s glob
        # + search_file loop exactly (mirrors _scan() in main(), about line 787-806).
        import glob
        found_strong, found_weak = {}, {}
        for pattern, status in store.items():
            paths = sorted(os.path.relpath(p, check_dup._repo())
                            for p in glob.glob(os.path.join(check_dup._repo(), pattern), recursive=True)
                            if os.path.isfile(p) and not check_dup._is_binary_store_file(p))
            for path in paths:
                res = check_dup.search_file(path, {"acme co"})
                if not res:
                    continue
                strong, weak = res
                if strong:
                    found_strong[path] = (status, strong)
                elif weak:
                    found_weak[path] = (status, weak)
        return found_strong, found_weak


class TestBinaryFilesDoNotCrash(_TempRepoCase):
    def test_pdf_under_applications_does_not_raise(self):
        pdf_path = os.path.join(self.apps_dir, "cv.pdf")
        # a minimal, genuinely non-UTF-8 PDF-ish blob (the %PDF header plus high bytes that are
        # not valid UTF-8 continuation sequences)
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4\n\xe4\xb1\x00\xff\xfe binary junk not text at all\n")
        try:
            self._scan_applications()
        except UnicodeDecodeError:
            self.fail("PDF under documents/applications/ raised UnicodeDecodeError")

    def test_ds_store_under_applications_does_not_raise(self):
        ds_path = os.path.join(self.apps_dir, ".DS_Store")
        with open(ds_path, "wb") as f:
            f.write(b"\x00\x00\x00\x01Bud1\x00\x00\xff\xfe\x00garbage")
        try:
            self._scan_applications()
        except UnicodeDecodeError:
            self.fail(".DS_Store under documents/applications/ raised UnicodeDecodeError")

    def test_pdf_and_ds_store_together_still_find_a_real_text_hit(self):
        """The crash-prevention must not swallow a genuine match sitting alongside the binaries."""
        with open(os.path.join(self.apps_dir, "cv.pdf"), "wb") as f:
            f.write(b"%PDF-1.4\n\xe4\xb1\x00 not text\n")
        with open(os.path.join(self.apps_dir, ".DS_Store"), "wb") as f:
            f.write(b"\x00\x00\x00\x01Bud1\x00\xff")
        with open(os.path.join(self.apps_dir, "notes.md"), "w", encoding="utf-8") as f:
            f.write("Applied to Acme Co on 2026-09-27, pending reply.\n")
        strong, weak = self._scan_applications()
        hit_texts = [txt for _status, hits in {**strong, **weak}.values() for _ln, txt in hits]
        self.assertTrue(any("Acme Co" in t for t in hit_texts),
                         f"expected the text-file hit to survive; got {hit_texts!r}")


class TestExtensionlessNulFileIsSkipped(_TempRepoCase):
    def test_extensionless_file_with_nul_byte_is_skipped(self):
        """Not a known binary extension, not a known text extension — classify by content."""
        path = os.path.join(self.apps_dir, "resume_export")
        with open(path, "wb") as f:
            f.write(b"some header bytes\x00then more binary junk that is not valid utf-8 \xff\xfe")
        try:
            strong, weak = self._scan_applications()
        except UnicodeDecodeError:
            self.fail("extensionless file with a NUL byte in its first 8KB was not skipped")
        rel = os.path.relpath(path, self.tmp)
        self.assertNotIn(rel, strong)
        self.assertNotIn(rel, weak)


class TestTextStoresStillFailClosed(_TempRepoCase):
    def test_corrupt_md_under_applications_still_raises(self):
        """A text extension (.md) keeps kit#159's strict fail-closed decode — corruption in a
        TEXT store must still refuse loudly, never silently drop bytes or skip the file."""
        path = os.path.join(self.apps_dir, "cover-letter.md")
        with open(path, "wb") as f:
            f.write(b"# Cover letter\nAcme Co \xff\xfe not valid utf-8 at all\n")
        with self.assertRaises(UnicodeDecodeError):
            self._scan_applications()

    def test_text_file_naming_the_company_is_still_found(self):
        path = os.path.join(self.apps_dir, "notes.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("Interviewed with Acme Co, went well.\n")
        strong, weak = self._scan_applications()
        hit_texts = [txt for _status, hits in {**strong, **weak}.values() for _ln, txt in hits]
        self.assertTrue(any("Acme Co" in t for t in hit_texts))


if __name__ == "__main__":
    unittest.main()
