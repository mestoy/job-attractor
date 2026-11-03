#!/usr/bin/env python3
"""Tests for kit_update.py's config-gap check (kit#85).

WHY THIS EXISTS. `kit_config.example.py` can gain a new top-level key (RANK_WEIGHTS is the known
case) after an install already has its own `kit_config.py`. Nothing in the update flow told the
operator the key was missing, so the consumer that reads it (`rank_applications.py`) fell back to
a hardcoded default and the operator kept believing they were running their own configured value.

The standing rule this encodes: an empty value and a clean value produce the same silence at a
gate, and that silence is never a pass. A missing config key is the same shape — it must be named
out loud, on every run that applies an update, never left for the operator to discover by hitting
a silent fallback somewhere else.

These tests call `kit_update.config_key_gaps()` / `report_config_gaps()` directly against throwaway
`scripts/kit_config.example.py` + `scripts/kit_config.py` pairs, never the real installed config.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.dirname(HERE)  # partner-starter/
sys.path.insert(0, os.path.join(KIT_ROOT, "scripts"))

import kit_update  # noqa: E402


def _seed(repo, example_src, installed_src):
    scripts = os.path.join(repo, "scripts")
    os.makedirs(scripts, exist_ok=True)
    if example_src is not None:
        with open(os.path.join(scripts, "kit_config.example.py"), "w", encoding="utf-8") as fh:
            fh.write(example_src)
    if installed_src is not None:
        with open(os.path.join(scripts, "kit_config.py"), "w", encoding="utf-8") as fh:
            fh.write(installed_src)


class ConfigKeyGapsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="kit-update-config-gaps-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_a_key_present_in_the_example_and_absent_from_the_install_is_named(self):
        """The exact reported shape: RANK_WEIGHTS shipped in the example, an older install
        never got it."""
        _seed(self._tmp,
              example_src="OWNER_NAME = 'x'\nRANK_WEIGHTS = {'skill': 0.4}\n",
              installed_src="OWNER_NAME = 'x'\n")
        gaps = kit_update.config_key_gaps(self._tmp)
        self.assertEqual(gaps, ["RANK_WEIGHTS"])

    def test_an_install_that_already_has_every_key_reports_nothing(self):
        _seed(self._tmp,
              example_src="OWNER_NAME = 'x'\nRANK_WEIGHTS = {'skill': 0.4}\n",
              installed_src="OWNER_NAME = 'x'\nRANK_WEIGHTS = {'skill': 0.5}\n")
        gaps = kit_update.config_key_gaps(self._tmp)
        self.assertEqual(gaps, [])

    def test_an_install_with_its_own_extra_keys_is_not_flagged_for_them(self):
        """The install is allowed to carry local additions the example never had (kit#86's own
        premise) — this check is one-directional: example -> install, never the reverse."""
        _seed(self._tmp,
              example_src="OWNER_NAME = 'x'\n",
              installed_src="OWNER_NAME = 'x'\nPERSON_WEIGHTS_V2 = {}\n")
        gaps = kit_update.config_key_gaps(self._tmp)
        self.assertEqual(gaps, [])

    def test_no_example_file_yet_reports_nothing_rather_than_raising(self):
        _seed(self._tmp, example_src=None, installed_src="OWNER_NAME = 'x'\n")
        gaps = kit_update.config_key_gaps(self._tmp)
        self.assertEqual(gaps, [])

    def test_no_installed_config_yet_reports_nothing_rather_than_raising(self):
        """A fresh install has no kit_config.py yet at all (install.sh seeds it before this ever
        runs) — this check must not crash or misreport ""every key"" as missing in that window."""
        _seed(self._tmp, example_src="OWNER_NAME = 'x'\n", installed_src=None)
        gaps = kit_update.config_key_gaps(self._tmp)
        self.assertEqual(gaps, [])


class ReportConfigGapsTests(unittest.TestCase):
    """The loud-print half: empty is silent (correct), any gap prints EVERY missing name."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="kit-update-config-gaps-report-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_keys_are_printed_loudly(self):
        _seed(self._tmp,
              example_src="RANK_WEIGHTS = {}\nMAINTAINER_EMAIL = ''\n",
              installed_src="")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gaps = kit_update.report_config_gaps(self._tmp)
        self.assertEqual(gaps, ["MAINTAINER_EMAIL", "RANK_WEIGHTS"])
        out = buf.getvalue()
        self.assertIn("RANK_WEIGHTS", out)
        self.assertIn("MAINTAINER_EMAIL", out)
        self.assertIn("kit_config.py", out)

    def test_nothing_missing_prints_nothing(self):
        _seed(self._tmp, example_src="OWNER_NAME = 'x'\n", installed_src="OWNER_NAME = 'x'\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gaps = kit_update.report_config_gaps(self._tmp)
        self.assertEqual(gaps, [])
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
