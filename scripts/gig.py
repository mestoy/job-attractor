#!/usr/bin/env python3
"""gig.py -- the gig income lane: platform stage log and income log, one CLI.

Built for G0 and G1 of `documents/state/gig-stories-2026-09-13.md` (both STAND, 2026-09-13),
per the build section of `documents/plan-gig-income-lane-2026-09-13.md`. His own DECIDED problem
statement: "nothing measures dollars against hours" (H1). This is the mechanism that measures it.

STORES (append-only JSONL, same shape as `stage_funnel.py`'s own pattern -- never mutate a row,
always append a new one; `current stage` is read as the LATEST row for a company_key):
    documents/state/gig-stages.jsonl   -- {ts, company_key, platform, stage, work_type, rate_hr,
                                            effective_rate_hr, onboarding_step, gates{...},
                                            red_flags[], sources[], note, needs_his_call}
    documents/state/gig-income.jsonl   -- {ts, company_key, week_of, hours, rate_hr, earned}

IDENTITY: a platform is a company entity. `screen_sweep.canon()` gives the identity key so
"Zzfake" and "Zzfake AI" collapse to one row set, the same defect class the blocked-list escape
in `screen_sweep.py`'s own docstring describes. `state.register("company", ..., lane="gig")`
puts the platform on the durable company store so it shows up beside every other tracked company.

RULES IN CODE (cited to the memory names that carry them):
  * `rate-floor-flags-never-drops` (memory: this story's own acceptance criteria, G0) -- a rate,
    or effective rate when given, under $50/hr appends the red flag "below floor". It NEVER
    removes the row, never skips the write, never drops the platform.
  * `a16z-veto-carve-out-for-gig-marketplaces` -- a16z_led=yes sets needs_his_call=True and
    nothing else. It is never resolved to applied or dropped by this tool; only his own
    `gig.py stage` call can move it.
  * Hard drop is narrow on purpose -- the ONLY automatic hard drop is a defense/military/
    law-enforcement customer gate (--defense drop) or a confirmed non-payment report
    (--nonpayment-reported yes). Every other gate combination (pe_owned, a16z_led alone) requires
    his own `stage` call.
  * Stage transitions are MONOTONIC by RANK (`StageRank`, same shape as `stage_funnel.py`'s own
    RANK dict), except `paid` may repeat -- which falls out for free, since a repeat lands on the
    same rank, never a lower one, so no special case is needed.
  * `earned` is COMPUTED, never typed -- `gig.py income` takes hours and rate_hr; there is no
    `--earned` flag at all, so a typo in a hand-multiplied figure can never reach the log.

Run: `python3 scripts/gig.py bank|screen|stage|correct|reopen|income|report|card|guide ...` (see each subcommand's --help).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
sys.path.insert(0, HERE)

import screen_sweep  # noqa: E402
import state  # noqa: E402

STAGES_REL = os.path.join("documents", "state", "gig-stages.jsonl")
INCOME_REL = os.path.join("documents", "state", "gig-income.jsonl")

# Same shape as stage_funnel.py's STAGES/RANK: a later stage always outranks an earlier one.
STAGES = ["banked", "screened", "applied", "active", "paid"]
RANK = {s: i for i, s in enumerate(STAGES)}
# `dropped` is terminal and orthogonal to depth, same treatment stage_funnel.py gives `closed`:
# ranked past everything so a hard drop is never mistaken for "earlier than banked".
RANK["dropped"] = len(STAGES)

WORK_TYPES = {"persona_build", "eval_rubric", "expert_calls", "fractional_pm"}
RATE_FLOOR = 50

NEXT_STEP = {
    "banked": "screen it",
    "screened": "apply",
    "applied": "follow up / move to active",
    "active": "log weekly hours",
    "paid": "log next week's hours",
    "dropped": "none, dropped",
}

# Story 7 (iteration 2, 2026-09-13): the gig lane is optional, off by default. His ruling,
# verbatim: "remember, the gig part of the pipeline should be optional. the boss hunting
# pipeline is the core part." This is the ONE switch, read here (cmd_report), by
# pair_brief.gig_alternate() and by build_app_feed.build_gigs() -- each reads the same env var
# directly rather than sharing a function across a subprocess boundary. A missing or malformed
# value is always off: nothing here is allowed to guess "on".
GIG_LANE_ENV_VAR = "GIG_LANE_ENABLED"
_GIG_LANE_ON_VALUES = {"1", "true", "yes", "on"}


def gig_lane_enabled(env=None):
    e = os.environ if env is None else env
    raw = (e.get(GIG_LANE_ENV_VAR) or "").strip().lower()
    return raw in _GIG_LANE_ON_VALUES


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stages_path():
    return os.path.join(REPO, STAGES_REL)


def _income_path():
    return os.path.join(REPO, INCOME_REL)


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _append_jsonl(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def company_key(platform):
    return screen_sweep.canon(platform)


def _opportunity_label(platform, opportunity):
    """His ruling, 2026-09-27 (relayed by orchestrator 1e): platform > opportunities, one
    card per opportunity (role, rate, stage); every status ask and every hours log names
    the opportunity, never just the platform. `--opportunity` is optional everywhere and
    defaults to the platform's own name, so every platform banked before this change (all
    24 of them) reads as a single opportunity named after itself -- zero migration, zero
    backfill, and the CLI/AJS report can tell "one opportunity" from "several" by checking
    whether opportunity == platform."""
    return opportunity if opportunity else platform


def _row_opportunity(row):
    """The grouping key for a stage row written before this field existed: falls back to
    the row's own platform name, the same default `_opportunity_label` gives a fresh row."""
    return row.get("opportunity") or row.get("platform")


def _latest_stage_row(key, opportunity=None):
    """The LATEST row for a (company_key, opportunity) pair -- the append-only log's own
    read of 'current stage', now per OPPORTUNITY rather than per platform, so two pieces
    of work on the same platform track independent stage progressions. `opportunity=None`
    matches every row for the platform (used only where no specific opportunity applies)."""
    rows = [r for r in _read_jsonl(_stages_path()) if r.get("company_key") == key]
    if opportunity is not None:
        rows = [r for r in rows if _row_opportunity(r) == opportunity]
    return rows[-1] if rows else None


