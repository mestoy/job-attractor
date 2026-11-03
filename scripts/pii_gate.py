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
import ast
import csv
import glob
import json
import os
import re
import subprocess
import sys
import datetime

REPO = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OWNER_UNRESOLVED = ("🔴 GATE BROKEN: the owner's own email could not be resolved (set JOBKIT_OWNER_EMAIL and "
                    "JOBKIT_OWNER_PHONE, or keep the contact line in CLAUDE.md). A scan that does not know the "
                    "owner's own details reads clean by knowing nothing. Refusing.")

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
    "white": "color word",
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

# ── RETIRED-FACT-TIER FILE EXCEPTIONS (H4 follow-up) ──────────────────────────────────────────
# The retired-fact tier (see _resolve_retired_facts()/scan_items() below) BLOCKS unconditionally,
# including as the push guard `backup.sh` runs before every push — so a false BLOCK here does not
# just mis-report, it stops the operator's next push outright. Measured on merge/v45 with a
# representative RETIRED list: every one of the 7 hits outside the genuine `sweep_segments.sh`
# leak sat in a file that DEFINES or DOCUMENTS the honesty/retired mechanism itself, quoting a
# retired phrase as the worked example the mechanism is explaining, never as a real fact:
#   * kit_config.example.py — the shipped template's own RETIRED=[] worked example line, and
#     kit_config.py.bak-* snapshots of the same template.
#   * check_style.py — two dev comments explaining WHY the honesty gate exempts certain paths,
#     each one quoting a retired figure/phrase as the very thing being explained.
# ⚠️ DO NOT re-quote the actual retired phrases IN THIS COMMENT to illustrate the above — doing so
# once already turned pii_gate.py itself into an 8th false BLOCK on its own source, the same
# failure this section exists to fix. Describe the shape, never the literal.
# ⛔ SCOPED BY PATH ONLY, never by phrase — a real leak of these same facts in any OTHER file must
# still BLOCK. Every entry needs a reason, same rule as TOKEN_EXCEPTIONS above. This is a MEASURED
# list, not a guessed one: add a path because its retired-phrase hits were read and confirmed to be
# about the mechanism, not add it because a file merely mentions "RETIRED" or "honesty".
RETIRED_FACT_FILE_EXCEPTIONS = {
    "scripts/kit_config.example.py": "the shipped RETIRED=[] template's own worked example",
    "scripts/check_style.py": "dev comments documenting why/how the honesty gate exempts paths, "
                               "quoting a retired phrase as the example being explained",
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
    (re.compile(r"/Users" r"/[A-Za-z0-9._-]+"), "absolute home path (leaks the account name)"),
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


# A TEMPLATE value, matched WHOLE (BUG-744, the same rule as BUG-737's check_store_data._PLACEHOLDER): [YOUR NAME], "Your Name", you@example.com,
# yoursite.* / yourdomain.* / example.*, the exact "Jane Doe" / "John Doe", 555-0100, "placeholder". A real owner named John or Jane ("John Smith",
# john@...) is NOT one: the old prefix match dropped him from the identity vocabulary, so the gate never searched for him (a fail-open).
# .invalid is deliberately NOT a template domain: test fixtures use it for fake real owners (BUG-745 review)
_TEMPLATE_VALUE = re.compile(r"^(?:\[[^\]]*\]|<?(?:your(?:\s.*)?|you@\S*|[^@\s<>]+@(?:[\w-]+\.)*(?:example\.(?:com|org|net)|[\w-]+\.(?:example|test))|(?:https?://)?(?:www\.)?(?:yoursite\S*|yourdomain\S*|example(?:\.\S*)?)|(?:jane|john)\s+doe|placeholder)>?|[+(]?(?:1[\W_]*)?5[\W_]*5[\W_]*5[\W_]*0[\W_]*1[\W_]*0[\W_]*0(?:[\W_]*1[\W_]*0[\W_]*0)?)$",
                             re.IGNORECASE)


def _resolve_owner():
    """The owner's OWN contact details from the RESOLVED config (env-backed kit_config), with the
    example placeholders filtered out. Blocked DIRECTLY in scan(), because the bigram tier they
    used to sit in can never match an email, a phone or a bare domain.

    Also carries "first" (kit_config.OWNER_FIRST, itself `OWNER_NAME.split()[0]`) for the BARE
    first-name WARN tier (H4). It is returned in the same dict as email/phone/site/name for a
    single resolution point, but `scan_items()` treats it separately from the others: "name" feeds
    the full-name BIGRAM tier and the other three feed the literal-BLOCK tier, while "first" feeds
    neither — a bare first name is common-word-adjacent in a way a full name or an email is not, so
    it is scoped to its own WARN-only tier below rather than folded into either existing one."""
    vals = {}
    src = {"email": "", "phone": "", "site": "", "name": "", "first": ""}
    try:
        sys.path.insert(0, os.path.join(REPO, "partner-starter", "scripts"))
        import kit_config  # noqa: reads JOBKIT_OWNER_* from the environment
        for k, attr in (("email", "OWNER_EMAIL"), ("phone", "OWNER_PHONE"),
                        ("site", "OWNER_SITE"), ("name", "OWNER_NAME"),
                        ("first", "OWNER_FIRST")):
            src[k] = str(getattr(kit_config, attr, "") or "")
    except Exception:
        pass
    bad = _TEMPLATE_VALUE
    for k, v in src.items():
        v = v.strip()
        # "first" gets its own, shorter floor (2, not 4) — a real first name can be as short as
        # "Sam" or "Al", and the WARN-only tier it feeds is already scoped tightly (word-boundary,
        # skips anything already covered by the full-name BLOCK) so a short token here is cheap.
        floor = 2 if k == "first" else 4
        if len(v) >= floor and not bad.search(v):
            vals[k] = v
    # OWNER_FIRST is the first word of OWNER_NAME, so one derived from a template name ("Jane Doe") is a template value too (BUG-744); on its own
    # "Jane" or "John" is a real first name and stays.
    if bad.search(src["name"].strip()):
        vals.pop("first", None)
    # 2026-09-21: an unset config left this empty, and every owner-literal check read clean by knowing
    # nothing. The install's project card (CLAUDE.md), when it carries a contact line, fills the gaps.
    for k, v in _owner_from_card(os.path.join(REPO, "CLAUDE.md")).items():
        if k not in vals and not bad.search(v):
            vals[k] = v
    return vals


def _owner_from_card(path):
    """{email, phone, site} from the first line of the project card that carries an email address."""
    try:
        with open(path, encoding="utf-8") as fh:
            head = [next(fh, "") for _ in range(40)]
    except OSError:
        return {}
    for line in head:
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", line)
        if not m:
            continue
        out = {"email": m.group(0)}
        ph = re.search(r"(?<!\d)\(?\d{3}\)?[.\-\s]\d{3}[.\-\s]\d{4}(?!\d)", line)
        if ph:
            out["phone"] = ph.group(0)
        rest = line.replace(m.group(0), " ")
        site = re.search(r"(?<![\w.@/-])((?:www\.)?[a-z0-9-]+\.(?:com|dev|net|org|io|co|me|ai|app))(?![\w.])", rest, re.I)
        if site:
            out["site"] = site.group(1)
        return out
    return {}


def _resolve_retired_facts():
    """The owner's own RETIRED literals and RETIRED_PATTERNS regexes, read from the same RESOLVED
    kit_config as _resolve_owner() — never hardcoded here. This module ships to every partner, so
    each installation's own honesty/retired facts have to come from THAT installation's own
    (gitignored, per-install) kit_config.py, exactly the way OWNER_NAME already does. kit_config's
    documented default (kit_config.example.py) ships RETIRED = [] and RETIRED_PATTERNS = [], so an
    install that has not filled them in yet gets an empty, harmless pair back, not an error.

    Returns (literals: list[str], patterns: list[(regex_str, label)])."""
    literals, patterns = [], []
    try:
        sys.path.insert(0, os.path.join(REPO, "partner-starter", "scripts"))
        import kit_config  # noqa
        for v in (getattr(kit_config, "RETIRED", None) or []):
            v = str(v).strip()
            if v:
                literals.append(v)
        for item in (getattr(kit_config, "RETIRED_PATTERNS", None) or []):
            try:
                pat, label = item
            except (TypeError, ValueError):
                continue
            pat = str(pat).strip()
            if pat:
                patterns.append((pat, str(label)))
    except Exception:
        pass
    return literals, patterns

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
        # kit#102: the export's own date is the blind-spot measure — a name connected after this
        # date, or never connected at all, is structurally absent from `full`/`tokens` and cannot
        # be caught by the BIGRAM/WORD tiers. Recorded here (not re-derived at print time) so the
        # scan-summary line always reports the SAME file this vocabulary was actually built from.
        m = re.search(r"(\d{2})-(\d{2})-(\d{4})", os.path.basename(path))
        if m:
            mm, dd, yyyy = m.groups()
            sources["connections_export_date"] = f"{yyyy}-{mm}-{dd}"

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
    #   - Banks, insurers, and mega-finance (off-segment): **<Bank A>**, **<Bank B>**, …
    #   - <A>, <B>, <C>, <D>, <E>, <F> (**EWA/CASH ADVANCE**, all six.)
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


# P0-1 (private #98): the old CONTROL 2 refused any vocabulary under 100 full names. That floor
# was a PROXY for "the export failed to load", and for the kit owner (hundreds of contacts) it
# happened to work. For a partner whose real network is 40-60 people it refused the push outright,
# permanently, and the refusal read the same as an empty install. The kit owner's rulings (2026-09-12):
# a gate fails CLOSED, never silently narrows; a small vocabulary is a BLIND SPOT to announce, not
# a reason to refuse the partner; a check measures the THING, not a proxy. The thing is "did every
# source load rows" — CONTROL 1 measures that, and a zero-name vocabulary is still refused below.
# What is left for this floor is the loud announcement: under it, the count and the export it came
# from are printed to stderr on every run, so a shrunken vocabulary (a partial export picked as
# newest, a mis-parsed CSV) is never mistaken for a clean tree by an owner who expects hundreds.
SMALL_VOCABULARY_FLOOR = 100


def _announce_small_vocabulary(sources, full_count):
    """Print the small-vocabulary blind spot to stderr when `full_count` is under the floor.
    Informational only, never changes the exit code — the scan proceeds with what is known."""
    if full_count >= SMALL_VOCABULARY_FLOOR:
        return
    date = sources.get("connections_export_date") or "unknown date"
    print(f"🟡 SMALL VOCABULARY: only {full_count} full names loaded "
          f"({sources.get('connections', 0)} from the Connections export dated {date}, plus the "
          f"owner). A small network is scanned with what is known, but any name outside these "
          f"{full_count} is NOT checked by the name tier. If you expected hundreds, the export "
          f"is wrong or truncated: fix it before trusting a clean result.", file=sys.stderr)


def _vocabulary_blind_spot_line(sources, full_count):
    """kit#102: `full` (the BLOCK-tier, full-name vocabulary) is built from exactly two sources —
    rows of the newest LinkedIn Connections export, and the kit owner's own name. A cold-outreach
    contact is definitionally absent from both: not yet connected, not the owner. A bare name with
    no adjacent email/phone/street/LinkedIn slug in the same passage is therefore invisible to the
    BLOCK tier, not merely under-flagged — and that population (people not yet connected) is
    exactly who a boss-hunt push is most likely to name.

    The kit owner's ruling (2026-09-12): the gate cannot invent a vocabulary for someone it has never
    seen, so the fix is not a guessing heuristic on unknown capitalized name pairs (that trades
    silent misses for a new false-positive class). It is telling the truth about the blind spot,
    every run, so a clean scan is never mistaken for a guarantee. This line is informational —
    it never blocks and never changes the exit code."""
    date = sources.get("connections_export_date")
    if date:
        try:
            age_days = (datetime.date.today() - datetime.date(*map(int, date.split("-")))).days
            age = f", {age_days} day(s) old"
        except (ValueError, TypeError):
            age = ""
        export_desc = f"the LinkedIn export dated {date}{age}"
    else:
        export_desc = "no LinkedIn export found"
    return (f"⚠️  SCAN BLIND SPOT: full-name matching ({full_count} names) draws only from "
            f"{export_desc} plus the owner's own name. A contact connected since that export, or "
            f"never connected at all, is NOT in this vocabulary — a bare mention of their name with "
            f"no adjacent email/phone/address/LinkedIn slug in the same text will not BLOCK or WARN. "
            f"A clean result covers what was checked, not what a person actually wrote.")


def _company_scope_line(n_companies):
    """What "clean" does NOT cover. Company names are matched only against three lists (the tracker, the blocked list and the employer
    registry), so a firm in none of them is invisible to this gate. The header's "N companies" reads as coverage and the only other caveat
    printed is about people, so a clean result was easy to read as "no company names in this tree". This line goes right under every clean
    result and is NOT silenced by --quiet: the person reading the clean line is exactly who needs it. Informational only; it never changes
    an exit code. The count is the one from this run."""
    return (f"   Scope of this result: company names are matched only against the {n_companies:,} companies in the tracker, the blocked list and "
            f"the employer registry. A company in none of them is not looked for, so this result does not mean there are no company names.")


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
        if kind in ("name", "first") or not val:
            continue
        if text == val:
            return True
    return False


# ── BUG-721: names split by source syntax ────────────────────────────────────────────────────────
# scan_items() reads each file's body as one string, so `"lists Pat "` + `"Fakename as CEO"` (a quote,
# a newline and an indent between the words) is not `pat fakename`. joined_items() ADDS items; it
# never changes scan_items(), the vocabulary, the tiers or the severities.
_JOIN_WINDOW = 40
_JOIN_PREFIX = re.compile(r"(?:rb|br|fr|rf|f|r|b|u)(?=[\"'])", re.I)
_JOIN_ADJ = re.compile(r"[\"'][ \t]+(?:(?:rb|br|fr|rf|f|r|b|u)(?=[\"']))?[\"']", re.I)
_JOIN_COMMENT = re.compile(r"([\"'])[ \t]*#[^\"']*$")
_JOIN_PLUS = re.compile(r"[\"'][ \t]*\+[ \t]*(?:(?:rb|br|fr|rf|f|r|b|u)(?=[\"']))?[\"']", re.I)


def _seam_windows(body):
    """One window per line break where a quote, `+`, `,`, `(` or string prefix was STRIPPED (a break with
    nothing to strip is already spanned by the plain body's BIGRAM). Blank lines make no window."""
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    for i in range(len(lines) - 1):
        raw_l, raw_r = lines[i].rstrip(), lines[i + 1].lstrip()
        if not raw_l or not raw_r:
            continue
        left = raw_l
        cm = _JOIN_COMMENT.search(left)
        if cm:
            left = left[:cm.end(1)]  # a trailing `# comment` after a closing quote
        if left[-1] in "+,(\\":
            left = left[:-1].rstrip()
        for _ in range(3):  # up to a triple quote
            if left and left[-1] in "\"'":
                left = left[:-1]
        right = raw_r
        if right[0] == "+":
            right = right[1:].lstrip()
        pm = _JOIN_PREFIX.match(right)
        if pm:
            right = right[pm.end():]
        for _ in range(3):
            if right and right[0] in "\"'":
                right = right[1:]
        if left == raw_l and right == raw_r:
            continue
        lw, rw = left[-_JOIN_WINDOW:], right[:_JOIN_WINDOW]
        # a cut must not leave half a word (it made the token tier see "abel" in "Isabel")
        if len(left) > _JOIN_WINDOW and not left[-_JOIN_WINDOW - 1].isspace():
            lw = lw.split(None, 1)[1] if len(lw.split(None, 1)) > 1 else ""
        if len(right) > _JOIN_WINDOW and not right[_JOIN_WINDOW].isspace():
            rw = rw.rsplit(None, 1)[0] if len(rw.rsplit(None, 1)) > 1 else ""
        out.append(lw + " " + rw)
    return out


def _py_joined_constants(body):
    """`"a" + "b"` of two string constants, and a string constant written as adjacent literals on one line
    (`"a " "b"`). Implicit concatenation across lines needs no item here: its seam window carries the words."""
    try:
        tree = ast.parse(body)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out = []
    lines = body.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if len(node.value) >= 8 and 0 < node.lineno <= len(lines) and _JOIN_ADJ.search(lines[node.lineno - 1]):
                out.append(node.value)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            l, r = node.left, node.right
            if (isinstance(l, ast.Constant) and isinstance(l.value, str)
                    and isinstance(r, ast.Constant) and isinstance(r.value, str)):
                out.append(l.value + r.value)
    return out


def joined_items(items):
    """The input items unchanged, then per item zero or more `(rel + " (joined)", text)` items."""
    out = list(items)
    for rel, body in items:
        windows = _seam_windows(body)
        if windows:
            out.append((rel + " (joined)", "\x00".join(windows)))
        if rel.endswith(".py") and (_JOIN_PLUS.search(body) or _JOIN_ADJ.search(body)):
            for text in _py_joined_constants(body):
                out.append((rel + " (joined)", text))
    return out


def dedupe_joined(hits):
    """Drop a joined `(rel (joined), hit, why)` when the plain body already reported `(rel, hit, why)`."""
    plain = {h for h in hits if not h[0].endswith(" (joined)")}
    return [h for h in hits
            if not h[0].endswith(" (joined)") or (h[0][:-len(" (joined)")],) + tuple(h[1:]) not in plain]


def scan_items(items, full, tokens, companies, owner=None, downgrade_owner=False, retired=None):
    """The core matcher, over an explicit `[(rel, body), ...]` list rather than a directory walk —
    shared by the whole-tree `--scan` path (via `scan()` below) and the diff-based `--push-guard`
    path, so the two can never drift apart into two gates with two different ideas of what PII is.

    `owner` (P1-1) is the resolved owner-identity dict from _resolve_owner(); its email/phone/site
    are matched as direct literals, and its "first" (bare first name, H4) feeds a separate WARN-only
    tier below. `downgrade_owner` (kit#61): when True — meaning the push destination has been
    CONFIRMED private — a hit that is the owner's OWN name/email/phone/site is reported as a WARN
    instead of a BLOCK. It is False by default so every existing `--scan` caller (the public repo,
    the deployed kit) keeps blocking on identity exactly as it always has; only `--push-guard` on a
    confirmed-private fork ever passes True. Third-party hits are NEVER downgraded by this flag —
    that branch does not exist here, on purpose, so there is no code path that could accidentally
    let a stranger's name through on a private destination.

    `retired` (H4) is the (literals, patterns) pair from _resolve_retired_facts(): the owner's own
    honesty-guardrail/retired facts (a retired figure, an employer name+dates that should no longer
    ship, a retired claim's regex). These BLOCK unconditionally — never downgraded by
    `downgrade_owner` — because a retired fact shipping in a partner-facing file is wrong regardless
    of whether the destination repo is private; privacy softens exposure of the owner's identity, it
    does not make a factual inaccuracy correct.
    """
    owner = owner or {}
    owner_name = str(owner.get("name") or "")
    owner_first = str(owner.get("first") or "")
    retired_literals, retired_patterns = retired or ([], [])
    # Whole-phrase only, never an embedded substring: `(?<![A-Za-z0-9])...(?![A-Za-z0-9])` is the
    # same boundary style the company matcher already uses below. A bare `in` check on a retired
    # dollar figure would also fire inside a larger, unrelated figure that merely contains the
    # same digits (e.g. a retired "$9M" embedded in "$49M" or "$9M0"), which is not the same fact.
    retired_lit_compiled = [(re.compile(r"(?<![A-Za-z0-9])" + re.escape(lit) + r"(?![A-Za-z0-9])",
                                         re.IGNORECASE), lit)
                             for lit in retired_literals]
    retired_pat_compiled = [(re.compile(p, re.IGNORECASE), label) for p, label in retired_patterns]
    blocks, warns = [], []
    lower_full = {f.lower(): f for f in full}
    for rel, body in items:
        bigram_starts = set()
        for m in BIGRAM.finditer(body):
            cand = f"{m.group(1)} {m.group(2)}"
            if cand.lower() in lower_full:
                if downgrade_owner and owner_name and cand.lower() == owner_name.lower():
                    warns.append((rel, cand, "owner's own name (private fork; would BLOCK if public)"))
                else:
                    blocks.append((rel, cand, "contact full name"))
                if owner_name and cand.lower() == owner_name.lower():
                    bigram_starts.add(m.start())
        # kit#103: `finditer()`, not `search()` — `search()` returns only the first match, so five
        # distinct third-party emails in one file reported as one block instead of five. Every
        # other tier in this function (BIGRAM/_PHONE/_STREET/WORD) already iterates every hit;
        # ALWAYS (email + LinkedIn slug) was the one holdout.
        for pat, why in ALWAYS:
            for mm in pat.finditer(body):
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
            if kind in ("name", "first"):
                continue  # "name" is the First-Last bigram above; "first" is its own tier below
            if val and val in body:
                if downgrade_owner:
                    warns.append((rel, val[:60], f"owner's own {kind} (private fork; would BLOCK if public)"))
                else:
                    blocks.append((rel, val[:60], f"owner identity ({kind})"))
        # H4 / Q5 (2026-10-14, BUG-294): bare first name, WARN if confirmed private else BLOCK. Scoped so the gate stays usable: word-boundary,
        # case-sensitive (a name is capitalized; a lowercase collision with an ordinary word is not
        # this), skips a hit already counted by the full-name BLOCK above (same start offset), and
        # respects TOKEN_EXCEPTIONS the same way the WORD/token tier does — an install can silence a
        # first name that collides with its own vocabulary the same way it silences any other token.
        if owner_first:
            for m in re.finditer(r"\b" + re.escape(owner_first) + r"\b", body):
                if m.start() in bigram_starts:
                    continue
                if owner_first.lower() in TOKEN_EXCEPTIONS:
                    continue
                if downgrade_owner:
                    warns.append((rel, m.group(0), "owner's own first name (private fork; would BLOCK if public)"))
                else:
                    blocks.append((rel, m.group(0), "owner's own first name"))
        # H4: the owner's own RETIRED honesty-guardrail facts. BLOCK, never downgraded — see the
        # docstring above. Whole-phrase match (case-insensitive) plus the variant-tolerant
        # RETIRED_PATTERNS regexes — except in a file that DEFINES or DOCUMENTS the mechanism
        # itself (RETIRED_FACT_FILE_EXCEPTIONS), where the same phrase is the worked example, not
        # a real fact. Scoped by path only, so a real leak of the same phrase anywhere else still
        # BLOCKs.
        if rel not in RETIRED_FACT_FILE_EXCEPTIONS:
            for pat, lit in retired_lit_compiled:
                for mm in pat.finditer(body):
                    blocks.append((rel, mm.group(0)[:60],
                                    "owner's own retired/honesty-guardrail fact"))
            for pat, label in retired_pat_compiled:
                for mm in pat.finditer(body):
                    blocks.append((rel, mm.group(0)[:60],
                                    f"owner's own retired/honesty-guardrail fact ({label})"))
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
            # a two-word name such as "Example Federal" carries their own specificity.
            if " " not in c and c.lower() in COMPANY_EXCEPTIONS:
                continue
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(c) + r"(?![A-Za-z0-9])", body):
                warns.append((rel, c, "company from tracker/blocked list"))
        for m in WORD.finditer(body):
            w = m.group(1).lower()
            if w in tokens and w not in TOKEN_EXCEPTIONS:
                warns.append((rel, m.group(1), "name token (review, not a block)"))
    return blocks, warns


