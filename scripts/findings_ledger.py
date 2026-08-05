#!/usr/bin/env python3
"""findings_ledger.py — the READER for DEFERRED verdicts in documents/findings/*.jsonl.

WHY THIS EXISTS (ruled 2026-08-02). `record_finding.py` makes a verdict durable and
`reconcile_findings.py` makes DROP and SURVIVOR visible. DEFERRED was deliberately routed
nowhere, and that decision is quoted in reconcile_findings.py's own header:

    "UNVERIFIED / DEFERRED → neither. They are recorded facts about an unfinished screen, and
     writing them anywhere authoritative would launder 'we could not tell' into a verdict."

That reasoning is correct about UNVERIFIED and wrong about DEFERRED, and the receipt arrived on
2026-08-02. Kuya Andy's #1 pick of the day was **a founder at a company ruled on days earlier**.
The owner had personally ruled on one company fifteen days earlier — DEFERRED, banked, "revisit only if
they raise," with a TRIPWIRE set for 2026-10-31 — and `rank_people()` handed the same name back at
the top of the list with no trace of that ruling anywhere on the card. Two more contacts at other companies,
both DEFERRED days earlier, sat at ranks 5 and 6 of the same list. Three
of the top six were rework.

**138 companies carry a DEFERRED latest verdict and nothing read a single one of them.**

The distinction this module draws, and it is the whole design:

  • UNVERIFIED means "the screen did not finish." Nobody ruled. It must NOT suppress, because
    suppressing it would let a failed fetch quietly bury a live company forever — which is the
    laundering reconcile_findings.py warns about, pointed the other way.
  • DEFERRED means "we looked, and set it aside." Somebody ruled. Resurfacing it silently costs
    the same screen twice and, worse, presents a settled question as a fresh one.

⚖️ SUPPRESSION IS NOT A DROP. A DEFERRED company never reaches the blocked list, never gets a
filter number, and stays fully visible in the excluded-reasons line with its date. You can
overrule it by naming the company. This module only stops it CLIMBING TO #1 unannounced.

⏳ TRIPWIRES ARE HONORED. A note carrying `TRIPWIRE <YYYY-MM-DD>` stops suppressing on that date,
which is what makes "revisit only if they raise" a scheduled question instead of a permanent
burial. one company AI carries the only one today (2026-10-31).

🔁 LAST-WRITE-WINS, per [[append-only-logs-need-last-write-wins]]. A company is screened by several
runs and the rows are append-only, so the LATEST row by `ts` is the ruling and every earlier row is
history. Reconcile once kept the FIRST row and discarded the corrections; that bug is not repeated
here. Ties on an identical `ts` fall back to file-then-line order, which is the arrival order.

Fails OPEN (empty ruling map) on a broken ledger, and says so via `load_errors()`. This is the
opposite of `rank_criteria.blocked_set()`, which fails CLOSED, and the asymmetry is deliberate: an
unreadable BLOCKED list that fails open offers you companies he has vetoed, while an unreadable
DEFERRED ledger that fails closed would hide his entire pipeline behind a parse error. The cost of
failing open here is one repeated screen, which is exactly today's bug and is survivable; the cost
of failing closed is an empty board with no explanation.
"""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
FINDINGS_DIR = os.path.join(REPO, "documents", "findings")

# Only DEFERRED suppresses. See the module docstring for why UNVERIFIED deliberately does not.
SUPPRESSING = ("DEFERRED",)

TRIPWIRE_RE = re.compile(r"TRIPWIRE[:\s]+(\d{4}-\d{2}-\d{2})", re.I)

_ERRORS = []


def canon(name):
    """The SAME normalizer the blocked list and the reconciler use, by import, never forked.

    A copied matcher drifts from its original the first time either side is fixed — that is
    screen_sweep.canon()'s own stated reason for being hoisted to module level. If the import
    breaks we fall back to a bare lowercase key rather than dying, and record the reason, because
    a degraded key still catches exact-name matches (which is most of them) whereas raising here
    would take the whole ranker down over a normalization helper.
    """
    try:
        import sys
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        from screen_sweep import canon as _c
        return _c(name)
    except Exception as e:                                  # pragma: no cover - import guard
        _ERRORS.append(f"canon fallback ({e.__class__.__name__})")
        return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _rows():
    """Every findings row, in arrival order (file name, then line number within the file)."""
    for path in sorted(glob.glob(os.path.join(FINDINGS_DIR, "*.jsonl"))):
        try:
            with open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        # One malformed line must not discard the file's other rulings.
                        _ERRORS.append(f"{os.path.basename(path)}:{i + 1} unparseable")
                        continue
                    if isinstance(row, dict) and row.get("company"):
                        yield row
        except Exception as e:
            _ERRORS.append(f"{os.path.basename(path)} unreadable ({e.__class__.__name__})")


def rulings():
    """company canon-key → the LATEST row for that company, whatever its verdict.

    Returns every verdict, not only the suppressing ones, so a caller can explain a company's
    state without re-reading the ledger. Filtering to SUPPRESSING is the caller's job via
    `suppressed()`.
    """
    latest = {}
    for order, row in enumerate(_rows()):
        key = canon(row["company"])
        if not key:
            continue
        # Sort key is (ts, arrival). `ts` decides; arrival breaks a tie in the order the rows were
        # actually written, which is the only ordering the file format preserves.
        stamp = (str(row.get("ts") or ""), order)
        prev = latest.get(key)
        if prev is None or stamp >= prev[0]:
            latest[key] = (stamp, row)
    return {k: v[1] for k, v in latest.items()}


def tripwire(row):
    """The date a DEFERRED ruling expires, or None. Read from the note's `TRIPWIRE YYYY-MM-DD`."""
    m = TRIPWIRE_RE.search(str(row.get("note") or ""))
    return m.group(1) if m else None


def suppressed(today=None):
    """company canon-key → a short human reason, for companies whose ruling still holds.

    `today` is an ISO date string, injected rather than read from the clock so a caller can test
    the tripwire boundary. A tripwire on or before `today` releases the company: the ruling was
    written as a question to re-ask on that date, and re-asking it is the point.
    """
    if today is None:
        from datetime import date
        today = date.today().isoformat()
    out = {}
    for key, row in rulings().items():
        if row.get("verdict") not in SUPPRESSING:
            continue
        tw = tripwire(row)
        if tw and tw <= today:
            continue                                        # the tripwire fired; ask again
        when = str(row.get("ts") or "")[:10]
        reason = f"deferred {when}" if when else "deferred"
        if tw:
            reason += f" (tripwire {tw})"
        out[key] = reason
    return out


def load_errors():
    """Whatever went wrong while reading, so a caller can print it instead of failing silently."""
    return list(_ERRORS)


if __name__ == "__main__":
    from datetime import date
    supp = suppressed()
    print(f"findings ledger: {len(rulings())} companies ruled · "
          f"{len(supp)} still suppressed as of {date.today().isoformat()}")
    for k, why in sorted(supp.items())[:20]:
        print(f"  · {k:<32} {why}")
    if len(supp) > 20:
        print(f"  … +{len(supp) - 20} more")
    for e in load_errors()[:10]:
        print(f"  ⚠️  {e}")
