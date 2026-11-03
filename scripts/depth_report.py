#!/usr/bin/env python3
"""depth_report.py — the pipeline's stage queues, hand time, and owed reads, from the files.

WHY. The stage counts (discovered, carded, RADAR, BUILD, staged, sent, replied) were
written by hand into documents/state/card-depth-<seat>-<date>.md every day, and the two
floors (50 cards in BUILD or RADAR, 10 in BUILD) were checked by eye. Story S6 of the
pipeline-as-product backlog (2026-09-10) turns that into a script so the count is the same
every run and nobody types it.

SOURCES, read only:
  documents/state/*-card-*.md      the first line carries a STATUS token; that token is the stage
  documents/outreach-queue.md      rows with STATUS: NEW and no card are "discovered or screened"
  documents/send-log.jsonl         sent today; replied flags
  documents/state/mac-time-summary.jsonl   minutes per phase from the passive sampler (S2)
WRITES, only:
  documents/state/depth-report-<date>.md   the report
  documents/state/owed-seen.jsonl          reads already listed, so each is listed once

OWED READS. Any line in a BUILD or RADAR card that carries "OWED" or "read owed" (the markers
new_card.py and the culture gate already write). A read is listed the first time it is
seen; on later runs it is counted but not re-listed until its text leaves the card.

Usage:
    python3 scripts/depth_report.py                 # today, writes the report
    python3 scripts/depth_report.py --print         # print only
    python3 scripts/depth_report.py --repo DIR --date YYYY-MM-DD
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)

CARD_FLOOR = 50
BUILD_FLOOR = 10
STAGE_TOKENS = ("SENT", "PASS", "DROP", "PARK", "BUILD", "RADAR")
TOKEN_RE = re.compile(r"\b(SENT|PASS|DROPPED|DROP|PARK|BUILD|RADAR)\b")
# An owed read is a structured marker, never the word "owed" in prose: a line that starts with
# the scaffold's OWED placeholder, the culture gate's exact S5 phrase, or a bullet under the
# card's "Gate still owed" section.
OWED_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?OWED\b|[Gg]lassdoor unavailable, read owed")
OWED_SECTION_RE = re.compile(r"^##+\s.*gate still owed", re.I)
NOT_A_CARD = ("dedup-card", "panel-calibration-card", "-call-card-", "TEMPLATE")
# ⛔ WHAT A CARD IS, BY THE SHAPE OF ITS NAME, AND ITS ONE HOME (2026-09-21). NOT_A_CARD alone is a
# list of substrings somebody happened to add. A planning memo named `<topic>-card-supply-<date>.md`
# carried none of them and sat on his board as a card; a bug draft was kept off only because its
# name happened to contain `dedup-card`.
#
# A card is `<slug>-card-<YYYY-MM-DD>.md`, optionally `-render`. Words between `-card-` and the date
# mean it is another kind of document. The NAME is used because the content cannot tell them apart:
# real, unresearched cards open with a bare "Name — resolution card, <date>" line and no `·` fields,
# exactly like the documents that are not cards.
#
# ⛔ THIS IS THE ONLY COPY. It lives here because depth_report depends on nothing in this package,
# and board.py already loads it. The fix first landed in board.load_cards alone and his board dropped
# to 101 cards while THIS scanner still gave the memo a stage, so it went on counting as an unruled
# card in the floor. A fix in one of two copies of a rule is a fix in neither.
#
# ⚠️ ITS LIMIT, STATED SO NOBODY OVER-TRUSTS IT: a file named EXACTLY like a card passes, whatever
# is inside it. A memo saved as `<topic>-card-<date>.md` is a card to this rule. The name is the
# only reliable signal available, and it is only as good as the naming.
CARD_NAME_RE = re.compile(r"^(?P<slug>.+?)-card-\d{4}-\d{2}-\d{2}(?:-render)?\.md$")


def why_not_a_card(name):
    """A plain reason a file that looks like a card is not one, or "" when it is one."""
    base = os.path.basename(name)
    if CARD_NAME_RE.match(base) and not any(x in base for x in NOT_A_CARD):
        return ""
    if re.search(r"-card-", base, re.I) and not re.search(r"-card-", base):
        return ("capital letters in `-card-`; the card shape is lowercase, so this is not read as "
                "a card. If it is one, rename it.")
    if any(x in base for x in NOT_A_CARD):
        return "a named kind of document that is not a company card (call card, calibration, draft)"
    if re.search(r"-card-(?!\d{4}-\d{2}-\d{2})", base):
        return "words between `-card-` and the date, so it is some other kind of document"
    return "not the card shape `<slug>-card-<YYYY-MM-DD>.md`"


def is_card_file(name):
    """True when a file under documents/state is a company card, by the shape of its name."""
    base = os.path.basename(name)
    if any(x in base for x in NOT_A_CARD):
        return False
    return CARD_NAME_RE.match(base) is not None


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def card_slug(path):
    """The slug, from the SAME rule that decides a file is a card.

    ⛔ This used `^(.*?)-card-`, which stops at the FIRST `-card-`, while CARD_NAME_RE's slug group
    backtracks to the `-card-` before the date. For `weird-card-y-card-2026-09-03.md` the two gave
    "weird" and "weird-card-y" for one file, and board.py kept a second identical copy. One
    definition now: a name the rule accepts gets the rule's slug."""
    base = os.path.basename(path)
    m = CARD_NAME_RE.match(base)
    if m:
        return m.group("slug")
    m = re.match(r"^(.*?)-card-", base)
    return m.group(1) if m else base


