#!/usr/bin/env python3
"""pii_gate.py — the single PII gate both push paths call, with a vocabulary DERIVED from the
live stores instead of a hand-maintained list.

WHY THIS EXISTS (2026-07-26). `publish-public.sh` carried an 18-term denylist. On the day it was
audited, three real contacts were live in the PUBLIC repo (`scripts/sync_contacted.py` docstrings)
and the gate passed them clean, because a denylist only ever knows the leaks it has already been
taught. The near miss proves the shape of the failure: main said one spelling of a contact's name, the
public copy carried a one-letter variant, and the denylist listed only the first. One name was
scrubbed, its variant walked through. (The real names are genericized here so this file itself ships
clean to the kit.)

The second half of the problem was structural. `backup.sh` pushes to the kit repo with NO code gate
at all, protected only by a prose step in /sync-kit that had already passed clean while two real
leaks sat in the files it was meant to read. That path is UPSTREAM of the public one, so this module
is wired into both and lives in exactly one place. Two copies of one rule drift, and the copy that
drifts is the one nobody re-reads (see mail-draft.sh's PYGATE comment for the last time that bit).

TWO TIERS, because the measurement said so. Sweeping 268 tracked files against the live stores:
  * full "First Last" names → 22 hits, essentially all true positives.       → BLOCK
  * single name tokens      → 84 hits, mostly ordinary words that happen to  → WARN
    be surnames (dodge, martin, white, hamilton, little, speed, sharp, paris)
A single-tier gate would have to choose between missing the first class and crying wolf on the
second. Crying wolf is not the safer failure: a gate that blocks correct publishes gets bypassed,
and then it protects nothing.

⚠️ THE EXCEPTION LIST IS THE DANGEROUS PART, and it is deliberately weak. While building the sweep
that found this leak, `eric`, `shaw` and `shawn` were added to an exception list to quiet the token
tier, and that suppressed two of the three REAL hits. So: exceptions apply to the WARN tier only and
can never suppress a BLOCK, and every entry carries a written reason.

Usage:
    scripts/pii_gate.py --scan <dir>          # scan a tree, exit 0 clean / 3 on a block
    scripts/pii_gate.py --scan <dir> --quiet  # findings only

Exit: 0 clean · 2 the gate itself is broken (a control failed) · 3 PII found.
Stdlib only.
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Canary. Planted in this file's own source and asserted found on every scan of a tree containing
# it, so "the matcher works" is proven per-run rather than assumed. See control 3 below.
CANARY = "PIIGATE-CANARY-Zzyzx-Quibblesworth"

# WARN-tier exceptions ONLY. Never consulted for a full-name BLOCK. Every entry needs a reason.
TOKEN_EXCEPTIONS = {
    "lacivita": "Andrew LaCivita, public methodology author, cited on purpose throughout the kit",
    "andrew": "same, plus an extremely common given name",
    "andy": "same (his shorthand in the method docs)",
    "dodge": "ordinary verb, and a surname in the export",
    "martin": "ordinary given name that is also a surname in the export",
    "white": "colour word",
    "hamilton": "place name",
    "little": "ordinary adjective",
    "speed": "ordinary noun",
    "sharp": "ordinary adjective",
    "paris": "place name",
    "robert": "extremely common given name",
    "hays": "appears only as a ranking-source token",
    "lang": "appears as an abbreviation for language",
    "york": "place name",
    "power": "ordinary noun",
    "close": "ordinary verb",
    "archive": "ordinary noun",
    "render": "ordinary verb, and a hosting provider",
    "array": "programming term",
    "fragment": "programming term",
    "will": "modal verb",
    "lane": "ordinary noun",
    "strong": "ordinary adjective",
    "mark": "ordinary verb",
    "deep": "ordinary adjective",
    "small": "ordinary adjective",
    "light": "ordinary noun",
    "wall": "ordinary noun",
    "bank": "ordinary noun, and a customer segment word",
    "smith": "extremely common placeholder surname (John Smith fixtures)",
    "john": "placeholder given name (John Smith fixtures)",
    "jane": "placeholder given name (Jane Doe fixtures)",
    "dana": "placeholder given name used in kit test fixtures",
}

# ── COMPANY-TIER EXCEPTIONS (BUG-086, the overcount half) ────────────────────────────────────
# 🔴 THE OTHER DIRECTION OF THE SAME BUG. The company tier matched ordinary English at a word
# boundary, so a run printed `✅ pii_gate clean (134 warning(s), 0 blocking)`. **134 warnings nobody
# can read is 134 warnings nobody reads**, and a report that is skimmed past is a report that stops
# guarding. Measured on partner-starter/: `Check` fired 15 times, `Find` 8, `Close` 7.
#
# ⚖️ TWO CLASSES, and both are structurally unable to indicate a leak at the single-token level:
#   1. A company whose name is an ordinary English word. `Check`, `Find`, `Close`, `Mode`,
#      `Column`, `Section`, `Front`, `Balance`, `Merge`, `Sequence`, `Cadence`, `Resolve`,
#      `Writer`. The kit's own code uses these as words, constantly.
#   2. Infrastructure vendors the kit MUST name by function to work at all. It calls the
#      Greenhouse, Ashby, Lever and Rippling APIs by name; naming them is the feature.
# Verified by reading every occurrence: they sit in test fixtures, ATS endpoint lists and
# docstrings, never in a target list.
#
# ⛔ THIS IS A MEASURED LIST, NOT A GUESSED ONE, and it stays that way. Do not add a name because
# it "looks generic". Add it because you read its occurrences and none of them was a leak.
# ⛔ SCOPED TO THE COMPANY TIER ONLY. The full-name tier still BLOCKS on every one of these
# strings if it appears as a real contact's name, which is the tier that protects a person.
COMPANY_EXCEPTIONS = {
    # 1. ordinary English words that happen to be company names
    "check", "find", "close", "mode", "column", "section", "front", "balance", "merge",
    "sequence", "cadence", "resolve", "writer", "archive", "render", "array", "numeric",
    "precisely", "astra", "scale", "speed", "power", "column", "ramp",
    # 2. ATS and infrastructure vendors the kit names by function
    "greenhouse", "ashby", "lever", "rippling", "workday", "icims", "dayforce",
}

# Always wrong in a file that ships, regardless of vocabulary.
ALWAYS = [
    (re.compile(r"/Users/[A-Za-z0-9._-]+"), "absolute home path (leaks the account name)"),
    # ⚠️ The middle-initial placeholders (`jane-a-doe`) were added 2026-08-05 for a REAL reason, not
    # for convenience. BUG-020 was a join that broke on a middle initial in a slug, and the test that
    # pins it has to feed the function a slug SHAPED like that. Every sanctioned placeholder was a
    # two-part name, so the only fixture that could exercise the fix was one the gate blocked, and
    # the tempting move is to smuggle the string past the gate by concatenating it. That would leave
    # a technique in the repo for defeating the gate on purpose. Widening the placeholder instead
    # keeps the gate literal and keeps every real slug blocked.
    (re.compile(r"linkedin\.com/in/"
                r"(?!example|slug|username|your|janedoe|johnsmith|jane-doe|john-smith|firstlast"
                r"|jane-[a-z]-doe|john-[a-z]-smith)"
                r"[A-Za-z0-9-]{3,}"),
     "LinkedIn profile slug"),
    (re.compile(r"(?!(?:first|firstname|last|lastname|you|your|name|user|someone|contact|boss|"
                r"jane|john|jo|test|noreply|dana|sam)@)"
                r"[A-Za-z0-9._%+-]{2,}@(?!example\.|company\.|yourdomain|acme\.|somewhere\.|"
                r"x\.com|test\.|invalid\b)"
                r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email address"),
]

# Placeholder-shaped values are the documented way to write an example, so exempting them is not a
# hole, it is the difference between a gate people keep and a gate people bypass. Learned the hard
# way on the first run: `firstname@company.com` and `linkedin.com/in/example` both blocked.

# ── generic PII shapes (P1-1) ──────────────────────────────────────────────────────────────────
# A phone number or a street address is PII whoever it belongs to, so these block on SHAPE, not on
# a vocabulary. They also close the hole under the owner block: an email, a phone or a bare domain
# can NEVER match the First-Last bigram, so feeding the owner's OWN email/phone/site into `full`
# (the bigram tier) left three of the four owner fields DEAD. The generic shapes catch the owner's
# details regardless of whether their config is set, and _resolve_owner() adds a direct literal tier
# for a partner who HAS configured JOBKIT_OWNER_*.
# US NANP shape: optional +1/1 country code, optional parens, area+exchange both [2-9]NN, then 4.
# ⛔ The two internal separators are MANDATORY. A bare ten-digit run (no separators) is genuinely
# ambiguous with a numeric ID — kits carry LinkedIn JOB IDs that are NANP-shaped by coincidence, and
# blocking those wedges the publish (adversarial panel). Requiring a separator, or a +1/1 country
# code prefix, is what tells a phone from an id. Groups stay (area, exchange, line).
_PHONE = re.compile(
    r"(?<![\d/])(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]([2-9]\d{2})[\s.\-](\d{4})(?!\d)")
_STREET = re.compile(
    r"\b\d{1,5}[A-Za-z]?\s+(?:[A-Z][A-Za-z.]+\s+){1,4}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Way|Place|Pl|"
    r"Circle|Cir|Terrace|Ter|Parkway|Pkwy|Highway|Hwy|Square|Sq)\b\.?"
    # High-confidence tail: a comma/newline/unit word, OR (optionally a city word then) STATE ZIP,
    # so a number+street+city+state+zip line with no comma still matches while a suffix word
    # mid-prose ("3 Step Plan to…") does not. Alphanumeric house numbers are covered above.
    r"(?=\s*(?:,|\n|$|#|Apt\b|Suite\b|Ste\b|Unit\b|(?:[A-Z][a-z]+\s+)?[A-Z]{2}\.?\s+\d{5}))")
# Example addresses are documented the same way example emails are, so they are exempt like them.
# Keyed on a CANONICAL placeholder house number (1/0/123) or an unambiguous example street NAME,
# never a real name like Main/First/Elm — those are streets people live on, so exempting by that
# name would wave a genuine address through (adversarial panel). "123 Main St" still clears via the
# number branch; "4567 Main Street" does not.
_STREET_PLACEHOLDER = re.compile(
    r"^(?:123|1|0)\s+\w+|^\d{1,5}[A-Za-z]?\s+(?:example|sample|anytown|your|some|fake)\b",
    re.IGNORECASE)


def _phone_is_placeholder(g):
    """g = (area, exchange, line). The 555 exchange is the reserved fictional range; a single
    repeated digit or a 12345/09876 run is filler. All are how you write an EXAMPLE number."""
    if g[1] == "555":
        return True
    digits = "".join(g)
    if len(set(digits)) <= 1:
        return True
    if digits in ("1234567890", "0123456789", "9876543210"):
        return True
    return False


def _resolve_owner():
    """The owner's OWN contact details from the RESOLVED config (env-backed kit_config), with the
    example placeholders filtered out. Blocked DIRECTLY in scan(), because the bigram tier they
    used to sit in can never match an email, a phone or a bare domain."""
    vals = {}
    src = {"email": "", "phone": "", "site": "", "name": ""}
    try:
        sys.path.insert(0, os.path.join(REPO, "partner-starter", "scripts"))
        import kit_config  # noqa: reads JOBKIT_OWNER_* from the environment
        for k, attr in (("email", "OWNER_EMAIL"), ("phone", "OWNER_PHONE"),
                        ("site", "OWNER_SITE"), ("name", "OWNER_NAME")):
            src[k] = str(getattr(kit_config, attr, "") or "")
    except Exception:
        pass
    bad = re.compile(r"^(your|you@|yoursite|yourdomain|example|jane|john|555-0100|placeholder)",
                     re.IGNORECASE)
    for k, v in src.items():
        v = v.strip()
        if len(v) >= 4 and not bad.match(v):
            vals[k] = v
    return vals

# Paths never shipped, so their contents are not exposure. Kept explicit rather than implicit.
SKIP_NAMES = {"FOR-TERMINAL-REPACKAGE.md"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "documents"}


# ── vocabulary ───────────────────────────────────────────────────────────────────────────────
def _newest_connections():
    """Newest LinkedIn export by FILENAME date, matching the resolver convention in state.py.

    mtime is the wrong key: touching a 2025 file would make it outrank a 2026 one, which is a
    defect this repo already fixed once in parse_network.py.
    """
    paths = glob.glob(os.path.join(REPO, "documents", "linkedin-exports", "Connections-*.csv"))
    def key(p):
        m = re.search(r"(\d{2})-(\d{2})-(\d{4})", os.path.basename(p))
        return (m.group(3), m.group(1), m.group(2)) if m else ("0", "0", "0")
    return sorted(paths, key=key)[-1] if paths else None


def build_vocabulary():
    """Return (full_names, tokens, companies, sources) derived from the live stores."""
    full, tokens, companies = set(), set(), set()
    sources = {}

    path = _newest_connections()
    if path:
        raw = open(path, encoding="utf-8", errors="ignore").read()
        i = raw.find("First Name")
        n = 0
        if i != -1:
            for r in csv.DictReader(raw[i:].splitlines()):
                fn = (r.get("First Name") or "").strip()
                ln = (r.get("Last Name") or "").strip()
                if len(fn) >= 2 and len(ln) >= 2:
                    full.add(f"{fn} {ln}")
                    n += 1
                for v in (fn, ln):
                    if len(v) >= 4:
                        tokens.add(v.lower())
        sources["connections"] = n

    p = os.path.join(REPO, "job_search_tracker.csv")
    if os.path.exists(p):
        n = 0
        with open(p, encoding="utf-8", errors="ignore") as fh:
            for r in csv.DictReader(fh):
                c = (r.get("company") or "").strip()
                if 4 <= len(c) <= 60:
                    companies.add(c); n += 1
        sources["tracker"] = n

    p = os.path.join(REPO, "documents", "blocked-employers-list.md")
    if os.path.exists(p):
        n = 0
        with open(p, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                s = line.lstrip()
                if not s.startswith(("-", "*")):
                    continue
                # STRICT: only the LEADING bold of a list item, and never an all-caps label. A
                # naive "every bolded span" parse yields REMOTE / CULTURE / COMP / TRAVEL /
                # PE-OWNED, because this file bolds prose for emphasis; those terms then match
                # half the tree and the gate becomes noise.
                m = re.match(r"[-*]\s+\*\*([^*]+)\*\*", s)
                if m:
                    name = m.group(1).strip().rstrip(",.;:")
                    if 4 <= len(name) <= 60 and not name.isupper():
                        companies.add(name); n += 1
        sources["blocked"] = n

    # ── ASK THE STORE, DO NOT RE-PARSE THE PROSE (BUG-086, the undercount half) ───────────────
    # 🔴 THE MISS IS STRUCTURAL, NOT A BAD REGEX. The block above takes only the LEADING bold of a
    # bullet, so it harvests NOTHING from the two shapes the list uses most:
    #   - Banks, insurers, and mega-finance (off-segment): **Flagstar**, **Fifth Third**, …
    #   - Dave, DailyPay, Brigit, Kikoff, Tapcheck, Rain (**EWA/CASH ADVANCE**, all six.)
    # and it fuses `**A / B**` into one string that is neither name. A sweep built on that parser
    # reported 14 occurrences where a per-name re-scan found 54 across 8 files, and the gate passed
    # a tree that still leaked.
    # ✅ `documents/employers.jsonl` is keyed PER NAME POSITION and carries aliases, so every part
    # of a slash or comma list resolves on its own. It is the same registry the screening gates
    # read, which means the PII gate and the blocked check can no longer disagree about what a
    # company is. The markdown parse above stays as the fallback for an install with no registry.
    p = os.path.join(REPO, "documents", "employers.jsonl")
    if os.path.exists(p):
        n = 0
        with open(p, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                for name in [r.get("display") or ""] + list(r.get("aliases") or []):
                    name = str(name).strip().rstrip(",.;:")
                    if 4 <= len(name) <= 60 and not name.isupper():
                        companies.add(name)
                        n += 1
        sources["registry"] = n

    try:
        sys.path.insert(0, os.path.join(REPO, "partner-starter", "scripts"))
        import kit_config  # noqa
        # Only the owner NAME belongs in `full` (the First-Last bigram tier). The owner's email,
        # phone and site went here too before P1-1, where the bigram could never match them — they
        # are blocked directly in scan() via _resolve_owner() now, plus the generic shape matchers.
        v = str(getattr(kit_config, "OWNER_NAME", "") or "").strip()
        if len(v) >= 4 and not v.lower().startswith("your"):
            full.add(v)
        sources["kit_config"] = 1
    except Exception:
        pass

    return full, tokens, companies, sources


# ── scanning ─────────────────────────────────────────────────────────────────────────────────
def iter_files(root):
    """Walk the tree. Python's os.walk carries no word-splitting hazard, which is the whole
    reason the sweep lives here rather than in shell: the previous prose sweep passed CLEAN
    because `Update Kit.command` contains a space and an unquoted shell variable split it into
    two nonexistent paths, with 2>/dev/null hiding the error."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_NAMES:
                continue
            p = os.path.join(dirpath, fn)
            try:
                yield p, open(p, encoding="utf-8", errors="ignore").read()
            except (OSError, UnicodeDecodeError):
                continue


