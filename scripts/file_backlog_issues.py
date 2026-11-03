#!/usr/bin/env python3
"""File .github/ISSUE_BACKLOG.md into GitHub issues, in one pass.

WHY THIS EXISTS: `gh` stores its token in the macOS keychain, which a non-interactive ssh shell
cannot unlock, so the container cannot file these even with `gh` authenticated on the Mac. This
runs in the owner's own Terminal, where the keychain is available.

Sections 1, 2, 3, 4 and 4b are filed. Section 5 is deliberately excluded — those rows are
specific to one job search, and both issue templates say the tracker is for defects in the
shipped kit. Sections differ in DISPOSITION as well as inclusion: §1 and §4b are already fixed
(file, then close as completed), §2/§3/§4 are filed as open. SECTION_DISPOSITION below is the
single place that mapping lives — an unknown section heading is a hard error, never a silent skip.

DRY RUN BY DEFAULT. Nothing is created until --apply.

Run:  python3 scripts/file_backlog_issues.py            # show what would be filed
      python3 scripts/file_backlog_issues.py --apply    # create them
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
BACKLOG = os.path.join(REPO_ROOT, ".github", "ISSUE_BACKLOG.md")
ITEM_RE = re.compile(r"^\*\*\[(bug|enhancement)\]\s+(.+?)\*\*(.*)$")
# Accepts a letter suffix: "## 4b." is its own section, NOT a continuation of "## 4.".
SECTION_RE = re.compile(r"^## (\d+[a-z]?)\.")

# What happens to each section's rows, stated once. "shipped" = file it, then close as completed;
# "open" = file it and leave it open; None = never file it. Section NUMBERS carry no meaning here
# — only this table does, so a renumbered backlog cannot change a row's disposition by accident.
SECTION_DISPOSITION = {
    "1": "shipped",   # Shipped — file and close, or file as already-fixed
    "2": "open",      # Current — in flight
    "3": "open",      # Intended — file as open
    "4": "open",      # Future — file as open, no date
    "4b": "shipped",  # Also shipped — the accessibility pass, file as already-fixed
    "5": None,        # Deliberately NOT GitHub issues
}


def parse(path):
    """Read every section named in SECTION_DISPOSITION and tag each item with its disposition.

    A heading this map does not know raises rather than being skipped: the backlog HAS been
    restructured before (§3 went from "excluded" to "file as open" and §4b appeared), and the
    failure that caused was a parser that returned a short list and looked successful.
    """
    section, items = None, []
    cur = None
    seen = set()
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    for line in lines:
        m = SECTION_RE.match(line)
        if m:
            section, cur = m.group(1), None
            if section not in SECTION_DISPOSITION:
                raise ValueError(
                    "unknown backlog section '## %s.' in %s — the backlog was restructured. "
                    "Give it a disposition in SECTION_DISPOSITION before filing anything."
                    % (section, path))
            seen.add(section)
            continue
        disposition = SECTION_DISPOSITION.get(section)
        if disposition is None:
            cur = None
            continue
        m = ITEM_RE.match(line)
        if m:
            kind, title, tail = m.group(1), m.group(2).strip(), m.group(3)
            ref = re.search(r"`(BUG-\d+)`", tail)
            cur = {"kind": kind, "title": title, "section": section,
                   "disposition": disposition,
                   "ref": ref.group(1) if ref else None, "body": []}
            items.append(cur)
        elif cur is not None and line.strip():
            cur["body"].append(line.rstrip())
    if not seen:
        raise ValueError(
            "no '## N.' sections found in %s — this is not a backlog in the expected shape. "
            "Filing nothing would look like success; refusing instead." % path)
    return items


def existing_titles(repo):
    try:
        out = subprocess.run(["gh", "issue", "list", "-R", repo, "--state", "all",
                              "--limit", "300", "--json", "title"],
                             capture_output=True, text=True, check=True).stdout
        return {r["title"].strip() for r in json.loads(out or "[]")}
    except Exception as e:
        print(f"!! could not list existing issues ({e}). Refusing to risk duplicates.", file=sys.stderr)
        raise SystemExit(2)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="mestoy/job-attractor-kit")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    items = parse(BACKLOG)
    if not items:
        print("no items parsed — has the backlog format changed?", file=sys.stderr)
        return 2

    have = existing_titles(a.repo) if a.apply else set()
    made = skipped = 0
    for it in items:
        label = "bug" if it["kind"] == "bug" else "enhancement"
        title = it["title"] if not it["ref"] else f'{it["title"]} ({it["ref"]})'
        body = "\n".join(it["body"]).strip()
        if it["disposition"] == "shipped":
            body += "\n\n---\nAlready fixed; filed so the record carries the defect, not only the commit."
        tag = "completed→close" if it["disposition"] == "shipped" else "open"
        if title in have:
            print(f"  skip (exists): {title}")
            skipped += 1
            continue
        print(f"  [{tag}] [{label}] {title}")
        if not a.apply:
            continue
        r = subprocess.run(["gh", "issue", "create", "-R", a.repo, "--title", title,
                            "--body", body, "--label", label],
                           capture_output=True, text=True)
        if r.returncode != 0:
            # A missing label must not lose the issue; retry once without it.
            r = subprocess.run(["gh", "issue", "create", "-R", a.repo, "--title", title,
                                "--body", body], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"    !! failed: {r.stderr.strip()[:200]}")
            continue
        url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        print(f"    created {url}")
        made += 1
        if it["disposition"] == "shipped" and url:
            subprocess.run(["gh", "issue", "close", url, "--reason", "completed",
                            "--comment", f"Fixed and shipped with a red-then-green test"
                                         f"{' (' + it['ref'] + ')' if it['ref'] else ''}."],
                           capture_output=True, text=True)
            print("    closed as completed")
    verb = "created" if a.apply else "would create"
    per_section = ", ".join(
        f"§{s}: {sum(1 for i in items if i['section'] == s)}"
        for s in SECTION_DISPOSITION if any(i["section"] == s for i in items))
    shipped = sum(1 for i in items if i["disposition"] == "shipped")
    print(f"\n{verb} {made if a.apply else len(items) - skipped}, skipped {skipped}"
          f"  ({shipped} already-fixed→close, {len(items) - shipped} open; {per_section})")
    if not a.apply:
        print("DRY RUN — nothing was created. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
