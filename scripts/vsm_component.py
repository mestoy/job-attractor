#!/usr/bin/env python3
"""vsm_component.py — the value-stream component of a boss-hunt note, co-constructed not remembered.

WHY THIS EXISTS (Issue #65). Every boss-hunt note is supposed to SEND VALUE, not just praise: it
carries a research-grounded value-stream read of the target org and names the single number that is
the org's core promise to its customer, framed as "the problem I want to work on." That rule has
lived only as checklist guidance, so it depended on the operator remembering to do it by hand each
run. This deploys it as a first-class, repeatable, co-constructed step: research fans out and
generates MULTIPLE candidate numbers, a CEO/CTO/CPO-style panel vets them to >=95, the survivors are
presented as a PICKER with the panel default as option 1, and the operator picks. The picked number
is then phrased SHOW-DON'T-TELL — plain words, no coined metric term, never labeled "the value
stream" — because asking the sharp number IS the demonstration.

WHAT THIS FILE IS AND IS NOT.
  • It is the DETERMINISTIC spine of the step: it enforces the calibrated lens on each candidate,
    enforces the >=95 panel gate, orders the picker so the panel default is option 1, records the
    operator's pick, and gates the final plain-words sentence for show-don't-tell.
  • It is NOT the research or the panel themselves — those are agent/team activities the skill
    (job-attractor-pipeline / boss-hunt-message) drives. This script is what makes their output a
    repeatable pipeline step instead of a from-memory reconstruction, and what refuses to present a
    candidate that fails the lens or the panel gate.

THE CALIBRATED LENS. Pick the number that is the org's CORE PROMISE to its customer, expressed as
the customer's TIME or COST to value, in the org's OWN language. NOT internal-ops, NOT scale/breadth,
NOT a vanity count. A candidate that reads as ops throughput or a headcount/coverage brag is rejected
here, before the operator ever sees it.

Usage:
    # present verified candidates as a picker (candidates as JSON on stdin or --candidates FILE)
    vsm_component.py present --company "Acme School Fund" --candidates cands.json
    # the operator's pick + the plain-words sentence they will actually send
    vsm_component.py pick --option 1 --sentence "how long from a parent's intent to give until the school actually has the money"
    # standalone show-don't-tell gate on a sentence (exit 0 clean, 3 violations)
    vsm_component.py check-sentence "the share of intended giving that completes"
    vsm_component.py --clear
    vsm_component.py --require-required cold-boss   # is the step required for this rung?

Exit: 0 ok · 2 usage/no-candidates · 3 gate failure (lens/panel/show-don't-tell)
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
PENDING = os.path.join(REPO, "documents", "pending-vsm.json")
TTL_SECONDS = 2 * 60 * 60

# The panel bar. A candidate reaches the operator only if the LOWEST panel voice scored it here or
# above — mirrors the workspace rule "panel-vetted to 95, he decides".
PANEL_FLOOR = 95

# Rungs that OWE a value-stream number. Boss-hunt notes must send value; warm/reply/thank-you/other
# comms MAY carry one but are not blocked without it (AC: optional for those, required for boss-hunt).
REQUIRED_RUNGS = {"cold-boss", "cold-boss-unequipped", "cold-stranger", "referred"}

# Candidate "kind" values the lens REJECTS: the number must be the customer's time/cost to value, so
# an internal-ops / scale / breadth / vanity number is off-lens by construction.
OFF_LENS_KINDS = {"internal-ops", "ops", "scale", "breadth", "vanity", "headcount", "coverage"}
# Units that read as customer time-or-cost-to-value (on-lens). A candidate carries either an explicit
# on-lens `kind` ("time"/"cost"/"core-promise") or a unit that matches one of these.
TIME_UNITS = {"days", "hours", "minutes", "weeks", "time", "cycle-time", "lead-time", "turnaround"}
COST_UNITS = {"dollars", "cost", "fees", "%", "percent", "rate", "share"}

# Show-don't-tell: a coined metric TERM is a capitalized multi-word label, or a single word dressed as
# a proprietary metric (TitleCase ending in Rate/Score/Index/Ratio/Rating/Velocity/Time presented as
# a NAME). And the note must never label the number "the value stream" / "VSM".
_LABEL_LEAK = re.compile(r"\b(value[\s-]?stream|VSM|value[\s-]?stream\s+map(ping)?)\b", re.IGNORECASE)
_COINED_SUFFIX = re.compile(
    r"\b([A-Z][a-z]+(?:[\s-][A-Z][a-z]+)*[\s-](?:Rate|Score|Index|Ratio|Rating|Velocity|Time|Metric))\b"
)
# A capitalized multi-word phrase (>=2 Capitalized tokens) reads as a coined proper-noun metric name.
_COINED_PHRASE = re.compile(r"\b([A-Z][a-z]+(?:[\s-][A-Z][a-z]+){1,3})\b")
# Words allowed to be capitalized inside an otherwise-plain sentence (sentence start etc. is handled
# by position). Proper nouns the operator legitimately names (the company) are passed in and skipped.


def _now():
    return datetime.now(timezone.utc)


def validate_lens(cand: dict):
    """(ok, reasons) — does this candidate fit the calibrated lens?

    On-lens = the org's core promise to its customer, as the customer's time or cost to value. A
    candidate is REJECTED if its kind is an off-lens kind (ops/scale/breadth/vanity) or if it names
    neither an on-lens kind nor a time/cost unit. `voice` must be the customer's, not internal.
    """
    reasons = []
    kind = str(cand.get("kind", "")).strip().lower()
    unit = str(cand.get("unit", "")).strip().lower()
    voice = str(cand.get("voice", "")).strip().lower()

    if kind in OFF_LENS_KINDS:
        reasons.append(f"off-lens kind {kind!r}: the number must be the customer's time/cost to "
                       f"value, not internal-ops/scale/breadth")
    on_lens_kind = kind in {"time", "cost", "core-promise", "promise"}
    on_lens_unit = unit in TIME_UNITS or unit in COST_UNITS
    if not (on_lens_kind or on_lens_unit):
        reasons.append("no time-or-cost-to-value signal: give kind time|cost|core-promise or a "
                       "time/cost unit (days, %, dollars, ...)")
    if voice and voice not in {"customer", "core-promise", "promise"}:
        reasons.append(f"voice {voice!r} is not the customer's promise (internal/ops voice is "
                       f"off-lens)")
    return (not reasons, reasons)


def panel_ok(cand: dict):
    """True if the LOWEST panel voice scored the candidate at or above the floor.

    `panel` is a dict like {"ceo": 96, "cto": 95, "cpo": 97}. Absent/empty panel never passes — a
    candidate with no vetting cannot reach the operator.
    """
    panel = cand.get("panel") or {}
    if not isinstance(panel, dict) or not panel:
        return False
    try:
        scores = [float(v) for v in panel.values()]
    except (TypeError, ValueError):
        return False
    return bool(scores) and min(scores) >= PANEL_FLOOR


def eligible(candidates):
    """(kept, dropped) — candidates that pass BOTH the lens and the panel gate, and why the rest fell.

    Kept are ordered by panel default first: a candidate flagged {"default": true} leads, else the
    highest minimum-panel-score leads. The leader becomes picker option 1 (the panel's recommendation).
    """
    kept, dropped = [], []
    for c in candidates:
        ok_lens, why = validate_lens(c)
        if not ok_lens:
            dropped.append((c, "; ".join(why)))
            continue
        if not panel_ok(c):
            dropped.append((c, f"panel below {PANEL_FLOOR} or unvetted"))
            continue
        kept.append(c)

    def _minscore(c):
        panel = c.get("panel") or {}
        try:
            return min(float(v) for v in panel.values())
        except (TypeError, ValueError):
            return 0.0

    kept.sort(key=lambda c: (0 if c.get("default") else 1, -_minscore(c)))
    return kept, dropped


def show_dont_tell_violations(sentence: str, company: str = ""):
    """[issues] — reasons the plain-words sentence is NOT show-don't-tell.

    Flags: (1) labeling the number "the value stream"/"VSM", (2) a coined metric term (TitleCase +
    Rate/Score/Index/...), (3) a capitalized multi-word phrase that reads as a proprietary metric
    NAME. The company name is allowed and skipped so "Acme School Fund" is not read as a coined term.
    """
    issues = []
    s = sentence or ""
    if _LABEL_LEAK.search(s):
        issues.append('labels the number "the value stream" / "VSM" — do not name the lens; asking '
                      "the number IS the demonstration")
    if _COINED_SUFFIX.search(s):
        m = _COINED_SUFFIX.search(s)
        issues.append(f'coined metric term "{m.group(1)}" — say it in plain words, not a named metric')

    # Strip the company name before hunting capitalized proper-noun phrases, so a legitimately-named
    # employer is not mistaken for a coined metric.
    scrubbed = s
    if company:
        scrubbed = re.sub(re.escape(company), "", scrubbed, flags=re.IGNORECASE)
    for m in _COINED_PHRASE.finditer(scrubbed):
        phrase = m.group(1)
        # A phrase at the very start of the sentence is ordinary capitalization, not a coined name.
        if s.strip().startswith(phrase):
            continue
        issues.append(f'capitalized phrase "{phrase}" reads as a coined metric name — lowercase it '
                      f'into plain words')
    return issues


def is_required(rung: str) -> bool:
    return str(rung or "").strip().lower() in REQUIRED_RUNGS


def write_pending(company, kept, dropped):
    os.makedirs(os.path.dirname(PENDING), exist_ok=True)
    row = {
        "company": (company or "").strip(),
        "ts": _now().isoformat(),
        "candidates": kept,
        "dropped": [{"candidate": c, "why": why} for c, why in dropped],
        "note": "VSM candidates presented as a picker; awaiting the operator's pick. NOT the send.",
    }
    with open(PENDING, "w", encoding="utf-8") as fh:
        json.dump(row, fh, ensure_ascii=False, indent=2)


def read_pending():
    if not os.path.exists(PENDING):
        return None
    try:
        with open(PENDING, encoding="utf-8") as fh:
            row = json.load(fh)
    except (OSError, ValueError):
        return None
    ts = row.get("ts")
    if ts:
        try:
            age = (_now() - datetime.fromisoformat(ts)).total_seconds()
            if age > TTL_SECONDS:
                return None
        except ValueError:
            return None
    return row


def _render_picker(company, kept):
    lines = [f"NEXT-STEP · value-stream number for {company or '(company)'} — you pick:"]
    for i, c in enumerate(kept, 1):
        who = "panel default" if i == 1 else f"panel min {_minfmt(c)}"
        desc = c.get("plain") or c.get("desc") or c.get("name") or "(unnamed)"
        lines.append(f"  {i}. {desc}   [{who}]")
    lines.append("  (each is the org's core promise as the customer's time or cost to value)")
    return "\n".join(lines)


def _minfmt(c):
    panel = c.get("panel") or {}
    try:
        return f"{min(float(v) for v in panel.values()):.0f}"
    except (TypeError, ValueError):
        return "?"


def _load_candidates(args):
    raw = None
    if args.candidates:
        with open(args.candidates, encoding="utf-8") as fh:
            raw = fh.read()
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    if not raw or not raw.strip():
        return None
    data = json.loads(raw)
    if isinstance(data, dict) and "candidates" in data:
        data = data["candidates"]
    return data if isinstance(data, list) else None


def cmd_present(args):
    candidates = _load_candidates(args)
    if not candidates:
        print("no candidates supplied (JSON list on stdin or --candidates FILE)", file=sys.stderr)
        return 2
    kept, dropped = eligible(candidates)
    if not kept:
        print("NO candidate cleared the lens + panel>=95 gate. Nothing to present.", file=sys.stderr)
        for c, why in dropped:
            print(f"  dropped {c.get('name') or c.get('plain') or c!r}: {why}", file=sys.stderr)
        return 3
    write_pending(args.company, kept, dropped)
    print(_render_picker(args.company, kept))
    if dropped:
        print(f"({len(dropped)} candidate(s) dropped off-lens or below the panel floor)")
    return 0


def cmd_pick(args):
    row = read_pending()
    if not row:
        print("no live VSM picker to pick from (present candidates first, or it expired)",
              file=sys.stderr)
        return 2
    kept = row.get("candidates") or []
    chosen = None
    if args.option is not None:
        if not (1 <= args.option <= len(kept)):
            print(f"option {args.option} out of range 1..{len(kept)}", file=sys.stderr)
            return 2
        chosen = kept[args.option - 1]
    sentence = args.sentence or (chosen or {}).get("plain") or ""
    if not sentence.strip():
        print("no plain-words sentence to gate (pass --sentence)", file=sys.stderr)
        return 2
    issues = show_dont_tell_violations(sentence, company=row.get("company", ""))
    if issues:
        print("SHOW-DON'T-TELL gate FAILED:", file=sys.stderr)
        for it in issues:
            print(f"  - {it}", file=sys.stderr)
        return 3
    print(f"VSM number locked for {row.get('company') or '(company)'}: {sentence.strip()}")
    return 0


def cmd_check_sentence(args):
    issues = show_dont_tell_violations(args.sentence, company=args.company or "")
    if issues:
        print("SHOW-DON'T-TELL gate FAILED:", file=sys.stderr)
        for it in issues:
            print(f"  - {it}", file=sys.stderr)
        return 3
    print("show-don't-tell: clean")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clear", action="store_true", help="drop any pending VSM picker")
    p.add_argument("--require-required", metavar="RUNG",
                   help="print yes/no: does this rung owe a value-stream number?")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("present", help="present verified candidates as a picker")
    sp.add_argument("--company", default="")
    sp.add_argument("--candidates", help="path to a JSON list of candidates (else read stdin)")

    pk = sub.add_parser("pick", help="record the operator's pick + gate the plain-words sentence")
    pk.add_argument("--option", type=int, default=None)
    pk.add_argument("--sentence", default=None)

    cs = sub.add_parser("check-sentence", help="show-don't-tell gate on a sentence")
    cs.add_argument("sentence")
    cs.add_argument("--company", default="")

    args = p.parse_args(argv)

    if args.clear:
        if os.path.exists(PENDING):
            os.remove(PENDING)
        print("pending VSM picker cleared")
        return 0
    if args.require_required is not None:
        print("yes" if is_required(args.require_required) else "no")
        return 0
    if args.cmd == "present":
        return cmd_present(args)
    if args.cmd == "pick":
        return cmd_pick(args)
    if args.cmd == "check-sentence":
        return cmd_check_sentence(args)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