def _rate_floor_flags(rate_hr, effective_rate_hr, existing_flags=None, rate_high=None):
    """Rate under $50/hr (or effective rate, when given) is a red flag, never a drop.

    BUG-750: a posted BAND is judged by its HIGH end, because a band that reaches the floor is
    not a below-floor role (a high end EQUAL to the floor clears it, same as a single rate of
    exactly $50). A single rate, and every row written before the band existed, is judged as
    before. An effective rate, when given, still wins over either.

    Cited: G0 acceptance test `RateFloorFlagsNeverDrops` -- "a rate under $50/hr sets a red flag
    on the row; it never removes the row or silently skips the write."
    """
    flags = list(existing_flags or [])
    if effective_rate_hr is not None:
        check = effective_rate_hr
    elif rate_high is not None:
        check = rate_high
    else:
        check = rate_hr
    if check is not None and check < RATE_FLOOR and "below floor" not in flags:
        flags.append("below floor")
    return flags


def _validate_band(rate_hr, rate_low, rate_high):
    """BUG-750: the band inputs, refused before anything is written. Both ends or neither, never
    together with a single --rate-hr (ambiguous), both above zero, low not above high."""
    if (rate_low is None) != (rate_high is None):
        raise SystemExit("--rate-low and --rate-high go together (a band has two ends).")
    if rate_low is None:
        return
    if rate_hr is not None:
        raise SystemExit("a band replaces --rate-hr: give --rate-low and --rate-high, or --rate-hr.")
    if rate_low <= 0 or rate_high <= 0:
        raise SystemExit("a band's ends must be above zero.")
    if rate_low > rate_high:
        raise SystemExit(f"--rate-low ({rate_low}) is above --rate-high ({rate_high}).")


def _band_of(row):
    """The band fields a row carries, as a dict to merge into the next row ({} for a row with no
    band, which is every row written before BUG-750). `rate_hr` on a banded row is the LOW end, so a
    reader that knows nothing about bands still gets a number."""
    if row.get("rate_low") is not None and row.get("rate_high") is not None:
        return {"rate_low": row["rate_low"], "rate_high": row["rate_high"]}
    return {}


def _rate_text(rate_hr, band):
    if band:
        return f"${band['rate_low']:g}-{band['rate_high']:g}/hr"
    return f"${rate_hr}/hr" if rate_hr is not None else "rate not given"


def _hard_drop_gates(gates):
    """The gate answers that cmd_screen hard-drops on (G0 `HardDropDefense`), as labels like
    'defense=drop'. Empty when none are set. Screen is the only path that writes a gate."""
    gates = gates or {}
    out = []
    if gates.get("defense") == "drop":
        out.append("defense=drop")
    if gates.get("nonpayment_reported") == "yes":
        out.append("nonpayment_reported=yes")
    return out


def _check_monotonic(old_stage, new_stage):
    """Refuse a stage move that ranks BELOW the current stage. `paid` repeating lands on the same
    rank as itself, so it passes this check with no special case -- it was never actually a
    demotion. Cited: G0's 'stage transitions must be monotonic by RANK, except paid may repeat'."""
    if old_stage is None:
        return
    if RANK.get(new_stage, -1) < RANK.get(old_stage, -1):
        raise SystemExit(
            f"refusing non-monotonic stage move: {old_stage!r} -> {new_stage!r} "
            f"(RANK {RANK.get(old_stage)} -> {RANK.get(new_stage)}). "
            "Stages only move forward (paid may repeat)."
        )


# ── subcommands ──────────────────────────────────────────────────────────────────────────────

def cmd_bank(a):
    key = company_key(a.platform)
    opportunity = _opportunity_label(a.platform, a.opportunity)
    state.register("company", a.platform, lane="gig")
    rate_low, rate_high = a.rate_low, a.rate_high
    _validate_band(a.rate_hr, rate_low, rate_high)
    band = {"rate_low": rate_low, "rate_high": rate_high} if rate_low is not None else {}
    rate_hr = rate_low if band else a.rate_hr
    effective_rate_hr = a.effective_rate_hr
    red_flags = _rate_floor_flags(rate_hr, effective_rate_hr, rate_high=rate_high)
    row = {
        "ts": _now_iso(),
        "company_key": key,
        "platform": a.platform,
        "opportunity": opportunity,
        "stage": "banked",
        "work_type": a.work_type,
        "rate_hr": rate_hr,
        **band,
        "effective_rate_hr": effective_rate_hr,
        "onboarding_step": "",
        "gates": {"defense": None, "a16z_led": None, "pe_owned": None, "nonpayment_reported": None},
        "red_flags": red_flags,
        "sources": [a.source] if a.source else [],
        "note": a.note or "",
        "needs_his_call": False,
    }
    _append_jsonl(_stages_path(), row)
    label = a.platform if opportunity == a.platform else f"{a.platform}: {opportunity}"
    rate_text = _rate_text(rate_hr, band)
    print(f"banked {label} ({key}) at {rate_text}"
          + (f" (below floor)" if "below floor" in red_flags else ""))
    return 0


