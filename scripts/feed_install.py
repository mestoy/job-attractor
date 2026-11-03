#!/usr/bin/env python3
"""feed_install.py: the readers that let the app's feed see a person's WHOLE install (slice 3, Task 2).

The feed build took its cards only from scorecards. A company the person queued but never scorecarded had no card, their warm network
gave no warm rung, a thread they already had read as a cold stranger, and nothing said what had been found. These readers wire in the
files the kit already writes: the queues, the warm network, the correspondence log, plus counts of the rest, so the first screen can
say what was found and the cards can say what is true about them.

Every reader degrades to an empty answer when its file is absent, and says so in `found`; none writes anything. Standard library
only. Names are matched on letters and digits alone, so "Example Widgets (FAKE)" in the queue and the scorecard agree.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board  # noqa: E402  the one rule for 'this row reached a person'

QUEUE = "documents/outreach-queue.md"
GREEN = "documents/green-board.md"
DISCOVERY = "documents/discovery-board.md"
CONTACTS = "documents/state/contact.jsonl"
CLOSENESS = "documents/contact-closeness.json"
WARM_MD = "documents/warm-network.md"
THREADS = "documents/correspondence-log.md"
EMPLOYERS = "documents/employers.jsonl"
PROFILE = "documents/PROFILE.md"
SEND_LOG = "documents/send-log.jsonl"
LEDGER = "documents/decision-ledger.jsonl"
STORE = "documents/state/app-store/store.jsonl"
SOURCES = (QUEUE, GREEN, DISCOVERY, CONTACTS, CLOSENESS, WARM_MD, THREADS, EMPLOYERS, PROFILE, SEND_LOG, LEDGER, STORE)

_TOKEN = re.compile(r"\b(SENT|PASS|DROPPED|DROP|PARK|BUILD|RADAR)\b")
DECIDED = ("BUILD", "RADAR", "PARK", "DROP", "SENT")


def name_key(s):
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def slug_of(name):
    """The same slug the queue reader in depth_report makes: parentheticals dropped, letters and digits joined by dashes."""
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"\(.*?\)", "", str(name or "")).lower()).strip("-")


def _read(repo, rel):
    try:
        with open(os.path.join(repo, rel), encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _jsonl(repo, rel):
    out = []
    for line in (_read(repo, rel) or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _board_names(text):
    """Company names on a board file: the first cell of a table row, or the bold name starting a bullet.

    Correct for green-board.md and discovery-board.md, whose own first column IS the company. NOT used for
    warm-network.md (see `_warm_names` below): that file's first column is a bare rank number, and taking
    cells[0] there reads "1", "2", "3" as if they were names (BUG-560)."""
    names = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            first = re.sub(r"[*_`]", "", cells[0]).strip() if cells else ""
            if not first or set(first) <= set("-: ") or first.lower() in ("company", "name", "companies"):
                continue
            names.append(first)
        else:
            m = re.match(r"^[-*]\s+\*\*(.+?)\*\*", s)
            if m:
                names.append(m.group(1).strip())
    return names


def _table_blocks(text):
    """[[[cell, ...], ...], ...] -- one list of rows per contiguous run of "|"-led lines, so a file
    with several independent tables (warm-network.md ships one per segment) reads each table's own
    header against its own rows, never a header from a different table above it."""
    blocks, cur = [], None
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cur is None:
                cur = []
                blocks.append(cur)
            cur.append(cells)
        else:
            cur = None
    return blocks


def _is_separator_row(cells):
    return all(not c or set(re.sub(r"[:\s]", "", c)) <= set("-") for c in cells)


def _name_column_index(header_cells):
    """The index of the header cell that reads "Name" (markup stripped, case-insensitive), or None."""
    for i, c in enumerate(header_cells):
        if re.sub(r"[*_`]", "", c).strip().lower() == "name":
            return i
    return None


def _warm_names(text):
    """Names from warm-network.md, read by its OWN column header -- never assumed to be the first
    cell. The real file's header is `| | Name | Title | Company | Known since | |`: an empty first
    column, with the data rows' first cell a bare rank number ("1", "2", "3", ...). `_board_names()`
    took that rank number as the name (BUG-560); every row then normalized to a number, which never
    matches a real boss name, so the warm rung silently never lit for an install using this fallback
    (contact.jsonl empty, warm-network.md the only source).

    Falls back to a bold bullet ("- **Name**") when the file carries no table with a Name column at
    all -- a simpler warm-network.md some partners may write by hand."""
    names = []
    for block in _table_blocks(text):
        if len(block) < 2:
            continue
        idx = _name_column_index(block[0])
        if idx is None:
            continue
        for row in block[1:]:
            if _is_separator_row(row) or idx >= len(row):
                continue
            cell = re.sub(r"[*_`]", "", row[idx]).strip()
            cell = re.sub(r"\s*(?:✅|✉)\s*$", "", cell).strip()   # a trailing verified/contacted mark, not part of the name
            if cell and cell.lower() not in ("company", "name", "companies"):
                names.append(cell)
    if names:
        return names
    for line in (text or "").splitlines():
        m = re.match(r"^[-*]\s+\*\*(.+?)\*\*", line.strip())
        if m:
            names.append(m.group(1).strip())
    return names


def read_added(repo):
    """[{company, boss, at}] for the companies the person added in the app (Add a company): the `board` rows of the app's own store,
    last row per id wins, a tombstoned id is gone. The same reader the fold uses; nothing is fetched and nothing is written."""
    path = os.path.join(repo, STORE)
    if not os.path.exists(path):
        return []
    import importlib.util
    spec = importlib.util.spec_from_file_location("feed_install_app_fold", os.path.join(HERE, "app_fold.py"))
    fold = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fold)
    rows, _skipped = fold.read_store(path)
    live, _tombs = fold.materialize(rows or [])
    out = []
    for doc in (live.get("board") or {}).values():
        if not isinstance(doc, dict) or not isinstance(doc.get("company"), str) or not doc["company"].strip():
            continue
        boss = doc.get("boss")
        out.append({"company": doc["company"].strip(), "boss": boss.strip() if isinstance(boss, str) and boss.strip() else "",
                    "at": str(doc.get("at") or "")})
    return sorted(out, key=lambda e: e["at"])


def blocked_list_state(repo):
    """"missing" | "unreadable" | "torn" | "empty" | "listed" for THIS install's blocked list (documents/blocked-employers-list.md).
    missing: no file. unreadable: the file is there and cannot be opened. torn: it holds binary bytes, so it is not a list at all.
    empty: it reads and names nobody (no bullet, no table row beyond the header and the template's example, and no blocked row in the
    registry): the normal state of a new install. listed: at least one company is named."""
    path = os.path.join(repo, "documents", "blocked-employers-list.md")
    if not os.path.exists(path):
        return "missing"
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return "unreadable"
    if b"\x00" in raw:
        return "torn"
    in_instructions = False
    for ln in raw.decode("utf-8", errors="ignore").splitlines():
        s = ln.strip()
        if s.startswith("#"):
            # The starter list explains itself in bullets under "How to use". Those are instructions, not companies.
            in_instructions = bool(re.search(r"how to use|instructions", s, re.I))
            continue
        if in_instructions:
            continue
        if s.startswith(("- ", "* ")):
            return "listed"
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            first = re.sub(r"[*_`]", "", cells[0]).strip() if cells else ""
            if first and not set(first) <= set("-: ") and first.lower() not in ("company", "name", "companies") and not first.startswith("[Example"):
                return "listed"
    return "listed" if blocked_count(repo) else "empty"


def blocked_verdict(repo, company):
    """("red" | "yellow" | "unresolved" | None, reason) for a company against THIS install's blocked list, by check_dup's own two precise checks
    (the canon key, then the bare token; Q29), run in a child process so it reads `repo`'s list and not this tree's. His rule: check the blocked
    list FIRST before surfacing any company. FAILS CLOSED: a child that raises, exits nonzero or times out is "unresolved", and so is a MISSING
    list (nothing to check against). A list that exists and names nobody is a valid empty list for a new install: clean."""
    import subprocess
    cannot = ("unresolved", "the blocked-list check could not run, so verify this company against documents/blocked-employers-list.md before any send")
    state = blocked_list_state(repo)
    if state == "missing":
        return "unresolved", "there is no blocked list to check against, so verify this company before any send"
    if state in ("unreadable", "torn"):
        return "unresolved", "the blocked list could not be read, so verify this company against documents/blocked-employers-list.md before any send"
    # "empty" is NOT a reason to skip the check: blocked_list_state is a classifier for doctor's notice only, and its parser can disagree with
    # check_dup's (R163 M1). Whenever the file exists and reads, check_dup decides; an empty list simply finds nothing and reads clean.
    code = ("import sys; sys.path.insert(0, %r); import check_dup; sys.stdout.write(check_dup.blocked_list_verdict(sys.argv[1]) or '')" % HERE)
    env = dict(os.environ, JOBSEARCH_DATA_ROOT=os.path.abspath(repo), CLAUDE_PROJECT_DIR=os.path.abspath(repo), JOBSEARCH_TEST="1")   # the registry and the sweep read CLAUDE_PROJECT_DIR; check_dup reads JOBSEARCH_DATA_ROOT
    try:
        r = subprocess.run([sys.executable, "-c", code, company], capture_output=True, text=True, env=env, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return cannot
    if r.returncode != 0:
        return cannot
    verdict = (r.stdout or "").strip()
    if verdict == "red":
        return "red", "on the blocked list (documents/blocked-employers-list.md)"
    if verdict == "yellow":
        return "yellow", "shares a word with a blocked company: verify it is a different company before any send"
    return None, ""


def prior_contact_verdict(repo, company, person=""):
    """("red" | "yellow" | "unresolved" | None, reason) for a company against THIS install's send log and contact stores, by check_dup's own
    prior_contact (the send gate's signal set), in a child process pointed at `repo`. red is a recorded contact, yellow a weaker mention (a
    staged, bounced or failed send, or prose), None is clean. FAILS CLOSED: a child that raises, exits nonzero, times out or prints nothing
    readable is "unresolved", never clean."""
    import subprocess
    code = ("import sys, json; sys.path.insert(0, %r); import check_dup; r = check_dup.prior_contact(sys.argv[1], sys.argv[2]); "
            "hits = (r['strong'] or r['weak'])[:1]; "
            "sys.stdout.write(json.dumps({'verdict': r['verdict'], 'store': hits[0]['store'] if hits else ''}))" % HERE)
    env = dict(os.environ, JOBSEARCH_DATA_ROOT=os.path.abspath(repo), CLAUDE_PROJECT_DIR=os.path.abspath(repo), JOBSEARCH_TEST="1")   # the registry and the sweep read CLAUDE_PROJECT_DIR; check_dup reads JOBSEARCH_DATA_ROOT
    cannot = ("unresolved", "the prior-contact check could not run, so verify against documents/send-log.jsonl that you have not written to them before any send")
    try:
        r = subprocess.run([sys.executable, "-c", code, company, person or ""], capture_output=True, text=True, env=env, timeout=60)
        if r.returncode != 0:
            return cannot
        got = json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return cannot
    where = got.get("store") or "your records"
    if got.get("verdict") == "red":
        return "red", "you already wrote to them (%s): no second touch on a cold boss" % where
    if got.get("verdict") == "yellow":
        return "yellow", "they are mentioned in %s but no delivered note is recorded: verify you have not written to them before any send" % where
    if got.get("verdict") == "clean":
        return None, ""
    return cannot


def screen_added(repo):
    """[{company, boss, at, blocked, prior}] for every company added in the app, each screened against THIS install (blocked list first,
    then prior contact) every time the feed builds, so a company blocked after it was added never reads clean (BUG-518). `blocked` and `prior`
    are (verdict, reason) pairs from blocked_verdict and prior_contact_verdict. A blocked (red) company skips the prior-contact check."""
    out = []
    for e in read_added(repo):
        blocked = blocked_verdict(repo, e["company"])
        prior = (None, "") if blocked[0] == "red" else prior_contact_verdict(repo, e["company"], e["boss"])
        out.append(dict(e, blocked=blocked, prior=prior))
    return out


def read_queue(repo, screened=None):
    """[{company, slug, stage, source}] in file order: the outreach queue first (its STATUS token is the stage), then the green board
    (BANKED) and the discovery board (DISCOVERED), then the companies added in the app (QUEUED, with the boss she typed). One entry per
    company, so a company already in a file is never doubled by an add."""
    out, seen = [], set()

    def add(company, stage, source, boss=""):
        slug, key = slug_of(company), name_key(re.sub(r"\(.*?\)", "", company))
        if not slug or key in seen:
            return
        seen.add(key)
        entry = {"company": company.strip(), "slug": slug, "stage": stage, "source": source}
        if boss:
            entry["boss"] = boss
        out.append(entry)

    text = _read(repo, QUEUE) or ""
    for block in re.split(r"(?m)^## ", text)[1:]:
        head = block.splitlines()[0] if block.splitlines() else ""
        parts = head.split("·")
        if len(parts) < 2 or not parts[1].strip():
            continue
        m = re.search(r"STATUS:\s*(.*)$", head)
        t = _TOKEN.search(m.group(1)) if m else None
        stage = ("DROP" if t.group(1) == "DROPPED" else t.group(1)) if t else "QUEUED"
        add(parts[1].strip(), stage, QUEUE)
    for rel, stage in ((GREEN, "BANKED"), (DISCOVERY, "DISCOVERED")):
        for name in _board_names(_read(repo, rel)):
            add(name, stage, rel)
    for added in (screen_added(repo) if screened is None else screened):
        if added["blocked"][0] == "red":
            continue          # his rule: check the blocked list FIRST. A blocked company is never carded; found.added_blocked says so.
        before = len(out)
        add(added["company"], "QUEUED", STORE, added["boss"])
        if len(out) > before:
            out[-1]["screen"] = {"blocked": added["blocked"], "prior": added["prior"]}
    return out


def _closeness_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("feed_install_closeness", os.path.join(HERE, "closeness.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_warm(repo):
    """{"names": {normalized name: display}, "tiers": {normalized name: stated closeness or None}}. The network is the contact rows
    (kind contact); a repo with none falls back to warm-network.md's own Name column (BUG-560: NOT the first cell -- the real
    file's first column is a bare rank number, which `_board_names()` was built for a different file shape and reads it as the name)."""
    cl = _closeness_module()
    names = {}
    for row in _jsonl(repo, CONTACTS):
        if row.get("kind") != "contact":
            continue
        n = (row.get("payload") or {}).get("name")
        if n and cl.normalize_name(n):
            names[cl.normalize_name(n)] = n
    if not names:
        for n in _warm_names(_read(repo, WARM_MD)):
            if cl.normalize_name(n):
                names[cl.normalize_name(n)] = n
    store = cl.load(os.path.join(repo, CLOSENESS)) or {}
    tiers = {k: ((store.get(k) or {}).get("closeness") or None) for k in names}
    rows = {k: store.get(k) for k in names}
    return {"names": names, "tiers": tiers, "rows": rows, "normalize": cl.normalize_name,
            "sanctioned": cl.warm_sanctioned}


