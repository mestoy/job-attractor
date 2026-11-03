#!/usr/bin/env python3
"""local_gates.py: resolve the two gates a card can be settled on THIS MACHINE, for every card, with the code that already exists.

COUNTS (slice 3a/3b, plan-app-onboarding-parity-2026-10-07.md §0b B1, §0c C1/C2). A gate with an answer unlocks Decide; a gate that
merely had nothing to check against must never read as a quiet pass. Every entry this module writes now carries a `counts` boolean
alongside its state:

  blocked   counts only when the blocked list OR the person's own INDUSTRY_VETO OR VETO_EMPLOYERS carries real content; both
            empty gives "not asked yet", counts False, whatever `classify()` would otherwise have answered. INDUSTRY_VETO and
            VETO_EMPLOYERS are read straight off kit_config, never off the `no_industry_vetoes`/`NO_INDUSTRY_VETO` marker (C1):
            that marker is written both for a CHOSEN "None" and for the untouched Setup default, so it cannot tell the two apart
            and a marker that never counts is the only safe reading of it.
  dedup     counts only when the send log or a contact store (never the card's own queue or card files -- a self-match proves
            nothing about anyone else) carries at least one row.

LOCAL_KEYS stays exactly two (C2): industry rides the `blocked` gate rather than adding an eleventh row. `gate_blocked` matches
the company's own name against the person's INDUSTRY_VETO words and VETO_EMPLOYERS entries, the same local, no-network check as
the blocked list itself.

WHY (f2's slice, 2026-09-21, from 98's plan). 81 of the feed's dedup and blocked gates read UNRESOLVED (68 dedup, 13 blocked) on cards that simply
have no such section, or whose wording the gate reader cannot parse (the "🔴 ALREADY-SEEN ... self-match" line). Both questions are answered
from local files, so nothing needs the web:

  blocked   filter_blocked.classify(company)   -> pass (not on the blocked list) or fail (the entry is quoted)
  dedup     check_dup.prior_contact(company)   -> pass (no recorded contact) or warn (a real prior contact)

Only these two gates run here, and GATE_STATES is not widened: the states are the feed's own (pass, warn, fail, unresolved). The company is read
with board.card_company (the ONE place a name is read from a header), never from the card's own gate prose, so a card with no section or an odd one
still gets an answer.

SELF-MATCH VERSUS PRIOR CONTACT (approved defaults). A match against the card's OWN files (documents/state/<slug>-...) or its own QUEUE row is a
self-match and counts as clean: the pipeline has always known this candidate. A match in the send log, another card or a contact store is a prior
contact, which is a WARN. The blocked list belongs to the blocked gate and is not counted twice in dedup. A weak, prose-only or staged-draft
mention is not a recorded contact: a pass that says so.

FAIL LOUD. A check that returns ERROR or raises leaves that gate UNRESOLVED with the reason, never pass. A card whose company cannot be read is
UNRESOLVED on both gates and no check runs for it.

OUTPUT documents/state/local-gates.json is exactly {slug: {"blocked"|"dedup": {state, why, at, source: "local check"}}}. `overlay_gates` is the pure
function the feed builder calls: a local blocked FAIL always overrides the card's own blocked gate; otherwise an UNRESOLVED dedup or blocked gate
takes the local result, and a pass or an unresolved local result never overrides a gate the card already READ.

USAGE  python3 scripts/local_gates.py [--only slug[,slug]] [--dry-run] [--today YYYY-MM-DD]
EXIT   0 ok · 3 --today is not a real date · 4 no cards to look at · 5 the existing output file is unreadable (left as it is)
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE if os.path.basename(HERE) == "scripts" else os.path.dirname(HERE))
for _p in (HERE, os.path.join(os.path.dirname(HERE), "partner-starter", "scripts")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.append(_p)
import board  # noqa: E402

LOCAL_KEYS = ("blocked", "dedup")
SOURCE = "local check"
OUT_REL = os.path.join("documents", "state", "local-gates.json")
UNREAD = ("none", "owed")
QUEUE_NAMES = ("outreach-queue.md", "prospect_queue.md")
CONTACT_STORES = ("warm-network", "contact-closeness")
BLOCKED_LIST = "blocked-employers-list.md"


class NothingToLookAt(Exception):
    pass


class OutputUnreadable(Exception):
    pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def company_of(card):
    """The company NAME (board.card_company), or "" when the header gives none."""
    name = board.card_company(card["head"]["company"]).strip()
    return name if len(name) >= 2 and re.search(r"[A-Za-z0-9]", name) else ""


NOT_ASKED_YET = "not asked yet: nothing to check against"


def _entry(state, why, at, counts):
    return {"state": state, "why": why, "at": at, "source": SOURCE, "counts": counts}


def _industry_hit(company, industry_patterns, employer_patterns):
    """The matched INDUSTRY_VETO word, or the company itself when a VETO_EMPLOYERS pattern names
    it, or None. Local only: the company's own NAME is all this module has, no page text."""
    low = (company or "").lower()
    for pat in industry_patterns or ():
        try:
            m = re.search(pat, low)
        except re.error:
            continue
        if m:
            return m.group(0)
    for pat in employer_patterns or ():
        try:
            m = re.search(pat, low)
        except re.error:
            continue
        if m:
            return company
    return None