# BUG-265: a BARE verdict field is a token standing alone between two "·" separators, as the
# pre-STATUS card format wrote it ("· RADAR ·"). It is deliberately NOT the same as a token with
# a qualifier in front of it: "· remote PASS ·" appears in a great many headers beside a real
# verdict, and PASS is a stage token, so matching it as a verdict would make almost every card a
# false conflict. Standing alone is what makes it a verdict.
BARE_FIELD_RE = re.compile(r"·\s*(?:[^\w·\s]\s*)?(SENT|PASS|DROPPED|DROP|PARK|BUILD|RADAR)\b[^·]*·", re.I)   # BUG-569: any case


# BUG-569: ONE reader for a status text, shared by card_stage, queue_statuses and (through this module) the board.
#   a verdict word counts in ANY case where a verdict can stand: the first word-like token after marks and the qualifiers NEW / HOLD (any case), and UPPERCASE
#   anywhere (as before, so a real token later in a long status still reads). Lowercase prose later ("was built", "pass") is never read.
#   NEW and HOLD are qualifiers, never verdicts and never stages: "NEW . RADAR" is RADAR (four of his real queue rows), NEW or HOLD alone give no verdict.
#   They come back as the labels "new" and "held", which depth_report only COUNTS. HOLD never maps to PARK (PARK is his decision).
_LEAD_RE = re.compile(r"^[^\w]*((?:(?:NEW|HOLD)\b[^\w]*)*)(?:(SENT|PASS|DROPPED|DROP|PARK|BUILD|RADAR)\b)?", re.I)


# R205: a NON-uppercase lead word is a verdict only when it STANDS ALONE: followed by the end, a separator (· — – :), "(", a check or cross mark, or a date.
# "sent? not yet", "drop me a line", "build out a demo", "Pass rate checked" start a sentence and are prose. After a HOLD qualifier a lowercase word is prose too.
_STANDS_ALONE_RE = re.compile(r"^\s*(?:$|[·—–:(✓✗✔✘]|\d{4}-\d{2}-\d{2})")


def read_status(text):
    """(verdict or None, {"new", "held"} labels) for the text after 'STATUS:' (a card header's, or a queue header's)."""
    t = text or ""
    verdict, quals = None, set()
    m = _LEAD_RE.match(t)
    if m:
        for q in re.findall(r"NEW|HOLD", m.group(1), re.I):
            quals.add("new" if q.upper() == "NEW" else "held")
        word = m.group(2)
        if word and (word == word.upper() or ("held" not in quals and _STANDS_ALONE_RE.match(t[m.end():]))):
            verdict = "DROP" if word.upper() == "DROPPED" else word.upper()
    if verdict is None:
        up = TOKEN_RE.search(t)
        if up:
            verdict = "DROP" if up.group(1) == "DROPPED" else up.group(1)
    return verdict, quals


