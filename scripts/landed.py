#!/usr/bin/env python3
"""landed.py: the typed record of what landed, for the brief's "SINCE YOUR LAST VISIT" section.

Plan: plan-next-build-slice-2026-11-02.md (rev 3), slice 1. The words he reads are typed by the seat that
merged or pushed the work (Q1 default): never derived from commit subjects, plans or diffs. A merge or kit
push with no typed line shows only as a count. One writer (`write_row`) appends to documents/state/landed.jsonl.

  python3 scripts/landed.py add --repo ajs|kit --sha <sha> --where terminal|app|both --what "..." --by <seat> [--plan <file>]
  python3 scripts/landed.py building --what "..." --plan <file> --by <seat>
  python3 scripts/landed.py nothing --what "<the reason>" --by <seat>
  python3 scripts/landed.py drop --plan <file> --why "..." --by <seat>
  python3 scripts/landed.py since [--json]
  python3 scripts/landed.py check          (the seat-facing view: what still owes a line)
"""
import argparse
import datetime
import fcntl
import functools
import json
import os
import re
import subprocess
import sys
import tempfile
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
RECORD = os.path.join("documents", "state", "landed.jsonl")
LEDGER = os.path.join("documents", "decision-ledger.jsonl")
KIT_CHECKOUT = "/home/vscode/kit-app"


def kit_checkout():
    """The kit checkout whose pushes the brief counts: LANDED_KIT_REPO in the environment, else kit_config.LANDED_KIT_REPO, else the default above.
    A path that is not a folder on this machine means kit pushes are not counted (never an error)."""
    env = os.environ.get("LANDED_KIT_REPO")
    if env is not None:
        return env
    try:
        from kit_config import LANDED_KIT_REPO
        if str(LANDED_KIT_REPO or "").strip():
            return str(LANDED_KIT_REPO).strip()
    except Exception:
        pass
    return KIT_CHECKOUT
WHERE_WORDS = {"terminal": "the terminal", "app": "the app", "both": "the terminal and the app"}
MAX_LINES = 5
STALE_BUILDING_DAYS = 7
LOOKBACK_DAYS = 30
FALLBACK_DAYS = 7
_HEX = re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")


class LandedError(ValueError):
    pass


def _zone(zone):
    if zone is None:
        import nextstep_scores
        return nextstep_scores._zone()
    if isinstance(zone, str):
        return zoneinfo.ZoneInfo(zone)
    return zone


def _dt(s):
    t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def _today(today, tz):
    return datetime.date.fromisoformat(today) if today else datetime.datetime.now(tz).date()


def _rows(path):
    """(rows, skipped_count). A malformed line is skipped, never fatal."""
    rows, skipped = [], 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    skipped += 1
                    continue
                if isinstance(r, dict) and r.get("ts"):
                    rows.append(r)
                else:
                    skipped += 1
    except OSError:
        pass
    return rows, skipped


# ── his last visit ─────────────────────────────────────────────────────────────────────────────

def last_visit(ledger, today=None, zone=None):
    """The latest picker answer of his (posttooluse-hook, not peer-minted) that falls on a day before
    today in his zone, within 30 days. {"ts", "local", "fallback"}; with none, a 7-day window."""
    import ledger_keys
    tz = _zone(zone)
    day = _today(today, tz)
    best = None
    rows, _ = _rows(ledger)
    for r in rows:
        if r.get("source") != "posttooluse-hook" or ledger_keys.row_is_peer_minted(r):
            continue
        try:
            t = _dt(r["ts"]).astimezone(tz)
        except (ValueError, KeyError):
            continue
        if t.date() < day and (day - t.date()).days <= LOOKBACK_DAYS and (best is None or t > best):
            best = t
    if best is None:
        start = datetime.datetime.combine(day - datetime.timedelta(days=FALLBACK_DAYS), datetime.time(), tz)
        return {"ts": start, "local": start, "fallback": True}
    return {"ts": best, "local": best, "fallback": False}


def head(v):
    if v.get("fallback"):
        return "the last 7 days"
    t = v["local"]
    return "%s, %d:%02d %s" % (t.strftime("%a %m-%d"), (t.hour % 12) or 12, t.minute, "am" if t.hour < 12 else "pm")


# ── events (injected in tests) ─────────────────────────────────────────────────────────────────

