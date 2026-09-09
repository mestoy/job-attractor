#!/usr/bin/env python3
"""new_card.py — scaffold a screening card, in the shape render_scorecard.py already reads.

WHY THIS EXISTS. Michael: "I want everyone who installs the pipeline to get scorecards
like we use." render_scorecard.py (kit #88) closes the READ side — it turns a card
markdown into an HTML scorecard — but a partner install has no scaffold that produces a
card shaped to match its 13-slot keyword contract. This closes the WRITE side.

SLOT ORDER, per card-scaffold-plan-53-2026-09-09.md's ruled default: HARD-INVARIANTS'
gate order (dedup → blocked-list → hard filters → live-role-verify → culture/leadership/
news → scorecard), not render_scorecard.py's own internal list order. Safe to reorder:
render_scorecard.py's ParsedCard.slot() matches every section by keyword search, never
by position.

PREFILL SCOPE, per the ruled default: only mechanically-sourced fields (a verdict row
from documents/findings/<run>.jsonl, an employer row from documents/employers.jsonl),
each cited inline with where it came from. Never a fabricated culture read, boss name,
or fit narrative — every unfilled slot gets an OWED placeholder naming the
workflow-checklist.md step that produces it, so the skeleton doubles as a checklist.

SAFETY CHECK (not in the original ask, added because it's cheap and obviously right):
refuses to scaffold a company employers.jsonl already marks status:blocked — the
dedup/blocked-list gate already says DROP for that company; producing a fresh card for
it would be building on top of a decision the pipeline already made.

Usage:
    python3 scripts/new_card.py "<Company>"
    python3 scripts/new_card.py "<Company>" --out documents/state --findings-dir documents/findings
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_finding(company, findings_dir):
    """Newest documents/findings/*.jsonl row matching company (normalized), or None."""
    want = _norm(company)
    if not want or not os.path.isdir(findings_dir):
        return None
    best = None
    for path in sorted(glob.glob(os.path.join(findings_dir, "*.jsonl"))):
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if _norm(row.get("company", "")) == want:
                        best = row  # keep the LAST match across sorted files = newest
        except OSError:
            continue
    return best


def load_employer(company, employers_path):
    """Row from employers.jsonl matching company's normalized key, or None."""
    want = _norm(company)
    if not want or not os.path.exists(employers_path):
        return None
    try:
        with open(employers_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if _norm(row.get("key", "")) == want or _norm(row.get("employer", "")) == want:
                    return row
    except OSError:
        return None
    return None


def refuse_if_blocked(employer_row):
    """A refusal message if employer_row shows status:blocked, else None."""
    if employer_row and employer_row.get("status") == "blocked":
        return (f"⛔ REFUSED: this company is already marked BLOCKED in employers.jsonl "
                f"(the dedup/blocked-list gate already says DROP). Not scaffolding a fresh "
                f"card for a decision the pipeline already made.")
    return None


def _owed(step_n, step_name):
    return (f"OWED — run `workflow-checklist.md` step {step_n} ({step_name}) and fill this in. "
            f"Never invent a value here.")


def _sourced(text, source):
    return f"{text}\n\n_Source: {source}._"


# (slot key, header text — matches render_scorecard.py's REQUIRED_SLOTS keyword regex
# verbatim — the workflow-checklist.md step this slot's gate belongs to)
SKELETON_SECTIONS = [
    ("dedup", "0. Dedup check", 1, "dedup"),
    ("blocked_hardfilter", "1. Blocked list / hard filters", 2, "blocked-list"),
    ("news_layoffs", "2. Industry news & layoffs (12 mo)", 3, "hard filters"),
    ("ownership", "3. Ownership", 3, "hard filters"),
    ("live_req", "4. Live PM req", 4, "live-role verify"),
    ("culture", "5. Culture", 5, "culture/leadership/news"),
    ("leadership_retention", "6. Leadership & retention", 5, "culture/leadership/news"),
    ("remote_reality", "7. Remote reality", 4, "live-role verify"),
    ("boss", "8. Boss", 6, "scorecard + pause"),
    ("current_direction", "9. Current Direction (dated)", 6, "scorecard + pause"),
    ("fit_read", "10. Fit read", 6, "scorecard + pause"),
    ("panel", "11. Panel", 6, "scorecard + pause"),
    ("score_history", "Score history", 6, "scorecard + pause"),
    ("sources", "Sources, with links", 6, "scorecard + pause"),
]
OPTIONAL_SKELETON_SECTIONS = [
    ("product_team", "Product team", 6, "scorecard + pause"),
    ("gate_owed", "Gate still owed", 6, "scorecard + pause"),
    ("public_errors", "Public errors", 6, "scorecard + pause"),
    ("ask_register", "Ask register suggestion", 6, "scorecard + pause"),
]


def render_skeleton(company, finding, employer, today=None):
    today = today or date.today().isoformat()
    finding = finding or {}
    employer = employer or {}

    lines = [f"# {company} · UNVERIFIED · {today}", ""]
    lines.append("Scaffolded by scripts/new_card.py. Fill every OWED slot in gate order "
                  "before this card reaches a picker.")
    lines.append("")

    def section(key, header, step_n, step_name, prefill=None, source=None):
        lines.append(f"## {header}")
        lines.append("")
        if prefill:
            lines.append(_sourced(str(prefill), source) if source else str(prefill))
        else:
            lines.append(_owed(step_n, step_name))
        lines.append("")

    for key, header, step_n, step_name in SKELETON_SECTIONS:
        prefill = source = None
        if key == "remote_reality" and finding.get("remote"):
            prefill, source = finding["remote"], f"documents/findings/{finding.get('run', '?')}.jsonl"
        elif key == "ownership" and finding.get("ownership"):
            prefill, source = finding["ownership"], f"documents/findings/{finding.get('run', '?')}.jsonl"
        elif key == "live_req" and finding.get("pm_req"):
            prefill, source = finding["pm_req"], f"documents/findings/{finding.get('run', '?')}.jsonl"
        elif key == "sources" and finding.get("evidence"):
            prefill, source = f"- {finding['evidence']}", f"documents/findings/{finding.get('run', '?')}.jsonl"
        elif key == "blocked_hardfilter" and employer.get("segment"):
            prefill = f"Segment: {employer['segment']}" + (
                f" · Industry: {employer['industry']}" if employer.get("industry") else "")
            source = "documents/employers.jsonl"
        section(key, header, step_n, step_name, prefill, source)

    for key, header, step_n, step_name in OPTIONAL_SKELETON_SECTIONS:
        section(key, header, step_n, step_name)

    return "\n".join(lines).rstrip() + "\n"


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "company"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("company", help="company name to scaffold a card for")
    ap.add_argument("--out", default=os.path.join(REPO, "documents", "state"))
    ap.add_argument("--findings-dir", default=os.path.join(REPO, "documents", "findings"))
    ap.add_argument("--employers-path", default=os.path.join(REPO, "documents", "employers.jsonl"))
    args = ap.parse_args()

    employer = load_employer(args.company, args.employers_path)
    refusal = refuse_if_blocked(employer)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2

    finding = load_finding(args.company, args.findings_dir)
    text = render_skeleton(args.company, finding, employer)

    os.makedirs(args.out, exist_ok=True)
    today = date.today().isoformat()
    out_path = os.path.join(args.out, f"{_slug(args.company)}-card-{today}.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"OK   scaffolded {args.company!r} -> {out_path}"
          + (" (prefilled from a finding row)" if finding else "")
          + (" (prefilled from employers.jsonl)" if employer else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