def gate_blocked(company, check, at, counts, industry_patterns=(), employer_patterns=()):
    """counts: bool, decided ONCE per run (B1/C1/C2) -- never re-derived per card, and never from
    the no_industry_vetoes/NO_INDUSTRY_VETO marker."""
    if not counts:
        return _entry("unresolved", NOT_ASKED_YET, at, False)
    try:
        status, detail = check(company)
    except Exception as e:  # a check that cannot run is never a pass
        return _entry("unresolved", "the blocked-list check failed: %s: %s" % (type(e).__name__, e), at, False)
    if status == "BLOCKED":
        return _entry("fail", "on the blocked list: %s" % re.sub(r"\s+", " ", detail or "").strip()[:200], at, True)
    if status == "CLEAN":
        hit = _industry_hit(company, industry_patterns, employer_patterns)
        if hit:
            return _entry("fail", "vetoed industry: matched %r" % hit, at, True)
        return _entry("pass", "not on the blocked list and not a vetoed industry (checked locally)", at, True)
    return _entry("unresolved", "the blocked-list check could not run: %s" % (detail or status), at, False)


def _owner_slug(store, slugs):
    """The card a documents/state file belongs to: the LONGEST slug that prefixes its name, so acme-labs-... is not acme's."""
    base = os.path.basename(store)
    best = ""
    for s in slugs:
        if base.startswith(s + "-") and len(s) > len(best):
            best = s
    return best


def _is_self(store, slug, slugs):
    base = os.path.basename(store)
    if base in QUEUE_NAMES or (base.endswith(".md") and "queue" in base):
        return True
    return "documents/state/" in store.replace("\\", "/") and _owner_slug(store, slugs) == slug


def _line(h):
    return "%s L%s" % (h["store"], h["line"])


_EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _mask_contact(text, store):
    """BUG-709 class A: the prior-contact line is copied into the app's store, so a third party's address
    must not ride along. Mask the FULL line (callers cut to 120 chars AFTER this, so an address that
    straddles the cut never leaves half of itself): an email becomes `[address in <store>]`, a bare
    `@word` / `@ Word` fragment becomes `[address]`, and any `@` still left becomes `[address]`. Store, line, date and
    company stay, so the card still says where the contact is on record."""
    label = "[address in %s]" % os.path.basename(str(store or "")).replace("@", "") if store else "[address]"
    text = _EMAIL_IN_TEXT.sub(label, text)
    text = re.sub(r"@\s*[A-Za-z0-9][A-Za-z0-9._-]*", "[address]", text)
    return text.replace("@", "[address]")


