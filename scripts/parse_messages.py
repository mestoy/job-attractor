#!/usr/bin/env python3
"""parse_messages.py — read the LinkedIn message archive, the one export file nothing reads.

WHY THIS EXISTS. `messages.csv` ships inside every LinkedIn export and is the single best evidence
of who you actually have a relationship with. In most pipelines it is referenced by zero lines of
code, and the cost shows up as false-NEW dedup verdicts: a company you already interviewed at comes
back clean, because the proof was sitting in an unread CSV. The second failure mode is quieter — an
old export gets read by hand and nobody notices it is a year stale.

A connection date tells you WHEN you met. Message counts tell you whether you ever spoke. That is
the difference between a warm rung and a stranger, and LaCivita's ladder is built on it.

WHAT THIS WRITES, AND WHAT IT REFUSES TO TOUCH. `documents/contact-closeness.json` is the CURATED
layer: `closeness`, `note` and `evidence` are human judgments nothing else can produce. This script
updates **only** the derived `messages: {total, he_sent, they_sent}` block and leaves every curated
field byte-identical. Keeping the regenerable store and the curated store separate is what makes
this safe; do not blur it.

Merge-only, `.bak` first, dry-run by default.

Usage:
  scripts/parse_messages.py                 # report only, writes nothing
  scripts/parse_messages.py --write         # merge message counts into contact-closeness.json
  scripts/parse_messages.py --export <path> # explicit messages.csv instead of the newest export

Exit: 0 = ok · 2 = no export or no closeness file · 3 = usage
"""
import contextlib
import csv
import io
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
CLOSENESS = os.path.join(REPO, "documents", "contact-closeness.json")
BACKUP = CLOSENESS + ".bak"

sys.path.insert(0, HERE)
import closeness  # the ONE writer of contact-closeness.json (P1-3)  # noqa: E402


def _owner_names(rows):
    """Infer the account owner from the FROM column: whoever appears most often as a sender.

    Deliberately inferred rather than configured. The export is the owner's own archive, so they
    are in nearly every thread; hardcoding a name here would be one more owner-specific value to
    keep in sync, and getting it wrong would silently invert he_sent/they_sent for every contact.
    """
    counts = {}
    for r in rows:
        f = (r.get("FROM") or "").strip()
        if f:
            counts[f] = counts.get(f, 0) + 1
    return max(counts, key=counts.get) if counts else ""


def find_messages(explicit=None):
    """(path, rows) for the newest messages.csv, reusing parse_network's export resolver."""
    if explicit:
        with open(explicit, encoding="utf-8-sig", errors="ignore") as fh:
            return explicit, list(csv.DictReader(fh))
    try:
        from parse_network import find_export
    except Exception:
        return None, []
    path, _text = find_export()
    if not path:
        return None, []
    # find_export resolves Connections.csv; messages.csv sits beside it, in the dir or the zip.
    if "::" in str(path):
        zpath, member = str(path).split("::", 1)
        target = member.rsplit("/", 1)[0] + "/messages.csv" if "/" in member else "messages.csv"
        try:
            with zipfile.ZipFile(zpath) as zf:
                names = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == "messages.csv"]
                if not names:
                    return None, []
                target = names[0]
                raw = zf.read(target).decode("utf-8-sig", "ignore")
            return f"{zpath}::{target}", list(csv.DictReader(io.StringIO(raw)))
        except Exception:
            return None, []
    cand = os.path.join(os.path.dirname(str(path)), "messages.csv")
    if not os.path.exists(cand):
        return None, []
    with open(cand, encoding="utf-8-sig", errors="ignore") as fh:
        return cand, list(csv.DictReader(fh))


