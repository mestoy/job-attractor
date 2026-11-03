#!/usr/bin/env python3
"""boss_fill.py — plan the boss lookups that turn a card's boss into a TWO-SOURCE verified boss, and
record what the assistant finds THROUGH boss_registry.py's own CLI.

WHY. The 2026-09-21 address dry run found the real bottleneck: 10 awaiting cards have a boss the
feed cannot call verified, and address_fill.py only works on verified bosses. Nothing owned the
second-source lookup.

TWO TRUTHS, KEPT IN STEP. The feed's "verified" comes from the CARD's Boss section text
(board.boss_confidence wants "two-source" / "CONFIRMED") plus a person name in the card header. The
SEND gate (mail-draft.sh, boss_registry.py check) reads the REGISTRY. A registry row alone does not
flip the card, and a card edit alone does not satisfy the send gate. So this script writes the
registry (through its CLI) and emits the card lines built from the SAME two source URLs the registry
row holds; they cannot drift. THE CARD IS NOT MINE: 98's /app step applies card_boss_line and
card_header_boss (one writer per file).

WHAT IT DOES
  1. Plans: every BUILD or awaiting card whose boss is not two-source verified. Mode "find" when the
     card names no person, "second_source" when it names one. No web here (BUG-218): the assistant
     looks things up and reports back with --record.
  2. Records each source through `scripts/boss_registry.py add` (a subprocess, never state.py or
     boss.jsonl directly), so its vocabulary, --why rule, Pindrop rule and same-person-delivered
     refusal all apply. Its refusal is surfaced verbatim and this script's own store is unchanged.
     --next-target-ok is never passed.
  3. Counts a SECOND SOURCE only when: type linkedin-live or company-page (after the registry's
     aggregator demotion), role current, the same person, and a different hostname from the first.
     press-release is a lead. secondhand, unverified and every aggregator never count.
  4. Two qualifying sources -> the registry row becomes `finalist` (the caller must give --why) and
     the result carries card_boss_line and card_header_boss.
  5. Cadence: once a day per card for 14 days, cap 5 per run, BUILD before awaiting; after 14 it
     reads "no second source found after 14 days (last tried <date>)" ("no boss found ..." in find
     mode). A hand Ask (exports/requests.json) earns one more try.
  Writes only under documents/state/boss-fill/, plus the registry's own row via its CLI.

USAGE
  scripts/boss_fill.py [--today YYYY-MM-DD] [--cap 5] [--dry-run]
  scripts/boss_fill.py --record --slug S --person "Name" --title T --type linkedin-live|company-page|
        press-release|secondhand|unverified --url U --role-status current|departed|unverified
        --boss-read likely-boss|direct-boss|founder-fallback|hiring-authority|not-the-boss
        [--why "..."] [--at ISO]

EXIT  0 ok · 2 record refused before the registry · 3 --today not a real date · 4 no cards
      5 state.json unreadable · 7 the registry CLI refused (its message is printed)
"""
import argparse
import datetime
import json
import os
import threading
import re
import subprocess
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)
import build_app_feed as baf  # noqa: E402  (split_boss, gate_bodies: read only)
import boss_registry as reg  # noqa: E402  (vocabulary and aggregator demotion, read only)
import research_fill as rf  # noqa: E402  (_day, _read_docs)

board = baf.board
MAX_TRIES = 14
DEFAULT_CAP = 5
AWAITING = "carded_unruled"
SCHEDULED = ("BUILD", AWAITING)
QUALIFYING = ("linkedin-live", "company-page")
URL_TYPES = ("linkedin-live", "company-page", "press-release")
LABEL = {"linkedin-live": "LinkedIn live", "company-page": "company page"}
REGISTRY_CLI = os.path.join(HERE, "boss_registry.py")


class NothingToLookAt(Exception):
    pass


class StateUnreadable(Exception):
    pass


class OutsideBossFillDir(Exception):
    pass


class BadDate(Exception):
    pass


# ── paths and guarded writes ──────────────────────────────────────────────────────────────────

def out_dir(repo):
    return os.path.join(repo, "documents", "state", "boss-fill")


def _write_json(repo, path, obj):
    root = os.path.realpath(out_dir(repo))
    real = os.path.realpath(path)
    if not real.startswith(root + os.sep):
        raise OutsideBossFillDir(path)
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