BIGRAM = re.compile(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b")
WORD = re.compile(r"\b([A-Za-z][a-z]{3,})\b")


def scan(root, full, tokens, companies, owner=None):
    """Returns (blocks, warns, nfiles). `nfiles` is what CONTROL 4 measures, and it is counted
    HERE rather than by a second walk, because the number that matters is what this scan actually
    read, not what a later walk could have read.

    `owner` (P1-1) is the resolved owner-identity dict from _resolve_owner(); its email/phone/site
    are blocked as direct literals. It is optional so the direct scan() callers in the test suite
    keep working unchanged."""
    owner = owner or {}
    blocks, warns = [], []
    nfiles = 0
    for path, body in iter_files(root):
        nfiles += 1
        rel = os.path.relpath(path, root)
        lower_full = {f.lower(): f for f in full}
        for m in BIGRAM.finditer(body):
            cand = f"{m.group(1)} {m.group(2)}"
            if cand.lower() in lower_full:
                blocks.append((rel, cand, "contact full name"))
        for pat, why in ALWAYS:
            mm = pat.search(body)
            if mm:
                blocks.append((rel, mm.group(0)[:60], why))
        # P1-1 generic shapes: a real phone or street address is PII regardless of vocabulary.
        for m in _PHONE.finditer(body):
            if not _phone_is_placeholder(m.groups()):
                blocks.append((rel, m.group(0)[:60], "phone number"))
        for m in _STREET.finditer(body):
            if not _STREET_PLACEHOLDER.match(m.group(0)):
                blocks.append((rel, m.group(0)[:60], "street address"))
        # P1-1 owner identity: the owner's OWN email/phone/site, direct literals (never the bigram).
        for kind, val in owner.items():
            if kind == "name":
                continue  # the name is a First-Last bigram; `full` already carries it
            if val and val in body:
                blocks.append((rel, val[:60], f"owner identity ({kind})"))
        # COMPANIES WARN, THEY DO NOT BLOCK. Measured on the first real run: this tier flagged
        # Array, Close, Archive, Render, Balance, Numeric, Sequence, Greenhouse and Precisely,
        # because the tracker holds real companies whose names are ordinary English words, and the
        # kit's own code uses those words as words. It behaves like the token tier, not the
        # full-name tier.
        #
        # It is also lower stakes by nature. A company name reveals which employers are being
        # targeted; a person's name exposes someone who never opted in. Blocking a publish over
        # the word "Array" would train the reader to bypass the gate, and a bypassed gate protects
        # nothing at all.
        for c in companies:
            # BUG-086 overcount: a single-token name that is an ordinary word or an ATS vendor
            # cannot tell a leak from prose. Multi-word names are always checked, because
            # "Fifth Third" or "Colony Bank" carry their own specificity.
            if " " not in c and c.lower() in COMPANY_EXCEPTIONS:
                continue
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(c) + r"(?![A-Za-z0-9])", body):
                warns.append((rel, c, "company from tracker/blocked list"))
        for m in WORD.finditer(body):
            w = m.group(1).lower()
            if w in tokens and w not in TOKEN_EXCEPTIONS:
                warns.append((rel, m.group(1), "name token (review, not a block)"))
    return blocks, warns, nfiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", required=True)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(os.path.expanduser(a.scan))
    if not os.path.isdir(root):
        print(f"🔴 not a directory: {root}", file=sys.stderr); return 2

    full, tokens, companies, sources = build_vocabulary()

    # ── CONTROL 1: every vocabulary source must have contributed ──────────────────────────────
    # A moved or renamed store would silently shrink the list, and a shrunken list looks exactly
    # like a clean tree.
    missing = [s for s in ("connections", "tracker", "blocked") if not sources.get(s)]
    if missing:
        print(f"🔴 GATE BROKEN: no rows loaded from {', '.join(missing)}. "
              f"The vocabulary cannot have been built. Refusing.", file=sys.stderr)
        return 2

    # ── CONTROL 2: the vocabulary must clear a floor ──────────────────────────────────────────
    if len(full) < 100:
        print(f"🔴 GATE BROKEN: only {len(full)} full names loaded, expected hundreds. Refusing.",
              file=sys.stderr)
        return 2

    blocks, warns, nfiles = scan(root, full, tokens, companies, owner=_resolve_owner())

    # ── CONTROL 4: THE SCAN MUST PROVE IT READ THE PAYLOAD ────────────────────────────────────
    # 🔴 THE FAILURE THIS CLOSES, AND IT WAS LIVE ON 2026-08-09. The nightly backup ran against a
    # directory macOS would not let it read. Every `cp` failed, `os.walk` yielded NOTHING, and this
    # gate printed `✅ pii_gate clean (0 warning(s), 0 blocking)` against a 917-company vocabulary.
    # Zero warnings there is not a clean tree, it is a tree nobody read, and those two render
    # identically. Controls 1 and 2 both PASSED, because they measure the VOCABULARY; nothing
    # measured the PAYLOAD. `publish-public.sh:36-40` had this control all along (its `kit_config`
    # sentinel) and the backup path had none.
    # ⚖️ A floor, not an exact count, because the payload legitimately changes size. A kit is ~250
    # files; 50 is generous enough never to fire on real work and still catches an empty or
    # near-empty walk, which is the only failure this is for.
    if nfiles < 50:
        print(f"🔴 GATE BROKEN: read only {nfiles} file(s) under {root}. A scan that reads nothing "
              f"reports clean. Check permissions on that path. Refusing.", file=sys.stderr)
        return 2

    # ── CONTROL 3: the canary ─────────────────────────────────────────────────────────────────
    # Prove the matcher actually fires on this run, rather than trusting that zero findings means
    # zero PII. Scanned only when this file is inside the tree (it is, for a repo self-scan).
    self_in_tree = os.path.commonpath([root, os.path.abspath(__file__)]) == root
    if self_in_tree:
        found = any(CANARY in body for _, body in iter_files(root))
        if not found:
            print("🔴 GATE BROKEN: the canary was not found in a tree that contains this file. "
                  "The scanner is not reading what it thinks it is. Refusing.", file=sys.stderr)
            return 2

    if not a.quiet:
        print(f"pii_gate: {len(full)} full names · {len(companies)} companies · "
              f"{len(tokens)} tokens  (sources: {sources})")
    for rel, hit, why in sorted(set(warns))[:40]:
        print(f"  🟡 WARN  {rel}: {hit}  ({why})")
    if len(set(warns)) > 40:
        # NO SILENT CAPS: a truncated report reads as a complete one.
        print(f"  🟡 … and {len(set(warns)) - 40} more warnings not shown")
    for rel, hit, why in sorted(set(blocks)):
        print(f"  🔴 BLOCK {rel}: {hit}  ({why})", file=sys.stderr)

    if blocks:
        print(f"\n🔴 {len(set(blocks))} blocking finding(s). NOT safe to publish.", file=sys.stderr)
        return 3
    print(f"✅ pii_gate clean ({len(set(warns))} warning(s), 0 blocking)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