def cmd_screen(a):
    key = company_key(a.platform)
    opportunity = _opportunity_label(a.platform, a.opportunity)
    prior = _latest_stage_row(key, opportunity)
    if prior is None:
        raise SystemExit(
            f"no banked row for {a.platform!r} opportunity {opportunity!r} ({key}) -- "
            "run `gig.py bank` for this exact opportunity first."
        )
    _check_monotonic(prior["stage"], "screened")

    gates = {
        "defense": a.defense,
        "a16z_led": a.a16z_led,
        "pe_owned": a.pe_owned,
        "nonpayment_reported": a.nonpayment_reported,
    }
    if a.escalation:
        gates["escalation"] = a.escalation

    # Hard drop is the ONLY automatic drop: defense/military/LE customer, or confirmed non-payment.
    # Cited: G0 `HardDropDefense` -- "every other gate combination requires his stage command."
    hard_drop = a.defense == "drop" or a.nonpayment_reported == "yes"
    # a16z-led NEVER auto-resolves. Cited: memory a16z-veto-carve-out-for-gig-marketplaces and
    # G0 `A16zNeverAuto` -- sets needs_his_call and nothing else; stage stays 'screened'.
    needs_his_call = a.a16z_led == "yes"

    new_stage = "dropped" if hard_drop else "screened"
    red_flags = _rate_floor_flags(prior.get("rate_hr"), prior.get("effective_rate_hr"),
                                   prior.get("red_flags"), rate_high=prior.get("rate_high"))
    if needs_his_call and "needs his call (a16z-led)" not in red_flags:
        red_flags.append("needs his call (a16z-led)")

    row = {
        "ts": _now_iso(),
        "company_key": key,
        "platform": a.platform,
        "opportunity": opportunity,
        "stage": new_stage,
        "work_type": prior.get("work_type"),
        "rate_hr": prior.get("rate_hr"),
        **_band_of(prior),
        "effective_rate_hr": prior.get("effective_rate_hr"),
        "onboarding_step": prior.get("onboarding_step", ""),
        "gates": gates,
        "red_flags": red_flags,
        "sources": prior.get("sources", []),
        "note": a.note if a.note is not None else prior.get("note", ""),
        "needs_his_call": needs_his_call,
    }
    _append_jsonl(_stages_path(), row)
    tag = " (HARD DROP)" if hard_drop else (" (needs his call, a16z-led)" if needs_his_call else "")
    label = a.platform if opportunity == a.platform else f"{a.platform}: {opportunity}"
    print(f"screened {label} ({key}) -> {new_stage}{tag}")
    return 0


def cmd_stage(a):
    key = company_key(a.platform)
    opportunity = _opportunity_label(a.platform, a.opportunity)
    prior = _latest_stage_row(key, opportunity)
    if prior is None:
        raise SystemExit(
            f"no banked row for {a.platform!r} opportunity {opportunity!r} ({key}) -- "
            "run `gig.py bank` for this exact opportunity first."
        )
    _check_monotonic(prior["stage"], a.stage)
    # BUG-699: a reopened row can carry a hard-drop gate. No FORWARD move (by rank) except a drop
    # until a re-screen writes a fresh gate; a same-stage note (Later, Keep going) is not forward.
    carried = _hard_drop_gates(prior.get("gates"))
    if carried and a.stage != "dropped" and RANK.get(a.stage, -1) > RANK.get(prior["stage"], -1):
        raise SystemExit(
            f"re-screen first: this opportunity carries a hard-drop gate ({', '.join(carried)}); "
            "run `gig.py screen` with what changed."
        )
    # `dropped` is the manual Pass / retire path (screen's hard-drop gate is the automatic one).
    # It always says why, and a reason belongs to nothing else.
    if a.stage == "dropped" and not a.reason:
        raise SystemExit("--stage dropped needs --reason (why it is being dropped).")
    if a.reason and a.stage != "dropped":
        raise SystemExit("--reason only goes with --stage dropped.")

    red_flags = _rate_floor_flags(prior.get("rate_hr"), prior.get("effective_rate_hr"),
                                   prior.get("red_flags"), rate_high=prior.get("rate_high"))
    for rf in (a.red_flag or []):
        if rf and rf not in red_flags:
            red_flags.append(rf)

    row = {
        "ts": _now_iso(),
        "company_key": key,
        "platform": a.platform,
        "opportunity": opportunity,
        "stage": a.stage,
        "work_type": prior.get("work_type"),
        "rate_hr": prior.get("rate_hr"),
        **_band_of(prior),
        "effective_rate_hr": prior.get("effective_rate_hr"),
        "onboarding_step": a.onboarding_step if a.onboarding_step is not None
        else prior.get("onboarding_step", ""),
        "gates": prior.get("gates", {}),
        "red_flags": red_flags,
        "sources": prior.get("sources", []),
        "note": a.note if a.note is not None else prior.get("note", ""),
        "needs_his_call": prior.get("needs_his_call", False),
    }
    if a.stage == "dropped":
        row["drop_reason"] = a.reason
    _append_jsonl(_stages_path(), row)
    label = a.platform if opportunity == a.platform else f"{a.platform}: {opportunity}"
    print(f"staged {label} ({key}) -> {a.stage}")
    return 0


def _superseded_rows(numbered):
    """BUG-749: the 1-based row numbers (position in the append-only stage log) that a later
    correction row points at. A superseded row's stage was never true."""
    return {r["supersedes_row"] for _n, r in numbered
            if r.get("correction") and isinstance(r.get("supersedes_row"), int)}