def gate_dedup(slug, company, slugs, check, at, counts):
    """counts: bool, decided ONCE per run -- true only when the send log or a contact store
    carries at least one row (a self-match against the card's own files proves nothing)."""
    if not counts:
        return _entry("unresolved", NOT_ASKED_YET, at, False)
    try:
        pc = check(company)
    except Exception as e:
        return _entry("unresolved", "the prior-contact check failed: %s: %s" % (type(e).__name__, e), at, False)
    hits = [h for h in pc.get("strong", []) + pc.get("weak", []) if os.path.basename(h["store"]) != BLOCKED_LIST]
    own = [h for h in hits if _is_self(h["store"], slug, slugs)]
    other = [h for h in hits if h not in own]
    real = [h for h in other if h in pc.get("strong", [])
            or "state/" in h["store"] and "card" in os.path.basename(h["store"])
            or any(c in h["store"] for c in CONTACT_STORES)]
    if real:
        first = real[0]
        more = "" if len(real) == 1 else " (+%d more)" % (len(real) - 1)
        return _entry("warn", "prior contact: %s, %s%s" % (_line(first), _mask_contact(re.sub(r"\s+", " ", first.get("text", "")).strip(), first.get("store"))[:120], more), at, True)
    if other:
        return _entry("pass", "no recorded contact (%d mention(s) only as prose or a staged draft)" % len(other), at, True)
    if own:
        return _entry("pass", "matches only its own card or queue row (a self-match), so nothing else on record", at, True)
    return _entry("pass", "no prior contact found in the send log, outreach log, tracker or correspondence log", at, True)


def overlay_gates(gates, entry):
    """gates: the feed's gate dicts.
    - a local BLOCKED FAIL ALWAYS overrides the card's own blocked gate, whatever the card says (his blocked list is his latest word; 7 dropped
      companies read OPEN because a stale "good" gate on the card was never overridden);
    - otherwise an UNRESOLVED dedup or blocked gate takes the local result;
    - a pass or an unresolved local result NEVER overrides a gate the card already READ, and a dedup result never does either;
    - nothing else is touched, and the input is not mutated."""
    if not entry:
        return gates
    out = []
    for g in gates:
        key = g.get("key")
        e = entry.get(key) if key in LOCAL_KEYS else None
        if e:
            forced = key == "blocked" and e.get("state") == "fail"
            fills = g.get("state") == "unresolved" and e.get("state") != "unresolved"
            if forced or fills:
                g = dict(g, state=e["state"], why=e["why"], source=e.get("source", SOURCE), counts=e.get("counts", False))
        out.append(g)
    return out


def blocked_list_nonempty(repo):
    """True when the blocked list actually names anyone.

    Review 187 MUST2: this used to parse the list with screen_sweep.blocked_keys_from_list(),
    which reads the STARTER list's own "How to use" instruction prose as six company names
    (achatmemory, example, here, neverresurface, rerank, wheneveryouaddone) -- install.sh seeds
    that file into every fresh install, so a brand-new, truly empty install counted the blocked
    gate as answered and passed every company silently, the exact vacuous pass 3a/3b exist to
    stop. feed_install.blocked_list_state() is the ONE existing reader that already tells
    instructions apart from a real bullet or table row (two parsers deciding the same fact is
    the R163 class of bug this delegates away from, not a second count to keep in sync by hand)."""
    try:
        if HERE not in sys.path:
            sys.path.append(HERE)
        import feed_install
        return feed_install.blocked_list_state(repo) == "listed"
    except Exception:
        return False


def industry_veto_patterns(repo):
    """(INDUSTRY_VETO, VETO_EMPLOYERS) read straight off the person's own kit_config.py -- never
    off the no_industry_vetoes/NO_INDUSTRY_VETO marker (C1): that marker is written both for a
    CHOSEN "None" and for Setup's untouched default, so it cannot tell the two apart, and a
    marker that cannot tell a choice from a default must never be the thing that counts.

    Loaded by EXPLICIT FILE PATH (board.py's own `_load()` idiom), never a bare `import
    kit_config` -- that would resolve to whatever copy already sits in `sys.modules`, which is
    the wrong answer the moment two different repos are checked in the same process (a feed
    build walking a board row for a fresh install, right after this process already loaded the
    real install's own kit_config for a scorecard card)."""
    import importlib.util
    for candidate in (os.path.join(repo, "scripts", "kit_config.py"), os.path.join(repo, "kit_config.py")):
        if os.path.isfile(candidate):
            try:
                spec = importlib.util.spec_from_file_location("local_gates_kit_config_%d" % id(repo), candidate)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return (list(getattr(mod, "INDUSTRY_VETO", None) or []),
                        list(getattr(mod, "VETO_EMPLOYERS", None) or []))
            except Exception:
                return ([], [])
    return ([], [])