def read_threads(repo):
    """The dated thread headers of the correspondence log: [header line]. A thread is a `##` or `###` block that starts with a date."""
    out = []
    for line in (_read(repo, THREADS) or "").splitlines():
        m = re.match(r"^#{2,3}\s+(\d{4}-\d{2}-\d{2}\b.*)$", line)
        if m:
            out.append(m.group(1))
    return out


def blocked_count(repo):
    return sum(1 for r in _jsonl(repo, EMPLOYERS) if r.get("status") == "blocked")


def annotate(cards, queue, warm, threads, today=None):
    """Set stage, rung, closeness and thread on every card, in place. stage is the queue's token for the company, else None.

    rung is "warm" ONLY when the boss is a contact AND closeness.warm_sanctioned says the store sanctions a warm ask (BUG-600): a boss
    who is merely a connection is cold, as the CLI's WARM-RUNG consult already treats them. `today` pins the clock for thread_state."""
    stage_of = {}
    for q in queue:
        stage_of[q["slug"]] = q["stage"]
        stage_of[name_key(re.sub(r"\(.*?\)", "", q["company"]))] = q["stage"]
    thread_keys = [name_key(h) for h in threads]
    for c in cards:
        c["stage"] = stage_of.get(c.get("slug")) or stage_of.get(name_key(re.sub(r"\(.*?\)", "", c.get("company") or "")))
        boss = c.get("boss") if isinstance(c.get("boss"), dict) else {}
        key = warm["normalize"](boss.get("name")) if boss.get("name") else ""
        if key and key in warm["names"]:
            sanctioned = warm.get("sanctioned") or _closeness_module().warm_sanctioned     # a hand-built warm dict in the old shape has none
            ok = sanctioned((warm.get("rows") or {}).get(key), today=today)
            c["rung"], c["closeness"] = ("warm" if ok else None), warm["tiers"].get(key)
        else:
            c["rung"], c["closeness"] = None, None
        ck = name_key(re.sub(r"\(.*?\)", "", c.get("company") or ""))
        c["thread"] = bool(len(ck) >= 3 and any(ck in t for t in thread_keys))
    return cards


