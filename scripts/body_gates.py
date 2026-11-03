#!/usr/bin/env python3
"""body_gates.py -- the gates that depend only on the BODY of an outreach note, as importable functions.

BUG-202 item 2. mail-draft.sh used to carry the warm body/targets cross-check as an inline heredoc, so the only
way to learn whether a note would pass it was to attempt the send. Now mail-draft.sh and preflight_note.py call the
SAME functions, so a verdict cannot drift between them (the repo has paid for that drift before: check_preview and
mail-draft once held two copies of the BUILD match and disagreed).

CLI (what mail-draft.sh calls):
    body_gates.py targets <data-root> <body-file> <targets-csv>     exit 0 clean, 1 blocked (messages on stderr)
    body_gates.py phrasing <body-file> <phrasing>                   exit 0 found verbatim, 1 not

Nothing here writes a file or runs a subprocess except check_outreach_text(), which only reads.
"""
import os
import re
import subprocess
import sys


def targets_cross_check(here, bodyfile, targets_raw, out=None, err=None):
    """G2b: the body must name at least one declared --targets company, and no blocked or already-contacted company
    that is not declared. `here` is the DATA ROOT. Returns 0 (clean) or 1 (blocked); messages go to out/err.
    Moved verbatim from the mail-draft.sh PYBODY heredoc."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr

    body = open(bodyfile, encoding="utf-8", errors="ignore").read()
    targets = [t.strip() for t in targets_raw.split(",") if t.strip()]

    def bounded(needle, hay):
        return re.search(r"(?<![A-Za-z0-9])" + re.escape(needle) + r"(?![A-Za-z0-9])",
                         hay, re.I) is not None

    # POSITIVE CONTROL, and it is the load-bearing half. If NOT ONE of the declared targets appears in
    # the body, then either the matcher is broken or --targets describes a different ask than the one
    # being sent. Both are failures, and a check that cannot tell "found nothing" from "looked at
    # nothing" is not a check (the pre-push PII sweep learned this the expensive way). Refuse.
    def declared_in_body(t):
        """A target counts as named if the whole string appears, or a distinctive token of it does.

        Real asks say "Acme" where --targets says "Acme Corp"; requiring the full string would block a
        perfectly correct send, and a gate that blocks correct sends gets --force'd around, which
        disables every other check in this block.
        """
        if bounded(t, body):
            return True
        return any(bounded(tok, body) for tok in re.split(r"[^A-Za-z0-9]+", t) if len(tok) >= 4)

    if targets and not any(declared_in_body(t) for t in targets):
        print("⛔ BLOCKED: none of the --targets companies appear in the body.", file=err)
        print(f"   --targets: {', '.join(targets)}", file=err)
        print("   Either the body asks about different companies, or this check is broken. Both are", file=err)
        print("   blockers: --targets must name the companies the ask actually names.", file=err)
        return 1

    # MATCH AGAINST A KNOWN VOCABULARY, NOT AGAINST EXTRACTED PHRASES.
    #
    # The first version of this check extracted capitalized phrases from the body and asked check_dup
    # to judge each one. That is wrong, and the test caught it: check_dup matches BOSS NAMES as well as
    # companies, so "Hi Sam" and "Hope" both came back 🔴 and blocked a clean send. A gate with false
    # positives on ordinary prose gets --force'd around within a day, which disables every other gate
    # in this block too. So the direction is inverted: read the companies the pipeline ALREADY KNOWS
    # are blocked or in-process, and look for THOSE in the body. Only a real company name can fire it.
    # $HERE is `dirname "$0"`, which is RELATIVE when the script is invoked as `bash scripts/mail-draft.sh`.
    # A naive rsplit on it yielded "scripts", the stores never opened, and the vocabulary came back
    # empty — caught immediately by the positive control below, which is the whole reason it exists.
    import os
    # ⛔ THE VOCABULARY BELONGS TO THE INSTALL THIS SCRIPT LIVES IN, never to the session's folder (kit #156, the same rule as the signing fix 9c7a273).
    # This used to read CLAUDE_PROJECT_DIR first. A Claude session rooted anywhere else (an added directory, a parent workspace) has that variable
    # pointing at a folder with no documents/, so the stores "could not be read", the positive control below fired, and 14 Builds could not send;
    # and another folder's blocked list could have scoped this install's send. `here` is this script's own directory.
    repo = os.path.abspath(here)   # slice J: the first argument is now the DATA ROOT (it was this script's folder)
    known = set()
    stores_read = 0
    # kit#159: errors="ignore" used to silently drop undecodable bytes, so a corrupted store still
    # "read" -- stores_read still counted it, and the positive control below never fired. Strict
    # decode; a bad encoding is treated the same as OSError, i.e. this store did not read.
    def _read_text_strict(path):
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8")
    try:
        for line in _read_text_strict(repo + "/documents/blocked-employers-list.md").splitlines():
            if not line.lstrip().startswith(("-", "*")):
                continue
            b = re.findall(r"\*\*([^*]+)\*\*", line)
            if b:
                known.update(x.strip() for x in b)
            else:                                   # plain "- SomeCo, Otherco, Thirdco"
                known.update(x.strip() for x in re.split(r"[,;]", line.lstrip("-* ").strip()))
        stores_read += 1
    except (OSError, UnicodeDecodeError):
        pass
    try:
        import csv, io
        with io.StringIO(_read_text_strict(repo + "/job_search_tracker.csv")) as fh:
            for row in csv.DictReader(fh):
                if (row.get("company") or "").strip():
                    known.add(row["company"].strip())
        stores_read += 1
    except (OSError, UnicodeDecodeError):
        pass

    # Trim to names that can be matched safely. Sub-4-character names collide with English constantly.
    known = {k for k in known if 4 <= len(k) <= 60 and not k.startswith(("http", "["))}

    # POSITIVE CONTROL #2, same reasoning as the one above: a vocabulary that never loaded would make
    # this check pass every body silently, which looks identical to "nothing to report".
    #
    # The test is READABILITY, not size. A count threshold was the first attempt and it was wrong in a
    # way that only showed up in the partner kit: a brand-new user legitimately has an empty blocked
    # list and an empty tracker, and "fewer than N known companies" would have blocked every warm send
    # they ever tried. Zero known companies is a real answer; zero readable STORES is a broken check.
    if stores_read == 0:
        print("⛔ BLOCKED: neither known-company store could be read, so the body/targets", file=err)
        print(f"   cross-check cannot have run (looked under {repo}).", file=err)
        print("   Expected documents/blocked-employers-list.md and/or job_search_tracker.csv.", file=err)
        return 1

    def mentioned(name):
        """Word-bounded hit, with a casing rule that keeps a common noun from matching a brand.

        A company written in prose is capitalized, UNLESS the brand itself is styled lowercase, in
        which case a lowercase hit is the correct one. Without the casing rule, a one-word company name
        that is also an ordinary English word fires on every sentence that happens to use the word.
        """
        inherently_lower = name == name.lower()
        for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", body, re.I):
            if inherently_lower or m.group(0)[0].isupper():
                return True
        return False

    checked, bad = 0, []
    for k in sorted(known):
        if any(bounded(t, k) or bounded(k, t) for t in targets):
            continue                                    # declared, and already dedup'd above
        checked += 1
        if mentioned(k):
            bad.append(k)

    if bad:
        print("⛔ BLOCKED: the body names companies that are BLOCKED or ALREADY CONTACTED and are", file=err)
        print(f"   not in --targets: {', '.join(bad)}", file=err)
        print("   You would be asking for an intro to a company already in your process. Either drop", file=err)
        print("   it from the body, or add it to --targets and re-run so it is dedup'd on the record.", file=err)
        return 1
    print(f"✅ body/targets cross-check: {checked} undeclared name(s) dedup'd, 0 blocked", file=out)
    return 0



def phrasing_in_body(body, phrasing):
    """The cold-boss two-stage praise gate: the Stage-2 phrasing must appear VERBATIM in the body. Each non-blank line of a
    multi-line phrasing is its own fixed string and any one found passes, as `grep -qF` did. Blank lines are STRIPPED: grep -F
    treats an empty pattern as matching every line, so a stray blank line in --praise-phrasing made the check pass vacuously
    (2b, BUG-202 item 2 review). A phrasing with no non-blank line never matches."""
    lines = [p for p in phrasing.split("\n") if p.strip()]
    return bool(lines) and any(p in body for p in lines)


MTYPE_FOR_RUNG = {"thank-you": "thankyou", "reply": "reply", "follow-up": "followup"}


def mtype_for_rung(rung):
    """The --type mail-draft.sh hands check_outreach for a rung."""
    return MTYPE_FOR_RUNG.get(rung, "outreach")


# check_outreach failures that only mean "the note is not assembled yet" (first-contact SHAPE). Anything not listed here is
# a voice, honesty or format failure and stays a hard failure even on a partial draft. An unknown message defaults to hard.
SHAPE_PREFIXES = ("ingredient ", "O-A-K FAIL", "\u2191 if this is an in-thread", "signature:")


def check_outreach_text(scripts_dir, bodyfile, rung, mtype):
    """Run check_outreach.py on a body (read-only). Returns (rc, [failure lines without the marker], full output)."""
    p = subprocess.run([sys.executable, os.path.join(scripts_dir, "check_outreach.py"), bodyfile,
                        "--rung", rung, "--type", mtype], capture_output=True, text=True)
    text = (p.stdout or "") + (p.stderr or "")
    fails = [l.split("\u274c", 1)[1].strip() for l in text.splitlines() if "\u274c" in l]
    return p.returncode, fails, text


def split_shape(fails):
    """(shape, hard): shape failures only mean the note is not assembled yet."""
    # "missing <owner site> sign-off" names the install's own site, so it is matched by shape, not by a literal.
    shape = [f for f in fails if f.startswith(SHAPE_PREFIXES) or (f.startswith("missing ") and f.endswith(" sign-off"))]
    return shape, [f for f in fails if f not in shape]


def main(argv):
    if len(argv) == 5 and argv[1] == "targets":
        return targets_cross_check(argv[2], argv[3], argv[4])
    if len(argv) == 4 and argv[1] == "phrasing":
        with open(argv[2], encoding="utf-8", errors="ignore") as fh:
            return 0 if phrasing_in_body(fh.read(), argv[3]) else 1
    print("usage: body_gates.py targets <data-root> <body-file> <targets-csv> | phrasing <body-file> <phrasing>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
