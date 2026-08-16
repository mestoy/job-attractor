#!/usr/bin/env python3
"""product_docs.py — generate the product document from the system's own artifacts.

WHY THIS EXISTS, and the thesis is borrowed from FORGE. On the secure release pipeline the move that
mattered was encoding the required checks so every release was inspected and cleared automatically,
with the evidence GENERATED rather than assembled for an audit afterwards. Compliance stopped being
a document somebody wrote and became a property of the pipeline.

Documentation has the same failure mode. A hand-written product doc is a point in time audit: true
on the day it was written, quietly wrong a month later, and nobody can tell which. So this reads the
LIVE repo and writes the document from what is actually there. The counts, the surfaces, the gates
and the open defects are observations, never claims.

⛔ READ-ONLY on everything except its own output. It never edits a source file, and it exits 0 even
when a reader fails, because a doc build that breaks the repo is worse than a doc that is late.

WHAT IT WILL NOT DO, on purpose. It does not invent the PROBLEM, the users, or the experiment. Those
are judgment and they live in `documents/product/canvas.md`, which a human owns and this script only
embeds. A generator that writes its own product strategy is a generator that launders a guess.

Usage:
    scripts/product_docs.py                # write documents/product/PRODUCT.md
    scripts/product_docs.py --stdout       # print it instead
    scripts/product_docs.py --check        # exit 1 if the written doc is stale vs live state
Exit: 0 normally · 1 only for --check when stale
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
OUT = os.path.join(REPO, "documents", "product", "PRODUCT.md")
CANVAS = os.path.join(REPO, "documents", "product", "canvas.md")


def _rd(rel):
    try:
        with open(os.path.join(REPO, rel), encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def _sh(args):
    try:
        return subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return ""


# ── OBSERVATIONS ──────────────────────────────────────────────────────────────────────────────
# Every number below is counted from the tree at build time. None is typed. If a count looks wrong
# the fix is in the thing being counted, which is the property that makes this doc trustworthy.

def surfaces():
    return {
        "scripts": len(glob.glob(os.path.join(REPO, "scripts", "*.py")))
                   + len(glob.glob(os.path.join(REPO, "scripts", "*.sh"))),
        "commands": len(glob.glob(os.path.join(REPO, ".claude", "commands", "*.md"))),
        "skills": len([d for d in glob.glob(os.path.join(REPO, ".claude", "skills", "*")) if os.path.isdir(d)]),
        "gate docs": len(glob.glob(os.path.join(REPO, "documents", "*checklist*.md")))
                     + (1 if os.path.exists(os.path.join(REPO, "documents", "HARD-INVARIANTS.md")) else 0),
    }


def hooks():
    """Wired hooks by event. The enforcement layer, read from the live settings."""
    out = {}
    try:
        cfg = json.loads(_rd(".claude/settings.json") or "{}")
        for ev, groups in (cfg.get("hooks") or {}).items():
            names = set()
            for g in groups or []:
                for h in (g.get("hooks") or []):
                    for m in re.finditer(r"scripts/([A-Za-z0-9_.-]+)", str(h.get("command") or "")):
                        names.add(m.group(1))
            if names:
                out[ev] = sorted(names)
    except Exception:
        pass
    return out


def ladder():
    """The outcome measure. Imported rather than re-parsed, because a second counter is a second
    answer and this repo has paid for that three times."""
    # ⚠️ `tally()` returns a TUPLE (agg, dropped), not a dict. An earlier version here treated it as
    # a dict behind an isinstance guard, so it silently reported 0 sends as the document's headline
    # number. A guard that turns a wrong shape into a plausible zero is worse than a crash, because
    # a zero looks like an answer.
    try:
        sys.path.insert(0, HERE)
        import rung_ladder
        agg, _dropped = rung_ladder.tally(
            rung_ladder.load(os.path.join(REPO, "documents", "send-log.jsonl")))
        # Each value is a [sent, replied] PAIR, read from the real store rather than assumed.
        sent = sum(r[0] for r in agg.values())
        rep = sum(r[1] for r in agg.values())
        return (sent, rep) if sent else (None, None)
    except Exception:
        return None, None


def bugs():
    src = _rd("documents/BUG-LOG.md")
    body = src.split("## OPEN", 1)[-1].split("## FIXED", 1)[0]
    rows = re.findall(r"^- \[ \]\s+\*\*(BUG-\d+)\*\*\s*(\S*)\s*\*\*(.+?)\*\*", body, re.M | re.S)
    return [(i, sev, re.sub(r"\s+", " ", t).strip().rstrip(".")) for i, sev, t in rows]


def recent_changes(n=8):
    log = _sh(["git", "log", f"-{n}", "--pretty=%h|%ad|%s", "--date=short"])
    return [l.split("|", 2) for l in log.splitlines() if l.count("|") >= 2]


# ── DIAGRAMS ──────────────────────────────────────────────────────────────────────────────────
# Mermaid, because a diagram that is an image is a diagram that goes stale in a drawer. These are
# text, they live in git, and they diff.

def diagram_dataflow():
    return """```mermaid
flowchart LR
  subgraph Sources
    EX[LinkedIn export]
    BOARDS[Job boards and ATS]
    WEB[Public company sources]
  end
  subgraph Stores
    NET[(warm-network)]
    CLOSE[(closeness store)]
    BANK[(banked pool)]
    BLOCK[(blocked list)]
    SEND[(send log)]
  end
  subgraph Engine
    SCREEN[screen and culture gates]
    RANK[ranker]
    BRIEF[session brief and PAIR]
    DRAFT[co-construction]
  end
  EX --> NET --> RANK
  EX --> CLOSE --> RANK
  BOARDS --> SCREEN --> BANK --> RANK
  WEB --> SCREEN
  SCREEN --> BLOCK -.vetoes.-> RANK
  RANK --> BRIEF --> DRAFT
  DRAFT -->|human sends| SEND
  SEND -->|reply rates| BRIEF
  SEND -.already contacted.-> RANK
```"""


def diagram_valuestream():
    return """```mermaid
flowchart LR
  A[Discover] --> B[Screen]
  B --> C[Verify seat live]
  C --> D[Rank]
  D --> E[Pick target]
  E --> F[Co-construct message]
  F --> G[Human sends]
  G --> H[Reply]
  H --> I[Conversation]
  B -. most drop here .-> X[(Dropped)]
  C -. stale seat .-> X
  classDef slow fill:#fde,stroke:#b56
  class B,C slow
```

