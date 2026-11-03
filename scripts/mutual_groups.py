#!/usr/bin/env python3
"""mutual_groups.py — record the LinkedIn GROUPS a contact shares with the owner.

WHY THIS EXISTS (2026-08-11). On the day `shared-community` was ruled to open rung 7, a contact
upstream was levelled from cold to warm 7 on one line of evidence: LinkedIn's profile Highlights
card said *"1 mutual group · You and <them> are both in <group>."* That line was found because a
screenshot happened to include it. Nothing in the pipeline read it, and nothing would have.

🎯 A SHARED GROUP IS THE MOST MACHINE-READABLE FORM OF `shared-community` THERE IS, and it was the
one signal for that tier with no reader. The tier was created in the morning and by the evening it
had exactly one source: me noticing.

⛔ THE EXPORT DOES NOT HAVE IT. Checked against a full LinkedIn archive: there is no groups file
of any kind, and there could not be a useful one, because a MUTUAL group is the intersection of the
owner's memberships with the CONTACT'S, and a contact's memberships are not in the owner's own
export. So this is a live-profile read or it is nothing, which is why the work splits this way:

    this script  →  owns the QUEUE and the STORE, and never touches the network
    the operator →  opens the profile (logged in) and reads the Highlights card

Same division as the culture peek, and for the same reason: the source is behind a login, so an
agent reporting "no groups found" may only be reporting "profile unreachable". Those are opposite
findings and the store must never confuse them, which is why an unchecked contact and a
checked-and-empty contact are DIFFERENT recorded states here.

⚖️ IT RECORDS A FACT, IT DOES NOT SET A TIER. A shared group is evidence; the closeness answer stays
the owner's to give. This feeds `level_contacts --batch` as one more line of evidence next to the
strongest inbound message, exactly as BUG-160 required: **a question you have not given the reader
the means to answer is not a question.**

Usage:
    scripts/mutual_groups.py --queue [--n 12]        # who to check next, with profile URLs
    scripts/mutual_groups.py --record "Some Contact=A Group They Share With You"
    scripts/mutual_groups.py --record "Some One=NONE"      # checked, genuinely none
    scripts/mutual_groups.py --get "Some Contact"
    scripts/mutual_groups.py --report

Multiple groups: separate with `;`.
Stdlib only. Append-only; never rewrites a prior row.
Exit: 0 ok · 2 nothing found · 3 usage
"""
import argparse
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
STORE = os.path.join(REPO, "documents", "state", "mutual-groups.jsonl")

# The sentinel for "checked, and there are none". Distinct from an absent row, which means nobody
# has looked. Collapsing the two is the failure this file's docstring is about.
NONE = "NONE"


def load(path=None):
    """{normalized name: {name, groups, checked_at}} · last write wins, earlier rows preserved.

    ⛔ `path=None` AND NOT `path=STORE`. A default argument is bound at import time, so
    `path=STORE` freezes the location the module happened to see first: patching `STORE` later
    does nothing, the store cannot be redirected, and the only symptom is a reader that quietly
    answers from the wrong file. Caught by its own test on the day it was written.
    """
    path = path or STORE
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue        # a malformed line is preserved by being skipped, never rewritten
            key = _norm(row.get("name") or "")
            if key:
                out[key] = row
    return out


def _norm(name):
    try:
        sys.path.insert(0, HERE)
        import closeness
        return closeness.normalize_name(name)
    except Exception:
        return " ".join((name or "").lower().split())


def groups_for(name, store=None):
    """[group names] for this contact · [] means CHECKED AND NONE · None means NOT CHECKED."""
    store = store if store is not None else load()
    row = store.get(_norm(name))
    if row is None:
        return None
    return list(row.get("groups") or [])


def record(pairs):
    """`Name=Group A;Group B` or `Name=NONE`. Append-only, one row per call argument."""
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    written = errors = 0
    with open(STORE, "a", encoding="utf-8") as fh:
        for pair in pairs:
            if "=" not in pair:
                print(f"   🔴 not a NAME=GROUPS pair: {pair!r}")
                errors += 1
                continue
            name, _sep, raw = pair.partition("=")
            name, raw = name.strip(), raw.strip()
            if not name:
                print(f"   🔴 empty name in {pair!r}")
                errors += 1
                continue
            groups = [] if raw.upper() == NONE else [g.strip() for g in raw.split(";") if g.strip()]
            fh.write(json.dumps({"kind": "mutual-groups", "name": name, "groups": groups,
                                 "checked_at": now}, ensure_ascii=False) + "\n")
            written += 1
    if written:
        print(f"recorded {written} contact(s) into {os.path.relpath(STORE, REPO)}")
    return 0 if not errors else 2


