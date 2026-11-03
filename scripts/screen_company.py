#!/usr/bin/env python3
"""screen_company.py: run the screen on ONE company, with the kit's own checks, and say what passed, what was blocked, what is unknown and when it will be known.

WHY (slice B of "the app copies the CLI"). The terminal screens a company before it asks anyone anything: dedup, the blocked list, the live-role (ATS) check, and the
unread scorecard items research_fill plans. The app's local server (app/serve.py, POST /screen/run) calls THIS script, so the page never re-derives a verdict. Nothing here
decides for the person: it reports reasons, and the card asks the one decision after.

CHECKS, each one {key, label, state, reason, known, source}; state is "clear", "blocked" or "unknown":
  blocked    local_gates.gate_blocked over filter_blocked.classify and the person's INDUSTRY_VETO / VETO_EMPLOYERS (the same code the gates run). A fail is "blocked".
  dedup      local_gates.gate_dedup over check_dup.prior_contact. A warn (a recorded prior contact) is "blocked" for Build: it is a stop, not a soft note.
  live_role  scripts/check_ats.py "<company>" (exit 0 live in-lane role, 1 no live role = a radar reach, 2 unresolved). Never invented: a board that cannot be read is "unknown".
  research   the card's unread scorecard items (board.load_cards) with research_fill's own state (tries, last tried); a company with no card yet names the items it has not read.

A "blocked" check means `blocked: true`; the page offers no Build for it. `unknown` always carries `known`: when it will be known, in plain words.

USAGE  python3 scripts/screen_company.py --repo DIR --company "Name" [--slug S] [--ats-script PATH] [--ats-timeout SECONDS]
OUTPUT one JSON object on stdout. EXIT 0 answered · 2 no company name.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import board  # noqa: E402
import local_gates  # noqa: E402

SOURCE = "local check"
ATS_TIMEOUT = 60
LOCAL_ITEM_KEYS = ("dedup", "blocked", "live_req")
UNREAD = local_gates.UNREAD
UNREAD_NAMED = [label for key, label, _rx in board.GATES if key not in LOCAL_ITEM_KEYS]
READ_COST = "about a minute for each item, 5 items a run and 30 a day"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plain(text):
    """A reason as plain words: the blocked list is markdown, so its bold marks and backticks are dropped."""
    return re.sub(r"\s+", " ", re.sub(r"[*`]{1,3}", "", str(text or ""))).strip()


def _check(key, label, state, reason, known=None):
    out = {"key": key, "label": label, "state": state, "reason": plain(reason), "source": SOURCE}
    if state == "unknown":
        out["known"] = known or "not known yet"
    return out


def check_blocked(repo, company, at):
    import filter_blocked
    industry, employers = local_gates.industry_veto_patterns(repo)
    counts = local_gates.blocked_list_nonempty(repo) or bool(industry) or bool(employers)
    e = local_gates.gate_blocked(company, filter_blocked.classify, at, counts, industry, employers)
    label = "Blocked list and vetoed industries"
    if e["state"] == "fail":
        return _check("blocked", label, "blocked", re.sub(r"^(on the blocked list:)\s*[-*+]\s*", r"\1 ", e["why"]))
    if e["state"] == "pass":
        return _check("blocked", label, "clear", e["why"])
    return _check("blocked", label, "unknown", e["why"],
                  "stays unknown until your blocked list or your industry vetoes have an entry to check against")


def check_dedup(repo, company, slug, at):
    import check_dup
    counts = local_gates.dedup_sources_nonempty(repo)
    e = local_gates.gate_dedup(slug, company, [slug], check_dup.prior_contact, at, counts)
    label = "Prior contact"
    if e["state"] == "warn":
        return _check("dedup", label, "blocked", e["why"])
    if e["state"] == "pass":
        return _check("dedup", label, "clear", e["why"])
    return _check("dedup", label, "unknown", e["why"],
                  "stays unknown until you have a send log or a contact list to check against")


def _first(text, prefix):
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(prefix):
            return s[len(prefix):].strip()
    return ""


def check_live_role(company, ats_script, timeout):
    label = "Live role"
    argv = [sys.executable, ats_script, company]
    try:
        proc = subprocess.run(argv, shell=False, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return _check("live_role", label, "unknown", "the careers-board check took too long",
                      "the next time this card opens, the check runs again")
    except OSError as err:
        return _check("live_role", label, "unknown", "the careers-board check could not run (%s)" % err.__class__.__name__,
                      "the next time this card opens, the check runs again")
    out = proc.stdout.decode("utf-8", "replace")
    code = proc.returncode
    if code == 0:
        role = _first(out, "▸")
        return _check("live_role", label, "clear", "a live in-lane role is open" + (": " + role if role else ""))
    if code == 1:
        return _check("live_role", label, "clear",
                      "no live in-lane role on its careers board, so this is a radar reach, not an application")
    if "AMBIGUOUS" in out:
        return _check("live_role", label, "unknown", "more than one company board shares this name, so no live-role answer was given",
                      "when you pick the right board (the terminal's check_ats --token) or open its careers page")
    return _check("live_role", label, "unknown", "no careers board matched this name (a custom site or another ATS)",
                  "when someone opens its careers page and reads it by hand")


def check_research(repo, company, slug):
    label = "Still to read"
    cards = {}
    try:
        cards = board.load_cards(repo)
    except Exception:
        cards = {}
    card = cards.get(slug)
    if not card:
        names = ", ".join(n.lower() for n in UNREAD_NAMED)
        return _check("research", label, "unknown", "not read yet: " + names,
                      "reading needs a card on file; when this company has one, opening it in Find starts the read (%s)" % READ_COST)
    unread = [(k, l) for k, l, st in card["gates"] if st in UNREAD and k not in LOCAL_ITEM_KEYS]
    if not unread:
        return _check("research", label, "clear", "every scorecard item on this card has been read")
    try:
        import research_fill
        state_items = research_fill._load_state(repo)["items"]
    except Exception:
        state_items = {}
    tries = max([state_items.get("%s:%s" % (slug, k), {}).get("tries", 0) for k, _l in unread] or [0])
    names = ", ".join(l.lower() for _k, l in unread)
    if tries >= research_fill_max():
        when = "these were tried for %d days and not found; pressing Update asks for one more try" % tries
    else:
        when = "Find asks the engine to read them when this card opens (%s); the line under this one says where they stand" % READ_COST
    out = _check("research", label, "unknown", "not read yet: " + names, when)
    out["has_card"] = True
    out["items"] = [k for k, _l in unread]
    return out


def research_fill_max():
    try:
        import research_fill
        return research_fill.MAX_TRIES
    except Exception:
        return 14


def screen(repo, company, slug=None, ats_script=None, ats_timeout=ATS_TIMEOUT):
    company = (company or "").strip()
    slug = slug or re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    at = _now()
    checks = [check_blocked(repo, company, at), check_dedup(repo, company, slug, at)]
    # A stopped company does not get its careers board read: nothing it says could change the answer, and it saves a network call.
    if not any(c["state"] == "blocked" for c in checks):
        checks.append(check_live_role(company, ats_script or os.path.join(HERE, "check_ats.py"), ats_timeout))
    checks.append(check_research(repo, company, slug))
    blocked = [c for c in checks if c["state"] == "blocked"]
    return {"company": company, "slug": slug, "at": at, "blocked": bool(blocked),
            "stop": blocked[0]["reason"] if blocked else None, "checks": checks}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Screen one company with the kit's own checks.")
    ap.add_argument("--repo", default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    ap.add_argument("--company", required=True)
    ap.add_argument("--slug")
    ap.add_argument("--ats-script")
    ap.add_argument("--ats-timeout", type=int, default=ATS_TIMEOUT)
    a = ap.parse_args(argv)
    if not a.company.strip():
        print(json.dumps({"error": "no company name"}))
        return 2
    print(json.dumps(screen(a.repo, a.company, a.slug, a.ats_script, a.ats_timeout), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
