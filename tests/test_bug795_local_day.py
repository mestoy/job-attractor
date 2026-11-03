#!/usr/bin/env python3
"""BUG-795: one send day, read from kit_config.SCORES_TIMEZONE, for every send-log writer and the backfill
guard. A 23:30 ET send is 03:30 UTC the next day: it must be logged, and recognized as logged, on the ET day
whether the machine is a Mac in ET or a UTC container. Old rows are never rewritten; the guard also reads a
row's `ts` in the configured zone so a legacy UTC-day row still dedupes.

Fixtures only: a scratch project dir and a scratch send log, never the live ones. Every name is invented.
Each case runs in a child process under TZ=UTC AND TZ=America/New_York."""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
# Run against a COPY of the scripts folder whose kit_config names the ET zone, so the result does not depend on
# which install this tree is (the kit ships SCORES_TIMEZONE empty). The live tree is never touched.
_COPY = tempfile.mkdtemp(prefix="b795s-")
atexit.register(shutil.rmtree, _COPY, True)
SCRIPTS = os.path.join(_COPY, "scripts")
shutil.copytree(REAL_SCRIPTS, SCRIPTS, ignore=shutil.ignore_patterns("__pycache__"))
_PS = os.path.join(os.path.dirname(REAL_SCRIPTS), "partner-starter", "scripts")
if os.path.isdir(_PS):                         # rung_ladder loads board.py from the partner-starter folder in the private tree
    shutil.copytree(_PS, os.path.join(_COPY, "partner-starter", "scripts"), ignore=shutil.ignore_patterns("__pycache__"))
_cfg = os.path.join(SCRIPTS, "kit_config.py")
if not os.path.exists(_cfg):                  # the kit repo ships kit_config.example.py; an install copies it
    shutil.copy(os.path.join(SCRIPTS, "kit_config.example.py"), _cfg)
_src = open(_cfg, encoding="utf-8").read()
_zoned, _n = re.subn(r'(?m)^SCORES_TIMEZONE = .*$', 'SCORES_TIMEZONE = "America/New_York"', _src)
open(_cfg, "w", encoding="utf-8").write(_zoned if _n else _src + '\nSCORES_TIMEZONE = "America/New_York"\n')
LATE = "2026-08-04T03:30:00+00:00"      # 23:30 ET on 2026-08-03
ET_DAY, UTC_DAY = "2026-08-03", "2026-08-04"
PROFILE = "https://www.linkedin.com/" + "in/" + "zorblat-fakeperson"   # built, so no profile URL sits in the source
ZONES = ("UTC", "America/New_York")


def child(code, tz, extra_env=None):
    env = dict(os.environ, TZ=tz, LOCAL_DAY_NOW=LATE, PYTHONDONTWRITEBYTECODE="1")
    env.update(extra_env or {})
    return subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\n%s" % (SCRIPTS, code)],
                          capture_output=True, text=True, env=env, timeout=60)


class ZonesCase(unittest.TestCase):
    def each_zone(self, fn):
        for tz in ZONES:
            with self.subTest(tz=tz):
                fn(tz)


class LocalDayHelper(ZonesCase):
    def test_today_is_the_et_day_on_both_machines(self):
        def check(tz):
            r = child("import local_day; print(local_day.today())", tz)
            self.assertEqual(r.stdout.strip(), ET_DAY, r.stderr)
        self.each_zone(check)

    def test_day_of_converts_a_utc_instant(self):
        def check(tz):
            r = child("import local_day as l; print(l.day_of('2026-08-04 03:30:00 UTC'), l.day_of('%s'), l.day_of('junk'))" % LATE, tz)
            self.assertEqual(r.stdout.split(), [ET_DAY, ET_DAY], r.stderr)
        self.each_zone(check)

    def test_unset_or_unknown_zone_falls_back_to_the_machine_zone(self):
        def check(tz):
            for name in ("", "Not/AZone"):
                r = child("import kit_config, local_day; kit_config.SCORES_TIMEZONE = %r\n"
                          "print(local_day.today())" % name, tz)
                want = UTC_DAY if tz == "UTC" else ET_DAY
                self.assertEqual(r.stdout.strip(), want, (name, r.stderr))
        self.each_zone(check)


