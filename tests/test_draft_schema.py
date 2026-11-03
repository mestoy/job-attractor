#!/usr/bin/env python3
"""Red-first tests for scripts/draft_schema.py, the shared app-draft contract (seats S1 to S5).

The contract lives in app/design/draft_schema.md. validate(doc) returns a list of plain
problems; an empty list means the draft may be written and read.
"""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import draft_schema  # noqa: E402


def _opt(text, s=(22, 21, 22, 22), url=None):
    scores = dict(zip(("cpo", "cto", "ceo", "rise8"), s))
    return {"text": text, "scores": scores, "total": sum(s), "source_url": url}


def valid_doc():
    return {
        "schema": 1,
        "slug": "harbor-vale-priya",
        "company": "Harbor & Vale",
        "prepared_at": "2026-09-15T20:00:00Z",
        "rung": "cold-boss",
        "to_name": "Priya",
        "to_title": "VP Product",
        "boss_verified": True,
        "thesis": {"prompt": "Why are you writing to Priya?",
                   "options": [_opt("Harbor & Vale is moving freight onto one ledger.")],
                   "chosen": 0},
        "subject": {"options": [_opt("Quick thought on Harbor & Vale"),
                                _opt("The ledger move", (18, 18, 18, 18))],
                    "chosen": 0},
        "beats": [
            {"name": "greeting", "label": "Hello", "options": [_opt("Hi, Priya!")],
             "chosen": 0, "freeform_allowed": True},
            {"name": "praise", "label": "What you like",
             "options": [_opt("I like that you put carriers on one ledger.",
                              url="https://example.invalid/harbor/ledger")],
             "chosen": 0, "freeform_allowed": True},
        ],
        "body": "Hi, Priya!\n\nI like that you put carriers on one ledger.\n\n\nYou\nhttps://www.yoursite.example",
        "checks": {"outreach": "pass", "praise_sourced": True, "honesty": "pass", "notes": []},
        "resume": None,
    }


class ValidDoc(unittest.TestCase):
    def test_the_reference_doc_is_valid(self):
        self.assertEqual(draft_schema.validate(valid_doc()), [])

    def test_a_resume_block_is_valid(self):
        d = valid_doc()
        d["resume"] = {"filename": "Your Name - Resume - Harbor & Vale.pdf", "verify": "green",
                       "asset_url": None}
        self.assertEqual(draft_schema.validate(d), [])

    def test_not_a_dict(self):
        self.assertTrue(draft_schema.validate([]))
        self.assertTrue(draft_schema.validate(None))


class RequiredFields(unittest.TestCase):
    def test_each_required_top_level_field_omitted_is_rejected(self):
        for key in draft_schema.TOP_KEYS:
            d = valid_doc()
            del d[key]
            errs = draft_schema.validate(d)
            self.assertTrue(errs, "omitting %s passed" % key)
            self.assertTrue(any(key in e for e in errs), (key, errs))

    def test_each_opt_field_omitted_is_rejected(self):
        for key in ("text", "scores", "total", "source_url"):
            d = valid_doc()
            del d["subject"]["options"][0][key]
            self.assertTrue(draft_schema.validate(d), "omitting option %s passed" % key)

    def test_each_seat_score_omitted_is_rejected(self):
        for seat in ("cpo", "cto", "ceo", "rise8"):
            d = valid_doc()
            del d["subject"]["options"][0]["scores"][seat]
            self.assertTrue(draft_schema.validate(d), "omitting %s passed" % seat)

    def test_each_beat_field_omitted_is_rejected(self):
        for key in ("name", "label", "options", "chosen", "freeform_allowed"):
            d = valid_doc()
            del d["beats"][0][key]
            self.assertTrue(draft_schema.validate(d), "omitting beat %s passed" % key)

    def test_each_checks_field_omitted_is_rejected(self):
        for key in ("outreach", "praise_sourced", "honesty", "notes"):
            d = valid_doc()
            del d["checks"][key]
            self.assertTrue(draft_schema.validate(d), "omitting checks.%s passed" % key)

    def test_thesis_prompt_omitted_is_rejected(self):
        d = valid_doc()
        del d["thesis"]["prompt"]
        self.assertTrue(draft_schema.validate(d))

    def test_resume_fields_omitted_are_rejected(self):
        for key in ("filename", "verify", "asset_url"):
            d = valid_doc()
            d["resume"] = {"filename": "x.pdf", "verify": "green", "asset_url": None}
            del d["resume"][key]
            self.assertTrue(draft_schema.validate(d), "omitting resume.%s passed" % key)


