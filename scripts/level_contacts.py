#!/usr/bin/env python3
"""level_contacts.py — create and fill the closeness store: the levelling interview's engine.

WHY THIS EXISTS. The kit ships a closeness-DEPENDENT pipeline: the warm rungs (5/6/7) of the
boss-hunt ladder need a real relationship, and `check_preview.py` refuses a warm-shaped ask the
store does not sanction. But nothing in the kit CREATED that store — `parse_messages.py` and
`sync_contacted.py` both write into it and neither can produce it. This script owns the store's
whole life cycle: creation, the machine inference pass, the human batch interview, and targeted
one-name levelling when a refusal blocks a send.

THE DIVISION OF LABOUR, and it is strict:
  * The MACHINE infers from message counts, marks its own guesses as such
    (`source=inferred-from-messages`), and marks the ones it doubts (AMBIGUOUS, in the evidence
    text where `closeness.uncertainty()` reads it).
  * The HUMAN states levels, once, and a stated answer is NEVER overwritten by inference —
    enforced in code below (`_may_infer_over`), keyed on the NEGATIVE space: any source the
    machine pass did not write is a human answer, whatever it is spelled.
  * NOBODY mass-defaults. A contact never swept stays ABSENT, which downstream reads as
    "closeness UNRECORDED — ask" rather than as an answer nobody gave.

INFERENCE RULES (counts only — pinned upstream 2026-07-27):
  "both ways" means he_sent >= 1 AND they_sent >= 1.
  * real conversation:  total >= 6, both ways          -> know-well (INFERRED, scores thin
                                                          until confirmed: volume is not intimacy)
  * brief exchange:     2 <= total <= 5, both ways     -> never-spoke + AMBIGUOUS marker
                                                          (the re-ask queue)
  * outbound-only / inbound-only                       -> never-spoke (your own outreach, or an
                                                          unanswered inbound, is not a relationship)
HONEST LIMIT: this pass sees COUNTS, not content. A logistics thread (an event organiser sending
six Zoom links both ways) can auto-level know-well. That is accepted by ruling: the inferred tier
scores THIN, `uncertainty()` and the confirm pass are the backstop, and a stated answer fixes it
permanently in one line.

RESUMABLE BY CONSTRUCTION. Every recorded (human-stated) answer is excluded from every future
batch. A re-run processes only: contacts ABSENT from the store, `known-level-tbd` parkings, and
rows the store doubts (AMBIGUOUS / contradicted). Stop any time; the next run continues exactly
where you left off.

Merge-only writes, `.bak` first (same contract as parse_messages.py). Stdlib only.

Usage:
  scripts/level_contacts.py --status                   # coverage: what is levelled, what waits
  scripts/level_contacts.py --infer [--dry-run]        # machine pass from message counts
  scripts/level_contacts.py --batch [SIZE]             # next interview batch (default 12), oldest first
  scripts/level_contacts.py --record "Name=tier" [...] # record stated answers (immediate write)
  scripts/level_contacts.py --name "Contact Name"      # one-contact mode: state + exact fix command

Exit: 0 = ok · 2 = missing input (no export / no store where one is needed) · 3 = usage
"""
import contextlib
import csv
import datetime
import functools
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
STORE = os.path.join(REPO, "documents", "contact-closeness.json")
BACKUP = STORE + ".bak"

sys.path.insert(0, HERE)
import closeness  # the twin: one tier table, every consumer  # noqa: E402

BATCH_SIZE_DEFAULT = 12

# Tiers a HUMAN may state. `know-well` is deliberately absent: it is the inference pass's tier,
# and a human answer lands in one of these named levels instead. `never-spoke` is a real answer
# ("none of these" / unticked), and `known-level-tbd` is the parking state for "I know them, ask
# me the level later".
STATED_TIERS = ("worked-together", "know-not-close", "personal-friend", "classmate",
                "shared-community", "best-friend-lapsed", "never-spoke", "known-level-tbd")