class WriterStampsTheEtDay(ZonesCase):
    def test_linkedin_row_date(self):
        def check(tz):
            d = tempfile.mkdtemp(prefix="b795-")
            log = os.path.join(d, "send-log.jsonl")
            open(log, "w").close()
            def run(segment):
                return subprocess.run([sys.executable, os.path.join(SCRIPTS, "log_linkedin_send.py"), "--rung", "cold-stranger",
                                       "--to", PROFILE, "--path", log, "--note", "fixture",
                                       "--company", "Fakeco", "--segment", segment, "--no-followup", "--dry-run"],
                                      capture_output=True, text=True, timeout=60, cwd=d,
                                      env=dict(os.environ, TZ=tz, LOCAL_DAY_NOW=LATE, CLAUDE_PROJECT_DIR=d, HOME=d))
            r = run("govtech")
            canon = re.search(r"One of: ([\w-]+)", r.stdout + r.stderr)   # an install names its own segments
            if canon:
                r = run(canon.group(1))
            m = re.search(r'"date":\s*"([\d-]+)"', r.stdout)
            self.assertTrue(m, r.stdout + r.stderr)
            self.assertEqual(m.group(1), ET_DAY)
            self.assertEqual(open(log).read(), "", "dry run wrote the log")
        self.each_zone(check)

    def test_no_writer_still_reads_the_machine_calendar(self):
        for name in ("log_linkedin_send.py", "mail-draft.sh"):
            src = open(os.path.join(REAL_SCRIPTS, name), encoding="utf-8").read()
            for m in re.finditer(r'"date":\s*datetime\.date\.today\(\)', src):
                self.fail("%s still stamps a row date from date.today()" % name)
        src = open(os.path.join(REAL_SCRIPTS, "mail-draft.sh"), encoding="utf-8").read()
        self.assertNotIn("_TODAY=\"$(date '+%Y-%m-%d')\"", src)


class BackfillGuard(ZonesCase):
    ROW = {"ts": "2026-08-04T03:30:00+00:00", "date": UTC_DAY, "to": PROFILE,
           "channel": "linkedin", "status": "sent"}

    def event(self, day):
        return {"slug": "zorblat-fakeperson", "name": "Zorblat Fakeperson", "date": day}

    def guard(self, tz, rows, day):
        code = ("import json, backfill_linkedin_sends as b\n"
                "rows = json.loads(%r); ev = json.loads(%r)\n"
                "fresh, skipped = b.already_logged([ev], rows)\n"
                "print(len(fresh), len(skipped))") % (json.dumps(rows), json.dumps(self.event(day)))
        r = child(code, tz)
        return r.stdout.split(), r.stderr

    def test_a_legacy_utc_day_row_still_dedupes_the_et_day_candidate(self):
        def check(tz):
            out, err = self.guard(tz, [self.ROW], ET_DAY)
            self.assertEqual(out, ["0", "1"], err)
        self.each_zone(check)

    def test_a_row_stamped_with_the_et_day_dedupes_it(self):
        def check(tz):
            out, err = self.guard(tz, [dict(self.ROW, date=ET_DAY)], ET_DAY)
            self.assertEqual(out, ["0", "1"], err)
        self.each_zone(check)

    def test_a_different_day_is_not_deduped(self):
        def check(tz):
            out, err = self.guard(tz, [self.ROW], "2026-07-30")
            self.assertEqual(out, ["1", "0"], err)
        self.each_zone(check)

    def test_the_guard_day_key_matches_the_writer_day(self):
        def check(tz):
            r = child("import backfill_linkedin_sends as b; print(b._utc_day('2026-08-04 03:30:00 UTC'))", tz)
            self.assertEqual(r.stdout.strip(), ET_DAY, r.stderr)
        self.each_zone(check)


