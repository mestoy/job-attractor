#!/usr/bin/env python3
"""One lock for documents/send-log.jsonl (BUG-687), the safe spool, and the one reader that sees both.

Every writer of the send log takes `locked(path)` around its read-modify-write, and every writer is atomic (temp file plus os.replace), so a reader sees the old file or the new
one, whole, and never takes a lock. The lock is `<log>.lock`, a separate file beside the log (an os.replace over a locked path would orphan the lock).

NOT REENTRANT (the closeness.py store_lock note): flock on a second open of the same path in one process blocks forever, so a second `locked(` for the same log in one thread raises
at once. The lock is the INNERMOST lock: held only across one read-modify-write, never across a child, a subprocess, a network call or a wait on a slot. Order, outer to inner:
stage_slot, fold_lock, then this file's lock; the spool lock sits INSIDE the main lock, never the reverse.

Two budgets. `LOCK_TIMEOUT` (10 s) is for writers whose caller can try again and for every request thread in serve.py. `LOCK_TIMEOUT_AFTER` (60 s) is for the writers that run AFTER the
irreversible step (the mail-draft.sh row after delivery, `--confirm-sent` after the person pressed Send, `--mark-bounced` after a real bounce, a logged LinkedIn send): they NEVER give up
the change. When even their budget runs out they SPOOL it, as an operation and not a row, to `<log>.pending.jsonl` (append-only, its own lock); when the spool is also busy the operation
becomes its own file in `<log>.pending.d/`. The next `locked()` entry folds both into the main log inside the same lock (idempotent: every spooled entry carries a `spool_id` that stays
on the main row forever), and `read_all` applies them in memory so a board or a dedup check never lags a write that is on disk.

Without fcntl (Windows) the lock uses msvcrt.locking; with neither it is a no-op, says so once on stderr, and stamps `_write_meta: {"lock": "none"}` on the rows it writes.
"""
import contextlib
import copy
import datetime
def _load_local_day():
    """local_day, by import or by path: this module is also loaded by file path from a folder that is not on sys.path."""
    try:
        import local_day
        return local_day
    except ImportError:
        pass
    try:
        import importlib.util
        import os
        spec = importlib.util.spec_from_file_location("local_day", os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_day.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # a partial copy of scripts/ keeps the machine calendar
        return None


_local_day = _load_local_day()  # BUG-795


def _send_day():
    return _local_day.today() if _local_day else datetime.date.today().isoformat()

import json
import os
import sys
import threading
import time
import uuid

try:
    import fcntl
except ImportError:                                    # Windows
    fcntl = None
try:
    import msvcrt
except ImportError:                                    # POSIX
    msvcrt = None

LOCK_TIMEOUT = 10
LOCK_TIMEOUT_AFTER = 60
POLL_SECONDS = 0.05
BUSY_LINE = "another writer holds the send log; try again in a moment"
LOCK_KIND = "flock" if fcntl else ("msvcrt" if msvcrt else "none")

_HERE = os.path.dirname(os.path.abspath(__file__))
_held = threading.local()
_warned = []


class SendLogBusy(Exception):
    """The lock was not free within the budget. The message is the plain line a person reads."""


def spool_paths(path):
    """(spool file, pending folder, refused file) for a log path, named from the log's own file name (send-log.jsonl gives send-log.pending.jsonl and so on)."""
    d, base = os.path.split(os.path.abspath(path))
    stem = base[:-6] if base.endswith(".jsonl") else base
    return (os.path.join(d, stem + ".pending.jsonl"), os.path.join(d, stem + ".pending.d"), os.path.join(d, stem + ".pending.refused.jsonl"))


def _say_once(msg):
    if msg not in _warned:
        _warned.append(msg)
        sys.stderr.write(msg + "\n")


@contextlib.contextmanager
def _flock(lock_path, timeout):
    """Take an exclusive lock on `lock_path` (0600, created if absent), polling every 50 ms up to `timeout` seconds, else raise SendLogBusy."""
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if LOCK_KIND == "none":
            _say_once("send-log lock: neither fcntl nor msvcrt is available here, so this write is NOT locked")
            yield
            return
        deadline = time.monotonic() + timeout
        while True:
            try:
                if fcntl:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    os.lseek(fd, 0, 0)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SendLogBusy(BUSY_LINE)
                time.sleep(POLL_SECONDS)
        try:
            yield
        finally:
            try:
                if fcntl:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                else:
                    os.lseek(fd, 0, 0)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
    finally:
        os.close(fd)


@contextlib.contextmanager
def locked(path, timeout=LOCK_TIMEOUT, enabled=True, fold_in=True):
    """Hold the send log's lock across one read-modify-write. Not reentrant. `enabled=False` yields without a lock or a lock file (a --dry-run preview). On entry any spooled
    changes are folded into the log first, so the caller reads a log that already has them."""
    if not enabled:
        yield
        return
    key = os.path.abspath(path)
    held = getattr(_held, "paths", None)
    if held is None:
        held = _held.paths = set()
    if key in held:
        raise RuntimeError("the send-log lock is not reentrant: %s is already locked by this thread" % key)
    with _flock(key + ".lock", timeout):
        held.add(key)
        try:
            if fold_in:
                _fold_into(key)
            yield
        finally:
            held.discard(key)


def stamp_unlocked(rows):
    """With no lock available the loss is on record: each dict row gets _write_meta.lock = none."""
    if LOCK_KIND == "none":
        for r in rows:
            if isinstance(r, dict):
                r.setdefault("_write_meta", {})["lock"] = "none"
    return rows


def atomic_write_text(path, text):
    """Temp file plus os.replace in the log's own folder: a reader sees the old file or the new one, whole."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def atomic_write_rows(path, rows):
    """Write dict rows (and raw unparseable strings kept as found) one per line, atomically."""
    stamp_unlocked(rows)
    atomic_write_text(path, "".join((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n" for r in rows))


# ---- reading --------------------------------------------------------------------------------------------------------------------------------------
def read_items(path, strict=False):
    """The main log as a list: a dict per parsed line, the raw string for a line that does not parse (kept as found). strict=True raises ValueError/UnicodeDecodeError instead."""
    if not os.path.exists(path):
        return []
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8") if strict else raw.decode("utf-8", errors="ignore")
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            if strict:
                raise
            out.append(line)
            continue
        out.append(r)
    return out


def _entries(path):
    """Every pending operation, spool file first then the folder, one per spool_id."""
    spool, pend, _ref = spool_paths(path)
    seen, out = set(), []
    try:
        with open(spool, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("spool_id") and e["spool_id"] not in seen:
                    seen.add(e["spool_id"])
                    out.append(e)
    except OSError:
        pass
    try:
        names = sorted(os.listdir(pend))
    except OSError:
        names = []
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(pend, n), encoding="utf-8") as fh:
                e = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(e, dict) and e.get("spool_id") and e["spool_id"] not in seen:
            seen.add(e["spool_id"])
            out.append(e)
    # Apply in the order the changes were made (`at`, then spool_id). An update spooled before its append may find no row in one fold; it stays in the spool and lands at the next.
    out.sort(key=lambda e: (str(e.get("at") or ""), e["spool_id"]))
    return out


def _spool_ids(items):
    ids = set()
    for r in items:
        if isinstance(r, dict):
            if r.get("spool_id"):
                ids.add(r["spool_id"])
            for x in r.get("spool_ids") or []:
                ids.add(x)
    return ids


def _tag(row, sid):
    row["spool_id"] = sid
    ids = list(row.get("spool_ids") or [])
    if sid not in ids:
        ids.append(sid)
    row["spool_ids"] = ids


def _lls():
    """log_linkedin_send, imported lazily from this file's own folder (it imports this module at load, so a top import would be circular)."""
    m = sys.modules.get("log_linkedin_send")
    if m is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("log_linkedin_send", os.path.join(_HERE, "log_linkedin_send.py"))
        m = importlib.util.module_from_spec(spec)
        sys.modules["log_linkedin_send"] = m
        try:
            spec.loader.exec_module(m)
        except Exception:
            sys.modules.pop("log_linkedin_send", None)
            raise
    return m


class ResendBlocked(Exception):
    """The thread already had its one resend: no third address."""


def bounced_listed(path):
    """The lower-cased addresses on bounced-addresses.txt beside the log (an address on it is never written back)."""
    out = set()
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(path)), "bounced-addresses.txt"), encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                t = line.strip().lower()
                if t and not t.startswith("#"):
                    out.add(t)
    except OSError:
        pass
    return out


