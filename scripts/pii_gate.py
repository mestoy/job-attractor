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
import subprocess
import sys
import datetime

REPO = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def _owner_literal_hit(text, owner):
    """True if `text` (an ALWAYS/_PHONE match) IS, EXACTLY, the owner's own configured email or
    phone — as opposed to some OTHER person's email/phone that merely SHARES a substring with it.

    ⚠️ EXACT MATCH ONLY, ON PURPOSE — found by security review before ship. An earlier version used
    substring containment (`val in text or text in val`), which downgraded a THIRD PARTY's PII to a
    WARN whenever it happened to contain the owner's literal as a substring:
    `owner['email'] = 'j@example.com'` made a completely different person's `myj@example.com` match too, since
    `'j@example.com' in 'myj@example.com'` is True. That falsified this module's own stated invariant that
    third-party PII can NEVER be downgraded. `text` here is always the REGEX'S OWN exact matched
    span for a shape-anchored pattern (an email or a NANP phone), never a truncated or padded
    window around it, so an exact string comparison is the correct check, not an approximation of
    one — containment was never buying anything real, only creating a false-negative hole."""
    for kind, val in (owner or {}).items():
        if kind == "name" or not val:
            continue
        if text == val:
            return True
    return False


def scan_items(items, full, tokens, companies, owner=None, downgrade_owner=False):
    """The core matcher, over an explicit `[(rel, body), ...]` list rather than a directory walk —
    shared by the whole-tree `--scan` path (via `scan()` below) and the diff-based `--push-guard`
    path, so the two can never drift apart into two gates with two different ideas of what PII is.

    `owner` (P1-1) is the resolved owner-identity dict from _resolve_owner(); its email/phone/site
    are matched as direct literals. `downgrade_owner` (kit#61): when True — meaning the push
    destination has been CONFIRMED private — a hit that is the owner's OWN name/email/phone/site is
    reported as a WARN instead of a BLOCK. It is False by default so every existing `--scan` caller
    (the public repo, the deployed kit) keeps blocking on identity exactly as it always has; only
    `--push-guard` on a confirmed-private fork ever passes True. Third-party hits are NEVER
    downgraded by this flag — that branch does not exist here, on purpose, so there is no code path
    that could accidentally let a stranger's name through on a private destination.
    """
    owner = owner or {}
    owner_name = str(owner.get("name") or "")
    blocks, warns = [], []
    lower_full = {f.lower(): f for f in full}
    for rel, body in items:
        for m in BIGRAM.finditer(body):
            cand = f"{m.group(1)} {m.group(2)}"
            if cand.lower() in lower_full:
                if downgrade_owner and owner_name and cand.lower() == owner_name.lower():
                    warns.append((rel, cand, "owner's own name (private fork; would BLOCK if public)"))
                else:
                    blocks.append((rel, cand, "contact full name"))
        for pat, why in ALWAYS:
            mm = pat.search(body)
            if mm:
                hit = mm.group(0)[:60]
                if downgrade_owner and why == "email address" and _owner_literal_hit(hit, owner):
                    warns.append((rel, hit, "owner's own email (private fork; would BLOCK if public)"))
                else:
                    blocks.append((rel, hit, why))
        # P1-1 generic shapes: a real phone or street address is PII regardless of vocabulary.
        for m in _PHONE.finditer(body):
            if not _phone_is_placeholder(m.groups()):
                hit = m.group(0)[:60]
                if downgrade_owner and _owner_literal_hit(hit, owner):
                    warns.append((rel, hit, "owner's own phone (private fork; would BLOCK if public)"))
                else:
                    blocks.append((rel, hit, "phone number"))
        for m in _STREET.finditer(body):
            if not _STREET_PLACEHOLDER.match(m.group(0)):
                blocks.append((rel, m.group(0)[:60], "street address"))
        # P1-1 owner identity: the owner's OWN email/phone/site, direct literals (never the bigram).
        for kind, val in owner.items():
            if kind == "name":
                continue  # the name is a First-Last bigram; `full` already carries it
            if val and val in body:
                if downgrade_owner:
                    warns.append((rel, val[:60], f"owner's own {kind} (private fork; would BLOCK if public)"))
                else:
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
    return blocks, warns


