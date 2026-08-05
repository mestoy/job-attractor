#!/usr/bin/env python3
"""referral_intake.py, the missing conveyor segment between a warm reply and rung 8-9.

WHY THIS EXISTS (2026-08-02). The ladder is a conveyor: rung 7 asks "do you have relationships at
[Company 1, 2, or 3]?" and the name that comes back IS the rung 8-9 contact. The pipeline could
USE a referral (the `REFERRED: X VIA Y` marker in check_preview.py, `--referred-by` in
log_linkedin_send.py) but nothing could RECORD one: when a reply names a person, that name had
nowhere to land, so the referred rung stayed empty however many warm sends went out. This file is
where the name lands.

WHAT THIS IS NOT. Not a gate, not a hook, not a sender. It writes and reads one data file. The
send path is unchanged: a referred send still routes through the existing BUILD and SEND gates,
and check_preview still verifies the introducer independently. Recording here just means the name
survives long enough to reach them.

STORE: documents/state/referral.jsonl, append-only with last-write-wins by referred name (a later
row for the same name is a correction or a status change, and the LATEST row is the truth).

Row shape:
    {"referred": name, "introducer": name, "company": str|null, "status": "open"|"sent"|"dropped",
     "note": str|null, "recorded": "YYYY-MM-DD"}

Stdlib only, same promise as closeness.py.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
STORE = os.path.join(REPO, "documents", "state", "referral.jsonl")


def _rows(path=None):
    """Every row, in file order. Missing file is an empty conveyor, not an error."""
    p = path or STORE
    out = []
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("referred"):
                    out.append(row)
    except OSError:
        pass
    return out


def current(path=None):
    """{referred name: latest row}. Last write wins."""
    latest = {}
    for row in _rows(path):
        latest[str(row["referred"]).strip()] = row
    return latest


def open_referrals(path=None):
    """Latest-status rows still waiting on a send, oldest first. This is rung 8-9 supply."""
    rows = [r for r in current(path).values() if r.get("status", "open") == "open"]
    return sorted(rows, key=lambda r: (r.get("recorded") or "", r.get("referred") or ""))


def record(referred, introducer, company=None, note=None, path=None, today=None):
    """Append one row and return (row, advisories).

    Advisories, never refusals: this is intake, and the send gates downstream do the refusing.
    What gets flagged here is anything check_preview will later refuse, so the surprise arrives
    now instead of at draft time.
    """
    advisories = []
    try:
        sys.path.insert(0, HERE)
        import closeness
        store = closeness.load()
        crow = closeness.tier_for(introducer, store)
        if crow is None:
            advisories.append(f"introducer {introducer!r} is not in the closeness store; "
                              "check_preview will refuse the referred send until they are")
        else:
            held = closeness.is_held(crow)
            if held:
                advisories.append(f"introducer {introducer!r} is HELD ({held}); a referral routed "
                                  "through them cannot be drafted")
            if (crow.get("closeness") or "never-spoke") == "never-spoke":
                advisories.append(f"introducer {introducer!r} is recorded never-spoke; a stranger "
                                  "cannot make the introduction and check_preview will refuse")
    except Exception:
        advisories.append("closeness store unreadable; introducer unverified")
    row = {"referred": str(referred).strip(),
           "introducer": str(introducer).strip(),
           "company": (str(company).strip() or None) if company else None,
           "status": "open",
           "note": (str(note).strip() or None) if note else None,
           "recorded": today or date.today().isoformat()}
    p = path or STORE
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row, advisories


def close(referred, outcome, path=None, today=None):
    """Append a status change ('sent' or 'dropped') for a referred name. Returns the row or None."""
    if outcome not in ("sent", "dropped"):
        raise ValueError("outcome must be 'sent' or 'dropped'")
    prev = current(path).get(str(referred).strip())
    if prev is None:
        return None
    row = dict(prev)
    row["status"] = outcome
    row["recorded"] = today or date.today().isoformat()
    p = path or STORE
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Record and list rung 8-9 referrals mined from replies")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="a reply named a person; keep the name")
    r.add_argument("--name", required=True, help="the referred person")
    r.add_argument("--via", required=True, help="the introducer who named them")
    r.add_argument("--company", default=None)
    r.add_argument("--note", default=None, help="where the name came from, e.g. the reply date")
    sub.add_parser("list", help="open referrals waiting on a send")
    c = sub.add_parser("close", help="mark a referral sent or dropped")
    c.add_argument("--name", required=True)
    c.add_argument("--outcome", required=True, choices=["sent", "dropped"])
    args = ap.parse_args(argv)

    if args.cmd == "record":
        row, adv = record(args.name, args.via, args.company, args.note)
        print(f"recorded: {row['referred']} via {row['introducer']}"
              + (f" @ {row['company']}" if row["company"] else ""))
        for a in adv:
            print(f"  ⚠️ {a}")
        print('  next: draft with the marker `REFERRED: '
              f"{row['referred']} VIA {row['introducer']}` and log the send with "
              f"--rung referred --referred-by \"{row['introducer']}\"")
        return 0
    if args.cmd == "list":
        rows = open_referrals()
        if not rows:
            print("no open referrals. Rung 7 replies are where these come from.")
            return 0
        for r_ in rows:
            print(f"  {r_['referred']} via {r_['introducer']}"
                  + (f" @ {r_['company']}" if r_.get("company") else "")
                  + f"  (recorded {r_.get('recorded')})")
        return 0
    if args.cmd == "close":
        row = close(args.name, args.outcome)
        if row is None:
            print(f"no open referral for {args.name!r}")
            return 1
        print(f"{row['referred']}: {row['status']}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
