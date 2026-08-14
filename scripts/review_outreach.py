#!/usr/bin/env python3
"""review_outreach.py — run an independent reviewer panel over ONE outreach body, then leave a receipt.

WHY THIS EXISTS (2026-08-09). `WORKFLOW-RULES.md` has carried *"3-panel review before finalizing ANY
artifact"* since July. It was never mechanized. It sits in a block of résumé rules, so a line saying
"ANY artifact" reads as résumé-scoped. It is absent from the partner kit. And it was skipped that
same day on a real message to a real person, which is how it came to light.

⭐ **The question that surfaced it came from the partner install**, not from here: *"does your
install run MULTIPLE independent reviewers over the outreach EMAIL itself, beyond the checklist and
the linters?"* The honest answer was no. `check_outreach.py` lints mechanics — banned words, retired
claims, the seven ingredients, O-A-K, greeting shape, dense blocks. Nothing read the message the way
a person would.

⚖️ THE LENSES ARE CHOSEN FOR AN OUTREACH EMAIL, not borrowed from the product-artifact panel. A cold
message to a stranger fails differently from a résumé: it fails by being ignorable, by asking wrong,
or by claiming something that cannot be defended. So:

  1. RECIPIENT       would a busy person who has never heard of you reply? where does attention drop?
  2. METHOD          seven ingredients, O-A-K, praise specific and sourced, ask shaped to the rung
  3. HONESTY+VOICE   any claim not defensible from a primary source, any AI tell, any drift from the
                     writing samples

⛔ THE RECEIPT IS THE POINT, NOT THE PANEL. A panel whose output nobody has to act on is the rule
that already existed. This writes `documents/state/outreach-panels/<sha256-of-body>.json`, and
`mail-draft.sh` refuses to build without one. **The receipt is keyed to the BODY'S HASH**, so editing
one character after the review orphans it and the send blocks again. A panel run on an earlier draft
cannot authorize a later one.

⚠️ WHY A HASH AND NOT A FLAG, stated plainly because the difference is the whole mechanism.
`--lacivita-check pass` is an assertion: whoever types it is promising the checklist ran. That is
honor-system, and an agent under time pressure can type it without doing the work. A hash cannot be
typed from memory, and it changes the moment the text does.

Usage:
    scripts/review_outreach.py <body-file> --rung <rung> [--company "<name>"] [--boss "<name>"]
    scripts/review_outreach.py <body-file> --show          # print an existing receipt, review nothing
Exit: 0 receipt written · 2 usage · 3 the body could not be read
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
PANEL_DIR = os.path.join(REPO, "documents", "state", "outreach-panels")

# ── THE LENSES ───────────────────────────────────────────────────────────────────────────────
#
# Each is a PROMPT for an independent reviewer, and they are deliberately not variations on one
# question. Three reviewers asked the same thing produce one opinion with three signatures; the
# value is in reading the same text for different failure modes. That is the same reasoning behind
# the perspective-diverse verification this repo uses elsewhere.
#
# ⛔ ORDER IS NOT PRIORITY. RECIPIENT is first because a message nobody answers fails before any
# other flaw matters, but a finding from any lens can stop a send.
LENSES = {
    "recipient": {
        "title": "THE RECIPIENT",
        "asks": [
            "You are the person receiving this, and you have never heard of the sender. You are busy.",
            "Read it once, the way a real person does. Where does your attention drop? Name the line.",
            "Is there a reason to reply that is about YOU rather than about the sender's job search?",
            "Does the ask cost you more than ten seconds to answer? If yes, say what would make it cheaper.",
            "Would you feel researched, or processed? Quote the line that decides it.",
        ],
    },
    "method": {
        "title": "THE METHOD",
        "asks": [
            "Score against LaCivita's seven ingredients and O-A-K. Name any that is missing or weak.",
            "Is the praise beat a SPECIFIC sourced accomplishment, or generic product/mission praise?",
            "Is the ask the right shape for this rung? A cold boss asks about working for them; a warm "
            "connector asks who they know; a rung 1-2 note asks for acceptance and nothing more.",
            "Is the opener about the recipient, or about the sender?",
            "One touch per medium, one company per ask. Any violation?",
        ],
    },
    "honesty_voice": {
        "title": "HONESTY AND VOICE",
        "asks": [
            "Every factual claim: can it be defended from a primary source? Name any that cannot.",
            "Any figure, title, scope or credential stated more strongly than the record supports?",
            "Any AI tell: filler adverbs, clichés, 'not X but Y', em dashes, borrowed phrasing?",
            "Does this read like the writing samples, or like a generic professional register?",
            "Would the sender be comfortable if the recipient forwarded this to someone who knows them?",
        ],
    },
}


def body_hash(text):
    """SHA-256 of the exact bytes reviewed. The receipt's identity, and the reason it cannot be faked."""
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


