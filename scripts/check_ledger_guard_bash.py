#!/usr/bin/env python3
"""check_ledger_guard_bash.py — PreToolUse hook that DENIES a shell command that would discard or
overwrite a protected safety ledger.

WHY (2026-09-13 retro parking-lot item). check_ledger_guard.py DENIES the Write/Edit/MultiEdit
TOOLS on the protected ledgers, but it never sees a Bash tool call. Twice on 2026-09-13 a seat ran
`git checkout --` on documents/decision-ledger.jsonl as side-effect cleanup and discarded
hook-signed rulings that cannot be restored (a backdated restore is audit tampering and was
refused). This is the sibling hook: it inspects the Bash tool's `command` string and DENIES any
git checkout/restore/reset/stash/clean invocation, or raw shell redirection/truncation, that names
a protected ledger or would sweep the whole working tree (which takes the ledger with it).

Both ledgers from check_ledger_guard._PROTECTED_RELPATHS are covered here, not only the decision
ledger that prompted this: `git reset --hard` / `git checkout -- .` / a bare `git stash` sweep
EVERY file in the tree, so the run-budget ledger is exposed to the same commands.

Wired in .claude/settings.json as a PreToolUse hook matching Bash. DENY = print the reason to
stderr + exit 2 (the tool call is blocked, stderr is fed back to the model). Fail-OPEN on any
unparseable payload, non-Bash tool, or internal error (exit 0): this guard only ever DENIES on a
positively-identified dangerous command, so it can never wedge a legitimate Bash call — including
reads (git diff/log/show, cat, tail, grep) and edits to files that only happen to share a name
with a ledger.
"""
import fnmatch
import json
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_ledger_guard import _PROTECTED_RELPATHS  # noqa: E402

_SEPARATORS = {";", "&&", "||", "|"}
_SWEEP_TOKENS = {".", "./"}
_DESTRUCTIVE_VERBS = {"checkout", "restore", "reset", "stash", "clean"}


def _matches_protected(token):
    """True if `token` (a raw arg from a shell command, possibly a glob or a bare filename)
    would name or match one of the protected ledgers."""
    if not token or token.startswith("-") or token == "--":
        return False
    t = token[2:] if token.startswith("./") else token
    norm = t.replace(os.sep, "/")
    has_glob = any(c in norm for c in "*?[")
    for rel in _PROTECTED_RELPATHS:
        rel_fwd = rel.replace(os.sep, "/")
        if has_glob:
            if fnmatch.fnmatch(rel_fwd, norm):
                return True
            if "/" not in norm and fnmatch.fnmatch(os.path.basename(rel_fwd), norm):
                return True
            continue
        if norm == rel_fwd or norm == os.path.basename(rel_fwd):
            return True
        try:
            real = os.path.realpath(token)
            repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
            if real == os.path.realpath(os.path.join(repo, rel)):
                return True
            if real.replace(os.sep, "/").endswith("/" + rel_fwd):
                return True
        except Exception:
            pass
    return False


def _tokenize(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def _git_invocations(tokens):
    """Yield the arg list following each 'git' token, bounded by the next separator token."""
    for i, tok in enumerate(tokens):
        if tok != "git":
            continue
        args = []
        j = i + 1
        while j < len(tokens) and tokens[j] not in _SEPARATORS:
            args.append(tokens[j])
            j += 1
        yield args


def _dangerous_git_reason(args):
    if not args:
        return None
    verb = args[0].lower()
    if verb not in _DESTRUCTIVE_VERBS:
        return None
    rest = args[1:]

    if verb in ("checkout", "restore"):
        path_tokens = [a for a in rest if not a.startswith("-")]
        if verb == "restore" and not path_tokens:
            return "git restore with no pathspec restores everything from HEAD, ledger included"
        if any(a in _SWEEP_TOKENS for a in path_tokens):
            return f"git {verb} with a bare '.' pathspec sweeps the whole tree"
        for a in path_tokens:
            if _matches_protected(a):
                return f"git {verb} targets the protected ledger ({a})"
        return None

    if verb == "reset":
        if any(a == "--hard" for a in rest):
            return "git reset --hard sweeps the working tree unconditionally"
        for a in rest:
            if not a.startswith("-") and _matches_protected(a):
                return f"git reset targets the protected ledger ({a})"
        return None

    if verb == "stash":
        subverb = rest[0].lower() if rest and not rest[0].startswith("-") else None
        if subverb not in (None, "push", "save"):
            return None  # pop/apply/drop/clear/list/show never discard working-tree content
        tail = rest[1:] if subverb else rest
        path_tokens = [a for a in tail if not a.startswith("-") and a != "--"]
        if not path_tokens:
            return "git stash with no pathspec hides all uncommitted changes, ledger included"
        for a in path_tokens:
            if _matches_protected(a):
                return f"git stash targets the protected ledger ({a})"
        return None

    if verb == "clean":
        force = any(a.startswith("-") and ("f" in a or a == "--force") for a in rest)
        path_tokens = [a for a in rest if not a.startswith("-")]
        if force and not path_tokens:
            return "git clean -f with no pathspec sweeps untracked files, ledger included"
        for a in path_tokens:
            if _matches_protected(a):
                return f"git clean targets the protected ledger ({a})"
        return None

    return None


def _dangerous_redirection_reason(tokens):
    for i, tok in enumerate(tokens):
        if tok in (">", ">>") and i + 1 < len(tokens) and _matches_protected(tokens[i + 1]):
            return f"shell redirection ({tok}) writes over the protected ledger ({tokens[i + 1]})"
    for i, tok in enumerate(tokens):
        if tok != "truncate":
            continue
        j = i + 1
        while j < len(tokens) and tokens[j] not in _SEPARATORS:
            if _matches_protected(tokens[j]):
                return f"truncate targets the protected ledger ({tokens[j]})"
            j += 1
    return None


def _reason(command):
    tokens = _tokenize(command)
    if not tokens:
        return None
    for args in _git_invocations(tokens):
        reason = _dangerous_git_reason(args)
        if reason:
            return reason
    return _dangerous_redirection_reason(tokens)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail-open: no parseable input, never wedge unrelated Bash calls
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        sys.exit(0)
    try:
        command = (payload.get("tool_input") or {}).get("command")
        if not isinstance(command, str) or not command.strip():
            sys.exit(0)
        reason = _reason(command)
        if reason:
            print(
                "⛔ BLOCKED by check_ledger_guard_bash: %r is refused. %s. This is a SAFETY "
                "LEDGER (hook-signed rulings that cannot be restored). If you need to clean up "
                "the working tree, target other paths explicitly and leave the ledger out of "
                "the pathspec; if you believe the ledger is corrupt, tell the person who owns "
                "this install, do not discard or overwrite it." % (command, reason),
                file=sys.stderr)
            sys.exit(2)
    except Exception:
        sys.exit(0)  # fail-open on any matching error: only DENY on a confirmed dangerous command
    sys.exit(0)


if __name__ == "__main__":
    main()
