#!/usr/bin/env python3
"""bridge_sweep.py — record the network BRIDGES into a target company (the referral-path signal).

WHY THIS EXISTS. No ranker in this pipeline can see mutual connections unless something reads them.
The bridge data, once captured by hand into a markdown table, was unusable by any reader. The
self-refining ranker's north star is who best CONNECTS the user to their next opportunity, so a
referral route into a target company is a first-class VALUE signal, and it needs a durable store,
not a markdown table.

⛔ THE EXPORT DOES NOT HAVE IT, and it cannot: a MUTUAL connection is the intersection of the owner's
network with a target's, and a target's connections are not in the owner's export. So this is a
live-profile read or it is nothing, and the work splits exactly as the mutual-groups sweep does:

    this script  →  owns the QUEUE and the STORE, and never touches the network
    the operator →  opens the company / person page (logged in) and reads the shared connections

An unreachable page is NOT "no bridge". An unchecked company and a checked-and-none company are
DIFFERENT recorded states, the same distinction mutual_groups.py exists to protect.

⚖️ IT RECORDS A FACT, NEVER A SCORE. A bridge is evidence the verdict miner reads through the
`bridged-company` / `is-bridge` populations; whether it earns weight is a ratification, on
acceptance outcomes, through the experiment registry.

Usage:
    scripts/bridge_sweep.py --queue [--n 12]                     # which companies to check next
    scripts/bridge_sweep.py --record "Acme=Jane Doe;John Smith"  # named bridges INTO Acme
    scripts/bridge_sweep.py --record "Acme=NONE"                 # checked, genuinely none
    scripts/bridge_sweep.py --get "Acme"
    scripts/bridge_sweep.py --report

Multiple bridges: separate with `;`. Stdlib only. Append-only; never rewrites a prior row.
Exit: 0 ok · 2 nothing found · 3 usage
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
STORE = os.path.join(REPO, "documents", "state", "bridges.jsonl")

NONE = "NONE"     # checked, and there are none. Distinct from an absent row (nobody looked).


def _ckey(company):
    return re.sub(r"[^a-z0-9]", "", str(company or "").lower())


def load(path=None):
    """{company_key: {company, bridges, checked_at}} · last write wins, earlier rows preserved.

    ⛔ `path=None`, NOT `path=STORE`: a default bound at import time freezes the first location seen
    and silently defeats a redirected store (the mutual_groups lesson, verified by its own test)."""
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
            key = _ckey(row.get("company") or "")
            if key:
                out[key] = row
    return out


def bridges_for(company, store=None):
    """[bridge names] into this company · [] means CHECKED AND NONE · None means NOT CHECKED."""
    store = store if store is not None else load()
    row = store.get(_ckey(company))
    if row is None:
        return None
    return list(row.get("bridges") or [])


def record(pairs):
    """`Company=Bridge A;Bridge B` or `Company=NONE`. Append-only, one row per call argument."""
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    written = errors = 0
    with open(STORE, "a", encoding="utf-8") as fh:
        for pair in pairs:
            if "=" not in pair:
                print(f"   🔴 not a COMPANY=BRIDGES pair: {pair!r}")
                errors += 1
                continue
            company, _sep, raw = pair.partition("=")
            company, raw = company.strip(), raw.strip()
            if not company:
                print(f"   🔴 empty company in {pair!r}")
                errors += 1
                continue
            bridges = [] if raw.upper() == NONE else [b.strip() for b in raw.split(";") if b.strip()]
            fh.write(json.dumps({"kind": "bridge", "company": company, "bridges": bridges,
                                 "checked_at": now}, ensure_ascii=False) + "\n")
            written += 1
    if written:
        print(f"recorded {written} company(ies) into {os.path.relpath(STORE, REPO)}")
    return 0 if not errors else 2


def _company_queue(limit):
    """Board companies with no recorded bridge answer yet, so the operator checks the destinations
    the user is actually targeting. Best-effort: falls back to nothing if the board is unreadable, so
    a fresh install never errors."""
    store = load()
    names = []
    try:
        sys.path.insert(0, HERE)
        import state
        rows = state.from_source("company", "green-board")
        recs = rows.values() if isinstance(rows, dict) else rows
        for r in recs:
            nm = (r.get("company") or r.get("name") or "").strip() if isinstance(r, dict) else ""
            if nm and _ckey(nm) not in store:
                names.append(nm)
            if len(names) >= limit:
                break
    except Exception:
        pass
    return names


def queue(limit):
    names = _company_queue(limit)
    if not names:
        print("✅ nothing queued — every board company has a recorded bridge answer (or the board "
              "is empty).")
        return 0
    print(f"bridge queue: {len(names)} company(ies) to check "
          f"(open each company page LOGGED IN and read shared connections):\n")
    for i, nm in enumerate(names, 1):
        print(f"  {i:2}. {nm}")
    print("\n  ⛔ An unreachable page is NOT an empty answer. Record only what you actually read.")
    print('  record: python3 scripts/bridge_sweep.py --record "Company=Bridge A;Bridge B"')
    print('          python3 scripts/bridge_sweep.py --record "Company=NONE"   # checked, none')
    return 0


def report():
    store = load()
    if not store:
        print("bridges: empty. Nothing checked yet.")
        return 2
    checked = len(store)
    withb = [r for r in store.values() if r.get("bridges")]
    print(f"bridges: {checked} company(ies) checked · {len(withb)} have at least one bridge "
          f"({100 * len(withb) / max(checked, 1):.0f}%)")
    counter = collections.Counter(b for r in withb for b in r["bridges"])
    if counter:
        print("\nbridges, most connected first:")
        for b, n in counter.most_common():
            print(f"  {n:3d}  {b}")
    print("\n⚖️  A bridge is EVIDENCE, never a tier. Whether it scores is ratified on acceptance data.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("Usage:")[0].strip()[:200])
    ap.add_argument("--queue", action="store_true")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--record", nargs="+", metavar="COMPANY=BRIDGES")
    ap.add_argument("--get", metavar="COMPANY")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.record:
        return record(a.record)
    if a.get:
        b = bridges_for(a.get)
        if b is None:
            print(f"{a.get}: NOT CHECKED — nobody has opened the page. Not the same as 'no bridge'.")
            return 2
        print(f"{a.get}: {'; '.join(b) if b else 'checked, no bridge'}")
        return 0
    if a.report:
        return report()
    if a.queue:
        return queue(a.n)
    ap.print_help()
    return 3


if __name__ == "__main__":
    sys.exit(main())