def scan(root, full, tokens, companies, owner=None):
    """Returns (blocks, warns, nfiles). `nfiles` is what CONTROL 4 measures, and it is counted
    HERE rather than by a second walk, because the number that matters is what this scan actually
    read, not what a later walk could have read.

    Thin wrapper over `scan_items()` — see that function for the actual matching logic and for
    `downgrade_owner`, which this whole-tree path never sets: every `--scan` caller (the public
    repo, the deployed kit) must keep blocking on identity exactly as it always has."""
    items = []
    nfiles = 0
    for path, body in iter_files(root):
        nfiles += 1
        items.append((os.path.relpath(path, root), body))
    blocks, warns = scan_items(items, full, tokens, companies, owner=owner)
    return blocks, warns, nfiles


# ── PUSH GUARD (kit#61) ─────────────────────────────────────────────────────────────────────────
# `--scan <dir>` above answers "is anything in this tree PII" — right for the two paths that
# publish a WHOLE assembled tree from scratch each time (the deployed kit, the public stage). It is
# the wrong question for a partner's own backup push to their own fork, which re-adds the SAME
# already-published tree every run: the operator's own résumé (their own name, expected content)
# and the mirrored memory store sat in that tree forever, so the whole-tree scan blocked EVERY
# push, permanently, regardless of what the push actually added (kit#61's own repro: three commits
# of pure kit plumbing, zero personal content in the diff, withheld anyway).
#
# `--push-guard` answers the right question instead: "does THIS diff add a third party's PII", and
# treats the operator's OWN identity as expected content once the destination is CONFIRMED private.
# Two things make that safe:
#   1. It scans committed content ONLY (`git show HEAD:<path>` for files named in a `git diff
#      --name-status`), so an untracked or gitignored file — which can never be pushed — can never
#      be scanned or block a push either. `scripts/kit_config.py` (the operator's own identity
#      file, gitignored by design) is simply never in this list.
#   2. The owner-identity downgrade requires an EXPLICIT, VERIFIED "isPrivate": true from `gh repo
#      view`. Anything else — `gh` missing, not authenticated, offline, an ambiguous remote URL, a
#      JSON parse failure, or a repo that says `isPrivate: false` — is treated as PUBLIC. Guessing
#      wrong toward "public" only means an extra WARN-turned-BLOCK on the operator's own name; guessing
#      wrong toward "private" would mean a real leak sailing through on a repo that turned out to be
#      public. The cheap wrong guess is the only one this makes.
# Third-party PII is NEVER downgraded by any of this — `scan_items(..., downgrade_owner=...)` only
# ever softens a hit that is the OWNER's own name/email/phone/site; every other hit blocks exactly
# as it does in `--scan`, private fork or not.

_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's own empty-tree constant


def _git(repo, *args, timeout=30):
    try:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                               timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _diff_files(repo, base):
    """([(rel, body)], [unreadable_rel, ...]) for every ADDED/MODIFIED/RENAMED file between `base`
    and HEAD, with content read from the COMMITTED blob at HEAD via `git show` — never the working
    tree, so an uncommitted local edit can never widen or narrow what a push guard sees; what is
    being PUSHED is what HEAD says, full stop. Deleted files are skipped (nothing to scan; nothing
    is pushed that adds them). Returns (None, None) on any git failure — the caller must treat that
    as GATE BROKEN, never as 'nothing changed', or an unreadable diff would report clean."""
    p = _git(repo, "diff", "--name-status", f"{base}..HEAD")
    if p is None or p.returncode != 0:
        return None, None
    rels = []
    for line in p.stdout.splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        status, rel = parts[0], parts[-1]
        if status.startswith("D"):
            continue
        rels.append(rel)
    items, unreadable = [], []
    for rel in rels:
        sp = _git(repo, "show", f"HEAD:{rel}")
        if sp is None or sp.returncode != 0:
            unreadable.append(rel)
            continue
        items.append((rel, sp.stdout))
    return items, unreadable


