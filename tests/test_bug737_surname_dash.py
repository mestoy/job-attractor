#!/usr/bin/env python3
"""BUG-737 (a) and BUG-738: check_boss_sourced.surname_rx in every tree (main, partner-starter, kit) cuts a credential or tagline the same way.

The rule (BUG-728 plus BUG-737, the same as check_dup._display_person): a comma or a dash with a space on at least one side ends the name
("Erin Fakerson- Empowering Leaders", "Erin Fakerson - ...", "Erin Fakerson -..."); a hyphen inside a surname ("Smith-Jones") stays; an apostrophe is optional
in the match ("O'Fakely"); a Jr/PhD-style suffix is not the surname. The module is loaded BY PATH from this tree's own scripts/, so a polluted
sys.path cannot swap in another tree's copy. Names are invented.   python3 -m unittest tests.test_bug737_surname_dash -v
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(HERE), "scripts", "check_boss_sourced.py")


def _load():
    spec = importlib.util.spec_from_file_location("check_boss_sourced_surname_under_test", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cbs = _load()


class SurnameRule(unittest.TestCase):
    def assertSurname(self, name, surname, not_surname):
        rx = cbs.surname_rx(name)
        self.assertIsNotNone(rx, name)
        self.assertTrue(rx.search("seat names %s as the boss" % surname), "%r should match %r" % (name, surname))
        self.assertIsNone(rx.search("a seat about %s" % not_surname), "%r must not match %r" % (name, not_surname))

    def test_a_dash_with_no_space_before_it_cuts_the_tagline(self):          # the real closeness shape
        self.assertSurname("Pat Fakely- Empowering Leaders", "Fakely", "Leaders")

    def test_a_dash_with_no_space_after_it_cuts_the_tagline(self):
        self.assertSurname("Pat Fakely -Empowering Leaders", "Fakely", "Leaders")

    def test_a_spaced_dash_still_cuts_it(self):
        self.assertSurname("Pat Fakely - Empowering Leaders", "Fakely", "Leaders")

    def test_a_hyphenated_surname_is_not_cut(self):
        rx = cbs.surname_rx("Pat Fakely-Testcase")
        self.assertTrue(rx.search("Fakely-Testcase leads it"))
        self.assertIsNone(rx.search("Fakely leads it"))

    def test_a_comma_credential_still_cuts(self):
        self.assertSurname("Pat Fakely, MBA", "Fakely", "MBA")

    def test_an_apostrophe_surname_matches_as_written_or_without(self):       # BUG-728
        rx = cbs.surname_rx("Pat O'Fakely")
        for text in ("O'Fakely owns it", "O’Fakely owns it", "OFakely owns it"):
            with self.subTest(text=text):
                self.assertTrue(rx.search(text))

    def test_a_credential_suffix_is_not_the_surname(self):                    # BUG-728
        rx = cbs.surname_rx("Pat Fakely Jr.")
        self.assertTrue(rx.search("Fakely owns it"))
        self.assertIsNone(rx.search("a seat about Jr"))

    def test_a_common_word_surname_matches_only_as_a_word(self):
        rx = cbs.surname_rx("Sam White")
        self.assertIsNone(rx.search("white-label is their whole model"))
        self.assertTrue(rx.search("White owns the roadmap"))


if __name__ == "__main__":
    unittest.main()