# A "sent note" is a row that reached a person, by the kit's ONE rule for that (board.counts_as_send, the rule rung_ladder imports):
# sent and replied count; staged, drafted, bounced, blocked, failed, discarded, inbound rows, ATS applications and unknown statuses do not.
# Two counters disagreeing about what a send is would be a real defect, so this file keeps no list of its own.
def sent_count(send_rows):
    return sum(1 for r in send_rows if isinstance(r, dict) and board.counts_as_send(r))


def send_log_unread(repo, send_rows):
    """Non-blank send-log lines that did not become a row: a torn or hand-edited line. The receipt says so instead of hiding it."""
    lines = sum(1 for line in (_read(repo, SEND_LOG) or "").splitlines() if line.strip())
    return max(0, lines - len(send_rows))


def found_block(repo, send_rows, cards_count, queue, warm, threads, rulings, added_blocked=None):
    files = sorted(rel for rel in SOURCES if os.path.exists(os.path.join(repo, rel)))
    block = {"send_log": len(send_rows), "sent": sent_count(send_rows),
             "send_log_unread": send_log_unread(repo, send_rows),
             "folder": os.path.abspath(repo),
             "replies": sum(1 for r in send_rows if r.get("replied") is True),
             "rulings": rulings, "cards": cards_count, "queued": len(queue),
             "warm": len(warm["names"]), "threads": len(threads), "blocked": blocked_count(repo), "files": files,
             "added_blocked": list(added_blocked or [])}
    return block


def is_empty(block):
    return all(block[k] == 0 for k in ("send_log", "replies", "rulings", "cards", "queued", "warm", "threads", "blocked"))