# ── sources ───────────────────────────────────────────────────────────────────────────────────

def _key(person):
    return " ".join(re.findall(r"[a-z]+", str(person).lower()))


def _host(url):
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _is_url(u):
    return isinstance(u, str) and u.lower().startswith(("http://", "https://")) and bool(_host(u))


def check_source(s, slugs):
    """(clean, None) or (None, reason). Vocabulary beyond these basics is the registry's to refuse."""
    if not isinstance(s, dict):
        return None, "not an object"
    if s.get("slug") not in slugs:
        return None, "unknown card"
    person = s.get("person")
    if not isinstance(person, str) or baf.person_name(person.strip()) is None:
        return None, "person is not a real person name"
    typ = s.get("type")
    if typ not in reg.VERIFIED:
        return None, "type must be one of %s" % ", ".join(reg.VERIFIED)
    url = s.get("url")
    if typ in URL_TYPES and not _is_url(url):
        return None, "a %s source needs an http(s) url" % typ
    if url and not _is_url(url):
        return None, "url is not an http(s) address"
    if rf._day(s.get("at")) is None:
        return None, "unreadable time"
    eff, _note = reg.demote_if_aggregator(url, typ)
    return {"slug": s["slug"], "person": person.strip(), "title": str(s.get("title") or "").strip(),
            "type": typ, "effective_type": eff, "url": url or "", "host": _host(url),
            "role_status": s.get("role_status") or "unverified",
            "boss_read": s.get("boss_read") or "", "at": s["at"]}, None


def assess(sources):
    """Best person group for one card: qualifying sources on distinct hosts, role, readiness."""
    groups = {}
    for s in sources:
        groups.setdefault(_key(s["person"]), []).append(s)
    best = None
    for g in groups.values():
        g = sorted(g, key=lambda s: s["at"])
        qual, hosts = [], set()
        for s in g:
            if s["effective_type"] in QUALIFYING and s["role_status"] == "current" and s["host"] not in hosts:
                hosts.add(s["host"])
                qual.append(s)
        departed = g[-1]["role_status"] == "departed"
        info = {"person": g[-1]["person"], "title": next((s["title"] for s in reversed(g) if s["title"]), ""),
                "sources": g, "qualifying": qual, "departed": departed,
                "ready": len(qual) >= 2 and not departed}
        rank = (info["ready"], len(qual), g[-1]["at"])
        if best is None or rank > best[0]:
            best = (rank, info)
    return best[1] if best else None


def card_lines(info, date):
    a, b = info["qualifying"][0], info["qualifying"][1]
    title = re.split(r"\s+[—–]\s+", info["title"])[0].strip()
    who = "%s, %s" % (info["person"], title) if title else info["person"]
    return {"card_header_boss": "boss " + who,
            "card_boss_line": "%s: CONFIRMED two-source. %s (%s); %s (%s). Verified %s." % (
                who, LABEL[a["effective_type"]], a["url"], LABEL[b["effective_type"]], b["url"], date),
            "registry_source_urls": [a["url"], b["url"]]}


# ── the run ───────────────────────────────────────────────────────────────────────────────────

