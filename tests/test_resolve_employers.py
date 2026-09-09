#!/usr/bin/env python3
"""scripts/resolve_employers.py — aggregator-sourced segment verdicts must not land at top confidence.

Issue #34: `AGGREGATOR_DOMAINS` (boss_registry.py) demotes boss NAMES sourced from aggregators like
lusha.com, but resolve_employers.py had no equivalent path, so an employer-SEGMENT verdict sourced
from an aggregator landed at full ("stated") confidence — the same silent-trust gap boss_registry
already closed for names, just open on the employer side. The fix shares boss_registry's list rather
than copying it, so the two never drift.
"""
import argparse
import collections
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import resolve_employers as RE  # noqa: E402


class AggregatorDemotionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobattractor-resolve-")
        self.cache = os.path.join(self.tmp, "employer-segments.jsonl")
        self._real_cache = RE.CACHE
        RE.CACHE = self.cache

    def tearDown(self):
        RE.CACHE = self._real_cache

    def _ingest(self, rows):
        path = os.path.join(self.tmp, "in.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"employers": rows}, fh)
        # #36 landed after this test: cmd_ingest now gates on pool membership, and this fixture's
        # employers are not in the real rankable pool, so --add-employer keeps this test's scope
        # on the aggregator-demotion behavior it actually checks.
        args = argparse.Namespace(path=path, dry_run=False, add_employer=True)
        RE.cmd_ingest(args)
        out = []
        with open(self.cache, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.append(json.loads(line))
        return out

    def test_lusha_sourced_verdict_is_demoted_below_top_tier(self):
        rows = self._ingest([
            {"employer": "Acme Aggregated Co", "segment": "segment-a",
             "industry": "widgets", "source": "https://lusha.com/company/acme"},
        ])
        self.assertEqual(rows[0]["confidence"], "low")

    def test_company_domain_source_stays_top_tier(self):
        rows = self._ingest([
            {"employer": "Acme Direct Co", "segment": "segment-a",
             "industry": "widgets", "source": "https://acme.com/about"},
        ])
        self.assertNotEqual(rows[0]["confidence"], "low")


class BatchIdempotencyAndPoolGateTest(unittest.TestCase):
    """Issue #36: (1) every row written by one `ingest` call carries the same `batch` id, and two
    separate calls get different ids. (2) The store's natural key is the employer alone
    (`contact_signals._employer_key` — `load_employer_cache` indexes on it and "newest row wins",
    so segment is NOT part of the key; a corrected segment for an already-known employer is still
    an update, not a duplicate). Re-ingesting a byte-identical row (same segment/industry/source/
    confidence/country/note) is therefore a no-op: 0 added, N already present. (3) An employer
    absent from the rankable pool (`pool_employers()`) is refused with a clear message unless
    `--add-employer` is passed.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jobattractor-resolve-")
        self.cache = os.path.join(self.tmp, "employer-segments.jsonl")
        self._real_cache = RE.CACHE
        RE.CACHE = self.cache
        self._real_pool = RE.pool_employers
        RE.pool_employers = lambda: collections.Counter({"Acme Direct Co": 3, "Acme Aggregated Co": 1})

    def tearDown(self):
        RE.CACHE = self._real_cache
        RE.pool_employers = self._real_pool

    def _ingest(self, rows, add_employer=False, dry_run=False):
        path = os.path.join(self.tmp, "in.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"employers": rows}, fh)
        args = argparse.Namespace(path=path, dry_run=dry_run, add_employer=add_employer)
        RE.cmd_ingest(args)

    def _rows(self):
        out = []
        if not os.path.exists(self.cache):
            return out
        with open(self.cache, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.append(json.loads(line))
        return out

    def test_every_row_in_one_run_shares_a_batch_id(self):
        self._ingest([
            {"employer": "Acme Direct Co", "segment": "off-segment",
             "industry": "widgets", "source": "https://acme.com/about"},
            {"employer": "Acme Aggregated Co", "segment": "off-segment",
             "industry": "widgets", "source": "https://acme.com/about"},
        ])
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["batch"])
        self.assertEqual(rows[0]["batch"], rows[1]["batch"])

    def test_two_runs_get_different_batch_ids(self):
        self._ingest([{"employer": "Acme Direct Co", "segment": "off-segment",
                       "industry": "widgets", "source": "https://acme.com/about"}])
        self._ingest([{"employer": "Acme Aggregated Co", "segment": "off-segment",
                       "industry": "widgets", "source": "https://acme.com/about"}])
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["batch"], rows[1]["batch"])

    def test_reingesting_the_same_file_adds_zero_rows(self):
        row = {"employer": "Acme Direct Co", "segment": "off-segment",
               "industry": "widgets", "source": "https://acme.com/about"}
        self._ingest([row])
        self.assertEqual(len(self._rows()), 1)
        self._ingest([row])
        self.assertEqual(len(self._rows()), 1, "second ingest of the same row must be a no-op")

    def test_reingest_reports_zero_added_n_already_present(self):
        row = {"employer": "Acme Direct Co", "segment": "off-segment",
               "industry": "widgets", "source": "https://acme.com/about"}
        self._ingest([row])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self._ingest([row])
        out = buf.getvalue()
        self.assertIn("added: 0", out)
        self.assertIn("already present: 1", out)

    def test_a_corrected_segment_for_a_known_employer_still_lands(self):
        # Natural key is the employer, not employer+segment: a resend with a DIFFERENT segment is
        # a real update, not a duplicate, and must still be written (newest row wins on load).
        self._ingest([{"employer": "Acme Direct Co", "segment": "segment-a",
                       "industry": "widgets", "source": "https://acme.com/about"}])
        self._ingest([{"employer": "Acme Direct Co", "segment": "off-segment",
                       "industry": "widgets", "source": "https://acme.com/about"}])
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["segment"], "off-segment")

    def test_unknown_employer_is_refused_without_the_flag(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self._ingest([{"employer": "Nobody Heard Of This LLC", "segment": "off-segment",
                           "industry": "widgets", "source": "https://nobody.example/about"}])
        self.assertEqual(len(self._rows()), 0)
        self.assertIn("not in the pool", buf.getvalue())

    def test_unknown_employer_is_accepted_with_add_employer(self):
        rows_before = len(self._rows())
        self._ingest([{"employer": "Nobody Heard Of This LLC", "segment": "off-segment",
                       "industry": "widgets", "source": "https://nobody.example/about"}],
                      add_employer=True)
        rows = self._rows()
        self.assertEqual(len(rows), rows_before + 1)
        self.assertEqual(rows[-1]["employer"], "Nobody Heard Of This LLC")


if __name__ == "__main__":
    unittest.main()
