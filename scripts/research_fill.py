#!/usr/bin/env python3
"""research_fill.py — the engine half of BUG-305 and BUG-310: fill each card's unread scorecard
items, one daily try each for 14 days, and fold every finding into ONE refined record.

WHY. Each missing item in a scorecard is researched automatically, and what is found is aggregated and refined into one record,
so the experience is the same in every interface. The page cannot research, and the CLI and the app must not keep separate
copies, so this script owns the state, the order, the cap and the synthesis.

WHAT IT DOES, in order:
  1. Reads the cards and their unread gates (board.gates_for: a gate whose state is none or owed).
  2. Reads requests (the page's Ask or a card open) and findings (page-claude, connector, engine)
     from documents/state/research/exports/{requests,findings}.json, plus its own engine-findings.json.
  3. Picks today's items: opened AND awaiting cards first, then BUILD (the person is about to write to that boss),
     then opened, then awaiting, then radar; PARK, DROP and SENT cards are skipped unless asked;
     fewest tries first; a hard cap per run. Each item is tried once a day for 14 days. The try is
     counted when the item enters the plan, and a second run the same day re-emits the same plan.
     After 14 tries it reads "not found after 14 days (last tried <date>)" and stops. A hand Ask
     on an exhausted item earns exactly one more try.
  4. Synthesizes one record per card and item. A SOURCED value (an engine URL, or a connector that
     names its record or URL) beats an unverified page-claude value. Sourced values that disagree
     are both kept and flagged, never promoted. Nothing is invented: a value is only ever copied
     from a finding.
  5. Writes ONLY under documents/state/research/ (state.json, refined.json, plan.json,
     engine-findings.json). It never touches the web: the assistant session does the lookup for the
     plan's items and reports back with --record. That keeps BUG-218 (no unattended web plus write)
     closed.

USAGE
  scripts/research_fill.py [--today YYYY-MM-DD] [--cap 10] [--dry-run]
  scripts/research_fill.py --record --slug S --item K --value V --source engine --url U
                           [--record-name R] [--confidence low|med|high] [--at ISO]
  scripts/research_fill.py --record-file findings.json      (a JSON list of finding objects)

EXIT  0 ok · 2 a recorded finding was refused · 3 --today is not a real date · 4 no cards to look at (an empty look is not a pass)
      5 state.json is unreadable (refused: a reset would restart every 14-day count)
"""
import argparse
import datetime
import json
import os
import threading
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)
import board  # noqa: E402

MAX_TRIES = 14
DEFAULT_CAP = 10
UNREAD = ("none", "owed")
AWAITING = "carded_unruled"
SCHEDULED = (AWAITING, "BUILD", "RADAR")   # PARK, DROP, SENT and PASS are skipped unless asked
GATE_KEYS = {key: label for key, label, _rx in board.GATES}
SOURCES_PLAIN = ("page-claude", "engine")
CONF = {"low": 0, "med": 1, "high": 2}


class NothingToLookAt(Exception):
    """No card was read. An empty look must fail loudly, never pass."""


class BadDate(Exception):
    pass


class StateUnreadable(Exception):
    pass


class OutsideResearchDir(Exception):
    pass


# ── paths and safe writes ─────────────────────────────────────────────────────────────────────

def out_dir(repo):
    return os.path.join(repo, "documents", "state", "research")


def _write_json(repo, path, obj):
    """The only writer. A path that resolves outside documents/state/research/ is refused."""
    root = os.path.realpath(out_dir(repo))
    real = os.path.realpath(path)
    if not real.startswith(root + os.sep):
        raise OutsideResearchDir(path)
    os.makedirs(os.path.dirname(real), exist_ok=True)
    tmp = "%s.%d.%d.tmp" % (real, os.getpid(), threading.get_ident())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, real)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _read_docs(path):
    """(status, documents). status is ok, absent or unreadable; never a silent empty."""
    if not os.path.exists(path):
        return "absent", []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return "unreadable", []
    if isinstance(data, dict) and isinstance(data.get("documents"), list):
        return "ok", data["documents"]
    if isinstance(data, list):
        return "ok", data
    return "unreadable", []


# ── validation ────────────────────────────────────────────────────────────────────────────────

def _day(at):
    try:
        if isinstance(at, str) and len(at) >= 10:
            return datetime.date.fromisoformat(at[:10]).isoformat()
    except ValueError:
        pass
    return None


