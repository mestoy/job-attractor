#!/usr/bin/env python3
"""BUG-180: contacts key on the LinkedIn HANDLE (from payload.linkedin), with dual-key reads.

Michael's ruling 2026-08-16 (hybrid c). The store's squashed display-name key collides with real
strangers ("janedoe" is a DIFFERENT human than "jane-doe"). Forward-fix: new rows
key on the handle from payload.linkedin, falling back to the squash only when no handle exists.
Dual-key readers: a name lookup with the linkedin checks BOTH key spaces, so old squash rows and new
handle rows both resolve — no rewrite of any existing row (append-only)."""
import importlib
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))


class ContactKeyHandleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "documents", "state"), exist_ok=True)
        os.environ["CLAUDE_PROJECT_DIR"] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop("CLAUDE_PROJECT_DIR", None))
        import state
        importlib.reload(state)
        self.state = state

    # ── writer forward-fix ──
    def test_new_row_keys_on_the_handle_not_the_squash(self):
        r = self.state.append("contact", "Jane Doe", as_of="2026-08-16",
                              as_of_source="export:c",
                              linkedin="https://www.linkedin.com/in/jane-doe",
                              name="Jane Doe")
        self.assertEqual(r["key"], "li:jane-doe")

    def test_new_row_falls_back_to_squash_without_a_handle(self):
        r = self.state.append("contact", "No Handle Person", as_of="2026-08-16",
                              as_of_source="export:c", name="No Handle Person")
        self.assertEqual(r["key"], "nohandleperson")

    def test_a_display_name_or_email_is_never_mistaken_for_a_handle(self):
        # robustness: only an unambiguous slug becomes a handle key
        self.assertEqual(self.state.key_for("contact", "Jane Doe", linkedin="jane@x.com"), "janedoe")
        self.assertEqual(self.state.key_for("contact", "Jane Doe", linkedin="Jane Doe"), "janedoe")

    # ── dual-key readers ──
    def test_handle_row_is_found_by_name_plus_linkedin(self):
        self.state.append("contact", "Jane Doe", as_of="2026-08-16", as_of_source="export:c",
                          linkedin="https://www.linkedin.com/in/jane-doe", name="Jane Doe")
        importlib.reload(self.state)
        cur = self.state.current("contact", "Jane Doe",
                                 linkedin="linkedin.com/in/jane-doe")
        self.assertIsNotNone(cur)
        self.assertEqual(cur["key"], "li:jane-doe")

    def test_old_squash_row_still_resolves_by_name_only(self):
        self.state.append("contact", "Legacy Person", as_of="2026-08-15", as_of_source="export:o",
                          name="Legacy Person")
        importlib.reload(self.state)
        self.assertIsNotNone(self.state.current("contact", "Legacy Person"))

    def test_resolve_is_dual_key(self):
        self.state.append("contact", "Jane Doe", as_of="2026-08-16", as_of_source="export:c",
                          linkedin="https://www.linkedin.com/in/jane-doe", name="Jane Doe")
        importlib.reload(self.state)
        self.assertEqual(
            self.state.resolve("contact", "Jane Doe",
                               linkedin="https://www.linkedin.com/in/jane-doe"),
            "li:jane-doe")

    def test_the_two_key_spaces_do_not_cross_collide(self):
        # handle keys carry an "li:" prefix the bare-alphanumeric squash can never produce
        self.assertNotEqual(self.state.key_for("contact", "Jane Doe",
                                               linkedin="linkedin.com/in/jane-doe"),
                            self.state.key_for("contact", "Jane Doe"))

    def test_a_hyphenless_handle_does_not_merge_a_differently_named_person(self):
        # panel-found: without the li: prefix, a hyphenless handle "johnsmith" (here on Jane Doe's row)
        # would equal a DIFFERENT person "John Smith"'s squashed key and merge two humans. The prefix
        # keeps them disjoint, so a name-only lookup of "John Smith" can never land on the other row.
        bob = self.state.key_for("contact", "Jane Doe", linkedin="linkedin.com/in/johnsmith")
        robert = self.state.key_for("contact", "John Smith")   # no handle → squash
        self.assertEqual(bob, "li:johnsmith")
        self.assertEqual(robert, "johnsmith")
        self.assertNotEqual(bob, robert)

    # ── backward compatibility ──
    def test_credential_strip_and_no_linkedin_are_unchanged(self):
        self.assertEqual(self.state.key_for("contact", "Pamela Buchanan MD"),
                         self.state.key_for("contact", "Pamela Buchanan"))
        self.assertEqual(self.state.key_for("contact", "John Smith"), "johnsmith")


if __name__ == "__main__":
    unittest.main()
