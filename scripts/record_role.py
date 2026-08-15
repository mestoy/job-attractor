#!/usr/bin/env python3
"""Record that a contact's CURRENT role was checked by a human.

WHY THIS EXISTS (2026-08-04). `Connections.csv` records a contact's company and title as they stood
when the connection was MADE, and `parse_network.py` copies that into `warm-network.md`, where the
ranker treats it as current. Nothing re-verifies it, ever.

The cost, measured: a contact **ranked #1** as "Director, Services @ SomeCo", off a title that had
ended **years earlier**. The role was long over before the ranker offered them as a warm target,
and a brief was written describing them in the present tense off it.

⛔ WRITE HERE, NEVER INTO `warm-network.md`. That file is REGENERATED from the export on every
`parse_network.py` run, so a correction made there is erased the next time anyone parses. This store
is append-only, dated, sourced, and survives.

  record_role.py --name "Jane Doe" --title "Associate Director, Technology" \
                 --company "SomeCo" --source-type company-page \
                 --source "https://someco.example.com/leadership, retrieved 2026-08-11"

  record_role.py --name "Jane Doe" --left --source "linkedin.com/in/..., experience section" \
                 --note "prior role ran Jan 2019 to Feb 2020"

⚖️ A SOURCE IS MANDATORY, for the same reason the employer cache demands one: an unsourced
verification is a memory, and a memory is what produced the defect.

⚖️ AND THE SOURCE NEEDS A TYPE (2026-08-11, partner issue #26). `--source` was free text, so a
confirmation read off a company's own leadership page or a dated press release either had to
masquerade as the LinkedIn read `/verify-titles` asked for, or be dropped on the floor. On the
partner's install that day, 4 of 6 boss rows verified from company pages and a press release and
**0** from LinkedIn, because LinkedIn answers HTTP 999 to every automated fetch. A store that
cannot tell those apart cannot tell a strong confirmation from a weak one.

⛔ THE VOCABULARY IS IMPORTED FROM `boss_registry`, NEVER RETYPED. `boss_registry.VERIFIED` already
defines it, and this repo has repeatedly paid for two writers of one definition. If the registry
grows a source type, this script gets it for free.
"""
import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contact_signals as cs   # noqa: E402
import boss_registry as br     # noqa: E402  (the ONE definition of the source vocabulary)

# ⛔ An ALIAS, not a copy. Rebinding the name keeps the reader honest about where it came from.
# (boss_registry's `_VERIFIED_FAMILY` — the map from source type to `state.py` provenance family —
# is a LOCAL inside `cmd_add` and cannot be imported. Rather than retype it here and create the
# second writer this comment exists to forbid, this store records the typed source and leaves the
# family derivation to the one place that already owns it.)
SOURCE_TYPES = br.VERIFIED

# What an OMITTED --source-type means. Not a claim of anything: the caller told us where they
# looked but not what kind of thing it was, and the honest label for that is "unverified". Every
# pre-existing invocation keeps working and simply lands here.
DEFAULT_SOURCE_TYPE = "unverified"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="the contact, as they appear in warm-network.md")
    ap.add_argument("--title", default="", help="their CURRENT title (omit with --left)")
    ap.add_argument("--company", default="", help="their CURRENT company (omit with --left)")
    ap.add_argument("--source", required=True, help="where you looked; an unsourced check is a memory")
    # ⛔ NOT argparse `choices=`. An unknown value must be REFUSED loudly, in this script's own
    # words, naming the whole vocabulary — the same shape boss_registry.cmd_add uses. argparse's
    # usage dump is a worse error at the exact moment someone is guessing at the vocabulary.
    ap.add_argument("--source-type", default="",
                    help="what KIND of source: " + " | ".join(SOURCE_TYPES) +
                         f" (omitted = {DEFAULT_SOURCE_TYPE})")
    ap.add_argument("--note", default="", help="anything the next reader needs, e.g. the real dates")
    ap.add_argument("--left", action="store_true",
                    help="the stored role has ENDED; they are no longer where the pipeline thinks")
    ap.add_argument("--date", default="", help="YYYY-MM-DD, defaults to today")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not a.left and not (a.title or a.company):
        print("⛔ give --title/--company, or --left if they have moved on", file=sys.stderr)
        return 2

    stype = (a.source_type or "").strip()
    # ⛔ THE SOURCE TYPE IS NOT THE CALLER'S TO ASSERT WHEN THE URL SAYS OTHERWISE (2026-08-11).
    # Three wrong boss names landed in one evening, all from aggregators, all stated confidently,
    # and one was a step away from a real message. See `boss_registry.AGGREGATOR_DOMAINS`.
    # This can only ever make a claim WEAKER, never stronger, and it says so out loud.
    stype, _demoted = br.demote_if_aggregator(a.source, stype)
    if _demoted:
        print(f"⚠️  {_demoted}", file=sys.stderr)
    if stype and stype not in SOURCE_TYPES:
        print(f"⛔ BLOCKED: --source-type {stype!r} is not one of: {', '.join(SOURCE_TYPES)}",
              file=sys.stderr)
        print("   This vocabulary is boss_registry.VERIFIED, shared on purpose. Do not invent a "
              "value here; a type nobody reads is worse than an honest 'unverified'.",
              file=sys.stderr)
        return 4
    if not stype:
        stype = DEFAULT_SOURCE_TYPE

    row = {"name": a.name.strip(), "title": a.title.strip(), "company": a.company.strip(),
           "still_there": not a.left, "verified_on": a.date or str(date.today()),
           "source": a.source.strip(), "source_type": stype, "note": a.note.strip()}

    if a.dry_run:
        print(json.dumps(row, ensure_ascii=False))
        return 0
    os.makedirs(os.path.dirname(cs.ROLE_CACHE), exist_ok=True)
    with open(cs.ROLE_CACHE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    state = "ROLE ENDED" if a.left else f"{row['title']} @ {row['company']}"
    print(f"✅ recorded {row['name']}: {state}  "
          f"(verified {row['verified_on']}, source-type {row['source_type']})")
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
