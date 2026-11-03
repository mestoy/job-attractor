#!/usr/bin/env python3
"""verdict_miner.py — Phase 3 of the self-refining ranker. The VERDICT MINER.

A PURE RECOMPUTE. It reads three durable stores — the target-impression log
(documents/state/target-impressions.jsonl), the send log, and (for context only) the decision ledger
— and DERIVES, per surfaced target, one of three labels:

  · accepted          — the ranker surfaced this target and the user chose it, OR they contacted them
                        after it was surfaced.
  · rejected-explicit — the user's words negated this target ("skip this one", "not her").
  · passed-over       — surfaced, and neither chosen nor rejected. Repeated across rows, this is the
                        strongest negative training signal, and the reason BUG-185 mattered.

These labels are the training data the experiment registry (rank_experiments.py) validates VALUE
features against, on the EV objective the ranker exists to answer: who best connects a pipeline user
to their next opportunity toward an OFFER. Success here is ACCEPTANCE, not a reply.

⛔ NO VERDICT STORE, BY DESIGN. The impression log already IS the append-only, audit-grade fact store
(log_impression.py records facts, never verdicts, precisely so the derivation can improve without the
raw record lying). A second, derived store would go stale the moment these rules sharpen — the repo's
recurring failure class. So the miner recomputes every run, idempotent and self-healing, exactly as
the registry re-measures warm_path_lift live. Audit is served by `--json` (each verdict carries its
evidence keys) and by the run event the registry appends.

⛔ THE LEDGER IS NEVER A LABEL SOURCE. Pair-picker rows classify OTHER in the ledger by design, so
reading the ledger `ruling` as a rejection would mislabel every pair pick. The label is derived from
the impression row (the answer text) and the send log ONLY; the ledger is left for future
corroboration. That way the pair-picker trap cannot fire regardless of trigger-string drift.

READ, NEVER COPIED: the negation vocabulary and the option-reference resolver are IMPORTED from
record_decision; the send-log name join reuses rank_criteria._send_identity_name and its normalizer.

GENERIC: names, companies, sends, and the board feature all come from THIS user's own stores. No
owner-specific value is baked in. Ships to the partner kit like the other ranker scripts.

⚖️ NOT a gate, hook, or send-path change — a read-only analysis module (same standing as
rank_experiments.py), so it ships panel-free. That changes the day verdict-derived weights enter
scoring/next_target (a later phase): influencing the send path takes the review panels.

Usage:
    verdict_miner.py                # ranked table of derived verdicts
    verdict_miner.py --json         # full records with evidence keys
    verdict_miner.py --name jane   # filter to one target
Exit: 0 always (analysis must never block a session).
"""
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rank_criteria as rc                                # _send_identity_name + its join contract
# Imported, never copied: one definition of the negation vocabulary and the option resolver.
from record_decision import NEGATION, _verdict_clause, resolve_option_answer  # noqa: F401

REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The SAME normalizer validate_signal joins on (rank_criteria.py:2702) — a name reduced to [a-z0-9].
def _norm(x):
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


def _impressions_path():
    return os.path.join(REPO, "documents", "state", "target-impressions.jsonl")


def _date(s):
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _read_jsonl(path):
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    yield json.loads(ln)
                except Exception:
                    continue
    except Exception:
        return


def _load_sends():
    try:
        from rung_ladder import load as _load
        return _load()
    except Exception:
        return []


def _name_hit(name, answer):
    """The target's name (whole, or a token of >=4 chars to catch 'not Lovelace') appears in the
    answer text. Used only alongside a negation test or an off-list affirmative."""
    na = _norm(answer)
    if not na:
        return False
    if _norm(name) and _norm(name) in na:
        return True
    return any(_norm(t) in na for t in re.split(r"\s+", str(name)) if len(t) >= 4)


def _new_agg(tgt):
    return {"name": tgt.get("name"), "company": tgt.get("company"), "rung": tgt.get("rung"),
            "first_surfaced": None,
            "counts": {"surfaced": 0, "chosen": 0, "passed_over": 0, "rejected": 0},
            "evidence": {"impressions": [], "chosen_in": [], "rejected_in": [],
                         "send_dates": [], "pre_impression_sends": 0},
            "_acc_dates": [], "_rej_dates": []}


def _company_key(company):
    if not company:
        return None
    try:
        import state
        return state.key_for("company", company)
    except Exception:
        return None


