#!/usr/bin/env python3
"""rank_experiments.py — the self-refining ranker's EXPERIMENT REGISTRY and runner.

WHY (2026-08-14): the ranker's ranking METHOD must self-refine, because the world is
dynamic. A signal is not typed into the code and trusted forever; it is PROPOSED as a hypothesis,
RUN against real outcomes, and only RATIFIED by the user's judgment. This formalizes the ad-hoc
EXP-000 / EXP-001 loop (documents/ranker-experiment-findings.md) into an append-only registry so the
loop is repeatable and auditable, not a thing the assistant re-derives from memory each session.

NORTH STAR: rank people by who can best connect a pipeline USER to their next opportunity toward a
job offer. Expected value, not replies (EV = P(engage) x Value). Replies validate the P(engage)
factor only. This registry is the machine that tests candidate signals against that objective.

TWO HARD CONSTRAINTS, enforced by construction:
  1. Features are STARTING POINTS. The predicate and hypothesis of every experiment live in the
     DATA (the proposed record), never in this code. There is not one regex, segment name, or
     function list in this file. New signals are discovered by proposing them, not by editing here.
  2. GENERIC to EVERY user (Matthew too). The joins read the CURRENT repo's own send log, export,
     and people rows (rank_criteria resolves them from its own location), so the same mechanism
     measures whatever THAT user's data expresses. Zero owner-specific values are baked in.
     [[the-kit-must-not-assume-whose-search-it-is-running]]

THE JOIN IS BORROWED, NEVER REIMPLEMENTED. rank_criteria.validate_signal / warm_path_lift / _lift
own the leakage screen, the n>=15 floor, and the [0.5, 2.0] clamp. This orchestrates them.

⚠️ CELL-ORDER BRIDGE. Both joins return cells as [replies, sends]; rank_criteria._lift unpacks
[sends, replies]. `classify` swaps before calling _lift. `test_cell_order_swap_pins_the_bridge`
is the tripwire that fails if the swap is ever dropped (it would misread n and invert the verdict).

APPEND-ONLY. A status change is a NEW event row referencing the id; no line is ever rewritten or
deleted. `project()` folds the file (latest event wins per id) into current status. This is the same
discipline as the send log and the ruling store: history is a ledger, never a mutable record.

Usage:
    rank_experiments.py propose --hypothesis "..." --signal NAME \\
        [--predicate REGEX] [--population note|titles] \\
        [--join validate_signal|warm_path_lift] [--objective p-engage|value]
    rank_experiments.py run EXP-001            # or:  run --all-proposed
    rank_experiments.py list [--json]
    rank_experiments.py ratify EXP-001 --lane evidence --note "..." [--weight 1.67]
    rank_experiments.py ratify EXP-001 --lane ruling  --note "..."
Exit: 0 ok · 3 refused (bad shape, leakage, floor guard).
"""
import json
import math
import os
import sys
from datetime import datetime, timezone

# rank_criteria and its dependency web resolve off scripts/ on sys.path, exactly as rank_criteria
# does for its own imports. Borrowed, never copied: one definition of the join, the floor, the clamp.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rank_criteria as rc

# Honor CLAUDE_PROJECT_DIR like the hook scripts do, so a sandbox (which sets it) writes to the
# sandbox's state dir; fall back to this file's repo when it is unset.
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# THE DEAD BAND, derived from the existing clamp — no new magic number. A signal earns the evidence
# lane only by moving at least HALFWAY to the clamp edge in log space: log2(sqrt(2.0)) = 0.5 =
# half of log2(2.0). Symmetric on the ratio scale. an illustrative ratified lift of 1.67 clears BAND_HI
# (separation, correctly); a 1.2x wobble sits inside the band (no-separation, correctly). Each run
# event records the band in force, so tightening or widening it later never corrupts recorded history.
BAND_HI = math.sqrt(rc.PERSON_LIFT_CLAMP[1])   # ~1.4142
BAND_LO = 1.0 / BAND_HI                         # ~0.7071

_VALID_JOINS = ("validate_signal", "warm_path_lift", "verdict_objective")


class ExpError(Exception):
    """A refusal the CLI turns into a non-zero exit. `code` defaults to 3 (the house 'refused' code:
    bad shape, leakage, or the floor guard), matching validate_signal's usage exit."""

    def __init__(self, msg, code=3):
        super().__init__(msg)
        self.code = code