**Where the time goes.** Discovery and screening consume most of it, and the only step that produces
value is the send. Everything upstream is inventory."""


def diagram_blueprint():
    return """```mermaid
flowchart TB
  subgraph Front stage, what the human does
    H1[Reads the brief]
    H2[Picks a target]
    H3[Picks each beat]
    H4[Sends it]
    H5[Reads the reply]
  end
  subgraph Back stage, what the assistant does
    A1[Recompute ladder]
    A2[Screen and rank]
    A3[Pull voice corpus]
    A4[Lint the draft]
    A5[Log the send]
  end
  subgraph Support, what the gates do
    G1[HARD-INVARIANTS re-read]
    G2[check_dup and blocked list]
    G3[check_outreach and check_style]
    G4[check_preview BUILD gate]
    G5[check_pair]
  end
  H1 --> A1 --> G5
  H2 --> A2 --> G2
  H3 --> A3 --> G1
  H4 --> A4 --> G3
  H4 --> G4
  H5 --> A5
```

⛔ **The line that matters is the one between front stage and back stage.** The human sends. Nothing
in the back stage may cross it."""


def diagram_usecases():
    return """```mermaid
flowchart LR
  U((Job seeker))
  P((Partner))
  U --- UC1[Find companies that fit]
  U --- UC2[Find the likely boss]
  U --- UC3[Write in my own voice]
  U --- UC4[Know what to do next]
  U --- UC5[See whether it is working]
  U --- UC6[Prepare for the interview]
  P --- UC7[Run the same pipeline on my own data]
  P --- UC8[Report a defect upstream]
```"""


def diagram_rungs():
    return """```mermaid
flowchart TB
  R12[1-2 cold stranger<br/>ask: connect] --> R34[3-4 cold boss<br/>ask: work for you]
  R34 --> R57[5-7 warm 1st degree<br/>ask: who do you know]
  R57 --> R89[8-9 referred<br/>ask: they sent me]
  R89 --> R10[10 event follow up]
  classDef best fill:#dfd,stroke:#5a5
  classDef worst fill:#fdd,stroke:#a55
  class R57,R89 best
  class R34 worst
```

