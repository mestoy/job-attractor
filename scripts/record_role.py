#!/usr/bin/env python3
"""Record that a contact's CURRENT role was checked by a human.

WHY THIS EXISTS (2026-08-04). `Connections.csv` records a contact's company and title as they stood
when the connection was MADE, and `parse_network.py` copies that into `warm-network.md`, where the
ranker treats it as current. Nothing re-verifies it, ever.

The cost, measured: **a contact ranked #1** on a stored title. That role
ran **Jan 2019 to Feb 2020**. It had ended SIX YEARS before the ranker offered him as a warm target,
and a brief was written describing him in the present tense off it.

⛔ WRITE HERE, NEVER INTO `warm-network.md`. That file is REGENERATED from the export on every
`parse_network.py` run, so a correction made there is erased the next time anyone parses. This store
is append-only, dated, sourced, and survives.

  record_role.py --name "Dana Reyes" --title "Associate Director, Technology" \
                 --company "Vaco by Highspring" --source "linkedin.com/in/..., experience section"

  record_role.py --name "Jane Doe" --left --source "linkedin.com/in/..., experience section" \
                 --note "that role ran Jan 2019 to Feb 2020"

⚖️ A SOURCE IS MANDATORY, for the same reason the employer cache demands one: an unsourced
verification is a memory, and a memory is what produced the defect.
"""
import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contact_signals as cs   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="the contact, as they appear in warm-network.md")
    ap.add_argument("--title", default="", help="their CURRENT title (omit with --left)")
    ap.add_argument("--company", default="", help="their CURRENT company (omit with --left)")
    ap.add_argument("--source", required=True, help="where you looked; an unsourced check is a memory")
    ap.add_argument("--note", default="", help="anything the next reader needs, e.g. the real dates")
    ap.add_argument("--left", action="store_true",
                    help="the stored role has ENDED; they are no longer where the pipeline thinks")
    ap.add_argument("--date", default="", help="YYYY-MM-DD, defaults to today")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not a.left and not (a.title or a.company):
        print("⛔ give --title/--company, or --left if they have moved on", file=sys.stderr)
        return 2

    row = {"name": a.name.strip(), "title": a.title.strip(), "company": a.company.strip(),
           "still_there": not a.left, "verified_on": a.date or str(date.today()),
           "source": a.source.strip(), "note": a.note.strip()}

    if a.dry_run:
        print(json.dumps(row, ensure_ascii=False))
        return 0
    os.makedirs(os.path.dirname(cs.ROLE_CACHE), exist_ok=True)
    with open(cs.ROLE_CACHE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    state = "ROLE ENDED" if a.left else f"{row['title']} @ {row['company']}"
    print(f"✅ recorded {row['name']}: {state}  (verified {row['verified_on']})")
    # Read it straight back through the real reader, so a key mismatch shows up HERE rather than
    # as a silently-unapplied verification in tomorrow's briefing. A credential suffix already
    # caused exactly that once.
    cs._ROLE_CACHE = None
    if not cs.verified_role(row["name"]):
        print("⚠️  WROTE IT, BUT THE READER CANNOT SEE IT. The name key does not round-trip; "
              "check spelling against warm-network.md.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
