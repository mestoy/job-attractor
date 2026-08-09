#!/usr/bin/env python3
"""parse_network.py — turn a LinkedIn connections export into a ranked WARM-target list.

WHY. A job search that runs on 100% cold outreach leaves the warmest lane untouched: the people
you already know. Career coaches (Andy LaCivita's Grid) put ~half of a search into NETWORKING —
"find people first, companies second." A LinkedIn connections export is that people-first lane in
a file, and it usually sits unused in ~/Downloads. This script reads your OWN network and ranks
who to talk to.

EXCLUDED EMPLOYERS (config-driven). Some searches carry a hard rule: no outreach to anyone
affiliated with a particular former employer — or to specific named people (a founder, say) whose
leadership you are deliberately routing around. That rule lives in kit_config as DATA
(EXCLUDED_EMPLOYERS, EXCLUDED_PEOPLE, EXCLUDED_EMPLOYER_LEADERSHIP_TITLES), never hard-coded here,
and it is applied HERE, at the source, so an excluded contact can never reach a list you review.
Only the LEADERSHIP tier is filtered; PEERS stay in scope — the exclusion is usually about
leadership harm, not former teammates. The dropped count is ALWAYS reported: an exclusion that
hides its own effect is not auditable. All three lists ship EMPTY, so with no configuration
nothing is excluded.

PRIVACY. This reads YOUR OWN export for YOUR OWN search. Email addresses are NEVER written to the
output file — only counted — because this repo can sync into a shared kit. No enrichment against
outside sources.

Usage:
    scripts/parse_network.py                    # auto-find the newest export
    scripts/parse_network.py <Connections.csv>  # explicit file
    scripts/parse_network.py --limit 40         # cap the printed list
"""
import csv
import glob
import io
import os
import re
import sys
import zipfile
from datetime import date, datetime

# ⛔ BUG-102 (reported by a partner install, FIXED 2026-08-09). This read
# `REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` and ignored
# CLAUDE_PROJECT_DIR, unlike every sibling (state.py, closeness.py, parse_messages.py, …). So this
# script wrote into the REAL documents/ even when a sandbox had redirected the data root, which
# means any test that exercised it mutated live data instead of the copy.
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from check_ats import is_pm  # reuse the title classifier
except Exception:
    def is_pm(t):
        return bool(re.search(r"\bproduct (manager|management|owner)\b", (t or "").lower()))

# Person-specific values come from kit_config; nothing about a particular search is baked in here.
# Every list ships EMPTY except the leadership-title default, so with no config the exclusion is a
# no-op (nothing dropped) and auto-discovery still finds a LinkedIn export in the usual places.
try:
    from kit_config import (
        EXCLUDED_EMPLOYERS,                    # employer NAMES whose people are filtered/flagged
        EXCLUDED_PEOPLE,                       # specific NAMES always excluded (e.g. a founder)
        EXCLUDED_EMPLOYER_LEADERSHIP_TITLES,   # the leadership tier to exclude while keeping peers
        SEARCH_START_DATE,                     # ISO date you began the search ("" disables the flag)
        NETWORK_EXPORT_GLOBS,                  # home-relative globs to auto-find Connections.csv
        NETWORK_EXPORT_ZIP_GLOBS,              # home-relative globs to auto-find the export .zip
    )
except Exception:  # ── standalone fallbacks (generic; no owner data) ──────────────────────────
    EXCLUDED_EMPLOYERS = []                     # [] → no employer is excluded
    EXCLUDED_PEOPLE = []                        # [] → no specific person is excluded
    # ⚠️ EXAMPLE leadership tier — the C-suite / VP / Director / Founder band. Peers below this
    # line stay IN SCOPE; only this tier is filtered out of an excluded employer. Edit in kit_config.
    EXCLUDED_EMPLOYER_LEADERSHIP_TITLES = [
        r"\bfounder\b", r"\bco-?founder\b", r"\bceo\b", r"\bcto\b", r"\bcoo\b", r"\bcpo\b",
        r"\bchief\b", r"\bvp\b", r"\bvice president\b", r"\bhead of\b", r"\bdirector\b",
        r"\bpresident\b", r"\bpartner\b",
    ]
    SEARCH_START_DATE = ""                      # "" → never flag a connection as "search-era"
    NETWORK_EXPORT_GLOBS = [
        "Downloads/*LinkedInDataExport*/Connections.csv",
        "Desktop/*LinkedInDataExport*/Connections.csv",
        "Downloads/Connections.csv",
    ]
    NETWORK_EXPORT_ZIP_GLOBS = [
        "Downloads/*LinkedIn*Export*.zip",
        "Desktop/*LinkedIn*Export*.zip",
    ]