def write_receipt(sha, rung, findings, meta):
    """⛔ The receipt records WHAT WAS REVIEWED and WHAT WAS FOUND, never a verdict.

    It deliberately does NOT say "approved". Approval is the human passing `--panel-check pass` to
    mail-draft.sh after reading the findings. A receipt that carried a verdict would let a panel
    authorize a send, and this is a review mechanism, not an authorization one, exactly as the boss
    registry is research rather than consent.
    """
    os.makedirs(PANEL_DIR, exist_ok=True)
    row = {
        "body_sha256": sha,
        "rung": rung,
        "reviewed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lenses": sorted(LENSES),
        "findings": findings,
        **meta,
    }
    with open(receipt_path(sha), "w", encoding="utf-8") as fh:
        json.dump(row, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return row


def print_briefs(text, rung, company, boss):
    """Emit the three reviewer briefs for the caller to run as independent agents.

    ⚠️ THIS SCRIPT DOES NOT CALL A MODEL. It prepares the panel and records the outcome, so it stays
    a plain stdlib tool that runs anywhere, in tests, and offline. The agent driving it runs the
    three briefs, ideally in parallel and without showing one reviewer another's findings, then
    passes what came back to `--record`.
    """
    print(f"── reviewer panel · rung {rung} · {len(text.split())} words ──\n")
    for key, lens in LENSES.items():
        print(f"### LENS: {lens['title']}  (id: {key})")
        print("Read the body below and answer each question with a specific quote from it.")
        print("⛔ Do not soften. A finding you decline to state is a finding the sender never gets.")
        for a in lens["asks"]:
            print(f"  · {a}")
        print()
    ctx = " · ".join(x for x in (f"company: {company}" if company else "",
                                f"boss: {boss}" if boss else "") if x)
    if ctx:
        print(f"CONTEXT: {ctx}\n")
    print("─── BODY UNDER REVIEW ───")
    print(text)
    print("─── END BODY ───")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("body_file")
    ap.add_argument("--rung", default="")
    ap.add_argument("--company", default="")
    ap.add_argument("--boss", default="")
    ap.add_argument("--show", action="store_true", help="print the existing receipt and exit")
    ap.add_argument("--record", metavar="JSON",
                    help="findings as JSON: {\"recipient\": [...], \"method\": [...], \"honesty_voice\": [...]}")
    a = ap.parse_args(argv)

    try:
        with open(a.body_file, encoding="utf-8") as fh:
            text = fh.read()
    except Exception as e:
        print(f"🔴 could not read {a.body_file}: {e}", file=sys.stderr)
        return 3

    sha = body_hash(text)

    if a.show:
        row = existing(sha)
        if not row:
            print(f"no receipt for this body ({sha[:12]})")
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
        row = write_receipt(sha, a.rung, findings,
                            {"company": a.company, "boss": a.boss, "lenses_missing": missing})
        n = sum(len(v) for v in findings.values() if isinstance(v, list))
        print(f"✅ receipt written · {sha[:12]} · {n} finding(s) across {len(findings)} lens(es)")
        if missing:
            # Reported, never silently tolerated: a partial panel is a real state (one lens may
            # legitimately have nothing to say) but it must be visible in the receipt and on screen.
            print(f"   ⚠️  no findings recorded for: {', '.join(missing)} — recorded as such, not as clean")
        print(f"   now: mail-draft.sh … --panel-check pass")
        return 0

    prior = existing(sha)
    if prior:
        print(f"⚠️  a receipt already exists for this exact body ({sha[:12]}), written "
              f"{prior.get('reviewed_at')}. Re-running is fine; it will be overwritten.\n")
    print_briefs(text, a.rung or "(unspecified)", a.company, a.boss)
    print("\n── after running the three lenses ──")
    print("Record what came back, then the send unblocks:")
    print(f'  python3 scripts/review_outreach.py "{a.body_file}" --rung "{a.rung}" \\')
    print("      --record '{\"recipient\": [\"…\"], \"method\": [\"…\"], \"honesty_voice\": [\"…\"]}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
