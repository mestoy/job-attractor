#!/usr/bin/env python3
"""reference_docs.py — generate the API-style reference from the code itself.

WHY THIS EXISTS. A new user's first question is never "what is this product". It is "what does this
one thing do, when does it run, and what happens when it fails". Good developer documentation
answers that in the same shape every time, so a reader learns the shape once and then reads fast.

⚖️ THE SAME THESIS AS `product_docs.py`, borrowed from FORGE. Evidence is generated rather than
assembled. Every entry below is read out of the source at build time: the summary comes from the
module docstring, the invocation from the declared `Usage:` block, the exit codes from the declared
`Exit:` line, and **when it fires** from the wired hooks in `.claude/settings.json`. Nothing is
transcribed by hand, so an entry cannot describe a script that no longer behaves that way.

⚠️ WHAT THIS MAKES VISIBLE, and it is meant to. A script with no `Usage:` block gets an entry that
says so. The gap is the finding: an undocumented surface is one a new user cannot use, and printing
a blank is more honest than printing nothing.

⛔ READ-ONLY except for its own output. Exits 0 even when a reader fails.

Usage:
    scripts/reference_docs.py             # write documents/product/REFERENCE.md
    scripts/reference_docs.py --stdout    # print it instead
    scripts/reference_docs.py --gaps      # list only the undocumented surfaces
    scripts/reference_docs.py --check     # exit 1 if the written file is stale
Exit: 0 normally · 1 only for --check when stale
"""
import argparse
import ast
import glob
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
OUT = os.path.join(REPO, "documents", "product", "REFERENCE.md")

# Grouping is by WHAT A READER IS TRYING TO DO, never by file type. A reference sorted
# alphabetically makes the reader already know the answer to find the answer.
GROUPS = [
    ("Gates that can block you", r"^check_|^record_(decision|chat_ruling|scorecard)"),
    ("The daily loop", r"^(session_start|pair_brief|rung_ladder|rank_criteria|rank_network)"),
    ("Finding and screening", r"^(screen_|sweep_|crawl_|resolve_|reconcile_|findings_|boss_registry)"),
    ("Writing and sending", r"^(mail-draft|log_linkedin_send|voice_samples|check_outreach)"),
    ("Your stores", r"^(state|closeness|parse_|ingest_|backfill_|sync_|contact_signals|schema)"),
    ("Keeping it healthy", r"^(doctor|durability|consistency|kit_|pii_gate|verify_|product_docs|reference_docs)"),
]