def cmd_correct(a):
    """BUG-749: fix a stage that was never true, with one appended row that points at the row it
    supersedes. Nothing is edited. The target defaults to the opportunity's LATEST row; `--row N`
    names an earlier one by its 1-based position in the log (a timestamp can repeat, a position
    cannot). It skips the monotonic check on purpose, since correcting backward is its job, but it
    never lets a correction slip past a carried hard-drop gate (re-screen first). A correction of an
    EARLIER row leaves the current stage alone (it keeps the latest row's stage and records
    `corrected_stage` beside it), so fixing history never rewinds the present. A correction can
    itself be corrected: the next one points at the correction. Readers already take the latest row
    per opportunity, so the corrected stage is what they see, and `reopen` skips superseded stages."""
    key = company_key(a.platform)
    opportunity = _opportunity_label(a.platform, a.opportunity)
    label = a.platform if opportunity == a.platform else f"{a.platform}: {opportunity}"
    reason = (a.reason or "").strip()
    if not reason:
        raise SystemExit("correct needs --reason (what was never true, in his own words).")
    numbered = list(enumerate(_read_jsonl(_stages_path()), 1))
    rows_n = [(n, r) for n, r in numbered
              if r.get("company_key") == key and _row_opportunity(r) == opportunity]
    if not rows_n:
        raise SystemExit(
            f"no banked row for {a.platform!r} opportunity {opportunity!r} ({key}) -- "
            "run `gig.py bank` for this exact opportunity first."
        )
    latest_n, latest = rows_n[-1]
    if a.row is None:
        target_n, target = latest_n, latest
    else:
        match = [(n, r) for n, r in rows_n if n == a.row]
        if not match:
            raise SystemExit(
                f"row {a.row} is not a row of {label} ({key}); its rows are "
                f"{', '.join(str(n) for n, _ in rows_n)}."
            )
        target_n, target = match[0]
    if a.stage == target.get("stage"):
        raise SystemExit(f"nothing to correct: row {target_n} of {label} already says {a.stage!r}.")
    # An EARLIER row's correction fixes history, never the present: the new row keeps the opportunity's
    # CURRENT stage (the latest row's) and records the corrected stage beside it, so no reader loses
    # the true current stage. Only a correction of the latest row changes what readers see.
    is_latest = target_n == latest_n
    new_stage = a.stage if is_latest else latest.get("stage")
    carried = _hard_drop_gates(latest.get("gates"))
    if is_latest and carried and a.stage != "dropped":
        raise SystemExit(
            f"re-screen first: this opportunity carries a hard-drop gate ({', '.join(carried)}); "
            "a correction does not lift it. Run `gig.py screen` with what changed."
        )
    today = date.today().isoformat()
    prior_note = latest.get("note", "")
    note = f"[correction {today}] {reason}" + (f" | {prior_note}" if prior_note else "")
    red_flags = _rate_floor_flags(latest.get("rate_hr"), latest.get("effective_rate_hr"),
                                   latest.get("red_flags"), rate_high=latest.get("rate_high"))
    row = {
        "ts": _now_iso(),
        "company_key": key,
        "platform": a.platform,
        "opportunity": opportunity,
        "stage": new_stage,
        "work_type": latest.get("work_type"),
        "rate_hr": latest.get("rate_hr"),
        **_band_of(latest),
        "effective_rate_hr": latest.get("effective_rate_hr"),
        "onboarding_step": latest.get("onboarding_step", ""),
        "gates": latest.get("gates", {}),
        "red_flags": red_flags,
        "sources": latest.get("sources", []),
        "note": note,
        "needs_his_call": latest.get("needs_his_call", False),
        "correction": True,
        "supersedes_row": target_n,
        "supersedes_ts": target.get("ts"),
        "supersedes_stage": target.get("stage"),
        "corrected_stage": a.stage,
        "correction_reason": reason,
    }
    if is_latest and a.stage == "dropped":
        row["drop_reason"] = reason
    elif new_stage == "dropped" and latest.get("drop_reason"):
        row["drop_reason"] = latest["drop_reason"]
    _append_jsonl(_stages_path(), row)
    if is_latest:
        print(f"corrected {label} ({key}): row {target_n} said {target.get('stage')!r}, now {a.stage}")
    else:
        print(f"corrected {label} ({key}): earlier row {target_n} said {target.get('stage')!r}, "
              f"now {a.stage}; the current stage stays {new_stage}")
    return 0


def cmd_reopen(a):
    """BUG-699: return a dropped opportunity to the stage it held before the drop, forward-only.
    One appended row; nothing is edited. The stage is read from the log, never typed. The gates
    and red flags carry over untouched: only `screen` writes a gate."""
    key = company_key(a.platform)
    opportunity = _opportunity_label(a.platform, a.opportunity)
    label = a.platform if opportunity == a.platform else f"{a.platform}: {opportunity}"
    reason = (a.reason or "").strip()
    if not reason:
        raise SystemExit("reopen needs --reason (why it is being reopened), in his own words.")
    numbered = list(enumerate(_read_jsonl(_stages_path()), 1))
    superseded = _superseded_rows(numbered)
    rows_n = [(n, r) for n, r in numbered
              if r.get("company_key") == key and _row_opportunity(r) == opportunity]
    rows = [r for _n, r in rows_n]
    if not rows:
        raise SystemExit(
            f"no banked row for {a.platform!r} opportunity {opportunity!r} ({key}) -- "
            "run `gig.py bank` for this exact opportunity first."
        )
    drop = rows[-1]
    if drop.get("stage") != "dropped":
        raise SystemExit(f"nothing to reopen: {label} is {drop.get('stage')}")
    # BUG-749: a stage a correction superseded was never true, so reopen never restores it.
    held = [r for n, r in rows_n[:-1]
            if n not in superseded and r.get("stage") in RANK and r.get("stage") != "dropped"]
    new_stage = held[-1]["stage"] if held else "banked"
    if new_stage == "paid":
        new_stage = "active"
    gate_words = _hard_drop_gates(drop.get("gates"))
    prior_reason = drop.get("drop_reason") or (
        "screen: " + ", ".join(gate_words) if gate_words else "dropped (no reason recorded)")
    today = date.today().isoformat()
    prior_note = drop.get("note", "")
    note = f"[reopened {today}] {reason}" + (f" | {prior_note}" if prior_note else "")
    row = {
        "ts": _now_iso(),
        "company_key": key,
        "platform": a.platform,
        "opportunity": opportunity,
        "stage": new_stage,
        "work_type": drop.get("work_type"),
        "rate_hr": drop.get("rate_hr"),
        **_band_of(drop),
        "effective_rate_hr": drop.get("effective_rate_hr"),
        "onboarding_step": drop.get("onboarding_step", ""),
        "gates": drop.get("gates", {}),
        "red_flags": list(drop.get("red_flags", [])),
        "sources": drop.get("sources", []),
        "note": note,
        "needs_his_call": drop.get("needs_his_call", False),
        "reopen_reason": reason,
        "reopened_from_ts": drop.get("ts"),
        "prior_drop_reason": prior_reason,
    }
    _append_jsonl(_stages_path(), row)
    print(f"reopened {label} ({key}) -> {new_stage}")
    return 0


