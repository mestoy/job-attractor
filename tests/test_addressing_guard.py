#!/usr/bin/env python3
"""BUG-180 ADDRESSING GUARD: a stored contact is addressed by its HANDLE, never the squashed key.

Michael's ruling 2026-08-16. The store's top-level `key` is a squashed display name that can collide
with a DIFFERENT, vetoed human ("janedoe" is not "jane-doe"); a note addressed off the
key can reach the wrong person (the measured near-miss). Two guards:
  1. state.address_for() is the one sanctioned resolver — it derives the URL strictly from
     payload.linkedin and RAISES when no handle exists, never falling back to the key.
  2. a static invariant: no script BUILDS a linkedin /in/ (or linkedin:/li:) address from a
     key-derived value (row["key"], .get("key"), key_for(...), _canon_person(...), display_name).
     The audit found none today; this fails the build if one is ever introduced."""
import glob
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import state


class AddressForResolver(unittest.TestCase):
    def test_addresses_off_the_handle_not_the_key(self):
        # a row whose squashed key DISAGREES with the real handle (the BUG-180 case)
        row = {"key": "janedoe",
               "payload": {"name": "Jane Doe",
                           "linkedin": "https://www.linkedin.com/in/jane-doe"}}
        url = state.address_for(row)
        self.assertEqual(url, "https://www.linkedin.com/in/jane-doe")
        self.assertNotIn("janedoe", url.rsplit("/in/", 1)[1],
                         "address must be the handle, never the squashed key")

    def test_accepts_a_bare_payload_dict(self):
        self.assertEqual(state.address_for({"linkedin": "linkedin.com/in/jane-doe"}),
                         "https://www.linkedin.com/in/jane-doe")

    def test_raises_when_no_handle_rather_than_using_the_key(self):
        # only a key + name, no payload.linkedin → must REFUSE, not address off the key
        with self.assertRaises(state.StateError):
            state.address_for({"key": "janedoe", "payload": {"name": "Jane Doe"}})

    def test_raises_on_empty(self):
        with self.assertRaises(state.StateError):
            state.address_for({})


class NoAddressingOffTheKey(unittest.TestCase):
    """Static: scan scripts/*.py + *.sh for lines that BUILD a linkedin address, and assert none of
    them interpolate a key-derived value. Line-level (cross-line data flow is covered by address_for +
    review), but it catches the naive `f"...linkedin.com/in/{row['key']}"` mistake mechanically."""

    # a KEY-DERIVED value: the store key or any of the squashers (incl. _canon_boss, the boss
    # key-deriver, which itself falls back to a squash). Allows .get("key", default) and inner spaces.
    _KEY_SOURCE = re.compile(r"""\[\s*['"]key['"]\s*\]|\.get\(\s*['"]key['"]|\bkey_for\(|"""
                             r"""\b_canon_(?:person|boss|company|slug)\(|\bdisplay_name\b|"""
                             r"""\bnormalize_name\(""")
    # a line that CONSTRUCTS a /in/ url or linkedin:/li: address (f-string / concat / .format / %).
    _BUILDS_ADDR = re.compile(r"""(/in/\{|/in/['"]\s*\+|linkedin\.com/in/['"]\s*\+|"""
                              r"""/in/%s|linkedin:\{|["']li:["']\s*\+|["']li:\{)""")
    # skip only genuine regex-CALL lines (a raw-string token alone must NOT exempt a whole line).
    _IS_REGEX = re.compile(r"""\bre\.(?:search|match|compile|sub|findall|fullmatch)\(""")

    def test_no_script_builds_a_linkedin_address_from_the_key(self):
        offenders = []
        for path in glob.glob(os.path.join(REPO, "scripts", "*.py")) + \
                glob.glob(os.path.join(REPO, "scripts", "*.sh")):
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for n, line in enumerate(fh, 1):
                    if self._IS_REGEX.search(line):
                        continue
                    if self._BUILDS_ADDR.search(line) and self._KEY_SOURCE.search(line):
                        offenders.append(f"{os.path.relpath(path, REPO)}:{n}: {line.strip()[:120]}")
        self.assertEqual(offenders, [],
                         "a script builds a LinkedIn address from a key-derived value — address off "
                         "payload.linkedin (state.address_for) instead:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