def _people_queue(limit):
    """Contacts worth checking, highest-ranked first, that nobody has checked yet.

    Ranked order rather than alphabetical because the point is to inform the NEXT pick, not to
    achieve coverage for its own sake. Falls back to the closeness store when the ranker is
    unavailable, so this still works on a fresh install.
    """
    store = load()
    rows = []
    try:
        sys.path.insert(0, HERE)
        import closeness
        cl = closeness.load_store() if hasattr(closeness, "load_store") else None
    except Exception:
        cl = None
    if cl is None:
        path = os.path.join(REPO, "documents", "contact-closeness.json")
        try:
            cl = json.load(open(path, encoding="utf-8")).get("contacts", {})
        except Exception:
            cl = {}
    for name, row in cl.items():
        if _norm(name) in store:
            continue                        # already checked, never re-ask
        tier = (row.get("closeness") or "").strip()
        # Only rows a group could CHANGE. A contact already stated warm gains nothing, and a held
        # contact is not a candidate for any ask.
        if tier not in ("", "never-spoke", "known-level-tbd"):
            continue
        try:
            if closeness.is_held(row):
                continue
        except Exception:
            pass
        rows.append((name, row))
        if len(rows) >= limit:
            break
    return rows


def _profile_url(row):
    li = (row.get("linkedin") or "").strip()
    if li:
        return li
    note = row.get("note") or ""
    return f"(no URL on file — search LinkedIn for the name; note: {note[:60]})"


def queue(limit):
    rows = _people_queue(limit)
    if not rows:
        print("✅ nothing queued — every eligible contact has a recorded groups answer.")
        return 0
    print(f"mutual-groups queue: {len(rows)} contact(s) to check "
          f"(open each profile LOGGED IN and read the Highlights card):\n")
    for i, (name, row) in enumerate(rows, 1):
        print(f"  {i:2}. {name:<28} {_profile_url(row)}")
    print("\n  Highlights shows: 'N mutual groups · You and <First> are both in <Group>'.")
    print("  ⛔ An unreachable profile is NOT an empty answer. Record only what you actually read.")
    print('  record: python3 scripts/mutual_groups.py --record "Name=Group A;Group B"')
    print('          python3 scripts/mutual_groups.py --record "Name=NONE"   # checked, none')
    return 0


def report():
    store = load()
    if not store:
        print("mutual-groups: empty. Nothing checked yet.")
        return 2
    checked = len(store)
    withg = [r for r in store.values() if r.get("groups")]
    print(f"mutual-groups: {checked} contact(s) checked · {len(withg)} share at least one group "
          f"({100 * len(withg) / max(checked, 1):.0f}%)")
    counter = collections.Counter(g for r in withg for g in r["groups"])
    if counter:
        print("\ngroups, most shared first:")
        for g, n in counter.most_common():
            print(f"  {n:3d}  {g}")
    print("\n⚖️  A shared group is EVIDENCE, never a tier. The closeness answer stays the owner's:")
    print("    python3 scripts/level_contacts.py --record \"<Name>=shared-community::<why>\"")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("Usage:")[0].strip()[:200])
    ap.add_argument("--queue", action="store_true")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--record", nargs="+", metavar="NAME=GROUPS")
    ap.add_argument("--get", metavar="NAME")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.record:
        return record(a.record)
    if a.get:
        g = groups_for(a.get)
        if g is None:
            print(f"{a.get}: NOT CHECKED — nobody has opened the profile. "
                  f"That is not the same as 'no groups'.")
            return 2
        print(f"{a.get}: {'; '.join(g) if g else 'checked, no mutual groups'}")
        return 0
    if a.report:
        return report()
    if a.queue:
        return queue(a.n)
    ap.print_help()
    return 3


if __name__ == "__main__":
    sys.exit(main())