def _compile_literals(terms):
    """Word-boundary OR of ESCAPED literal names — for employer names and people names, which are
    plain strings a user types, not regexes. Returns None (matches nothing) when the list is empty,
    which is how an unconfigured exclusion becomes a clean no-op."""
    terms = [t.strip() for t in (terms or []) if t and t.strip()]
    if not terms:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b", re.I)


def _compile_patterns(terms):
    """OR of RAW regex fragments — for the leadership-title tier, which is expressed as patterns
    (\\bvp\\b, \\bhead of\\b, …). Returns None when the list is empty."""
    terms = [t for t in (terms or []) if t and str(t).strip()]
    if not terms:
        return None
    return re.compile("|".join(terms), re.I)


# The excluded-employer rule, compiled from config data. EMPLOYER matches a company/position;
# PEOPLE matches a specific full name; LEADERSHIP matches the title tier to drop while keeping peers.
EXCLUDED_EMPLOYER_RE = _compile_literals(EXCLUDED_EMPLOYERS)
EXCLUDED_PEOPLE_RE = _compile_literals(EXCLUDED_PEOPLE)
EXCLUDED_LEADERSHIP_RE = _compile_patterns(EXCLUDED_EMPLOYER_LEADERSHIP_TITLES)
EXCLUSION_CONFIGURED = bool(EXCLUDED_EMPLOYER_RE or EXCLUDED_PEOPLE_RE)

SENIOR = re.compile(
    r"\b(founder|co-?founder|ceo|cto|coo|cpo|chief|vp\b|vice president|head of|"
    r"director|president|partner|principal|owner)\b", re.I)
CONNECTOR = re.compile(r"\b(recruit|talent|people ops|hr\b|human resources|staffing|search)\b", re.I)


_EXPORT_NAME_DATE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")

# ⚠️ THE PEOPLE-TABLE LAYOUT IS A CONTRACT BETWEEN THIS WRITER AND rank_criteria._people_rows().
# It was implicit once, and it silently drifted: a `Known since` column was added here and the
# reader was never updated, so EVERY row put the date badge in `company` and mashed the real
# employer into `title`. The daily briefing rendered a date where an employer belongs for months
# and nobody read it as broken.
# The reader now imports this constant and ASSERTS the header it finds matches. Change the columns
# here and the reader fails loudly instead of mis-indexing quietly.
# NOTE the SIXTH column is real and deliberately unnamed: it carries `✉` plus the blocked/contacted
# status. It is empty for most rows, which is exactly why an off-by-one here is so easy to miss.
PEOPLE_TABLE_HEADER = "| | Name | Title | Company | Known since | |"
PEOPLE_TABLE_RULE = "|---|---|---|---|---|---|"


def export_date_from_name(name):
    """Date encoded in a LinkedIn export filename (`..._07-21-2026...`), or None.

    🔴 WHY FILENAME BEATS MTIME. Ranking candidates purely by
    `os.path.getmtime`, and that is a silent-regression hazard: an extracted `Connections.csv`
    inherits LinkedIn's OWN archive timestamp, which can be older than a stale `.zip` sitting beside
    it. So unzipping a NEWER export can produce an OLDER mtime and lose `max()`. A `touch`, a Finder
    copy, a restore-from-backup or a cloud re-sync on any 2025 export would make it beat a 2026 one,
    and the only evidence would be a single `source:` line on stdout that nobody reads afterwards.

    The whole network would then quietly regress by a year with no error. Rank on the date the
    human can see in the filename; fall back to mtime only when the name carries no date.
    """
    m = _EXPORT_NAME_DATE.search(os.path.basename(name or ""))
    if not m:
        return None
    mm, dd, yyyy = (int(x) for x in m.groups())
    try:
        return date(yyyy, mm, dd)
    except ValueError:
        return None


def _recorded_source_date(repo=None):
    """Date of the export that produced the CURRENT warm-network.md, per its own header line."""
    repo = repo or REPO
    try:
        head = open(os.path.join(repo, "documents", "warm-network.md"),
                    encoding="utf-8", errors="ignore").read(4000)
    except Exception:
        return None
    m = re.search(r"Generated by .*?from `([^`]+)`", head)
    return export_date_from_name(m.group(1)) if m else None


def _rank(path):
    """Sort key for an export candidate: (filename date if any, mtime). Newest wins."""
    d = export_date_from_name(path)
    try:
        mt = os.path.getmtime(path)
    except Exception:
        mt = 0
    return (d or date.fromtimestamp(mt), mt)