# Self-documenting seed. The store explains its own vocabulary, its inference rules and its picker
# semantics, so a reader opening the raw JSON — or an assistant resuming a sweep months later —
# needs no other document to interpret or extend it correctly.
_SEED = {
    "_README": (
        "Relationship closeness, stated by YOU (the kit owner). ASK ONCE, REUSE FOREVER. "
        "This is the field the boss-hunt ladder actually runs on: rungs 5/6/7 need a real "
        "relationship, rungs 1/2 do not, and a connection date CANNOT tell the two apart. "
        "Created and maintained by scripts/level_contacts.py (/level-network); read by "
        "scripts/closeness.py for every consumer. If a person is absent here, nobody asked yet — "
        "run: python3 scripts/level_contacts.py --name \"Their Name\""),
    "_scale": {
        "worked-together":    "Real shared work history. Full warm ask available, rung 5/6/7.",
        "know-not-close":     "Friendly but thin. Warm rung, REDUCED ask that earns the request — never hire-me.",
        "personal-friend":    "A friend outside work. Real relationship; confirm the ask shape first.",
        "classmate":          "Knew them at school — a real relationship and a legitimate warm rung.",
        "shared-community":   "Shared community/school/group identity. Warm OPENER (rung 10), not a rung 5-7 ask.",
        "best-friend-lapsed": "Close friend gone quiet. Reunion with NO ask first; outreach later, separately.",
        "never-spoke":        "Connection with no history. NOT a warm rung. Rung 1/2, zero-ask hello.",
        "known-level-tbd":    "You confirmed you know them; the LEVEL is not yet asked. Ask before building.",
        "know-well":          "INFERENCE-ONLY tier, levelled from message evidence (6+ msgs both ways). "
                              "Scores thin until you confirm the person — volume is not intimacy.",
    },
    "_INFERENCE_RULES": (
        "Machine pass (level_contacts.py --infer), counts only; STATED answers are NEVER "
        "overwritten. 'Both ways' = at least 1 message in each direction. Rules: real "
        "conversation (6+ msgs both ways) -> know-well, source=inferred-from-messages · brief "
        "exchange (2-5 msgs both ways) -> never-spoke, flagged AMBIGUOUS in evidence (the re-ask "
        "queue) · outbound-only or inbound-only -> never-spoke. Limitation, accepted: counts "
        "cannot tell a logistics thread from a conversation; inferred tiers score thin and the "
        "confirm pass is the backstop."),
    "_PICKER_SEMANTIC": (
        "On a tick-who-you-know batch, an EMPTY answer means NONE OF THEM — record never-spoke "
        "for the whole batch and keep going. It never means 'skipped' or 'stepped away'. Every "
        "batch also carries an explicit 'none of these' option so the empty answer is a choice, "
        "not an accident."),
}


