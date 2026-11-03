#!/usr/bin/env python3
"""stage_funnel.py -- the reply-to-offer funnel, computed PER THREAD, plus the replied-only list.

Outcome tracking is easy to let stop at `replied`: a reply is not a call, a call is not an
interview, an interview is not an offer, and the true north star is interviews and offers, not
replies. The logger already records advances via `--stage`
(sent, replied, conversation, screen, interview, onsite, offer, closed), but a stage lands on the
LATEST row for a recipient, so a naive per-row count under-reports it. This reads the funnel the
way it must be read, PER THREAD (per recipient, via the logger's own same_recipient), and then
lists the threads that replied and stopped there, so each can be staged as its real outcome lands.

Run: `python3 scripts/stage_funnel.py`  (add --replied-only to print just the threads owed a stage).
It never writes; it only reports. Populate the funnel with `log_linkedin_send.py --stage <s> --to <r>`.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from log_linkedin_send import same_recipient, REPO  # noqa: E402

STAGES = ["sent", "replied", "conversation", "screen", "interview", "onsite", "offer", "closed"]
RANK = {s: i for i, s in enumerate(STAGES)}
# `closed` is terminal and orthogonal to depth; rank it high so it does not read as "past offer".
RANK["closed"] = len(STAGES)


def _threads(rows):
    """Collapse send-log rows to one entry per recipient: did they reply, and the deepest stage."""
    threads = []
    for r in rows:
        to = r.get("to") or ""
        hit = next((t for t in threads if same_recipient(t["to"], to)), None)
        if hit is None:
            hit = {"to": to, "name": "", "company": "", "replied": False, "stage": "sent"}
            threads.append(hit)
        if r.get("replied"):
            hit["replied"] = True
        st = r.get("stage")
        if st and RANK.get(st, 0) > RANK.get(hit["stage"], 0):
            hit["stage"] = st
        if r.get("to_name") and not hit["name"]:
            hit["name"] = r.get("to_name")
        if r.get("company") and not hit["company"]:
            hit["company"] = r.get("company")
    return threads


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = os.path.join(REPO, "documents", "send-log.jsonl")
    try:
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        print("(no send-log yet)")
        return 0
    threads = _threads(rows)
    # A thread "in the funnel" replied, or reached a stage past replied even if the flag missed.
    engaged = [t for t in threads if t["replied"] or RANK.get(t["stage"], 0) >= RANK["replied"]]

    counts = {s: 0 for s in STAGES}
    for t in engaged:
        deepest = t["stage"] if RANK.get(t["stage"], 0) > RANK["replied"] else "replied"
        counts[deepest] = counts.get(deepest, 0) + 1

    replied_only = [t for t in engaged if RANK.get(t["stage"], 0) < RANK["conversation"]]

    if "--replied-only" in argv:
        print(f"REPLIED-ONLY threads owed a stage decision ({len(replied_only)}):")
        for t in replied_only:
            print(f"  {t['name'] or t['to']}  ({t['company'] or 'company?'})")
        return 0

    print("── STAGE FUNNEL (per thread) ──")
    for s in STAGES:
        if s in ("sent",):
            continue
        label = s if s != "replied" else "replied (only)"
        print(f"  {label:16} {counts.get(s, 0):3}")
    print(f"\n  {len(replied_only)} replied threads carry no stage past 'replied'.")
    print("  A reply is not an interview. Stage each as its outcome lands:")
    print("    python3 scripts/log_linkedin_send.py --stage conversation --to <recipient>")
    print("  See the full list with:  python3 scripts/stage_funnel.py --replied-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
