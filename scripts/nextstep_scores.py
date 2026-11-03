#!/usr/bin/env python3
"""Carry the NEXT-STEP picker's four scores to the next-step card.

The CLI writes (THE PAIR): a PostToolUse hook on AskUserQuestion stores every option of a picker whose
question carries the literal NEXT-STEP marker, scores parsed from the description, in
documents/state/next-step-scores.json. The app reads (build_app_feed.build_next_move): `attach_scores`
matches the stored options to the card's rows BY CONTENT and draws only what a fresh panel scored.

  python3 scripts/nextstep_scores.py --hook                       (stdin = the hook payload)
  python3 scripts/nextstep_scores.py set --label "..." --cpo 24 --cto 22 --designer 23 --rise8 24 [--default] [--why cpo "..."]
  python3 scripts/nextstep_scores.py replay [--last 10]

This module never runs the ranker or pair_brief.derive() (the ranker re-stamps weights-derive.json,
BUG-783); the hook stores and exits. Plan: plan-nextstep-scores-a3-2026-10-31.md."""
import argparse
import datetime
import glob
import json
import os
import re
import sys
import zoneinfo

REPO_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIDECAR = os.path.join("documents", "state", "next-step-scores.json")
MARKER = "NEXT-STEP"
SEATS = ("cpo", "cto", "designer", "rise8")
_SEAT_RX = r"CPO|CTO|Designer|CEO|Rise8"
_SEAT = re.compile(r"\b(" + _SEAT_RX + r")\b\s*[:=]?\s*(\d{1,3})\b"
                   r"(?:\s*\(([^()]*)\)|\s*:\s*(.+?)(?=\s*(?:[·/,;]\s*)?\b(?:" + _SEAT_RX + r")\b\s*[:=]?\s*\d|\s*=\s*\d|$))?",
                   re.I)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _configured_zone():
    """kit_config.SCORES_TIMEZONE; an older kit_config that predates it means unset."""
    try:
        from kit_config import SCORES_TIMEZONE
        return str(SCORES_TIMEZONE or "").strip()
    except Exception:
        return ""


def _zone():
    """His install's configured zone, else this machine's own. A name the machine does not know is
    the machine's zone too: a clock must never crash the feed."""
    name = _configured_zone()
    if name:
        try:
            return zoneinfo.ZoneInfo(name)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            pass
    return datetime.datetime.now().astimezone().tzinfo


def _path(repo):
    return os.path.join(repo or REPO_DEFAULT, SIDECAR)


def parse_scores(desc):
    """{"scores": {cpo,cto,designer,rise8}, "scale": 25|100, "why": {seat: sentence}} or None when the
    description does not carry all four numbers. "CEO" is the Designer seat's old name."""
    found, why = {}, {}
    for m in _SEAT.finditer(str(desc or "")):
        seat = m.group(1).lower()
        seat = "designer" if seat == "ceo" else seat
        if seat in found:
            continue
        found[seat] = int(m.group(2))
        note = (m.group(3) or m.group(4) or "").strip(" .·")
        if note:
            why[seat] = note
    if set(found) != set(SEATS):
        return None
    return {"scores": {k: found[k] for k in SEATS},
            "scale": 25 if max(found.values()) <= 25 else 100, "why": why}


def options_from_question(q):
    """The picker's options as stored, or None when the question is not a NEXT-STEP picker."""
    if MARKER not in (str((q or {}).get("question", "")) + " " + str((q or {}).get("header", ""))):
        return None
    out = []
    for i, o in enumerate((q or {}).get("options") or []):
        p = parse_scores(o.get("description"))
        row = {"label": str(o.get("label", "")), "is_default": i == 0,
               "scores": p["scores"] if p else None, "scale": p["scale"] if p else None,
               "why": p["why"] if p else {}}
        if not p:  # keep the text a null parse failed on, so the miss can be diagnosed
            row["description"] = str(o.get("description") or "")
        out.append(row)
    return out


def _local(now):
    """`now` in his zone. A naive time is already his local time; an aware one is converted."""
    if now is None:
        return datetime.datetime.now(_zone())
    if isinstance(now, str):
        now = datetime.datetime.fromisoformat(now)
    return now.astimezone(_zone()) if now.tzinfo else now


def local_today():
    return datetime.datetime.now(_zone()).date().isoformat()