def _board_keys():
    """The set of company keys on THIS user's green board — a feature TYPE computed from the current
    repo's data, never a baked-in list. Best-effort: any state-store shape or absence → empty set, so
    the board feature simply flags nothing (an honest 'underpowered'), never a crash."""
    try:
        import state
        rows = state.from_source("company", "green-board")
        if isinstance(rows, dict):
            return {k for k in rows if k}
        return {r.get("key") for r in rows if isinstance(r, dict) and r.get("key")}
    except Exception:
        return set()


def mine_verdicts(impressions_path=None, ledger_path=None, send_rows=None):
    """{norm(name): verdict_record} derived from the impression log + the send log. `ledger_path` is
    accepted for API stability but is NOT consulted for labels (see the module docstring). `send_rows`
    is injectable for tests; None loads the live send log."""
    impressions_path = impressions_path or _impressions_path()
    seen, per = set(), {}

    for row in _read_jsonl(impressions_path):
        if not isinstance(row, dict):
            continue
        ik = row.get("impression_key")
        if ik and ik in seen:
            continue                                       # dedupe: the hook's tail-window is bounded
        if ik:
            seen.add(ik)
        options = row.get("options")
        if not isinstance(options, list):
            continue
        idate = _date(row.get("ts"))
        chosen = row.get("chosen") or {}
        ans = str(chosen.get("answer") or "")
        cidx = chosen.get("idx")
        off_list = bool(chosen.get("off_list"))
        negates = bool(NEGATION.search(_verdict_clause(ans))) if ans else False

        for opt in options:
            if not isinstance(opt, dict):
                continue
            tgt = opt.get("target")
            if not tgt or not tgt.get("name"):
                continue
            key = _norm(tgt["name"])
            if not key:
                continue
            agg = per.setdefault(key, _new_agg(tgt))
            # keep the latest row's display fields; track the earliest surfacing date
            for f in ("name", "company", "rung"):
                if tgt.get(f):
                    agg[f] = tgt[f]
            if idate and (agg["first_surfaced"] is None or idate < agg["first_surfaced"]):
                agg["first_surfaced"] = idate
            agg["evidence"]["impressions"].append(ik)
            agg["counts"]["surfaced"] += 1

            name_in_answer = _name_hit(tgt["name"], ans)
            chosen_here = (cidx == opt.get("idx"))
            # The user typed the name affirmatively instead of clicking (off-list, name present, no negation).
            if not chosen_here and off_list and name_in_answer and not negates:
                chosen_here = True
            rejected_here = name_in_answer and negates

            if chosen_here:
                agg["counts"]["chosen"] += 1
                agg["evidence"]["chosen_in"].append(ik)
                if idate:
                    agg["_acc_dates"].append(idate)
            elif rejected_here:
                agg["counts"]["rejected"] += 1
                agg["evidence"]["rejected_in"].append(ik)
                if idate:
                    agg["_rej_dates"].append(idate)
            else:
                agg["counts"]["passed_over"] += 1

    _join_sends(per, _load_sends() if send_rows is None else send_rows)
    return {k: _finalize(k, agg) for k, agg in per.items()}


def _join_sends(per, send_rows):
    """A DELIVERED send to a surfaced target, dated ON/AFTER its first surfacing, is acceptance. A
    send strictly BEFORE is counted but never labels — a pre-existing contact is not the ranker's
    surfacing being accepted, and counting it would leak the outcome into the label, the same class
    warm_path_lift guards with its strictly-before rule."""
    try:
        from rung_ladder import NOT_DELIVERED
    except Exception:
        NOT_DELIVERED = set()
    for r in send_rows or []:
        if not isinstance(r, dict):
            continue
        if str(r.get("status", "")).lower() in NOT_DELIVERED:
            continue
        key = _norm(rc._send_identity_name(r))
        agg = per.get(key)
        if not agg:
            continue
        sd = _date(r.get("date"))
        first = agg["first_surfaced"]
        if sd and first and sd >= first:
            agg["evidence"]["send_dates"].append(r.get("date"))
            agg["_acc_dates"].append(sd)
        elif sd is None or first is None or sd < first:
            agg["evidence"]["pre_impression_sends"] += 1