def card_stage(first_line):
    """Stage from the H1: the token after 'STATUS:' wins; 'DROPPED' counts as DROP.
    No STATUS or no token = 'carded_unruled'.

    BUG-265: a header carrying TWO DIFFERENT verdicts REFUSES ('verdict_conflict') instead of
    resolving by position. Nine cards carried "· RADAR · ... · PARK ·"; none had a STATUS key, so
    this returned 'carded_unruled' and the queue then filled RADAR while INDEX.md recorded PARK
    with a reason. Taking the first silently is what let that disagreement live. Same discipline
    as rule_card.py refusing on 0 or 2+ queue matches: where the record contradicts itself, a
    human rules it. The owner's ruling, 2026-09-11.
    """
    def _norm(tok):
        return "DROP" if tok == "DROPPED" else tok

    found = {_norm(t.upper()) for t in BARE_FIELD_RE.findall(first_line)}
    m = re.search(r"STATUS:\s*(.*)$", first_line, re.I)
    hay = m.group(1) if m else ""
    verdict, _quals = read_status(hay)
    if verdict:
        found.add(verdict)
    if len(found) > 1:
        return "verdict_conflict"
    if verdict:
        return verdict
    return "carded_unruled"


def card_labels(first_line):
    """{"new", "held"} for a card header whose STATUS text carries those qualifiers. Labels only: they never change a stage."""
    m = re.search(r"STATUS:\s*(.*)$", first_line, re.I)
    return read_status(m.group(1) if m else "")[1]


def scan_labels(repo):
    """{slug: {"new"|"held", ...}} for the cards that carry a NEW or HOLD qualifier (same files and same newest-wins rule as scan_cards)."""
    out = {}
    state = os.path.join(repo, "documents", "state")
    try:
        names = sorted(n for n in os.listdir(state) if n.lower().endswith(".md") and re.search(r"-card-", n, re.I))
    except OSError:
        return out
    for n in names:
        if why_not_a_card(n):
            continue
        text = _read(os.path.join(state, n))
        if text is None or not text.strip():
            continue
        slug = card_slug(os.path.join(state, n))
        labels = card_labels(text.splitlines()[0])
        if labels:
            out[slug] = labels
        else:
            out.pop(slug, None)
    return out


def scan_cards(repo):
    """Returns (stages: {slug: stage}, owed: [(slug, line)], skipped: [(file name, reason)]).

    ⛔ NOTHING IS DROPPED IN SILENCE. Every file whose name carries `-card-`, in ANY case, is
    considered, and each one the rule refuses goes into `skipped` with a plain reason. A card
    named with a capital C used to be invisible: the glob is case sensitive, so it never reached
    the rule and vanished without a word. The candidate set is deliberately the near misses, not
    every file mentioning "card": on his data that is 4 refusals out of 108, where the wider set
    would list 47 unrelated files and teach the reader to skip the section."""
    stages, owed, skipped = {}, [], []
    state = os.path.join(repo, "documents", "state")
    try:
        names = sorted(n for n in os.listdir(state)
                       if n.lower().endswith(".md") and re.search(r"-card-", n, re.I))
    except OSError:
        names = []
    for n in names:
        p = os.path.join(state, n)
        why = why_not_a_card(n)
        if why:
            skipped.append((n, why))
            continue
        text = _read(p)
        if text is None or not text.strip():
            skipped.append((n, "empty or unreadable"))
            continue
        slug = card_slug(p)
        first = text.splitlines()[0]
        stage = card_stage(first)
        stages[slug] = stage  # the newest file for a slug wins (sorted by name, date last)
        if True:  # owed lines are collected for every card; build() keeps BUILD and RADAR only
            in_section = False
            for line in text.splitlines()[1:]:
                if line.startswith("#"):
                    in_section = bool(OWED_SECTION_RE.match(line))
                    continue
                s = line.strip()
                if not s:
                    continue
                if OWED_LINE_RE.search(s) or (in_section and s.startswith(("-", "*"))):
                    owed.append((slug, s[:160]))
    return stages, owed, skipped