def _norm(value):
    return " ".join(str(value).casefold().split())


def _is_http(url):
    return isinstance(url, str) and url.lower().startswith(("http://", "https://"))


def check_finding(f, slugs):
    """(clean finding, None) or (None, reason)."""
    if not isinstance(f, dict):
        return None, "not an object"
    slug, item = f.get("slug"), f.get("item")
    if slug not in slugs:
        return None, "unknown card"
    if item not in GATE_KEYS:
        return None, "unknown item"
    value = f.get("value")
    if not isinstance(value, str) or not value.strip():
        return None, "no value"
    source = f.get("source")
    if not (source in SOURCES_PLAIN or (isinstance(source, str) and source.startswith("connector:")
                                         and len(source) > len("connector:"))):
        return None, "unknown source (use engine, page-claude or connector:<name>)"
    conf = f.get("confidence", "low")
    if conf not in CONF:
        return None, "unknown confidence"
    at = f.get("at")
    if _day(at) is None:
        return None, "unreadable time"
    # BUG-332/BUG-218: the unattended engine researches the web, so every finding IT records
    # must carry the page it came from -- accepting one with no url and storing url: None is
    # exactly the unsourced-value gap the honesty rule exists to close. Scoped to source ==
    # "engine" only: page-claude (a self-report) and a connector naming its own record (which
    # substitutes for a url) both stay accepted as "unverified", unchanged.
    if source == "engine" and not _is_http(f.get("url")):
        return None, f"engine finding for {slug}/{item} has no http(s) source url"
    rec = f.get("record")
    return {"slug": slug, "item": item, "value": value.strip(), "source": source,
            "url": f.get("url") if _is_http(f.get("url")) else None,
            "record": rec.strip() if isinstance(rec, str) and rec.strip() else None,
            "confidence": conf, "at": at}, None


def check_request(r, slugs):
    if not isinstance(r, dict):
        return None, "not an object"
    if not isinstance(r.get("id"), str) or not r["id"]:
        return None, "no id"
    if r.get("slug") not in slugs:
        return None, "unknown card"
    if r.get("item") not in GATE_KEYS:
        return None, "unknown item"
    if r.get("source") not in ("ask", "open", "decide"):
        return None, "unknown request source"
    if _day(r.get("at")) is None:
        return None, "unreadable time"
    return {"id": r["id"], "slug": r["slug"], "item": r["item"], "source": r["source"],
            "at": r["at"]}, None


def is_sourced(f):
    """An engine finding needs a URL. A connector finding needs its URL or the record it came
    from. A page-claude finding is never sourced: the page cannot verify anything."""
    if f["source"] == "engine":
        return f["url"] is not None
    if f["source"].startswith("connector:"):
        return f["url"] is not None or f["record"] is not None
    return False


# ── synthesis ─────────────────────────────────────────────────────────────────────────────────

def _view(f):
    return {"value": f["value"], "source": f["source"], "url": f["url"], "record": f["record"],
            "confidence": f["confidence"], "at": f["at"]}


def _best(fs):
    return max(fs, key=lambda f: (CONF[f["confidence"]], f["at"]))


def synthesize(findings):
    """One finding list for one item in, one record out. Sourced beats unverified; sourced
    disagreements are kept and flagged; the value is only ever copied from a finding."""
    sourced = [f for f in findings if is_sourced(f)]
    plain = [f for f in findings if not is_sourced(f)]
    if sourced:
        distinct = {}
        for f in sourced:
            distinct.setdefault(_norm(f["value"]), []).append(f)
        if len(distinct) == 1:
            best = _best(sourced)
            rec = {"status": "sourced", "value": best["value"], "source": best["source"],
                   "url": best["url"], "record": best["record"], "confidence": best["confidence"],
                   "at": best["at"], "unverified": False, "candidates": []}
        else:
            rec = {"status": "disagree", "value": None, "source": None, "url": None, "record": None,
                   "confidence": None, "at": max(f["at"] for f in sourced), "unverified": False,
                   "candidates": [_view(_best(g)) for g in distinct.values()]}
        agreed = _norm(rec["value"]) if rec["value"] is not None else None
        rec["overridden"] = [_view(f) for f in plain if _norm(f["value"]) != agreed]
        return rec
    if plain:
        best = _best(plain)
        distinct = {_norm(f["value"]) for f in plain}
        return {"status": "unverified", "value": best["value"], "source": best["source"],
                "url": best["url"], "record": best["record"], "confidence": best["confidence"],
                "at": best["at"], "unverified": True,
                "candidates": [_view(f) for f in plain] if len(distinct) > 1 else [],
                "overridden": []}
    return None