def _finalize(key, agg):
    """Apply the precedence rule: the LATEST-dated signal between acceptance and rejection wins.
    Acceptance ties (same-dated) resolve to accepted, since a click/contact is behavioral."""
    acc, rej = agg["_acc_dates"], agg["_rej_dates"]
    if acc and (not rej or max(acc) >= max(rej)):
        label, basis = "accepted", ("chosen" if agg["evidence"]["chosen_in"] else "sent-after")
    elif rej and (not acc or max(rej) > max(acc)):
        label, basis = "rejected-explicit", "negation"
    else:
        label, basis = "passed-over", "never-chosen"
    dates = acc + rej
    last = max(dates) if dates else agg["first_surfaced"]
    return {
        "key": key, "name": agg["name"], "company": agg["company"],
        "company_key": _company_key(agg["company"]), "rung": agg["rung"],
        "label": label, "basis": basis,
        "evidence": agg["evidence"], "counts": agg["counts"],
        "first_surfaced": agg["first_surfaced"].isoformat() if agg["first_surfaced"] else None,
        "last_signal": last.isoformat() if last else None,
    }


# ── VALUE-FEATURE populations (Phase 4) ─────────────────────────────────────────────────────────
# Built-in booleans take NO predicate (the feature IS the membership test); field populations
# regex-match a per-verdict field. The registry reads this tuple so a proposed experiment can name a
# built-in population without a predicate. Every helper below is best-effort: an absent or malformed
# store returns empty, so the feature flags nothing and the experiment runs honestly underpowered,
# never crashes. All values derive from THIS user's own stores, zero owner-specifics.
BUILTIN_POPULATIONS = ("board", "banked", "on-segment", "bridged-company", "is-bridge", "shared-group")


def _banked_keys():
    """Company keys anywhere on the user's vetted BACKLOG (banked pool), finer than the 10-company
    board. The needle 'banked' matches the pool's own file-naming convention, which the kit ships."""
    try:
        import state
        rows = state.from_source("company", "banked")
        if isinstance(rows, dict):
            return {k for k in rows if k}
        return {r.get("key") for r in rows if isinstance(r, dict) and r.get("key")}
    except Exception:
        return set()


def _segment_lookup():
    """(cache, employer_key_fn, not_found_sentinel). Reads the user's own resolved employer CACHE
    only, NEVER contact_signals.segment_for's regex patterns, which hardcode one user's segments. A
    partner's cache carries their segments or nothing."""
    try:
        import contact_signals as cs
        return cs.load_employer_cache(), cs._employer_key, cs._NOT_FOUND
    except Exception:
        return {}, (lambda x: x), "not-found"


def _segment_of(company, ctx):
    cache, keyfn, _nf = ctx
    if not company:
        return None
    row = cache.get(keyfn(company))
    return row.get("segment") if row else None


def _closeness_by_norm():
    """{_norm(display_name): tier} from the user's STATED closeness answers. Reads the raw contacts
    dict keyed by DISPLAY name so the miner's own _norm applies directly, sidestepping the closeness
    store's different normalizer (the mismatch the design review flagged). Tier aliases folded in."""
    out = {}
    try:
        import closeness
        path = os.path.join(REPO, "documents", "contact-closeness.json")
        contacts = json.load(open(path, encoding="utf-8")).get("contacts", {})
        for disp, row in contacts.items():
            tier = str((row or {}).get("closeness") or "").strip()
            tier = closeness.TIER_ALIASES.get(tier, tier)
            if tier:
                out[_norm(disp)] = tier
    except Exception:
        pass
    return out


def _people_fields_by_norm():
    """{_norm(name): {'title', 'known_since'}} from the export snapshot (_people_rows) — the
    send-date-computable title and vintage columns."""
    out = {}
    try:
        for name, title, _co, _fl, known in rc._people_rows():
            k = _norm(name)
            if k:
                out[k] = {"title": title, "known_since": known}
    except Exception:
        pass
    return out


def _shared_group_names():
    """{_norm(name)} for contacts with a VERIFIED shared LinkedIn group. Tri-state honored: unchecked
    (absent) and checked-none ([]) are both excluded."""
    try:
        import mutual_groups
        return {_norm(r.get("name")) for r in mutual_groups.load().values() if r.get("groups")}
    except Exception:
        return set()


