#!/usr/bin/env python3
"""Slice 5 invariant 3 (BUG-332): no engine value without an http(s) URL. The port keeps the rule, with its positive control in the
same test: a finding with a URL is recorded, the same finding without one (or with a non-http one) is refused naming slug and item."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_research_fill import World, finding, rf, D1   # noqa: E402  (names only)


class NoValueWithoutAUrl(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.addCleanup(self.w.cleanup)

    def test_a_url_records_and_a_missing_or_non_http_url_is_refused(self):
        ok, why = rf.record(self.w.root, finding(source="engine", url="https://example.org/a"), today=D1)
        self.assertTrue(ok, why)                                    # positive control: the same finding WITH a url
        for bad in (None, "", "ftp://example.org/a", "javascript:alert(1)"):
            with self.subTest(url=bad):
                ok, why = rf.record(self.w.root, finding(source="engine", url=bad, value="Other value"), today=D1)
                self.assertFalse(ok)
                self.assertIn("zzwidgets", why)
                self.assertIn("ownership", why)


if __name__ == "__main__":
    unittest.main()
