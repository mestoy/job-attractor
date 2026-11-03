"""kit reviewer bug: screen_sweep.blocked_keys_from_list's prose fallback harvests
placeholder/stopword bullets ("- nothing here yet", "- TBD") as blocked-company keys.
A section still being drafted then reads as though it blocks a company by that name.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import screen_sweep  # noqa: E402


class TestPlaceholderProseIsNeverAKey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _keys(self, text):
        p = os.path.join(self.tmp.name, "blocked.md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return screen_sweep.blocked_keys_from_list(p)

    def test_nothing_here_yet_is_not_a_key(self):
        keys = self._keys("- nothing here yet\n")
        self.assertNotIn(screen_sweep.canon("nothing here yet"), keys)
        self.assertEqual(keys, set())

    def test_tbd_is_not_a_key(self):
        keys = self._keys("- TBD\n")
        self.assertEqual(keys, set())

    def test_none_yet_is_not_a_key(self):
        keys = self._keys("- none yet\n")
        self.assertEqual(keys, set())

    def test_real_company_bullet_still_becomes_a_key(self):
        keys = self._keys("- **Fakemonth Corp** (blocked: pe-owned)\n")
        self.assertIn(screen_sweep.canon("Fakemonth Corp"), keys)


if __name__ == "__main__":
    unittest.main()