# ── state ─────────────────────────────────────────────────────────────────────────────────────

def _load_state(repo):
    path = os.path.join(out_dir(repo), "state.json")
    if not os.path.exists(path):
        return {"items": {}, "handled_requests": []}
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
        if not isinstance(st, dict) or not isinstance(st.get("items"), dict):
            raise ValueError("shape")
    except (OSError, ValueError):
        raise StateUnreadable(path)
    st.setdefault("handled_requests", [])
    return st


def _exhaust_note(st):
    return "not found after %d days (last tried %s)" % (MAX_TRIES, st.get("last_tried"))


# ── the run ───────────────────────────────────────────────────────────────────────────────────

def _collect(repo, slugs):
    """Validated requests and findings, the export status per file, and every rejection."""
    root = out_dir(repo)
    rejected, exports = [], {}
    st_req, raw_req = _read_docs(os.path.join(root, "exports", "requests.json"))
    st_fnd, raw_fnd = _read_docs(os.path.join(root, "exports", "findings.json"))
    _st_eng, raw_eng = _read_docs(os.path.join(root, "engine-findings.json"))
    exports["requests"], exports["findings"] = st_req, st_fnd
    requests, findings = [], []
    for r in raw_req:
        c, why = check_request(r, slugs)
        (requests.append(c) if c else rejected.append({"kind": "request", "why": why}))
    for f in raw_fnd + raw_eng:
        c, why = check_finding(f, slugs)
        (findings.append(c) if c else rejected.append({"kind": "finding", "why": why}))
    return requests, findings, exports, rejected


