#!/usr/bin/env python3
"""send_feedback.py — the ONE channel for upstream kit-defect feedback.

documents/ is git-ignored by design (it holds a partner's private working files), so nothing
written there ever reaches the kit maintainer via git. When a SHIPPED script or rule is broken,
docs/partner-feedback-protocol.md says: append a structured entry to
documents/partner-feedback.md, then run THIS script to send it. Transport is `gh issue create`
(repo: mestoy/job-attractor-kit) when `gh` is authenticated and can see that repo, otherwise a
mailto/copy-block fallback. NEVER git. NEVER auto-send — a human gate sits before every send.

Usage:  python3 scripts/send_feedback.py            (interactive: confirms before sending)
        python3 scripts/send_feedback.py --yes       (bypass the interactive confirm)

Importable: parse(), unsent(), scrub(), mark_sent() have no side effects beyond mark_sent's
own file write, and main() is the only thing that talks to gh or asks for confirmation.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Matches the sibling scripts' idiom (session_start.py etc.): $CLAUDE_PROJECT_DIR when the
# runtime sets it, otherwise the parent of this scripts/ dir when run standalone.
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)

FEEDBACK = "documents/partner-feedback.md"
KIT_REPO = "mestoy/job-attractor-kit"

# The single parser's contract. This regex lives ONLY here.
_HEADER_RE = re.compile(
    r"^##\s+FEEDBACK\s+(\d{4}-\d{2}-\d{2})\s+·\s+(.+?)\s+·\s+status:(unsent|sent\b[^\n]*|dropped\b[^\n]*)\s*$"
)


def _path(repo=None):
    return os.path.join(repo or REPO, FEEDBACK)


def parse(repo=None):
    """Return a list of {date, slug, status, raw_body, line_no} for every well-formed
    `## FEEDBACK ...` block in documents/partner-feedback.md.

    A malformed `##` line (one that does not match the header regex) is simply ignored — it
    never raises. `line_no` is the 1-based line number of the header line, used by mark_sent()
    to rewrite exactly that line.
    """
    p = _path(repo)
    try:
        with open(p, encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:
        return []

    entries = []
    current = None
    for i, line in enumerate(lines):
        m = _HEADER_RE.match(line.rstrip("\n"))
        if m:
            if current is not None:
                entries.append(current)
            current = {
                "date": m.group(1),
                "slug": m.group(2),
                "status": m.group(3),
                "raw_body": "",
                "line_no": i + 1,
            }
        elif current is not None:
            current["raw_body"] += line
    if current is not None:
        entries.append(current)
    return entries


def unsent(repo=None):
    """Entries whose status is exactly 'unsent'."""
    return [e for e in parse(repo) if e["status"] == "unsent"]


def scrub(text):
    """Replace /Users/<name>/... with ~ so nothing personally identifying leaves the machine."""
    return re.sub(r"/Users/[^/\s]+", "~", text or "")


def mark_sent(slug, via, repo=None):
    """Flip exactly the one matching entry's header line to status:sent, in place.

    Writes a `.bak` of the file first. Every other byte in the file is preserved.
    """
    p = _path(repo)
    with open(p, encoding="utf-8") as fh:
        lines = fh.readlines()

    from datetime import date as _date
    today = _date.today().isoformat()

    target_line_no = None
    for e in parse(repo):
        if e["slug"] == slug and e["status"] == "unsent":
            target_line_no = e["line_no"]
            break
    if target_line_no is None:
        return False

    idx = target_line_no - 1
    old_line = lines[idx].rstrip("\n")
    m = _HEADER_RE.match(old_line)
    if not m:
        return False
    new_line = f"## FEEDBACK {m.group(1)} · {m.group(2)} · status:sent {today} via:{via}\n"

    with open(p + ".bak", "w", encoding="utf-8") as fh:
        fh.writelines(lines)

    lines[idx] = new_line
    with open(p, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    return True


def _gh_available():
    """True only when BOTH `gh auth status` and `gh repo view <KIT_REPO>` succeed."""
    try:
        a = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=10)
        if a.returncode != 0:
            return False
        b = subprocess.run(["gh", "repo", "view", KIT_REPO], capture_output=True, timeout=10)
        return b.returncode == 0
    except Exception:
        return False


def _confirm(prompt, auto_yes):
    if auto_yes:
        return True
    try:
        ans = input(f"{prompt} y/N: ").strip().lower()
    except Exception:
        return False
    return ans == "y"


def _maintainer_email():
    """Guarded import: kit_config may not have MAINTAINER_EMAIL, or it may be blank/placeholder."""
    try:
        import kit_config
        email = getattr(kit_config, "MAINTAINER_EMAIL", "") or ""
        email = email.strip()
        if not email or email in ("you@example.com",):
            return ""
        return email
    except Exception:
        return ""


def _send_via_gh(entry, body):
    title = f"[partner-feedback] {entry['slug']}"
    try:
        r = subprocess.run(
            ["gh", "issue", "create", "-R", KIT_REPO, "--title", title, "--body", body],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        print(f"  [!] gh issue create failed to run: {e}")
        return False
    if r.returncode != 0:
        print(f"  [!] gh issue create failed: {r.stderr.strip()}")
        return False
    out = (r.stdout or "").strip()
    print(f"  [ok] {out}")
    m = re.search(r"/issues/(\d+)", out)
    n = m.group(1) if m else "?"
    mark_sent(entry["slug"], f"gh#{n}")
    return True


def _send_via_fallback(entry, body, auto_yes):
    print("\n  ── copy-and-send this ──────────────────────────────────────────")
    print("```")
    print(body)
    print("```")
    email = _maintainer_email()
    if email:
        subject = f"[partner-feedback] {entry['slug']}"
        print(f"\n  mailto:{email}?subject={subject}")
    else:
        # No maintainer address ships in the kit. Two channels that always work:
        print(f"\n  • email the block above to whoever sent you this kit")
        print(f"  • or, if you have a GitHub account: https://github.com/{KIT_REPO}/issues/new")
    print("  ─────────────────────────────────────────────────────────────────\n")
    if _confirm("paste-sent?", auto_yes):
        mark_sent(entry["slug"], "mailto")
        return True
    return False


def main():
    argv = sys.argv[1:]
    auto_yes = "--yes" in argv

    try:
        entries = unsent()
    except Exception as e:
        print(f"[send_feedback] could not read {FEEDBACK}: {type(e).__name__}: {e}")
        sys.exit(0)

    if not entries:
        print("🟢 nothing to send")
        sys.exit(0)

    try:
        gh_ok = _gh_available()
        for entry in entries:
            body = scrub(f"## FEEDBACK {entry['date']} · {entry['slug']} · "
                          f"status:{entry['status']}\n{entry['raw_body']}")
            print(f"\n── {entry['slug']} ({entry['date']}) ──")
            print(body)

            if not _confirm("send this entry?", auto_yes):
                print("  skipped.")
                continue

            if gh_ok:
                if not _send_via_gh(entry, body):
                    _send_via_fallback(entry, body, auto_yes)
            else:
                _send_via_fallback(entry, body, auto_yes)
    except Exception as e:
        print(f"[send_feedback] unexpected error, nothing further sent: {type(e).__name__}: {e}")
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