_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
                   r"|\b" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b"          # Sep 1, 2026 / September 1, 2026
                   r"|\b\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH + r",?\s+\d{4}\b", re.I)    # 1 Sep 2026
_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+\S")
_TABLE_SEP = re.compile(r"^\|?[\s:|-]+\|[\s:|-]*$")


def _text_store_has_a_record(path):
    """True when a send-gate history file holds at least one RECORD that check_dup.search_file could match a company in. Counted: every heading of two
    or more #s (a thread header), every blockquote (a quoted reply), every list item, every table body row, and any line that carries a date (ISO, d/m/y, or written with a month name: Sep 1, 2026 / 1 September 2026), even a single `# ` heading. NOT
    counted: blank lines, a single `# ` title with no date, HTML comments, a markdown table's header and separator rows, and plain prose with no date (the text
    install.sh seeds under a log's title is exactly that, and a fresh install must not read as having a history). A csv holds a record when it has
    more than its header line.

    KNOWN GAP, said plainly: an undated bold-label line ("**Sent:** yes") or a pasted body with no date, list item, quote or heading is not counted. The outcome
    of that gap is "not asked yet" (counts false), never a false pass: the gate stays gray until a record the rule can see exists."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return False
    if path.endswith(".csv"):
        return len(lines) > 1
    skip = set()
    for i, ln in enumerate(lines):
        if i and _TABLE_SEP.match(ln) and lines[i - 1].startswith("|"):
            skip.update((i - 1, i))
    for i, ln in enumerate(lines):
        if i in skip or ln.startswith("<!--"):
            continue
        if ln.startswith("#"):
            if re.match(r"^#{2,}\s", ln) or _DATE.search(ln):
                return True
            continue                                  # a single `# ` title with no date
        if ln.startswith(">") or _LIST_ITEM.match(ln) or ln.startswith("|") or _DATE.search(ln):
            return True
    return False


def dedup_sources_nonempty(repo):
    """True when something prior_contact can actually find exists: the send log, a history store in check_dup.SEND_GATE_STORES (minus the
    blocked list, which gate_dedup ignores), or a contact row that records a touch. Never the card's own queue or card files under
    documents/state (a self-match proves nothing about anyone else), and NEVER a contact row from an import alone (BUG-601): a
    LinkedIn export, warm-network.md and contact-closeness.json say who the person knows, not whom they have already written to.

    The store list is imported from check_dup, never hand-copied: a hand-written list once left out job_search_tracker.csv, so a
    tracker-only history would never have warned (R240c)."""
    sendlog = os.path.join(repo, "documents", "send-log.jsonl")
    try:
        with open(sendlog, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip():
                    return True
    except OSError:
        pass
    if HERE not in sys.path:
        sys.path.append(HERE)
    try:
        import check_dup
        for rel in sorted(check_dup.SEND_GATE_STORES):
            if rel == "documents/blocked-employers-list.md":
                continue
            if _text_store_has_a_record(os.path.join(repo, rel)):
                return True
    except Exception:
        pass
    try:
        import feed_install
        for row in feed_install._jsonl(repo, feed_install.CONTACTS):
            payload = row.get("payload") or {}
            if row.get("kind") == "contact" and (payload.get("touch") or payload.get("last_contact")):
                return True
    except Exception:
        pass
    return False


def _load_out(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return data
    except (OSError, ValueError):
        raise OutputUnreadable(path)


def run(repo, blocked_check=None, prior_check=None, today=None, dry_run=False, only=None,
        blocked_counts=None, dedup_counts=None, veto_patterns=None):
    """blocked_counts, dedup_counts: bool overrides for a test fixture; None computes the real
    answer from `repo` ONCE for the whole run, never re-derived per card. veto_patterns: an
    (INDUSTRY_VETO, VETO_EMPLOYERS) override; None reads kit_config."""
    if blocked_check is None or prior_check is None:
        if HERE not in sys.path:
            sys.path.append(HERE)
        import check_dup
        import filter_blocked
        blocked_check = blocked_check or filter_blocked.classify
        prior_check = prior_check or check_dup.prior_contact
    if veto_patterns is None:
        veto_patterns = industry_veto_patterns(repo)
    industry_patterns, employer_patterns = veto_patterns
    if blocked_counts is None:
        blocked_counts = blocked_list_nonempty(repo) or bool(industry_patterns) or bool(employer_patterns)
    if dedup_counts is None:
        dedup_counts = dedup_sources_nonempty(repo)
    day = today or datetime.date.today().isoformat()
    at = day + "T00:00:00Z" if today else _now()
    cards = board.load_cards(repo)
    if not cards:
        raise NothingToLookAt("no company cards under %s" % os.path.join(repo, "documents", "state"))
    path = os.path.join(repo, OUT_REL)
    existing = _load_out(path)
    slugs = sorted(cards)
    todo = [s for s in slugs if not only or s in only]
    results, unreadable, before, still = {}, [], 0, 0
    for slug in todo:
        card = cards[slug]
        company = company_of(card)
        unread_before = {k for k, _l, st in card["gates"] if k in LOCAL_KEYS and st in UNREAD}
        before += len(unread_before)
        if not company:
            unreadable.append(slug)
            why = "the company name could not be read from the card header"
            results[slug] = {k: _entry("unresolved", why, at, False) for k in LOCAL_KEYS}
        else:
            results[slug] = {"blocked": gate_blocked(company, blocked_check, at, blocked_counts,
                                                      industry_patterns, employer_patterns),
                             "dedup": gate_dedup(slug, company, slugs, prior_check, at, dedup_counts)}
        still += sum(1 for k in unread_before if results[slug][k]["state"] == "unresolved")
    merged = dict(existing) if only else {}
    merged.update(results)
    merged = {s: merged[s] for s in sorted(merged) if s in cards}
    if not dry_run:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=1, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    states = {}
    for r in results.values():
        for e in r.values():
            states[e["state"]] = states.get(e["state"], 0) + 1
    return {"cards": len(todo), "unresolved_before": before, "still_unresolved": still, "unreadable": unreadable,
            "states": states, "dry_run": dry_run}


def summary_line(r):
    return ("local_gates: cards %d · unresolved before %d · still unresolved %d · states %s · cards whose company cannot be read %d%s"
            % (r["cards"], r["unresolved_before"], r["still_unresolved"], json.dumps(r["states"], sort_keys=True),
               len(r["unreadable"]), " · DRY RUN" if r["dry_run"] else ""))


def main(argv=None, blocked_check=None, prior_check=None):
    ap = argparse.ArgumentParser(description="Resolve the blocked and dedup gates locally for every card.")
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--today")
    ap.add_argument("--only", help="comma-separated slugs; merges into the existing file")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.today:
        try:
            datetime.date.fromisoformat(a.today)
            if len(a.today) != 10:
                raise ValueError
        except ValueError:
            print("local_gates: --today %r is not a real YYYY-MM-DD date." % a.today)
            return 3
    only = [x.strip() for x in a.only.split(",") if x.strip()] if a.only else None
    try:
        r = run(a.repo, blocked_check, prior_check, today=a.today, dry_run=a.dry_run, only=only)
    except NothingToLookAt as e:
        print("local_gates: nothing to look at (%s). Refusing to report a clean pass." % e)
        return 4
    except OutputUnreadable as e:
        print("local_gates: %s is unreadable; left as it is. Fix or move it." % e)
        return 5
    print(summary_line(r))
    if r["unreadable"]:
        print("  unreadable: " + ", ".join(r["unreadable"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