def resend_into(items, row, company, to_name, subject, listed, day=None):
    """THE ONE RESEND, ON THE SAME ROW: when a `bounced` row for this company and person (the subject stands in when there is no person) has no `resent_date`, `row` replaces it IN
    PLACE with the new address, the original date and sent_ts, `resent_date` today and the bounce history carried forward. Returns True when it did, False when no such row exists (or the
    address is the bounced one or is listed). `day` is the send day to stamp (a folded entry passes the day it was spooled, BUG-698); None means today. Raises ResendBlocked when the matched row already had its resend. The live writer (mail-draft.sh) and the fold both call this one function."""
    norm = lambda a: (a or "").strip().lower()
    to = row.get("to")
    for i in range(len(items) - 1, -1, -1):
        r = items[i]
        if not (isinstance(r, dict) and r.get("status") == "bounced" and r.get("company") == company
                and (r.get("to_name") == to_name if to_name else r.get("subject") == subject)):
            continue
        if r.get("resent_date"):
            raise ResendBlocked()
        if norm(to) == norm(r.get("to")) or norm(to) in listed:
            continue
        row["to"] = norm(to)
        row["date"] = r.get("date", row.get("date"))
        if r.get("sent_ts"):
            row["sent_ts"] = r["sent_ts"]
        row["resent_date"] = day or _send_day()
        row["bounced_to"] = r.get("bounced_to") or r.get("to")
        row["first_bounced_at"] = r.get("first_bounced_at") or r.get("bounced_at") or ""
        if r.get("bounced_at"):
            row["bounced_at"] = r["bounced_at"]
        items[i] = row
        return True
    return False