def cmd_income(a):
    key = company_key(a.platform)
    opportunity = _opportunity_label(a.platform, a.opportunity)
    # earned is COMPUTED, never typed -- there is no --earned flag on this parser at all.
    earned = round(a.hours * a.rate_hr, 2)
    row = {
        "ts": _now_iso(),
        "company_key": key,
        "opportunity": opportunity,
        "week_of": a.week_of,
        "hours": a.hours,
        "rate_hr": a.rate_hr,
        "earned": earned,
    }
    _append_jsonl(_income_path(), row)
    label = a.platform if opportunity == a.platform else f"{a.platform}: {opportunity}"
    print(f"logged {label} ({key}) week of {a.week_of}: {a.hours}h @ ${a.rate_hr}/hr = ${earned}")
    return 0


def _current_queue():
    """One entry per (company_key, opportunity): its latest stage row. A row written before
    the opportunity field existed groups under its own platform name (`_row_opportunity`'s
    fallback), so every platform banked before this change still reads as exactly one
    queue entry, unchanged. Callers read `row["opportunity"]`/`row["platform"]` for
    identity, never the dict key itself, so this key's shape (a tuple, not a bare string)
    is this function's own business."""
    by_pair = {}
    for r in _read_jsonl(_stages_path()):
        by_pair[(r["company_key"], _row_opportunity(r))] = r
    return by_pair


def _trailing_totals(income_rows, window_days, today=None):
    """Sum hours/earned for income rows whose week_of falls within the trailing window.

    Read from `week_of` (the week the hours belong to) rather than `ts` (when logged), so the
    report answers 'what did he earn in week X' deterministically off the data itself instead of
    off wall-clock time at write. Denominator is the window size itself (7 or 28), per the plan's
    own 'sends per day, denominators' shape for every rate the pipeline reports.
    """
    today = today or date.today()
    hours = 0.0
    earned = 0.0
    for r in income_rows:
        try:
            wk = date.fromisoformat(r["week_of"])
        except (KeyError, ValueError):
            continue
        if 0 <= (today - wk).days < window_days:
            hours += r.get("hours", 0) or 0
            earned += r.get("earned", 0) or 0
    return {"hours": round(hours, 2), "earned": round(earned, 2), "denominator_days": window_days}


def _reopen_fields(r):
    """The report's reopen marker. Only the LATEST row speaks: once a later stage row lands
    the opportunity is simply back in the flow. The app marker is stripped from the reason."""
    if not r.get("reopened_from_ts"):
        return {"reopened": False, "reopen_reason": "", "reopen_date": ""}
    why = re.sub(r"\s*\[app [^\]]*\]\s*$", "", r.get("reopen_reason", "") or "")
    return {"reopened": True, "reopen_reason": why, "reopen_date": str(r.get("ts", ""))[:10]}


def _report_row(r):
    """One queue entry as `report --json` shows it (shared with `card`, which adds two fields)."""
    return {"platform": r["platform"], "company_key": r["company_key"],
            "opportunity": _row_opportunity(r), "rate_hr": r.get("rate_hr"),
            "rate_low": r.get("rate_low"), "rate_high": r.get("rate_high"),
            "next_step": NEXT_STEP.get(r["stage"], ""), "red_flags": r.get("red_flags", []),
            "drop_reason": r.get("drop_reason", ""), "note": r.get("note", ""),
            **_reopen_fields(r)}


def cmd_report(a):
    enabled = gig_lane_enabled()
    if not enabled:
        zero = {"hours": 0, "earned": 0, "denominator_days": 7}
        zero28 = {"hours": 0, "earned": 0, "denominator_days": 28}
        data = {
            "enabled": False,
            "queue": {s: [] for s in STAGES + ["dropped"]},
            "trailing_7_days": zero,
            "trailing_28_days": zero28,
        }
        if a.json:
            print(json.dumps(data, indent=2))
            return 0
        print(f"── GIG LANE DISABLED (set {GIG_LANE_ENV_VAR}=1 to opt in) ──")
        return 0

    queue = _current_queue()
    income_rows = _read_jsonl(_income_path())
    seven = _trailing_totals(income_rows, 7)
    twenty_eight = _trailing_totals(income_rows, 28)

    by_stage = {s: [] for s in STAGES + ["dropped"]}
    for key, row in queue.items():
        by_stage.setdefault(row["stage"], []).append(row)

    data = {
        "enabled": True,
        "queue": {
            s: [_report_row(r) for r in rows]
            for s, rows in by_stage.items()
        },
        "trailing_7_days": seven,
        "trailing_28_days": twenty_eight,
    }

    if a.json:
        print(json.dumps(data, indent=2))
        return 0

    print("── GIG QUEUE ──")
    for s in STAGES + ["dropped"]:
        rows = by_stage.get(s, [])
        if not rows:
            continue
        print(f"  {s.upper()} ({len(rows)})")
        for r in rows:
            flag = f"  [{', '.join(r.get('red_flags', []))}]" if r.get("red_flags") else ""
            opp = _row_opportunity(r)
            label = r["platform"] if opp == r["platform"] else f"{r['platform']}: {opp}"
            ro = _reopen_fields(r)
            reopened = f"  (reopened {ro['reopen_date']}: {ro['reopen_reason']})" if ro["reopened"] else ""
            print(f"    {label:20} next: {NEXT_STEP.get(r['stage'], ''):28}{flag}{reopened}")
    print()
    print(f"  trailing 7 days:  ${seven['earned']:.2f} / {seven['hours']:.1f}h "
          f"(of {seven['denominator_days']} days)")
    print(f"  trailing 28 days: ${twenty_eight['earned']:.2f} / {twenty_eight['hours']:.1f}h "
          f"(of {twenty_eight['denominator_days']} days)")
    return 0


