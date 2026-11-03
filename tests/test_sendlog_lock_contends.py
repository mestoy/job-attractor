#!/usr/bin/env python3
"""BUG-687: two processes each run 50 read-modify-write cycles on one send log. With the lock the log has all 100 rows, none twice, none lost. Without it (the control) rows are
lost, which is what proves this test CAN fail: an empty check passes.
Run: python3 -m unittest tests.test_sendlog_lock_contends
"""
import json
import multiprocessing
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import sendlog_lock as sl   # noqa: E402

TMP = os.environ.get("SJ_TMP") or os.path.join(os.path.expanduser("~"), "render", "sendlog-tmp")  # never /tmp and never a sibling of the tree
os.makedirs(TMP, exist_ok=True)
CYCLES = 50


def cycle(path, who, n, use_lock):
    """One cycle: read the whole log, add this process's row, write it back whole and atomically."""
    def body():
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()] if os.path.exists(path) else []
        rows.append({"to": "%s-%d@zz.example" % (who, n), "date": "2026-10-20", "ts": "%s%04d" % (who, n)})
        sl.atomic_write_rows(path, rows)
    if use_lock:
        with sl.locked(path, timeout=30):
            body()
    else:
        body()


def worker(path, who, use_lock):
    for n in range(CYCLES):
        cycle(path, who, n, use_lock)


class Contention(unittest.TestCase):
    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        self.d = tempfile.mkdtemp(prefix="contend-", dir=TMP)
        self.addCleanup(shutil.rmtree, self.d, True)
        self.path = os.path.join(self.d, "documents", "send-log.jsonl")
        os.makedirs(os.path.dirname(self.path))

    def run_pair(self, use_lock):
        ctx = multiprocessing.get_context("fork")
        ps = [ctx.Process(target=worker, args=(self.path, who, use_lock)) for who in ("a", "b")]
        for p in ps:
            p.start()
        for p in ps:
            p.join(120)
            self.assertEqual(0, p.exitcode)
        return [json.loads(l)["to"] for l in open(self.path, encoding="utf-8") if l.strip()]

    def test_with_the_lock_all_one_hundred_rows_land_once(self):
        got = self.run_pair(True)
        self.assertEqual(2 * CYCLES, len(got))
        self.assertEqual(2 * CYCLES, len(set(got)))

    def test_control_without_the_lock_rows_are_lost(self):
        lost = 0
        for _ in range(5):                                       # a lost update is a race; five rounds make the control reliable
            if os.path.exists(self.path):
                os.remove(self.path)
            lost += 2 * CYCLES - len(set(self.run_pair(False)))
            if lost:
                break
        self.assertGreater(lost, 0, "the control lost nothing, so the contention test could not fail")


if __name__ == "__main__":
    unittest.main()
