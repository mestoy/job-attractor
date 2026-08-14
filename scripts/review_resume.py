#!/usr/bin/env python3
"""review_resume.py — run an independent reviewer panel over ONE résumé, then leave a receipt.

WHY THIS EXISTS. `WORKFLOW-RULES.md` carries *"3-panel review (CEO/CTO/CPO lenses) before
finalizing ANY artifact, then apply fixes"*, and for months nothing enforced it. `review_outreach.py`
mechanized the outreach half. This is the résumé half, and it is the one the rule was written next
to. A rule that nothing enforces runs when somebody remembers it.

⛔ THE RECEIPT IS THE POINT, NOT THE PANEL. A panel whose output nobody has to act on is the rule
that already existed. This writes `documents/state/resume-panels/<sha256>.json`, and `mail-draft.sh`
refuses to attach a résumé without one.

⚖️ THE HASH IS OF THE TEXT LAYER, NOT THE FILE BYTES, and that is a deliberate difference from the
outreach panel. `pdflatex` stamps a creation date into the PDF, so two builds of an unchanged `.tex`
have different bytes. Hashing bytes would orphan the receipt on every recompile and teach everyone
to re-run the panel without reading it, which is how a gate becomes a formality. The text layer is
what a reader and an ATS see: it is stable across a rebuild and it changes the moment the CONTENT
does. ⛔ So a reworded bullet still orphans the receipt. That is the binding, and it is intact.

⚠️ WHY A HASH AND NOT A FLAG. A `--panel-check pass` flag is an assertion: whoever types it is
promising the panel ran. That is honor-system, and an agent under time pressure can type it without
doing the work. A receipt cannot be typed from memory, and it changes when the résumé does.

Usage:
    scripts/review_resume.py <resume.pdf|resume.tex> [--company "<name>"] [--role "<title>"]
    scripts/review_resume.py <file> --show           # print an existing receipt, review nothing
    scripts/review_resume.py <file> --record '<json>'
Exit: 0 receipt written · 2 usage · 3 the résumé could not be read
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
PANEL_DIR = os.path.join(REPO, "documents", "state", "resume-panels")

# ── THE LENSES ───────────────────────────────────────────────────────────────────────────────
#
# ⚖️ THESE ARE THE CODIFIED THREE, NOT NEW ONES. `WORKFLOW-RULES.md:119` names CEO, CTO and CPO,
# and the whole point of this file is to mechanize the rule that exists rather than to invent a
# better one nobody agreed to. The outreach panel uses different lenses because a cold email fails
# differently from a résumé; a résumé fails by being unconvincing, by being undefensible in the
# interview that follows, or by being untargeted.
#
# ⛔ ORDER IS NOT PRIORITY. CEO is first because a résumé that does not earn the read fails before
# any other flaw matters, but a finding from any lens can stop an export.
_DEFAULT_LENSES = {
    "ceo": {
        "title": "THE CEO LENS — narrative and positioning",
        "asks": [
            "Read only the top third, the way a screener does. What is this person FOR? Say it in one line.",
            "Is the target title obvious without reading the bullets? Quote the line that decides it.",
            "Does the summary make a claim about outcomes, or does it describe a job? Name which.",
            "Is there a reason to talk to this person that a hundred other résumés do not also give?",
            "Which single bullet is the strongest, and is it in the top half? If not, say where it is.",
        ],
    },
    "cto": {
        "title": "THE CTO LENS — credibility and the interview-backtrack test",
        "asks": [
            "Every technical or quantified claim: could the candidate defend it under questioning?",
            "Any claim that implies they BUILT something an employer or a team built? Name it.",
            "Any figure, scope, headcount or budget stated more strongly than a record would support?",
            "Would an engineer reading this believe it, or would they read marketing? Quote the tell.",
            "Any credential stated without its current status, if that status has lapsed?",
        ],
    },
    "cpo": {
        "title": "THE CPO LENS — craft signal and targeting",
        "asks": [
            "Does this show product craft (discovery, 0-to-1, roadmap, outcomes) or only delivery?",
            "Against the target role: which of its stated needs does this résumé answer, and which does it leave unanswered?",
            "Is the language the JD's language, or the candidate's internal vocabulary?",
            "Is any gap handled honestly and early, or left for the reader to find and guess at?",
            "One page or two, is anything here NOT earning its space? Name the line to cut first.",
        ],
    },
}


# ── THE PANEL IS YOURS TO NAME (reported by a partner install, kit issue #16) ─────────────────
#
# ⛔ THE INCONSISTENCY THIS FIXES, and the kit's own words convict it. The OPTIONAL fourth lens
# already ships with this comment: "EMPTY BY DEFAULT, DELIBERATELY. The kit must not assume what
# kind of seat you are hunting, so it ships you the mechanism and none of the names." That
# reasoning applies with MORE force to the three lenses that ALWAYS run than to the optional one.
#
# 📊 THE RECEIPT. CEO, CTO and CPO is a product-startup executive panel. An operator hunting a
# remote product-owner or business-analyst seat in a regulated industry has a real interview loop of
# a hiring manager, a peer analyst, and the operations leader whose process changes. Run against
# that operator's resume, the CPO lens returned "shows delivery, not product craft, no discovery or
# roadmap ownership" — a fair critique of a startup product manager and a MIS-AIMED one for a
# backlog owner whose profile never claimed roadmap authority. They recognised the panel as
# belonging to someone else's search on sight.
#
# ⚠️ WHY THE EXISTING HOOK DID NOT COVER IT. `RESUME_EXPERT_LENSES` is built for a NAMED PUBLIC
# PRACTITIONER and renders as "critique this as {name} would, grounded in what they have published".
# Passing a job title there produces an instruction to cite the published methodology of a role,
# which is incoherent. The two mechanisms are complementary: one names a person, this one names a
# seat at your table.
#
# ⚖️ THE DEFAULT IS UNCHANGED, so an install that likes the executive panel sees nothing different.
def _core_lenses():
    """The three lenses that always run: `kit_config.RESUME_CORE_LENSES`, else the shipped default.

    A lens is a key mapped to `{"title": str, "asks": [str, ...]}`. Malformed config falls back to
    the default rather than running a broken panel, because a resume reviewed by nothing at all
    would still print a clean report.
    """
    try:
        import kit_config
        cfg = getattr(kit_config, "RESUME_CORE_LENSES", None)
        if isinstance(cfg, dict) and cfg and all(
                isinstance(v, dict) and v.get("title") and v.get("asks") for v in cfg.values()):
            return cfg
    except Exception:
        pass
    return _DEFAULT_LENSES


LENSES = _core_lenses()

# ⚖️ AN OPTIONAL FOURTH LENS, CONFIG-DRIVEN AND EMPTY BY DEFAULT. Some searches want a critique in
# a named practitioner's voice on top of the business three. Whose voice that should be depends
# entirely on what you are hunting, so the kit ships the mechanism and none of the names. Set
# RESUME_EXPERT_LENSES in scripts/kit_config.py, or leave it empty and run the three lenses alone.
def domain_experts():
    """Names configured for a domain-expert lens, or an empty list. Never fails the panel."""
    try:
        sys.path.insert(0, HERE)
        import kit_config  # noqa: PLC0415
        return list(getattr(kit_config, "RESUME_EXPERT_LENSES", []) or [])
    except Exception:
        return []


def text_layer(path):
    """The characters a reader and an ATS see. Returns None when the file cannot be read.

    ⛔ A .tex is hashed as its own bytes, deliberately. Hashing the source of an unbuilt résumé is
    honest about what was reviewed; it is the PDF the recipient receives, so that is the artifact
    the gate cares about, and reviewing the source is a courtesy rather than the gate's subject.
    """
    if path.lower().endswith(".pdf"):
        try:
            r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True)
        except Exception:
            return None
        if r.returncode != 0 or not r.stdout.strip():
            return None
        # Collapse whitespace runs: pdftotext's column reconstruction is not stable enough to hash
        # raw, and a receipt that orphans because a line wrapped differently is a receipt nobody
        # trusts. The WORDS are the content.
        return re.sub(r"\s+", " ", r.stdout).strip()
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


def artifact_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def receipt_path(sha):
    return os.path.join(PANEL_DIR, f"{sha}.json")


def existing(sha):
    p = receipt_path(sha)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def write_receipt(sha, findings, meta):
    """⛔ Records WHAT WAS REVIEWED and WHAT WAS FOUND, never a verdict.

    It deliberately does not say "approved". Approval is the human passing `--resume-panel-check
    pass` after reading the findings. A receipt that carried a verdict would let a panel authorize
    an export, and this is a review mechanism rather than an authorization one.
    """
    os.makedirs(PANEL_DIR, exist_ok=True)
    row = {
        "artifact_sha256": sha,
        "reviewed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lenses": sorted(LENSES),
        "findings": findings,
        **meta,
    }
    with open(receipt_path(sha), "w", encoding="utf-8") as fh:
        json.dump(row, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return row


def print_briefs(text, path, company, role):
    """Emit the reviewer briefs for the caller to run as independent agents.

    ⚠️ THIS SCRIPT DOES NOT CALL A MODEL. It prepares the panel and records the outcome, so it stays
    a plain stdlib tool that runs anywhere, in tests, and offline. The agent driving it runs the
    lenses, ideally in parallel and without showing one reviewer another's findings.
    """
    print(f"── résumé panel · {os.path.basename(path)} · {len(text.split())} words ──\n")
    for key, lens in LENSES.items():
        print(f"### LENS: {lens['title']}  (id: {key})")
        print("Read the résumé below and answer each question with a specific quote from it.")
        print("⛔ Do not soften. A finding you decline to state is a finding the candidate never gets.")
        for a in lens["asks"]:
            print(f"  · {a}")
        print()
    for name in domain_experts():
        print(f"### LENS: {name} (domain expert)")
        print(f"Critique this résumé as {name} would, in their real public methodology.")
        print("⛔ Ground every note in something they have actually published. Do not invent their opinion.")
        print()
    ctx = " · ".join(x for x in (f"company: {company}" if company else "",
                                f"role: {role}" if role else "") if x)
    if ctx:
        print(f"CONTEXT: {ctx}\n")
    print("─── RÉSUMÉ UNDER REVIEW ───")
    print(text)
    print("─── END ───")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("resume")
    ap.add_argument("--company", default="")
    ap.add_argument("--role", default="")
    ap.add_argument("--show", action="store_true", help="print the existing receipt and exit")
    ap.add_argument("--record", metavar="JSON",
                    help='findings as JSON: {"ceo": [...], "cto": [...], "cpo": [...]}')
    a = ap.parse_args(argv)

    text = text_layer(a.resume)
    if text is None:
        print(f"🔴 could not read a text layer from {a.resume}. If it is a PDF, is it built, and is "
              f"pdftotext installed?", file=sys.stderr)
        return 3

    sha = artifact_hash(text)

    if a.show:
        row = existing(sha)
        if not row:
            print(f"no receipt for this résumé ({sha[:12]})")
            return 0
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return 0

    if a.record is not None:
        try:
            findings = json.loads(a.record)
        except Exception as e:
            print(f"🔴 --record is not valid JSON: {e}", file=sys.stderr)
            return 2
        if not isinstance(findings, dict) or not set(findings) & set(LENSES):
            print(f"🔴 --record must carry at least one of: {', '.join(sorted(LENSES))}", file=sys.stderr)
            return 2
        missing = [k for k in LENSES if k not in findings]
        row = write_receipt(sha, findings, {"company": a.company, "role": a.role,
                                            "artifact": os.path.basename(a.resume),
                                            "lenses_missing": missing})
        n = sum(len(v) for v in findings.values() if isinstance(v, list))
        print(f"✅ receipt written · {sha[:12]} · {n} finding(s) across {len(findings)} lens(es)")
        if missing:
            # Reported, never silently tolerated: a partial panel is a real state (one lens may
            # legitimately have nothing to say) but it must be visible in the receipt and on screen.
            print(f"   ⚠️  no findings recorded for: {', '.join(missing)} — recorded as such, not as clean")
        print("   now: mail-draft.sh … --resume-panel-check pass")
        return 0

    prior = existing(sha)
    if prior:
        print(f"⚠️  a receipt already exists for this exact résumé ({sha[:12]}), written "
              f"{prior.get('reviewed_at')}. Re-running is fine; it will be overwritten.\n")
    print_briefs(text, a.resume, a.company, a.role)
    print("\n── after running the lenses ──")
    print("Record what came back, then the attachment unblocks:")
    print(f'  python3 scripts/review_resume.py "{a.resume}" \\')
    print("      --record '{\"ceo\": [\"…\"], \"cto\": [\"…\"], \"cpo\": [\"…\"]}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