def scan(root, full, tokens, companies, owner=None, retired=None):
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
    blocks, warns = scan_items(joined_items(items), full, tokens, companies, owner=owner, retired=retired)
    blocks, warns = dedupe_joined(blocks), dedupe_joined(warns)
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
    """Raw BYTES, never `text=True`. A committed blob named in a diff can be anything — a PDF, an
    image, any binary asset — and `text=True` decodes eagerly as strict UTF-8 inside
    `subprocess.communicate()`, raising UnicodeDecodeError on the first invalid byte (kit#93,
    kit#104). Every caller now decodes what it actually expects, with the error handling that
    call site can justify, instead of getting an unconditional decode it never asked for."""
    try:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _diff_files(repo, base):
    """([(rel, body)], [unreadable_rel, ...], [unscannable_rel, ...]) for every
    ADDED/MODIFIED/RENAMED file between `base` and HEAD, with content read from the COMMITTED blob
    at HEAD via `git show` — never the working tree, so an uncommitted local edit can never widen
    or narrow what a push guard sees; what is being PUSHED is what HEAD says, full stop. Deleted
    files are skipped (nothing to scan; nothing is pushed that adds them). Returns (None, None,
    None) on any git failure — the caller must treat that as GATE BROKEN, never as 'nothing
    changed', or an unreadable diff would report clean.

    `unreadable` is a genuine git failure (nonzero exit) — unchanged from before. `unscannable` is
    NEW (kit#93/#104): content `git show` returned successfully but that is not valid UTF-8 (a
    committed PDF/image/binary asset). The kit owner's ruling (2026-09-12): an unscannable file is a
    file this gate cannot clear, so it BLOCKS the push and is named, the same as `unreadable` —
    it does not silently drop out of `items` and it does not get scanned as best-effort text."""
    p = _git(repo, "diff", "--name-status", f"{base}..HEAD")
    if p is None or p.returncode != 0:
        return None, None, None
    out = p.stdout.decode("utf-8", errors="replace")  # filenames only; never the risky content
    rels = []
    for line in out.splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        status, rel = parts[0], parts[-1]
        if status.startswith("D"):
            continue
        rels.append(rel)
    items, unreadable, unscannable = [], [], []
    for rel in rels:
        sp = _git(repo, "show", f"HEAD:{rel}")
        if sp is None or sp.returncode != 0:
            unreadable.append(rel)
            continue
        try:
            body = sp.stdout.decode("utf-8")
        except UnicodeDecodeError:
            unscannable.append(rel)
            continue
        items.append((rel, body))
    return items, unreadable, unscannable


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
    owner_repo = _parse_owner_repo(g.stdout.decode("utf-8", errors="replace").strip())
    if not owner_repo:
        return False
    try:
        p = subprocess.run(["gh", "repo", "view", owner_repo, "--json", "isPrivate"],
                            capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    if p.returncode != 0:
        return False
    try:
        data = json.loads(p.stdout.decode("utf-8", errors="replace"))
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
        retired = _resolve_retired_facts()
    finally:
        REPO = _prev_repo
    if not owner.get("email"):
        print(OWNER_UNRESOLVED, file=sys.stderr)
        return 2
    missing = [s for s in ("connections", "tracker", "blocked") if not sources.get(s)]
    if missing:
        print(f"🔴 GATE BROKEN: no rows loaded from {', '.join(missing)}. "
              f"The vocabulary cannot have been built. Refusing.", file=sys.stderr)
        return 2
    if len(full) == 0:
        print("🔴 GATE BROKEN: zero full names loaded. The vocabulary cannot have been built. "
              "Refusing.", file=sys.stderr)
        return 2
    _announce_small_vocabulary(sources, len(full))

    if not _self_test_matcher():
        print("🔴 GATE BROKEN: the matcher self-test did not fire on its own fixture. The scanner "
              "is not reading what it thinks it is. Refusing.", file=sys.stderr)
        return 2

    items, unreadable, unscannable = _diff_files(repo, a.base)
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
    # kit#93/#104: a committed binary (PDF, image, any non-UTF-8 blob) reads fine via `git show`
    # but cannot be decoded as text. The kit owner ruled 2026-09-12: this BLOCKS the push and names the
    # file, the same "cannot check = cannot clear" philosophy as `unreadable` above — it is a
    # different failure mode (a successful git read that isn't scannable text) so it gets its own
    # message, but the outcome is the same refusal, never a silent drop or a best-effort scan.
    if unscannable:
        shown = ", ".join(unscannable[:5]) + ("…" if len(unscannable) > 5 else "")
        print(f"🔴 GATE BROKEN: {len(unscannable)} file(s) being pushed are not scannable text "
              f"({shown}). A binary/non-UTF-8 file this gate cannot read as text is a file it "
              f"cannot clear. Refusing.", file=sys.stderr)
        return 2

    private = _repo_is_private(repo, remote)
    blocks, warns = scan_items(joined_items(items), full, tokens, companies, owner=owner,
                                downgrade_owner=private, retired=retired)
    blocks, warns = dedupe_joined(blocks), dedupe_joined(warns)

    if not a.quiet:
        dest = "CONFIRMED PRIVATE" if private else "public or UNCONFIRMED (treated as public)"
        print(f"pii_gate --push-guard: {len(items)} file(s) in {a.base}..HEAD, destination {dest}")
        print(_vocabulary_blind_spot_line(sources, len(full)))
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
    print(_company_scope_line(len(companies)))
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

    # ── CONTROL 0 (2026-09-21): the owner's own details must be known, or the scan cannot find them ──
    if not _resolve_owner().get("email"):
        print(OWNER_UNRESOLVED, file=sys.stderr)
        return 2
    # ── CONTROL 1: every vocabulary source must have contributed ──────────────────────────────
    # A moved or renamed store would silently shrink the list, and a shrunken list looks exactly
    # like a clean tree.
    missing = [s for s in ("connections", "tracker", "blocked") if not sources.get(s)]
    if missing:
        print(f"🔴 GATE BROKEN: no rows loaded from {', '.join(missing)}. "
              f"The vocabulary cannot have been built. Refusing.", file=sys.stderr)
        return 2

    # ── CONTROL 2: the vocabulary must not be EMPTY; a SMALL one is announced, not refused ────
    if len(full) == 0:
        print("🔴 GATE BROKEN: zero full names loaded. The vocabulary cannot have been built. "
              "Refusing.", file=sys.stderr)
        return 2
    _announce_small_vocabulary(sources, len(full))

    blocks, warns, nfiles = scan(root, full, tokens, companies, owner=_resolve_owner(),
                                  retired=_resolve_retired_facts())

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
        print(_vocabulary_blind_spot_line(sources, len(full)))
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
    print(_company_scope_line(len(companies)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