def _git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout


def default_events(since_iso, repo_dir=None):
    """Merges on main of THIS workspace (repo_dir, else the module's own folder) and commits on kit origin/main since the window opened."""
    out = []
    kit = kit_checkout()
    rc, txt = _git("log", "main", "--merges", "--since", since_iso, "--format=%H|%cI|%s", cwd=repo_dir or REPO_DEFAULT)
    for line in txt.splitlines() if rc == 0 else []:
        sha, ts, subj = (line.split("|", 2) + ["", ""])[:3]
        out.append({"repo": "ajs", "sha": sha, "ts": ts, "subject": subj})
    if kit and os.path.isdir(kit):
        rc, txt = _git("log", "origin/main", "--since", since_iso, "--format=%H|%cI|%s", cwd=kit)
        for line in txt.splitlines() if rc == 0 else []:
            sha, ts, subj = (line.split("|", 2) + ["", ""])[:3]
            out.append({"repo": "kit", "sha": sha, "ts": ts, "subject": subj})
    return out


def default_resolve(repo, sha, repo_dir=None):
    if repo == "ajs":
        return _git("merge-base", "--is-ancestor", sha, "main", cwd=repo_dir or REPO_DEFAULT)[0] == 0
    kit = kit_checkout()
    if not (kit and os.path.isdir(kit)):
        raise LandedError("the kit checkout %s is absent, so a kit sha cannot be checked" % kit)
    _git("fetch", "-q", "origin", cwd=kit)
    return _git("merge-base", "--is-ancestor", sha, "origin/main", cwd=kit)[0] == 0


def default_style(text):
    """House-style findings (hard reads) for one line, [] when clean."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(text + "\n")
        name = fh.name
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, "check_style.py"), name, "--mode", "chat"],
                           capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(name)
    return [l.strip() for l in r.stdout.splitlines() if "🔴" in l] if r.returncode == 2 else []


def default_time(repo, sha, repo_dir=None):
    """When the work landed: the commit's own time, ISO. None if it cannot be read."""
    cwd = (repo_dir or REPO_DEFAULT) if repo == "ajs" else kit_checkout()
    rc, txt = _git("show", "-s", "--format=%cI", sha, cwd=cwd)
    return txt.strip() or None if rc == 0 else None


def _when(r):
    """The moment a row belongs to: when its work landed, else when the line was typed."""
    return r.get("landed_at") or r["ts"]


def _matches(row_sha, sha):
    a, b = str(row_sha or "").lower(), str(sha or "").lower()
    return len(a) >= 7 and len(b) >= 7 and (a.startswith(b) or b.startswith(a))


# ── the one writer ─────────────────────────────────────────────────────────────────────────────