# ── store I/O ────────────────────────────────────────────────────────────────────────────────
def load_raw():
    """The raw store dict, or None when the file is absent. Distinct on purpose (see closeness.load)."""
    try:
        with open(STORE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def ensure_store():
    """Create the store, seeded with its own documentation, ONLY when absent.

    Never touches an existing file: creation must not clobber curated fields, and the seeding is
    additive metadata only. The operator's documents/ belongs to the operator."""
    data = load_raw()
    if data is not None:
        return data, False
    data = dict(_SEED)
    data["_updated"] = datetime.date.today().isoformat()
    data["contacts"] = {}
    _write(data, fresh=True)
    return data, True


LOCK = STORE + ".lock"


@contextlib.contextmanager
def _store_lock():
    """Serialize the read-modify-write of contact-closeness.json ACROSS PROCESSES (BUG-221, kit port).

    ⛔ WHY. The store is a WHOLE-FILE json dict: load_raw/ensure_store read it, _write rewrites it,
    and the mutation lives in the caller between those two. Two writers racing that read→write span
    silently lose one update (last writer wins) — a real hazard the moment a second session, or the
    auto-fired new-contact sweep -> infer, writes at the same time as the live interview. An
    exclusive flock held across the whole span (via the @_under_store_lock decorator on the two
    mutating entry points) makes the writers take turns. This mirrors the workspace fix (BUG-221) so
    the kit's interview writer — the MOST FREQUENT writer of this file — locks against the same LOCK
    path parse_messages and sync_contacted already share, rather than clobbering a concurrent write.

    Degrades to a NO-OP lock if fcntl is unavailable (non-unix); the atomic _write below still
    prevents truncation/corruption there, only cross-process ordering is lost. Non-reentrant on
    purpose: the two decorated entry points (infer, record) never call each other, and ensure_store
    (which they call) is NOT decorated, so a single process never double-acquires and deadlocks.
    """
    try:
        import fcntl
    except Exception:
        yield
        return
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    fh = open(LOCK, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def _under_store_lock(fn):
    """Run `fn` holding the exclusive store lock, so its load→mutate→write span cannot interleave
    with another writer's. Applied to the two entry points that rewrite the whole store."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with _store_lock():
            return fn(*args, **kwargs)
    return wrapped


def _write(data, fresh=False):
    """Write the store ATOMICALLY (tmp + os.replace), `.bak` first (BUG-221, kit port).

    ⛔ The old form was `json.dump(data, open(STORE, "w"))` — a direct truncate-then-write, so a
    crash or a concurrent reader mid-dump saw a truncated/half-written store, and the `.bak` was
    written the same non-atomic way. Now every file swap is tmp+os.replace, which is atomic on POSIX:
    a reader sees either the whole old file or the whole new one, never a torn one. Serialization of
    the read-modify-write across processes is the caller's job, via @_under_store_lock."""
    data["_updated"] = datetime.date.today().isoformat()
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    if not fresh and os.path.exists(STORE):
        try:
            with open(STORE, encoding="utf-8") as src:
                cur = src.read()
            tmpbak = BACKUP + ".tmp"
            with open(tmpbak, "w", encoding="utf-8") as bf:
                bf.write(cur)
            os.replace(tmpbak, BACKUP)
        except Exception:
            pass
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, STORE)


def _index(contacts):
    """{normalized name: display key} so lookups survive credential tails and nicknames."""
    return {closeness.normalize_name(k): k for k in contacts}


# ── the export: the contact universe and its dates ───────────────────────────────────────────
def export_contacts():
    """[(display name, company, position, connected_date)] from the newest export on disk.

    Reuses parse_network's resolver (repo linkedin-exports/ first-class, then Downloads/Desktop),
    so the universe is the same one every other kit surface reads. [] when no export exists."""
    try:
        from parse_network import find_export, parse_rows, connected_on
    except Exception:
        return []
    try:
        path, text = find_export()
        if not text:
            return []
    except Exception:
        return []
    out = []
    for r in parse_rows(text):
        name = f"{(r.get('First Name') or '').strip()} {(r.get('Last Name') or '').strip()}".strip()
        if not name:
            continue
        out.append((name, (r.get("Company") or "").strip(), (r.get("Position") or "").strip(),
                    connected_on(r.get("Connected On"))))
    return out


def _message_counts():
    """{contact name: {total, he_sent, they_sent}} via parse_messages, or {} when none found."""
    try:
        import parse_messages
        _path, rows = parse_messages.find_messages()
        if not rows:
            rows = _raw_messages_rows()
        if not rows:
            return {}
        counts, _owner = parse_messages.tally(rows)
        return counts
    except Exception:
        return {}


def _raw_messages_rows():
    """messages.csv from a raw export still sitting in Downloads/Desktop (folder or .zip).

    WHY THIS FALLBACK EXISTS — found in the fresh-install rehearsal, not in review. The documented
    flow is ingest THEN infer. But ingest copies only Connections into the repo (emails stripped),
    and the repo copy then OUTRANKS the raw export, so parse_messages.find_messages() — which looks
    for messages.csv BESIDE the newest Connections source — looks in the repo, where message
    content deliberately never lives. Result: the machine pass came back silently empty right
    after the flow ran exactly as documented. So when the beside-the-newest lookup finds nothing,
    read the raw source directly. Message content is only ever READ here; it is never copied into
    the repo."""
    import zipfile
    home = os.path.expanduser("~")
    cands = []
    for pat in ("Downloads/*LinkedInDataExport*/messages.csv",
                "Desktop/*LinkedInDataExport*/messages.csv",
                "Downloads/messages.csv"):
        for p in glob.glob(os.path.join(home, pat)):
            try:
                cands.append((os.path.getmtime(p), p, None))
            except OSError:
                continue
    for pat in ("Downloads/*LinkedIn*Export*.zip", "Desktop/*LinkedIn*Export*.zip"):
        for z in glob.glob(os.path.join(home, pat)):
            try:
                with zipfile.ZipFile(z) as zf:
                    for n in zf.namelist():
                        if n.rsplit("/", 1)[-1] == "messages.csv":
                            cands.append((os.path.getmtime(z), z, n))
            except Exception:
                continue
    if not cands:
        return []
    _mt, path, member = max(cands, key=lambda c: c[0])
    try:
        if member:
            with zipfile.ZipFile(path) as zf:
                raw = zf.read(member).decode("utf-8-sig", "ignore")
            return list(csv.DictReader(io.StringIO(raw)))
        with open(path, encoding="utf-8-sig", errors="ignore") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


# ── the EVIDENCE the picker owes the reader (BUG-160, 2026-08-11) ───────────────────────────
# 🎯 A QUESTION YOU HAVE NOT GIVEN THE READER THE MEANS TO ANSWER IS NOT A QUESTION.
# `--batch` used to mark a row "store flags a two-way thread against this tag" and then print only
# name, title, company and connect date. The thread that CAUSED the doubt was never shown. Twelve
# rows at a time with no way to tell a recruiter blast from a real conversation, the rational
# answer to every row is "no", and on 2026-08-11 that is exactly what happened: 72 rows recorded
# never-spoke in six rounds, including one contact who had written *"I popped our chat and your
# profile after seeing your post regarding some PM positions that will be opening up soon. Very
# interested."* The OWNER was the one with the job, so the goodwill ran in that contact's
# direction, and the interview filed them as a stranger.
#
# ⛔ The failure mode is the dangerous one: it does not error, it produces a false negative wearing
# the costume of diligence. The row leaves the queue, gains source=stated-by-owner, and is never
# asked again, so a wrong answer hardens into an owner-stated one.

# Openers and sign-offs that carry no relationship information. Matched against the WHOLE message,
# so a long note that merely begins "Thanks" is still surfaced.
_PLEASANTRY = re.compile(
    r"^(thanks?|thank you|glad to connect|wonderful|see you( later)?|you.re welcome|sure|ok(ay)?|"
    r"great|nice to (meet|connect)( you)?|likewise|absolutely|of course|no problem|hi|hello|hey|"
    r"congrats|congratulations|welcome|cheers|same here|will do|sounds good)"
    r"[\s!.,:;\-\u2019'\w]{0,24}$", re.I)


def _inbound_evidence():
    """{contact name: (date, strongest inbound line)} — what THEY wrote to him, longest first.

    Only their side is considered. What the owner sent proves they had the address, never that a
    relationship exists; a thread is two-way or it is a broadcast they answered.
    """
    try:
        import parse_messages
        _path, rows = parse_messages.find_messages()
        if not rows:
            rows = _raw_messages_rows()
        if not rows:
            return {}
        owner = parse_messages._owner_names(rows)
    except Exception:
        return {}
    best = {}
    for r in rows:
        try:
            if (r.get("IS MESSAGE DRAFT") or "").strip().lower() in ("true", "yes", "1"):
                continue
            frm = (r.get("FROM") or "").strip()
            if not frm or frm == owner:
                continue                      # his own words are not evidence of THEIR interest
            body = " ".join((r.get("CONTENT") or "").split())
            if not body or _PLEASANTRY.match(body):
                continue
            when = (r.get("DATE") or "")[:10]
            prev = best.get(frm)
            if prev is None or len(body) > len(prev[1]):
                best[frm] = (when, body)
        except Exception:
            continue
    return best


def _groups_for(name):
    """[groups] · [] checked-and-none · None not-checked. Degrades to None when the store is absent."""
    try:
        sys.path.insert(0, HERE)
        import mutual_groups
        return mutual_groups.groups_for(name)
    except Exception:
        return None


def _evidence_for(name, evidence):
    """Match a store/export name against the messages.csv sender spelling."""
    if not evidence:
        return None
    hit = evidence.get(name)
    if hit:
        return hit
    want = closeness.normalize_name(name)
    for sender, val in evidence.items():
        if closeness.normalize_name(sender) == want:
            return val
    return None


def why_name(name):
    """--why <name>: dump their whole side of the thread, for one contact, on demand."""
    hit = _evidence_for(name, _inbound_evidence())
    print(f"contact: {name}")
    if not hit:
        print("  no substantive inbound message found — nothing they wrote survives the "
              "pleasantry filter, so the thread is not evidence of a relationship.")
        return 0
    when, body = hit
    print(f"  strongest inbound [{when}]:\n    {body}")
    return 0


# ── the machine pass ─────────────────────────────────────────────────────────────────────────
def _may_infer_over(row):
    """May the machine pass set closeness on this row? NEGATIVE-space rule, never spelling:
    a row with no closeness is fair game; a row whose source is one the machine pass itself wrote
    (INFERRED_SOURCES) is fair game; anything else is a HUMAN answer and is untouchable."""
    if row.get("closeness") in (None, ""):
        return True
    return str(row.get("source") or "") in closeness.INFERRED_SOURCES


def _infer_tier(m):
    """(tier, evidence) per the pinned count rules, or (None, None) when counts say nothing."""
    total, he, they = m.get("total", 0), m.get("he_sent", 0), m.get("they_sent", 0)
    both = he >= 1 and they >= 1
    if both and total >= 6:
        return "know-well", f"real conversation: {total} msgs ({he} sent / {they} received)"
    if both and 2 <= total <= 5:
        return "never-spoke", (f"brief exchange: {total} msgs ({he}/{they}) — AMBIGUOUS, could be "
                               f"connect-and-pleasantries; confirm")
    if he >= 1 and they == 0:
        return "never-spoke", f"outbound only ({total} msgs) — your own outreach, not a relationship"
    if they >= 1 and he == 0:
        return "never-spoke", f"inbound only ({total} msgs) — they wrote, no reply"
    return None, None


@_under_store_lock
def infer(write=True):
    """The machine pass. Creates/updates INFERRED rows; never touches a human answer.

    Also writes the ⚠️CONTRADICTS marker when a NEWER export shows a two-way thread against a
    STATED never-spoke — the tag is not changed (the human said it), but the doubt is recorded
    where `closeness.uncertainty()` reads it, so the contact re-enters the levelling queue."""
    data, _created = ensure_store()
    contacts = data.setdefault("contacts", {})
    idx = _index(contacts)
    export = export_contacts()
    export_names = {closeness.normalize_name(n): n for n, _c, _p, _d in export}
    counts = _message_counts()

    stats = {"levelled": 0, "ambiguous": 0, "never": 0, "contradicts": 0,
             "stated_kept": 0, "unmatched": 0, "counts_updated": 0}
    for raw_name, m in counts.items():
        norm = closeness.normalize_name(raw_name)
        key = idx.get(norm)
        if key is None:
            if norm not in export_names:
                stats["unmatched"] += 1     # left the network / name variant: never invent a row
                continue
            key = export_names[norm]
            contacts[key] = {}
            idx[norm] = key
        row = contacts[key]
        if row.get("messages") != m:
            row["messages"] = m
            stats["counts_updated"] += 1
        tier, evidence = _infer_tier(m)
        if tier is None:
            continue
        if not _may_infer_over(row):
            stats["stated_kept"] += 1
            # The stated answer stands — but a two-way thread against a stated never-spoke is a
            # doubt worth recording, in the exact shape uncertainty() detects.
            if (row.get("closeness") == "never-spoke"
                    and m.get("he_sent", 0) >= 1 and m.get("they_sent", 0) >= 1):
                marker = (f"Tagged never-spoke but a TWO-WAY thread exists "
                          f"({m.get('total', 0)} msgs). Re-check before trusting the tag.")
                if row.get("⚠️CONTRADICTS") != marker:
                    row["⚠️CONTRADICTS"] = marker
                    stats["contradicts"] += 1
            continue
        row["closeness"] = tier
        row["source"] = closeness.INFERRED_SOURCES[0]
        row["evidence"] = evidence
        if tier == "know-well":
            stats["levelled"] += 1
        elif "AMBIGUOUS" in evidence:
            stats["ambiguous"] += 1
        else:
            stats["never"] += 1

    if write:
        # Sweep stamp: which export this pass last saw. SURFACED numbers are always recomputed
        # live from the two sources; the stamp is a convenience, never the authority.
        try:
            from parse_network import find_export
            path, _ = find_export()
            if path:
                data["_last_swept_export"] = os.path.basename(str(path).split("::")[0])
        except Exception:
            pass
        _write(data)
    return stats


# ── the human pass ───────────────────────────────────────────────────────────────────────────
def pending(data=None):
    """The interview's work list: (name, company, position, connected, why), oldest connection
    first. Absent rows, known-level-tbd parkings, and store-doubted rows; NEVER a stated answer,
    NEVER a held contact. This is what makes every run resume where the last one stopped."""
    data = data if data is not None else (load_raw() or {"contacts": {}})
    contacts = data.get("contacts", {})
    idx = _index(contacts)
    out = []
    for name, co, pos, conn in export_contacts():
        row = contacts.get(idx.get(closeness.normalize_name(name), ""), None)
        if row is None or not row.get("closeness"):
            why = "unswept — never asked"
        elif closeness.is_held(row):
            continue
        elif row.get("closeness") == "known-level-tbd":
            why = "known — level not yet asked"
        else:
            doubt = closeness.uncertainty(row)
            if doubt and str(row.get("source") or "") in closeness.INFERRED_SOURCES:
                why = doubt
            elif row.get("⚠️CONTRADICTS"):
                why = "store flags a two-way thread against this tag — level it"
            else:
                continue    # a recorded answer is never re-asked
        out.append((name, co, pos, conn, why))
    out.sort(key=lambda r: (r[3] is None, r[3] or datetime.date.max, r[0]))
    return out


@_under_store_lock
def record(pairs):
    """Record stated answers. Immediate write, `.bak` first. Returns (n_recorded, errors).

    A stated answer resolves every machine doubt about the row: the ⚠️CONTRADICTS marker is
    dropped and the evidence is replaced with the statement's provenance — otherwise a leftover
    'ambiguous' in old evidence text would keep a HUMAN answer in the doubt queue forever."""
    data, _created = ensure_store()
    contacts = data.setdefault("contacts", {})
    idx = _index(contacts)
    export_names = {closeness.normalize_name(n): n for n, _c, _p, _d in export_contacts()}
    today = datetime.date.today().isoformat()
    n, errors = 0, []
    for pair in pairs:
        if "=" not in pair:
            errors.append(f"not Name=tier: {pair!r}")
            continue
        name, tier = (s.strip() for s in pair.split("=", 1))
        tier = closeness.TIER_ALIASES.get(tier, tier)
        if tier not in STATED_TIERS:
            errors.append(f"{name}: unknown tier {tier!r} (one of: {', '.join(STATED_TIERS)})")
            continue
        norm = closeness.normalize_name(name)
        key = idx.get(norm) or export_names.get(norm) or name
        row = contacts.setdefault(key, {})
        idx[norm] = key
        row["closeness"] = tier
        row["source"] = closeness.STATED_SOURCE
        row["evidence"] = f"levelled by the owner {today}"
        row.pop("⚠️CONTRADICTS", None)
        n += 1
    if n:
        _write(data)
    return n, errors


# ── reporting ────────────────────────────────────────────────────────────────────────────────
def status():
    data = load_raw()
    export = export_contacts()
    print(f"export contacts on disk: {len(export)}"
          + ("" if export else "   (no export found — download one from LinkedIn first)"))
    if data is None:
        print("closeness store: ABSENT — run /level-network to create and fill it")
        return 2 if not export else 0
    contacts = data.get("contacts", {})
    stated = sum(1 for r in contacts.values()
                 if r.get("closeness") and str(r.get("source") or "") not in closeness.INFERRED_SOURCES)
    inferred = sum(1 for r in contacts.values()
                   if str(r.get("source") or "") in closeness.INFERRED_SOURCES)
    todo = pending(data)
    doubted = sum(1 for *_x, why in todo if "unswept" not in why)
    print(f"closeness store: {len(contacts)} rows · {stated} stated by you · {inferred} inferred "
          f"from messages")
    print(f"levelling queue: {len(todo)} to go ({len(todo) - doubted} unswept · {doubted} "
          f"doubted/parked)")
    if data.get("_last_swept_export"):
        print(f"last swept export: {data['_last_swept_export']}")
    print("next: python3 scripts/level_contacts.py --batch    (or /level-network in Claude Code)")
    return 0


def show_name(name):
    """One-contact mode: the 30-second interview a check_preview refusal points at."""
    data = load_raw() or {"contacts": {}}
    contacts = data.get("contacts", {})
    row = contacts.get(_index(contacts).get(closeness.normalize_name(name), ""), None)
    print(f"contact: {name}")
    if row is None:
        print("  closeness: ABSENT — nobody asked yet. A warm rung is NOT sanctioned until levelled.")
    else:
        print(f"  closeness: {row.get('closeness') or 'unset'}   "
              f"source: {row.get('source') or '-'}")
        m = row.get("messages") or {}
        if m:
            print(f"  messages: {m.get('total', 0)} total "
                  f"({m.get('he_sent', 0)} sent / {m.get('they_sent', 0)} received)")
        held = closeness.is_held(row)
        if held:
            print(f"  ⛔ HELD: {held}")
        doubt = closeness.uncertainty(row)
        if doubt:
            print(f"  ⚠️ {doubt}")
    print("\n  the scale:")
    for tier in STATED_TIERS:
        desc = _SEED["_scale"].get(tier, "")
        print(f"    {tier:20s} {desc}")
    print(f'\n  record it: python3 scripts/level_contacts.py --record "{name}=<tier>"')
    return 0


def batch(size):
    todo = pending()
    if not todo:
        print("✅ nothing to level — every export contact has a recorded answer or is held.")
        return 0
    print(f"levelling queue: {len(todo)} remaining. Next batch of {min(size, len(todo))} "
          f"(oldest connection first):\n")
    evidence = _inbound_evidence()
    for i, (name, co, pos, conn, why) in enumerate(todo[:size], 1):
        when = conn.isoformat() if conn else "????-??-??"
        line = f"  {i:2}. {name:<26} {(pos or '')[:28]:<28} @ {(co or '-')[:22]:<22} {when}"
        print(line + (f"   [{why}]" if "unswept" not in why else ""))
        # BUG-160: a doubted row MUST carry the thread that caused the doubt, or the question
        # cannot be answered and every batch quietly returns never-spoke.
        if "unswept" not in why:
            hit = _evidence_for(name, evidence)
            if hit:
                mdate, body = hit
                print(f'        💬 [{mdate}] them: "{body[:240]}'
                      f'{"…" if len(body) > 240 else ""}"')
            else:
                print("        💬 nothing substantive from them — pleasantries only")
        # 👥 SHARED GROUPS, the second evidence lane (2026-08-11). A group is the most
        # machine-readable form of `shared-community` there is, and that tier opens rung 7
        # ([[shared-community-opens-rung-7]]). It shows on EVERY row, not only doubted ones,
        # because a group can level someone the message lane knows nothing about: upstream, a
        # contact with NO message history at all was moved from cold to warm 7 by one shared group.
        # ⛔ THREE STATES, NEVER TWO. "not checked" is not "none": the source is behind a login,
        # so an unchecked profile and an empty one are opposite findings and the line says which.
        gset = _groups_for(name)
        if gset:
            print(f"        👥 shares: {'; '.join(gset)}")
        elif gset is None:
            print("        👥 groups not checked — scripts/mutual_groups.py --queue")
    print("\n  picker semantics (verbatim, non-negotiable):")
    print("  • every batch carries an explicit 'none of these' option")
    print("  • an EMPTY answer records never-spoke for the WHOLE batch — it never means 'skipped'")
    print("  • ticked names get a short second pass for the LEVEL; park with known-level-tbd")
    print('  record: python3 scripts/level_contacts.py --record "Name=tier" ["Name=tier" ...]')
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__.split("Usage:")[1].split("Exit:")[0].strip())
        return 3
    if "--status" in args:
        return status()
    if "--infer" in args:
        dry = "--dry-run" in args
        st = infer(write=not dry)
        verb = "(dry-run) would level" if dry else "levelled"
        print(f"{verb}: {st['levelled']} know-well (thin until confirmed) · "
              f"{st['ambiguous']} ambiguous brief exchanges · {st['never']} never-spoke")
        print(f"stated answers kept untouched: {st['stated_kept']} "
              f"({st['contradicts']} gained a ⚠️CONTRADICTS re-check marker)")
        print(f"message counts updated on {st['counts_updated']} row(s); "
              f"{st['unmatched']} message contact(s) not in the export — no row invented")
        return 0
    if "--batch" in args:
        i = args.index("--batch")
        size = BATCH_SIZE_DEFAULT
        if i + 1 < len(args) and args[i + 1].isdigit():
            size = int(args[i + 1])
        return batch(size)
    if "--record" in args:
        pairs = [a for a in args if a != "--record" and not a.startswith("--")]
        if not pairs:
            print('usage: --record "Name=tier" ["Name=tier" ...]')
            return 3
        n, errors = record(pairs)
        print(f"recorded {n} stated answer(s) (source={closeness.STATED_SOURCE}; "
              f"a .bak was written first)")
        for e in errors:
            print(f"  🔴 {e}")
        return 0 if not errors else 2
    if "--why" in args:
        i = args.index("--why")
        if i + 1 >= len(args):
            print('usage: --why "Contact Name"')
            return 3
        return why_name(args[i + 1])
    if "--name" in args:
        i = args.index("--name")
        if i + 1 >= len(args):
            print('usage: --name "Contact Name"')
            return 3
        return show_name(args[i + 1])
    print(__doc__.split("Usage:")[1].split("Exit:")[0].strip())
    return 3


if __name__ == "__main__":
    sys.exit(main())