def run(repo, today=None, cap=DEFAULT_CAP, dry_run=False, hold=None, spent=()):
    """`hold(info) -> bool`: the engine's S4 gate. A person group it holds is NOT two_source_ready and gets no card lines (the two
    sources came from the web search and the person has not confirmed them).
    `spent`: slugs the engine already READ today. They stay in the plan but take no slot of the cap, so a card never read today is not crowded out by them."""
    today = rf._day(today) if today else datetime.date.today().isoformat()
    if today is None:
        raise BadDate("--today must be a real YYYY-MM-DD date")
    cards = board.load_cards(repo)
    if not cards:
        raise NothingToLookAt("no company cards under %s" % os.path.join(repo, "documents", "state"))
    try:
        stages, _ = board.resolve_stages(repo)
        stage_error = None
    except Exception as e:  # said, never swallowed
        stages, stage_error = {}, "%s: %s" % (type(e).__name__, e)
    slugs = set(cards)
    _s, raw = rf._read_docs(os.path.join(out_dir(repo), "sources.json"))
    by_slug = {}
    for d in raw:
        clean, _why = check_source(d, slugs)
        if clean:
            by_slug.setdefault(clean["slug"], []).append(clean)
    exp_status, raw_r = rf._read_docs(os.path.join(out_dir(repo), "exports", "requests.json"))
    asks = {}
    for r in raw_r:
        if isinstance(r, dict) and isinstance(r.get("id"), str) and r.get("slug") in slugs \
                and r.get("source") in ("ask", "open", "decide") and rf._day(r.get("at")):
            asks.setdefault(r["slug"], []).append(r)

    state = _load_state(repo)
    items, handled = state["items"], set(state["handled_requests"])
    unhandled = lambda slug: [r for r in asks.get(slug, []) if r["id"] not in handled]  # noqa: E731
    records, eligible, retry_ids, candidates, today_retry = {}, [], set(), [], set()
    for slug in sorted(cards):
        c = cards[slug]
        stage = stages.get(slug, AWAITING)
        boss = baf.split_boss(c["head"]["boss"], c["boss_conf"])
        info = assess(by_slug.get(slug, []))
        base = {"slug": slug, "company": c["head"]["company"], "status": "open", "person": None,
                "title": None, "sources": [], "qualifying_sources": 0, "two_source_ready": False,
                "card_boss_line": None, "card_header_boss": None, "registry_source_urls": [],
                "tries": 0, "last_tried": None, "note": None}
        if info:
            base.update(person=info["person"], title=info["title"], qualifying_sources=len(info["qualifying"]),
                        sources=[{k: s[k] for k in ("type", "effective_type", "url", "host", "role_status", "at")}
                                 for s in info["sources"]])
        if boss["verified"]:
            if info:
                records[slug] = dict(base, status="card_verified")
            handled.update(r["id"] for r in unhandled(slug))
            continue
        if stage not in SCHEDULED:
            if info:
                records[slug] = dict(base, status="one_source" if info["qualifying"] else "open")
            continue
        mode = "second_source" if baf.person_name(boss["name"]) else "find"
        st = items.setdefault(slug, {"tries": 0, "last_tried": None})
        base.update(mode=mode, stage=stage, boss=boss)
        records[slug] = base
        if info and info["ready"] and hold and hold(info):
            info = dict(info, ready=False)
            base.update(status="candidate_unconfirmed", note="found on the web; waiting for your confirmation")
        if info and info["ready"]:
            base.update(status="two_source_ready", two_source_ready=True,
                        **card_lines(info, max(s["at"] for s in info["qualifying"])[:10]))
            handled.update(r["id"] for r in unhandled(slug))
            continue
        if info and info["departed"]:
            base.update(status="departed", note="recorded as departed from %s; find the current boss"
                        % c["head"]["company"])
        elif info and info["qualifying"]:
            base["status"] = "one_source"
        eligible.append(slug)
        tries, last = st.get("tries", 0), st.get("last_tried")
        if last == today and tries and any(r["source"] == "decide" for r in unhandled(slug)):
            candidates.append((slug, True))         # Decide asked again: one more try today
            today_retry.add(slug)
            continue
        if last == today and tries:
            if st.get("retry_day") == today:
                retry_ids.add(slug)
            continue
        if tries >= MAX_TRIES:
            if any(r["source"] == "ask" for r in unhandled(slug)):
                candidates.append((slug, True))
            continue
        candidates.append((slug, False))

    def rank(slug, retry):
        """-4 a card never tried today that Decide asked for, -3 one a hand request or Find asked for, -2 a card tried today that Decide asks for again
        (a retry never crowds out an untried request), -1 any other retry, then BUILD before the rest."""
        pending = unhandled(slug)
        if slug in today_retry:
            return -2
        if any(r["source"] == "decide" for r in pending):
            return -4
        if pending and slug in cand and not retry:
            return -3
        return -1 if retry or slug in retry_ids else (0 if stages.get(slug, AWAITING) == "BUILD" else 1)
    cand = dict(candidates)
    rk = {slug: rank(slug, cand.get(slug, False)) for slug in eligible}   # before requests are marked handled
    planned = [s for s in eligible if items[s].get("last_tried") == today and items[s].get("tries") and s not in today_retry]
    candidates.sort(key=lambda t: (rk[t[0]], items[t[0]].get("tries", 0), t[0]))
    room = max(0, cap - len([p for p in planned if p not in spent]))
    for slug, retry in candidates:
        if room <= 0:
            continue
        room -= 1
        st = items[slug]
        st["last_tried"] = today
        if retry:
            st["retry_day"] = today
            retry_ids.add(slug)
        else:
            st["tries"] = st.get("tries", 0) + 1
        handled.update(r["id"] for r in unhandled(slug))
        planned.append(slug)
    planned.sort(key=lambda s: (rk[s], items[s]["tries"], s))

    for slug in eligible:
        st, r = items[slug], records[slug]
        r.update(tries=st.get("tries", 0), last_tried=st.get("last_tried"))
        if st.get("tries", 0) >= MAX_TRIES and st.get("last_tried") != today and slug not in planned \
                and r["status"] in ("open", "one_source"):
            r["status"] = "none_found"
            r["note"] = "no %s found after %d days (last tried %s)" % (
                "second source" if r["mode"] == "second_source" else "boss", MAX_TRIES, st.get("last_tried"))

    plan = []
    for s in planned:
        r = records[s]
        c = cards[s]
        info = assess(by_slug.get(s, []))
        have = [q["url"] for q in info["qualifying"]] if info else []
        if r["mode"] == "find":
            need = "name the boss, then two independent sources (LinkedIn live and the company page)"
        elif not have:
            need = "two independent sources for %s (LinkedIn live and the company page)" % r["boss"]["name"]
        else:
            need = "one more source for %s on a host other than %s" % (
                info["person"], ", ".join(sorted({_host(u) for u in have})))
        body = baf.gate_bodies(c["text"]).get("boss") or ""
        plan.append({"slug": s, "company": r["company"], "mode": r["mode"], "stage": r["stage"],
                     "boss": {"name": r["boss"]["name"],
                              "title": re.split(r"\s+[—–]\s+", r["boss"]["title"])[0].strip()},
                     "need": need, "have": have, "known_urls": board.URL_RE.findall(body)[:4],
                     "tries": items[s]["tries"], "retry": s in retry_ids})
    for r in records.values():
        r.pop("boss", None)
        r.pop("stage", None)
        r.pop("mode", None)
    count = lambda x: sum(1 for r in records.values() if r["status"] == x)  # noqa: E731
    summary = {"today": today, "cards": len(cards), "eligible": len(eligible), "plan": plan, "cap": cap,
               "two_source_ready": count("two_source_ready"), "one_source": count("one_source"),
               "none_found": count("none_found"), "departed": count("departed"),
               "stage_error": stage_error, "exports": {"requests": exp_status}, "dry_run": dry_run}
    if not dry_run:
        state["handled_requests"] = sorted(handled)
        root = out_dir(repo)
        _write_json(repo, os.path.join(root, "state.json"), state)
        _write_json(repo, os.path.join(root, "results.json"), {"generated": today, "records": records})
        _write_json(repo, os.path.join(root, "plan.json"), {
            "date": today, "cap": cap, "items": plan,
            "none_found": sorted(s for s, r in records.items() if r["status"] == "none_found")})
    return summary


