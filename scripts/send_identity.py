#!/usr/bin/env python3
"""send_identity.py — WHO a logged send went to, without ever rewriting the log.

⛔ THE INVARIANT THIS IS SHAPED AROUND. The log is NEVER rewritten: it is the record of what
happened and its shape is part of that record. So a send row that went out without a `to_name` keeps
its empty `to_name` forever. That is correct, and it is also why the ladder cannot answer questions
about PEOPLE on its own.

📊 THE COST (BUG-166). A large share of delivered sends carry no recipient name, and most of the
replies sit in that group, because the field is empty on the rungs that actually convert (warm and
reply). Two separate features died on this: the warm-path term (n too small, direction unmeasurable)
and the recruiter term (a thin cell below the n<15 floor `validate_signal` refuses to ratify on).
Neither signal is weak. Neither could be SEEN.

⚖️ SO THE NAME LIVES BESIDE THE LOG, NEVER INSIDE IT. This store is append-only and keyed by the
ADDRESS the send actually went to, which the row does carry. `name_for(row)` is the ONE definition
of "who was this to": the row's own `to_name` always wins, and the sidecar answers only where the
row is silent. That ordering matters — a recorded fact outranks a derived one, always.

🔬 EVERY ROW CARRIES ITS SOURCE AND CONFIDENCE, because these are not equally trustworthy:
  `export`   the LinkedIn export's own URL column maps that handle to that person. Not a guess.
  `stated`   a human said so.
  `crosswalk` a SQUASHED handle confirmed by a name the LOG ITSELF carries on a sibling row
             (`linkedin:janedoe` settled by a row addressed to the literal `Jane Doe`).
             Evidence, not inference, which is why it outranks `derived`.
  `derived`  read out of a hyphenated handle or a dotted email local-part (`jane-doe`,
             `jane.doe@`). Usually right, occasionally a middle name or a hyphenated surname.
⛔ A SQUASHED HANDLE IS NOT DERIVABLE and must not be guessed. `janedoe` could be Jane Doe or Jan
Edoe, and some handles reverse the name order. Those stay unresolved, which is an honest gap; a wrong
name here would silently corrupt every per-person rate downstream.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

STORE = os.path.join(REPO, "documents", "state", "send-identity.jsonl")

# Confidence ordering, so a later `export` row can supersede an earlier `derived` one for the same
# address without the file needing to be edited. Newest row wins only WITHIN a tier.
TIERS = {"stated": 4, "export": 3, "crosswalk": 2, "derived": 1}


def addr_key(addr):
    """Normalize an address so the same person written three ways lands on one key.

    The log carries `linkedin:janedoe`, `linkedin.com/in/janedoe` and
    `https://www.linkedin.com/in/janedoe/` for the same human, plus bare emails. Squash all of them.
    """
    a = (addr or "").strip().lower().rstrip("/")
    if not a:
        return ""
    if a.startswith("linkedin:"):
        return "li:" + a.split(":", 1)[1]
    m = re.search(r"linkedin\.com/in/([^/?#]+)", a)
    if m:
        return "li:" + m.group(1)
    if "@" in a:
        return "em:" + a
    return "raw:" + re.sub(r"\s+", " ", a)


def _rows():
    if not os.path.exists(STORE):
        return []
    out = []
    with open(STORE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue          # one bad line must not discard the file
    return out


def store():
    """addr_key -> the best row for it. Higher confidence tier wins; then later arrival."""
    best = {}
    for r in _rows():
        k = r.get("key")
        if not k or not r.get("name"):
            continue
        prev = best.get(k)
        if prev is None or TIERS.get(r.get("source"), 0) >= TIERS.get(prev.get("source"), 0):
            best[k] = r
    return best


def name_for(row, cache=None):
    """THE one definition of who a send went to. Returns ('', None) when genuinely unknown.

    ⛔ THE ROW'S OWN `to_name` ALWAYS WINS. This store exists to fill silence, never to correct the
    record. If a row says who it went to, that is the answer, even where the sidecar disagrees:
    the sidecar is derived from addresses and the row is what was written at send time.
    """
    named = (row.get("to_name") or "").strip()
    if named:
        return named, "logged"
    k = addr_key(row.get("to"))
    if not k:
        return "", None
    hit = (cache if cache is not None else store()).get(k)
    if not hit:
        return "", None
    return hit["name"], hit.get("source")


def company_for(row, cache=None):
    """The EMPLOYER a send went to, filling from the sidecar where the row is silent.

    ⛔ THE OTHER HALF OF BUG-166, AND IT IS A SEPARATE FIELD. Filling names did not move the
    warm-path signal at all, because that one joins on COMPANY: a large share of rows carry no
    company, and they hold most of the replies. Two problems were wearing one number.

    ⚠️ THE EXPORT'S COMPANY IS FROZEN AT EXPORT DATE, which the name is not. A person changes
    employers; their profile URL does not. So this answers "where did the export say they worked",
    which is the right answer for a send made near that export and a decaying one otherwise. The
    row's own `company` always wins, and every sidecar row keeps its source so a consumer can weigh
    it (the connect-date proxy is the same class).
    """
    stated = (row.get("company") or "").strip()
    if stated:
        return stated, "logged"
    k = addr_key(row.get("to"))
    if not k:
        return "", None
    hit = (cache if cache is not None else store()).get(k)
    if not hit or not hit.get("company"):
        return "", None
    return hit["company"], hit.get("source")


def append(rows, path=None):
    """Append identity rows. Returns how many were written. Never rewrites, never dedupes in place."""
    path = path or STORE
    good = [r for r in rows
            if r.get("key") and r.get("name") and r.get("source") in TIERS]
    if not good:
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in good:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(good)