def find_export(explicit=None):
    """Newest Connections.csv from an explicit path, a LinkedIn export dir, or a .zip."""
    if explicit:
        return explicit, open(explicit, encoding="utf-8-sig", errors="ignore").read()
    cands = []
    # THE REPO IS SEARCHED FIRST-CLASS. Exports used to live only in ~/Downloads, which
    # is not backed up: losing the machine meant re-requesting from LinkedIn. `documents/linkedin-
    # exports/` holds a PII-stripped, version-controlled copy (see scripts/ingest_export.py), so the
    # raw input is as durable as everything derived from it. Ranked identically to any other
    # candidate, by the date in the filename.
    cands += [(_rank(p), p, None)
              for p in glob.glob(os.path.join(REPO, "documents", "linkedin-exports",
                                              "Connections-*.csv"))]
    home = os.path.expanduser("~")
    for pat in ("Downloads/*LinkedInDataExport*/Connections.csv",
                "Desktop/*LinkedInDataExport*/Connections.csv",
                "Downloads/Connections.csv"):
        cands += [(_rank(p), p, None) for p in glob.glob(os.path.join(home, pat))]
    for pat in ("Downloads/*LinkedIn*Export*.zip", "Desktop/*LinkedIn*Export*.zip"):
        for z in glob.glob(os.path.join(home, pat)):
            try:
                with zipfile.ZipFile(z) as zf:
                    for n in zf.namelist():
                        if n.rsplit("/", 1)[-1] == "Connections.csv":
                            cands.append((_rank(z), z, n))
            except (IsADirectoryError, zipfile.BadZipFile, PermissionError, OSError):
                # NARROWED from a bare `except Exception: pass`. Unzipping an export in place can
                # leave a DIRECTORY whose name still ends in .zip, which matches this glob and makes
                # ZipFile raise IsADirectoryError. The bare except swallowed that, and the candidate
                # survived only because another glob happened to catch the same folder by a
                # different route. A bare except here hides real corruption just as quietly.
                continue
    if not cands:
        return None, None
    _, path, member = max(cands, key=lambda c: c[0])
    if member:
        with zipfile.ZipFile(path) as zf:
            return f"{path}::{member}", zf.read(member).decode("utf-8-sig", "ignore")
    return path, open(path, encoding="utf-8-sig", errors="ignore").read()


def parse_rows(text):
    """LinkedIn prepends a 3-line 'Notes:' preamble above the real header.

    A naive csv.DictReader treats that preamble as the header and returns ZERO rows — which makes
    a full network look empty. Always seek the real header row.
    """
    lines = text.splitlines()
    try:
        hdr = next(i for i, l in enumerate(lines) if l.startswith("First Name,"))
    except StopIteration:
        return []
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[hdr:]))))
    return [r for r in rows if (r.get("First Name") or "").strip()]


def blocked_companies():
    p = os.path.join(REPO, "documents", "blocked-employers-list.md")
    names = set()
    if os.path.exists(p):
        # WIDENED (adversarial re-test). An earlier pattern demanded a single capitalized name
        # followed immediately by "(" or "—" and missed four real shapes, any of which would
        # surface a BLOCKED employer as a networking target on the next export:
        #   "- SomeCo, Otherco, Thirdco"                            (comma list, no detail)
        #   "- Recurring-layoff passes: SomeCo, Otherco, Thirdco"   (prose lead-in, names after ":")
        #   "- Example Security / Example AI (blocked ...)"         (slash aliases)
        #   "- 1Password (blocked ...)"                             (digit-leading name)
        for line in open(p, encoding="utf-8", errors="ignore"):
            if not re.match(r"\s*-\s+", line):
                continue
            body = re.sub(r"\[\[[^\]]*\]\]", "", line.strip()[1:].strip())
            # A prose lead-in ends in ":" and the names follow it. Distinguish from a real
            # entry like "- Acme (blocked 2026-01-01): reason" by requiring no "(" in the head.
            head, sep, rest = body.partition(":")
            # A SHORT prose lead-in must not lose its FIRST name: "Recurring-layoff passes: SomeCo,
            # Otherco, Thirdco" loses SomeCo if a `len(head.split()) > 3` guard drops the lead-in,
            # and a BLOCKED company slipping off the blocked-name set means its contact re-surfaces on
            # the warm-network list (a safety filter failing open). A real entry ("Acme (blocked):
            # reason") carries "(" in the head; a prose lead-in does not. When the head has no "(",
            # keep the comma NAME LIST if the rest is a list, else keep the head token.
            if sep and "(" not in head:
                body = rest if "," in rest else head
            body = re.split(r"[\(—]", body)[0]           # drop the parenthetical / em-dash detail
            # Split on commas, and on " / " ONLY when spaced. An unspaced slash is part of the
            # brand: "New/Mode" (newmode.net) is ONE company, and splitting it invents a bogus
            # blocked entry called "new" — which would silently exclude any company whose name
            # starts with that token. Spaced slashes are the alias separator used in this file
            # ("Example Security / Example AI", "SomeCo / Otherco").
            for part in re.split(r",|\s+/\s+", body):
                part = part.strip(" .*\t")
                # A company name here: proper-noun or digit-leading, at most four words, and not a
                # prose fragment. Over-capture is NOT safe — a junk name would wrongly exclude a
                # legitimate company from the warm list — so keep this tight.
                if (2 <= len(part) <= 40 and len(part.split()) <= 4
                        and re.match(r"^[A-Z0-9][\w&.\-'’/ ]*$", part)   # "/" kept: New/Mode
                        and re.search(r"[A-Za-z]{2}", part)):
                    names.add(part.lower())
    return names