def write_row(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return row


def _check_words(what, style_fn):
    what = str(what or "").strip()
    if not 8 <= len(what) <= 160:
        raise LandedError("the line must be 8 to 160 characters (it is %d)" % len(what))
    if what.lower().startswith("merge"):
        raise LandedError("the line starts with 'Merge': say what he can now do or see")
    if _HEX.search(what):
        raise LandedError("the line holds a hash; a hash is never a word")
    found = (style_fn or default_style)(what)
    if found:
        raise LandedError("house style: " + "; ".join(found))
    return what


def _now(now):
    return str(now) if now else datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def add(repo, sha, where, what, by, path=None, plan=None, resolve_fn=None, style_fn=None, time_fn=None,
        now=None, repo_dir=None):
    path = path or os.path.join(REPO_DEFAULT, RECORD)
    if repo not in ("ajs", "kit"):
        raise LandedError("repo must be ajs or kit")
    if where not in WHERE_WORDS:
        raise LandedError("where must be terminal, app or both")
    what = _check_words(what, style_fn)
    if not (resolve_fn or functools.partial(default_resolve, repo_dir=repo_dir))(repo, sha):
        raise LandedError("%s does not resolve on %s main" % (sha, repo))
    rows, _ = _rows(path)
    if any(r.get("kind") == "landed" and _matches(r.get("sha"), sha) for r in rows):
        raise LandedError("%s already has a line" % sha)
    row = {"ts": _now(now), "kind": "landed", "repo": repo, "sha": sha, "where": where, "what": what, "by": by}
    committed = (time_fn or functools.partial(default_time, repo_dir=repo_dir))(repo, sha)
    if committed:
        row["landed_at"] = committed
    if plan:
        row["plan"] = plan
    return write_row(path, row)


def building(what, plan, by, path=None, repo=None, style_fn=None, now=None):
    path = path or os.path.join(REPO_DEFAULT, RECORD)
    row = {"ts": _now(now), "kind": "building", "what": _check_words(what, style_fn), "plan": plan, "by": by}
    if repo:
        row["repo"] = repo
    return write_row(path, row)


def nothing(what, by, path=None, style_fn=None, now=None):
    path = path or os.path.join(REPO_DEFAULT, RECORD)
    return write_row(path, {"ts": _now(now), "kind": "nothing", "what": _check_words(what, style_fn), "by": by})


def drop(plan, why, by, path=None, style_fn=None, now=None):
    path = path or os.path.join(REPO_DEFAULT, RECORD)
    return write_row(path, {"ts": _now(now), "kind": "drop", "plan": plan, "why": _check_words(why, style_fn), "by": by})


# ── the window ─────────────────────────────────────────────────────────────────────────────────

def since(path, ledger, today=None, zone=None, events_fn=None, repo_dir=None):
    tz = _zone(zone)
    day = _today(today, tz)
    v = last_visit(ledger, today, tz)
    start = v["ts"]
    rows, skipped = _rows(path)
    if skipped:
        print("landed: skipped %d unreadable line(s) in %s" % (skipped, path), file=sys.stderr)
    in_window = []
    for r in rows:
        try:
            if _dt(_when(r)) >= start:
                in_window.append(r)
        except (ValueError, KeyError):
            pass
    landed_rows = [r for r in in_window if r.get("kind") == "landed"]
    ended = {r.get("plan") for r in rows if r.get("kind") in ("landed", "drop") and r.get("plan")}
    open_building = []
    for r in rows:
        if r.get("kind") == "building" and r.get("plan") not in ended:
            age = (day - _dt(r["ts"]).astimezone(tz).date()).days
            open_building.append(dict(r, stale=age > STALE_BUILDING_DAYS))
    notes = [r for r in in_window if r.get("kind") == "nothing"]
    try:
        events = (events_fn or functools.partial(default_events, repo_dir=repo_dir))(start.astimezone(datetime.timezone.utc).isoformat(timespec="seconds"))
    except Exception:
        events = []
    typed = [r.get("sha") for r in rows if r.get("kind") == "landed"]
    unwritten = [e for e in events if not any(_matches(t, e.get("sha")) for t in typed)]
    return {"last_visit": v, "head": head(v), "fallback": v["fallback"], "window_start": start,
            "rows": landed_rows, "building": open_building,
            "nothing": notes[-1]["what"] if notes else None, "unwritten": len(unwritten),
            "unwritten_events": unwritten, "tz": tz}


def _day(r, tz):
    return _dt(_when(r)).astimezone(tz).strftime("%m-%d")


def _surface(r, tz):
    """"the app, 11-01"; just the date when the line named no surface."""
    where = WHERE_WORDS.get(r.get("where"))
    return "%s, %s" % (where, _day(r, tz)) if where else _day(r, tz)


def section(path, ledger, today=None, zone=None, events_fn=None, repo_dir=None):
    """The brief's lines for his view, [] when there is no landed.jsonl at all (a partner install)."""
    if not os.path.exists(path):
        return []
    d = since(path, ledger, today, zone, events_fn, repo_dir)
    tz = d["tz"]
    out = ["SINCE YOUR LAST VISIT (%s)" % d["head"]]
    rows = d["rows"]
    for r in rows[:MAX_LINES]:
        out.append("  ✅ %s  · %s" % (r["what"], _surface(r, tz)))
    if len(rows) > MAX_LINES:
        out.append("  … and %d more" % (len(rows) - MAX_LINES))
    n = d["unwritten"]
    if n:
        out.append("  ⚪ %d change%s landed that no one has described yet" % (n, "" if n == 1 else "s"))
    if not rows and not n:
        out.append("  nothing landed; %s" % (d["nothing"] or "no reason recorded yet"))
    if d["building"]:
        out.append("BUILDING NOW")
        for b in d["building"]:
            since_txt = "(since %s) " % _day(b, tz) if b["stale"] else ""
            out.append("  🔨 %s%s" % (since_txt, b["what"]))
    return out


def as_block(path, ledger, today=None, zone=None, events_fn=None, repo_dir=None):
    """The same facts as `section`, for as_json(); None when there is no landed.jsonl."""
    if not os.path.exists(path):
        return None
    d = since(path, ledger, today, zone, events_fn, repo_dir)
    tz = d["tz"]
    # only what he may read: no sha, no seat name, no plan file (slice 2 must not draw those)
    return {"last_visit": d["head"],
            "rows": [{"what": r["what"], "where": WHERE_WORDS.get(r.get("where")), "day": _day(r, tz)}
                     for r in d["rows"]],
            "building": [{"what": b["what"], "since": _day(b, tz) if b["stale"] else None} for b in d["building"]],
            "nothing": d["nothing"], "unwritten": d["unwritten"]}


# ── seat view ──────────────────────────────────────────────────────────────────────────────────

def check(path, ledger, today=None, zone=None, events_fn=None, resolve_fn=None, now=None, repo_dir=None):
    """Lines for the seat that owes words (his view carries none of this)."""
    tz = _zone(zone)
    d = since(path, ledger, today, zone, events_fn, repo_dir)
    out = []
    for r in _rows(path)[0]:
        if r.get("kind") == "landed" and not (resolve_fn or functools.partial(default_resolve, repo_dir=repo_dir))(r.get("repo", "ajs"), r.get("sha")):
            out.append("a landed line points at %s, which no longer resolves on %s main" % (r.get("sha"), r.get("repo")))
    cutoff = (_dt(now) if now else datetime.datetime.now(datetime.timezone.utc)) - datetime.timedelta(hours=48)
    for e in d["unwritten_events"]:
        try:
            old = _dt(e["ts"]) < cutoff
        except (ValueError, KeyError):
            old = False
        if old:
            out.append('%s %s has no line: python3 scripts/landed.py add --repo %s --sha %s --where <terminal|app|both> --what "..." --by <seat>'
                       % (e.get("repo"), str(e.get("sha"))[:8], e.get("repo"), str(e.get("sha"))[:8]))
    for b in d["building"]:
        if b["stale"]:
            out.append("building since %s is over %d days old: land it or `landed.py drop --plan %s`"
                       % (b["plan"], STALE_BUILDING_DAYS, b["plan"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo-dir", default=REPO_DEFAULT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_ = sub.add_parser("add")
    a_.add_argument("--repo", required=True)
    a_.add_argument("--sha", required=True)
    a_.add_argument("--where", required=True)
    a_.add_argument("--what", required=True)
    a_.add_argument("--by", required=True)
    a_.add_argument("--plan")
    b_ = sub.add_parser("building")
    b_.add_argument("--what", required=True)
    b_.add_argument("--plan", required=True)
    b_.add_argument("--by", required=True)
    n_ = sub.add_parser("nothing")
    n_.add_argument("--what", required=True)
    n_.add_argument("--by", required=True)
    d_ = sub.add_parser("drop")
    d_.add_argument("--plan", required=True)
    d_.add_argument("--why", required=True)
    d_.add_argument("--by", required=True)
    s_ = sub.add_parser("since")
    s_.add_argument("--json", action="store_true")
    sub.add_parser("check")
    a = ap.parse_args(argv)
    path = os.path.join(a.repo_dir, RECORD)
    ledger = os.path.join(a.repo_dir, LEDGER)
    try:
        if a.cmd == "add":
            add(a.repo, a.sha, a.where, a.what, a.by, path=path, plan=a.plan, repo_dir=a.repo_dir)
        elif a.cmd == "building":
            building(a.what, a.plan, a.by, path=path)
        elif a.cmd == "nothing":
            nothing(a.what, a.by, path=path)
        elif a.cmd == "drop":
            drop(a.plan, a.why, a.by, path=path)
        elif a.cmd == "since":
            if a.json:
                print(json.dumps(as_block(path, ledger, repo_dir=a.repo_dir), indent=2, default=str))
            else:
                print("\n".join(section(path, ledger, repo_dir=a.repo_dir)) or "no landed.jsonl yet")
        elif a.cmd == "check":
            print("\n".join(check(path, ledger, repo_dir=a.repo_dir)) or "nothing owed")
    except LandedError as e:
        print("landed: refused. %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