# ── the gig card and the income line (gig slice 1, plan-gig-slice1-2026-11-04.md) ────────────
# Pure functions on report-shaped data plus the income rows: the sign-in brief shows ONE card
# (pay, time, why it fits, one next action) and ONE income line. Nothing here writes a row.
HOLD_FLAG = "needs his call (a16z-led)"
_HOURS_IN_NOTE = re.compile(r"\d+(\.\d+)?\s*(hr|hrs|hour|hours)\b", re.I)
# (gate key, the answer that means clear, words): `screen` writes defense pass|drop, pe_owned and
# nonpayment_reported yes|no, so "clear" is not the same word for all three.
_GATE_WORDS = [("defense", "pass", "defense"), ("pe_owned", "no", "PE ownership"),
               ("nonpayment_reported", "no", "nonpayment")]


def _num(x):
    return f"{x:.0f}" if float(x).is_integer() else f"{x:.2f}".rstrip("0").rstrip(".")


def _money(x):
    return "$" + _num(x)


def _hours(x):
    return f"{_num(x)} hour" + ("" if float(x) == 1 else "s")


def _income_for(row, income_rows):
    """The income rows that belong to one opportunity (a legacy row groups under its platform)."""
    return [i for i in income_rows
            if i.get("company_key") == row.get("company_key")
            and (i.get("opportunity") or row["platform"]) == row["opportunity"]]


def _in_window(week_of, today, days=7):
    try:
        return 0 <= (today - date.fromisoformat(week_of)).days < days
    except (TypeError, ValueError):
        return False


def _pay_text(row):
    if row.get("rate_low") is not None and row.get("rate_high") is not None:
        return _rate_text(row.get("rate_hr"), {"rate_low": row["rate_low"], "rate_high": row["rate_high"]})
    rate = row.get("rate_hr")
    return f"${_num(rate)}/hr" if rate is not None else "rate not given"


def _why_text(row):
    parts = []
    top = row.get("rate_high") if row.get("rate_high") is not None else row.get("rate_hr")
    if top is not None:
        if "below floor" in (row.get("red_flags") or []) or top < RATE_FLOOR:
            parts.append(f"below your ${RATE_FLOOR} floor")
        elif top == RATE_FLOOR:
            parts.append(f"meets your ${RATE_FLOOR} floor exactly")
        else:
            parts.append(f"above your ${RATE_FLOOR} floor")
    if row.get("work_type"):
        parts.append(row["work_type"].replace("_", " "))
    gates = row.get("gates") or {}
    clear = [word for key, ok, word in _GATE_WORDS if gates.get(key) == ok]
    if clear:
        parts.append("clear on " + ", ".join(clear[:-1]) + (" and " if len(clear) > 1 else "") + clear[-1])
    if HOLD_FLAG in (row.get("red_flags") or []):
        parts.append("a16z-led, so it is your call")
    if row.get("note"):
        note = row["note"]
        parts.append("note: " + (note if len(note) <= 100 else note[:97].rstrip() + "..."))
    return "; ".join(parts)


def _flags(row):
    return row.get("red_flags") or []


def _gig_cmd(verb, row, tail):
    import shlex
    opp = "" if row["opportunity"] == row["platform"] else f" --opportunity {shlex.quote(row['opportunity'])}"
    return f"python3 scripts/gig.py {verb} {shlex.quote(row['platform'])}{opp} {tail}"


def card(data, income_rows, today=None):
    """The one gig card, or None. Log hours wins (income first): an active or paid opportunity with
    no income row in the trailing 7 days. Else the first screened opportunity, preferring one with no
    flag at all. A screened gig carrying ANY flag (a16z-led, below floor, a free-text one) gets "your
    call" with Skip only, never Apply."""
    today = today or date.today()
    queue = data.get("queue", {})
    for stage in ("active", "paid"):
        for row in queue.get(stage, []):
            mine = _income_for(row, income_rows)
            if any(_in_window(i.get("week_of"), today) for i in mine):
                continue
            if mine:
                last = max(mine, key=lambda i: i.get("week_of") or "")
                time = (f"time: no hours logged in the last 7 days; last logged week of "
                        f"{last['week_of']}, {_hours(last.get('hours') or 0)}")
            else:
                time = "time: nothing logged yet"
            rate = row.get("rate_hr")
            tail = ("--week-of <YYYY-MM-DD> --hours <hours> --rate-hr "
                    + (_num(rate) if rate is not None else "<rate>"))
            return {"platform": row["platform"], "opportunity": row["opportunity"],
                    "pay": _pay_text(row), "time": time, "why": _why_text(row),
                    "action": "Log hours", "commands": [_gig_cmd("income", row, tail)]}
    screened = queue.get("screened", [])
    pick = next((r for r in screened if not _flags(r)), None)
    held = pick is None and bool(screened)
    if held:
        pick = screened[0]
    if pick is None:
        return None
    note = pick.get("note") or ""
    time = f"time: {note}" if _HOURS_IN_NOTE.search(note) else "time: not recorded"
    skip = _gig_cmd("stage", pick, "--stage dropped --reason passed")
    commands = [skip] if held else [_gig_cmd("stage", pick, "--stage applied"), skip]
    return {"platform": pick["platform"], "opportunity": pick["opportunity"],
            "pay": _pay_text(pick), "time": time, "why": _why_text(pick),
            "action": "your call" if held else "Apply", "commands": commands}


def income_line(data, income_rows, today=None):
    """The one income line. This week is gig.py's own trailing 7 days by week_of. When nothing falls
    in that window it says so and names the last logged week, never a bare $0 beside real income."""
    today = today or date.today()
    c = card(data, income_rows, today)
    nxt = f", next: {c['platform']}" if c else ""
    week = _trailing_totals(income_rows, 7, today)
    if week["hours"] or week["earned"]:
        return f"This week: {_money(week['earned'])} from {_hours(week['hours'])}{nxt}"
    dated = [i for i in income_rows if i.get("week_of")]
    if not dated:
        return f"Income: nothing logged yet{nxt}"
    last = max(i["week_of"] for i in dated)
    sums = [i for i in dated if i["week_of"] == last]
    earned = sum(i.get("earned") or 0 for i in sums)
    hours = sum(i.get("hours") or 0 for i in sums)
    return (f"Income: nothing logged this week; last logged week of {last}: "
            f"{_money(earned)} from {_hours(hours)}{nxt}")