def _parse_owner_repo(url):
    """'owner/repo' from a github.com remote URL (SSH or HTTPS), or None if it isn't one. A
    non-GitHub or unparsable remote is treated as 'cannot confirm private' by the caller, which
    is the fail-safe (public) direction."""
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _repo_is_private(repo, remote):
    """True ONLY on a CONFIRMED-private destination. Every failure mode — no such remote, a
    non-GitHub URL, `gh` absent or unauthenticated, a network error, a malformed JSON reply, or an
    explicit `isPrivate: false` — returns False. See the module note above for why 'unknown'
    resolves to the strict (public) side rather than the lenient one.

    ⚠️ CHECKS THE PUSH URL, NOT JUST THE FETCH URL (security review, before ship). A remote can have
    a separate push URL (`git remote set-url --push <remote> <other>`) that differs from its fetch
    URL. `git push` follows the PUSH url; checking only the fetch URL could confirm-private a repo
    that isn't actually where the push is headed, and downgrade the owner's own identity toward a
    destination that was never verified. `--push` returns the fetch URL too when no push URL is
    configured (the common case), so this is a strict widening, never a behavior change for a
    single-URL remote.
    """
    g = _git(repo, "remote", "get-url", "--push", remote or "origin")
    if g is None or g.returncode != 0:
        return False
    owner_repo = _parse_owner_repo(g.stdout.strip())
    if not owner_repo:
        return False
    try:
        p = subprocess.run(["gh", "repo", "view", owner_repo, "--json", "isPrivate"],
                            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    if p.returncode != 0:
        return False
    try:
        data = json.loads(p.stdout)
    except (ValueError, json.JSONDecodeError):
        return False
    return data.get("isPrivate") is True


def _self_test_matcher():
    """CONTROL-3, adapted for a diff scan (kit#61). The whole-tree gate's canary proves the matcher
    fires by finding a literal string planted in ITS OWN source, which only works because a
    self-scan always includes this file. A push diff usually does NOT include pii_gate.py, so that
    trick has nothing to check. Prove the REGEX ENGINE ITSELF fires instead, against a synthetic
    fixture the real vocabulary can never suppress (it names no real person and matches no
    TOKEN/COMPANY exception): if this returns False, the matcher is not running, and 'no findings'
    would mean nothing.

    ⚠️ ASSEMBLED AT RUNTIME, NEVER WRITTEN AS ONE CONTIGUOUS LITERAL. A first version spelled the
    fixture address out directly in this docstring's neighborhood as one string, and a WHOLE-TREE
    `--scan` of a directory containing this very file then matched that literal against its own
    email regex — the self-test fixture became a permanent, self-inflicted BLOCK on
    `scripts/pii_gate.py` itself, changing `--scan`'s output on every tree that includes this file.
    Splitting the local-part and domain so neither half is a real address on its own, and joining
    them only inside this function's local variable, keeps the fixture invisible to a scan of the
    SOURCE while still producing a real, matchable string when this function actually RUNS it
    through the matcher.
    """
    local, domain = "piigate" + "-selftest", "zzyzx-canary" + "-fixture.zz"
    fixture = f"contact: {local}@{domain}"
    blocks, _ = scan_items([("__pii_gate_selftest__", fixture)], set(), set(), set())
    return any(why == "email address" for _, _, why in blocks)


def _log_override(repo, blocks):
    """A `--override` is an explicit judgment call, never a silent bypass — logged, append-only,
    with what was overridden, so the record survives even though the push itself does not carry it."""
    path = os.path.join(repo, "documents", "state", "pii-gate-overrides.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        row = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "findings": [{"file": rel, "hit": hit, "why": why} for rel, hit, why in sorted(set(blocks))],
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return True
    except OSError:
        return False


def push_guard(a):
    """`--push-guard`: scan the DIFF being pushed, not the working tree. See the module note above
    this section for the full design. Exit codes match `--scan`: 0 clean, 2 gate broken, 3 blocked."""
    if not a.repo or not a.base:
        print("🔴 --push-guard requires --repo and --base", file=sys.stderr)
        return 2
    repo = os.path.abspath(os.path.expanduser(a.repo))
    if not os.path.isdir(repo):
        print(f"🔴 not a directory: {repo}", file=sys.stderr)
        return 2
    remote = a.remote or "origin"

    # ⚠️ build_vocabulary() and _resolve_owner() both read the module-level `REPO` (set once, from
    # $CLAUDE_PROJECT_DIR or this file's own location on disk) — correct for `--scan`, which is
    # always invoked in place inside the tree it scans, but `--push-guard` takes an EXPLICIT
    # `--repo` that can legitimately differ from wherever pii_gate.py happens to live or from
    # whatever $CLAUDE_PROJECT_DIR says (a multi-project shell, or this file invoked by absolute
    # path from elsewhere). Scope the vocabulary to `--repo` for the duration of this call, restore
    # after, so `--push-guard` never silently answers "is this PII" using a DIFFERENT repo's
    # contacts and identity than the one it was told to guard.
    global REPO
    _prev_repo = REPO
    REPO = repo
    try:
        full, tokens, companies, sources = build_vocabulary()
        owner = _resolve_owner()
    finally:
        REPO = _prev_repo
    missing = [s for s in ("connections", "tracker", "blocked") if not sources.get(s)]
    if missing:
        print(f"🔴 GATE BROKEN: no rows loaded from {', '.join(missing)}. "
              f"The vocabulary cannot have been built. Refusing.", file=sys.stderr)
        return 2
    if len(full) < 100:
        print(f"🔴 GATE BROKEN: only {len(full)} full names loaded, expected hundreds. Refusing.",
              file=sys.stderr)
        return 2

    if not _self_test_matcher():
        print("🔴 GATE BROKEN: the matcher self-test did not fire on its own fixture. The scanner "
              "is not reading what it thinks it is. Refusing.", file=sys.stderr)
        return 2

    items, unreadable = _diff_files(repo, a.base)
    if items is None:
        print(f"🔴 GATE BROKEN: could not compute the diff {a.base}..HEAD in {repo}. Refusing.",
              file=sys.stderr)
        return 2
    # ── CONTROL-4, adapted: an unreadable PUSHED file is GATE BROKEN, never silently skipped. A
    # small/empty diff is normal here (unlike the whole-tree scan, where it signals nfiles<50 read
    # nothing) — a no-op push is a legitimate, frequent, clean result, so there is no floor on
    # len(items). What must never happen is treating "couldn't read it" as "nothing to see".
    if unreadable:
        shown = ", ".join(unreadable[:5]) + ("…" if len(unreadable) > 5 else "")
        print(f"🔴 GATE BROKEN: could not read {len(unreadable)} file(s) being pushed ({shown}). "
              f"A file this gate cannot read is a file it cannot clear. Refusing.", file=sys.stderr)
        return 2

    private = _repo_is_private(repo, remote)
    blocks, warns = scan_items(items, full, tokens, companies, owner=owner,
                                downgrade_owner=private)

    if not a.quiet:
        dest = "CONFIRMED PRIVATE" if private else "public or UNCONFIRMED (treated as public)"
        print(f"pii_gate --push-guard: {len(items)} file(s) in {a.base}..HEAD, destination {dest}")
    for rel, hit, why in sorted(set(warns))[:40]:
        print(f"  🟡 WARN  {rel}: {hit}  ({why})")
    if len(set(warns)) > 40:
        print(f"  🟡 … and {len(set(warns)) - 40} more warnings not shown")
    for rel, hit, why in sorted(set(blocks)):
        print(f"  🔴 BLOCK {rel}: {hit}  ({why})", file=sys.stderr)

    if blocks:
        if a.override:
            logged = _log_override(repo, blocks)
            tag = "" if logged else " (⚠️ could not write the override log — proceeding anyway)"
            print(f"\n⚠️  {len(set(blocks))} blocking finding(s) OVERRIDDEN by --override{tag}.",
                  file=sys.stderr)
            return 0
        print(f"\n🔴 {len(set(blocks))} blocking finding(s) in this push. NOT safe to push.",
              file=sys.stderr)
        return 3
    print(f"✅ pii_gate --push-guard clean ({len(set(warns))} warning(s), 0 blocking)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--push-guard", action="store_true",
                     help="scan the diff being pushed (base..HEAD), not the working tree")
    ap.add_argument("--repo", help="--push-guard: the repo to diff and push from")
    ap.add_argument("--base", help="--push-guard: diff base, e.g. origin/main "
                                    f"(use {_EMPTY_TREE} for 'everything in HEAD is new')")
    ap.add_argument("--remote", default="origin", help="--push-guard: remote to check privacy on")
    ap.add_argument("--override", action="store_true",
                     help="--push-guard: proceed past BLOCKs anyway; logged, never silent")
    a = ap.parse_args()

    if a.push_guard:
        return push_guard(a)

    if not a.scan:
        print("🔴 --scan is required unless --push-guard is given", file=sys.stderr)
        return 2
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