def write_panel(options, stamp, repo=None, now=None, by="orchestrator"):
    """The one writer of the sidecar (hook mode and `set` share it)."""
    t = _local(now)
    data = {"scored_at": t.isoformat(timespec="seconds"), "scored_local": t.strftime("%Y-%m-%d %H:%M"),
            "scored_by": by, "stamp": stamp, "options": options}
    path = _path(repo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return data


def hook(payload, repo=None, now=None):
    """Store the first NEXT-STEP question of a picker; any other picker stores nothing."""
    for q in ((payload or {}).get("tool_input") or {}).get("questions") or []:
        opts = options_from_question(q)
        if opts is not None:
            return write_panel(opts, q.get("question", ""), repo=repo, now=now)
    return None


# ── matching, by content (the table in the plan is the whole rule) ──────────────────────────────

def _clean(label):
    s = re.sub(r"\(\s*andy\s*\)", "", str(label or ""), flags=re.I)
    s = re.sub(r",\s*reunion\b", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip().lower()


def _usable(o):
    return bool(o.get("scores")) and o.get("scale") == 25


def _default_matches(opt_label, default_label):
    d = str(default_label or "")
    lab = _clean(opt_label)
    m = re.search(r"work the due tripwire:\s*(.+)$", d, re.I)
    if m:
        co = m.group(1).strip().lower()
        return bool(co) and "unknown" not in co and co in lab
    m = re.search(r"next initial contact:\s*(.+?)(?:\s+·\s+|\s+@\s+|$)", d, re.I)
    if m:
        name = m.group(1).strip().lower()
        if not name.startswith("run discovery"):  # pair_brief's refill wording is a task, not a person
            return bool(name) and name in lab
    # another task: the same keyword rules the alternates use (gig lane, refill, bug work ...)
    return lab == _clean(d) or _alt_matches(opt_label, {"label": d})


def _alt_matches(opt_label, alt):
    lab = _clean(opt_label)
    label = str(alt.get("label", ""))
    low = label.lower()
    if low.startswith("gig lane"):
        return lab.startswith("gig lane")
    if "refill" in low:
        return "discovery" in lab or "refill" in lab
    if "screening debt" in low:
        return "screening debt" in lab or "banked" in lab
    if low.startswith("bug and test work"):
        return "bug" in lab or "test work" in lab
    if low.startswith("stalled boss search:"):
        cos = [c.strip().lower() for c in label.split(":", 1)[1].split(",") if c.strip()]
        return any(c in lab for c in cos)
    return lab == _clean(label)


def _pause_matches(opt_label):
    """The picker's option 1 while boss hunting is paused: the next Rise8 activity."""
    return "rise8 activity" in _clean(opt_label)


def match_rows(panel, default_label, alternates):
    """({"default" | "alt:<i>": stored option}, [labels of usable options no row took]).
    First match wins in row order; one option takes at most one row and a row takes one option."""
    pool = [o for o in (panel or {}).get("options") or [] if _usable(o)]
    hits = {}
    for o in list(pool):
        if _default_matches(o["label"], default_label):
            hits["default"] = o
            pool.remove(o)
            break
    for i, alt in enumerate(alternates or []):
        for o in list(pool):
            if _alt_matches(o["label"], alt):
                hits["alt:%d" % i] = o
                pool.remove(o)
                break
    return hits, [o["label"] for o in pool]


def load_panel(repo=None):
    try:
        with open(_path(repo), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _fresh(panel, today):
    today = today or local_today()
    return str(panel.get("scored_local", ""))[:10] == str(today)[:10]


def _scored_line(panel):
    loc = str(panel.get("scored_local", ""))
    m = re.match(r"\d{4}-(\d\d-\d\d) (\d\d:\d\d)", loc)
    when = " %s at %s" % (m.group(1), m.group(2)) if m else ""
    return "scored%s by the %s" % (when, panel.get("scored_by") or "orchestrator")


def attach_scores(next_move, repo=None, today=None):
    """Attach `scores` (the feed's own keys: cpo, cto, ceo=Designer, rise8), `scored_line` and
    `seat_notes` to the card rows a fresh panel scored. Nothing else changes; no sidecar, a broken
    one, a stale one, or an old-scale one draws nothing."""
    panel = load_panel(repo)
    if not panel or not _fresh(panel, today):
        return next_move
    alts = next_move.get("alternates") or []
    hits, misses = match_rows(panel, (next_move.get("default") or {}).get("label"), alts)
    line = _scored_line(panel)
    rows = {"default": next_move.get("default")}
    rows.update({"alt:%d" % i: a for i, a in enumerate(alts)})
    for key, o in hits.items():
        row = rows.get(key)
        if row is None:
            continue
        s = o["scores"]
        row["scores"] = {"cpo": s["cpo"], "cto": s["cto"], "ceo": s["designer"], "rise8": s["rise8"]}
        row["scored_line"] = line
        if o.get("why"):
            row["seat_notes"] = dict(o["why"])
    # While boss hunting is paused the page makes option 1 itself ("Next Rise8 activity: ..."), a row the feed never carried.
    # Its scores come from the same panel, matched by content, or it draws none.
    for o in (panel.get("options") or []):
        if o.get("label") in misses and _usable(o) and _pause_matches(o["label"]):
            s = o["scores"]
            next_move["pause_option"] = {
                "scores": {"cpo": s["cpo"], "cto": s["cto"], "ceo": s["designer"], "rise8": s["rise8"]},
                "scored_line": line, "seat_notes": dict(o.get("why") or {})}
            misses = [m for m in misses if m != o["label"]]
            break
    for label in misses:
        print("nextstep_scores: scored in the picker, no card row: %s" % label, file=sys.stderr)
    return next_move


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────

_KEYWORD_ROWS = ("gig lane", "discovery", "refill", "screening debt", "banked", "bug", "test work")


def _replay(last):
    """How many of the last N NEXT-STEP pickers' options this slice can score at all: parsed out of
    25, and whether the label hits a card-row keyword. Reads the session transcripts; runs no ranker."""
    pickers = []
    base = os.path.expanduser("~/.claude/projects")
    for f in sorted(glob.glob(os.path.join(base, "*", "*.jsonl")), key=os.path.getmtime):
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    if "AskUserQuestion" not in line or MARKER not in line:
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    content = (msg.get("message") or {}).get("content")
                    for c in content if isinstance(content, list) else []:
                        if c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion":
                            for q in (c.get("input") or {}).get("questions") or []:
                                opts = options_from_question(q)
                                if opts:
                                    pickers.append((msg.get("timestamp", ""), opts))
        except OSError:
            continue
    pickers = sorted(pickers, key=lambda p: p[0])[-last:]
    total = scored = 0
    for ts, opts in pickers:
        s25 = [o for o in opts if _usable(o)]
        kw = [o for o in s25 if any(k in _clean(o["label"]) for k in _KEYWORD_ROWS)]
        total += len(opts)
        scored += len(s25)
        print("%s  options %d  out of 25: %d  alternate-row keyword hits: %d  (default: not measured)"
              % (ts[:16], len(opts), len(s25), len(kw)))
    print("pickers %d  options %d  out of 25 %d" % (len(pickers), total, scored))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=None)
    ap.add_argument("--hook", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    st = sub.add_parser("set")
    st.add_argument("--label", required=True)
    for s in SEATS:
        st.add_argument("--" + s, type=int, required=True)
    st.add_argument("--default", action="store_true")
    st.add_argument("--why", nargs=2, action="append", metavar=("SEAT", "TEXT"), default=[])
    rp = sub.add_parser("replay")
    rp.add_argument("--last", type=int, default=10)
    a = ap.parse_args(argv)
    if a.hook:
        try:
            hook(json.load(sys.stdin), repo=a.repo)
        except Exception as e:  # a hook must never block the picker
            print("nextstep_scores: hook skipped (%s: %s)" % (type(e).__name__, e), file=sys.stderr)
        return 0
    if a.cmd == "set":
        today = local_today()
        panel = load_panel(a.repo)
        opts = (panel["options"] if panel and _fresh(panel, today) else [])
        opts = [o for o in opts if o.get("label") != a.label]
        vals = {s: getattr(a, s) for s in SEATS}
        why = {s.lower().replace("ceo", "designer"): t for s, t in a.why}
        opts.append({"label": a.label, "is_default": bool(a.default), "scores": vals,
                     "scale": 25 if max(vals.values()) <= 25 else 100, "why": why})
        write_panel(opts, (panel or {}).get("stamp", "set by hand"), repo=a.repo)
        return 0
    if a.cmd == "replay":
        _replay(a.last)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