# ── recording, through the registry's own CLI ─────────────────────────────────────────────────

def _registry_add(repo, registry, args):
    try:
        p = subprocess.run([sys.executable, registry, "add"] + args, capture_output=True, text=True,
                           timeout=60, env=dict(os.environ, CLAUDE_PROJECT_DIR=repo))
    except (OSError, subprocess.SubprocessError) as e:
        return False, "registry CLI could not run: %s" % e
    if p.returncode != 0:
        return False, ((p.stderr or "") + (p.stdout or "")).strip() or "registry exit %d" % p.returncode
    return True, p.stdout.strip()


def record(repo, source, today=None, why="", registry=None, hold=None):
    """Record one source. (ok, message). The registry writes first; only its acceptance is stored."""
    registry = registry or REGISTRY_CLI
    cards = board.load_cards(repo)
    if not cards:
        raise NothingToLookAt("no company cards")
    clean, refusal = check_source(source, set(cards))
    if clean is None:
        return False, refusal
    company = cards[clean["slug"]]["head"]["company"]
    path = os.path.join(out_dir(repo), "sources.json")
    _s, docs = rf._read_docs(path)
    have = [d for d in (check_source(x, set(cards))[0] for x in docs) if d]
    after = [x for x in have if x != clean] + [clean]
    same = [x for x in after if x["slug"] == clean["slug"]]
    before_ready = (assess([x for x in same if x != clean]) or {}).get("ready", False)
    info = assess(same)
    person_info = assess([x for x in same if _key(x["person"]) == _key(clean["person"])])
    qualifies = clean["effective_type"] in QUALIFYING and clean["role_status"] == "current"
    # A lead after a finalist stays out of the registry (a later candidate row would supersede the
    # finalist, latest ts wins), EXCEPT a departure: the send gate must see that the boss left.
    stored_only = before_ready and not qualifies and clean["role_status"] != "departed"
    msg = "recorded"
    if not stored_only:
        finalist = bool(person_info and person_info["ready"])
        held = bool(finalist and hold and hold(person_info))
        if held:
            finalist = False
        verified = person_info["qualifying"][0]["effective_type"] if finalist else clean["effective_type"]
        urls = [q["url"] for q in person_info["qualifying"][:2]] if finalist else ([clean["url"]] if clean["url"] else [])
        args = ["--person", clean["person"], "--company", company,
                "--verdict", "finalist" if finalist else "candidate",
                "--boss-read", clean["boss_read"], "--verified", verified,
                "--role-status", clean["role_status"], "--title", clean["title"],
                "--date", clean["at"][:10]]
        for u in urls:
            args += ["--source-url", u]
        if clean["type"] == "linkedin-live" and clean["url"]:
            args += ["--linkedin", clean["url"]]
        if why:
            args += ["--why", why]
        ok, out = _registry_add(repo, registry, args)
        if not ok:
            return False, "registry refused: " + out
        msg = out.splitlines()[-1] if out else msg
        if held:
            msg = "held as a candidate until you confirm: " + msg
    else:
        msg = "kept as a lead; the two-source finalist row stays as it is"
    if clean not in have:
        _write_json(repo, path, {"documents": have + [clean]})
    run(repo, today=today, cap=0, hold=hold)
    return True, msg