**Rung sets two things at once:** how deep the screen goes and what shape the message takes. It is
the biggest single lever measured so far."""


# ── RENDER ────────────────────────────────────────────────────────────────────────────────────

def render():
    s = surfaces()
    hk = hooks()
    sent, rep = ladder()
    bg = bugs()
    canvas = _rd("documents/product/canvas.md").strip()
    today = str(date.today())

    L = []
    a = L.append
    a("# The Job Attractor")
    a("")
    a(f"> **Generated by `scripts/product_docs.py` on {today}.** Every count below is read from the "
      f"live repo at build time, never typed. If a number here is wrong, the thing it counts is "
      f"wrong. Do not hand edit this file, edit what it measures.")
    a("")
    a("---")
    a("")
    a("## What this is")
    a("")
    a("A job search that runs as a pipeline instead of a slot machine. It finds companies that fit a "
      "stated set of criteria, finds the person who would be the boss, screens both against rules "
      "the owner wrote down, and helps write one message at a time in the owner's own voice. "
      "**A human sends every message.** Nothing here has a send button.")
    a("")

    if canvas:
        a("## Product canvas")
        a("")
        a(canvas)
        a("")
    else:
        a("## Product canvas")
        a("")
        a(f"⚠️ `documents/product/canvas.md` is missing, so the canvas is not embedded. That file is "
          f"owned by a human on purpose: the problem, the users and the next experiment are judgment "
          f"and a generator that wrote them would be laundering a guess.")
        a("")

    a("## The system, as built")
    a("")
    a("| Surface | Count |")
    a("|---|---|")
    for k, v in s.items():
        a(f"| {k} | {v} |")
    a("")

    if sent is not None:
        rate = f"{(rep / sent * 100):.1f}%" if sent else "n/a"
        a(f"**Outcome measure.** {sent} messages sent, {rep} replied, {rate}. Read from the send log "
          f"through the same counter the daily brief uses, because a second counter is a second "
          f"answer.")
        a("")

    a("### Data flow")
    a("")
    a(diagram_dataflow())
    a("")
    a("### Value stream")
    a("")
    a(diagram_valuestream())
    a("")
    a("### Service blueprint")
    a("")
    a(diagram_blueprint())
    a("")
    a("### Use cases")
    a("")
    a(diagram_usecases())
    a("")
    a("### The relationship ladder")
    a("")
    a(diagram_rungs())
    a("")

    a("## Enforcement, the part that makes it a system")
    a("")
    a("A rule that lives only in prose is not a rule. Every gate below is a script the harness runs, "
      "so the rule fires whether or not anyone remembers it.")
    a("")
    if hk:
        a("| Event | Scripts |")
        a("|---|---|")
        for ev, names in sorted(hk.items()):
            a(f"| `{ev}` | {', '.join('`' + n + '`' for n in names)} |")
    else:
        a("⚠️ No wired hooks found in `.claude/settings.json`. If that is unexpected, the gates are "
          "not firing and nothing else on screen will say so.")
    a("")

    a("## Known defects")
    a("")
    a("Open defects are published rather than hidden, because a system that never contradicts itself "
      "is a system that is not measuring anything.")
    a("")
    if bg:
        a("| ID | Severity | What |")
        a("|---|---|---|")
        for i, sev, t in bg[:12]:
            a(f"| {i} | {sev or ''} | {t[:110]} |")
        if len(bg) > 12:
            a("")
            a(f"…and {len(bg) - 12} more in `documents/BUG-LOG.md`.")
    else:
        a("None open.")
    a("")

    a("## Recent changes")
    a("")
    ch = recent_changes()
    if ch:
        a("| Commit | Date | Summary |")
        a("|---|---|---|")
        for h, d, msg in ch:
            a(f"| `{h}` | {d} | {msg[:90]} |")
    a("")
    a("---")
    a("")
    a("*Regenerate with `python3 scripts/product_docs.py`. Check for staleness in CI or a hook with "
      "`--check`.*")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the written doc differs from live state")
    a = ap.parse_args()
    doc = render()
    if a.stdout:
        print(doc)
        return 0
    if a.check:
        cur = _rd(os.path.relpath(OUT, REPO))
        # The generated-on line changes daily and is not drift, so compare everything else.
        strip = lambda t: re.sub(r"^> \*\*Generated by.*$", "", t, flags=re.M)
        if strip(cur) != strip(doc):
            print("🟠 PRODUCT.md is stale against live state — run scripts/product_docs.py")
            return 1
        print("✅ PRODUCT.md matches live state")
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"✅ wrote {os.path.relpath(OUT, REPO)} ({len(doc.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