def _rd(p):
    try:
        with open(p, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def summary_and_blocks(path):
    """(summary, usage, exitline) read from the source, never transcribed."""
    src = _rd(path)
    doc = ""
    if path.endswith(".py"):
        try:
            doc = ast.get_docstring(ast.parse(src)) or ""
        except Exception:
            doc = ""
    else:
        # Shell: the leading comment block is the docstring by convention here.
        lines = []
        for line in src.splitlines()[1:]:
            if not line.startswith("#"):
                break
            lines.append(line.lstrip("# ").rstrip())
        doc = "\n".join(lines)

    # Summary = the first sentence after the "name — " prefix, which every module here uses.
    first = (doc.strip().split("\n\n") or [""])[0].replace("\n", " ").strip()
    first = re.sub(r"^[\w.-]+\s*[—-]\s*", "", first)
    # ⚖️ The SOURCE keeps its own header convention (`name.py — summary`), which is code, not prose.
    # This document IS prose, so it follows the house rules on the way out: no em dashes, no spaces
    # around a slash. Normalizing here beats rewriting 50 docstrings to satisfy a linter that was
    # never aimed at them.
    first = first.replace(" — ", ", ").replace("—", ", ").replace(" / ", "/")
    summary = first.strip()

    usage = ""
    m = re.search(r"^Usage:\s*\n((?:[ \t]+.*\n?)+)", doc, re.M)
    if m:
        usage = "\n".join(l.strip() for l in m.group(1).splitlines() if l.strip())

    exitline = ""
    m = re.search(r"^Exit:?\s*(.+)$", doc, re.M)
    if m:
        exitline = m.group(1).strip()
    return summary, usage, exitline


def hook_map():
    """script name → the events that run it. This is the 'when does it fire' column, and it is the
    single most useful fact about a gate: a reader needs to know it runs whether or not they call
    it."""
    out = {}
    try:
        cfg = json.loads(_rd(os.path.join(REPO, ".claude", "settings.json")) or "{}")
        for ev, groups in (cfg.get("hooks") or {}).items():
            for g in groups or []:
                for h in (g.get("hooks") or []):
                    for m in re.finditer(r"scripts/([A-Za-z0-9_.-]+)", str(h.get("command") or "")):
                        out.setdefault(m.group(1), set()).add(ev)
    except Exception:
        pass
    return {k: sorted(v) for k, v in out.items()}


def commands():
    rows = []
    for p in sorted(glob.glob(os.path.join(REPO, ".claude", "commands", "*.md"))):
        name = os.path.basename(p)[:-3]
        src = _rd(p)
        m = re.search(r"^#\s*/?[\w-]+\s*[-—]\s*(.+)$", src, re.M)
        title = m.group(1).strip() if m else ""
        body = re.sub(r"^#.*$", "", src, count=1, flags=re.M).strip()
        first = (body.split("\n\n") or [""])[0].replace("\n", " ").strip()
        rows.append((name, title, first[:280]))
    return rows


def group_for(name):
    for label, pat in GROUPS:
        if re.search(pat, name):
            return label
    return "Everything else"


def render():
    hooks = hook_map()
    files = sorted(glob.glob(os.path.join(REPO, "scripts", "*.py"))
                   + glob.glob(os.path.join(REPO, "scripts", "*.sh")))
    entries = {}
    gaps = []
    for p in files:
        name = os.path.basename(p)
        s, u, e = summary_and_blocks(p)
        if not u:
            gaps.append(name)
        entries.setdefault(group_for(name), []).append((name, s, u, e, hooks.get(name, [])))

    L = []
    a = L.append
    a("# Reference")
    a("")
    a(f"> **Generated by `scripts/reference_docs.py` on {date.today()}.** Every entry is read from "
      f"the source at build time. The summary is the module docstring, the invocation is the "
      f"declared usage block, and **when it fires** comes from the wired hooks. Do not hand edit "
      f"this file.")
    a("")
    a("Each entry answers the same four questions in the same order, so you learn the shape once.")
    a("")
    a("| | |")
    a("|---|---|")
    a("| **What it does** | one sentence, from the source |")
    a("| **When it fires** | on its own via a hook, or only when you run it |")
    a("| **How to run it** | the declared invocation |")
    a("| **What the exit codes mean** | 0 is not always success; some of these gate a workflow |")
    a("")
    a("---")
    a("")

    for label, _pat in GROUPS + [("Everything else", "")]:
        rows = entries.get(label)
        if not rows:
            continue
        a(f"## {label}")
        a("")
        for name, s, u, e, ev in sorted(rows):
            a(f"### `{name}`")
            a("")
            a(s or "_No module docstring._")
            a("")
            if ev:
                a(f"**When it fires.** Automatically on `{'`, `'.join(ev)}`. It runs whether or not "
                  f"you call it.")
            else:
                a("**When it fires.** Only when you run it.")
            a("")
            if u:
                a("```")
                for line in u.splitlines():
                    a(line)
                a("```")
            else:
                a("⚠️ **No declared usage.** Run it with `--help` if it takes arguments. An "
                  "undocumented surface is one a new user cannot reach.")
            a("")
            if e:
                a(f"**Exit.** {e}")
                a("")
        a("---")
        a("")

    cmds = commands()
    if cmds:
        a("## Commands")
        a("")
        a("Typed as `/name` in a session. These are workflows rather than scripts: each one is a "
          "procedure the assistant follows, with its own gates.")
        a("")
        for name, title, first in cmds:
            a(f"### `/{name}`")
            a("")
            if title:
                a(f"**{title}**")
                a("")
            if first:
                a(first)
                a("")
        a("---")
        a("")

    if gaps:
        a("## Documentation gaps")
        a("")
        a(f"{len(gaps)} of {len(files)} scripts declare no usage block, so this reference cannot "
          f"tell a reader how to run them. Listed rather than hidden, because the gap is the "
          f"finding.")
        a("")
        a(", ".join(f"`{g}`" for g in gaps))
        a("")

    a("*Regenerate with `python3 scripts/reference_docs.py`. Check staleness with `--check`.*")
    return "\n".join(L) + "\n", gaps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--gaps", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    doc, gaps = render()
    if a.gaps:
        print(f"{len(gaps)} script(s) with no declared usage block:")
        for g in gaps:
            print("  ", g)
        return 0
    if a.stdout:
        print(doc)
        return 0
    if a.check:
        cur = _rd(OUT)
        strip = lambda t: re.sub(r"^> \*\*Generated by.*$", "", t, flags=re.M)
        if strip(cur) != strip(doc):
            print("🟠 REFERENCE.md is stale — run scripts/reference_docs.py")
            return 1
        print("✅ REFERENCE.md matches the source")
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"✅ wrote {os.path.relpath(OUT, REPO)} ({len(doc.splitlines())} lines, "
          f"{len(gaps)} undocumented)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