def apply_entry(items, e, path=None):
    """Apply one spooled operation to `items` (a list of dict rows and raw strings), in place. Returns (state, detail): applied, nomatch, or refused (detail is the writer's own sentence).
    The matching is the live writer's own: log_linkedin_send's pure functions, never a copy."""
    lls = _lls()
    sid = e["spool_id"]
    rows = [r for r in items if isinstance(r, dict)]
    fields = e.get("fields") or {}
    key = e.get("key") or {}
    if e.get("op") == "append":
        new = dict(fields)
        _tag(new, sid)
        if new.get("status") in ("staged", "drafted"):     # a rebuild of the same draft overwrites its row in the same state (mail-draft.sh's one-row-per-draft rule)
            for i in range(len(items) - 1, -1, -1):
                r = items[i]
                if (isinstance(r, dict) and r.get("status") == new.get("status") and r.get("to") == new.get("to")
                        and r.get("company") == new.get("company") and r.get("subject") == new.get("subject")):
                    items[i] = new
                    return "applied", ""
        if key.get("resend"):                              # a spooled resend after a bounce: the same in-place rewrite the live writer does
            try:
                spooled_day = _local_day.day_of(e.get("at")) if _local_day and e.get("at") else ""     # BUG-698: the day it was spooled, not the day the fold runs
                if resend_into(items, new, key.get("company"), key.get("to_name"), key.get("subject"), bounced_listed(path) if path else set(), day=spooled_day or None):
                    return "applied", ""
            except ResendBlocked:
                return "refused", "this thread already had its one resend; the person pivot or LinkedIn is next"
        items.append(new)
        return "applied", ""
    if e.get("op") != "update":
        return "refused", "unknown operation %r" % (e.get("op"),)
    writer, to = e.get("writer"), key.get("to")
    if writer == "set_stage":
        target = lls.match_newest(rows, to)
        if target is None:
            return "nomatch", "no send-log row for %r" % (to,)
        want = fields.get("stage")
        refusal = lls.stage_refusal(lls.current_stage(target), want, to)
        if refusal:
            return "refused", refusal
        target["stage"], target["stage_at"] = want, fields.get("stage_at")
        if fields.get("stage_note"):
            target["stage_note"] = fields["stage_note"]
    elif writer == "mark_replied":
        target = lls.match_newest(rows, to)
        if target is None:
            return "nomatch", "no send-log row for %r" % (to,)
        target["replied"] = True
        target["replied_note"] = fields.get("replied_note")
    elif writer == "confirm_sent":
        target = lls.match_unsent(rows, to, key.get("company") or None, key.get("subject") or None)
        if target is None:
            return "nomatch", "no drafted/staged row for %r" % (to,)
        target.update({k: v for k, v in fields.items()})
    elif writer == "mark_bounced":
        target = lls.match_newest(rows, to)
        if target is None:
            return "nomatch", "no send-log row for %r" % (to,)
        st = target.get("status")
        if st == "bounced":
            return "refused", "the row for %s is already bounced; a bounced row is never flipped again" % to
        if st not in ("sent", "staged"):
            return "refused", "the newest row for %s is %r, not sent or staged, so it cannot have bounced" % (to, st)
        when = fields.get("bounced_at")
        target["status"], target["bounced_at"] = "bounced", when
        target["bounced_to"] = target.get("bounced_to") or target.get("to")
        target["first_bounced_at"] = target.get("first_bounced_at") or when
    else:
        return "refused", "unknown writer %r" % (writer,)
    _tag(target, sid)
    return "applied", ""


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


def effective_items(path, strict=False):
    """The main log as items (dicts and raw strings) with every spooled operation applied in memory. Takes no lock."""
    items = read_items(path, strict)
    pend = _entries(path)
    if pend:
        have = _spool_ids(items)
        items = copy.deepcopy(items)
        for e in pend:
            if e["spool_id"] not in have:
                if apply_entry(items, e, path)[0] == "applied":
                    have.add(e["spool_id"])
    return items


def _log_path(root_or_path):
    return root_or_path if root_or_path.endswith(".jsonl") else os.path.join(root_or_path, "documents", "send-log.jsonl")


