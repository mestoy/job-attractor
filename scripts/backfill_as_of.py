#!/usr/bin/env python3
"""backfill_as_of.py — give every legacy row a real date, from git history.

WHY THIS EXISTS
---------------
`state.py` refuses to write a record with no `as_of`, which is the right rule and also a wall:
almost nothing in the markdown stores carries a date it wrote down itself. Without a backfill,
`state.current()` would be answering questions about a nearly empty store while the real data sat
in markdown, and the age labels would fire on everything at once — noise, which is the exact
failure mode `check_network_freshness.py` was written to avoid ("a check that cannot tell you what
to do next is a check that gets ignored").

So: where a row states its own date, believe it (`authored`). Where it does not, ask git when the
line was written (`git:<sha>`). A git date is a good guess in THIS repo specifically — 391 of 435
commits are frequent "backup" commits, so they land close to real edit times, and the whole repo
spans 2026-07-17 to 2026-07-25, which bounds how wrong any inferred date can be at ~8 days.

THREE THINGS THE PLAN GOT WRONG, CORRECTED HERE AGAINST MEASURED DATA
---------------------------------------------------------------------
1. ⚠️ **The bulk-commit detector was the wrong test.** The plan said to skip "any bulk-reformat
   commit, identified by a diff touching more than ~60% of a file's lines." Measured, that rule
   fires on `documents/discovery-board.md`, where ONE commit accounts for 100% of the lines — and
   it is not a reformat at all, it is the commit that CREATED the file. The rule would have
   discarded the only honest date the entire file has.

   A reformat and a file creation are indistinguishable by line-count share. They are trivially
   distinguishable by CHURN: a reformat rewrites lines it already had (adds ≈ deletes, both
   large), while a creation only adds (deletes = 0). So this file tests churn, not share.

   Measured across all four stores: **zero bulk-reformat commits exist.** Every heavy commit is
   pure-add. The two high-churn commits in `outreach-queue.md` are PRUNES (0/84 and 3/246), and a
   prune cannot corrupt blame — deleted lines are gone, and the lines that survive keep the blame
   they always had. The guard stays because it is cheap and the next reformat is a matter of time,
   but it currently excludes nothing, and this docstring says so rather than implying coverage.

2. ⚠️ **"One store, one table" is false.** `green-board.md` holds FIVE tables with five different
   column layouts (9, 8, 6, 4 and 3 cells wide), and the company sits in column 2 in one of them
   and column 1 in the rest. Any fixed-column parser reads the wrong column on four tables out of
   five and does it silently. So extraction is driven by each table's OWN header row: find the
   column headed "Company", read that. A table with no such header is skipped rather than guessed
   at. This is the same defect class the plan's root-cause section names — a contract between a
   writer and a reader that nothing checks — and the fix is to make the file declare its schema.

3. ⚠️ **The row counts do not reproduce**, same as the "17 parse sites" estimate did not. The
   plan's table says 737 / 102 / 16 / 101 rows. Measured: 732 bullets, 87 pipe rows, 12 pipe rows,
   57 entry headers. The `--json` output reports what was actually found, and the summary prints
   both the extracted and the dated count, so the gap is visible rather than assumed away.

IDEMPOTENCY
-----------
Append-only stores make a double run a doubling, so a record identical in
(key, source_file, source_line, as_of) to one already present is SKIPPED. Re-running is therefore
safe and picks up only what is new, which matters because this will be re-run every time a store
grows before Phase 3 turns markdown into a generated view.

Usage:  scripts/backfill_as_of.py [--write] [--store PATH] [--json] [--limit N]
        scripts/backfill_as_of.py --identity [--kind company|contact] [--auto-only] [--write]
        (dry run by default — it prints what it WOULD write and touches nothing)
Exit:   0 = clean · 1 = rows could not be dated · 2 = git or store unreadable · 3 = usage
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

import state  # noqa: E402  (path juggling must precede the import)

_ISO = re.compile(r"(\d{4}-\d{2}-\d{2})")
# A bullet's company name ends at the first structural break: an em/en dash, an open paren, a
# colon, or a comma. Everything after that is prose or a parenthetical ruling.
_NAME_END = re.compile(r"\s+[—–]\s+|\s*\(|\s*:\s|\s*,\s")
# Same, but WITHOUT the comma: `_split_names` needs the commas intact to see a bare list.
_NAME_END_NOCOMMA = re.compile(r"\s+[—–]\s+|\s*\(|\s*:\s")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_STRIKE = re.compile(r"~~(.+?)~~")
_LEGAL_SUFFIX = re.compile(
    r"^(inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|plc|sa|nv|ag|holdings|"
    r"group|pbc|llp|lp)\.?$", re.I)

# Bullets that are section prose rather than a company row. Keeping this list short and explicit
# beats a cleverer heuristic: a wrong exclusion here silently loses a blocked employer, and the
# blocked list is the one store where a false negative means you gets shown a company he has
# already ruled out.
# ⚠️ EVERY ALTERNATIVE NEEDS ITS WORD BOUNDARY. Without the trailing `\b` this dropped
# **Sourceco**, because the bare alternative `source` matched its first six letters. A prefix
# match in an exclusion list is a silent false negative, and in THIS store that means a company
# you already ruled out becomes eligible to be surfaced to him again.
_NOT_A_COMPANY = re.compile(
    r"^(check this list|these are|keep appending|permanent culture|note|see|source|"
    r"revisit|all of the above|do not|update|why)\b", re.I)


# ── git ──────────────────────────────────────────────────────────────────────────────────────

def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd or REPO, capture_output=True, text=True)


def reformat_revs(path, min_deletes=20, churn_ratio=0.5):
    """Commits that REWROTE this file rather than adding to it. See docstring note 1.

    A commit qualifies only when it deleted a substantial number of lines AND deleted roughly as
    many as it added. That catches a re-template or a re-sort, and deliberately does NOT catch a
    file creation (deletes = 0) or a prune (adds ≈ 0), neither of which makes blame lie.
    """
    rel = os.path.relpath(path, REPO)
    shas = _git("log", "--format=%H", "--", rel).stdout.split()
    out = set()
    for sha in shas:
        ns = _git("show", "--numstat", "--format=", "--first-parent", sha, "--", rel).stdout.strip()
        if not ns:
            continue
        try:
            add, dele = (int(x) for x in ns.splitlines()[0].split("\t")[:2])
        except (ValueError, IndexError):
            continue  # binary or renamed; blame is unaffected either way
        if dele >= min_deletes and add >= min_deletes and dele >= churn_ratio * add:
            out.add(sha)
    return out


def blame_map(path, ignore_revs=()):
    """{line number: (sha, ISO date)} for every line, via one `git blame --line-porcelain`.

    One subprocess for the whole file, not one per line: the per-line shape is what made this
    feel expensive in the plan, and it is not — 567 lines resolve in about a second.
    """
    rel = os.path.relpath(path, REPO)
    cmd = ["blame", "--line-porcelain", "-w"]
    for sha in ignore_revs:
        cmd += ["--ignore-rev", sha]
    r = _git(*cmd, "--", rel)
    if r.returncode != 0:
        return {}

    out, sha, lineno = {}, None, None
    for line in r.stdout.splitlines():
        m = re.match(r"^([0-9a-f]{40})\s+\d+\s+(\d+)", line)
        if m:
            sha, lineno = m.group(1), int(m.group(2))
            continue
        if line.startswith("author-time ") and sha and lineno:
            ts = int(line.split()[1])
            out[lineno] = (sha, datetime.fromtimestamp(ts, timezone.utc).date().isoformat())
    return out


# ── extraction ───────────────────────────────────────────────────────────────────────────────

def _clean_name(s):
    """Strip markdown/emoji down to a bare name.

    ⚠️ The bold span is only honored when it starts at the HEAD of the string. It used to be a
    plain `search()` anywhere, which silently deleted rows: the SomeCo bullet is
    `- SomeCo (BORDERLINE …) … **UPDATE 2026-07-18 — you PASSED**`, so the first bold span
    sat 200 characters in, `_clean_name` returned "UPDATE 2026-07-18 …", and the not-a-company
    filter dropped the whole row. That is a FALSE NEGATIVE in the blocked list, the one store
    where a miss means you gets re-shown a company he already ruled out — the exact harm this
    file's own docstring warns about.
    """
    s = _STRIKE.sub(r"\1", s)
    b = _BOLD.search(s)
    if b and b.start() <= 3:
        s = b.group(1)
    s = re.sub(r"[`*_~]", "", s)
    s = re.sub(r"[\U0001F300-\U0001FAFF\u2190-\u27BF\uFE0F]", " ", s)  # emoji/badges
    return re.sub(r"\s+", " ", s).strip(" .·-—–")


def disposition(text, store):
    """Normalize any store's own vocabulary into ONE comparable verdict.

    WHY THIS FIELD EXISTS — it is the difference between a store that can detect a contradiction
    and one that merely holds two of them. On the first live run `conflicts()` found 2 disagreements
    across 902 keys and looked reassuring. It was not: 23 companies sit on the blocked list AND on
    a live board at the same time, and not one was reported, because `blocked-employers-list.md`
    contributes `{name, note}` while the boards contribute `{status, badge, tier}`. With no
    overlapping field there is nothing to compare, so the single highest-stakes contradiction in
    the repo — CLAUDE.md's *"check this list FIRST before surfacing any company"* against a board
    row saying pursue it — was invisible BY CONSTRUCTION.

    Co-presence alone is not the contradiction, which is why this returns a verdict rather than a
    flag. A blocked company legitimately appears on a board when the board row is struck through
    (already retired), and the blocked list itself carries CORRECTIONS that un-block a company —
    Campminder's *"NOT blocked, and an earlier bench call is CORRECTED"* is the live example, and
    re-benching Campminder is a mistake this repo has already made once.

    Returns: blocked · parked · retired · sent · active · None (unknown, never guessed).
    """
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    low = t.lower()

    if store == "blocked":
        # The correction case must be tested FIRST — these rows live on the blocked list and say
        # the opposite of what the file they sit in means.
        #
        # ⚠️ Kept DELIBERATELY NARROW to explicit reversals. An earlier cut also matched
        # "borderline" and "not a flat block", which misread the SomeCo row: it hedges
        # ("BORDERLINE / his-call … NOT a flat block") and then records
        # "UPDATE 2026-07-18 — you PASSED". A hedge is not an un-blocking, and treating it as
        # one invented a contradiction against the discovery board that did not exist.
        if re.search(r"\bnot blocked\b|\bis corrected\b|\bunblock", low):
            return "allowed"
        return "blocked"

    # ⚠️ An explicit BLOCKED verdict beats the strike-through marker, and this order matters.
    # Testing strike-through first labels a row like `~~**SomeCo**~~ … 🔴 **BLOCKED 2026-01-01**`
    # as "retired" while the blocked list calls the same company "blocked", and `conflicts()` duly
    # reports a disagreement between two rows that say the same thing. When this was measured, a
    # QUARTER of the first batch of conflicts were this normalizer arguing with itself — a false
    # positive manufactured by the detector, which is the fastest way to make a conflict report
    # unreadable.
    if re.search(r"\bblocked\b|\bdrop\b|\bdropped\b|\bdrop\+block\b|\bremote fail\b|"
                 r"\bpass(ed)?\b.*\bnot\b|\bveto\b", low):
        return "blocked"
    if re.search(r"~~", t):                       # struck through, with no explicit verdict
        return "retired"
    if re.search(r"\bparked\b|\bpaused\b|\bon hold\b", low):
        return "parked"
    if re.search(r"\bsent\b", low):
        return "sent"
    if re.search(r"\bnew\b|\bready\b|\bgreen\b|\bprep\b|\bradar\b|\bverify\b", low):
        return "active"
    return None


# A stated date this much older than the commit that wrote the line is a CITATION, not the row's
# own date. The number is not a guess: measured across every dated row in a real store, the gap
# between the stated date and the blame date is bimodal with an EMPTY BAND between 8 and 71 days.
#
#     nearly all   gap 0 to 7 days      a ruling written down within a week of being made
#     none at all  gap 8 to 71 days     nothing lands here
#     a handful    gap 72 days and up   every one hand-checked, every one a citation
#
# The handful were all the same shape: a row saying "a 1st-degree connection since <year>" (a
# connection date), or "acquired by <buyer>, completed <date>" (a deal close). None is when the row
# was ruled, and left alone they became the oldest entries in `stale()` at up to three years —
# sitting at the top of the age report, which is the most visible output this phase produces.
#
# Any cut inside the empty band gives identical results, so 30 is chosen for being round rather
# than for being tuned. If a future row lands in the band, that is a signal to re-measure, not to
# nudge the constant.
CITATION_GAP_DAYS = 30


def _d(s):
    return date.fromisoformat(s)


def _is_citation(stated, blame):
    try:
        return (date.fromisoformat(blame) - date.fromisoformat(stated)).days > CITATION_GAP_DAYS
    except (ValueError, TypeError):
        return False


def _split_names(head):
    """One bullet, one or more companies.

    Splitting is done on the HEAD (the text before the first paren, colon or dash), never the whole
    bullet. The first cut tested the whole bullet for separators and so refused to split any row
    that had a parenthetical, which is nearly all of them — it silently collapsed 24 blocked
    companies into 4 keys:
        `- SomeCo / Otherco / Thirdco / … / Fifteenco (blocked 2026-07-21 …)`    15 companies
        `- Fourthco · Fifthco · … · Seventhco (…)`                                 7 companies
        `- Eighthco Software · Ninthco Finance Group (…)`                          2 companies

    `FIS / Fidelity National Information Services` is an ALIAS pair rather than a list, and it
    splits too. That is deliberate: two keys both resolve to blocked, and for a blocked list an
    over-block is a harmless duplicate while an under-block re-surfaces a company you already
    ruled out. When the two failure modes are asymmetric, lean into the survivable one.
    """
    parts = [p for p in re.split(r"\s*[,·/]\s*", head) if p.strip()]
    if len(parts) < 2:
        return [head]
    # ⚠️ `QAD, Inc.` and `Steampunk, Inc.` are ONE company each. A comma followed by a legal
    # suffix is part of the name, not a list separator, so a part that is a bare suffix means the
    # whole split was a misread and the head must be returned intact.
    if any(_LEGAL_SUFFIX.match(_clean_name(p)) for p in parts):
        return [head]
    # A real list is a list of NAMES. Anything long is prose that happened to contain a slash.
    if all(1 <= len(_clean_name(p).split()) <= 4 and len(_clean_name(p)) >= 2 for p in parts):
        return parts
    return [head]


def _explicit_date(text):
    """The row's own date: the LATEST ISO date it states, not the first.

    ⚠️ This was `search()` (first match) until git contradicted it. 260 bullets in
    `blocked-employers-list.md` carry two or more dates, because a row records its original ruling
    and then its later revisions in place. Taking the first date stamps such a row with the date of
    the call that was subsequently OVERTURNED — the older set winning again, in the very backfill
    written to stop that.

    Blame settles it independently. On every row where first and max disagree, max matches the git
    blame date and first does not. The two shapes, with the companies genericized:
        SomeCo   — "blocked <date> … " then updated three days later; blame says the later date
        Otherco  — "softened <date> on revisit" then a revision; blame says the revision
    Measured across the whole store, max agrees with blame more often than first does. A row is
    current as of the latest thing it records.
    """
    found = _ISO.findall(text)
    good = []
    for d in found:
        try:
            good.append(date.fromisoformat(d).isoformat())
        except ValueError:
            continue
    return max(good) if good else None


def extract_bullets(path):
    """`blocked-employers-list.md`: one company (sometimes several) per `- ` bullet."""
    rows = []
    for i, line in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
        raw = line.rstrip("\n")
        if not raw.startswith("- "):
            continue
        body = raw[2:].strip()
        if not body:
            continue

        # Test the prose filter against the extracted HEAD, never the whole bullet. A bullet's
        # tail routinely contains ruling verbs ("UPDATE", "revisit", "do not") that the filter is
        # meant to catch only when they are the row's SUBJECT.
        head = _NAME_END_NOCOMMA.split(body, 1)[0]
        if _NOT_A_COMPANY.match(_clean_name(head)):
            continue
        names = _split_names(head)

        for n in names:
            name = _clean_name(n)
            if not name or len(name) < 2:
                continue
            rows.append({"line": i, "name": name, "as_of": _explicit_date(body),
                         "payload": {"note": body[:400],
                                     "disposition": disposition(body, "blocked")}})
    return rows


def extract_pipe_tables(path):
    """Header-driven pipe-table extraction. See docstring note 2 for why fixed columns are wrong.

    Walks the file tracking the most recent header row. When a header names a "Company" column,
    subsequent rows of the same width yield that column. Tables without one are skipped, loudly
    in the sense that their row count shows up as `skipped_no_company_header`.
    """
    rows, skipped = [], 0
    header, col, width = None, None, None
    for i, line in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
        raw = line.rstrip("\n")
        if not raw.startswith("|"):
            header, col, width = None, None, None
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        if re.match(r"^\|[\s:\-|]+\|?$", raw):      # the |---|---| separator
            continue

        low = [_clean_name(c).lower() for c in cells]
        if "company" in low:                         # this row is a header
            header, col, width = raw, low.index("company"), len(cells)
            continue

        if header is None or col is None or len(cells) != width:
            if header is None:
                skipped += 1
            continue
        name = _clean_name(cells[col])
        if not name or len(name) < 2:
            continue
        payload = {}
        for h, c in zip([_clean_name(x) for x in header.strip().strip("|").split("|")], cells):
            hk = re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_")
            if hk and hk != "company" and c:
                payload[hk] = c[:300]
        # Read the verdict off the STATUS-ish cells plus the raw company cell, because a
        # struck-through name is itself the retirement marker on this board.
        verdict_src = " ".join(str(payload.get(k, "")) for k in
                               ("status", "tier", "badge", "next_action", "fit_flags", "caveat"))
        payload["disposition"] = disposition(cells[col] + " " + verdict_src, "board")
        rows.append({"line": i, "name": name, "as_of": _explicit_date(raw), "payload": payload})
    return rows, skipped


def extract_queue(path):
    """`outreach-queue.md`: `## 2026-07-17 11:50 ET · Company (domain) · Person (role) · STATUS: X`."""
    rows = []
    for i, line in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
        raw = line.rstrip("\n")
        if not raw.startswith("## "):
            continue
        body = raw[3:].strip()
        parts = [p.strip() for p in body.split("·")]
        if len(parts) < 2:
            continue
        as_of = _explicit_date(parts[0])
        # The first field is the timestamp only when it actually parses as one. A section heading
        # like "## 🔄 RE-SCORE 2026-07-18 (…)" also carries a date, and its second field is not a
        # company, so it must not become a row.
        if not as_of or not re.match(r"^\d{4}-\d{2}-\d{2}", parts[0]):
            continue
        # "Zilliz (zilliz.com)" — the domain belongs in the payload, not welded onto the name.
        # canon() drops parentheticals so the KEY was already right; the display name was not, and
        # Phase 3 regenerates markdown from these payloads.
        raw_name = parts[1]
        domain = None
        dm = re.search(r"\(([a-z0-9.\-]+\.[a-z]{2,})\)", raw_name, re.I)
        if dm:
            domain = dm.group(1)
            raw_name = raw_name[: dm.start()]
        name = _clean_name(raw_name)
        if not name or len(name) < 2:
            continue
        payload = {"entry": body[:400]}
        if domain:
            payload["domain"] = domain
        for p in parts[2:]:
            m = re.match(r"STATUS:\s*(\S+)", p, re.I)
            if m:
                payload["status"] = m.group(1)
        if len(parts) > 2 and "STATUS" not in parts[2].upper():
            payload["person"] = _clean_name(parts[2].split("(")[0])
        payload["disposition"] = disposition(payload.get("status", ""), "queue")
        rows.append({"line": i, "name": name, "as_of": as_of, "payload": payload})
    return rows


# ── the stores ───────────────────────────────────────────────────────────────────────────────

_EXPORT_SOURCE = re.compile(r"Generated by .*?from `([^`]+)`")
_EXPORT_DATE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")


def export_provenance(path):
    """(as_of, as_of_source) from a generated file's OWN provenance header, or (None, None).

    `warm-network.md` is the one file in the repo that already declares where it came from:
    *"Generated by `scripts/parse_network.py` from `Connections-07-21-2026.csv`."* That header is
    the correct `as_of` for every contact in it, and it beats git blame here, because the commit
    date says when the file was REGENERATED while the export date says when the facts were
    observed. Phase 3 extends this header to every generated file.
    """
    try:
        head = open(path, encoding="utf-8", errors="ignore").read(4000)
    except OSError:
        return None, None
    m = _EXPORT_SOURCE.search(head)
    if not m:
        return None, None
    name = m.group(1)
    d = _EXPORT_DATE.search(name)
    if not d:
        return None, None
    mm, dd, yyyy = d.groups()
    try:
        return date(int(yyyy), int(mm), int(dd)).isoformat(), f"export:{os.path.basename(name)}"
    except ValueError:
        return None, None


def extract_contacts(path):
    """`warm-network.md`: `| 17 | Ana Kirk | Title | Company | 🟢 3y (2023-07-21) | |`.

    ⚠️ THE PARENTHESISED DATE IS NOT THE ROW'S as_of. It is the CONNECTION date, which is the axis
    LaCivita's ladder ranks on, and for Tommy it reads 2023-07-21 while the observation is from the
    2026-07-21 export. Using it would age every contact by years and would be the citation-date
    defect all over again, in a file where the header hands us the right answer for free.
    """
    rows = []
    header, cols, width = None, None, None
    for i, line in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
        raw = line.rstrip("\n")
        if not raw.startswith("|"):
            header, cols, width = None, None, None
            continue
        if re.match(r"^\|[\s:\-|]+\|?$", raw):
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        low = [_clean_name(c).lower() for c in cells]
        if "name" in low:
            header, cols, width = raw, {h: n for n, h in enumerate(low)}, len(cells)
            continue
        if header is None or len(cells) != width:
            continue
        name = _clean_name(cells[cols["name"]])
        if not name or len(name) < 2 or name.isdigit():
            continue
        payload = {"name": name}
        for field in ("title", "company"):
            if field in cols and cells[cols[field]]:
                payload[field] = _clean_name(cells[cols[field]])
        if "known since" in cols:
            m = re.search(r"\((\d{4}-\d{2}-\d{2})\)", cells[cols["known since"]])
            if m:
                payload["connected_on"] = m.group(1)
        rows.append({"line": i, "name": name, "as_of": None, "payload": payload})
    return rows


def extract_sessions(repo):
    """Every `session-state-*.md`, keyed on the single logical fact "which handoff is newest".

    The suffix ordering is parsed HERE, in the extractor, rather than living as a bespoke sort key
    inside `session_start.py`. That is the point of Phase 8: filename shapes are a per-store
    concern like any other parsing, while RESOLUTION belongs to one shared rule. Rows are appended
    oldest first so the generic clause 3 (later append order) settles a same-date tie without
    anyone re-implementing a comparator.
    """
    found = []
    for p in state.handoffs(repo):          # ONE ordering rule, shared with session_start.py
        base = os.path.basename(p)
        m = re.search(r"session-state-(\d{4}-\d{2}-\d{2})(.*)\.md$", base)
        if not m:
            continue
        found.append((m.group(1), m.group(2).strip("-"), base))
    # `line` carries the ORDINAL, not a line number, and it is load-bearing twice over.
    #   1. Dedup fingerprints are (key, file, line, as_of). Three handoffs share 2026-07-22 and
    #      three more share 2026-07-25, so a constant line collided them and silently dropped 7 of
    #      15 — keeping the FIRST of each date, which is the oldest. The bug being fixed, rebuilt
    #      inside the fix.
    #   2. Every version keeps source_file = the glob, so `conflicts()` sees ONE source and does
    #      not report a 15-way disagreement. These files are successive versions of one fact, not
    #      independent observers of it, and that distinction is what source_file means.
    return [{"line": i, "name": "handoff", "as_of": d,
             "payload": {"file": base, "suffix": suffix or "(none)",
                         "path": f"documents/{base}"}}
            for i, (d, suffix, base) in enumerate(found)]


def extract_vetoes(path):
    """`employer-criteria-matrix.md` section A: the 15 hard vetoes, one record each.

    THIS IS THE SINGLE SOURCE (you, 2026-07-25: *"i want a single source"*). Section A is
    chosen over `HARD-INVARIANTS.md`'s never-waived line because it is the ITEMIZED list: 15 rows
    with a test column, against 5 category labels. A category can be regenerated from items, but
    items cannot be recovered from a category, so the finer-grained side has to be the source.

    Both documents become VIEWS of this store, and `check_rulings.py` checks each against it
    rather than against the other. Two documents checked against each other can agree while both
    drift; checked against one source, they cannot.
    """
    rows = []
    text = open(path, encoding="utf-8", errors="ignore").read()
    m = re.search(r"^##\s*A\.\s*HARD VETOES(.*?)^##\s", text, re.S | re.M | re.I)
    if not m:
        return rows
    start = text[: m.start()].count("\n") + 1
    for off, line in enumerate(m.group(1).splitlines()):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not cells[0].isdigit():
            continue
        label = _clean_name(cells[1])
        if not label:
            continue
        rows.append({"line": start + off + 1, "name": label, "as_of": None,
                     "payload": {"ordinal": int(cells[0]), "label": label,
                                 "test": cells[2][:300] if len(cells) > 2 else "",
                                 "never_waived": True}})
    return rows


STORES = [
    {"path": "documents/employer-criteria-matrix.md", "kind": "ruling", "how": "vetoes"},
    {"path": "documents/blocked-employers-list.md", "kind": "company", "how": "bullets"},
    {"path": "documents/green-board.md", "kind": "company", "how": "pipe"},
    {"path": "documents/discovery-board.md", "kind": "company", "how": "pipe"},
    {"path": "documents/outreach-queue.md", "kind": "company", "how": "queue"},
    {"path": "documents/warm-network.md", "kind": "contact", "how": "contacts"},
    {"path": "documents/session-state-*.md", "kind": "session", "how": "sessions"},
]


def _extract(spec, path):
    if spec["how"] == "bullets":
        return extract_bullets(path), 0
    if spec["how"] == "queue":
        return extract_queue(path), 0
    if spec["how"] == "contacts":
        return extract_contacts(path), 0
    if spec["how"] == "sessions":
        return extract_sessions(REPO), 0
    if spec["how"] == "vetoes":
        return extract_vetoes(path), 0
    return extract_pipe_tables(path)


def _existing_fingerprints(kind):
    """(key, source_file, source_line, as_of) already in the store — the idempotency guard."""
    rows, _ = state._read_raw(kind)
    return {(r.get("key"), r.get("source_file"), str(r.get("source_line")), r.get("as_of"))
            for r in rows}


def backfill(spec, write=False, limit=None, seen=None):
    rel = spec["path"]
    path = os.path.join(REPO, rel)
    is_glob = "*" in rel
    # ⚠️ A GLOB STORE THAT MATCHES NOTHING IS ABSENT, and saying otherwise is not cosmetic. The
    # existence test used to skip globs entirely, so a store reported as PRESENT on a repo holding
    # zero files, which made --check count it and print a green "in sync" instead of "nothing to
    # compare". A store whose absence cannot be reported is a store that cannot be checked.
    if is_glob:
        import glob as _glob
        if not _glob.glob(os.path.join(REPO, rel)):
            return {"store": rel, "error": "missing"}
    elif not os.path.exists(path):
        return {"store": rel, "error": "missing"}

    rows, skipped = _extract(spec, path)
    # A glob store has no single file to blame, and its rows carry their own dates by construction.
    bad = set() if is_glob else reformat_revs(path)
    bl = {} if is_glob else blame_map(path, ignore_revs=bad)

    # A generated file that declares its provenance is believed over git: the commit date says
    # when it was REGENERATED, the header says when the facts were observed.
    exp_as_of, exp_src = (None, None) if is_glob else export_provenance(path)

    seen = _existing_fingerprints(spec["kind"]) if seen is None else seen
    res = {"store": rel, "kind": spec["kind"], "extracted": len(rows),
           "skipped_no_company_header": skipped, "reformat_commits": sorted(s[:8] for s in bad),
           "authored": 0, "from_git": 0, "undatable": 0, "duplicate": 0, "written": 0,
           "from_export": 0, "citation_overridden": 0,
           "undatable_rows": [], "citation_rows": []}

    for r in rows[: limit or len(rows)]:
        g = bl.get(r["line"])
        if r["as_of"] is None and exp_as_of:
            as_of, src = exp_as_of, exp_src
        elif r["as_of"]:
            as_of, src = r["as_of"], "authored"
            if g and _is_citation(r["as_of"], g[1]):
                as_of, src = g[1], f"git:{g[0][:12]}"
                res["citation_overridden"] += 1
                res["citation_rows"].append({"line": r["line"], "name": r["name"],
                                             "stated": r["as_of"], "used": g[1]})
        else:
            if not g:
                res["undatable"] += 1
                res["undatable_rows"].append({"line": r["line"], "name": r["name"]})
                continue
            as_of, src = g[1], f"git:{g[0][:12]}"

        key = state.key_for(spec["kind"], r["name"])
        if not key:
            res["undatable"] += 1
            continue
        fp = (key, rel, str(r["line"]), as_of)
        if fp in seen:
            res["duplicate"] += 1
            continue
        seen.add(fp)
        res["authored" if src == "authored" else
            "from_export" if src.startswith("export:") else "from_git"] += 1
        if write:
            # `name` is passed explicitly, so an extractor that ALSO puts it in the payload raises
            # TypeError on the keyword collision. Strip it here rather than in each extractor: one
            # guard in the driver beats the same rule remembered in six places, and the contact
            # extractor tripped exactly this on its first run.
            payload = {k: v for k, v in r["payload"].items() if k != "name"}
            state.append(spec["kind"], r["name"], as_of=as_of, as_of_source=src,
                         source_file=rel, source_line=r["line"], run="backfill",
                         name=r["name"], **payload)
            res["written"] += 1
    return res


# ── identity: alias harvest (phase 1d) ───────────────────────────────────────────────────────
#
# WHY THIS MODE EXISTS. `state.resolve()` shipped in 1c with an alias index behind it and NOTHING
# to index: zero of the 2,065 company rows and 1,525 contact rows carry `payload.aliases`, so the
# resolve arm of `rank_criteria.done_set()` is inert and only 44 of the 148 companies with a
# delivered send exist as a key in `company.jsonl` at all. That is why Astra Finance was offered as
# a fresh rung-7 target hours after you had interviewed there.
#
# The harvest is deliberately DUMB: read every place a company or a person is spelled out, group by
# `state.key_for`, and write what was seen. It invents no names.
#
# TWO CLASSES OF VARIANT, AND THEY GET OPPOSITE TREATMENT
# -------------------------------------------------------
# SAME KEY ("SomeCo" / "SomeCo, Inc." → `someco`), auto-merge. The normalizer already ruled these
# identical; recording both spellings only writes down a decision that was already made.
#
# DIFFERENT KEY ("Astra" / "Astra Finance" → `astra` / `astrafinance`), a REAL claim about the
# world, and never made on name similarity. `Zip` and `Zipline`, `Ramp` and `Rampart`, `Spire
# Energy` and `Spire Global` all pass any string test you care to write, and a wrong merge collapses
# two real companies and silently deletes a live target, worse than the bug being fixed here.
# you ruled 2026-08-03 (unattended run): decide on EVIDENCE only. `_merge_evidence()` below
# accepts exactly three proofs, in that order, and a pair with none of them is left unmerged and
# printed. Under-merging costs one duplicate row; over-merging costs a job.

# Ordered MOST curated first. This order IS the canonical-name precedence: green-board and the
# blocked list are hand-written by you, findings and banked are machine-written by the agent
# pipeline, and `send-log.company` is whatever the sender typed in a hurry ("Astra" for Astra
# Finance). Curated beats machine-written, per the plan.
IDENTITY_COMPANY_SOURCES = [
    {"tag": "green-board",  "glob": "documents/green-board.md",            "how": "pipe"},
    {"tag": "blocked-list", "glob": "documents/blocked-employers-list.md", "how": "bullets"},
    {"tag": "findings",     "glob": "documents/findings/*.jsonl",          "how": "findings"},
    {"tag": "banked",       "glob": "documents/banked-candidates-*.md",    "how": "banked"},
    {"tag": "send-log",     "glob": "documents/send-log.jsonl",            "how": "sendlog"},
]

IDENTITY_CONTACT_SOURCES = [
    {"tag": "closeness",   "glob": "documents/contact-closeness.json",             "how": "closeness"},
    {"tag": "connections", "glob": "documents/linkedin-exports/Connections-*.csv", "how": "connections",
     "newest_only": True},
]

_EMAIL = re.compile(r"[\w.+-]+@([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)
_PAREN_DOMAIN = re.compile(r"\(([a-z0-9-]+(?:\.[a-z0-9-]+)+)\)", re.I)
# Sections of a banked file that list names. Everything else in those files is prose about them.
#
# ⚠️ ANCHORED AT THE HEAD OF THE HEADING, and measured. A loose `.*\bPasses\b` also matched
# "## Unresolved, deliberately NOT passes" and "### Product-owner sweep passes", and the paragraphs
# under those two headings entered the store as companies named "Contradictory; comp unstated;
# consulting travel unassessed" and "SomeCo ownership caveat left OPEN". A heading that says
# NOT passes is the strongest possible signal that its contents are not passes.
_BANKED_SECTION = re.compile(r"^##\s+(?:Passes\b|Still worth working\b)", re.I)


def _domains(text):
    """Every email domain and parenthesised domain in one line of source text.

    Emails are the strongest identity evidence this repo holds, and they are sitting in plain text
    in two places already: `send-log.to` (a contact's work address) and the green board's
    "Boss + email" column (a boss address at the company domain). A domain is a fact about who owns the mailbox,
    which is exactly the claim a cross-key merge has to justify.
    """
    t = str(text or "")
    return {d.lower() for d in _EMAIL.findall(t)} | {d.lower() for d in _PAREN_DOMAIN.findall(t)}


def _domain_keys(domain):
    """The company keys a domain could plausibly name: the whole domain, and its first label.

    `astra.finance` yields {`astrafinance`, `astra`}, which is precisely the pair the send log and
    the banked list disagree about, and the reason the domain settles it. `.finance` is a TLD here,
    so stripping "the TLD" would be wrong; both readings are offered and a merge fires only when the
    two keys under review are BOTH in this set.
    """
    d = str(domain or "").lower().strip()
    if not d or "." not in d:
        return set()
    labels = d.split(".")
    return {re.sub(r"[^a-z0-9]+", "", d), re.sub(r"[^a-z0-9]+", "", labels[0])} - {""}


def _blame_dates(path, _cache={}):
    """{line: (sha, date)} for a markdown file, cached per process.

    ⚠️ Deliberately does NOT run `reformat_revs()`, unlike `backfill()` above. That guard costs one
    `git show` per commit per file and currently excludes nothing (see docstring note 1), and the
    thing it protects, a row's ruling date, is not what is being dated here. An alias row records
    "this file spelled it this way", and a reformat would shift that by days inside a repo that
    spans three weeks. Wrong by days on the LOWEST-precedence source family is not a risk worth
    twelve seconds of subprocesses on every run.
    """
    if path not in _cache:
        _cache[path] = blame_map(path)
    return _cache[path]


def _occurrence(tag, rank, literal, kind, as_of, src, rel, line, domains=()):
    key = state.key_for(kind, literal)
    if not key or not as_of:
        return None
    return {"tag": tag, "rank": rank, "literal": literal, "key": key, "as_of": as_of,
            "as_of_source": src, "source_file": rel, "source_line": line,
            "domains": set(domains)}


def extract_banked(path):
    """`banked-candidates-*.md`: `## Passes` sections holding `·`-separated name runs.

    Only the Passes sections, because the other headings in these files ("Resolved out of this
    pool", "Still worth working") are PROSE about companies rather than a list of them, and a
    sentence yields garbage names. Lines that start a bullet or a quote are skipped for the same
    reason: in this file shape a `- ` line is always commentary on a name, never a name.
    """
    rows, inside = [], False
    for i, line in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
        raw = line.rstrip("\n")
        # Only a LEVEL-2 heading switches the section. `## Passes by batch` is followed by
        # `### Batch 1 (16 of 32)` and the names live under the sub-heading, so a `###` that reset
        # the flag would harvest nothing at all from the 07-21 file.
        if raw.startswith("## "):
            inside = bool(_BANKED_SECTION.match(raw))
            continue
        if raw.startswith("#"):
            continue
        s = raw.strip()
        if not inside or not s or s[0] in "->|(*":
            continue
        for part in s.split("·"):
            # "SomeCo.com (2 reqs)" and "Otherco (Thirdco Software)", the parenthetical is a note
            # or a former name, not part of the literal the rest of the pipeline writes.
            name = _clean_name(re.sub(r"\s*\([^)]*\)\s*$", "", part.strip()))
            # A sentence is not a company. Semicolons, a closing period and a lowercase first letter
            # are what separates the prose that leaked in from the names that belong.
            if (not name or len(name) < 2 or len(name) > 60 or ";" in part
                    or part.strip().endswith(".") or not name[0].isupper() and not name[0].isdigit()
                    or len(name.split()) > 8 or _NOT_A_COMPANY.match(name)):
                continue
            rows.append({"line": i, "name": name})
    return rows


def _harvest_company(spec, rank):
    """Every company literal one source spells out, as occurrence records."""
    import glob as _glob
    out = []
    for path in sorted(_glob.glob(os.path.join(REPO, spec["glob"]))):
        rel = os.path.relpath(path, REPO)
        how = spec["how"]

        if how in ("pipe", "bullets", "banked"):
            # Markdown carries no date of its own for a SPELLING, so git blame answers when the line
            # was written. Family `git` is the bottom of SOURCE_PRECEDENCE, which is the honest
            # placement: an alias backfill must never outrank something you actually observed.
            bl = _blame_dates(path)
            rows = (extract_bullets(path) if how == "bullets" else
                    extract_banked(path) if how == "banked" else
                    extract_pipe_tables(path)[0])
            lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
            for r in rows:
                g = bl.get(r["line"])
                if not g:
                    continue
                raw_line = lines[r["line"] - 1] if r["line"] <= len(lines) else ""
                o = _occurrence(spec["tag"], rank, r["name"], "company",
                                g[1], f"git:{g[0][:12]}", rel, r["line"], _domains(raw_line))
                if o:
                    out.append(o)
            continue

        # JSONL sources state their own date, so the family is `authored`, the row wrote it down.
        for i, line in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            name = _clean_name(rec.get("company") or "")
            if not name or len(name) < 2:
                continue
            as_of = _explicit_date(str(rec.get("date") or rec.get("ts") or ""))
            dom = _domains(rec.get("to") or "") if how == "sendlog" else set()
            o = _occurrence(spec["tag"], rank, name, "company", as_of, "authored", rel, i, dom)
            if o:
                out.append(o)
    return out


def _harvest_contact(spec, rank):
    """Every person literal one source spells out. ⛔ No slug capture, that is 1b, not this."""
    import glob as _glob
    paths = sorted(_glob.glob(os.path.join(REPO, spec["glob"])))
    if spec.get("newest_only") and paths:
        sys.path.insert(0, HERE)
        from parse_network import export_date_from_name          # ONE export-ranking rule, shared
        paths = [max(paths, key=lambda p: (export_date_from_name(p) or date.min, p))]
    out = []
    for path in paths:
        rel = os.path.relpath(path, REPO)
        if spec["how"] == "closeness":
            try:
                blob = json.load(open(path, encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            # The file stamps its own `_updated`, which is the date these closeness rulings were
            # last true. That is a stated date, so `authored`, same as any self-dating row.
            as_of = _explicit_date(str(blob.get("_updated") or ""))
            for n, name in enumerate(sorted(blob.get("contacts") or {}), 1):
                o = _occurrence(spec["tag"], rank, str(name).strip(), "contact",
                                as_of, "authored", rel, n)
                if o:
                    out.append(o)
            continue

        sys.path.insert(0, HERE)
        from parse_network import export_date_from_name, parse_rows
        d = export_date_from_name(path)
        base = os.path.basename(path)
        text = open(path, encoding="utf-8-sig", errors="ignore").read()
        for n, row in enumerate(parse_rows(text), 1):
            name = f"{(row.get('First Name') or '').strip()} {(row.get('Last Name') or '').strip()}"
            o = _occurrence(spec["tag"], rank, name.strip(), "contact",
                            d.isoformat() if d else None, f"export:{base}", rel, n)
            if o:
                out.append(o)
    return out


def group_occurrences(occs):
    """{key → group}. A group holds every literal seen for one key and picks the canonical one.

    Canonical = the literal from the most curated source (lowest `rank`), ties broken by the newest
    observation and then by the longest spelling. Longest last because it is the weakest argument:
    it only ever fires when two equally curated sources of the same age disagree, and there the
    fuller name ("Astra Finance" over "Astra") is the one a human reading the board would recognise.
    """
    groups = {}
    for o in occs:
        g = groups.setdefault(o["key"], {"key": o["key"], "occs": [], "domains": set()})
        g["occs"].append(o)
        g["domains"] |= o["domains"]
    for g in groups.values():
        best = min(g["occs"], key=lambda o: (o["rank"], _neg_date(o["as_of"]), -len(o["literal"])))
        g["canonical"] = best
        # Dedup literals case-insensitively but KEEP the canonical spelling's own casing.
        seen, lits = {best["literal"].lower()}, [best["literal"]]
        for o in sorted(g["occs"], key=lambda o: (o["rank"], o["literal"])):
            if o["literal"].lower() not in seen:
                seen.add(o["literal"].lower())
                lits.append(o["literal"])
        g["literals"] = lits
    return groups


def _neg_date(iso):
    """Sort helper: newer dates sort FIRST under a plain ascending `min()`."""
    return tuple(-int(p) for p in str(iso or "0-0-0").split("-")[:3])


def _pair_candidates(groups, min_len=5):
    """Different-key pairs worth ASKING about. Not one of them is merged on this evidence alone.

    Three shapes, all cheap: one key is a prefix of the other (`astra`/`astrafinance`), one key is a
    substring of the other (`paywithspire`/`spirepaywithspire`), or they share a six-character
    prefix. `min_len` keeps `zip`, `arc`, `ramp` and `loop` out, the exact short names that
    `_BlockedText`'s substring matching silently deleted twice before it was rescued.
    """
    keys = sorted(groups)
    pairs = []
    for i, a in enumerate(keys):
        if len(a) < min_len:
            continue
        for b in keys[i + 1:]:
            if len(b) < min_len:
                continue
            short, long = (a, b) if len(a) <= len(b) else (b, a)
            if short in long or os.path.commonprefix([a, b]) and len(os.path.commonprefix([a, b])) >= 6:
                pairs.append((a, b))
    return pairs


def _word_inside(short, long):
    """Is `short` a whole-word run inside `long`? "pay with spire" ⊂ "spire - pay with spire, inc."

    ⚠️ WORD BOUNDARIES ARE THE ENTIRE GUARD. A plain substring test says "someco" is inside
    "awesomeco bank", "otherco" inside "notherco", "resolve" inside "resolver" and "engine" inside
    "advisorengine", four different companies each, and each one a merge that would delete a live
    target. All four die at `\\b`.
    """
    if not short or short == long:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(short) + r"(?![a-z0-9])", long) is not None


def _merge_evidence(a, b, groups):
    """Why these two keys are one entity, or None. THE ONLY GATE A CROSS-KEY MERGE PASSES THROUGH.

    your rule, 2026-08-03: evidence or nothing, never name similarity. Two proofs, and the list
    is short because everything longer turned out to be circular.

      1. SHARED EMAIL DOMAIN. A mailbox proves ownership. `astra.finance` yields both `astra` and
         `astrafinance`, so the send log's "Astra" and the banked list's "Astra Finance" are one
         company and the domain says so without anyone guessing. This is the strong one.
      2. ONE SOURCE ROW SPELLING BOTH, with one literal a whole-word run inside the other. Same file,
         same line, so the writer wrote them together deliberately: `FIS / Fidelity National` and
         `Spire - Pay with Spire, Inc.` are that shape. Containment alone is NOT enough and neither
         is the shared row alone, `SomeCo / Otherco / Thirdco / … / Fifteenco` is fifteen
         different companies on one blocked-list line, and merging those would be a catastrophe.

    ⛔ REJECTED: "one line anywhere in documents/ writes both". Measured, it fired on 35 pairs and
    was CIRCULAR by construction, the shorter literal matches inside the longer one, so any line
    carrying the long name automatically "co-occurs" with the short one. It merged Awesomeco Bank
    with SomeCo, Notherco with Otherco, and Fourthco Staffing Solutions with Staffing. A test that cannot fail
    is not evidence.
    """
    for dom in sorted(groups[a]["domains"] | groups[b]["domains"]):
        dk = _domain_keys(dom)
        if a in dk and b in dk:
            return f"shared email domain {dom}"

    rows_a = {(o["source_file"], o["source_line"]): o["literal"] for o in groups[a]["occs"]}
    for o in groups[b]["occs"]:
        other = rows_a.get((o["source_file"], o["source_line"]))
        if not other:
            continue
        x, y = sorted((other.lower(), o["literal"].lower()), key=len)
        if _word_inside(x, y):
            return f"one row spells both: '{other}' + '{o['literal']}' at {o['source_file']}:{o['source_line']}"
    return None


def _resolve_merges(groups, auto_only=False):
    """(applied, unmerged). Union-find over the evidenced pairs, so a chain lands on one winner."""
    pairs = _pair_candidates(groups)
    parent = {}

    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    applied, unmerged = [], []
    for a, b in pairs:
        why = None if auto_only else _merge_evidence(a, b, groups)
        if not why:
            unmerged.append((a, b))
            continue
        applied.append((a, b, why))
        parent[find(b)] = find(a)

    # The winner of a component is its most curated canonical literal, same rule as within a key.
    merge_map = {}
    for comp in {find(k) for k in parent}:
        members = sorted(k for k in parent if find(k) == comp)
        win = min(members, key=lambda k: (groups[k]["canonical"]["rank"],
                                          _neg_date(groups[k]["canonical"]["as_of"]),
                                          -len(groups[k]["canonical"]["literal"])))
        for m in members:
            if m != win:
                merge_map[m] = win
    return merge_map, applied, unmerged


def identity(kind, sources, write=False, auto_only=False):
    """Harvest, group, merge on evidence, and register. Dry by default."""
    occs = []
    for rank, spec in enumerate(sources):
        occs += (_harvest_company(spec, rank) if kind == "company"
                 else _harvest_contact(spec, rank))
    groups = group_occurrences(occs)
    merge_map, applied, unmerged = _resolve_merges(groups, auto_only=auto_only)

    # Fold every loser key's literals into its winner BEFORE writing, so the loser key is never
    # created. This is the whole mechanism: `state.resolve()` tries `key_for` first and only falls
    # through to the alias index when the key is unknown, so writing an `astra` row would make
    # resolve("Astra") answer `astra` forever and the merge would be decorative.
    for loser, win in merge_map.items():
        for lit in groups[loser]["literals"]:
            if lit.lower() not in {x.lower() for x in groups[win]["literals"]}:
                groups[win]["literals"].append(lit)
        groups.pop(loser, None)

    res = {"kind": kind, "occurrences": len(occs), "keys": len(groups),
           "merges_applied": applied, "merges_unmerged": unmerged,
           "written": 0, "already": 0, "keys_touched": 0}

    # ⚠️ THE IDEMPOTENCY TEST READS EVERY ROW, NOT `current()`, and it reads them ONCE. Two bugs
    # were fixed here together. Asking `current()` per key made a second run rewrite 601 of the
    # 1,924 company keys, because `register()` unions against the newest row while each row carries
    # its OWN alias's date: register a 2026-07-21 spelling after a 2026-08-02 one and the newer row
    # still wins `current()` without it. `state._alias_index` scans ALL rows, so an alias on any row
    # is already resolvable, and asking the index's own question is what makes a re-run a no-op.
    # Reading the store once rather than 1,924 times took the re-run from over two minutes to
    # seconds, which matters because this is meant to be re-run whenever a store grows.
    have_by_key = {}
    for r in state._read_raw(kind)[0]:
        if r.get("key"):
            have_by_key.setdefault(r["key"], set()).update(
                str(a).lower() for a in (r.get("payload") or {}).get("aliases") or [])

    for key in sorted(groups):
        g = groups[key]
        canon_lit = g["canonical"]["literal"]
        want = g["literals"]
        have = have_by_key.get(key, set())
        todo = [a for a in want if a.lower() not in have]
        if not todo:
            res["already"] += 1
            continue
        res["keys_touched"] += 1
        if not write:
            res["written"] += len(todo)
            continue
        # OLDEST FIRST, so each row unions onto the one before it and the newest row ends up
        # carrying the whole set. `name` needs no ordering care: every call passes `canon_lit` as the
        # name and only the alias varies, so the display name is the canonical spelling either way.
        by_literal = {x["literal"]: x for x in g["occs"]}
        for alias in sorted(todo, key=lambda a: by_literal.get(a, g["canonical"])["as_of"]):
            o = by_literal.get(alias, g["canonical"])
            state.register(kind, canon_lit, alias=alias,
                           as_of=o["as_of"], as_of_source=o["as_of_source"],
                           source_file=o["source_file"], source_line=o["source_line"],
                           run="identity")
            res["written"] += 1
    return res


def _print_identity(res, write):
    print(f"{'✅' if write else '⚪'} {res['kind']}: {res['occurrences']} literal(s) harvested → "
          f"{res['keys']} key(s) · {res['keys_touched']} key(s) need aliases · "
          f"{res['already']} already current · {res['written']} row(s) "
          f"{'written' if write else 'pending'}")
    if res["merges_applied"]:
        print(f"   🔗 {len(res['merges_applied'])} cross-key merge(s) AUTO-APPLIED on evidence:")
        for a, b, why in res["merges_applied"]:
            print(f"      {a} ↔ {b}   ← {why}")
    if res["merges_unmerged"]:
        pairs = ", ".join(f"{a}/{b}" for a, b in res["merges_unmerged"][:20])
        print(f"   ⚪ {len(res['merges_unmerged'])} look-alike pair(s) left UNMERGED, no evidence: "
              f"{pairs}{' …' if len(res['merges_unmerged']) > 20 else ''}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip().split("Usage:")[-1].strip())
        return 3
    write = "--write" in argv
    check = "--check" in argv
    as_json = "--json" in argv
    if write and check:
        print("usage: --check and --write are mutually exclusive", file=sys.stderr)
        return 3
    limit = None
    if "--limit" in argv:
        i = argv.index("--limit")
        try:
            limit = int(argv[i + 1])
        except (IndexError, ValueError):
            print("usage: backfill_as_of.py --limit N", file=sys.stderr)
            return 3
    specs = STORES
    if "--store" in argv:
        i = argv.index("--store")
        want = argv[i + 1] if i + 1 < len(argv) else ""
        specs = [s for s in STORES if s["path"].endswith(want) or want in s["path"]]
        if not specs:
            print(f"no store matches {want!r}", file=sys.stderr)
            return 3

    if _git("rev-parse", "--git-dir").returncode != 0:
        print("🔴 not a git repository — the backfill has no history to read", file=sys.stderr)
        return 2

    if "--identity" in argv:
        # `--auto-only` runs the SAME-KEY half alone. It is the honest way to measure what the
        # normalizer already knew before any cross-key claim is made, which is the number the phase
        # is judged on.
        auto_only = "--auto-only" in argv
        want = argv[argv.index("--kind") + 1] if "--kind" in argv else None
        todo = [("company", IDENTITY_COMPANY_SOURCES), ("contact", IDENTITY_CONTACT_SOURCES)]
        if want:
            todo = [t for t in todo if t[0] == want]
            if not todo:
                print("usage: --kind company|contact", file=sys.stderr)
                return 3
        head = "WROTE" if write else "DRY RUN — nothing written, pass --write to commit"
        print(f"── backfill_as_of --identity{' --auto-only' if auto_only else ''} · {head} ──")
        for kind, srcs in todo:
            _print_identity(identity(kind, srcs, write=write, auto_only=auto_only), write)
        return 0

    results = [backfill(s, write=write, limit=limit) for s in specs]
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 1 if any(r.get("undatable") for r in results) else 0

    if check:
        # The store ↔ markdown contract, read from BOTH sides. This exists because of the plan's
        # own standing rule: "whenever a phase writes a contract between two files, it also writes
        # the check that reads both sides." Until Phase 3 makes the markdown a generated view, the
        # markdown stays hand-edited and the store can silently fall behind it.
        pending = sum(r.get("authored", 0) + r.get("from_git", 0) + r.get("from_export", 0)
                      for r in results)
        # ⚠️ NOTHING TO COMPARE IS NOT AGREEMENT. On a fresh install every store is absent, so
        # `pending` is 0 and the old wording printed a green "in sync": a check reporting success
        # for the reason that it did no work. That is the vacuous pass this store exists to end,
        # so the empty case now says which case it took.
        present = [r for r in results if not r.get("error")]
        if not present:
            print(f"⚪ none of the {len(results)} markdown stores exist yet — nothing to compare. "
                  f"This is normal before the first discovery sweep.")
            return 0
        if not pending:
            print(f"✅ state store is in sync with the markdown stores "
                  f"({len(present)}/{len(results)} store(s) present)")
            return 0
        print(f"🟠 state store is BEHIND the markdown by {pending} row(s)")
        for r in results:
            n = r.get("authored", 0) + r.get("from_git", 0) + r.get("from_export", 0)
            if n:
                print(f"   {n:>4} new row(s) in {r['store']}")
        print("   fix: python3 scripts/backfill_as_of.py --write")
        return 1

    head = "WROTE" if write else "DRY RUN — nothing written, pass --write to commit"
    print(f"── backfill_as_of · {head} ──")
    tot_u = 0
    for r in results:
        if r.get("error"):
            print(f"⚪ {r['store']}: {r['error']}")
            continue
        tot_u += r["undatable"]
        mark = "🟠" if r["undatable"] else "✅"
        print(f"{mark} {r['store']}")
        print(f"     extracted {r['extracted']:>4}  ·  authored {r['authored']:>4}  ·  "
              f"git {r['from_git']:>4}  ·  export {r['from_export']:>4}  ·  "
              f"undatable {r['undatable']:>3}  ·  already present {r['duplicate']:>4}")
        if r["reformat_commits"]:
            print(f"     ⚠️  ignoring {len(r['reformat_commits'])} reformat commit(s): "
                  f"{', '.join(r['reformat_commits'])}")
        for c in r["citation_rows"]:
            print(f"     🔎 line {c['line']} · {c['name']}: stated {c['stated']} reads as a "
                  f"CITATION ({(_d(c['used']) - _d(c['stated'])).days}d before the line was "
                  f"written), using {c['used']} from git instead")
        if r["skipped_no_company_header"]:
            print(f"     ⚪ {r['skipped_no_company_header']} pipe row(s) in tables with no "
                  f"'Company' header — skipped rather than guessed at")
        for u in r["undatable_rows"][:5]:
            print(f"     🟠 undatable: line {u['line']} · {u['name']}")
    if tot_u:
        print(f"\n🟠 {tot_u} row(s) could not be dated. They are NOT written: an undated row in the "
              f"store is the one thing state.py refuses.")
    return 1 if tot_u else 0


if __name__ == "__main__":
    sys.exit(main())