def queue_statuses(repo):
    """{slug: stage} from outreach-queue.md headers. The seats' rule: the queue STATUS wins over a
    stale card header, so this is applied on top of the card scan."""
    text = _read(os.path.join(repo, "documents", "outreach-queue.md")) or ""
    out = {}
    for block in re.split(r"(?m)^## ", text)[1:]:
        head = block.splitlines()[0]
        m = re.search(r"STATUS:\s*(.*)$", head, re.I)
        if not m:
            continue
        tok, _quals = read_status(m.group(1))
        if not tok:
            continue
        name = head.split("·")[1] if "·" in head else head
        name = re.sub(r"\(.*?\)", "", name).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        out[slug] = tok
    return out


def _name_key(name):
    """A company name reduced to letters and digits: "Fakecorp Information Systems" and the queue's
    "fakecorp-information-systems" become one key."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


# BUG-564 follow-up: queue_match's rule 3 (exact name key) missed 4 real cases where a queue
# header carries a trailing corporate suffix or descriptive note the card's own shorter name
# omits -- "Fakecorp" on the card, "Fakecorp, Inc." or "Fakecorp — built by Example Vendor" in
# the queue. These patterns run on SPACE-separated text; the queue side only ever reaches
# queue_match as an already-hyphenated SLUG ("fakecorp-built-by-example-vendor"), so
# `_queue_match_name_key` de-hyphenates a bare slug (one that has no spaces of its own) back to
# words before matching, rather than keeping two pattern sets in step.
#
# Stripped ONLY for THIS comparison (never for `_name_key` itself, whose other callers -- ledger
# matching in resolve()/board.py -- this task was not asked to touch).
_TRAILING_NOTE = re.compile(r"\s+(?:—\s*.+|built\s+by\s+.+)$", re.I)
_TRAILING_SUFFIX = re.compile(r"(?:,\s*|\s+)(?:inc|l\.?l\.?c|ltd|corp|co)\.?$", re.I)


def _strip_if_safe(pattern, s):
    """`pattern` removed from the END of `s`, kept ONLY if what remains still has 3+ letters or
    digits -- conservative on purpose: a strip that would hollow out the name (or the whole
    thing) is not applied, and `s` comes back unchanged."""
    stripped = pattern.sub("", s).strip().rstrip(",.").strip()
    if len(re.sub(r"[^a-z0-9]", "", stripped.lower())) >= 3:
        return stripped
    return s


def _queue_match_name_key(name):
    """`_name_key`, after stripping ONE trailing descriptive note and ONE trailing corporate
    suffix, each only if doing so leaves a real name behind. Never strips mid-name, never
    touches `_name_key` itself."""
    s = str(name or "").strip()
    if " " not in s and "-" in s:
        s = s.replace("-", " ")   # a queue slug arrives hyphenated; the patterns expect words
    s = _strip_if_safe(_TRAILING_NOTE, s)
    s = _strip_if_safe(_TRAILING_SUFFIX, s)
    return _name_key(s)


def _load_board():
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("depth_report_board", os.path.join(HERE, "board.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def card_companies(repo):
    """{slug: company} from each card's first line ("# <Company> · ..."), over the same files
    scan_cards reads. The name is board's own header reading (board.card_company, 41), so the two
    can never disagree. board loads this module by path, so board is imported here, lazily."""
    board = _load_board()
    out = {}
    state = os.path.join(repo, "documents", "state")
    try:
        names = sorted(n for n in os.listdir(state)
                       if n.lower().endswith(".md") and re.search(r"-card-", n, re.I))
    except OSError:
        return out
    for n in names:
        if why_not_a_card(n):
            continue
        text = _read(os.path.join(state, n)) or ""
        first = text.splitlines()[0] if text.strip() else ""
        name = board.parse_header(first).get("company") or ""
        if name:
            out[card_slug(os.path.join(state, n))] = name
    return out


def queue_match(slug, qstat, company=""):
    """The queue status for one card, or None. TWO rules, used by apply_queue and the feed:
      1. the exact slug;
      2. BUG-313 (2026-09-21): the card's company name equals the queue header's name, letters
         and digits only, after _queue_match_name_key strips ONE trailing corporate suffix
         (", Inc.", "LLC", "Ltd", "Corp", "Co.") and ONE trailing descriptive note ("— ...",
         "built by ...") -- conservatively, never mid-name, never below 3 letters (BUG-564
         follow-up). A short slug ("acme") never met its own company's queue entry
         ("example-co-06") under the old dashed-suffix floor, and his RADAR vanished from Decide.

    BUG-564 (R190c): a THIRD rule used to sit here -- a dashed suffix either way, both sides at
    least 5 letters ("fakecare" / "fakecare-portal"), meant to stop a bare concatenation like
    "kite" taking "kitesoft"'s status. It checked the SLUG's shape, never identity: the dash
    boundary and length floor rule out word concatenation, but they do nothing to rule out two
    REAL, DIFFERENT companies where one's name is a dash-bounded prefix of the other's --
    "acme-health" is not "Acme Health Foo", yet "acme-health-foo".startswith("acme-health-") is
    true, and that rule asked nothing else. Measured against his real cards and queue (101
    cards): removing it changed 0 merged stages, and its own stated intent (a card slug shorter
    than its company's full name) is the exact case rule 2 above already covers, correctly, by
    NAME rather than by slug shape."""
    qs = qstat.get(slug)
    if qs is not None:
        return qs
    key = _queue_match_name_key(company)
    if key:
        for q, st in qstat.items():
            if _queue_match_name_key(q) == key:
                return st
    return None


def apply_queue(stages, qstat, names=None):
    """The card's own STATUS token is the ruled artifact and wins. The queue fills in only for a
    card with no token, and any card where the two disagree is returned for the report.
    Matching is queue_match(); `names` is {slug: company} from card_companies()."""
    merged = dict(stages)
    disagree = []
    for slug, stage in stages.items():
        qs = queue_match(slug, qstat, (names or {}).get(slug, ""))
        if qs is None:
            continue
        if stage == "carded_unruled":
            merged[slug] = qs
        elif qs != stage:
            disagree.append((slug, stage, qs))
    return merged, disagree


# ── BUG-317 (2026-09-21): decisions that live only in the ledger ──────────────────────────────────
# A card with no token and no queue header showed as undecided even when he had decided it: June's
# PARK and Example Co 2's DROP were written to the ledger by a seat when the hooks were not running, and
# Fakecertco's BUILD was a signed hook row. So they came back in Decide and in the fill plans.
# WHICH ROWS COUNT (b4, option B): a SIGNED hook row, or an UNSIGNED manual row whose ruling is a
# verdict, or HOLD with an answer that starts with one. A hook-source row whose signature does not
# verify is forged and ignored. Display only: the send gate (check_preview) still reads hook rows
# with a valid signature and nothing else.
LEDGER_VERDICTS = ("BUILD", "RADAR", "PARK", "DROP")
LEDGER_HOOK_SOURCES = ("posttooluse-hook", "userpromptsubmit-hook")
LEDGER_MANUAL_SOURCE = "manual-devcontainer-no-hooks"
LEDGER_KEYFILES = ("~/.claude/.jobsearch-ledger-key", "~/.jobsearch-ledger-key")


def _ledger_verifying_keys():
    """Every key this machine holds for the ledger. The two installs keep the key in different places."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        import ledger_keys as lk  # noqa: PLC0415
    except ImportError:
        return None, []
    keys, seen = [], set()
    for path in (os.environ.get("JOBKIT_LEDGER_KEYFILE"),) + LEDGER_KEYFILES:
        if not path:
            continue
        for kid, key, src in lk.verifying_keys(os.path.expanduser(path)):
            if kid not in seen:
                seen.add(kid)
                keys.append((kid, key, src))
    return lk, keys


def _ledger_verdict(row):
    ruling = str(row.get("ruling") or "").upper()
    if ruling in LEDGER_VERDICTS:
        return ruling
    if ruling == "HOLD":
        m = re.match(r"\s*(BUILD|RADAR|PARK|DROP)\b", str(row.get("answer") or ""))
        return m.group(1) if m else None
    return None


def ledger_statuses(repo):
    """{company name key: {verdict, provenance, ts, company}}, the latest counted row per company."""
    text = _read(os.path.join(repo, "documents", "decision-ledger.jsonl")) or ""
    lk, keys = None, None
    out = {}
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or not _name_key(row.get("company")):
            continue
        verdict = _ledger_verdict(row)
        if not verdict:
            continue
        if keys is None:
            lk, keys = _ledger_verifying_keys()
        if lk is not None and lk.row_is_peer_minted(row):
            continue  # minted from another session's message or harness text: no verdict, whatever its signature says
        source = row.get("source")
        if source in LEDGER_HOOK_SOURCES:
            if keys is None:
                lk, keys = _ledger_verifying_keys()
            if not lk or not lk.verify_kid(row, keys):
                continue  # forged, tampered, or signed by a key this machine does not hold
            provenance = "signed"
        elif source == LEDGER_MANUAL_SOURCE and not str(row.get("mac") or ""):
            provenance = "unsigned"
        else:
            continue
        key = _name_key(row.get("company"))
        ts = str(row.get("ts") or "")
        if key not in out or ts >= out[key]["ts"]:
            out[key] = {"verdict": verdict, "provenance": provenance, "ts": ts,
                        "company": str(row.get("company"))}
    return out


def resolve(repo):
    """(stages, disagree, basis): the card token, then the queue, then the ledger, fill-only.
    basis is {slug: {"source": card|queue|ledger-signed|ledger-unsigned|none, "at": ts or ""}}.
    A ledger verdict that differs from a card or queue status is reported, never applied. A card
    already at SENT is past any BUILD in the ledger, so that pair is not a disagreement."""
    cards, _owed, _skipped = scan_cards(repo)
    names = card_companies(repo)
    qstat = queue_statuses(repo)
    stages, disagree = apply_queue(cards, qstat, names)
    led = ledger_statuses(repo)
    basis = {}
    for slug, stage in stages.items():
        if cards[slug] != "carded_unruled":
            basis[slug] = {"source": "card", "at": ""}
        elif stage != "carded_unruled":
            basis[slug] = {"source": "queue", "at": ""}
        else:
            basis[slug] = {"source": "none", "at": ""}
        row = led.get(_name_key(names.get(slug, ""))) or led.get(_name_key(slug))
        if not row:
            continue
        if stage == "carded_unruled":
            stages[slug] = row["verdict"]
            basis[slug] = {"source": "ledger-" + row["provenance"], "at": row["ts"]}
        elif row["verdict"] != stage and stage != "SENT":
            disagree.append((slug, stage, row["verdict"]))
    return stages, disagree, basis


def stage_basis(repo):
    """{slug: basis} from resolve(), for a card that must say where its status came from."""
    return resolve(repo)[2]


def queue_new_without_card(repo, stages):
    text = _read(os.path.join(repo, "documents", "outreach-queue.md")) or ""
    n = 0
    for block in re.split(r"(?m)^## ", text)[1:]:
        head = block.splitlines()[0]
        if "STATUS: NEW" not in head:
            continue
        name = head.split("·")[1].strip() if "·" in head else head.strip()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not any(s.startswith(slug[:8]) for s in stages):
            n += 1
    return n


def send_log_today(repo, date):
    sent, replied = 0, 0
    text = _read(os.path.join(repo, "documents", "send-log.jsonl")) or ""
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        d = str(r.get("date") or r.get("ts") or "")[:10]
        if d == date:
            sent += 1
            if r.get("replied") in (True, "true", "yes"):
                replied += 1
    return sent, replied


def hand_time(repo, date):
    text = _read(os.path.join(repo, "documents", "state", "mac-time-summary.jsonl")) or ""
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("date") == date:
            return r
    return None


def suppress_owed(repo, owed, write=True):
    """Return the owed items not yet listed; record them. Keys that left the cards are dropped."""
    path = os.path.join(repo, "documents", "state", "owed-seen.jsonl")
    seen = set()
    for line in (_read(path) or "").splitlines():
        try:
            seen.add(tuple(json.loads(line)))
        except ValueError:
            continue
    current = {(s, t) for s, t in owed}
    new = [(s, t) for s, t in owed if (s, t) not in seen]
    if write:
        with open(path, "w", encoding="utf-8") as f:
            for k in sorted(current):
                f.write(json.dumps(list(k)) + "\n")
    return new


def counts(stages, labels=None):
    """Stage counts, plus (BUG-569) the LABELS "new" and "held" counted next to them. A label is never a stage: the stage counts are the same with or without it."""
    c = {k: 0 for k in ("carded_unruled",) + STAGE_TOKENS}
    for s in stages.values():
        c[s] = c.get(s, 0) + 1
    c["new"] = sum(1 for v in (labels or {}).values() if "new" in v)
    c["held"] = sum(1 for v in (labels or {}).values() if "held" in v)
    return c


def render(date, c, new_rows, sent, replied, owed_all, owed_new, ht, skipped):
    build_radar = c["BUILD"] + c["RADAR"]
    L = [f"# Depth report, {date}", "",
         "Generated by scripts/depth_report.py from the cards, the queue, the send log and the passive sampler. Nothing here was typed.", "",
         "| Stage | Depth |", "|---|---|",
         f"| Discovered or screened, no card (queue NEW) | {new_rows} |",
         f"| Carded, unruled | {c['carded_unruled']} |",
         f"| Ruled RADAR | {c['RADAR']} |",
         f"| Ruled BUILD | {c['BUILD']} of {BUILD_FLOOR} |",
         f"| Sent today | {sent} |",
         f"| Replied, of today's sends | {replied} |",
         f"| PARK / DROP / PASS (off the floor) | {c['PARK']} / {c['DROP']} / {c['PASS']} |",
         f"| SENT lifetime cards | {c['SENT']} |"]
    if c.get("new") or c.get("held"):        # BUG-569: labels only, counted next to the stages and never a stage themselves
        L.append(f"| Labeled NEW and HOLD (labels only, not a stage) | {c.get('new', 0)} / {c.get('held', 0)} |")
    L += ["",
         f"**Floor:** {build_radar} of {CARD_FLOOR} in BUILD or RADAR, gap {max(0, CARD_FLOOR - build_radar)}; "
         f"BUILD {c['BUILD']} of {BUILD_FLOOR}, gap {max(0, BUILD_FLOOR - c['BUILD'])}.", ""]
    L.append("## Hand time, Mac side (passive sampler)")
    if ht:
        m = ht.get("minutes", {})
        L.append("| Phase | Minutes |")
        L.append("|---|---|")
        for k, v in m.items():
            L.append(f"| {k} | {v} |")
        L.append(f"| gap (idle, asleep, not sampling) | {ht.get('gap_minutes', 0)} |")
        L.append(f"| samples | {ht.get('samples', 0)} |")
    else:
        L.append("no samples for this date")
    L.append("")
    L.append(f"## Reads owed on BUILD and RADAR cards: {len(owed_all)} open, {len(owed_new)} new since the last report")
    for s, t in owed_new:
        L.append(f"- {s}: {t}")
    if owed_all and not owed_new:
        L.append("- none new; the open items were listed in an earlier report")
    if skipped:
        L.append("")
        L.append("## Not read as cards, and why")
        L.extend(f"- {n}: {why}" for n, why in skipped)
    return "\n".join(L) + "\n"


def build(repo, date, write=True):
    _cards, owed, skipped = scan_cards(repo)
    stages, disagree, _basis = resolve(repo)
    owed = [(s, t) for s, t in owed if stages.get(s) in ("BUILD", "RADAR")]
    c = counts(stages, scan_labels(repo))
    new_rows = queue_new_without_card(repo, stages)
    sent, replied = send_log_today(repo, date)
    owed_new = suppress_owed(repo, owed, write=write)
    ht = hand_time(repo, date)
    text = render(date, c, new_rows, sent, replied, owed, owed_new, ht, skipped)
    if disagree:
        text += "\n## Card and queue disagree (reconciliation owed; the card's token was counted)\n"
        text += "".join(f"- {s}: card {a}, queue {b}\n" for s, a, b in sorted(disagree))
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--print", action="store_true", dest="only_print")
    a = ap.parse_args(argv)
    text = build(a.repo, a.date, write=not a.only_print)
    print(text)
    if not a.only_print:
        out = os.path.join(a.repo, "documents", "state", f"depth-report-{a.date}.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