def read_all(root_or_path, strict=False):
    """Every row a reader should see: the main log with any spooled operations applied in memory (the fold's own apply function, dry). Takes no lock. Accepts a data root or a log path."""
    return [r for r in effective_items(_log_path(root_or_path), strict) if isinstance(r, dict)]


def open_lines(path, errors="ignore"):
    """A text handle over what a reader should see: the file itself, byte for byte, when nothing is spooled; else the file's lines plus the spooled changes applied. Raises OSError
    (FileNotFoundError, IsADirectoryError) the way open() does, so a reader's existing handling still works. errors='strict' keeps a strict reader strict."""
    import io
    if _entries(path):
        if os.path.isdir(path):
            raise IsADirectoryError(path)
        items = effective_items(path, strict=(errors == "strict"))
        return io.StringIO("".join((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n" for r in items))
    return open(path, encoding="utf-8", errors=errors)


def orphans(root_or_path):
    """['<writer>, <to>'] for each spooled change that finds no row yet, for pair_brief and the fold's stderr."""
    path = root_or_path if root_or_path.endswith(".jsonl") else os.path.join(root_or_path, "documents", "send-log.jsonl")
    items = copy.deepcopy(read_items(path))
    have = _spool_ids(items)
    out = []
    for e in _entries(path):
        if e["spool_id"] in have:
            continue
        state, _d = apply_entry(items, e, path)
        if state == "nomatch":
            out.append("%s, %s" % (e.get("writer"), (e.get("key") or {}).get("to")))
    return out


# ---- the spool: operations, not rows ------------------------------------------------------------------------------------------------------------------
def spool(path, op, writer, key, fields):
    """Record one change for the next fold. Spool file under its own lock (10 s); when that is busy too, its own file in the pending folder (O_EXCL, a fresh name). Returns the
    spool_id. Only an OSError (a disk problem) can lose the change."""
    spool_file, pend, _ref = spool_paths(path)
    e = {"spool_id": uuid.uuid4().hex, "at": _now_iso(), "op": op, "key": key, "fields": fields, "writer": writer}
    line = json.dumps(e, ensure_ascii=False) + "\n"
    try:
        with _flock(spool_file + ".lock", LOCK_TIMEOUT):
            with open(spool_file, "a", encoding="utf-8") as fh:
                fh.write(line)
    except SendLogBusy:
        os.makedirs(pend, exist_ok=True)
        fd = os.open(os.path.join(pend, e["spool_id"] + ".json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(e, ensure_ascii=False))
    return e["spool_id"]


def fold(root):
    """Fold the spool and the pending folder of the log under `root` into its main log. The caller resolves the root (never the module's own default), so a foreign
    CLAUDE_PROJECT_DIR cannot redirect it. Takes the main lock itself; use inside `locked()` through _fold_into."""
    path = os.path.join(root, "documents", "send-log.jsonl")
    with locked(path, fold_in=False):
        _fold_into(os.path.abspath(path))


def _fold_into(path):
    """The fold, with the MAIN lock already held by the caller. Order: spool lock, read, main replace, spool rewrite, pending files removed. Idempotent through spool_id."""
    if not _entries(path):
        return
    spool_file, pend, refused_file = spool_paths(path)
    try:
        cm = _flock(spool_file + ".lock", LOCK_TIMEOUT)
        cm.__enter__()
    except SendLogBusy:
        _say_once("send log: the spool is busy; its changes fold in at the next write")
        return
    try:
        entries = _entries(path)
        if not entries:
            return
        items = read_items(path)
        have = _spool_ids(items)
        done, refused, changed = set(), [], False
        for e in entries:
            sid = e["spool_id"]
            if sid in have:
                done.add(sid)
                continue
            state, detail = apply_entry(items, e, path)
            if state == "applied":
                have.add(sid)
                done.add(sid)
                changed = True
            elif state == "refused":
                refused.append(dict(e, refusal=detail))
                done.add(sid)
            else:
                sys.stderr.write("send log: a spooled change found no row yet (%s, %s); it stays in the spool\n" % (e.get("writer"), (e.get("key") or {}).get("to")))
        if changed:
            atomic_write_rows(path, items)
        if refused:
            with open(refused_file, "a", encoding="utf-8") as fh:
                for e in refused:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        keep = []
        try:
            with open(spool_file, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        keep.append(line.rstrip("\n"))
                        continue
                    if not (isinstance(e, dict) and e.get("spool_id") in done):
                        keep.append(line.rstrip("\n"))
        except OSError:
            pass
        if os.path.exists(spool_file):
            atomic_write_text(spool_file, "".join(l + "\n" for l in keep))
        for sid in done:
            try:
                os.remove(os.path.join(pend, sid + ".json"))
            except OSError:
                pass
    finally:
        cm.__exit__(None, None, None)