class Values(unittest.TestCase):
    def test_chosen_out_of_range_is_rejected(self):
        for path, bads in (("thesis", (1, -1, 5)), ("subject", (2, -1, 5))):
            for bad in bads:
                d = valid_doc()
                d[path]["chosen"] = bad
                self.assertTrue(draft_schema.validate(d), (path, bad))
        d = valid_doc()
        d["beats"][0]["chosen"] = 1
        self.assertTrue(draft_schema.validate(d))

    def test_chosen_bool_is_not_an_int(self):
        d = valid_doc()
        d["thesis"]["chosen"] = False
        self.assertTrue(draft_schema.validate(d))

    def test_empty_options_are_rejected(self):
        d = valid_doc()
        d["thesis"]["options"] = []
        self.assertTrue(draft_schema.validate(d))

    def test_total_must_equal_the_sum_of_the_seats(self):
        d = valid_doc()
        d["subject"]["options"][0]["total"] = 99
        self.assertTrue(draft_schema.validate(d))

    def test_seat_scores_stay_on_the_0_to_25_scale(self):
        d = valid_doc()
        o = d["subject"]["options"][0]
        o["scores"]["cpo"] = 30
        o["total"] = sum(o["scores"].values())
        self.assertTrue(draft_schema.validate(d))

    def test_check_values_are_closed_vocabularies(self):
        d = valid_doc()
        d["checks"]["outreach"] = "ok"
        self.assertTrue(draft_schema.validate(d))
        d = valid_doc()
        d["resume"] = {"filename": "x.pdf", "verify": "yellow", "asset_url": None}
        self.assertTrue(draft_schema.validate(d))

    def test_prepared_at_must_be_utc_iso(self):
        for bad in ("2026-09-15", "yesterday", "2026-09-15T20:00:00-04:00"):
            d = valid_doc()
            d["prepared_at"] = bad
            self.assertTrue(draft_schema.validate(d), bad)

    def test_schema_version_is_one(self):
        d = valid_doc()
        d["schema"] = 2
        self.assertTrue(draft_schema.validate(d))

    def test_empty_body_is_rejected(self):
        d = valid_doc()
        d["body"] = ""
        self.assertTrue(draft_schema.validate(d))

    def test_source_url_must_be_a_web_link(self):
        d = valid_doc()
        d["beats"][1]["options"][0]["source_url"] = "company blog"
        self.assertTrue(draft_schema.validate(d))


class Order(unittest.TestCase):
    def test_thesis_must_come_before_subject_and_beats(self):
        d = valid_doc()
        reordered = {k: d[k] for k in d if k != "thesis"}
        reordered["thesis"] = d["thesis"]
        errs = draft_schema.validate(reordered)
        self.assertTrue(any("thesis" in e for e in errs), errs)


class NoAddress(unittest.TestCase):
    def test_an_at_sign_anywhere_is_rejected(self):
        spots = [
            lambda d: d.__setitem__("to_name", "priya@harbor.example"),
            lambda d: d["beats"][0]["options"][0].__setitem__("text", "Hi, priya@x.example!"),
            lambda d: d["checks"]["notes"].append("to: a@b.example"),
            lambda d: d.__setitem__("body", d["body"] + " a@b.example"),
        ]
        for put in spots:
            d = valid_doc()
            put(d)
            errs = draft_schema.validate(d)
            self.assertTrue(any("@" in e for e in errs), errs)

    def test_a_to_email_key_is_rejected(self):
        d = valid_doc()
        d["to_email"] = "hidden"
        self.assertTrue(draft_schema.validate(d))


class Praise(unittest.TestCase):
    def test_a_praise_option_without_a_source_is_rejected(self):
        d = valid_doc()
        d["beats"][1]["options"][0]["source_url"] = None
        self.assertTrue(draft_schema.validate(d))

    def test_praise_sourced_must_match_whether_a_praise_beat_exists(self):
        d = valid_doc()
        d["checks"]["praise_sourced"] = False
        self.assertTrue(draft_schema.validate(d))
        d = valid_doc()
        d["beats"] = d["beats"][:1]
        self.assertTrue(draft_schema.validate(d))
        d["checks"]["praise_sourced"] = False
        self.assertEqual(draft_schema.validate(d), [])


class NoMutation(unittest.TestCase):
    def test_validate_never_changes_the_doc(self):
        d = valid_doc()
        before = copy.deepcopy(d)
        draft_schema.validate(d)
        self.assertEqual(d, before)


if __name__ == "__main__":
    unittest.main()