class ReadersCountTheDayTheWritersStamp(ZonesCase):
    """2e B1: the 3-3-3 counter and the LADDER stamp asked for the machine's day while the writers stamped the ET
    day, so from 20:00 ET to midnight a UTC container counted 0 for a send it had just logged."""

    def test_a_row_written_by_the_logger_is_counted_by_the_pair_readers(self):
        def check(tz):
            d = _COPY                              # the project root the copied scripts belong to
            try:
                os.makedirs(os.path.join(d, "documents"), exist_ok=True)
                log = os.path.join(d, "documents", "send-log.jsonl")
                if os.path.exists(log):
                    os.remove(log)
                env = dict(os.environ, TZ=tz, LOCAL_DAY_NOW=LATE, CLAUDE_PROJECT_DIR=d, HOME=d)

                def write(segment):
                    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "log_linkedin_send.py"), "--rung", "cold-stranger",
                                           "--to", PROFILE, "--path", log, "--note", "fixture", "--company", "Fakeco",
                                           "--segment", segment, "--no-followup"],
                                          capture_output=True, text=True, timeout=60, cwd=d, env=env)
                w = write("govtech")
                canon = re.search(r"One of: ([\w-]+)", w.stdout + w.stderr)
                if canon:
                    w = write(canon.group(1))
                self.assertIn('"date": "%s"' % ET_DAY, open(log, encoding="utf-8").read(), w.stdout + w.stderr)
                code = ("import pair_brief as p\n"
                        "print(p.sends_today_logged(repo=%r))\n"
                        "print(p.stamp(repo=%r))") % (d, d)
                r = child(code, tz, {"CLAUDE_PROJECT_DIR": d, "HOME": d})
                lines = r.stdout.strip().splitlines()
                self.assertEqual(lines[0], "1", r.stdout + r.stderr)
                self.assertIn("LADDER " + ET_DAY, lines[1])
                self.assertIn("3-3-3 1/3", lines[1])
            finally:
                if os.path.exists(log):
                    os.remove(log)
        self.each_zone(check)

    def test_session_start_and_the_resend_stamp_use_the_same_day(self):
        def check(tz):
            r = child("import sendlog_lock as s, session_start as t\nprint(s._send_day(), t._send_day())", tz,
                      {"CLAUDE_PROJECT_DIR": tempfile.gettempdir()})
            self.assertEqual(r.stdout.split(), [ET_DAY, ET_DAY], r.stdout + r.stderr)
        self.each_zone(check)


class ConsistencyCheckCountsTheWritersDay(ZonesCase):
    """2e E1: consistency-check [13] is a third 3-3-3 counter over the send-log `date`."""

    def test_block_13_counts_a_row_written_on_the_et_day(self):
        src = open(os.path.join(REAL_SCRIPTS, "consistency-check.sh"), encoding="utf-8").read()
        m = re.search(r"<<'PY313'\n(.*?)\nPY313", src, re.S)
        self.assertTrue(m, "block [13] not found")

        def check(tz):
            d = tempfile.mkdtemp(prefix="b795c-")
            try:
                os.makedirs(os.path.join(d, "documents"))
                shutil.copytree(SCRIPTS, os.path.join(d, "scripts"), ignore=shutil.ignore_patterns("__pycache__"))
                with open(os.path.join(d, "documents", "send-log.jsonl"), "w", encoding="utf-8") as fh:
                    fh.write(json.dumps({"date": ET_DAY, "status": "sent", "rung": "cold-stranger", "to": "a@example.com"}) + "\n")
                r = subprocess.run([sys.executable, "-c", m.group(1)], capture_output=True, text=True, timeout=60, cwd=d,
                                   env=dict(os.environ, TZ=tz, LOCAL_DAY_NOW=LATE, HOME=d))
                self.assertIn("sent today: 1/3", r.stdout, r.stdout + r.stderr)
            finally:
                shutil.rmtree(d, ignore_errors=True)
        self.each_zone(check)


class APartialCopyStillRuns(unittest.TestCase):
    """A copy of scripts/ without local_day.py (a test sandbox, a partner's partial sync) must not crash a writer."""

    def test_writers_import_and_fall_back_to_the_machine_day(self):
        d = tempfile.mkdtemp(prefix="b795p-")
        try:
            part = os.path.join(d, "scripts")
            shutil.copytree(SCRIPTS, part, ignore=shutil.ignore_patterns("__pycache__", "local_day.py"))
            code = ("import sys; sys.path.insert(0, %r)\n"
                    "import log_linkedin_send as l, backfill_linkedin_sends as b\n"
                    "print(l._local_day.today(), b._utc_day('2026-08-04 03:30:00 UTC'))") % part
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                               env=dict(os.environ, TZ="America/New_York", CLAUDE_PROJECT_DIR=d, HOME=d))
            self.assertEqual(r.stdout.split()[1:], [ET_DAY], r.stdout + r.stderr)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