def contacted_companies():
    """Companies already contacted — a warm intro there is a re-touch, not a fresh lead."""
    names = set()
    p = os.path.join(REPO, "job_search_tracker.csv")
    if os.path.exists(p):
        try:
            for r in csv.reader(open(p, encoding="utf-8", errors="ignore")):
                if len(r) > 6 and r[6].strip().lower() in ("sent", "applied", "contacted", "interviewing"):
                    names.add(r[1].strip().lower())
        except Exception:
            pass
    return names


def classify(pos):
    pos = pos or ""
    if is_pm(pos):
        return "product"
    if SENIOR.search(pos):
        return "senior"
    if CONNECTOR.search(pos):
        return "connector"
    return "other"


# ── RELATIONSHIP DISTANCE ────────────────────────────────────────────────────────────────────
# WHY: LaCivita's ten outreach templates are ordered by relationship DISTANCE, not by title — that
# ordering IS the method. Ranking by title alone cannot tell a colleague of five years from a
# stranger who accepted an invite last week. The cost is concrete: a contact who connected TWO
# WEEKS AGO can rank near the top of a "who can help first" list on title alone, and then get
# recommended for a warm-rung intro ask — but a fourteen-day-old contact cannot carry a
# "warm the opener to the real relationship, no pretending" message.
#
# The export carries exactly one relationship artifact: `Connected On`. It is a PROXY, never proof —
# it catches the two-week stranger, but it also rates a best friend of three years identically to a
# stranger of three years. So this SORTS and FLAGS; it never decides. Closeness is the searcher's to
# state, and the tool must ask rather than assume.


