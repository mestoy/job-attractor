#!/usr/bin/env python3
"""backfill_linkedin_sends.py — put unlogged LinkedIn sends INTO the ladder, with their replies.

WHY THIS EXISTS. `reconcile_linkedin.py` MEASURES the gap between what the send log holds and what
LinkedIn says you actually sent, and it deliberately writes nothing, because its own docstring is
right that "backfilling is a separate, gated decision: a burn is correct for a real past send and
destructive on a mis-parse." This is that separate, gated decision, kept in its own script so the
instrument stays read-only.

The gap is not small for anyone who messages on LinkedIn. Sends made in the LinkedIn UI never pass
through mail-draft.sh, so nothing writes them a send-log row — which means the rung ladder measures
only the scripted channel and calls that your reply rate.

⚠️ THE TRAP THIS SCRIPT IS SHAPED AROUND. `reconcile_linkedin.py` finds SENDS. Sends are the
DENOMINATOR. Backfilling them alone mechanically drives the reply rate DOWN, and the number you land
on is not a humbler truth, it is a wrong one — the replies to those same threads are sitting in the
same export, equally unlogged, and they belong in the numerator. So this script never writes a send
without reading its thread for the answer. `--sends-only` exists to prove the difference, not to be
used.

⛔ SET THE WINDOW YOURSELF. `BACKFILL_SINCE` in scripts/kit_config.py ships BLANK and the script
refuses to run until you set it. That is deliberate. A LinkedIn export reaches back years, and
messages from an earlier search went to different people about different roles under different
conditions. Folding them in moves the rate you read every session while telling you nothing about the
search you are running now. Set it to the date THIS search began.

HOW A RUNG IS DECIDED, and it is EVIDENCE ONLY. Every rung below is read off the export, never
inferred from what a message looks like:

  invitation note      → `cold-stranger`. An invitation note is a rung 1-2 touch, and it is scored on
                         ACCEPTANCE rather than on a written reply.
  they wrote first     → `reply`. If the earliest message in the conversation is inbound, your
                         message answered it. That is a reply, and filing it as outreach would credit
                         you with initiating contact you did not initiate.
  you wrote first, and
  already connected    → `warm`. Connections.csv gives `Connected On`; connected on or before the
                         send date means a 1st-degree ask, rung 5-7.
  you wrote first, not
  yet connected        → `cold-stranger`.

⛔ NOTHING IS EVER FILED AS `cold-boss`, and that is the honest limit of this script. cold-boss is a
rung 3-4 ask to a person you believed was the hiring manager, and NOTHING in a LinkedIn export knows
what you believed at the time. Guessing it would corrupt the rung whose true rate matters most, since
cold-boss is usually where the volume goes. Backfilled cold outreach lands in `cold-stranger` and the
summary says so out loud. Every row carries a `backfill` field, so a later ruling can re-file them.

A REPLY means an inbound message in the SAME conversation, dated AFTER the send. Same-day inbound
counts, because the export's DATE carries a time and threads turn around inside a day.

DOUBLE-COUNT GUARD. A row is skipped when the log already holds that person on that date, by slug, by
raw recipient, or by the imported `sync_contacted` name rule. One row per person per DAY: a burst of
messages in one afternoon is one send, while a thread spanning three days is three. ⚠️ Send-log rows
that carry NO recipient identity cannot participate in this guard, so a small double count is
possible against those; the count is reported, never silently absorbed.

Usage:
    scripts/backfill_linkedin_sends.py                     # DRY RUN, writes nothing
    scripts/backfill_linkedin_sends.py --write             # append to documents/send-log.jsonl
    scripts/backfill_linkedin_sends.py --since 2026-01-01  # override the configured window
    scripts/backfill_linkedin_sends.py --until 2026-12-31  # upper bound, default none
    scripts/backfill_linkedin_sends.py --show              # every row it would write

Exit: 0 = clean (dry run, or written) · 1 = nothing to backfill · 2 = no window set
      3 = no export found
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
SENDLOG = os.path.join(REPO, "documents", "send-log.jsonl")
sys.path.insert(0, HERE)

# Reuse BY IMPORT, never by copy. Export resolution, slug handling and identity matching are all
# solved in reconcile_linkedin and sync_contacted, and a second copy of the identity rule is exactly
# how hand-rolled gap counts get the answer wrong.
from reconcile_linkedin import (  # noqa: E402
    _dict_rows,
    _invite_date,
    _owner,
    _pick_name,
    _read_text,
    load_sendlog,
    slug_of,
)
from sync_contacted import first_last, index_sendlog, match_sendlog  # noqa: E402

# The rung vocabulary belongs to the WRITER, never to this reader.
from log_linkedin_send import RUNGS  # noqa: E402

# The window comes from YOUR config, and it ships blank so the script refuses rather than guessing.
try:
    from kit_config import BACKFILL_SINCE as DEFAULT_SINCE
except ImportError:
    DEFAULT_SINCE = ""

# Lifted OUT of main() so both trees' main() bodies stay identical for kit_parity_check.
SINCE_HELP = "window start (default: BACKFILL_SINCE from kit_config.py)"

# The marker written onto every backfilled row. Two jobs: it makes the backfill reversible with a
# one-line filter, and it stops a future reader from mistaking a reconstructed row for one that
# mail-draft.sh wrote at the moment of sending.
BACKFILL_TAG = "linkedin-export"


def _drafted(row):
    return (row.get("IS MESSAGE DRAFT") or "").strip().lower() in ("true", "yes", "1")


def _conn_dates(export=None):
    """{slug: 'YYYY-MM-DD'} from Connections.csv, for the connected-at-send-time test.

    ⚠️ Connections.csv is NOT safe to hand to a naive DictReader: LinkedIn prepends a 3-line "Notes:"
    preamble that DictReader takes AS the header, so it silently yields nothing and every connection
    looks unknown. parse_network.parse_rows strips it; import that rather than re-solving it.
    """
    _p, text = _read_text("Connections.csv", export)
    if not text:
        return {}
    try:
        from parse_network import parse_rows
        rows = parse_rows(text)
    except ImportError:
        return {}
    out = {}
    for r in rows:
        s = slug_of(r.get("URL") or r.get("Url"))
        if not s:
            continue
        raw = (r.get("Connected On") or "").strip()
        for fmt in ("%d %b %Y", "%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y"):
            try:
                out[s] = datetime.strptime(raw, fmt).date().isoformat()
                break
            except ValueError:
                continue
    return out


def _utc_day(raw_ts):
    """messages.csv's DATE is UTC ("2026-08-02 02:36:15 UTC"). BUG-176: the double-count guard's
    join key used to be this string's first 10 characters — the UTC calendar day — compared against
    the send-log's LOCAL-ET `date` field. A send after 20:00 ET is already past midnight UTC, so it
    landed on the day AFTER the one log_linkedin_send.py stamped and every guard check missed it.
    Converts to the same local day the send log itself uses, via astimezone() reading the system
    timezone rather than hardcoding one, since that is what wrote the log rows to begin with.
    """
    try:
        dt = datetime.strptime(raw_ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return raw_ts[:10]
    return dt.astimezone().date().isoformat()


def threads(export=None):
    """(by_conv, owner). by_conv[conversation id] = [{slug, name, date, inbound}], date-sorted.

    Drafts are dropped: a draft never reached a human, which is the same rule NOT_DELIVERED encodes
    on the send-log side.
    """
    _p, text = _read_text("messages.csv", export)
    rows = _dict_rows(text)
    owner = _owner(rows)
    by_conv = {}
    for r in rows:
        if _drafted(r):
            continue
        conv = (r.get("CONVERSATION ID") or "").strip()
        date = (r.get("DATE") or "")[:19]
        inbound = (r.get("FROM") or "").strip() != owner
        field = "SENDER PROFILE URL" if inbound else "RECIPIENT PROFILE URLS"
        raw_name = (r.get("FROM") if inbound else r.get("TO")) or ""
        slugs = [s for s in (slug_of(u) for u in (r.get(field) or "").split(",")) if s]
        for s in slugs:
            by_conv.setdefault(conv, []).append({
                "slug": s, "name": _pick_name(raw_name, s), "date": date, "inbound": inbound,
            })
    for conv in by_conv:
        by_conv[conv].sort(key=lambda e: e["date"])
    return by_conv, owner


def _invitation_events(export=None):
    """Outbound invitations that CARRIED A NOTE. A bare connection request is not outreach."""
    _p, text = _read_text("Invitations.csv", export)
    out = []
    for r in _dict_rows(text):
        if not (r.get("Direction") or "").upper().startswith("OUTGOING"):
            continue
        if not (r.get("Message") or "").strip():
            continue
        s = slug_of(r.get("inviteeProfileUrl"))
        out.append({"slug": s or "", "name": (r.get("To") or "").strip(),
                    "date": _invite_date(r), "channel": "invitation note",
                    "conv": "", "replied": False})
    return out


def candidates(since, until=None, export=None):
    """Every outbound LinkedIn event in the window, one per (person, DAY), rung + reply decided.

    Deliberately does NOT reuse reconcile_linkedin.reconcile's `missing` list. That list dedups to ONE
    event per person, which is right for reporting "is this contact in the log at all" and wrong here:
    a thread spanning three days is three sends and belongs in the denominator three times.
    """
    by_conv, _owner_name = threads(export)
    conn = _conn_dates(export)
    events = {}

    for conv, msgs in by_conv.items():
        # Who spoke first decides `reply` vs outreach for EVERY message you sent in this thread.
        first_inbound = bool(msgs) and msgs[0]["inbound"]
        inbound_dates = [m["date"] for m in msgs if m["inbound"]]
        for m in msgs:
            if m["inbound"]:
                continue
            day = _utc_day(m["date"])
            if not day or day < since or (until and day > until):
                continue
            if first_inbound:
                rung = "reply"
            else:
                c = conn.get(m["slug"])
                rung = "warm" if (c and c <= day) else "cold-stranger"
            # A reply is an inbound message in the same thread AFTER this one. Compared on the full
            # timestamp, not the day: threads turn around inside an afternoon and a day-granular
            # test would credit a same-day answer to the wrong send, or miss it entirely.
            replied = any(d > m["date"] for d in inbound_dates)
            key = (m["slug"], day)
            prev = events.get(key)
            if prev is None or (replied and not prev["replied"]):
                events[key] = {"slug": m["slug"], "name": m["name"], "date": day,
                               "channel": "message", "conv": conv, "rung": rung,
                               "replied": replied}

    for e in _invitation_events(export):
        day = (e["date"] or "")[:10]
        if not day or day < since or (until and day > until):
            continue
        key = (e["slug"] or ("name:" + e["name"].lower()), day)
        if key not in events:
            # An accepted invitation is the reply, and Invitations.csv does not record acceptance.
            # Connections.csv does, so a connection dated on or after the note IS the acceptance.
            c = conn.get(e["slug"])
            events[key] = {**e, "rung": "cold-stranger", "replied": bool(c and c >= day)}

    return sorted(events.values(), key=lambda e: (e["date"], e["slug"]))


def _to_field(e):
    """What goes in the row's `to`. A profile URL when there is a slug, else the raw recipient.

    An invitation addressed to an email has no slug, and writing an EMPTY `to` would add another row
    to the identity-less rows this script already has to warn about.
    """
    if e["slug"]:
        return f"https://www.linkedin.com/in/{e['slug']}/"
    return (e["name"] or "").strip()


def already_logged(events, rows):
    """(fresh, skipped) — drop events the log already holds for that person on that DAY."""
    idx = index_sendlog(rows)
    by_slug_day, by_name_day, by_to_day = set(), set(), set()
    for r in rows:
        day = (r.get("date") or "")[:10]
        for field in ("to", "from"):
            raw = (r.get(field) or "").strip().lower()
            if raw:
                # RAW `to` EQUALITY, not just the slug. LinkedIn lets an invitation be addressed to
                # an EMAIL rather than a profile, and those events carry no slug at all — so a
                # slug-only guard cannot see them, so a second run re-appends them. Run it twice
                # before trusting it: that is the only way this class of bug shows up.
                by_to_day.add((raw, day))
            s = slug_of(raw)
            if s:
                by_slug_day.add((s, day))
        note = " ".join(str(r.get(k) or "") for k in ("to", "sent_note", "company"))
        for tok in re.findall(r"[A-Za-z][A-Za-z'\-]+ [A-Z][A-Za-z'\-]+", note):
            by_name_day.add((tok.lower(), day))

    fresh, skipped = [], []
    for e in events:
        if e["slug"] and (e["slug"], e["date"]) in by_slug_day:
            skipped.append((e, "slug already logged that day")); continue
        if (_to_field(e).lower(), e["date"]) in by_to_day:
            skipped.append((e, "recipient already logged that day")); continue
        if e["name"] and first_last(e["name"]) != (None, None):
            hit = match_sendlog(e["name"], idx)
            if hit is not None and (e["name"].lower(), e["date"]) in by_name_day:
                skipped.append((e, "name already logged that day")); continue
        fresh.append(e)
    return fresh, skipped


def _local_midnight_iso(day):
    """Midnight of `day` (a LOCAL calendar day, post-BUG-176) tagged with the system's ACTUAL utc
    offset. `day` used to be a UTC day, so hardcoding +00:00 was coherent; now that _utc_day()
    converts it to local before it reaches here, a hardcoded +00:00 would silently reintroduce the
    exact day-attribution bug this file exists to fix, one field over.
    """
    try:
        naive = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return f"{day}T00:00:00+00:00"
    return naive.astimezone().isoformat()


def to_row(e, sends_only=False):
    """One send-log row. Shape mirrors what mail-draft.sh writes, plus the backfill marker."""
    return {
        "ts": _local_midnight_iso(e["date"]),
        "date": e["date"],
        "rung": e["rung"],
        "to": _to_field(e),
        "company": "",
        "targets": "",
        "subject": "",
        "segment": "",
        "followup_due": "",
        "status": "sent",
        "replied": False if sends_only else bool(e["replied"]),
        "channel": "linkedin",
        "backfill": BACKFILL_TAG,
        "sent_note": (
            f"BACKFILL from LinkedIn export ({e['channel']}) for {e['name'] or e['slug']}. "
            f"Rung read from the export, not recalled: "
            + {"reply": "the other person wrote first in this thread",
               "warm": "you wrote first, already a 1st-degree connection",
               "cold-stranger": "you wrote first, not connected at the time"}[e["rung"]]
            + ". ⚠️ Never filed cold-boss: the export cannot know whether you believed this person "
              "was the hiring manager."
        ),
    }


def summarize(fresh, rows):
    """Before-and-after on the ladder, computed by rung_ladder so it cannot drift from the source."""
    import rung_ladder
    before, _ = rung_ladder.tally(rows)
    after, _ = rung_ladder.tally(rows + [to_row(e) for e in fresh])
    return before, after


def _rate(agg):
    s = sum(v[0] for v in agg.values())
    r = sum(v[1] for v in agg.values())
    return s, r, (100.0 * r / s if s else 0.0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backfill unlogged LinkedIn sends into the send log")
    ap.add_argument("--since", default=DEFAULT_SINCE, help=SINCE_HELP)
    ap.add_argument("--until", default=None, help="window end, inclusive")
    ap.add_argument("--export", default=None, help="export dir or .zip (default: newest)")
    ap.add_argument("--write", action="store_true", help="append the rows (default: dry run)")
    ap.add_argument("--show", action="store_true", help="print every row it would write")
    ap.add_argument("--sends-only", action="store_true",
                    help="write sends with replied=false, to show what the denominator alone costs")
    ap.add_argument("--path", default=SENDLOG, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    # A BLANK WINDOW REFUSES rather than defaulting. BACKFILL_SINCE ships blank on purpose, because
    # a wrong window silently rewrites the numbers you make decisions from.
    if not (a.since or "").strip():
        print("🔴 no backfill window set. A LinkedIn export reaches back years, and messages from an "
              "earlier search belong to a different search.\n"
              "   Set BACKFILL_SINCE in scripts/kit_config.py (or pass --since) to the date THIS "
              "search began.")
        return 2

    _p, mtext = _read_text("messages.csv", a.export)
    if not mtext:
        print("🔴 no LinkedIn export found (messages.csv). Nothing to reconcile.")
        return 3

    rows = load_sendlog(a.path)
    events = candidates(a.since, a.until, a.export)
    fresh, skipped = already_logged(events, rows)

    print(f"window: {a.since} .. {a.until or 'today'}")
    print(f"send log: {len(rows)} rows · export outbound events in window: {len(events)}")
    print(f"  already logged that day: {len(skipped)}   → to backfill: {len(fresh)}")
    if not fresh:
        print("✅ nothing to backfill in this window.")
        return 1

    by_rung = {}
    for e in fresh:
        slot = by_rung.setdefault(e["rung"], [0, 0])
        slot[0] += 1
        slot[1] += 1 if e["replied"] else 0
    print("\nrung breakdown of the backfill (read from the export):")
    for k in sorted(by_rung):
        s, r = by_rung[k]
        print(f"  {k:16} {s:4} sent  {r:3} replied   {(100.0*r/s if s else 0):5.1f}%")

    no_identity = sum(1 for r in rows if not (r.get("to") or "").strip()
                      and not (r.get("from") or "").strip())
    if no_identity:
        print(f"\n⚠️ {no_identity} logged rows carry NO recipient identity, so the double-count "
              f"guard cannot see them. A small overcount is possible against those rows only.")

    before, after = summarize(fresh, rows)
    bs, br, brate = _rate(before)
    as_, ar, arate = _rate(after)
    print(f"\nLADDER before: sent {bs} · replied {br} · {brate:.1f}%")
    print(f"LADDER after:  sent {as_} · replied {ar} · {arate:.1f}%")
    print(f"{'rung':18}{'before':>16}{'after':>16}")
    for k in sorted(set(before) | set(after)):
        b = before.get(k, [0, 0]); f = after.get(k, [0, 0])
        print(f"  {k:16}{b[0]:6}/{b[1]:<4}{'':4}{f[0]:6}/{f[1]:<4}")

    if a.show:
        print("\nrows:")
        for e in fresh:
            flag = "✅ replied" if e["replied"] else "  no reply"
            print(f"  {e['date']}  {e['rung']:14} {flag}  {e['name'][:28]:28} {e['slug']}")

    for e in fresh:
        assert e["rung"] in RUNGS, f"rung {e['rung']!r} is not in the writer's vocabulary"

    if not a.write:
        print("\n🔵 DRY RUN, nothing written. Re-run with --write to append.")
        return 0

    with open(a.path, "a", encoding="utf-8") as fh:
        for e in fresh:
            fh.write(json.dumps(to_row(e, a.sends_only), ensure_ascii=False) + "\n")
    print(f"\n✅ appended {len(fresh)} rows to {a.path}")
    print("   reversible: every row carries \"backfill\": \"" + BACKFILL_TAG + "\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
