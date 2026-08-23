#!/usr/bin/env python3
"""reconcile_linkedin.py — does the send log agree with what LinkedIn says actually happened?

WHY THIS EXISTS (2026-07-26). The send log is the denominator for every rung statistic, so a send
that never got a row inflates the reply rate. Until a full LinkedIn export was compared against it,
the size of the gap is unknown. Hand-rolled attempts to measure it tend to fail the same way: they
key on ONE spelling of the recipient and report rows as missing that were logged under another,
which overstates the gap by a wide margin and invites a backfill that duplicates existing rows.

So the instrument itself has to be careful about identity, and it must never collapse three very
different disagreements into one number:

  MISSING SEND      an outbound event in the export with no send-log row. A real gap.
  IDENTITY MISMATCH a send-log row whose handle does not exist on LinkedIn. The send HAPPENED;
                    the row points at nobody. These are invisible to a naive "is it logged" check
                    because the row is right there, and they are why reply and send can end up
                    filed under two different keys for the same person.
  EXPORT LAG        logged after the export snapshot. NOT a gap, and reporting it as one trains
                    the reader to ignore the output.

⛔ READ-ONLY. This script writes nothing, burns no target, and arms no follow-up. Backfilling is a
separate, gated decision: a burn is correct for a real past send and destructive on a mis-parse.

Identity matching is NOT reimplemented here. It is imported from sync_contacted, which already
carries a first-AND-last-token rule that avoids substring false positives (a two-token contact name
must not match an unrelated surname). Reuse BY IMPORT, never by copy.

Usage:
    scripts/reconcile_linkedin.py                # auto-find the newest export
    scripts/reconcile_linkedin.py --export DIR   # explicit export dir or .zip
    scripts/reconcile_linkedin.py --since DATE   # window for outbound events (default 2026-07-01)
    scripts/reconcile_linkedin.py --quiet        # counts only

Exit: 0 = no MISSING/MISMATCH findings · 1 = findings · 3 = no export found
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
SENDLOG = os.path.join(REPO, "documents", "send-log.jsonl")
sys.path.insert(0, HERE)

# A LinkedIn message body can be far longer than the csv default field cap.
csv.field_size_limit(10 ** 7)

from sync_contacted import (  # noqa: E402  (path must be set first)
    _slug_from_to,
    first_last,
    index_sendlog,
    match_sendlog,
)

DEFAULT_SINCE = "2026-07-01"


def _owner(rows):
    """Whose export is this? Derived from the data, never hardcoded.

    parse_messages already solves this: the owner is the most frequent FROM across the whole file,
    because they appear in every conversation and nobody else does. Reuse BY IMPORT
    — a hardcoded name here would silently invert "sent" and "received" for
    anyone else's export, and would be a literal PII string in a file destined for the shared kit.
    """
    try:
        from parse_messages import _owner_names
        return _owner_names(rows)
    except ImportError:
        counts = {}
        for r in rows:
            f = (r.get("FROM") or "").strip()
            if f:
                counts[f] = counts.get(f, 0) + 1
        return max(counts, key=counts.get) if counts else ""


# --------------------------------------------------------------------------------------
# Export resolution
# --------------------------------------------------------------------------------------

def _read_text(basename, explicit=None):
    """(path, raw_text) for `basename` in the newest export, or (None, None).

    Returns TEXT, not parsed rows, because the members do not share a parser: messages.csv and
    Invitations.csv are ordinary CSVs, while Connections.csv carries a 3-line "Notes:" preamble that
    a naive DictReader silently mistakes for the header. The caller picks the right reader.

    Mirrors parse_messages.find_messages, generalized: find_export resolves Connections.csv, and
    every other member sits beside it, in the directory or inside the .zip. Kept tolerant because a
    missing member is normal (an export can be requested without messages) and must not be fatal.
    """
    def _from_zip(zpath):
        with zipfile.ZipFile(zpath) as zf:
            names = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == basename]
            if not names:
                return None, None
            return f"{zpath}::{names[0]}", zf.read(names[0]).decode("utf-8-sig", "ignore")

    def _from_dir(d):
        cand = os.path.join(d, basename)
        if not os.path.exists(cand):
            return None, None
        with open(cand, encoding="utf-8-sig", errors="ignore") as fh:
            return cand, fh.read()

    try:
        if explicit:
            if os.path.isdir(explicit):
                return _from_dir(explicit)
            if zipfile.is_zipfile(explicit):
                return _from_zip(explicit)
            return None, None
        from parse_network import find_export
        path, _text = find_export(member=basename)
        if not path:
            return None, None
        if "::" in str(path):
            return _from_zip(str(path).split("::", 1)[0])
        return _from_dir(os.path.dirname(str(path)))
    except (OSError, zipfile.BadZipFile, ImportError):
        return None, None


def _dict_rows(text):
    return list(csv.DictReader(io.StringIO(text))) if text else []


# --------------------------------------------------------------------------------------
# Slug handling
# --------------------------------------------------------------------------------------

def slug_of(url):
    """Lowercase vanity slug from any profile URL shape, else None."""
    return _slug_from_to(url or "") or None


def compress(slug):
    """Alphabetic-only form of a slug: drops hyphens and the numeric id suffix.

    This is what lets `first-last` and `firstlast` and `first-last-8412` collapse to one another.
    It is deliberately lossier than the slug itself and is used ONLY to SUGGEST a candidate for a
    handle that does not resolve, never to assert a match.
    """
    return "".join(t for t in re.split(r"[^a-z0-9]+", (slug or "").lower()) if t.isalpha())


def _invite_date(row):
    for fmt in ("%m/%d/%y, %I:%M %p", "%m/%d/%Y, %I:%M %p", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime((row.get("Sent At") or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    # ⚠️ A lexical slice of "7/14/26, 1:05 PM" sorts as "7/14/26, 1" and compares WRONG against an
    # ISO bound, silently letting months of out-of-window rows through. Parse, never slice.
    return ""


# --------------------------------------------------------------------------------------
# Building the two sides
# --------------------------------------------------------------------------------------

def export_facts(export=None):
    """(known_slugs, outbound_events, snapshot_date, sources).

    known_slugs: every slug LinkedIn itself mentions anywhere in the export. A logged handle absent
    from this set cannot be real, which is what makes IDENTITY MISMATCH detectable at all.
    outbound_events: [{slug, name, date, channel}] for things the owner actually sent.
    """
    known, events, sources = set(), [], []

    mpath, mtext = _read_text("messages.csv", export)
    mrows = _dict_rows(mtext)
    owner = _owner(mrows)
    if mpath:
        sources.append(mpath)
        for r in mrows:
            for field in ("RECIPIENT PROFILE URLS", "SENDER PROFILE URL"):
                for u in (r.get(field) or "").split(","):
                    s = slug_of(u)
                    if s:
                        known.add(s)
            if (r.get("FROM") or "").strip() != owner:
                continue
            if (r.get("IS MESSAGE DRAFT") or "").strip().lower() in ("true", "yes", "1"):
                continue
            date = (r.get("DATE") or "")[:10]
            raw_to = (r.get("TO") or "").strip()
            for u in (r.get("RECIPIENT PROFILE URLS") or "").split(","):
                s = slug_of(u)
                if s:
                    events.append({"slug": s, "name": _pick_name(raw_to, s),
                                   "date": date, "channel": "message"})

    ipath, itext = _read_text("Invitations.csv", export)
    irows = _dict_rows(itext)
    if ipath:
        sources.append(ipath)
        for r in irows:
            for field in ("inviteeProfileUrl", "inviterProfileUrl"):
                s = slug_of(r.get(field))
                if s:
                    known.add(s)
            if not (r.get("Direction") or "").upper().startswith("OUTGOING"):
                continue
            if not (r.get("Message") or "").strip():
                continue  # a bare connection request is not outreach
            s = slug_of(r.get("inviteeProfileUrl"))
            events.append({"slug": s, "name": (r.get("To") or "").strip(),
                           "date": _invite_date(r), "channel": "invitation note"})

    # ⚠️ Connections.csv is NOT safe to hand to a naive DictReader. LinkedIn prepends a 3-line
    # "Notes:" preamble above the real header, so DictReader takes the preamble AS the header, never
    # finds a URL column, and silently yields nothing. That cost this script 573 of the handles it is
    # supposed to know, and turns a real connection into a false IDENTITY MISMATCH — an accusation
    # that a send was mis-filed when it was not. parse_network.parse_rows already strips the
    # preamble; reuse BY IMPORT, never by copy.
    cpath, ctext = _read_text("Connections.csv", export)
    if cpath:
        sources.append(cpath)
        try:
            from parse_network import parse_rows
            crows = parse_rows(ctext)
        except ImportError:
            crows = []
        for r in crows:
            s = slug_of(r.get("URL") or r.get("Url"))
            if s:
                known.add(s)

    snapshot = max([e["date"] for e in events if e["date"]] or [""])
    return known, events, snapshot, sources


def _pick_name(raw_to, slug):
    """A group thread lists every participant in TO; take the one whose tokens match this slug."""
    parts = [p.strip() for p in (raw_to or "").split(",") if p.strip()]
    for p in parts:
        toks = [t.lower() for t in re.split(r"[^A-Za-z]+", p) if len(t) > 2]
        if any(t in slug for t in toks):
            return p
    return raw_to or ""


def load_sendlog(path=SENDLOG):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


# --------------------------------------------------------------------------------------
# The three buckets
# --------------------------------------------------------------------------------------

def reconcile(rows, known, events, snapshot):
    idx = index_sendlog(rows)
    logged_slugs = {s for s in (slug_of(r.get("to")) for r in rows) if s}
    logged_slugs |= {s for s in (slug_of(r.get("from")) for r in rows) if s}

    mismatch, lag = [], []
    for r in rows:
        s = slug_of(r.get("to"))
        if not s or s in known:
            continue
        if snapshot and (r.get("date") or "") > snapshot:
            lag.append((r.get("date", ""), s, r.get("rung", "")))
            continue
        c = compress(s)
        cands = sorted({k for k in known if k != s and compress(k) == c})
        mismatch.append((r.get("date", ""), s, r.get("rung", ""), cands))

    seen, missing = set(), []
    for e in events:
        s = e["slug"]
        key = s or ("name:" + e["name"].lower())
        if key in seen:
            continue
        seen.add(key)
        if s and s in logged_slugs:
            continue
        if e["name"] and first_last(e["name"]) != (None, None):
            if match_sendlog(e["name"], idx) is not None:
                continue
        missing.append(e)

    # Identity deficits: rows that can never be reconciled because they hold no person.
    no_identity = [r for r in rows if not (r.get("to") or "").strip() and not (r.get("from") or "")]
    inbound = [r for r in rows if (r.get("from") or "").strip()]
    return mismatch, lag, missing, no_identity, inbound


# --------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Reconcile the send log against a LinkedIn export")
    ap.add_argument("--export", default=None, help="export directory or .zip (default: newest)")
    ap.add_argument("--since", default=DEFAULT_SINCE, help="window for outbound events")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--path", default=SENDLOG, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    known, events, snapshot, sources = export_facts(a.export)
    if not sources:
        print("🔴 no LinkedIn export found. Request one from LinkedIn, drop it in ~/Downloads, "
              "and re-run.", file=sys.stderr)
        return 3
    events = [e for e in events if e["date"] and e["date"] >= a.since]
    rows = load_sendlog(a.path)
    mismatch, lag, missing, no_identity, inbound = reconcile(rows, known, events, snapshot)

    logged = {s for s in (slug_of(r.get("to")) for r in rows) if s}
    print(f"export snapshot: {snapshot or 'unknown'}   window: from {a.since}")
    for s in sources:
        print(f"  source: {s}")
    print(f"\nsend log: {len(rows)} rows · {len(logged)} distinct LinkedIn handles")
    print(f"export:   {len(events)} outbound events · {len(known)} handles LinkedIn knows")

    print(f"\n🔴 MISSING SEND ...... {len(missing)}   (in the export, no send-log row)")
    print(f"🟠 IDENTITY MISMATCH . {len(mismatch)}   (logged handle does not exist on LinkedIn)")
    print(f"⚪ EXPORT LAG ........ {len(lag)}   (logged after the snapshot, NOT a gap)")
    print(f"\n📭 rows with NO recipient identity: {len(no_identity)} "
          f"(backfill owed; their person exists only in outreach_log.md)")
    print(f"📥 rows keyed on `from` (inbound):   {len(inbound)}")

    if not a.quiet:
        if mismatch:
            print("\n🟠 IDENTITY MISMATCH — the send happened, the row points at nobody")
            for date, s, rung, cands in sorted(mismatch):
                hint = f"→ did you mean {', '.join(cands)}?" if cands else "→ no near match"
                print(f"   {date}  rung={rung:12} {s:34} {hint}")
        if missing:
            print("\n🔴 MISSING SEND — in the export, never logged")
            by_ch = {}
            for e in sorted(missing, key=lambda e: e["date"]):
                by_ch.setdefault(e["channel"], []).append(e)
            for ch, items in by_ch.items():
                print(f"   ── {ch} ({len(items)})")
                for e in items:
                    print(f"      {e['date']}  {(e['name'] or '?')[:30]:30} {e['slug'] or ''}")
        if lag:
            print("\n⚪ EXPORT LAG — logged after the snapshot, expected")
            for date, s, rung in sorted(lag):
                print(f"   {date}  rung={rung:12} {s}")

    return 1 if (missing or mismatch) else 0


if __name__ == "__main__":
    sys.exit(main())