def _bridge_sets():
    """(bridged_company_keys, bridge_person_norms) from the bridges store. Empty until it fills, so
    the referral-path populations flag nothing and run underpowered rather than error."""
    ckeys, people = set(), set()
    try:
        import bridge_sweep
        for row in bridge_sweep.load().values():
            bridges = row.get("bridges") or []
            if not bridges:
                continue
            ck = _company_key(row.get("company"))
            if ck:
                ckeys.add(ck)
            people.update(_norm(b) for b in bridges if _norm(b))
    except Exception:
        pass
    return ckeys, people


def _field_value(population, v, ctx):
    if population in ("company", "name", "rung"):
        return v.get(population)
    if population == "segment":
        return _segment_of(v.get("company"), ctx["seg"])
    if population == "closeness":
        return ctx["close"].get(v["key"])
    if population in ("title", "known_since"):
        return (ctx["people"].get(v["key"]) or {}).get(population)
    return None


def _flag(predicate, population, verdicts):
    """The set of verdict keys a value-feature predicate flags. A built-in boolean population takes no
    predicate; a field population regex-matches a per-verdict field resolved from the user's stores."""
    if population == "board":
        board = _board_keys()
        return {k for k, v in verdicts.items() if v.get("company_key") and v["company_key"] in board}
    if population == "banked":
        banked = _banked_keys()
        return {k for k, v in verdicts.items() if v.get("company_key") and v["company_key"] in banked}
    if population == "on-segment":
        ctx, out = _segment_lookup(), set()
        nf = ctx[2]
        for k, v in verdicts.items():
            seg = _segment_of(v.get("company"), ctx)
            if seg and seg not in ("off-segment", nf):
                out.add(k)
        return out
    if population == "shared-group":
        names = _shared_group_names()
        return {k for k, v in verdicts.items() if _norm(v.get("name")) in names}
    if population in ("bridged-company", "is-bridge"):
        ckeys, people = _bridge_sets()
        if population == "bridged-company":
            return {k for k, v in verdicts.items() if v.get("company_key") and v["company_key"] in ckeys}
        return {k for k, v in verdicts.items() if _norm(v.get("name")) in people}
    # ── field populations (predicate required) ──
    ctx = {"seg": _segment_lookup(),
           "close": _closeness_by_norm() if population == "closeness" else {},
           "people": _people_fields_by_norm() if population in ("title", "known_since") else {}}
    if not predicate:
        return set()
    rx = re.compile(predicate, re.I)
    return {k for k, v in verdicts.items() if rx.search(str(_field_value(population, v, ctx) or ""))}


def verdict_cells(predicate, population="company", verdicts=None):
    """(with_cell, without_cell, unjoined) in the registry's [successes, population] order, where
    SUCCESS = label 'accepted' and the population is EVERY verdict (passed-over and rejected sit in
    the denominator). Feeds rank_experiments.classify() unchanged — the n>=15 floor and dead band
    apply, so a thin store honestly returns 'underpowered'."""
    if verdicts is None:
        verdicts = mine_verdicts()
    flagged = _flag(predicate, population, verdicts)
    a_r = a_s = b_r = b_s = 0
    for k, v in verdicts.items():
        won = 1 if v.get("label") == "accepted" else 0
        if k in flagged:
            a_s += 1
            a_r += won
        else:
            b_s += 1
            b_r += won
    return [a_r, a_s], [b_r, b_s], 0


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    verdicts = mine_verdicts()
    if "--name" in argv:
        i = argv.index("--name")
        needle = _norm(argv[i + 1]) if i + 1 < len(argv) else ""
        if needle:
            verdicts = {k: v for k, v in verdicts.items() if needle in k}
    if "--json" in argv:
        print(json.dumps(verdicts, ensure_ascii=False, indent=2, default=str))
        return 0
    if not verdicts:
        print("no target impressions yet — the logger writes them as pickers are answered.")
        return 0
    rank = {"accepted": 0, "rejected-explicit": 1, "passed-over": 2}
    print(f"{'name':24} {'company':20} {'label':18} {'surf':>4} {'acc':>4} {'rej':>4}")
    for k in sorted(verdicts, key=lambda k: (rank.get(verdicts[k]["label"], 9),
                                             verdicts[k]["name"] or "")):
        v, c = verdicts[k], verdicts[k]["counts"]
        print(f"{str(v['name'])[:24]:24} {str(v.get('company') or '-')[:20]:20} {v['label']:18} "
              f"{c['surfaced']:>4} {c['chosen']:>4} {c['rejected']:>4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