def _parse_search_start(raw):
    """Parse the configured search-start date. Returns None when unset/unparseable, which turns the
    'search-era' flag OFF entirely (the neutral default)."""
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime((raw or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


# Connections made ON/AFTER this date skew toward search networking rather than a real relationship.
# Unset by default (None) → nothing is flagged search-era until you set your own search-start date.
SEARCH_START = _parse_search_start(SEARCH_START_DATE)


def connected_on(raw):
    """Parse LinkedIn's '09 Jun 2023' date. Returns None when absent or unparseable."""
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime((raw or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def distance(d, today=None):
    """(badge, score_delta, label) for a connection date. Older = more likely a real relationship."""
    if d is None:
        return "", 0, "unknown"
    today = today or date.today()
    years = (today - d).days / 365.25
    if SEARCH_START is not None and d >= SEARCH_START:
        return "🔴", -2, f"search-era ({d.isoformat()})"   # met while job-hunting, not a relationship
    if years >= 3:
        return "🟢", 3, f"{years:.0f}y ({d.isoformat()})"
    return "🟡", 1, f"{years:.0f}y ({d.isoformat()})"


def main():
    # Parse flags and their VALUES out before treating anything as a path — "--limit 20" was
    # leaving "20" as a positional and it got opened as a filename.
    # 🔴 DEFAULT RAISED 40 → 999. A warm-network.md generated with a high limit can hold
    # thousands of numbered rows; a bare `parse_network.py` re-run with a default of 40 per bucket
    # rewrites it at a fraction of that, a silent loss of most of the file. The tables
    # feed `rank_criteria._people_rows()` and the daily 3-people pick, so truncating them quietly
    # shrinks the pool you pick from, the same class of failure as a capped roster section making
    # the WARM-RUNG gate fail CLOSED for everyone outside the printed tiers.
    #
    # This was caught by the row-delta report on its first real run. That is the
    # argument for the report: the old code would have printed "✅ wrote …" and looked identical to
    # a good parse. `--limit N` still works for anyone who wants a short printed list.
    argv, args, limit = sys.argv[1:], [], 999
    force = "--force" in argv
    i = 0
    while i < len(argv):
        if argv[i] == "--limit" and i + 1 < len(argv):
            try:
                limit = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if not argv[i].startswith("--"):
            args.append(argv[i])
        i += 1

    path, text = find_export(args[0] if args else None)
    if not text:
        print("❌ no LinkedIn Connections.csv found. Export from LinkedIn → Settings → Get a copy "
              "of your data, then drop it in ~/Downloads and re-run.")
        sys.exit(2)
    # 🔴 REGRESSION GUARD. warm-network.md is overwritten wholesale, so parsing from an
    # OLDER export than the one that produced the current file silently deletes every connection
    # made in between. Nothing would report it: the file would still look complete, just a year
    # short. This is the mechanism by which recent connections silently stop being durable.
    # Refuse, and make --force the deliberate way past.
    if not force:
        prev = _recorded_source_date()
        now = export_date_from_name(str(path))
        if prev and now and now < prev:
            print(f"⛔ REFUSING to parse: {os.path.basename(str(path))} ({now}) is OLDER than the "
                  f"export that produced the current warm-network.md ({prev}).")
            print("   Overwriting would delete every connection made between those dates.")
            print("   If this is deliberate, re-run with --force.")
            sys.exit(3)
    rows = parse_rows(text)
    if not rows:
        print(f"❌ parsed 0 rows from {path} (header not found — is this a Connections.csv?)")
        sys.exit(2)

    print(f"source: {path}")
    print(f"total 1st-degree connections: {len(rows)}")

    def _is_excluded_employer(r):
        """True when the contact is CURRENTLY at an excluded employer (company or position match)."""
        if EXCLUDED_EMPLOYER_RE is None:
            return False
        return bool(EXCLUDED_EMPLOYER_RE.search(r.get("Company") or "")
                    or EXCLUDED_EMPLOYER_RE.search(r.get("Position") or ""))

    def _is_excluded_leadership(r):
        """True for the LEADERSHIP tier that gets dropped while peers are kept: a specifically named
        person (EXCLUDED_PEOPLE), or a leadership-title position (EXCLUDED_EMPLOYER_LEADERSHIP_TITLES).
        The exclusion is about leadership harm, not former teammates — so PEERS stay in scope."""
        name = f"{r.get('First Name','')} {r.get('Last Name','')}"
        if EXCLUDED_PEOPLE_RE is not None and EXCLUDED_PEOPLE_RE.search(name):
            return True
        if EXCLUDED_LEADERSHIP_RE is not None and EXCLUDED_LEADERSHIP_RE.search(r.get("Position") or ""):
            return True
        return False

    # Filter the excluded employer's LEADERSHIP tier at the source, so an excluded person can never
    # reach a list the searcher reviews. Report the count — an exclusion that hides its effect is not
    # auditable. With EXCLUDED_EMPLOYERS/EXCLUDED_PEOPLE empty, excluded_leadership is [] and nothing
    # is dropped.
    excluded_all = [r for r in rows if _is_excluded_employer(r)]
    excluded_leadership = [r for r in excluded_all if _is_excluded_leadership(r)]
    rows = [r for r in rows if r not in excluded_leadership]
    if EXCLUSION_CONFIGURED:
        print(f"⛔ excluded-employer LEADERSHIP tier filtered at source: {len(excluded_leadership)} "
              f"(of {len(excluded_all)} currently at an excluded employer) — named people + "
              f"leadership titles only. PEERS are IN SCOPE.")
        print("   ⚠️  the export carries CURRENT employer only, so a teammate who LEFT an excluded "
              "employer shows their new company and is invisible to this filter in BOTH directions. "
              "The valuable bridges are the departed teammates, and only you can name them.")

    blocked, contacted = blocked_companies(), contacted_companies()
    buckets = {"product": [], "senior": [], "connector": [], "other": []}
    n_email = 0
    for r in rows:
        co = (r.get("Company") or "").strip()
        kind = classify(r.get("Position"))
        # Accept EITHER column. The raw LinkedIn export carries `Email Address`; the PII-stripped
        # copy in documents/linkedin-exports/ carries a `Has Email` boolean instead, because third
        # party addresses must never be committed (scripts/ingest_export.py). Only the boolean was
        # ever used here, so nothing downstream changes.
        has_email = bool((r.get("Email Address") or r.get("Has Email") or "").strip())
        n_email += 1 if has_email else 0
        flag = ""
        if co.lower() in blocked:
            flag = "🔴 blocked co"
        elif co.lower() in contacted:
            flag = "🟡 already contacted"
        d = connected_on(r.get("Connected On"))
        badge, ddelta, dlabel = distance(d)
        # Relationship distance outweighs title. A stranger with a great title is worse warm-rung
        # fuel than a long-standing contact with a plain one, because the ASK is what has to land.
        score = (2 if kind == "product" else 1 if kind == "senior" else 0) + (1 if has_email else 0)
        score += ddelta
        if flag.startswith("🔴"):
            score -= 3
        buckets[kind].append((score, r.get("First Name", ""), r.get("Last Name", ""),
                              (r.get("Position") or "")[:44], co[:28], has_email, flag,
                              f"{badge} {dlabel}".strip()))

    print(f"contacts with an email exposed: {n_email}")
    for k in ("product", "senior", "connector", "other"):
        print(f"  {k:10} {len(buckets[k])}")

    excl_note = ""
    if EXCLUSION_CONFIGURED:
        excl_note = (f" after excluding **{len(excluded_leadership)} excluded-employer "
                     f"leadership-tier** contact(s) (of {len(excluded_all)} currently at an excluded "
                     f"employer — named people + leadership titles only; **peers are IN SCOPE**)")
    out = [f"# Warm network — ranked warm-outreach targets",
           "",
           f"> Generated by `scripts/parse_network.py` from `{os.path.basename(str(path))}`.",
           f"> {len(rows)} contacts{excl_note}."]
    if EXCLUSION_CONFIGURED:
        out.append("> ⚠️ The export carries CURRENT employer only, so a teammate who LEFT an excluded "
                   "employer shows their new company. Departed teammates are the valuable bridges and "
                   "only you can name them.")
    out += ["> Emails are deliberately NOT written here (this repo can sync to a shared kit); "
            "run the script locally to see them.",
            "> 🔴 = company on the blocked list · 🟡 = company already contacted (a warm intro there "
            "is a re-touch, not a fresh lead).",
            "> **Known since** ranks relationship DISTANCE, which is the axis LaCivita's ladder is "
            "built on: 🟢 3+ years · 🟡 under 3 years · 🔴 connected during the search (on/after your "
            "configured search-start date), so almost certainly search networking rather than a "
            "relationship. A 🔴 must not receive a warm-rung ask — a two-week-old contact can rank "
            "near the top here on title alone.",
            "> ⚠️ **A date is a proxy, never proof.** It cannot tell a best friend from an "
            "acquaintance of the same vintage (a 3-year contact may be either). "
            "**Confirm how close the relationship is before proposing any warm-rung ask.**",
            ""]
    for k, title in (("product", "Product people — potential boss or peer"),
                     ("senior", "Senior decision-makers — can hire or refer"),
                     ("connector", "Connectors — recruiters, talent, people-ops")):
        b = sorted(buckets[k], key=lambda x: -x[0])
        out += [f"## {title} ({len(b)})", "",
                PEOPLE_TABLE_HEADER, PEOPLE_TABLE_RULE]
        for i, (_, fn, ln, pos, co, em, flag, dist) in enumerate(b[:limit], 1):
            out.append(f"| {i} | {fn} {ln} | {pos} | {co} | {dist} | {'✉' if em else ''} {flag} |")
        if len(b) > limit:
            out.append(f"| | *(+{len(b)-limit} more, rerun with --limit)* | | | |")
        out.append("")
    # Contacts at companies ALREADY in the pipeline deserve their own section rather than being
    # score-penalised and truncated off the bottom. A first-degree connection at a company where
    # cold outreach already bounced is a WARM RE-ENTRY — the most actionable row in the file, not
    # the least.
    inplay = [t for b in buckets.values() for t in b if t[6]]
    inplay.sort(key=lambda x: (x[6].startswith("🔴"), -x[0]))
    if inplay:
        out += [f"## ⚡ Contacts at companies already in the pipeline ({len(inplay)})", "",
                "> A warm path into a company we already tried cold. 🟡 already-contacted is the "
                "high-value case: cold outreach there has already been spent, and an intro restarts "
                "it warm. 🔴 blocked is informational only — the company is excluded, so do not "
                "pursue the company, though the person may still be worth knowing.", "",
                "| | Name | Title | Company | Known since | Status |",
                "|---|---|---|---|---|---|"]
        for i, (_, fn, ln, pos, co, em, flag, dist) in enumerate(inplay, 1):
            out.append(f"| {i} | {fn} {ln} | {pos} | {co} | {dist} | {flag} |")
        out.append("")

    # ── LaCivita steps 9 + 10: COMPANY REVIEW and PERSON REVIEW of contacts ──────────────────
    # "Look the other way too! From your LinkedIn Export, sort by name… Prioritize the names of
    # people by relationship, where they work. ADD THEIR COMPANIES TO YOUR COMPANY TARGET LIST
    # (stay in process!). Reach out to people based on your priority of company."
    #
    # This is the REVERSE of the usual pipeline. Instead of choosing companies and then hunting a
    # boss, the companies you already have a warm path into BECOME the target list. Hundreds of
    # companies sit in the export unexamined while discovery hunts strangers.
    NOISE = re.compile(r"^(self[- ]?employed|freelance|independent|n/?a|retired|none|unemployed"
                       r"|in transition|open to work|seeking|student|consultant)\b", re.I)
    bycompany = {}
    for r in rows:
        co = (r.get("Company") or "").strip()
        if not co or NOISE.match(co):
            continue
        bycompany.setdefault(co, []).append(r)

    cands = []
    for co, people in bycompany.items():
        low = co.lower()
        if low in blocked:
            continue                      # excluded company, not a target
        prod = [p for p in people if classify(p.get("Position")) == "product"]
        senr = [p for p in people if classify(p.get("Position")) == "senior"]
        # More contacts at one company = a warmer, more redundant path in. A product or senior
        # contact is worth more than a headcount of unrelated people.
        score = len(people) * 2 + len(prod) * 3 + len(senr) * 2
        if low in contacted:
            score -= 4                    # already contacted: a warm re-entry, still useful
        cands.append((score, co, people, prod, senr, low in contacted))
    cands.sort(key=lambda x: -x[0])

    out += [f"## 🔄 Companies sourced FROM your network (LaCivita steps 9-10) ({len(cands)})", "",
            "> The reverse direction: companies you already have a warm path into, ranked by how many "
            "people you know there and how relevant they are. Andy: *\"Add their companies to your "
            "company target list.\"* These have had **no screen yet** beyond the blocked-list and "
            "excluded-employer filters — per the tiered screen, a warm rung needs deal-breakers only, "
            "so screen each one when you pick it up, not before.",
            "> 🟡 = already contacted cold, so a warm intro here is a re-entry into a spent lead.", "",
            "| | Company | People you know | Product | Senior | |", "|---|---|---|---|---|---|"]
    for i, (sc, co, people, prod, senr, was) in enumerate(cands[:limit], 1):
        who = ", ".join(f"{p['First Name']} {p['Last Name']}" for p in (prod or senr or people)[:2])
        out.append(f"| {i} | **{co[:30]}** | {len(people)} | {len(prod)} | {len(senr)} | "
                   f"{who[:44]}{' 🟡' if was else ''} |")
    if len(cands) > limit:
        out.append(f"| | *(+{len(cands)-limit} more, rerun with --limit)* | | | | |")
    out.append("")
    print(f"  step 9-10 target companies from network: {len(cands)} "
           f"(top has {cands[0][2] and len(cands[0][2])} contacts)" if cands else "")

    # ── COMPLETE ROSTER — load-bearing, never truncate ───────────────────────────────────────
    # WHY THIS IS NOT COSMETIC. `check_preview._is_warm_rung_to_known_contact()` opens the picker
    # for a LaCivita warm rung ONLY if the named person appears in THIS FILE — that is the
    # tamper-evident anchor proving they are a real 1st-degree contact. Every section above is
    # capped by --limit, so a truncated file lists only the top slice and the anchor silently fails
    # CLOSED for everyone else: a legitimate warm question about a contact who fell below the cap
    # gets blocked for a DISPLAY-FORMATTING reason, and the block looks exactly like a real gate hit.
    #
    # A safety anchor whose completeness depends on a presentation flag is not an anchor. Names
    # only, no titles/companies/emails — the anchor does a word-boundary name match and nothing
    # more, so this stays cheap and leaks nothing the tables above do not already show.
    all_names = sorted({f"{r.get('First Name','')} {r.get('Last Name','')}".strip()
                        for r in rows} - {""})
    out += ["## Full 1st-degree roster (complete, never truncated)", "",
            "> ⚠️ **Load-bearing, do not prune or cap this section.** "
            "`check_preview.py` uses it as the tamper-evident anchor for the `WARM-RUNG:` picker "
            "exemption: a name missing here fails the warm-rung gate CLOSED, which reads as a real "
            "block rather than a missing row. Every other section in this file is capped by "
            "`--limit`; this one must not be.", "",
            f"{len(all_names)} contacts.", "",
            "  ".join(all_names), ""]

    dest = os.path.join(REPO, "documents", "warm-network.md")
    # BACKUP BEFORE THE TRUNCATING WRITE. This is a wholesale overwrite with no merge,
    # so a bad parse, a wrong export or an unnoticed hand-annotation is destroyed with no signal.
    # `sync_contacted.py` already established the pattern for the other durable store: write .bak
    # first, then touch the real file. Cheap, and it turns an irreversible step into a reversible
    # one. Also print the row delta, so a parse that LOSES people says so out loud rather than
    # looking like any other successful run.
    prev_rows = 0
    if os.path.exists(dest):
        try:
            prev_text = open(dest, encoding="utf-8", errors="ignore").read()
            prev_rows = len(re.findall(r"^\|\s*\d+\s*\|", prev_text, re.M))
            open(dest + ".bak", "w", encoding="utf-8").write(prev_text)
        except Exception:
            pass  # never let backup failure block the parse; the git history is the second net
    open(dest, "w", encoding="utf-8").write("\n".join(out))
    new_rows = len(re.findall(r"^\|\s*\d+\s*\|", "\n".join(out), re.M))
    if prev_rows:
        delta = new_rows - prev_rows
        mark = "⚠️ " if delta < 0 else ""
        print(f"\n{mark}rows: {prev_rows} → {new_rows} ({delta:+d})   backup: "
              f"{os.path.basename(dest)}.bak")
    print(f"\n✅ wrote {dest} (no email addresses included)")
    print(f"   full roster: {len(all_names)} names (anchors the WARM-RUNG picker exemption)")


if __name__ == "__main__":
    main()


def _register_contacts(rows, source_name, as_of, quiet=False):
    """Persist name + slug + title + company + connect date for each connection. Returns counts.

    PROVENANCE IS THE EXPORT, NOT TODAY. `as_of` is the date in the export's own filename and
    `as_of_source` is `export:<file>`, the same family the existing contact rows already carry.
    Stamping these `live:` would claim the pipeline saw the person today and would outrank a real
    observation under SOURCE_PRECEDENCE, which is the "guess that beats the truth" failure
    `state.append()` refuses undated writes to prevent.

    RE-RUNNING THE SAME EXPORT WRITES NOTHING. Every row already on file under this key, date and
    source with the same payload is a match, and a match is skipped, so a second parse of the same
    CSV neither duplicates a row nor flips a newer observation back to export-era values.
    """
    try:
        import state
    except Exception as e:                       # a store that cannot import must not stop the parse
        if not quiet:
            print(f"   ⚠️  contact store not registered (state.py unavailable: {e})")
        return 0, 0
    if not as_of:
        if not quiet:
            print(f"   ⚠️  contact store not registered: no date in `{source_name}`, and an undated "
                  f"row is refused by state.append() on purpose.")
        return 0, 0

    iso, src = as_of.isoformat(), f"export:{source_name}"

    # ONE STORE READ FOR THE WHOLE PASS. `state.register()` calls `current()`, which calls
    # `_read_raw()`, which re-parses all 1,525 JSON lines EVERY call. At 1,433 connections that is
    # 2.2M line parses against a store that also grows as we append to it, i.e. quadratic in the
    # thing we are looping over. Memoize the raw read for the duration of the pass and hand each
    # newly written record back into the same list, so a person who appears twice in the export
    # still unions their aliases correctly. Restored in `finally`: this is a private hook and it
    # must not stay patched for anything that imports this module.
    original_read_raw = state._read_raw
    cached, bad = original_read_raw("contact")
    next_seq = max([r.get("_seq", 0) for r in cached] or [0]) + 1

    def _cached_read_raw(kind):
        if kind == "contact":
            return cached, bad
        return original_read_raw(kind)

    # What is already on file from THIS export, so a re-run is a no-op.
    seen = set()
    for r in cached:
        if r.get("as_of") == iso and r.get("as_of_source") == src:
            p = r.get("payload") or {}
            seen.add((r.get("key"),) + tuple(str(p.get(f) or "") for f in _REGISTERED_FIELDS))

    written = failed = 0
    state._read_raw = _cached_read_raw
    try:
        for r in rows:
            try:
                url = (r.get("URL") or "").strip()
                if not url:
                    continue                      # no slug, nothing durable to add
                name = f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip()
                if not name:
                    continue
                d = connected_on(r.get("Connected On"))
                fields = {"linkedin": url,
                          "title": (r.get("Position") or "").strip(),
                          "company": (r.get("Company") or "").strip(),
                          "connected_on": d.isoformat() if d else ""}
                key = state.key_for("contact", name)
                sig = (key,) + tuple(str(fields.get(f) or "") for f in _REGISTERED_FIELDS)
                if sig in seen:
                    continue
                rec = state.register("contact", name, as_of=iso, as_of_source=src,
                                     source_file=source_name, run="parse_network", **fields)
                rec = dict(rec)
                rec["_seq"] = next_seq
                next_seq += 1
                cached.append(rec)
                seen.add(sig)
                written += 1
            except Exception:
                # FAIL SOFT PER ROW. One unparseable name is a lost slug; an exception here would
                # be a lost run, and the markdown is already on disk by this point.
                failed += 1
    finally:
        state._read_raw = original_read_raw

    if not quiet:
        note = f", {failed} skipped on error" if failed else ""
        print(f"   contact store: {written} of {len(rows)} rows registered with a LinkedIn slug "
              f"(as_of {iso}, source {src}{note})")
    return written, failed