# ── the guided first run (gig slice 2, plan-gig-slice2-2026-11-05.md rev 4) ───────────────────
# One stateless function names the ONE step a new person is on, from the stage set and the income
# rows. Nothing is stored and nothing is written: every step prints a command he runs himself. The
# first run lasts until the first income row exists.
_SCREEN_GATES = ("defense", "a16z_led", "pe_owned", "nonpayment_reported")


def screen_gate_words():
    """{gate: [accepted words]} read from the `screen` parser itself, so the guide can never name a
    word `screen` would refuse (defense is pass|drop, the other gates yes|no, a16z-led also unknown)."""
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers()
    _add_screen(sub)
    return {a.dest: list(a.choices) for a in sub.choices["screen"]._actions
            if getattr(a, "choices", None) and a.dest in _SCREEN_GATES}


def _step(label, now, nxt, where, meanwhile, commands, card_=None):
    return {"label": label, "now": now, "next": nxt, "where": where, "meanwhile": meanwhile,
            "commands": commands, "card": card_}


def first_run_step(data, income_rows):
    """The one first-run step, or None (lane off, or any income row exists: the run is over). The
    furthest-along row decides: active/paid, then applied, then screened (a clean row before a flagged
    one), then banked. Extends card()'s order, which never looks at applied."""
    if not data.get("enabled") or income_rows:
        return None
    q = data.get("queue", {})
    live = lambda s: q.get(s, [])
    if live("active") or live("paid"):
        c = card(data, income_rows)
        return _step(
            "Step 4 of 4, log your first hours",
            "You have started a gig and nothing is logged yet. Logging the hours is your part; the tool only does the math.",
            "Once an hour is logged, the income line in this brief shows dollars and hours, and the first run is over.",
            "In the INCOME line at the top of this brief, the next time you run it.",
            "Nothing else is needed. Log a week whenever you have the hours.",
            c["commands"], c)
    if live("applied"):
        r = live("applied")[0]
        return _step(
            "Step 4 of 4, waiting on them",
            f"You applied to {r['platform']} and they have not answered yet: waiting on them. Nothing for you to do.",
            "When you start work there, tell the tool, then log your first hours.",
            "In the GIG CARD block of this brief, once you move it to active.",
            "Carry on with your search; this does not interrupt it.",
            [_gig_cmd("stage", r, "--stage active")])
    screened = live("screened")
    clean = next((r for r in screened if not _flags(r)), None)
    if clean:
        c = card(data, income_rows)
        return _step(
            "Step 3 of 4, apply",
            f"{clean['platform']} passed your screening. Applying is your part; this tool never applies for you.",
            "After you apply, tell the tool you did, and it waits for their answer.",
            "In the GIG CARD block of this brief.",
            "Apply on their site, or skip this one with the second command.",
            c["commands"], c)
    if screened:
        c = card(data, income_rows)
        flag = next(iter(_flags(screened[0])))
        return _step(
            "Step 2 of 4, your call",
            f"{screened[0]['platform']} is screened, but one thing is yours to decide: {flag}.",
            "Skip it, or decide on your own and apply outside this tool.",
            "In the GIG CARD block of this brief.",
            "Nothing is waiting on anyone else.",
            c["commands"], c)
    banked = live("banked")
    if banked:
        r = banked[0]
        words = screen_gate_words()
        spoken = "; ".join(f"{k.replace('_', '-')}: {', '.join(v)}" for k, v in words.items())
        cmd = (_gig_cmd("screen", r, "--defense <" + "|".join(words["defense"]) + "> --a16z-led <"
                        + "|".join(words["a16z_led"]) + "> --pe-owned <" + "|".join(words["pe_owned"])
                        + "> --nonpayment-reported <" + "|".join(words["nonpayment_reported"]) + ">"))
        return _step(
            "Step 2 of 4, screen it",
            f"{r['platform']} is recorded. Next are four screening questions about it. The accepted answers are {spoken}.",
            "A clean answer set makes it ready to apply to.",
            "In the GIG CARD block of this brief, right after you run the command.",
            "Nothing is waiting on anyone else; answer when you know.",
            [cmd])
    gone = live("dropped")
    why = f" Your last one dropped: {gone[-1].get('drop_reason') or 'no reason recorded'}." if gone else ""
    return _step(
        "Step 1 of 4, bank one",
        "Nothing is tracked yet." + why
        + " You pick a gig you are thinking about and record it; this tool does not look for gigs or apply for you.",
        "Then you answer four screening questions about it.",
        "In the GIG CARD block of this brief, as soon as it is recorded.",
        "Nothing is waiting on anyone; take your time.",
        ["python3 scripts/gig.py bank \"<platform>\" --work-type <" + "|".join(sorted(WORK_TYPES))
         + "> --rate-hr <rate>"])


def cmd_guide(a):
    if not gig_lane_enabled():
        if a.json:
            print(json.dumps({"enabled": False}, indent=2))
        else:
            print("The gig lane is off, so nothing here changes until you turn it on.\n"
                  "Turn it on for this terminal:\n  export GIG_LANE_ENABLED=1\n"
                  "Then run `python3 scripts/gig.py guide` again for step 1.")
        return 0
    data = _card_data()
    step = first_run_step(data, _read_jsonl(_income_path()))
    if a.json:
        print(json.dumps({"enabled": True, "first_run": step}, indent=2))
        return 0
    if step is None:
        print("The first run is over: you have logged hours. Your gig card and income line are in "
              "`python3 scripts/pair_brief.py`.")
        return 0
    print(step["label"])
    for k in ("now", "next", "where", "meanwhile"):
        print(f"  {k.upper()}: {step[k]}")
    print()
    for cmd in step["commands"]:
        print(f"  {cmd}")
    return 0


