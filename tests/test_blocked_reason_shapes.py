#!/usr/bin/env python3
"""kit issue #67: blocked_reason() anchored only to a bare `-`/`*` bullet, so entries written
as a bold bullet (`- **Name** (...)`) or a table row (`| Name | DROPPED ... |`) returned None
and blocked companies leaked into the banked pool. This pins the three list-item shapes the
blocked list is actually written in, while keeping the anchor tight enough that a company named
inside ordinary prose (not at a list-item start) still does not read as blocked.
"""
import importlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

screen_sweep = importlib.import_module("screen_sweep")


class BlockedReasonShapesTests(unittest.TestCase):
    BLOCKED_TXT = (
        "- acme robotics (blocked 2026-01-01): reason one\n"
        "- **beta industries** (blocked 2026-02-01): bold bullet reason\n"
        "| gamma systems | dropped 2026-03-01 industry mismatch |\n"
        "prose paragraph mentioning delta corp in passing, not a list line at all\n"
    )

    def test_bare_bullet_is_blocked(self):
        self.assertIsNotNone(
            screen_sweep.blocked_reason("Acme Robotics", self.BLOCKED_TXT))

    def test_bold_bullet_is_blocked(self):
        got = screen_sweep.blocked_reason("Beta Industries", self.BLOCKED_TXT)
        self.assertIsNotNone(got, "a `- **Name** (...)` bold-bullet entry must still block")
        self.assertIn("beta industries", got)

    def test_table_row_is_blocked(self):
        got = screen_sweep.blocked_reason("Gamma Systems", self.BLOCKED_TXT)
        self.assertIsNotNone(got, "a `| Name | DROPPED ... |` table row must still block")
        self.assertIn("gamma systems", got)

    def test_prose_mention_is_not_blocked(self):
        """A company named only inside a prose sentence — not at a list-item start — must NOT
        read as blocked. Widening the anchor to catch bold bullets and table rows must not
        widen it into a substring match."""
        self.assertIsNone(
            screen_sweep.blocked_reason("Delta Corp", self.BLOCKED_TXT))


if __name__ == "__main__":
    unittest.main()