# ── command line ──────────────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="Plan boss lookups; record sources through boss_registry.py.")
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--today")
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--record", action="store_true")
    for a in ("slug", "person", "title", "type", "url", "role-status", "boss-read", "why", "at"):
        ap.add_argument("--" + a)
    args = ap.parse_args(argv)
    today = args.today or datetime.date.today().isoformat()
    if rf._day(today) != today:
        print("boss_fill: --today %r is not a real YYYY-MM-DD date." % today)
        return 3
    try:
        if args.record:
            src = {"slug": args.slug, "person": args.person, "title": args.title, "type": args.type,
                   "url": args.url, "role_status": args.role_status or "unverified",
                   "boss_read": args.boss_read or "likely-boss",
                   "at": args.at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            ok, msg = record(args.repo, src, today=today, why=args.why or "")
            print(("%s: %s" % (args.slug, msg)) if ok else "refused (%s): %s" % (msg, args.slug))
            return 0 if ok else (7 if msg.startswith("registry") else 2)
        s = run(args.repo, today=today, cap=args.cap, dry_run=args.dry_run)
    except NothingToLookAt as e:
        print("boss_fill: nothing to look at (%s). Refusing to report a clean pass." % e)
        return 4
    except StateUnreadable as e:
        print("boss_fill: state file unreadable (%s). Fix or move it; a reset would restart every "
              "14-day count." % e)
        return 5
    print("boss_fill %s: cards %d · eligible %d · plan %d/%d · two-source ready %d · one source %d · "
          "none found %d · departed %d%s"
          % (s["today"], s["cards"], s["eligible"], len(s["plan"]), s["cap"], s["two_source_ready"],
             s["one_source"], s["none_found"], s["departed"], " · DRY RUN" if s["dry_run"] else ""))
    for i in s["plan"]:
        print("  %s [%s] %s%s try %d: %s" % (i["slug"], i["mode"], i["boss"]["name"] or "(no boss named)",
                                             " RETRY" if i["retry"] else "", i["tries"], i["need"]))
    if s["stage_error"]:
        print("  stage read failed, all cards treated as awaiting: %s" % s["stage_error"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