def run(repo, today=None, cap=DEFAULT_CAP, dry_run=False, spent=()):
    today = _day(today) if today else datetime.date.today().isoformat()
    if today is None or len(str(today)) != 10:
        raise BadDate("--today must be a real YYYY-MM-DD date")
    cards = board.load_cards(repo)
    if not cards:
        raise NothingToLookAt("no company cards under %s" % os.path.join(repo, "documents", "state"))
    stage_error = None
    try:
        stages, _ = board.resolve_stages(repo)
    except Exception as e:  # a stage read that fails must be said, not swallowed
        stages, stage_error = {}, "%s: %s" % (type(e).__name__, e)
    slugs = set(cards)
    requests, findings, exports, rejected = _collect(repo, slugs)
    state = _load_state(repo)
    items = state["items"]
    handled = set(state["handled_requests"])

    by_item = {}
    for f in findings:
        by_item.setdefault("%s:%s" % (f["slug"], f["item"]), []).append(f)
    synth = {k: synthesize(v) for k, v in by_item.items()}
    reqs = {}
    for r in requests:
        reqs.setdefault("%s:%s" % (r["slug"], r["item"]), []).append(r)

    def stage_of(slug):
        return stages.get(slug, AWAITING)

    unread = {}
    for slug, c in cards.items():
        if stage_of(slug) in SCHEDULED or any(
                k.startswith(slug + ":") and any(r["id"] not in handled for r in v)
                for k, v in reqs.items()):
            for key, label, gstate in c["gates"]:
                if gstate in UNREAD:
                    unread["%s:%s" % (slug, key)] = (slug, key, label)

    def pending(iid):
        return [r for r in reqs.get(iid, []) if r["id"] not in handled]

    def priority(iid, retry):
        if retry:
            return -1
        stage = stage_of(unread[iid][0])
        opened = bool(pending(iid))
        if any(r["source"] == "decide" for r in pending(iid)):
            return -2             # the card he is deciding now: ahead of everything, retries included
        if stage == AWAITING and opened:
            return 0
        return 1 if stage == "BUILD" else 2 if opened else 3 if stage == AWAITING else 4

    pri = {iid: priority(iid, False) for iid in unread}   # before requests are marked handled
    plan_ids, retry_ids, candidates, today_retry = [], set(), [], set()
    for iid in sorted(unread):
        st = items.setdefault(iid, {"tries": 0, "last_tried": None})
        rec = synth.get(iid)
        if rec and rec["status"] == "sourced":
            st["status"] = "found"
            handled.update(r["id"] for r in pending(iid))
            continue
        tries, last = st.get("tries", 0), st.get("last_tried")
        if last == today and tries and any(r["source"] == "decide" for r in pending(iid)):
            candidates.append((iid, True))          # Decide asked again: one more try today
            today_retry.add(iid)
            continue
        if last == today and tries:
            plan_ids.append(iid)
            if st.get("retry_day") == today:
                retry_ids.add(iid)
            continue
        if tries >= MAX_TRIES:
            st["status"] = "exhausted"
            if any(r["source"] == "ask" for r in pending(iid)):
                candidates.append((iid, True))
            continue
        candidates.append((iid, False))
    cand = dict(candidates)

    def rank(iid):
        """An untried item Decide asked for, then an untried item a hand request or Find asked for, then a card tried today that Decide asks for again
        (a retry never crowds out an untried request), then any other retry, then the rest by priority."""
        if iid in today_retry:
            return (2, pri[iid])
        if iid in cand and any(r["source"] == "decide" for r in pending(iid)):
            return (0, pri[iid])
        if iid in cand and not cand[iid] and pending(iid):
            return (1, pri[iid])
        return (3, pri[iid]) if (iid in cand and cand[iid]) or iid in retry_ids else (4, pri[iid])
    rk = {iid: rank(iid) for iid in unread}                  # before requests are marked handled
    candidates.sort(key=lambda c: (rk[c[0]], items[c[0]].get("tries", 0), c[0]))
    room = max(0, cap - len([i for i in plan_ids if i.split(":", 1)[0] not in spent]))
    for iid, retry in candidates[:room]:
        st = items[iid]
        st["last_tried"] = today
        if retry:
            st["retry_day"] = today
            retry_ids.add(iid)
        else:
            st["tries"] = st.get("tries", 0) + 1
        handled.update(r["id"] for r in pending(iid))
        plan_ids.append(iid)
    plan_ids.sort(key=lambda i: (rk[i], items[i]["tries"], i))

    records = {}
    for iid in sorted(set(unread) | set(synth)):
        slug, key = iid.split(":", 1)
        st = items.get(iid, {"tries": 0, "last_tried": None})
        rec = synth.get(iid) or {"status": "open", "value": None, "source": None, "url": None,
                                 "record": None, "confidence": None, "at": None,
                                 "unverified": False, "candidates": [], "overridden": []}
        rec = dict(rec)
        exhausted = (iid in unread and st.get("tries", 0) >= MAX_TRIES
                     and st.get("last_tried") != today and iid not in plan_ids
                     and rec["status"] != "sourced")
        if exhausted and rec["status"] == "open":
            rec["status"] = "exhausted"
        rec.update({"id": iid, "slug": slug, "item": key, "label": GATE_KEYS[key],
                    "unread": iid in unread, "tries": st.get("tries", 0),
                    "last_tried": st.get("last_tried"),
                    "note": _exhaust_note(st) if exhausted else None})
        rq = max(reqs.get(iid, []), key=lambda r: r["at"], default=None)
        if rq is None:
            rec["request"] = None
        else:
            answered = any(f["at"] >= rq["at"] for f in by_item.get(iid, []))
            rec["request"] = {"id": rq["id"], "source": rq["source"], "at": rq["at"],
                              "status": "answered" if answered
                              else "picked_up" if rq["id"] in handled else "waiting"}
        records[iid] = rec

    plan = [{"id": i, "slug": unread[i][0], "item": unread[i][1], "label": unread[i][2],
             "tries": items[i]["tries"], "retry": i in retry_ids,
             "awaiting": stage_of(unread[i][0]) == AWAITING, "opened": bool(reqs.get(i))}
            for i in plan_ids]
    counts = {"cards": len(cards), "unread_items": len(unread), "plan": len(plan), "cap": cap}
    for s in ("sourced", "unverified", "disagree", "exhausted"):
        counts[s] = sum(1 for r in records.values() if r["status"] == s)
    summary = dict(counts, plan=plan, exports=exports, rejected=len(rejected),
                   rejected_detail=rejected, stage_error=stage_error, today=today, dry_run=dry_run)

    if not dry_run:
        state["handled_requests"] = sorted(handled)
        root = out_dir(repo)
        _write_json(repo, os.path.join(root, "state.json"), state)
        _write_json(repo, os.path.join(root, "refined.json"), {
            "generated": today, "exports": exports, "rejected": rejected, "records": records})
        _write_json(repo, os.path.join(root, "plan.json"), {
            "date": today, "cap": cap, "items": plan,
            "exhausted": sorted(i for i, r in records.items() if r["status"] == "exhausted"
                                or (r["note"] or "").startswith("not found"))})
    return summary


