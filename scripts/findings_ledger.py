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

# The closed vocabulary `record_finding.py` enforces at write time. Duplicated here rather than
# imported: importing record_finding would pull in argparse and its whole CLI surface for one
# tuple, and the two are pinned together by test_ledger_verdict_vocabulary.py.
VERDICTS = ("SURVIVOR", "DROP", "UNVERIFIED", "DEFERRED")

# Strip a leading emoji/marker so "🔴 DROP — reason" reads the same as "DROP". `\w` alone is not
# enough: it would also eat the space before DROP and glue the emoji's byte remnants to nothing,
# so this targets everything that is NOT a letter or digit at the very start of the string.
_LEADING_NOISE = re.compile(r"^[^A-Za-z0-9]+")

_ERRORS = []


def normalize_verdict(raw):
    """Recover a closed-vocabulary verdict token from free-form or legacy prose, or "".

    ⛔ THE DEFECT THIS CLOSES. `verdict` had no closed vocabulary for a while before
    `record_finding.py` started enforcing one, so rows like `"🔴 DROP — zero on-lane roles..."`
    and `"SURVIVOR (qualified)"` sit in the ledger from before the gate existed, or from a hand
    edit that bypassed it. Every reader that tests `verdict == "SURVIVOR"` (or `"DROP"`) treats
    those rows as blank: not suppressed, not promoted, not counted — a verdict that took real
    screening time and has no effect on anything.

    This is NOT a license to accept arbitrary prose as a verdict. It recovers exactly one
    known token from the FRONT of the string — a leading marker stripped, then the first word
    up to whitespace or an opening paren, matched against the closed set. `"UNPROVEN — n too
    small"` and `"🟡 WATCH — ..."` are not recognized verdicts and correctly normalize to "",
    the same as a row with no verdict field at all: a real gap in the ledger, not a display bug,
    and it stays visible as a gap rather than being guessed into a token nobody wrote.
    """
    s = _LEADING_NOISE.sub("", str(raw or "")).strip()
    if not s:
        return ""
    first = re.split(r"[\s(]", s, 1)[0].upper()
    return first if first in VERDICTS else ""


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
        if normalize_verdict(row.get("verdict")) not in SUPPRESSING:
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


def unrecognized_verdicts():
    """[(company, raw verdict)] for every latest-row verdict `normalize_verdict` cannot place.

    The other half of the fix: a normalizing reader recovers what it can, but a row that
    recovers to "" (never written, or genuinely off-vocabulary like "WATCH") is still a real
    gap, and it must stay COUNTED rather than silently absorbed by the normalizer's own success
    on the other rows. `consistency-check.sh` reports this count so the gap surfaces before an
    operator notices a company missing from the board.
    """
    return sorted((r.get("company", "?"), r.get("verdict"))
                  for r in rulings().values()
                  if not normalize_verdict(r.get("verdict")))


if __name__ == "__main__":
    from datetime import date
    supp = suppressed()
    print(f"findings ledger: {len(rulings())} companies ruled · "
          f"{len(supp)} still suppressed as of {date.today().isoformat()}")
    for k, why in sorted(supp.items())[:20]:
        print(f"  · {k:<32} {why}")
    if len(supp) > 20:
        print(f"  … +{len(supp) - 20} more")
    unrec = unrecognized_verdicts()
    if unrec:
        print(f"  ⚠️  {len(unrec)} row(s) with an unrecognized verdict (invisible to every reader):")
        for co, v in unrec[:10]:
            print(f"      · {co}: {v!r}")
        if len(unrec) > 10:
            print(f"      … +{len(unrec) - 10} more")
    for e in load_errors()[:10]:
        print(f"  ⚠️  {e}")