def registry_path(repo=None):
    return os.path.join(repo or REPO, "documents", "state", "experiments.jsonl")


def _now():
    # A normal script (not a Workflow sandbox), so the wall clock is available. The timestamp is
    # AUDIT ONLY — ordering is file position, and append-only means file order is time order, so no
    # clock skew can reorder history.
    return datetime.now(timezone.utc).isoformat()


def _read_lines(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [ln for ln in fh.read().splitlines() if ln.strip()]


def _append(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _next_id(path):
    """max(existing EXP-NNN)+1, padded to three digits. Derived from the records themselves — never
    a clock or a random draw — so an empty registry mints EXP-000 and the two seeds land on their
    historical names for free."""
    hi = -1
    for ln in _read_lines(path):
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        m = str(rec.get("id") or "")
        if m.startswith("EXP-") and m[4:].isdigit():
            hi = max(hi, int(m[4:]))
    return f"EXP-{hi + 1:03d}"


def _leaky_fields(predicate):
    """The names in the predicate that are known only AFTER the send. One definition, imported from
    rank_criteria; this never keeps its own copy of the leakage vocabulary."""
    if not predicate:
        return []
    return [f for f in rc.LEAKY_FIELDS if f in predicate]


def project(path=None):
    """{id: {"proposed": row|None, "last_run": row|None, "decision": row|None}} — latest event wins
    per id, in one file-order pass. The file is never rewritten; this is the read side."""
    path = path or registry_path()
    proj = {}
    for ln in _read_lines(path):
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        eid = rec.get("id")
        if not eid:
            continue
        slot = proj.setdefault(eid, {"proposed": None, "last_run": None, "decision": None})
        ev = rec.get("event")
        if ev == "proposed":
            slot["proposed"] = rec
        elif ev == "run":
            slot["last_run"] = rec
        elif ev in ("ratified", "ruling"):
            slot["decision"] = rec
    return proj


def status_of(slot):
    """A short status string for `list`: proposed -> run:<verdict> -> ratified:<lane>(w=..) / ruling."""
    dec = slot.get("decision")
    if dec:
        if dec.get("event") == "ratified":
            return f"ratified:evidence(w={dec.get('weight')})"
        return "ruling"
    run = slot.get("last_run")
    if run:
        return f"run:{run.get('verdict')}"
    return "proposed"


# ── the verdict classifier ────────────────────────────────────────────────────────────────────────
def classify(with_cell, without_cell):
    """(verdict, lift|None, extra) for cells in [replies, sends] order (the join contract).

    verdict is one of: no-cells, underpowered, no-separation, separation.
    `extra` carries the direction ("+"/"-") for separation, or the underpowered reason, else None.
    Reuses rank_criteria._lift after SWAPPING into its [sends, replies] order (the load-bearing
    bridge). "underpowered" (n<15, the data said nothing) stays distinct from "no-separation"
    (n>=15, the data spoke and said flat)."""
    a_r, a_s = with_cell
    b_r, b_s = without_cell
    if a_s == 0:
        return "no-cells", None, None
    lift, _t, _b = rc._lift([a_s, a_r], [b_s, b_r])   # ⚠️ SWAP: [replies,sends] -> [sends,replies]
    if a_s < rc.WARM_PATH_MIN_N:
        return "underpowered", None, "n<%d" % rc.WARM_PATH_MIN_N
    if lift is None:
        # n cleared the floor but a base rate could not be formed (no replies in the base cell).
        return "underpowered", None, "base rate unformable"
    if BAND_LO < lift < BAND_HI:
        return "no-separation", lift, None
    return "separation", lift, ("+" if lift >= BAND_HI else "-")


# ── the four verbs ─────────────────────────────────────────────────────────────────────────────────
def propose(hypothesis, signal, predicate=None, population=None,
            join="validate_signal", objective="p-engage", path=None):
    """Append a proposed hypothesis. Refuses (ExpError, nothing written) a bad shape, an unknown
    join, a validate_signal experiment with no explicit predicate (the registry NEVER falls back to
    a built-in signal), or a leaky predicate. Returns the minted EXP-NNN id."""
    path = path or registry_path()
    if not hypothesis or not signal:
        raise ExpError("propose needs --hypothesis and --signal")
    if join not in _VALID_JOINS:
        raise ExpError(f"unknown --join {join!r}; choose one of {', '.join(_VALID_JOINS)}")
    if join == "validate_signal" and not predicate:
        raise ExpError("a validate_signal experiment needs an explicit --predicate; the registry "
                       "never falls back to a built-in signal (that would hardcode an owner-ism)")
    if join == "verdict_objective" and not predicate:
        try:
            import verdict_miner as _vm
            builtins = _vm.BUILTIN_POPULATIONS
        except Exception:
            builtins = ("board",)
        if (population or "company") not in builtins:
            raise ExpError("a verdict_objective experiment needs a --predicate unless --population is "
                           "a built-in boolean (" + ", ".join(builtins) + "), which takes none")
    leaks = _leaky_fields(predicate)
    if leaks:
        raise ExpError(f"REFUSED: predicate names {leaks}, known only AFTER the send — that is the "
                       "outcome leaking into the predictor. A feature must be send-date computable.")
    eid = _next_id(path)
    _append(path, {"event": "proposed", "id": eid, "ts": _now(),
                   "hypothesis": hypothesis, "signal": signal, "join": join,
                   "predicate": predicate, "population": population, "objective": objective})
    return eid


def run_experiment(exp_id, path=None):
    """Execute the proposed experiment's join, classify the result, append a run event, return it.
    NEVER ratifies — ratification is the user's, through `ratify`."""
    path = path or registry_path()
    proj = project(path)
    if exp_id not in proj or not proj[exp_id]["proposed"]:
        raise ExpError(f"{exp_id} has no proposed event to run")
    p = proj[exp_id]["proposed"]
    join = p.get("join", "validate_signal")
    with_cell = without_cell = unjoined = lift = direction = reason = None

    if join == "verdict_objective":
        # The EV objective: success is ACCEPTANCE (from the verdict miner), not a reply. Cells arrive
        # in the same [successes, population] order as every other join, so classify() is unchanged.
        import verdict_miner as _vm
        with_cell, without_cell, unjoined = _vm.verdict_cells(
            p.get("predicate"), p.get("population") or "company")
        verdict, lift, extra = classify(with_cell, without_cell)
        direction = extra if verdict == "separation" else None
        reason = extra if verdict == "underpowered" else None
    elif join == "warm_path_lift":
        _lf, wc, wo = rc.warm_path_lift()
        with_cell, without_cell = list(wc), list(wo)
        verdict, lift, extra = classify(with_cell, without_cell)
        direction = extra if verdict == "separation" else None
        reason = extra if verdict == "underpowered" else None
    else:
        res = rc.validate_signal(p["signal"], predicate=p.get("predicate"),
                                 population=p.get("population") or "note")
        if isinstance(res, dict) and res.get("error"):
            err = res["error"]
            if err == "unknown":
                # Unreachable by construction (propose forces an explicit predicate). If it happens,
                # it is a registry bug, not a measurement — surface it, do not log a fake verdict.
                raise ExpError(f"{exp_id}: validate_signal fell back to its built-in list — bug")
            verdict = err                      # "leaky" | "no-log" | "no-cells"
            with_cell = res.get("with")
            without_cell = res.get("without")
            unjoined = res.get("unjoined")
            if err == "leaky":
                reason = f"leaky fields: {res.get('fields')}"
        else:
            with_cell = res["with"]
            without_cell = res["without"]
            unjoined = res.get("unjoined")
            verdict, lift, extra = classify(with_cell, without_cell)
            direction = extra if verdict == "separation" else None
            reason = extra if verdict == "underpowered" else None

    ev = {"event": "run", "id": exp_id, "ts": _now(), "verdict": verdict,
          "with": with_cell, "without": without_cell, "unjoined": unjoined,
          "lift": round(lift, 4) if isinstance(lift, (int, float)) else None,
          "direction": direction, "floor": rc.WARM_PATH_MIN_N,
          "band": [round(BAND_LO, 4), round(BAND_HI, 4)], "reason": reason}
    _append(path, ev)
    return ev


def ratify(exp_id, lane, note, weight=None, path=None):
    """Append the user's judgment. The ONLY writer of ratified/ruling events — there is no code path
    from `run` to a decision. The EVIDENCE lane refuses a verdict the data cannot carry (it needs a
    'separation' run); the RULING lane is unconditional, because underpowered / judgment-heavy
    signals are exactly what it exists to hold."""
    path = path or registry_path()
    if lane not in ("evidence", "ruling"):
        raise ExpError("--lane must be 'evidence' or 'ruling'")
    if not note:
        raise ExpError("ratify needs --note (the judgment is the user's, in their words)")
    proj = project(path)
    if exp_id not in proj or not proj[exp_id]["proposed"]:
        raise ExpError(f"{exp_id} is not a known experiment")
    last = proj[exp_id]["last_run"]
    if lane == "evidence":
        if not last or last.get("verdict") != "separation":
            got = last.get("verdict") if last else "no run yet"
            raise ExpError(f"evidence lane needs a 'separation' run (this one is {got!r}). The "
                           "ruling lane is unconditional if you want a surfacing consult instead.")
        w = weight if weight is not None else last.get("lift")
        ev = {"event": "ratified", "id": exp_id, "ts": _now(),
              "lane": "evidence", "weight": w, "note": note}
    else:
        ev = {"event": "ruling", "id": exp_id, "ts": _now(), "lane": "ruling", "note": note}
    _append(path, ev)
    return ev


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────
USAGE = __doc__.split("Usage:", 1)[1].strip() if "Usage:" in __doc__ else "see --help"


def _print_list(as_json=False):
    proj = project()
    if as_json:
        print(json.dumps(proj, ensure_ascii=False, indent=2))
        return
    if not proj:
        print("no experiments yet — propose one: rank_experiments.py propose --hypothesis ...")
        return
    print(f"{'id':8} {'signal':22} {'status':26} {'n':>5}  {'lift':>5}  hypothesis")
    for eid in sorted(proj):
        slot = proj[eid]
        p = slot["proposed"] or {}
        run = slot["last_run"] or {}
        n = (run.get("with") or [None, None])[1]
        lift = run.get("lift")
        print(f"{eid:8} {str(p.get('signal'))[:22]:22} {status_of(slot):26} "
              f"{str(n if n is not None else '-'):>5}  {str(lift if lift is not None else '-'):>5}  "
              f"{str(p.get('hypothesis'))[:48]}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(USAGE)
        return 0
    verb = argv[0]

    def flag(name, default=None):
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                return argv[i + 1]
        return default

    def positional():
        # the first non-flag token after the verb (an EXP id), if any
        for tok in argv[1:]:
            if not tok.startswith("--"):
                return tok
        return None

    try:
        if verb == "propose":
            eid = propose(flag("--hypothesis"), flag("--signal"),
                          predicate=flag("--predicate"), population=flag("--population"),
                          join=flag("--join", "validate_signal"),
                          objective=flag("--objective", "p-engage"))
            print(f"✅ proposed {eid}: {flag('--hypothesis')}")
            return 0

        if verb == "run":
            if "--all-proposed" in argv:
                proj = project()
                todo = [eid for eid, s in sorted(proj.items())
                        if s["proposed"] and not s["last_run"]]
                if not todo:
                    print("nothing to run — every proposed experiment already has a run.")
                for eid in todo:
                    ev = run_experiment(eid)
                    print(f"  {eid}: {ev['verdict']}  (with {ev['with']} vs without {ev['without']})")
                return 0
            eid = positional()
            if not eid:
                print("usage: run <EXP-id>   |   run --all-proposed")
                return 3
            ev = run_experiment(eid)
            print(f"{eid}: {ev['verdict']}")
            print(f"   with    : {ev['with']} replied/sent")
            print(f"   without : {ev['without']} replied/sent")
            if ev.get("lift") is not None:
                print(f"   lift    : {ev['lift']}x  (dead band {ev['band']}, floor n>={ev['floor']})")
            if ev.get("direction"):
                print(f"   direction: {ev['direction']}")
            if ev.get("reason"):
                print(f"   note    : {ev['reason']}")
            return 0

        if verb == "list":
            _print_list(as_json="--json" in argv)
            return 0

        if verb == "ratify":
            eid = positional()
            if not eid:
                print("usage: ratify <EXP-id> --lane evidence|ruling --note '...' [--weight N]")
                return 3
            w = flag("--weight")
            ev = ratify(eid, lane=flag("--lane"), note=flag("--note"),
                        weight=float(w) if w is not None else None)
            if ev["event"] == "ratified":
                print(f"✅ {eid} ratified to the EVIDENCE lane, weight {ev['weight']}")
            else:
                print(f"✅ {eid} recorded to the RULING lane (surfacing consult, not a scored weight)")
            return 0

        print(f"unknown verb {verb!r}\n\n{USAGE}")
        return 3
    except ExpError as e:
        print(f"🔴 {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
