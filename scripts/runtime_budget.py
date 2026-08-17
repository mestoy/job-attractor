#!/usr/bin/env python3
"""runtime_budget.py — the ONE shared runtime cap for every unattended fan-out (BUG-215).

⛔ WHY (the pipeline safety assessment, CRITICAL). Two unattended crons (auto-sweep.sh,
job-attractor-prep.sh) and the multi-agent workflow runner each spawn headless `claude -p` agents
with WebFetch + Write/Edit, capped only by PROSE ("screen 8 or so"). A repo-wide search for any
runtime limiter returned zero hits; the only real cap was one workflow's REFUTE_CAP. One mis-scoped
instruction reproduces the "ran all night" failure, and it ships to every partner via the kit. This
module is the single mechanical backstop all of them consume — NOT a second limiter (it also satisfies
BUG-198 S6's "hard daily token+agent budget cap"; prefetch_dossiers.py, when built, imports this).

WHAT IT ENFORCES (the numbers are TUNABLE kit_config knobs; defaults here are deliberately
conservative/fail-safe, 2026-08-16):
  · MAX_TURNS_PER_AGENT      = 20        applied as `claude -p --max-turns`
  · RUN_WALL_CLOCK_SECONDS   = 720       applied by `runtime_budget run` (a portable watchdog)
  · MAX_COMPANIES_PER_SWEEP  = 8         enforced by record_finding.py refusing beyond it
  · DAILY_TOKEN_BUDGET       = 500_000   summed from the ledger; a run over it ABORTS before starting
  · DAILY_AGENT_BUDGET       = 10        same

⚖️ HARD STOP, NOT A TARGET. `check()` returns (False, reason) and the CLI exits non-zero so the cron
aborts BEFORE spending; `--max-turns` and the `run` watchdog bound the single run; the ledger bounds
the day. Two panel-found traps are closed here: the token count sums the CACHE token classes (not just
input+output — cache tokens dominate a real run, and omitting them undercounted spend ~1000x), and the
wall-clock runs through a stdlib process-group watchdog (`runtime_budget run`) because macOS ships no
`timeout` binary, so the old shell `timeout $_WALL` exited 127 and never bounded anything.
Honest limit: `claude -p` has no first-class max-CHILD-agents flag, so a nested Task-tool fan-out is
bounded transitively (turns + wall-clock + the daily token/agent ledger), not by a hard integer on
nested count. Documented so no one reads this as a per-nested-agent hard gate.

⛔ NO SILENT CAPS. Every abort/drop is written to the ledger and printed, per S6.

Usage (shell integration):
    python3 runtime_budget.py check <run>          # exit 0 ok · 3 over budget (abort the run)
    python3 runtime_budget.py max-turns            # prints the --max-turns value
    python3 runtime_budget.py wall-clock           # prints the wall-clock seconds
    python3 runtime_budget.py run --wall N -- CMD  # run CMD under a portable wall-clock (exit 124 on
                                                   # timeout, kills the whole process group)
    python3 runtime_budget.py record-from-stream <run>   # reads `claude -p --output-format
                                                         # stream-json` on stdin, records usage
    python3 runtime_budget.py status               # today's spend vs the caps
Stdlib only. Kit-portable (limits via kit_config, degrades to the defaults above).
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
LEDGER = os.path.join(REPO, "documents", "state", "run-budget.jsonl")

# Conservative fail-safe defaults. kit_config overrides each; a missing knob keeps the default here so
# an older kit_config never silently removes a cap (the fallback fails toward MORE restriction).
_DEFAULTS = {
    "MAX_TURNS_PER_AGENT": 20,
    "RUN_WALL_CLOCK_SECONDS": 720,
    "MAX_COMPANIES_PER_SWEEP": 8,
    "DAILY_TOKEN_BUDGET": 500_000,
    "DAILY_AGENT_BUDGET": 10,
}


def limit(name):
    """The tunable value for `name`, from kit_config if present, else the fail-safe default."""
    try:
        sys.path.insert(0, HERE)
        import kit_config
        v = getattr(kit_config, name, None)
        if isinstance(v, int) and v > 0:
            return v
    except Exception:
        pass
    return _DEFAULTS[name]


def _today(now=None):
    return (now or datetime.date.today()).isoformat()


def _rows():
    if not os.path.exists(LEDGER):
        return []
    out = []
    try:
        for line in open(LEDGER, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except Exception:
        pass
    return out


def today_spend(now=None):
    """(agents, tokens) summed over the ledger for today, EXCLUDING aborted rows (an aborted run
    spent nothing)."""
    d = _today(now)
    agents = tokens = 0
    for r in _rows():
        if r.get("date") != d or r.get("aborted"):
            continue
        agents += int(r.get("agents") or 0)
        tokens += int(r.get("tokens") or 0)
    return agents, tokens


def check(run, now=None):
    """(ok, reason). Call BEFORE a run. False when today's spend already meets/exceeds a daily cap —
    the run must then abort, and the abort is recorded (no silent cap)."""
    agents, tokens = today_spend(now)
    tok_cap, agt_cap = limit("DAILY_TOKEN_BUDGET"), limit("DAILY_AGENT_BUDGET")
    if tokens >= tok_cap:
        return False, f"daily token budget reached: {tokens:,} / {tok_cap:,}"
    if agents >= agt_cap:
        return False, f"daily agent budget reached: {agents} / {agt_cap}"
    return True, f"ok ({tokens:,}/{tok_cap:,} tokens, {agents}/{agt_cap} agents spent today)"


def record(run, agents=0, tokens=0, turns=0, wall_s=0, aborted=False, note="", now=None):
    """Append one ledger row. The ONLY writer. Never rewrites."""
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    row = {"date": _today(now), "run": run, "agents": int(agents), "tokens": int(tokens),
           "turns": int(turns), "wall_s": int(wall_s), "aborted": bool(aborted), "note": note,
           "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


_USAGE_KEYS = ("input_tokens", "output_tokens",
               "cache_read_input_tokens", "cache_creation_input_tokens")


def _sum_usage(u):
    """Sum EVERY token class Claude reports, not just input+output. Claude Code is cache-heavy: a
    real run's cache_read/cache_creation tokens dwarf the fresh input+output, and counting only the
    latter undercounted spend by ~1000x, so the daily token cap never tripped (BUG-215 panel)."""
    return sum(int(u.get(k) or 0) for k in _USAGE_KEYS) if isinstance(u, dict) else 0


def _usage_from_stream(text):
    """(tokens, turns) parsed from `claude -p --output-format stream-json` output.

    The terminal `result` event carries an authoritative CUMULATIVE usage for the whole run; when it
    is present it WINS over the per-event running sum (so cache tokens are not double counted). Absent
    a result event we fall back to summing per-event usage. Best-effort: unparseable → (0, 0), so a
    telemetry gap records a zero rather than crashing the cron — but the run-level wall-clock and
    max-turns still bound that run."""
    running = turns = 0
    result_total = None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        u = ev.get("usage") or (ev.get("message") or {}).get("usage") or {}
        if ev.get("type") == "result":
            ru = ev.get("usage") or (ev.get("message") or {}).get("usage") or {}
            if isinstance(ru, dict) and any(k in ru for k in _USAGE_KEYS):
                result_total = _sum_usage(ru)
        else:
            running += _sum_usage(u)
        if ev.get("type") == "assistant" or ev.get("role") == "assistant":
            turns += 1
    # Prefer the cumulative result total, but never let it UNDERcount a larger per-event sum.
    total = max(result_total, running) if result_total is not None else running
    return total, turns


def _run_with_wall_clock(cmd, wall_s):
    """Exec `cmd` (an argv list) under a PORTABLE wall-clock ceiling. Returns the child's exit code,
    or 124 on timeout (matching GNU `timeout`). stdout/stderr are inherited, so a downstream pipe
    (`... | tee | record-from-stream`) still sees the child's stream. On timeout the whole PROCESS
    GROUP is signalled — SIGTERM, then SIGKILL after a short grace — so a hung grandchild cannot
    outlive the ceiling (the gap GNU `timeout` needs -k for).

    WHY this exists: macOS ships no `timeout` (and no `gtimeout` unless coreutils is linked), so the
    cron's `timeout $_WALL ...` exited 127 and the wall-clock ceiling never actually ran on the target
    host (BUG-215 panel). This stdlib watchdog is the cross-platform replacement."""
    import signal
    import subprocess
    try:
        proc = subprocess.Popen(cmd, start_new_session=True)
    except FileNotFoundError as e:
        print(f"runtime_budget run: command not found: {e}", file=sys.stderr)
        return 127
    try:
        return proc.wait(timeout=wall_s)
    except subprocess.TimeoutExpired:
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        print(f"runtime_budget run: wall-clock {wall_s}s exceeded, killed process group",
              file=sys.stderr)
        return 124


def main():
    ap = argparse.ArgumentParser(description="the shared runtime cap for unattended fan-out")
    sub = ap.add_subparsers(dest="cmd")
    for c in ("check", "record-from-stream"):
        s = sub.add_parser(c)
        s.add_argument("run")
    sub.add_parser("max-turns")
    sub.add_parser("wall-clock")
    sub.add_parser("status")
    r = sub.add_parser("run")
    r.add_argument("--wall", type=int, default=None, help="wall-clock seconds (default: the knob)")
    r.add_argument("--run", dest="run_name", default="run")
    r.add_argument("argv", nargs=argparse.REMAINDER, help="-- command to run under the ceiling")
    a = ap.parse_args()

    if a.cmd == "max-turns":
        print(limit("MAX_TURNS_PER_AGENT")); return 0
    if a.cmd == "wall-clock":
        print(limit("RUN_WALL_CLOCK_SECONDS")); return 0
    if a.cmd == "check":
        ok, reason = check(a.run)
        if ok:
            print(f"✅ {reason}"); return 0
        record(a.run, aborted=True, note=reason)     # no silent cap: the abort is on the record
        print(f"⛔ ABORT {a.run}: {reason}", file=sys.stderr); return 3
    if a.cmd == "record-from-stream":
        text = sys.stdin.read()
        tokens, turns = _usage_from_stream(text)
        # one agent per invocation at this layer (nested agents are bounded by turns/wall-clock/day)
        row = record(a.run, agents=1, tokens=tokens, turns=turns)
        print(f"recorded {a.run}: {tokens:,} tokens, {turns} turns")
        return 0
    if a.cmd == "run":
        wall = a.wall if a.wall else limit("RUN_WALL_CLOCK_SECONDS")
        argv = a.argv
        if argv and argv[0] == "--":
            argv = argv[1:]
        if not argv:
            print("runtime_budget run: no command given (use: run --wall N -- cmd ...)",
                  file=sys.stderr)
            return 2
        return _run_with_wall_clock(argv, wall)
    if a.cmd == "status":
        agents, tokens = today_spend()
        print(f"today: {tokens:,}/{limit('DAILY_TOKEN_BUDGET'):,} tokens · "
              f"{agents}/{limit('DAILY_AGENT_BUDGET')} agents · "
              f"per-agent max-turns {limit('MAX_TURNS_PER_AGENT')} · "
              f"wall-clock {limit('RUN_WALL_CLOCK_SECONDS')}s · "
              f"companies/run {limit('MAX_COMPANIES_PER_SWEEP')}")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
