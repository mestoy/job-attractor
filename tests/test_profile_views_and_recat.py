#!/usr/bin/env python3
"""BUG-181 WU-4 / WU-5 kit-parity mechanism tests.

Standard library only, no network, no file mutation of the live tree. These assert the MECHANISM
(not the shipped defaults, per [[a-test-over-a-configurable-knob-must-assert-the-mechanism]]):

  WU-4 — a profile view is a SURFACE. `load_profile_views` keys viewers by normalized name and
         degrades to {} when the store is absent; `parse_views.ingest` is idempotent (re-ingest of
         a batch adds ZERO rows — the kit issue #36 lesson).
  WU-5 — a `changed` verified title RE-CATEGORIZES a contact. The test asserts the READ path:
         `rank_people` classifies off the verified title, not the frozen export title.
"""
import importlib
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

rank_criteria = importlib.import_module("rank_criteria")
parse_views = importlib.import_module("parse_views")


class ProfileViewsLoader(unittest.TestCase):
    def test_absent_store_degrades_to_empty(self):
        self.assertEqual(rank_criteria.load_profile_views("/no/such/file.jsonl"), {})

    def test_a_view_is_keyed_by_normalized_name(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write('{"name":"Ada Boss","title":"VP Product","company":"Acme",'
                     '"view_date":"2026-08-12","ingested_on":"2026-08-13"}\n')
            path = fh.name
        self.addCleanup(os.unlink, path)
        views = rank_criteria.load_profile_views(path)
        self.assertIn("adaboss", views)
        self.assertEqual(views["adaboss"]["view_date"], "2026-08-12")

    def test_age_line_names_the_store(self):
        line = rank_criteria._profile_views_age_line({"adaboss": {"view_date": "2026-08-12"}})
        self.assertIn("profile-views", line)
        self.assertIn("not scored", line)
        self.assertEqual(rank_criteria._profile_views_age_line({}), "")


class IngestIdempotency(unittest.TestCase):
    def test_reingest_adds_zero_rows(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            path = fh.name
        self.addCleanup(os.unlink, path)
        open(path, "w").close()  # empty store
        rows = parse_views.parse_rows("name,title,company,date\nAda,VP Product,Acme,2026-08-12\n",
                                      batch="2026-08-13")
        new1, _ = parse_views.ingest(rows, batch="2026-08-13", path=path)
        self.assertEqual(len(new1), 1)
        new2, dups = parse_views.ingest(rows, batch="2026-08-13", path=path)
        self.assertEqual(len(new2), 0, "re-ingest of the same batch must add ZERO rows")
        self.assertEqual(dups, 1)


class RecatReadPath(unittest.TestCase):
    """WU-5: rank_people must classify off a still-current verified title, not the frozen export."""

    STALE = "Software Engineer"          # _person_category → other
    VERIFIED = "VP Product Management"   # is_pm + SENIOR → product-leader

    def _patch(self, verified_row):
        cs = rank_criteria.contact_signals
        saves = {}

        def save(obj, attr, val):
            saves[(obj, attr)] = getattr(obj, attr)
            setattr(obj, attr, val)

        save(rank_criteria, "_people_rows",
             lambda: [("Sam Switch", self.STALE, "SomeCo", "", "🟢 3y (2020-01-01)")])
        save(rank_criteria, "blocked_set", lambda: set())
        save(rank_criteria, "contacted_people", lambda: frozenset())
        save(rank_criteria, "contacted_addresses", lambda: [])
        save(rank_criteria, "_company_shape_map", lambda: {})
        save(rank_criteria, "live_weights",
             lambda *a, **k: {"per_category": {}, "founder_order": "last"})
        save(rank_criteria, "closeness_tier_lift", lambda: {})
        save(rank_criteria, "load_profile_views", lambda *a, **k: {})
        save(rank_criteria, "closeness", None)  # every closeness branch is guarded by `if closeness`
        if cs:
            save(cs, "verified_role", lambda name, cache=None: verified_row)
            save(cs, "segment_read", lambda *a, **k: ("unknown", None))
            save(cs, "employer_evidence", lambda *a, **k: (1, None))

        def restore():
            for (obj, attr), val in saves.items():
                setattr(obj, attr, val)
        self.addCleanup(restore)

    def _cat_of(self, name, ranked):
        return next((c["cat"] for c in ranked if c["name"] == name), None)

    def test_no_verification_uses_the_export_title(self):
        self._patch(verified_row=None)
        ranked, _ = rank_criteria.rank_people(1)
        self.assertEqual(self._cat_of("Sam Switch", ranked), "other")

    def test_a_changed_verified_title_recategorizes(self):
        self._patch(verified_row={"title": self.VERIFIED, "company": "SomeCo",
                                  "still_there": True, "verified_on": "2026-08-13"})
        ranked, _ = rank_criteria.rank_people(1)
        self.assertEqual(self._cat_of("Sam Switch", ranked), "product-leader",
                         "a changed verified title did NOT re-categorize — the read path is dead")
        why = " ".join(next(c["reasons"] for c in ranked if c["name"] == "Sam Switch"))
        self.assertIn("re-categorized on verified title", why)

    def test_an_ended_role_does_not_recategorize(self):
        self._patch(verified_row={"title": self.VERIFIED, "still_there": False,
                                  "verified_on": "2026-08-13"})
        ranked, _ = rank_criteria.rank_people(1)
        self.assertEqual(self._cat_of("Sam Switch", ranked), "other")


if __name__ == "__main__":
    unittest.main()
