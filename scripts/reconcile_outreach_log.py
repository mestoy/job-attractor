#!/usr/bin/env python3
"""reconcile_outreach_log.py — find sends written up in outreach_log.md that never reached send-log.jsonl.

WHY THIS EXISTS. `send-log.jsonl` is the ladder's denominator: every rate on every picker is computed
from it. `mail-draft.sh` self-logs, so the normal path is safe. What is NOT covered is any send that
exists only as a narrative write-up: an older send, an import from another machine, a session that
wrote the prose and not the row. `backfill_linkedin_sends.py` covers LinkedIn from an export, and
`reconcile_linkedin.py` measures that gap. Nothing covered email, or the narrative log at all.

⛔ THE FAILURE IT CATCHES, reported from a partner install (kit issue #4, 2026-08-10). Ten real July
email boss-hunt sends were fully written up in `outreach_log.md` and absent from `send-log.jsonl`, so
their rung ladder read **0 cold-boss sent when the truth was 10**. The method's unit of work is
messages SENT, so a silently-zero denominator is the worst shape of wrong: it reads as "you have not
started" over a week of real work.

⚖️ WHAT THIS DELIBERATELY WILL NOT DO, and it is most of the design:

  · **It never infers a rung.** The rung decides which row of the ladder a send lands in, and a
    guessed rung silently moves the reply rate between rungs. No `**Rung:**` line means the entry is
    reported as unreconstructable, never reconstructed with a default.
  · **It never invents a recipient.** Only an entry carrying an explicit address is a candidate.
  · **It writes nothing without `--write`.** Read-only is the default, like `reconcile_linkedin.py`.
  · **Every written row carries `provenance: "backfill:outreach_log"`**, so the ladder can subtract
    them again. A denominator you cannot un-mix is worse than one you know is short.
  · **It reports its own COVERAGE, always**, including when the gap is zero. "Nothing to do" and
    "the parser understood nothing" must never render the same, which is the same class of failure
    as the one this script exists to catch, one layer up.

📊 MEASURED ON ONE REAL LOG, 2026-08-10, and the result is worth stating up front because
it is not what the field counts suggest. 121 SENT entries reach the parser. 30 carry a recoverable
address. 81 carry an explicit `**Rung:**` line. **The overlap is ZERO.**

⛔ THE TWO SETS ARE DISJOINT BY CONSTRUCTION, not by accident. The log has two eras. The older
email-era entries record `To \`someone@company.com\`` and never write a rung; the newer entries
record `**Rung:** warm 7` and never write an address, because by then `mail-draft.sh` was self-
logging and the narrative stopped carrying the machine fields. So on THIS log the reconciler can
confidently reconstruct **nothing**, and it says so rather than reaching for the nearest guess.

⚖️ THAT IS THE CORRECT OUTCOME, not a failure to fix by loosening. The 30 address-bearing entries
do carry rung HINTS: 25 say "boss-hunt" in the header and 29 say "warm" somewhere in the prose.
Reading either as a rung is exactly the inference this file refuses to make, because the rung
decides which ladder row a send lands in and both hints appear in entries that are not that rung.
The gap on this install therefore remains UNMEASURED, which is an honest state, and a reported one.

A log that records both fields per entry reconciles fine, which is the shape the partner install
described in kit issue #4.

Usage:
    scripts/reconcile_outreach_log.py                 # read-only: the gap and the coverage
    scripts/reconcile_outreach_log.py --write         # append the confident rows
    scripts/reconcile_outreach_log.py --show-skipped  # why each unreconstructable entry was skipped
Exit: 0 always (a measurement, not a gate)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
NARRATIVE = os.path.join(REPO, "outreach_log.md")
SENDLOG = os.path.join(REPO, "documents", "send-log.jsonl")
PROVENANCE = "backfill:outreach_log"

# The header is the only reliable date, and it has at least two shapes in the wild:
#   ## 2026-07-19 · Acme (acme.example) · A Person (VP Product) — ✅ SENT ...
#   ## 2026-07-27 · A Person (Director of Product, Acme) — ✅ SENT ...
# ⛔ Which field is the COMPANY differs between them, which is why company is NOT a join key here.
# An earlier attempt to measure this gap joined on field one and reported 27 orphans that were
# mostly warm sends whose field one is a PERSON. The address is unambiguous; the name is not.
HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*·\s*(.+)$")
SENT = re.compile(r"✅\s*SENT|—\s*SENT\b")
NOT_A_SEND = re.compile(r"bounce|INBOUND|UNLOGGED|DRAFT(?!ED BY)", re.I)
ADDR = re.compile(r"To\s+`([^`]+@[^`\s]+)`")
SUBJ = re.compile(r"^>\s*Subject:\s*(.+?)\s*$", re.M)
RUNG = re.compile(r"^\*\*Rung:\*\*\s*([\w-]+)", re.M)
CHAN_DECL = re.compile(r"^\*\*Channel:\*\*\s*(\w+)", re.M)
CHAN_TAIL = re.compile(r"channel:(\w+)")


# ⭐ THE STRUCTURED MARKER, and it is the ONLY key here that is not a guess about prose.
# `mail-draft.sh` writes one of these into every STAGED block from 2026-08-10 on:
#   <!-- SENDLOG v1 date=2026-08-10 rung=cold-boss channel=email to=a@b.com subject=Hello -->
# It is an HTML comment, so it survives the human editing the entry into its SENT form and never
# renders. When it is present NOTHING below is parsed: the fields are read, not inferred. The prose
# rules stay for the history that predates the marker, and they are the reason coverage on an older
# log is low rather than complete.
SENDLOG_MARK = re.compile(
    r"<!--\s*SENDLOG\s+v1\s+date=(\S+)\s+rung=(\S*)\s+channel=(\S*)\s+to=(\S+)\s+subject=(.*?)\s*-->")


def blocks(text):
    """Each `## ` section with its body, in file order."""
    parts = re.split(r"\n(?=## )", text)
    for p in parts:
        head = p.split("\n", 1)[0]
        m = HEAD.match(head)
        if m:
            yield m.group(1), m.group(2), p


def parse(text):
    """(candidates, skipped). A candidate carries everything a send-log row needs, from the entry."""
    cand, skipped = [], []
    for date, title, body in blocks(text):
        if not SENT.search(title) or NOT_A_SEND.search(title):
            continue
        mk = SENDLOG_MARK.search(body)
        if mk:
            # ⭐ Marker wins outright. Read, never inferred.
            cand.append({"date": mk.group(1), "rung": mk.group(2), "channel": (mk.group(3) or "email"),
                         "to": mk.group(4).strip().lower(), "subject": mk.group(5).strip(),
                         "title": title[:70], "source": "marker"})
            continue
        why = []
        a = ADDR.search(body)
        r = RUNG.search(body)
        if not a:
            why.append("no recoverable recipient address")
        if not r:
            # ⛔ NEVER DEFAULTED. See the module docstring.
            why.append("no explicit **Rung:** line, and the rung is never inferred")
        if why:
            skipped.append({"date": date, "title": title[:70], "why": why})
            continue
        s = SUBJ.search(body)
        decl = CHAN_DECL.search(body)
        tail = CHAN_TAIL.search(body)
        chan = (decl.group(1) if decl else (tail.group(1) if tail else "")).lower()
        row = {"date": date, "to": a.group(1).strip().lower(), "rung": r.group(1).strip(),
               "subject": s.group(1).strip() if s else "", "channel": chan or "email",
               "title": title[:70], "source": "prose"}
        # ⚠️ A REAL DISAGREEMENT IN THE SOURCE, surfaced rather than resolved. Some entries declare
        # `**Channel:** EMAIL` in the body and `channel:LinkedIn` in the FOLLOWUP-DUE line. Both are
        # hand-written and this script cannot know which is true, so it records the conflict on the
        # row and reports it. Picking one silently would put sends on the wrong ladder rung.
        if decl and tail and decl.group(1).lower() != tail.group(1).lower():
            row["channel_conflict"] = f"body says {decl.group(1)}, tail says {tail.group(1)}"
        cand.append(row)
    return cand, skipped


def existing(path):
    """(by_to_date, by_to_subject, count). Both keys, because either alone has collisions."""
    td, ts, n = set(), set(), 0
    if not os.path.exists(path):
        return td, ts, n
    with io.open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            n += 1
            to = (d.get("to") or "").strip().lower()
            if not to:
                continue
            if d.get("date"):
                td.add((to, d["date"]))
            if d.get("subject"):
                ts.add((to, d["subject"].strip()))
    return td, ts, n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="append the confident rows to the send log")
    ap.add_argument("--show-skipped", action="store_true", help="list every entry that was skipped, and why")
    ap.add_argument("--narrative", default=NARRATIVE)
    ap.add_argument("--sendlog", default=SENDLOG)
    a = ap.parse_args(argv)

    try:
        text = io.open(a.narrative, encoding="utf-8", errors="ignore").read()
    except OSError as e:
        print(f"🔴 cannot read {a.narrative}: {e}", file=sys.stderr)
        return 0

    cand, skipped = parse(text)
    td, ts, logged = existing(a.sendlog)
    missing = [c for c in cand
               if (c["to"], c["date"]) not in td and (c["to"], c["subject"]) not in ts]

    total = len(cand) + len(skipped)
    print(f"── outreach_log.md → send-log.jsonl ──")
    print(f"   {total} SENT write-up(s) · {len(cand)} reconstructable · {len(skipped)} not")
    print(f"   send-log.jsonl holds {logged} row(s)")
    # ⛔ COVERAGE IS ALWAYS PRINTED, gap or no gap. A run that parsed nothing and a run that found
    # nothing missing are the same three words otherwise, and this whole script exists because two
    # states that render identically is how a store goes quietly wrong.
    pct = (100.0 * len(cand) / total) if total else 0.0
    print(f"   coverage: this parser can speak for {pct:.0f}% of the write-ups "
          f"({len(cand)} of {total}). The rest are REPORTED, never dropped silently.")
    if not cand:
        print("   ⚠️  NOTHING was reconstructable. That is a parser result, NOT a clean log.")

    conflicts = [c for c in cand if c.get("channel_conflict")]
    if conflicts:
        print(f"\n   ⚠️  {len(conflicts)} entry(ies) disagree with themselves about the channel:")
        for c in conflicts[:5]:
            print(f"        {c['date']}  {c['to'][:34]:36} {c['channel_conflict']}")

    if missing:
        print(f"\n🔴 {len(missing)} send(s) written up but NOT in the ladder:")
        for m in missing[:20]:
            print(f"   · {m['date']}  {m['rung']:14} {m['to'][:36]:38} {m['title'][:40]}")
        if len(missing) > 20:
            print(f"   (+{len(missing) - 20} more)")
    elif cand:
        print(f"\n✅ every reconstructable write-up already has a ladder row.")
    else:
        # ⛔ NOT "✅ nothing missing". With zero candidates that sentence would be true and useless,
        # and it is the same two-states-render-identically failure this script exists to catch.
        print(f"\n⚪ no verdict on the gap: nothing could be reconstructed, so nothing was compared.")

    if a.show_skipped and skipped:
        print(f"\n── skipped, with the reason ──")
        for s in skipped[:40]:
            print(f"   {s['date']}  {'; '.join(s['why'])}")
            print(f"      {s['title']}")
        if len(skipped) > 40:
            print(f"   (+{len(skipped) - 40} more; this is a REPORT, not a drop)")

    if not a.write:
        if missing:
            print(f"\n   read-only. Re-run with --write to append {len(missing)} row(s), each tagged "
                  f"provenance={PROVENANCE!r} so the ladder can subtract them again.")
        return 0

    with io.open(a.sendlog, "a", encoding="utf-8") as fh:
        for m in missing:
            fh.write(json.dumps({
                "ts": f"{m['date']}T00:00:00", "date": m["date"], "channel": m["channel"],
                "status": "sent", "rung": m["rung"], "to": m["to"], "company": "",
                "targets": "", "subject": m["subject"], "followup_due": "", "segment": "",
                "panel": "n/a", "resume_panel": "n/a", "provenance": PROVENANCE,
            }, ensure_ascii=False) + "\n")
    print(f"\n✅ appended {len(missing)} row(s), each tagged provenance={PROVENANCE!r}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
