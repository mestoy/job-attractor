#!/usr/bin/env python3
"""local_day.py -- the ONE send day (BUG-795).

Every send-log writer stamped `date` with the machine's own calendar (date.today()), and the backfill guard
(BUG-176) converted a UTC timestamp to that same machine calendar. On a Mac in ET they agree. On a UTC
container a 23:30 ET send is already tomorrow, so the two machines disagree about which day a late send
belongs to, and the guard double-writes it.

This reads kit_config.SCORES_TIMEZONE (an IANA name such as "America/New_York") for BOTH sides. Empty, unset
or unknown means this machine's own zone, so an install that never set it keeps today's behavior. A clock
must never crash a writer: nothing here raises.

    python3 scripts/local_day.py        # prints today's day in the configured zone (mail-draft.sh uses it)

LOCAL_DAY_NOW (an ISO instant) pins "now" for tests only; nothing in production sets it."""
import datetime
import os
import sys
import zoneinfo


def configured_zone_name():
    here = os.path.dirname(os.path.abspath(__file__))
    added = here not in sys.path          # scoped: this folder is on the path only while kit_config loads
    if added:
        sys.path.insert(0, here)
    try:
        from kit_config import SCORES_TIMEZONE
        return str(SCORES_TIMEZONE or "").strip()
    except Exception:
        return ""
    finally:
        if added and here in sys.path:
            sys.path.remove(here)


def zone():
    name = configured_zone_name()
    if name:
        try:
            return zoneinfo.ZoneInfo(name)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
            pass
    return datetime.datetime.now().astimezone().tzinfo


def _now():
    pinned = os.environ.get("LOCAL_DAY_NOW", "").strip()
    if pinned:
        try:
            dt = datetime.datetime.fromisoformat(pinned.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.astimezone()
        except ValueError:
            pass
    return datetime.datetime.now().astimezone()


def today():
    """Today's YYYY-MM-DD in the configured zone."""
    return _now().astimezone(zone()).date().isoformat()


def day_of(value):
    """The YYYY-MM-DD an instant falls on in the configured zone, or "" when it cannot be read.

    `value` is a datetime, an ISO string, or messages.csv's "2026-08-02 02:36:15 UTC". A naive time is read
    as this machine's own zone (that is what wrote it)."""
    try:
        if isinstance(value, datetime.datetime):
            dt = value
        else:
            s = str(value or "").strip()
            if s.endswith(" UTC"):
                s = s[:-4].strip() + "+00:00"
            dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(zone()).date().isoformat()
    except Exception:
        return ""


if __name__ == "__main__":
    print(today())
