#!/usr/bin/env python3
"""push_owner_gate.py: may backup.sh push to this remote? Exit 0 to allow, 3 to refuse.

The pre-launch audit (documents/state/pre-launch-audit-kit-2026-09-14.md, risk 1, critical):
backup.sh pushed to origin whenever origin existed, so on a partner's clone of the kit it would
have pushed their commits into the author's repo. This gate answers one question before any push:
does the person own the remote?

Rules, in order:
  1. no remote, or a remote with no GitHub owner in its URL (a local path, a bare mirror): allow;
     the old behavior, nothing here to protect.
  2. `gh api user` answers with a login: allow only when the login equals the URL's owner.
  3. gh is absent or fails: allow unless the owner is the kit author's account (mestoy); that is
     the one case the audit named, and it must never push blind.

Refusal prints plain words for the person and exits 3; backup.sh then keeps the local commit and
the documents/ snapshot and skips the push. Usage: push_owner_gate.py [remote-name]
"""
import re
import subprocess
import sys

KIT_AUTHOR = "mestoy"


def parse_owner(url):
    """The GitHub owner in a remote URL, or None when the URL names no GitHub owner."""
    if not url:
        return None
    m = re.match(r"^(?:https?://|ssh://)?(?:[^@/]+@)?github\.com[:/]([^/]+)/", url.strip())
    return m.group(1) if m else None


def gh_login(run=subprocess.run):
    """The GitHub login gh is signed in as, or None when gh is absent or not signed in."""
    try:
        p = run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    login = (p.stdout or "").strip()
    return login or None


def decide(owner, login):
    """(allowed, reason). reason is empty when allowed."""
    if owner is None:
        return True, ""
    if login is not None:
        if login == owner:
            return True, ""
        return False, "this remote belongs to %s, and you are signed in to GitHub as %s." % (owner, login)
    if owner == KIT_AUTHOR:
        return False, "this remote is the kit author's own repo (%s), not yours." % owner
    return True, ""


def remote_url(remote, run=subprocess.run):
    try:
        p = run(["git", "remote", "get-url", remote], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def main(argv):
    remote = argv[1] if len(argv) > 1 else "origin"
    owner = parse_owner(remote_url(remote))
    allowed, reason = decide(owner, gh_login() if owner else None)
    if allowed:
        return 0
    print("[i] Not pushing: %s" % reason)
    print("    Your work is committed here and the documents/ snapshot is saved, so nothing is lost.")
    print("    To back up online as well, fork the kit on GitHub and point this clone at your fork:")
    print("      git remote set-url %s https://github.com/<your-github-name>/job-attractor-kit.git" % remote)
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
