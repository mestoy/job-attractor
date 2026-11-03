#!/usr/bin/env python3
"""board.py — the whole pipeline on one page, so a ruling costs one read instead of ten tabs.

WHY. The value stream map (documents/state/pipeline-vsm-current-2026-09-10.md) found the owner
crossing five surfaces to move a card, answering a mean of 159 rulings a day, and holding the
card floor at 21 of 50 with 0 of 10 BUILD. The problem statement names the missing thing plainly:
"no surface that shows the whole stream." This is that surface, v1, read-and-decide. It renders;
it never rules, never sends, never writes to a live store. The ruling still comes from the owner.

WHAT IT SHOWS, in the order the operator recites it:
  1. the header strip   — cards against the card floor, BUILD against the build floor, the ladder,
                          the sending-domain split, and hand time from the passive sampler
  2. awaiting a ruling  — one row per scored, unruled card: panel mean and the three seats, the
                          boss and how well the boss is verified, remote state, age oldest first,
                          the ten gates with honest states, and a link to the card's scorecard
  3. reads owed         — each owed read listed once, with the URL to open
A gate that says nothing is UNRESOLVED, never PASS: silence is not clearance.

STYLE. The <style> block is lifted at build time from the canonical scorecard template, so the
colorblind-safe palette and the state glyphs stay in lockstep with the cards instead of being
copied and drifting. Board-only rules are appended after it and use the same tokens.

PERSONA. Nothing here is specific to one owner. Floors, the owner label and the gate vocabulary
come from kit_config where set, so a second persona is a config change, not a fork.

Usage:
    python3 scripts/board.py                      # write documents/state/board.html
    python3 scripts/board.py --repo DIR --out PATH
    python3 scripts/board.py --print              # HTML to stdout, write nothing
"""
import argparse
import datetime
import glob
import html
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The install this script lives in, never the session root (CLAUDE_PROJECT_DIR); only an explicit JOBSEARCH_DATA_ROOT redirects (kit #156).
REPO = os.path.abspath(os.environ.get("JOBSEARCH_DATA_ROOT") or os.path.dirname(HERE))


def _load(name, path):
    """Load a sibling module by EXPLICIT FILE PATH, never via sys.path.

    ⛔ THE LEAK THIS CLOSES (2026-09-12). `sys.path.insert(0, HERE)` used to sit here so this
    file's own `import kit_config` / `import depth_report` / `from log_linkedin_send import ...`
    could find their siblings. That insert is GLOBAL and never restored: once ANY caller executes
    this module (directly, cross-tree, or even via `importlib.util.spec_from_file_location` —
    that only changes how THIS file is found, not what ITS OWN top-level code does once running),
    partner-starter/scripts sits ahead of every other directory on sys.path for the rest of the
    process, and a LATER bare `import check_style` / `import verify_resume` elsewhere resolves to
    the kit's generic copy instead of the owner's — 63 test_buglog_gate failures, traced through two
    other files (check_one_answer.py, rung_ladder.py) before landing on this one as the actual
    source. `spec_from_file_location` reads the named file directly and touches sys.path not at
    all, so this module can reach its own siblings without moving anyone else's."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

CARD_FLOOR = 50
BUILD_FLOOR = 10

# The ten canonical gates, in the standing order, DEDUP first. Keywords match a card's own
# section heading, never an exact string, because headings carry dates and asides.
GATES = [
    ("dedup", "Prior contact", re.compile(r"dedup|prior contact", re.I)),
    ("blocked", "Blocked list", re.compile(r"blocked list|hard.?filter", re.I)),
    ("news", "News & layoffs", re.compile(r"news.{0,15}layoff|layoff.{0,15}12|industry news", re.I)),
    ("culture", "Culture", re.compile(r"culture", re.I)),
    ("leadership", "Leadership", re.compile(r"leadership|retention", re.I)),
    ("remote", "Remote", re.compile(r"remote", re.I)),
    ("ownership", "Ownership", re.compile(r"ownership", re.I)),
    ("boss", "Boss", re.compile(r"\bboss\b", re.I)),
    ("product_team", "Product team", re.compile(r"product team", re.I)),
    ("live_req", "Live PM req", re.compile(r"live.{0,6}(pm\s*)?req", re.I)),
]

# How a gate's prose resolves. Order matters: a failing word beats a passing one in the same
# section, because a gate that names a problem has not cleared regardless of other wording.
GATE_STATES = [
    ("bad", re.compile(r"\bFAIL\b|\bDROP\b|hard fail|instant no|disqualif", re.I)),
    ("owed", re.compile(r"\bOWED\b|still owed|not pulled|not checked|read owed", re.I)),
    ("warn", re.compile(r"UNPROVEN|UNVERIFIED|UNSTATED|UNKNOWN|UNRESOLVED|CAUTION|FLAG|MIXED|too thin|403", re.I)),
    ("good", re.compile(r"\bPASS\b|\bCLEAN\b|\bCLEARS?\b|CONFIRMED|\bFOUND\b"
                        r"|safe to screen|no prior contact|no prior record", re.I)),
]
# Wording the table cannot classify resolves to "none" exactly like an absent section: the board
# will under-claim a gate before it will ever call an unread one clear.
GLYPH = {"good": "✓", "warn": "!", "owed": "!", "bad": "✕", "none": "○"}
PILL = {"good": "good", "warn": "warn", "owed": "warn", "bad": "bad", "none": "acc"}
LABEL = {"good": "PASS", "warn": "UNPROVEN", "owed": "OWED", "bad": "FAIL", "none": "UNRESOLVED"}

NOT_A_CARD = ("dedup-card", "panel-calibration-card", "-call-card-", "TEMPLATE")
def is_card_file(name):
    """True when a file under documents/state is a company card. The rule lives in depth_report,
    its only copy; see the note there for why it is a NAME rule and why it has one home."""
    return _load("depth_report", os.path.join(HERE, "depth_report.py")).is_card_file(name)
OWED_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?OWED\b|[Gg]lassdoor unavailable, read owed")
OWED_SECTION_RE = re.compile(r"^##+\s.*gate still owed", re.I)
URL_RE = re.compile(r"https?://[^\s)\]\"'<>]+")


def _cfg(name, default):
    try:
        kit_config = _load("kit_config", os.path.join(HERE, "kit_config.py"))
        return getattr(kit_config, name, default)
    except Exception:
        return default


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


# ── card parsing ──────────────────────────────────────────────────────────────────────────────

_SPACED_DASH = re.compile(r"\s+[\u2014\u2013]\s+|\s+-\s+")
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")
_COMMA_TITLE = re.compile(r",\s+[a-z][^,]*$")


def card_company(raw):
    """The company NAME from a card's H1 company field. The ONE place this is read (2026-09-21).

    parse_header splits the H1 on the middle dot and keeps the first piece, so a card titled with a dash instead
    ("Fakemonth (fakemonth.example) — card, 2026-09-04") carried the whole title as its company. 98's real /app run wrote that
    string to the boss registry, the feed showed it on the card, and three more readers took it as the name. This
    keeps what precedes a spaced dash, drops a trailing parenthetical aside ("(fakemonth.example)", "(FPC)", "(formerly ...)"),
    drops a comma before a LOWERCASE clause (", resolution card"; "FakeRx, PBC" and "FAKEE, Inc." keep their
    suffix), and drops a trailing lowercase word "card" only when a spaced dash followed it in the raw text, so
    "Fakeco Card" and "Alpha card" are never touched. A result with nothing left falls back to the raw text, never
    to an empty company."""
    text = " ".join(str(raw or "").split())
    name = _SPACED_DASH.split(text)[0]
    had_dash = name != text
    name = _TRAILING_PAREN.sub("", name)
    # after the parenthetical, whose own commas would otherwise be cut
    name = _COMMA_TITLE.sub("", name)
    if had_dash:
        name = re.sub(r"\s+card$", "", name)   # lowercase only: "Examplo Labs card" is a title, "Fakeco Card" is a name
    name = name.strip(" \u00b7,;")
    return name or text


def parse_header(line):
    """Pull the facts the board shows out of a card's H1. Every field is optional; a card that
    omits one shows the absence rather than a guess."""
    out = {"company": "", "segment": "", "mean": None, "seats": None,
           "status": "", "boss": "", "remote": "", "date": ""}
    body = line.lstrip("# ").strip()
    parts = [p.strip() for p in body.split("·")]
    if parts:
        out["company"] = card_company(parts[0])
    if len(parts) > 1 and "panel" not in parts[1].lower() and "STATUS" not in parts[1]:
        out["segment"] = parts[1]
    m = re.search(r"panel\s+(\d{2,3})\s*/\s*(\d{2,3})\s*/\s*(\d{2,3})", body, re.I)
    if m:
        out["seats"] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"mean\s+(\d{2,3}(?:\.\d)?)", body, re.I)
    if m:
        out["mean"] = float(m.group(1))
    elif out["seats"]:
        out["mean"] = round(sum(out["seats"]) / 3.0, 1)
    m = re.search(r"STATUS:\s*([^·]*)", body, re.I)         # BUG-569: the key in any case; the verdict inside it is read by depth_report.read_status
    if m:
        out["status"] = m.group(1).strip()
    m = re.search(r"boss\s+([^·]+)", body, re.I)
    if m:
        out["boss"] = m.group(1).strip()
    m = re.search(r"remote\s+([A-Za-z\-]+)", body, re.I)
    if m:
        out["remote"] = m.group(1).upper()
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*$", body)
    if m:
        out["date"] = m.group(1)
    return out


def sections(text):
    """{heading: body} for every '## ' section in a card."""
    out = {}
    cur, buf = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur is not None:
                out[cur] = "\n".join(buf)
            cur, buf = line[3:].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf)
    return out


# kit#158: a gate section's OWN bold verdict line ("**Live req** — pass ✅ …") is the gate's
# declared answer. A stray alarm word elsewhere in the section (a travel note, a caveat, a
# negated phrase) must not override it.
VERDICT_LINE_RE = re.compile(r"^\s*\*\*[^*\n]+\*\*\s*[—–-]\s*(.+)$", re.M)

# A match immediately preceded by a negator within a few words is not the thing it names:
# "not disqualifying", "not blocked", "no veto" must not read as the alarm they contain.
GATE_STATE_NEGATORS = re.compile(r"\b(not|no|never|isn't|wasn't|n't)\b", re.I)


def _negated(text, start):
    """True when a negator sits in the few words right before `start`."""
    prefix = " ".join(text[:start].split()[-4:])
    return bool(GATE_STATE_NEGATORS.search(prefix))


def _first_unnegated_state(text, states):
    for state, rx in states:
        for m in rx.finditer(text):
            if not _negated(text, m.start()):
                return state
    return None


def gate_state(body):
    m = VERDICT_LINE_RE.search(body)
    if m:
        verdict_state = _first_unnegated_state(m.group(1), GATE_STATES)
        if verdict_state:
            return verdict_state
    return _first_unnegated_state(body, GATE_STATES) or "none"


def gates_for(text):
    """Ten states, in standing order. A gate with no section at all is UNRESOLVED, not clear."""
    secs = sections(text)
    out = []
    for key, label, rx in GATES:
        body = None
        for heading, content in secs.items():
            if rx.search(heading):
                body = content
                break
        out.append((key, label, "none" if body is None else gate_state(body)))
    return out


def boss_confidence(text):
    secs = sections(text)
    for heading, body in secs.items():
        if re.search(r"\bboss\b", heading, re.I):
            if re.search(r"two[- ]source|independently corroborated|CONFIRMED", body, re.I):
                return "two-source"
            if re.search(r"founder fallback|founder-exception", body, re.I):
                return "founder fallback"
            if re.search(r"not identified|no product (function|leader)|UNRESOLVED", body, re.I):
                return "not identified"
            return "named"
    return "no boss gate"


def clean(s, limit=150):
    """Markdown out, whole words only. A read owed truncated mid-word with stray asterisks reads
    like a rendering bug and costs the reader trust in everything beside it."""
    s = re.sub(r"^\s*[-*\u2022]\s+", "", s)          # a list marker is not part of the text
    s = re.sub(r"\*\*|__|`", "", s).strip()
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\s+", " ", s)
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return cut + "…"


def owed_reads(text):
    """Structured markers only — the scaffold's OWED placeholder, the culture-gate phrase, and
    bullets under a 'Gate still owed' heading. The word 'owed' in prose is not a marker."""
    out, in_section = [], False
    for line in text.splitlines()[1:]:
        if line.startswith("#"):
            in_section = bool(OWED_SECTION_RE.match(line))
            continue
        s = line.strip()
        if not s:
            continue
        if OWED_LINE_RE.search(s) or (in_section and s.startswith(("-", "*"))):
            out.append(s[:200])
    return out


def card_slug(path):
    """The slug, from depth_report's single definition. See the note there."""
    return _load("depth_report", os.path.join(HERE, "depth_report.py")).card_slug(path)


def load_cards(repo):
    cards = {}
    for p in sorted(glob.glob(os.path.join(repo, "documents", "state", "*-card-*.md"))):
        if not is_card_file(p):
            continue
        text = _read(p)
        if not text or not text.strip():
            continue
        slug = card_slug(p)
        head = parse_header(text.splitlines()[0])
        cards[slug] = {
            "slug": slug, "path": p, "text": text, "head": head,
            "gates": gates_for(text), "boss_conf": boss_confidence(text),
            "owed": owed_reads(text),
            "age_h": (datetime.datetime.now()
                      - datetime.datetime.fromtimestamp(os.path.getmtime(p))).total_seconds() / 3600.0,
        }
    return cards


def verdict_of(status):
    """Kept for the header line alone. Stage resolution belongs to resolve_stages() below."""
    m = re.search(r"\b(SENT|PASS|DROPPED|DROP|PARK|BUILD|RADAR)\b", status or "")
    if not m:
        return "unruled"
    return "DROP" if m.group(1) == "DROPPED" else m.group(1)


def _utc(value, end_of_day=False):
    """An ISO time or date as a sortable UTC string, or "" when it is not one."""
    s = str(value or "").strip()
    if not s:
        return ""
    try:
        if len(s) == 10:
            d = datetime.date.fromisoformat(s)
            return d.isoformat() + ("T23:59:59+00:00" if end_of_day else "T00:00:00+00:00")
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()
    except ValueError:
        return ""


def resolve_stages(repo):
    """(stages, disagree). See resolve_stages_basis() for where each stage came from."""
    merged, disagree, _basis = resolve_stages_basis(repo)
    return merged, disagree


def resolve_stages_basis(repo):
    """One source of truth for what stage a card is in, borrowed whole from depth_report.

    Doing this here a second way was a real defect caught before it shipped: 45 of 99 cards
    write their verdict as a bare field ("· RADAR · ... · PARK ·") rather than "STATUS:", so a
    header-only read called them unruled and reported the card floor at 20 of 50 when it is 39.
    The depth report already resolves this correctly (card token first, the queue fills a header
    with no token, disagreements reported), so the board delegates rather than duplicating and
    the two pages can never show him different floors.
    """
    depth_report = _load("depth_report", os.path.join(HERE, "depth_report.py"))
    merged, disagree, basis = depth_report.resolve(repo)
    # BUG-317: a delivered send moves a card the ledger (or nothing) left at BUILD or undecided to
    # SENT, so a card he already wrote to never sits in Decide. A BUILD on the card or in the queue is
    # an explicit status and stays; counts_as_send is the one rule for "this row reached a person".
    # 48 (2026-09-21): only a send AT OR AFTER the ledger decision flips it. A BUILD decided after an old send is a
    # new decision (a next target) and stays BUILD. Times compare in UTC; a send with a date only counts as that
    # whole day, so a same-day send and decision flip.
    last_send = {}
    for line in (_read(os.path.join(repo, "documents", "send-log.jsonl")) or "").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and counts_as_send(r):
            key = depth_report._name_key(r.get("company"))
            when = _utc(r.get("ts")) or _utc(r.get("date"), end_of_day=True)
            if key and (key not in last_send or (when or "") > (last_send[key] or "")):
                last_send[key] = when
    names = depth_report.card_companies(repo)
    for slug, stage in merged.items():
        key = depth_report._name_key(names.get(slug) or slug)
        if (basis[slug]["source"] in ("none", "ledger-signed", "ledger-unsigned")
                and stage in ("BUILD", "carded_unruled") and key in last_send):
            decided = _utc(basis[slug].get("at"))
            if decided and (not last_send[key] or last_send[key] < decided):
                continue
            merged[slug] = "SENT"
            basis[slug] = {"source": "send-log", "at": last_send[key] or ""}
    return merged, disagree, basis


# ── the other data sources ────────────────────────────────────────────────────────────────────

# A send-log row is not automatically a send. Only these statuses reached a human, so only these
# belong in the reply-rate denominator; counting rows instead understates the rate and hides the
# bounces, which are their own signal for the deliverability work.
REACHED = {"sent", "replied"}

# ── ONE SHARED RULE FOR "DOES THIS ROW COUNT" (BUG-270's other door, 2026-09-12) ────────────────
# This file used an ALLOWLIST (REACHED); rung_ladder.py used a DENYLIST (NOT_OUTREACH plus
# log_linkedin_send.NOT_DELIVERED). They agreed at 555/73 only because no status outside those
# six existed in the file — add a seventh (say "queued") and it falls OUT of the allowlist and
# STAYS IN the denylist, and the two producers silently diverge. counts_as_send() is now the one
# place either question is answered; rung_ladder.py imports it rather than keeping its own copy.
NOT_DELIVERED = _load("log_linkedin_send", os.path.join(HERE, "log_linkedin_send.py")).NOT_DELIVERED
NOT_OUTREACH = {"submitted"}   # an ATS application is not a personal outreach touch (the owner, 2026-09-12)
_warned_unknown_statuses = set()


def counts_as_send(r, include_undelivered=False):
    """True when a send-log row belongs in the outreach denominator. Shared by board.ladder() and
    rung_ladder.tally() so the two cannot answer this differently for the same row.

    DIRECTION settles what a row IS, never status: an outbound note that earned a reply carries
    status "replied" too, so a status-based rule must never be allowed to drop it from the
    denominator on status alone (BUG-270's guard, unchanged). A row with no direction field is
    outbound by convention, which is how the historical rows are written.

    An UNRECOGNIZED status is never silently absorbed by either bucket — that silence is the whole
    defect. It does not count (the safer of the two current defaults: overcounting a rate read
    every morning is worse than undercounting it) and is reported by name, once per process, so a
    brand-new status word cannot slip past both producers unnoticed the way BUG-270 did.
    """
    if (r.get("direction") or "").lower() == "inbound":
        return False
    status = str(r.get("status") or "").lower()
    if status in REACHED:
        return True
    if status in NOT_OUTREACH:
        return False
    if status in NOT_DELIVERED:
        return bool(include_undelivered)
    if status not in _warned_unknown_statuses:
        _warned_unknown_statuses.add(status)
        print(f"⚠️  counts_as_send: unrecognized status {status!r} — excluded, not classified. "
              f"Add it to REACHED, NOT_OUTREACH or NOT_DELIVERED.", file=sys.stderr)
    return False


def ladder(repo):
    """Sends actually made, replies against them, bounces on their own, and the sending-domain
    split. The closed baseline is read from the experiment note a send carries, never recomputed,
    because rows before the experiment have no from_address and inferring one would invent a
    cohort."""
    by_status = {}
    reached = replied = 0
    by_domain = {}
    baseline_note = ""
    for line in (_read(os.path.join(repo, "documents", "send-log.jsonl")) or "").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        # An inbound row is a reply that reached HIM, not a note that reached a boss. The one on
        # file (Example Co 2, 2026-07-21) carries status "replied", which is in REACHED, so
        # it rode the denominator from that day and inflated every ladder figure by one. DIRECTION
        # settles what a row is, never status; a row with no direction is outbound by convention.
        if (r.get("direction") or "").lower() == "inbound":
            continue
        status = (r.get("status") or "unrecorded").lower()
        by_status[status] = by_status.get(status, 0) + 1
        if not counts_as_send(r):
            continue
        reached += 1
        rep = r.get("replied") is True
        replied += 1 if rep else 0
        addr = r.get("from_address") or ""
        dom = addr.split("@")[-1] if "@" in addr else None
        if dom:
            d = by_domain.setdefault(dom, [0, 0])
            d[0] += 1
            d[1] += 1 if rep else 0
        if r.get("sender_experiment"):
            baseline_note = str(r["sender_experiment"])
    return {"reached": reached, "replied": replied, "bounced": by_status.get("bounced", 0),
            "by_status": by_status, "by_domain": by_domain, "note": baseline_note,
            "excluded": sum(v for k, v in by_status.items() if k not in REACHED)}


def hand_time(repo, date):
    for line in (_read(os.path.join(repo, "documents", "state", "mac-time-summary.jsonl")) or "").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("date") == date:
            return r
    return None


def scorecard_links(repo):
    """{slug: url} from the hand-maintained index, so a row links to the page he already opens."""
    out = {}
    text = _read(os.path.join(repo, "documents", "state", "scorecards", "INDEX.md")) or ""
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        u = re.search(r"(https://claude\.ai/code/artifact/[0-9a-f-]+)", line)
        f = re.search(r"([A-Za-z0-9._-]+)-\d{4}-\d{2}-\d{2}\.html", line)
        if u and f:
            out.setdefault(f.group(1), u.group(1))
    return out


def canonical_style(repo):
    """Lift the <style> block from the canonical scorecard template so the palette and glyphs
    cannot drift from the cards. Falls back to nothing rather than to a stale copy."""
    for rel in (os.path.join("templates", "scorecard", "scorecard-template.html"),
                os.path.join("documents", "state", "scorecards", "TEMPLATE-scorecard-2026-09-06.html")):
        text = _read(os.path.join(repo, rel))
        if not text:
            continue
        m = re.search(r"<style>(.*?)</style>", text, re.S)
        if m:
            return m.group(1)
    return ""


# ── the priority ladder ───────────────────────────────────────────────────────────────────────

# His ruling 2026-09-10: nearest an offer first. Work already paid for moves before new work is
# started, because a pipeline that starts cards while finished notes sit unsent grows without
# delivering. Each step names the outcome it buys, which is what the breadcrumb shows.
STEPS = [
    ("send",  "Send",   "notes ready to send become conversations"),
    ("build", "Build",  "a ruled card becomes a note worth sending"),
    ("rule",  "Rule",   "scored cards become bosses worth writing to"),
    ("score", "Score",  "carded companies become cards you can rule"),
    ("feed",  "Feed",   "the funnel becomes companies worth knowing"),
]
SEAT_STEPS = {"score", "feed"}          # the seats owe these; they are shown, not assigned to him


# ── ONE SHARED SUPERSEDE CHECK (2026-09-12) ─────────────────────────────────────────────────────
# staged_sends() used to split on DATE ONLY, with no supersede check at all, and reported real,
# CONFIRMED sends as open work every session (seven of them on one install: Tigmamanukan Data, Masagana
# Financial, Kagalakan Health, Pamantayan Quest, Padala Network, Tanod Compliance, Bayad with Bituin — all resolved minutes to
# hours after their draft, one at the IDENTICAL timestamp to the microsecond). pair_brief.py's own
# stale_drafted() already asked the right question; this promotes that question here so both
# producers share it rather than one of them silently skipping it.
def unresolved_drafts(rows):
    """Every row still open (drafted/staged) that no OTHER row has resolved.

    The question is whether a send is still UNRESOLVED, never whether it is still literally
    "drafted" — a resolving row can carry the SAME timestamp as the draft it resolves (mail-draft.sh's
    manual confirmation flip appends a row rather than rewriting the first, because the log is
    append-only), so asking "is there a LATER row" reports an already-sent message as open. Asking
    "does a resolving row EXIST for this message" (same recipient, same subject) does not.

    ⛔ DATE DROPPED FROM THE KEY (kit #146, agreed by the owner and a partner, 2026-09-22). The date
    used to be part of the match, on the theory that a resolving row is logged "at the same time"
    as the draft it closes. A discard or retire is the opposite case: staged in August, ruled dead
    weeks later. Keying on the date as well meant the two rows could never share a key, so the
    draft nagged forever even though it was honestly closed. The same recipient and the same
    subject is already the same email; whether the resolving row landed an hour or a month later
    changes nothing about whether it is still open.
    """
    def key(r):
        return (str(r.get("to", "")), str(r.get("subject", "")))
    resolved = {key(r) for r in rows if str(r.get("status") or "").lower() not in ("drafted", "staged")}
    return [r for r in rows
            if str(r.get("status") or "").lower() in ("drafted", "staged") and key(r) not in resolved]


def staged_sends(repo, today):
    """A note staged today and not yet sent. Rows still open from earlier days are NOT a next
    action: seven of them on this install date back to July, and at least one names a company the
    outreach queue records as sent, so treating age-old drafts as work-to-do would point the owner
    at work already done. They surface as hygiene instead."""
    rows = []
    for line in (_read(os.path.join(repo, "documents", "send-log.jsonl")) or "").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    fresh, stale = [], []
    for r in unresolved_drafts(rows):
        d = str(r.get("date") or r.get("ts") or "")[:10]
        (fresh if d == today else stale).append(
            {"company": r.get("company") or "", "date": d, "to": r.get("to") or ""})
    return fresh, stale


def next_action(cards, ruled, batch, repo, today):
    """Returns (step_key, payload). The first step with work is the one he is standing on."""
    fresh, stale = staged_sends(repo, today)
    if fresh:
        return "send", {"rows": fresh, "stale": stale}

    build_ready = sorted(
        [c for s, c in cards.items() if ruled.get(s) == "BUILD"],
        key=lambda c: -(c["head"]["mean"] or 0))
    if build_ready:
        return "build", {"rows": build_ready, "stale": stale}

    if batch:
        return "rule", {"rows": batch, "stale": stale}

    unscored = [c for s, c in cards.items()
                if ruled.get(s) == "carded_unruled" and c["head"]["mean"] is None]
    if unscored:
        return "score", {"rows": unscored, "stale": stale}
    return "feed", {"rows": [], "stale": stale}


# ── rendering ─────────────────────────────────────────────────────────────────────────────────

BOARD_CSS = """
.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:14px}
.stat{background:var(--panel);border:1px solid var(--rule);padding:10px 12px}
.stat b{display:block;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);margin-bottom:3px}
.stat .v{font-family:"IBM Plex Mono",monospace;font-size:22px;font-weight:500;color:var(--ink)}
.stat .sub2{font-size:12px;color:var(--ink-2);margin-top:2px}
.short{color:var(--warn)}
.row{background:var(--panel);border:1px solid var(--rule);padding:12px 14px;margin-top:10px}
.row .top{display:grid;grid-template-columns:1fr auto;gap:14px;align-items:baseline}
.row .co{font-weight:600;font-size:16px}
.row .sc{font-family:"IBM Plex Mono",monospace;font-size:20px;font-weight:500;color:var(--accent)}
.row .meta{color:var(--ink-2);font-size:13px;margin-top:3px}
.row .gates{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.row .gates .pill{margin-bottom:0;font-size:11px}
.owedlist{margin:0;padding-left:18px}
.owedlist li{margin-bottom:5px;font-size:13px;color:var(--ink-2)}
.empty{color:var(--ink-3);font-size:14px;padding:10px 0}
.legend{font-size:12px;color:var(--ink-3);margin-top:8px}
/* The path: breadcrumb and the day's shape are one component, so position and the next action
   are never two separate readings of the same page. */
.path-nav{display:flex;flex-wrap:wrap;align-items:stretch;gap:0;margin:18px 0 4px;border:1px solid var(--rule);background:var(--panel)}
.step{flex:1 1 118px;padding:10px 12px;border-right:1px solid var(--rule);min-width:118px}
.step:last-child{border-right:0}
.step .nm{font-weight:600;font-size:13px;display:flex;align-items:baseline;gap:6px}
.step .ct{font-family:"IBM Plex Mono",monospace;font-size:20px;font-weight:500;margin-top:2px;color:var(--ink)}
.step .of{font-size:11px;color:var(--ink-3);margin-top:2px;line-height:1.35}
.step.here{background:var(--accent-soft);box-shadow:inset 0 -3px 0 var(--accent)}
.step.here .nm,.step.here .ct{color:var(--accent)}
.step.seat{opacity:.62}
.step.goal{background:var(--good-soft)}
.step.goal .nm,.step.goal .ct{color:var(--good)}
.now{border:1px solid var(--accent);border-left:5px solid var(--accent);background:var(--panel);padding:16px 18px;margin-top:0}
.now h2{margin:0 0 2px}
.now .why{color:var(--ink-2);font-size:14px;margin:0 0 12px}
.later{margin-top:18px;border-top:1px solid var(--rule);padding-top:12px}
.later summary{cursor:pointer;font-weight:600;font-size:14px;padding:6px 0}
.later summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.hygiene{background:var(--warn-soft);border-left:3px solid var(--warn);padding:10px 12px;margin-top:12px;font-size:13px;color:var(--ink-2)}
/* One viewport is a budget, not an aspiration (his ruling 2026-09-10): the decision must be
   reachable without scrolling on a laptop and on a phone. Everything that is not the decision is
   a line, a count, or a closed disclosure. */
.wrap{padding:20px 20px 24px}
h1{font-size:26px}
header{padding-bottom:12px}
.sub{margin-top:4px;font-size:14px}
.then{margin-top:10px;font-size:13px;color:var(--ink-2)}
.then b{color:var(--ink)}
.disclosures{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
.disclosures>details{flex:1 1 220px;margin:0;border:1px solid var(--rule);border-top:1px solid var(--rule);background:var(--panel);padding:8px 12px}
.disclosures>details>summary{font-size:13px;padding:2px 0}
.now{padding:14px 16px}
.now .why{font-size:13px;margin-bottom:10px}
.row{margin-top:8px}
@media (max-width:760px){
  .wrap{padding:14px 14px 20px}
  h1{font-size:21px}
  .sub{display:none}                       /* the headline already says it on a phone */
  .path-nav{flex-wrap:nowrap;overflow-x:auto}
  .step{flex:0 0 auto;min-width:96px;padding:8px 10px}
  .step .of{display:none}                  /* outcome text only where he is standing */
  .step.here .of,.step.goal .of{display:block;max-width:150px}
  .step .ct{font-size:17px}
  .row .top{grid-template-columns:1fr auto}
  .disclosures{flex-direction:column;gap:6px}
  .disclosures>details{flex:0 0 auto}      /* a closed disclosure must not stretch to fill */
}
/* WCAG 2.2 AA: a visible, non-color-only focus ring on every interactive target (2.4.7, 2.4.13),
   and a skip target so keyboard users are not walked through the header on every read (2.4.1). */
a:focus-visible,[tabindex]:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:2px}
.skip{position:absolute;left:-9999px}
.skip:focus{position:static;display:inline-block;margin-bottom:8px;padding:6px 10px;background:var(--accent-soft);color:var(--accent);border:1px solid var(--accent)}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def esc(s):
    return html.escape(str(s or ""))


def offers(repo):
    """Offers on the tracker. The terminus of the path is the mission impact, so it is read from
    the record rather than assumed to be zero."""
    text = _read(os.path.join(repo, "job_search_tracker.csv")) or ""
    n = 0
    for line in text.splitlines()[1:]:
        cells = [c.strip().strip('"').lower() for c in line.split(",")]
        if any(c == "offer" or c.startswith("offer ") for c in cells):
            n += 1
    return n


def card_row(c, links, level):
    """One card, as the active step shows it. At DIY the gates come in full; guided shows the
    gates that are not simply passing, because those are the ones a ruling turns on."""
    h = c["head"]
    seats = " / ".join(str(x) for x in h["seats"]) if h["seats"] else "no panel"
    url = links.get(c["slug"])
    link = (f' · <a href="{esc(url)}" target="_blank" rel="noopener">'
            f'{esc(h["company"])} scorecard</a>'
            if url else ' · <span class="short">scorecard not published</span>')
    gates = c["gates"] if level == "diy" else [g for g in c["gates"] if g[2] != "good"]
    hidden = len(c["gates"]) - len(gates)
    out = ['<div class="row"><div class="top">',
           f'<div><div class="co">{esc(h["company"])}</div>'
           f'<div class="meta">{esc(h["segment"])}</div></div>',
           f'<div class="sc">{h["mean"] if h["mean"] is not None else "—"}</div></div>',
           f'<div class="meta">{esc(seats)} · boss {esc(h["boss"]) or "not named"} '
           f'· <b>boss gate: {esc(c["boss_conf"])}</b> '
           f'· remote {esc(h["remote"]) or "unstated"} · '
           f'{c["age_h"]:.0f}h old{link}</div>',
           '<div class="gates">']
    for _k, label, state in gates:
        out.append(f'<span class="pill {PILL[state]}">{esc(label)} {esc(LABEL[state])}</span>')
    if hidden:
        out.append(f'<span class="pill good">{hidden} more passing</span>')
    out.append("</div>")
    if c["owed"]:
        out.append('<div class="meta">Owed before a ruling: '
                   + esc("; ".join(clean(x, 90) for x in c["owed"][:2])) + "</div>")
    out.append("</div>")
    return "\n".join(out)


def render(repo, date, level="guided"):
    cards = load_cards(repo)
    links = scorecard_links(repo)
    lad = ladder(repo)
    ht = hand_time(repo, date)

    ruled, disagree = resolve_stages(repo)
    n_radar = sum(1 for v in ruled.values() if v == "RADAR")
    n_build = sum(1 for v in ruled.values() if v == "BUILD")
    floor_now = n_radar + n_build

    batch = [c for s, c in cards.items()
             if ruled.get(s) == "carded_unruled" and c["head"]["mean"] is not None]
    # His ruling 2026-09-10: highest mean first, age as the tiebreak. Oldest-first was putting
    # three near-certain PARKs (46 to 48) above the only card on the page that needed thought.
    # The staleness of a low-scoring card is covered by the age shown on every row.
    batch.sort(key=lambda c: (-(c["head"]["mean"] or 0), -c["age_h"]))

    # The shipped kit_config default is the literal "Your Name", so OWNER_FIRST reads "Your" on a
    # config nobody has filled in. Printing that verbatim looks like a broken substitution, so an
    # unfilled name means the page simply does not claim one.
    owner = _cfg("OWNER_FIRST", "")
    if owner.strip().lower() in ("", "you", "your"):
        owner = ""
    card_floor = _cfg("CARD_FLOOR", CARD_FLOOR)
    build_floor = _cfg("BUILD_FLOOR", BUILD_FLOOR)

    step_key, payload = next_action(cards, ruled, batch, repo, date)
    step_label = dict((k, (lbl, buys)) for k, lbl, buys in
                      [(k, l, b) for k, l, b in STEPS])
    unscored = [c for s, c in cards.items()
                if ruled.get(s) == "carded_unruled" and c["head"]["mean"] is None]
    n_offers = offers(repo)
    target = _cfg("MISSION_TARGET", 2)
    by_when = _cfg("MISSION_BY", "Dec 31")

    # The path is chronological, the priority ladder is not. Position is where the work is, so the
    # highlighted step is whatever the ladder picked, wherever it sits on the path.
    path = [
        ("score", "Feed &amp; score", len(unscored), "companies become cards you can rule", True),
        ("rule", "Rule", len(batch), "cards become bosses worth writing to", False),
        ("build", "Build", n_build, "a ruling becomes a note worth sending", False),
        ("send", "Send", len(payload["rows"]) if step_key == "send" else 0,
         "notes become conversations", False),
        ("reply", "Reply", lad["replied"], "conversations become interviews", False),
        ("offer", f"{target} offers", n_offers, f"by {esc(by_when)}", False),
    ]

    L = ['<meta charset="utf-8">',
         # The publish wrapper supplies one for a published Artifact; emitting it here as well
         # makes the file correct when it is opened straight off disk, which is how it is read on
         # the Mac. Without it a phone lays the page out at 980px and crops it.
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         "<title>Job Attractor Board</title>",
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Serif:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap">',
         "<style>", canonical_style(repo), BOARD_CSS, "</style>",
         '<div class="wrap">',
         '<a class="skip" href="#now">Skip to what to do now</a>',
         "<header><div>",
         f'<div class="eyebrow">Job Attractor · {esc(date)}</div>',
         "<h1>What to do now</h1>",
         '<p class="sub">In the order that reaches an offer soonest. Everything else is here, '
         "underneath.</p>",
         "</div></header>"]

    # ── the path: breadcrumb and the day's shape, one component ──
    L.append('<nav class="path-nav" aria-label="Pipeline position">')
    for key, label, count, buys, is_seat in path:
        cls = "step"
        if key == step_key:
            cls += " here"
        if is_seat:
            cls += " seat"
        if key == "offer":
            cls += " goal"
        here = ' <span class="mono">◀</span>' if key == step_key else ""
        L.append(f'<div class="{cls}"><div class="nm">{label}{here}</div>'
                 f'<div class="ct">{count}</div><div class="of">{buys}</div></div>')
    L.append("</nav>")
    L.append('<p class="legend">Greyed steps are the seats’ work, not yours. '
             "The marked step is where the next move is.</p>")

    # ── the active step, expanded ──
    lbl, buys = step_label.get(step_key, (step_key.title(), ""))
    rows = payload["rows"]
    L.append('<section id="now" class="now">')
    if step_key == "send":
        L.append(f"<h2>Send {len(rows)} staged note{'' if len(rows) == 1 else 's'}</h2>")
        L.append(f'<p class="why">This is the step that {esc(buys)}. Your hand presses send.</p>')
        for r in rows:
            L.append(f'<div class="row"><div class="co">{esc(r["company"])}</div>'
                     f'<div class="meta">staged today to {esc(r["to"])}</div></div>')
    elif step_key == "build":
        L.append(f"<h2>Build the note for {esc(rows[0]['head']['company'])}</h2>")
        L.append(f'<p class="why">This is the step that {esc(buys)}. '
                 f'{len(rows)} card{"" if len(rows) == 1 else "s"} ruled BUILD, highest mean first.</p>')
        L.append(card_row(rows[0], links, level))
        if len(rows) > 1:
            L.append('<div class="then">then: ' + " \u00b7 ".join(
                f'<b>{esc(c["head"]["company"])}</b> {c["head"]["mean"]}' for c in rows[1:6])
                + "</div>")
    elif step_key == "rule":
        L.append(f"<h2>Rule {len(rows)} card{'' if len(rows) == 1 else 's'}</h2>")
        L.append(f'<p class="why">This is the step that {esc(buys)}. '
                 "Highest panel mean first. Nothing is staged and nothing is ruled BUILD, so "
                 "this is the work nearest an offer today.</p>")
        L.append(card_row(rows[0], links, level))
        if len(rows) > 1:
            L.append('<div class="then">then: ' + " \u00b7 ".join(
                f'<b>{esc(c["head"]["company"])}</b> {c["head"]["mean"]}' for c in rows[1:6])
                + "</div>")
    elif step_key == "score":
        L.append(f"<h2>{len(rows)} carded companies still need a panel</h2>")
        L.append(f'<p class="why">This is the seats’ work, not yours. It is here so you can '
                 "see the queue behind your rulings, not so you can do it.</p>")
        L.append('<div class="meta">' + esc(", ".join(c["head"]["company"] or c["slug"]
                                                      for c in rows[:12])) + "</div>")
    else:
        L.append("<h2>Nothing is waiting on you</h2>")
        L.append('<p class="why">No note staged, no card ruled BUILD, nothing scored and unruled. '
                 "The feeders are the constraint.</p>")
    L.append("</section>")

    # hygiene: real, and deliberately not dressed up as a next action
    L.append('<div class="disclosures">')
    if payload["stale"]:
        st = payload["stale"]
        L.append('<details class="later"><summary>' + str(len(st))
                 + " stale draft" + ("" if len(st) == 1 else "s") + " in the send log</summary>")
        L.append('<div class="hygiene"><b>' + str(len(st)) + " older draft"
                 + ("" if len(st) == 1 else "s")
                 + " still marked drafted in the send log</b>, the oldest from "
                 + esc(min([x["date"] for x in st if x["date"]] or ["an unknown date"]))
                 + ". These are not counted as sends and are not offered as work: at least one "
                 "names a company the outreach queue records as sent, so the rows are stale "
                 "rather than pending. Worth a reconciliation pass. "
                 + esc(", ".join(x["company"] for x in st if x["company"])) + "</div></details>")

    # ── everything else, demoted but present ──
    L.append('<details class="later"><summary>Where the pipeline stands</summary>')
    L.append('<div class="strip">')
    L.append(f'<div class="stat"><b>Card floor</b><div class="v{"" if floor_now >= card_floor else " short"}">'
             f'{floor_now} of {card_floor}</div><div class="sub2">RADAR {n_radar} · BUILD {n_build}'
             f'{"" if floor_now >= card_floor else f" · short {card_floor - floor_now}"}</div></div>')
    L.append(f'<div class="stat"><b>Build floor</b><div class="v{"" if n_build >= build_floor else " short"}">'
             f'{n_build} of {build_floor}</div><div class="sub2">'
             f'{"held" if n_build >= build_floor else f"short {build_floor - n_build}"}</div></div>')
    rate = (lad["replied"] / lad["reached"] * 100) if lad["reached"] else 0
    excluded = ", ".join(f"{v} {k}" for k, v in sorted(lad["by_status"].items())
                         if k not in REACHED and k != "bounced")
    L.append(f'<div class="stat"><b>Ladder</b><div class="v">{lad["reached"]}</div>'
             f'<div class="sub2">reached a person · {lad["replied"]} replied · {rate:.1f}%'
             f'<br>{lad["bounced"]} bounced'
             + (f" · excluded: {esc(excluded)}" if excluded else "")
             + "</div></div>")
    if ht:
        mins = ht.get("minutes", {})
        tot = sum(mins.values())
        L.append(f'<div class="stat"><b>Hand time today</b><div class="v">{tot // 60}h {tot % 60}m</div>'
                 f'<div class="sub2">' + " · ".join(f"{k.replace('_', ' ')} {v}m" for k, v in mins.items() if v)
                 + f' · gap {ht.get("gap_minutes", 0)}m</div></div>')
    else:
        L.append('<div class="stat"><b>Hand time today</b><div class="v">—</div>'
                 '<div class="sub2">no samples yet</div></div>')
    L.append("</div>")
    if lad["by_domain"] or lad["note"]:
        L.append('<div class="sectorline">Sending domain: ')
        L.append(" · ".join(f"<b>{esc(d)}</b> {s} sent, {r} replied"
                                 for d, (s, r) in sorted(lad["by_domain"].items()))
                 or "no send carries a from-address yet")
        if lad["note"]:
            L.append(f' — {esc(lad["note"])}')
        L.append("</div>")
    if disagree:
        L.append('<div class="hygiene"><b>' + str(len(disagree))
                 + " card(s) disagree with the queue</b>, card token counted: "
                 + esc("; ".join(f"{s} card {a}, queue {b}" for s, a, b in sorted(disagree)[:6]))
                 + "</div>")
    L.append("</details>")

    seen, owed_rows = set(), []
    for s, c in sorted(cards.items()):
        if ruled.get(s) not in ("BUILD", "RADAR"):
            continue
        for line in c["owed"]:
            key = (s, line)
            if key in seen:
                continue
            seen.add(key)
            urls = URL_RE.findall(line)
            owed_rows.append((c["head"]["company"] or s, line, urls[0] if urls else None))
    L.append(f'<details class="later"><summary>Reads owed on BUILD and RADAR cards '
             f'— {len(owed_rows)}</summary>')
    if not owed_rows:
        L.append('<p class="empty">None outstanding.</p>')
    else:
        L.append('<ul class="owedlist">')
        for co, line, url in owed_rows:
            open_link = (f' <a href="{esc(url)}" target="_blank" rel="noopener">'
                         f'open the source for {esc(co)}</a>') if url else ""
            L.append(f"<li><b>{esc(co)}</b> — {esc(clean(line))}{open_link}</li>")
        L.append("</ul>")
    L.append("</details>")

    L.append('<details class="later"><summary>How to read this page</summary>')
    L.append('<p class="legend">Glyphs carry the state as well as the color: '
             '✓ pass, ! unproven or owed, ✕ fail, ○ unresolved. A gate whose section is '
             "absent, or whose wording the board cannot classify, reads UNRESOLVED and never PASS "
             "— silence is not clearance, and neither is prose nobody has read.</p>")
    L.append("<footer>Generated by scripts/board.py"
             + (f" for {esc(owner)}" if owner else "") + " from "
             "documents/state/*-card-*.md, documents/send-log.jsonl, "
             "documents/state/mac-time-summary.jsonl and the scorecard index. "
             f"Guidance level: {esc(level)}. "
             "Read-and-decide: this page never rules, never sends and never writes to a live store. "
             "The recommendation and the outside read stay in the picker, because no card slot feeds "
             "them and inventing them here would put words in a seat’s mouth.</footer>")
    L.append("</details>")
    L.append("</div>")   # .disclosures
    L.append("</div>")   # .wrap
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--out", default=None)
    ap.add_argument("--level", default=_cfg("GUIDANCE_LEVEL", "guided"),
                    choices=["diy", "guided", "full"],
                    help="how much the page does the thinking: diy shows everything and recommends nothing, guided names the next action, full also names what the seats will do "
                         "without asking. Deeper automation needs the write path.")
    ap.add_argument("--print", action="store_true", dest="only_print")
    a = ap.parse_args(argv)
    text = render(a.repo, a.date, a.level)
    if a.only_print:
        sys.stdout.write(text)
        return 0
    out = a.out or os.path.join(a.repo, "documents", "state", "board.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"board -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
