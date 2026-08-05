#!/usr/bin/env python3
"""What changed in the kit since you last looked.

WHY THIS EXISTS. The kit updates itself from the maintainer's repo, so scripts and rules change
underneath a partner who never asked for it and is given no way to find out what moved. A silent
update is indistinguishable from a bug: the briefing prints something new, the ranker orders people
differently, and the only available explanation is "it broke".

⚠️ TWO FILES, TWO PURPOSES, and conflating them loses both:
  · `partner-docs/RELEASE-NOTES.md`  — what the MAINTAINER changed in the kit. Ships with updates,
                                      overwritten on every sync. Newest at the TOP.
  · `documents/JOB-ATTRACTOR-CHANGELOG.md` — what YOU changed in YOUR pipeline. Yours, append-only,
                                      never overwritten by an update. Newest at the BOTTOM.

The seen-stamp lives in `documents/state/release-seen.json`, which is YOURS and is never shipped,
so an update cannot mark its own notes as read.

  release_notes.py            # print the notes you have not seen, then say how to mark them read
  release_notes.py --all      # the whole history
  release_notes.py --check    # exit 0 if there is something unseen, 1 if not (for the briefing)
  release_notes.py --seen     # mark the current version read
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)

# Shipped by the maintainer. `partner-docs/` is the template layer; install.sh copies from it, so
# read BOTH and prefer whichever exists. A partner who never ran install still gets the notes.
NOTES_CANDIDATES = (
    os.path.join(REPO, "partner-docs", "RELEASE-NOTES.md"),
    os.path.join(REPO, "documents", "RELEASE-NOTES.md"),
)
SEEN_PATH = os.path.join(REPO, "documents", "state", "release-seen.json")

_VERSION_HEADING = re.compile(r"^##\s+(v[\w.\-]+)", re.M)


def notes_path():
    for p in NOTES_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def load_notes():
    """[(version, body)], newest first — the order the file is written in."""
    p = notes_path()
    if not p:
        return []
    try:
        text = open(p, encoding="utf-8", errors="ignore").read()
    except OSError:
        return []
    marks = list(_VERSION_HEADING.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1), text[m.start():end].rstrip()))
    return out


def seen_version():
    try:
        with open(SEEN_PATH, encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("version") or ""
    except (OSError, ValueError):
        # ⚖️ FAIL TOWARD SHOWING. An unreadable stamp means we cannot prove the partner has seen
        # the notes, and the cost of showing them twice is a shrug while the cost of hiding a
        # breaking change is a day spent debugging the kit instead of using it.
        return ""


def unseen():
    """Versions newer than the stamp. Position in the file is the order of record, so anything
    ABOVE the seen version is unseen — no version parsing, which would need a scheme the partner's
    maintainer has not promised to follow."""
    notes = load_notes()
    if not notes:
        return []
    mark = seen_version()
    if not mark:
        return notes
    for i, (ver, _body) in enumerate(notes):
        if ver == mark:
            return notes[:i]
    return notes          # stamp names a version not in the file: show everything


def mark_seen():
    notes = load_notes()
    if not notes:
        print("no release notes shipped with this kit yet.")
        return 0
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w", encoding="utf-8") as fh:
        json.dump({"version": notes[0][0]}, fh, indent=1)
    print(f"✅ marked read through {notes[0][0]}.")
    return 0


def banner():
    """One line for the session briefing, or '' when there is nothing new."""
    new = unseen()
    if not new:
        return ""
    vers = ", ".join(v for v, _ in new[:3])
    more = f" (+{len(new) - 3} more)" if len(new) > 3 else ""
    return (f"  📰 KIT UPDATED: {len(new)} release note(s) you have not read — {vers}{more}\n"
            f"       see what changed:  python3 scripts/release_notes.py")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="print every release note")
    ap.add_argument("--check", action="store_true", help="exit 0 if something is unseen")
    ap.add_argument("--seen", action="store_true", help="mark the current version read")
    a = ap.parse_args()
    if a.seen:
        return mark_seen()
    if a.check:
        return 0 if unseen() else 1
    rows = load_notes() if a.all else unseen()
    if not rows:
        p = notes_path()
        if not p:
            print("no RELEASE-NOTES.md shipped with this kit yet.")
        else:
            print(f"✅ up to date — nothing new since {seen_version() or 'the beginning'}.")
            print("   full history:  python3 scripts/release_notes.py --all")
        return 0
    for _ver, body in rows:
        print(body)
        print()
    if not a.all:
        print("── mark these read:  python3 scripts/release_notes.py --seen")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