def _iso(raw):
    """The date half of a LinkedIn message stamp ('2026-07-10 15:02:57 UTC'), or None."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(raw or ""))
    return m.group(0) if m else None


def tally(rows):
    """{contact name: {total, he_sent, they_sent, last_inbound, last_outbound}}.

    Drafts excluded, owner excluded.

    ⚖️ THE DATES ARE THE POINT. This file has always carried a per message DATE column and this
    function used to throw it away, so the store held volume with no time in it. Nothing could ask
    "did they ever write back, and how long ago" — the two halves of the live-thread signal.
    `last_inbound` is the most recent message FROM the other person, which is the reply half; its
    absence means they never wrote back at all.

    ⛔ These are inputs to `closeness.thread_state`, never to a closeness TIER. Deriving a tier
    from thread volume is what once recorded a decades-long friendship as a weak tie on the
    strength of one unanswered message.
    """
    owner = _owner_names(rows)
    out = {}
    for r in rows:
        if (r.get("IS MESSAGE DRAFT") or "").strip().lower() in ("true", "yes", "1"):
            continue  # an unsent draft is not a conversation
        frm = (r.get("FROM") or "").strip()
        to = (r.get("TO") or "").strip()
        if not frm and not to:
            continue
        other = to if frm == owner else frm
        if not other or other == owner:
            continue
        e = out.setdefault(other, {"total": 0, "he_sent": 0, "they_sent": 0,
                                   "last_inbound": None, "last_outbound": None})
        e["total"] += 1
        when = _iso(r.get("DATE"))
        if frm == owner:
            e["he_sent"] += 1
            if when and (e["last_outbound"] is None or when > e["last_outbound"]):
                e["last_outbound"] = when
        else:
            e["they_sent"] += 1
            if when and (e["last_inbound"] is None or when > e["last_inbound"]):
                e["last_inbound"] = when
    return out, owner


CURATED = ("closeness", "note", "evidence", "sent", "source", "level_source", "outreach_status",
           "paused_note", "decline_note", "pronouns", "do_not_contact", "outcome", "aka")


def merge(counts, write=False):
    # Hold the store lock across the read AND the write, so a concurrent writer (level_contacts'
    # interview, sync_contacted) cannot slip an update between our read and our write and lose it.
    # Read-only dry runs take no lock. (P1-3)
    with (closeness.store_lock() if write else contextlib.nullcontext()):
        try:
            data = json.load(open(CLOSENESS, encoding="utf-8"))
        except Exception as e:
            print(f"❌ cannot read {os.path.relpath(CLOSENESS, REPO)} ({type(e).__name__})")
            return 2, {}
        contacts = data.get("contacts", {})
        changed, added, unmatched = 0, 0, 0
        for name, m in counts.items():
            rec = contacts.get(name)
            if rec is None:
                unmatched += 1
                continue
            before = rec.get("messages")
            if before != m:
                rec["messages"] = m
                changed += 1
                if before is None:
                    added += 1
        if write and changed:
            data["contacts"] = contacts
            # atomic .bak + tmp+os.replace, keeping this file's indent=1 / ensure_ascii=False format
            closeness.atomic_write(data, indent=1, ensure_ascii=False)
        return 0, {"changed": changed, "added": added, "unmatched": unmatched,
                   "covered": len(counts)}


def main():
    args = sys.argv[1:]
    write = "--write" in args
    explicit = None
    if "--export" in args:
        i = args.index("--export")
        if i + 1 >= len(args):
            print(__doc__.split("Usage:")[1])
            return 3
        explicit = args[i + 1]

    path, rows = find_messages(explicit)
    if not rows:
        print("❌ no messages.csv found. It ships inside the LinkedIn export beside Connections.csv.")
        return 2
    counts, owner = tally(rows)
    print(f"source: {path}")
    print(f"owner inferred as: {owner!r}")
    print(f"{len(rows)} message rows · {len(counts)} distinct contacts")
    two_way = sum(1 for m in counts.values() if m["he_sent"] and m["they_sent"])
    print(f"{two_way} contacts with a TWO-WAY thread (the ones that are actually relationships)")

    code, stats = merge(counts, write=write)
    if code:
        return code
    verb = "updated" if write else "(dry-run) would update"
    print(f"\n{verb} messages{{}} on {stats['changed']} contact(s) "
          f"({stats['added']} gaining counts for the first time)")
    if stats["unmatched"]:
        print(f"   ⏭️  {stats['unmatched']} message contact(s) not in contact-closeness.json "
              f"— name variants or people who left the network; NOT added, this script never "
              f"invents a curated record")
    print("   ⚠️  curated fields (closeness / note / evidence / sent) are never touched")
    if not write:
        print("   re-run with --write to merge (a .bak is written first)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