def _card_data():
    """Report-shaped data for card() and first_run_step(): the queue with work_type and gates added."""
    by_stage = {s: [] for s in STAGES + ["dropped"]}
    for r in _current_queue().values():
        by_stage.setdefault(r["stage"], []).append(
            {**_report_row(r), "work_type": r.get("work_type"), "gates": r.get("gates") or {}})
    return {"enabled": True, "queue": by_stage}


def cmd_card(a):
    if not gig_lane_enabled():
        print(json.dumps({"enabled": False}, indent=2) if a.json
              else f"── GIG LANE DISABLED (set {GIG_LANE_ENV_VAR}=1 to opt in) ──")
        return 0
    data = _card_data()
    income = _read_jsonl(_income_path())
    today = date.fromisoformat(a.today) if a.today else None
    c = card(data, income, today)
    line = income_line(data, income, today)
    if a.json:
        out = {"enabled": True, "card": c, "income_line": line}
        step = first_run_step(data, income)
        if step is not None:          # absent once the first run is over, so that output is slice 1's, byte for byte
            out["first_run"] = step
        print(json.dumps(out, indent=2))
        return 0
    print(line)
    if c is None:
        print("Gig card: none to show; bank one with gig.py bank")
        return 0
    print(f"{c['action']}: {c['platform']} · {c['pay']} · {c['time']}")
    if c["why"]:
        print(f"  why it fits: {c['why']}")
    for cmd in c["commands"]:
        print(f"  {cmd}")
    return 0


# ── argparse wiring ──────────────────────────────────────────────────────────────────────────

def _add_bank(sub):
    p = sub.add_parser("bank")
    p.add_argument("platform")
    p.add_argument("--opportunity", default=None,
                    help="the piece of work at this platform (role); defaults to the "
                         "platform's own name when a platform has only one")
    p.add_argument("--work-type", required=True, choices=sorted(WORK_TYPES))
    p.add_argument("--rate-hr", type=float, default=None,
                    help="omit when the rate is not yet known; an unknown rate is its own "
                         "honest state, never guessed and never a floor violation")
    p.add_argument("--rate-low", type=float, default=None,
                    help="low end of a posted rate band; goes with --rate-high, never with "
                         "--rate-hr. The below-floor flag judges the band by its HIGH end")
    p.add_argument("--rate-high", type=float, default=None,
                    help="high end of a posted rate band")
    p.add_argument("--effective-rate-hr", type=float, default=None)
    p.add_argument("--source", default=None)
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_bank)


def _add_screen(sub):
    p = sub.add_parser("screen")
    p.add_argument("platform")
    p.add_argument("--opportunity", default=None,
                    help="which opportunity on this platform; defaults to the platform's "
                         "own name")
    p.add_argument("--defense", required=True, choices=["pass", "drop"])
    p.add_argument("--a16z-led", required=True, choices=["yes", "no", "unknown"])
    p.add_argument("--pe-owned", required=True, choices=["yes", "no"])
    p.add_argument("--nonpayment-reported", required=True, choices=["yes", "no"])
    p.add_argument("--escalation", choices=["known", "unknown"], default=None)
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_screen)


def _add_stage(sub):
    p = sub.add_parser("stage")
    p.add_argument("platform")
    p.add_argument("--opportunity", default=None,
                    help="which opportunity on this platform; defaults to the platform's "
                         "own name")
    p.add_argument("--stage", required=True, choices=STAGES + ["dropped"])
    p.add_argument("--reason", default=None,
                    help="why, required with --stage dropped (the app's Pass key sends "
                         "\"passed\")")
    p.add_argument("--onboarding-step", default=None)
    p.add_argument("--red-flag", action="append", default=None)
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_stage)


def _add_correct(sub):
    p = sub.add_parser("correct", help="fix a stage that was never true, by appending a row "
                                       "that points at the row it supersedes")
    p.add_argument("platform")
    p.add_argument("--opportunity", default=None,
                    help="which opportunity on this platform; defaults to the platform's "
                         "own name")
    p.add_argument("--stage", required=True, choices=STAGES + ["dropped"],
                    help="the stage that is true")
    p.add_argument("--reason", required=True,
                    help="what was never true, in his own words")
    p.add_argument("--row", type=int, default=None,
                    help="the 1-based row number (position in gig-stages.jsonl) it supersedes; "
                         "defaults to this opportunity's latest row")
    p.set_defaults(func=cmd_correct)


def _add_reopen(sub):
    p = sub.add_parser("reopen")
    p.add_argument("platform")
    p.add_argument("--opportunity", default=None,
                    help="which opportunity on this platform; defaults to the platform's "
                         "own name")
    p.add_argument("--reason", required=True,
                    help="why it is being reopened, in his own words")
    p.set_defaults(func=cmd_reopen)


def _add_income(sub):
    p = sub.add_parser("income")
    p.add_argument("platform")
    p.add_argument("--opportunity", default=None,
                    help="which opportunity the hours belong to; defaults to the "
                         "platform's own name")
    p.add_argument("--week-of", required=True)
    p.add_argument("--hours", required=True, type=float)
    p.add_argument("--rate-hr", required=True, type=float)
    p.set_defaults(func=cmd_income)


def _add_report(sub):
    p = sub.add_parser("report")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true")
    g.add_argument("--md", action="store_true")
    p.set_defaults(func=cmd_report)


def _add_guide(sub):
    p = sub.add_parser("guide", help="the one step of the guided first run you are on, in plain words")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_guide)


def _add_card(sub):
    p = sub.add_parser("card", help="the one gig card and the income line the sign-in brief shows")
    p.add_argument("--json", action="store_true")
    p.add_argument("--today", default=None, help="YYYY-MM-DD, for the brief's own render(today=)")
    p.set_defaults(func=cmd_card)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gig.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add_bank(sub)
    _add_screen(sub)
    _add_stage(sub)
    _add_correct(sub)
    _add_reopen(sub)
    _add_income(sub)
    _add_report(sub)
    _add_card(sub)
    _add_guide(sub)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
