#!/usr/bin/env python3
"""check_ledger_guard.py — PreToolUse hook that DENIES any Write/Edit to the safety ledgers.

WHY (BUG-215 fast-follow, panel-driven). The runtime-budget ledger (documents/state/run-budget.jsonl)
is what `runtime_budget.check()` reads at the START of each unattended run to enforce the daily
token/agent cap. If a runaway or prompt-injected agent OVERWRITES it to zero, the next run sees a full
budget and the daily cap is defeated. The `--disallowedTools "Edit(...)"` fence only covers the Edit
tool — Claude Code silently ignores path scopes on the Write tool, and the Write tool cannot be
path-restricted at all. A PreToolUse hook is the one place that SEES the Write tool's target path and
can DENY it, so this closes the vector the --disallowedTools fence could not. It also guards the
MAC-signed decision ledger (documents/decision-ledger.jsonl) as defense in depth.

The ledgers are written by their OWN scripts as subprocesses (runtime_budget.record-from-stream,
record_decision.py), never by the agent's file tools, so denying the Write/Edit TOOLS on these paths
breaks nothing legitimate — it only stops an agent from hand-editing a safety ledger.

Wired in .claude/settings.json as a PreToolUse hook matching Write|Edit|MultiEdit. Protects EVERY
session (interactive and the unattended crons), matching the check_pair / check_preview pattern.

DENY = print the reason to stderr + exit 2 (the tool call is blocked, stderr is fed back to the model).
Fail-OPEN on an unparseable payload or a non-matching path (exit 0): the guard only ever DENIES on a
positively-identified write to a protected ledger, so a hook error can never wedge unrelated edits.
"""
import json
import os
import sys

# The ledgers this hook protects, as repo-relative paths. Kept as a tuple so adding one is a one-liner.
_PROTECTED_RELPATHS = (
    os.path.join("documents", "state", "run-budget.jsonl"),
    os.path.join("documents", "decision-ledger.jsonl"),
)


def _target_path(tool_name, tool_input):
    """The filesystem path a Write/Edit-family tool call would write, or None."""
    if not isinstance(tool_input, dict):
        return None
    # Write/Edit/MultiEdit use file_path; NotebookEdit uses notebook_path (never a .jsonl ledger).
    return tool_input.get("file_path") or tool_input.get("notebook_path")


def _is_protected(path):
    """True if `path` resolves to one of the protected ledgers.

    Resolves symlinks and `..` traversal via realpath so an agent cannot reach the ledger by an
    indirect path, and also matches on a repo-relative suffix so it holds regardless of the checkout
    root (the crons cd to the project dir; realpath anchors relative paths there)."""
    if not path:
        return False
    real = os.path.realpath(path)
    repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    for rel in _PROTECTED_RELPATHS:
        if real == os.path.realpath(os.path.join(repo, rel)):
            return True
        # suffix match as a backstop for an unusual cwd / absolute path from another root
        if real.replace(os.sep, "/").endswith("/" + rel.replace(os.sep, "/")):
            return True
    return False


_RING_DIRNAME = ".jobsearch-ledger-keys"
_KEYFILE_DEFAULT = "~/.jobsearch-ledger-key"


def _same_or_inside(real, root):
    root = os.path.realpath(root)
    return real == root or real.startswith(root + os.sep)


def _key_material_paths():
    """(files, folders) that decide which BUILD rulings the gate believes: the signing key (default and
    the one JOBKIT_LEDGER_KEYFILE names), the ring folder beside it, and every key file the ring list
    names. They live outside the project, so the repo-relative list cannot name them. A trust anchor
    cannot sit where the people it protects against can write it."""
    keyfile = os.path.expanduser(os.environ.get("JOBKIT_LEDGER_KEYFILE") or _KEYFILE_DEFAULT)
    files = {os.path.realpath(os.path.expanduser(_KEYFILE_DEFAULT)), os.path.realpath(keyfile)}
    folders = {os.path.realpath(os.path.expanduser(os.path.join("~", _RING_DIRNAME))),
               os.path.realpath(os.path.join(os.path.dirname(keyfile) or ".", _RING_DIRNAME))}
    for rd in list(folders):
        try:
            with open(os.path.join(rd, "ring.json"), "r", encoding="utf-8") as fh:
                for e in (json.load(fh) or {}).get("keys") or []:
                    if isinstance(e, dict) and e.get("path"):
                        files.add(os.path.realpath(os.path.expanduser(str(e["path"]))))
        except (OSError, ValueError, AttributeError):
            pass
    return files, folders


def _is_key_material(path):
    if not path:
        return False
    real = os.path.realpath(os.path.expanduser(path))
    files, folders = _key_material_paths()
    return real in files or any(_same_or_inside(real, f) for f in folders)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail-open: no parseable input, never wedge unrelated tool calls
    tool_name = payload.get("tool_name") or ""
    if tool_name not in ("Write", "Edit", "MultiEdit"):
        sys.exit(0)
    try:
        path = _target_path(tool_name, payload.get("tool_input") or {})
        if _is_key_material(path):
            print(
                "⛔ BLOCKED by check_ledger_guard: %s to %r is refused. This is the ledger's KEY MATERIAL "
                "(the signing key, the ring list, or a key file the ring names). It decides which BUILD "
                "rulings the send gate believes, so it is changed only by a person, with "
                "`python3 scripts/ledger_keys.py add`, never by an agent file tool." % (tool_name, path),
                file=sys.stderr)
            sys.exit(2)
        if _is_protected(path):
            print(
                "⛔ BLOCKED by check_ledger_guard: %s to %r is refused. This is a SAFETY LEDGER "
                "(the runtime-budget or decision ledger). It is written only by its own script as a "
                "subprocess, never by an agent file tool — editing it by hand would let a run erase "
                "its own spend and defeat the daily cap. If you believe a ledger is corrupt, tell "
                "the person who owns this install; do not edit it directly." % (tool_name, path),
                file=sys.stderr)
            sys.exit(2)
    except Exception:
        sys.exit(0)  # fail-open on any matching error: only DENY on a confirmed protected path
    sys.exit(0)


if __name__ == "__main__":
    main()