def record(repo, finding, today=None, m2_quote=None):
    """Add one finding to the engine's own file, then re-synthesize (no new picks). (ok, why). `m2_quote` is passed ONLY by app/engine.py after
    its fetch and quote check (M2): the record is then stamped m2 true and carries the quote. check_finding drops every key it does not know,
    so a CLI or a JSON file can never stamp a record, and the feed carries only stamped ones."""
    cards = board.load_cards(repo)
    if not cards:
        raise NothingToLookAt("no company cards")
    clean, why = check_finding(finding, set(cards))
    if clean is None:
        return False, why
    path = os.path.join(out_dir(repo), "engine-findings.json")
    _status, docs = _read_docs(path)
    if m2_quote:
        clean = dict(clean, m2=True, quote=str(m2_quote)[:400])
    if clean not in docs and (m2_quote or clean not in [c for c in (check_finding(d, set(cards))[0] for d in docs) if c]):
        docs = docs + [clean]
        _write_json(repo, path, {"documents": docs})
    run(repo, today=today, cap=0)
    return True, "recorded"


# ── command line ──────────────────────────────────────────────────────────────────────────────

def _line(s):
    return ("research_fill %s: cards %d · unread %d · plan %d/%d · sourced %d · unverified %d · "
            "disagree %d · exhausted %d · rejected %d%s"
            % (s["today"], s["cards"], s["unread_items"], s["plan"] if isinstance(s["plan"], int)
               else len(s["plan"]), s["cap"], s["sourced"], s["unverified"], s["disagree"],
               s["exhausted"], s["rejected"], " · DRY RUN" if s["dry_run"] else ""))


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Daily fill and synthesis of missing scorecard items.")
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--today", default=None)
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--record-file")
    for a in ("slug", "item", "value", "source", "url", "record-name", "confidence", "at"):
        ap.add_argument("--" + a)
    args = ap.parse_args(argv)
    today = args.today or datetime.date.today().isoformat()
    if _day(today) != today:
        print("research_fill: --today %r is not a real YYYY-MM-DD date." % today)
        return 3
    try:
        if args.record or args.record_file:
            if args.record_file:
                _st, batch = _read_docs(args.record_file)
                if _st != "ok":
                    print("record file %s: %s" % (args.record_file, _st))
                    return 2
                # --record stamps "now" on a finding with no time, so a batch row must too (98's finding).
                # Only a MISSING or blank `at` is filled; a present but unreadable one is still refused.
                batch = [dict(d, at=_now()) if isinstance(d, dict) and not str(d.get("at") or "").strip() else d
                         for d in batch]
            else:
                batch = [{"slug": args.slug, "item": args.item, "value": args.value,
                          "source": args.source, "url": args.url, "record": args.record_name,
                          "confidence": args.confidence or "low",
                          "at": args.at or _now()}]
            bad = 0
            for f in batch:
                ok, why = record(args.repo, f, today=today)
                print(("recorded %s:%s" % (f.get("slug"), f.get("item"))) if ok
                      else "refused (%s): %s:%s" % (why, f.get("slug") if isinstance(f, dict) else "?",
                                                    f.get("item") if isinstance(f, dict) else "?"))
                bad += 0 if ok else 1
            return 2 if bad else 0
        s = run(args.repo, today=today, cap=args.cap, dry_run=args.dry_run)
    except NothingToLookAt as e:
        print("research_fill: nothing to look at (%s). Refusing to report a clean pass." % e)
        return 4
    except StateUnreadable as e:
        print("research_fill: state file unreadable (%s). Fix or move it; a reset would restart "
              "every 14-day count." % e)
        return 5
    print(_line(s))
    for i in s["plan"]:
        print("  %s%s (try %d)" % (i["id"], " RETRY" if i["retry"] else "", i["tries"]))
    if s["stage_error"]:
        print("  stage read failed, all cards treated as awaiting: %s" % s["stage_error"])
    if any(v != "ok" for v in s["exports"].values()):
        print("  exports: %s" % ", ".join("%s %s" % kv for kv in sorted(s["exports"].items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
