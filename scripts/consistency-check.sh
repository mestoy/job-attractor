#!/usr/bin/env bash
# consistency-check.sh — ONE consolidated durable-storage + workflow preflight.
# Runs the mechanizable cross-store consistency + completeness checks in one place, prints a
# ✅/⚠️/🔴 report, and exits non-zero if any 🔴 (hard drift) is found. ⚠️ = advisory.
# Run at end-of-block and daily (launchd). Wired as a Stop hook so it fires automatically.
#
# Checks: correspondence-sync · memory-index integrity · check_dup store coverage · queue health
#         · blocked-list sync · résumé tex↔export mapping + verify_resume --all · tmp-orphan · index size.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
REPO="$(pwd)"
# Memory dir: set JOBSEARCH_MEMORY_DIR to wherever your assistant keeps its memory store.
# The default derives it from this project's path; the checks below degrade to a skip when the
# directory isn't there, so this runs fine on any machine.
_MEMSLUG="$(printf '%s' "$REPO" | tr '/' '-')"
MEM="${JOBSEARCH_MEMORY_DIR:-$HOME/.claude/projects/$_MEMSLUG/memory}"

python3 - "$REPO" "$MEM" <<'PY'
import sys, os, re, glob
REPO, MEM = sys.argv[1], sys.argv[2]
FAIL = 0        # 🔴 count (drives exit code)
def p(mark, label, detail=""):
    print(f"   {mark} {label}" + (f": {detail}" if detail else ""))
def norm(s):
    s = s.lower()
    s = re.sub(r"\.(com|dev|io|ai|co|org|net|app|tech|xyz|so|sh)\b", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s
def read(path):
    f = os.path.join(REPO, path)
    return open(f, encoding="utf-8", errors="ignore").read() if os.path.exists(f) else ""

print("── consistency-check ──")

# 1. CORRESPONDENCE-SYNC: every genuine SENT in outreach_log has an OUTBOUND block in correspondence-log
print("\n[1] correspondence-sync")
ol = read("outreach_log.md"); cl = read("correspondence-log.md") or read("documents/correspondence-log.md")
sent = {}
for line in ol.splitlines():
    if line.startswith("## ") and re.search(r"\bSENT\b", line) and not re.search(r"bounce|INBOUND|UNLOGGED", line, re.I):
        m = re.search(r"·\s*([^·(]+?)\s*(?:\(|·)", line)
        if m: sent[norm(m.group(1))] = m.group(1).strip()
corr = norm(cl)
missing = [orig for k, orig in sent.items() if k and k not in corr]
if not sent:
    p("⚠️", "no SENT entries parsed", "check header format")
elif missing:
    p("⚠️", f"{len(missing)} SENT co(s) with no verbatim in correspondence-log", ", ".join(sorted(set(missing))[:12]))
else:
    p("✅", f"all {len(sent)} SENT cos have a verbatim block")

# 2. MEMORY-INDEX INTEGRITY: bare-filename pointers ↔ memory/*.md (orphans + dangling)
print("\n[2] memory-index integrity")
_mi = os.path.join(MEM, "MEMORY.md")
if not os.path.exists(_mi):
    p("⚠️", "memory dir/index not found — skipping (set JOBSEARCH_MEMORY_DIR)", MEM)
else:
    idx = open(_mi, encoding="utf-8", errors="ignore").read()
    links = set(re.findall(r"\]\(([A-Za-z0-9._-]+\.md)\)", idx))  # bare filenames only (skip ../ external)
    files = {os.path.basename(f) for f in glob.glob(os.path.join(MEM, "*.md")) if os.path.basename(f) != "MEMORY.md"}
    orphans = sorted(files - links)      # file exists, no pointer
    dangling = sorted(links - files)     # pointer, no file
    if orphans:
        FAIL += 1; p("🔴", f"{len(orphans)} memory file(s) NOT indexed", ", ".join(orphans[:8]))
    if dangling:
        FAIL += 1; p("🔴", f"{len(dangling)} dangling pointer(s)", ", ".join(dangling[:8]))
    if not orphans and not dangling:
        p("✅", f"{len(files)} memory files all indexed, no dangling pointers")

# 3. CHECK_DUP STORE COVERAGE: non-glob STORES exist; durable stores not covered = advisory
print("\n[3] check_dup store coverage")
cd = read("scripts/check_dup.py")
store_paths = re.findall(r'"([^"]+?)":\s*"', cd.split("STORES = {")[1].split("}")[0]) if "STORES = {" in cd else []
dangling_store = [s for s in store_paths if "*" not in s and not os.path.exists(os.path.join(REPO, s))]
if dangling_store:
    FAIL += 1; p("🔴", "STORES lists missing file(s)", ", ".join(dangling_store))
# durable stores that look trackable but aren't covered
covered = " ".join(store_paths)
candidates = ["outreach_log.md","job_search_tracker.csv","prospect_queue.md"] + \
             [os.path.relpath(f, REPO) for f in glob.glob(os.path.join(REPO,"documents","*.md"))]
def is_covered(path):
    base = os.path.basename(path)
    return base in covered or path in covered
# stores that hold RULES/CHANGELOG/process notes, not company records → not dedup stores
IGNORE_COV = ("changelog","self-learning","workflow","invariant","checklist","style-guide","teachings","audit","prep","spec","playbook","negotiation","question-bank","metrics")
tracky = [c for c in candidates if re.search(r"(queue|log|tracker|blocked|correspondence|decision|discovery|learning|handoff|shared-notes|baseline)", c, re.I)
          and not any(k in c.lower() for k in IGNORE_COV)]
uncov = sorted(set(c for c in tracky if not is_covered(c)))
if uncov:
    p("⚠️", f"{len(uncov)} durable store(s) not in STORES (verify not a dedup blind spot)", ", ".join(uncov[:8]))
if not dangling_store and not uncov:
    p("✅", f"{len(store_paths)} STORES entries all resolve; no obvious blind spots")

# 4. QUEUE HEALTH: count STATUS: NEW; flag stale SENT/DROP in the LIVE queue
print("\n[4] queue health")
oq = read("documents/outreach-queue.md"); pq = read("prospect_queue.md")
new_ct = len(re.findall(r"STATUS:\s*NEW", oq, re.I)) + len(re.findall(r"\bNEW\b", pq))
stale = len(re.findall(r"STATUS:\s*(SENT|DROP|BLOCKED|DUPLICATE)", oq, re.I))
p("✅" if new_ct else "⚠️", f"~{new_ct} reviewable NEW items in live queues", "(target ~50)" if new_ct < 50 else "")
if stale:
    p("⚠️", f"{stale} SENT/DROP/BLOCKED item(s) still in the LIVE outreach-queue", "should be archived")

# 5. BLOCKED-LIST SYNC: '+ BLOCKED' cos in outreach_log present on the canonical list
print("\n[5] blocked-list sync")
bl = norm(read("documents/blocked-employers-list.md"))
blocked = set()
for line in ol.splitlines():
    if re.search(r"\+\s*BLOCKED|Added to.*blocked", line) and not re.search(r"REINSTATED", line, re.I):
        m = re.search(r"·\s*([^·(]+?)\s*(?:\(|·)", line)
        if m: blocked.add(m.group(1).strip())
# drop any co that appears anywhere with REINSTATED (blocked-then-reinstated same entity)
reinstated = norm("".join(l for l in ol.splitlines() if re.search(r"REINSTATED", l, re.I)))
miss_bl = [b for b in blocked if norm(b) and norm(b) not in bl and norm(b) not in reinstated]
if miss_bl:
    p("⚠️", f"{len(miss_bl)} '+BLOCKED' co(s) maybe not on canonical list (verify not reinstated)", ", ".join(sorted(set(miss_bl))[:8]))
else:
    p("✅", "no un-reinstated blocked cos missing from the list")

# 6. RÉSUMÉ tex↔export mapping
print("\n[6] résumé tex↔export mapping")
texs = {re.sub(r"^main_", "", os.path.basename(f)[:-4]) for f in glob.glob(os.path.join(REPO,"cv","main_*.tex")) if os.path.basename(f)!="main_example.tex"}
exports = glob.glob(os.path.join(REPO,"documents","cv","*.pdf"))
export_norm = " ".join(norm(os.path.basename(e)) for e in exports)
tex_no_export = sorted(c for c in texs if norm(c) not in export_norm)
if tex_no_export:
    p("⚠️", f"{len(tex_no_export)} tex source(s) with no export", ", ".join(tex_no_export[:8]))
else:
    p("✅", f"all {len(texs)} tex sources have an export")

# 7. TMP ORPHANS
print("\n[7] tmp-orphan scan")
tmps = [os.path.relpath(f, REPO) for f in glob.glob(os.path.join(REPO,"**","*.tmp"), recursive=True)]
if tmps:
    p("⚠️", f"{len(tmps)} stray .tmp file(s)", ", ".join(tmps[:5]))
else:
    p("✅", "no stray .tmp files")

# 8. MEMORY INDEX SIZE — BOTH caps, measured the way the harness measures
# Claude Code loads the first 200 LINES **or** 25KB of MEMORY.md, whichever comes first, and
# everything past that is silently dropped on the NEXT session load. Measuring bytes alone lets a
# file of many short lines blow the 200-line cap while reporting ✅.
# FAIL fires at 85%, not 100%, because overflow is discovered after the loss, never before it.
# Frontmatter and block-level HTML comments are stripped before the index is loaded (CC 2.1.211+),
# so they are stripped here too — measuring the raw file would raise false alarms.
print("\n[8] MEMORY.md size")
MEM_MAX_LINES, MEM_MAX_BYTES = 200, 25 * 1024
mi = os.path.join(MEM, "MEMORY.md")
if not os.path.exists(mi):
    p("⚠️", "MEMORY.md not found — skipping", MEM)
else:
    _raw = open(mi, encoding="utf-8", errors="ignore").read()
    _m = re.match(r"\A---\n.*?\n---\n", _raw, re.S)          # YAML frontmatter: not loaded
    _loaded = _raw[_m.end():] if _m else _raw
    _loaded = re.sub(r"(?m)^[ \t]*<!--.*?-->[ \t]*\n?", "", _loaded, flags=re.S)  # block comments
    _lines = _loaded.splitlines()
    pl, pb = len(_lines) / MEM_MAX_LINES, len(_loaded.encode()) / MEM_MAX_BYTES
    worst = max(pl, pb)
    binder = "lines" if pl >= pb else "bytes"
    stat = (f"{len(_loaded.encode()):,}B/{MEM_MAX_BYTES:,} ({pb:.0%}) · "
            f"{len(_lines)}/{MEM_MAX_LINES} lines ({pl:.0%}) · binds on {binder}")
    if worst >= 0.85:
        FAIL += 1
        p("🔴", f"MEMORY.md at {worst:.0%} of its read limit — COMPACT NOW", stat)
    elif worst >= 0.65:
        p("⚠️", f"MEMORY.md at {worst:.0%} of its read limit — compact soon", stat)
    else:
        p("✅", f"MEMORY.md {worst:.0%} of read limit", stat)
    if worst >= 0.65:
        # Make the fix obvious instead of a chore: name the biggest lines and the growth signal.
        _long = sorted(((len(l), i + 1, l) for i, l in enumerate(_lines)), reverse=True)[:3]
        for n, i, l in _long:
            p("  ", f"longest line {i}: {n}B", l.strip()[:70])
        _nfiles = len([f for f in glob.glob(os.path.join(MEM, "*.md"))
                       if os.path.basename(f) != "MEMORY.md"])
        _entries = len([l for l in _lines if l.startswith("- ")])
        if _entries:
            p("  ", f"{_nfiles} files across {_entries} entry lines "
                    f"({_nfiles/_entries:.1f} files per line)",
                    "group more files per line; the index is a router, not a store")

print(f"\n── {'🔴 ' + str(FAIL) + ' hard issue(s)' if FAIL else '✅ no hard drift'} (⚠️ = advisory) ──")
sys.exit(1 if FAIL else 0)
PY
CODE=$?

# NOTE (2026-07-19): steps [9] and [10] used to run AFTER `CODE=$?` and pipe into `sed`,
# which swallowed their exit codes — verify_resume.py had NO path to failing anything,
# anywhere (mail-draft.sh never called it either). Use PIPESTATUS so their exits count.
echo
echo "[9] follow-up cadence (check_followups.py)"
python3 scripts/check_followups.py 2>/dev/null | sed 's/^/   /'
FOLLOWUP_CODE=${PIPESTATUS[0]}

echo
echo "[10] résumé QA (verify_resume.py --all)"
python3 scripts/verify_resume.py --all 2>/dev/null | sed 's/^/   /'
RESUME_CODE=${PIPESTATUS[0]}

echo
echo "[11] screen-gate evidence on the green board (check_screen_gate.py)"
# Closes register gap G6 ("good gates don't self-trigger"). check_screen_gate.py was DEAD CODE:
# its only non-doc appearance was a filename inside backup.sh's copy loop. It has always worked;
# nothing ever called it. Run it over the board so unscreened rows surface every Stop + daily.
# PER-ROW, not whole-file. Passing the entire board as one blob is VACUOUS: a cue ANYWHERE in
# the file satisfies a layer for EVERY row, so it reports 🟢 while each row individually fails
# five to seven layers. The sharpest case: the politics layer was satisfied by the warning text
# saying politics evidence was MISSING (that line contains "politic"). Documenting the gap
# closed the gap. Screen each row on its own.
BOARD=""
for _b in documents/green-board.md documents/outreach-queue.md; do
  [ -f "$_b" ] && { BOARD="$_b"; break; }
done
if [ -f scripts/check_screen_gate.py ] && [ -n "$BOARD" ]; then
  BOARD="$BOARD" python3 - <<'PYROW' | sed 's/^/   /'
import os, re, subprocess, sys
BOARD = os.environ["BOARD"]
rows = [l for l in open(BOARD, encoding="utf-8")
        if l.strip().startswith("|") and l.count("|") >= 8
        and not re.match(r"^\s*\|\s*[-: ]+\|", l)
        and not re.search(r"\|\s*#\s*\|", l)]
bad = []
for l in rows:
    # The review board holds TWO tables with DIFFERENT shapes: the numbered board
    # (| # | Company | Lane | Remote | Culture | Non-PE | Boss | Praise | Status |, 9 cols) and a
    # radar table below it with NO '#' column (8 cols), whose cells therefore sit one to the LEFT.
    # Hardcoding index 2 read a radar row's LANE as its company name and broke the ~~dropped~~ skip
    # (which reads the company cell). Detect per row: a numbered row has a digit in cells[1].
    # Fixed in the main kit 2026-07-21; mirrored here — a partner kit that keeps the defect is a
    # defect that ships to someone else.
    cells = [c.strip() for c in l.split("|")]
    off = 1 if len(cells) > 1 and cells[1].strip().isdigit() else 0
    co = cells[1 + off] if len(cells) > 1 + off else "?"
    # The radar table's own header row starts '| Company | Lane |' and carries no '#', so the
    # numbered-header filter above misses it.
    if not co or co.startswith("~~") or co.lower() == "company":
        continue
    r = subprocess.run([sys.executable, "scripts/check_screen_gate.py", "-"],
                       input=l, capture_output=True, text=True)
    if r.returncode != 0:
        gaps = re.findall(r"❌ ([^\n]+)", r.stdout)
        bad.append((co, gaps))
print(f"{len(rows)} board row(s) screened individually; {len(bad)} incomplete")
for co, gaps in bad[:12]:
    print(f"  ⚠️ {co}: missing {', '.join(g.strip() for g in gaps) if gaps else 'evidence'}")
sys.exit(1 if bad else 0)
PYROW
  SCREEN_CODE=${PIPESTATUS[0]}
  [ "$SCREEN_CODE" -ne 0 ] && echo "   ⚠️  advisory — close these before any build (a board row is NOT build-approval)"
else
  echo "   ⚠️  check_screen_gate.py or a review board (green-board.md / outreach-queue.md) missing"
fi

echo
echo "[14] two-tier target board (green-board.md)"
# TWO TIERS. The method says: "Make a list of 10 companies. Yes, make it 10, no less, no more." That
# cap assumes COLD boss-hunting, where you work one company at a time and depth beats breadth. It
# breaks under WARM outreach: the warm-ask template names THREE companies per ask, and the send gate
# blocks a company after a SINGLE prior naming, so six warm sends in one day exhausted a 9-company
# board and a seventh contact had no clean trio left.
#
# The resolution keeps the focus discipline and feeds the warm lane: the NUMBERED table stays capped
# at 10 = the ACTIVE boss-hunt list, worked deeply. The RADAR table below it is the BANKED POOL,
# stocked toward 40, which supplies named targets for warm asks. 10 + 40 = the 50 the method asks
# for. A deliberate divergence, recorded so nobody "fixes" it back to a flat 10.
python3 - <<'PY314'
import re, os
p = "documents/green-board.md"
if not os.path.exists(p):
    print("   ⚠️  green-board.md not found")
else:
    txt = open(p, encoding="utf-8").read()
    rows = [l for l in txt.splitlines()
            if l.strip().startswith("|") and l.count("|") >= 8
            and not re.match(r"^\s*\|\s*[-: ]+\|", l)
            and not re.search(r"\|\s*#\s*\|", l)]
    # SENT MUST BE READ FROM THE STATUS COLUMN, NOT THE WHOLE ROW. This was `"SENT" not in l.upper()`
    # — a substring test across the entire row — so any company whose NAME contains those four
    # letters read as already-sent and vanished: Sentry, Assent, Consent, Absentia. They dropped out
    # of the cap count, out of "tomorrow's three", and out of screening, silently. Same class as the
    # short-name false positives check_dup already had to fix: a status token that is also a
    # substring of a real name.
    def _live(l):
        if "~~" in l:
            return False
        cells = [c.strip() for c in l.split("|")]
        status = cells[-2] if len(cells) >= 2 and not cells[-1] else (cells[-1] if cells else "")
        return not re.search(r"\bSENT\b", status, re.I)
    live = [l for l in rows if _live(l)]
    # Split the two tiers: a numbered row is ACTIVE, an unnumbered radar row is BANKED.
    def _numbered(l):
        cells = [c.strip() for c in l.split("|")]
        return len(cells) > 1 and cells[1].strip().isdigit()
    active = [l for l in live if _numbered(l)]
    banked = [l for l in live if not _numbered(l)
              and [c.strip() for c in l.split("|")][1].lower() not in ("company", "#", "")]
    n = len(active)
    if n > 10:
        print(f"   \U0001f534 ACTIVE list has {n} rows, cap is 10 (\"no less, no more\") — close out {n-10}")
    else:
        print(f"   ✅ ACTIVE list {n}/10 (boss-hunt tier)")
    b = len(banked)
    if b < 40:
        print(f"   ⚠️  BANKED pool {b}/40 — warm asks name 3 companies each and a company "
              f"burns after ONE naming, so this tier is the warm lane's fuel")
    else:
        print(f"   ✅ BANKED pool {b}/40 (warm-ask supply)")
    # Only flag a LIVE 50-target. A historical note explaining the retirement is not drift, and a
    # check that fires on its own changelog is one people learn to ignore.
    live50 = [l for l in txt.splitlines()
              if re.search(r"bench.{0,12}=?\s*50|50 green|50 build-ready", l, re.I)
              and not re.search(r"retired|was a|restructured|no longer|reached 10 ever", l, re.I)]
    if live50:
        print("   ⚠️  a LIVE 50-bench target remains: " + live50[0].strip()[:70])
PY314

echo
echo "[12] BUILD-GATE ledger (decision-ledger.jsonl)"
# The tamper-resistant record of YOUR ACTUAL rulings, written by the PostToolUse hook
# (scripts/record_decision.py). check_preview.py consults it to block praise-beat options that
# were never authorized by a scorecard ruling. See HARD-INVARIANTS "BUILD GATE".
if [ -f documents/decision-ledger.jsonl ]; then
  _n=$(wc -l < documents/decision-ledger.jsonl | tr -d ' ')
  _b=$(grep -c '"ruling": "BUILD"' documents/decision-ledger.jsonl 2>/dev/null || echo 0)
  echo "   ✅ ledger present: $_n decision(s) recorded, $_b BUILD ruling(s)"
else
  echo "   ⚠️  no decision-ledger.jsonl yet (written on your first recorded AskUserQuestion answer)"
fi

echo
echo "[13] 3-3-3 daily loop (send-log.jsonl)"
# NOTHING counts sends per day unless something does. A cadence rule adopted with no mechanical
# representation goes the way of every volume target before it: quietly ignored. A number that judges you is the first thing to get rationalized away, so
# it has to be counted by a script, not remembered.
python3 - <<'PY313'
import json, os, datetime, collections
p = "documents/send-log.jsonl"
today = datetime.date.today().isoformat()
if not os.path.exists(p):
    print("   \u26a0\ufe0f  no send-log.jsonl yet (written by mail-draft.sh on each send)")
else:
    rows = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            try: rows.append(json.loads(line))
            except Exception: pass
    # A BOUNCE IS NOT A SEND. Counting every send-log row for the day whatever its status means a
    # hard bounce and a staged-but-unsent draft both score as outreach. A run then reads
    # "3/3 loop closed" when only two messages reached a human and the third reached nobody.
    # A bounce is not a completed send and does not count toward the 3-3-3.
    #
    # This is the same failure as the phantom follow-up: a number that judges you, inflated by
    # non-events, telling you that you are done when you are not. Excluded statuses are named
    # explicitly so an unfamiliar future status counts (over-counting is visible; silently
    # dropping a real send is not).
    NOT_DELIVERED = {"bounced", "drafted", "staged", "failed", "blocked"}
    _today_rows = [r for r in rows if r.get("date") == today]
    n = sum(1 for r in _today_rows if str(r.get("status", "")).lower() not in NOT_DELIVERED)
    _skipped = len(_today_rows) - n
    mark = "\u2705" if n >= 3 else "\u2b05"
    print(f"   {mark} sent today: {n}/3" +
          (f"   (+{_skipped} not delivered, not counted)" if _skipped else ""))
    wk = [r for r in rows if r.get("date","") >= (datetime.date.today()-datetime.timedelta(days=7)).isoformat()]
    if wk:
        by = collections.Counter(r.get("rung","?") for r in wk)
        cold = sum(v for k,v in by.items() if k.startswith("cold"))
        warm = sum(v for k,v in by.items() if k in ("warm","referred","event"))
        tot = cold + warm
        if tot:
            pct = round(100*warm/tot)
            flag = "" if pct >= 30 else "   \u26a0\ufe0f THE GRID wants ~50% networking"
            print(f"   last 7d by rung: " + ", ".join(f"{k}={v}" for k,v in by.most_common()))
            print(f"   networking share: {pct}%{flag}")
PY313

echo
echo "[15] segment spread / hot-zone (send-log.jsonl)"
# Andy's not-crystal-clear formula: send ACROSS segments ("5/segment vs. 20/one"), then "evaluate
# response rate for hot-zone — your focus is on data, not interviews!!" It is possible to run a hundred sends and
# not be able to name one segment's response rate, because nothing recorded a segment. mail-draft.sh now
# requires --segment on cold rungs; this reports the spread so 20-into-one is visible.
python3 - <<'PY315'
import json, os, datetime, collections
p = "documents/send-log.jsonl"
if not os.path.exists(p) or os.path.getsize(p) == 0:
    print("   ⚠️  no segment data yet (written by mail-draft.sh --segment on each cold send)")
else:
    cutoff = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
    rows = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("date", "") >= cutoff and (r.get("segment") or "").strip():
            rows.append(r)
    if not rows:
        print("   ⚠️  no segmented sends in the last 14d")
    else:
        by = collections.Counter(r["segment"] for r in rows)
        tot = sum(by.values())
        top, n = by.most_common(1)[0]
        print(f"   last 14d across {len(by)} segment(s): " + ", ".join(f"{k}={v}" for k, v in by.most_common()))
        if len(by) < 2:
            print(f"   ⚠️  all {tot} send(s) in ONE segment — Andy tests ACROSS segments (5/segment, not 20/one)")
        elif n / tot > 0.70:
            print(f"   ⚠️  {round(100*n/tot)}% concentrated in '{top}' — spread before concluding it is the hot-zone")

    # HOT-ZONE: response rate per segment, all-time. Spread alone was never the point — Andy's line is
    # "evaluate response rate for hot-zone, your focus is on data, not interviews." Needs the whole
    # history, not 14d, because a 14d window can't hold 5 sends/segment AND their replies.
    allrows = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if (r.get("segment") or "").strip():
            allrows.append(r)
    if allrows:
        agg = {}
        for r in allrows:
            s = r["segment"]
            a = agg.setdefault(s, [0, 0])
            a[0] += 1
            if r.get("replied"):
                a[1] += 1
        print("   hot-zone (all-time, replies are verified humans — not bounces or auto-responders):")
        for s, (n_, rep) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
            bar = "🟢" if n_ >= 5 and rep else ("🔴" if n_ >= 10 and not rep else "⚪")
            rate = f"{round(100*rep/n_)}%" if n_ else "—"
            thin = "  ⚠️ under 5 sends, not yet a test" if n_ < 5 else ""
            print(f"     {bar} {s:20} {n_:3} sends · {rep} replies · {rate}{thin}")
        cold = [s for s, (n_, rep) in agg.items() if n_ >= 10 and not rep and s != "off-segment"]
        if cold:
            print(f"   ⚠️  {', '.join(cold)}: 10+ sends and zero replies — re-examine the message before adding volume")
PY315

echo
echo "[16] tomorrow's three (the SECOND daily block)"
# "3-3-3 every day before 8:00 AM" is the morning block, counted by [13]. The source names a SECOND
# block later the same day: "Ok. Time to get back to it. Where are my 3 send-outs for tomorrow?"
# Nothing counted it, so the half of the loop that REFILLS the loop was invisible — which is how a
# 10-slot board runs at 3. The mechanizable proxy for "tomorrow's three are prepared" is board stock.
python3 - <<'PY316'
import re, os
p = "documents/green-board.md"
if not os.path.exists(p):
    print("   ⚠️  green-board.md not found")
else:
    rows = [l for l in open(p, encoding="utf-8")
            if l.strip().startswith("|") and l.count("|") >= 8
            and not re.match(r"^\s*\|\s*[-: ]+\|", l)
            and not re.search(r"\|\s*#\s*\|", l)]
    # SENT MUST BE READ FROM THE STATUS COLUMN, NOT THE WHOLE ROW (fixed 2026-07-20, Group H).
    # This was `"SENT" not in l.upper()` — a substring test across the entire row — so any company
    # whose NAME contains those four letters read as already-sent and vanished: Sentry, Assent,
    # Consent, Absentia. They dropped out of the cap count, out of "tomorrow's three", and out of
    # screening, silently. Same class as the "Ramp"/"Sound"/"Vector" false positives check_dup
    # already had to fix: a status token that is also a substring of a real name.
    def _live(l):
        if "~~" in l:
            return False
        cells = [c.strip() for c in l.split("|")]
        status = cells[-2] if len(cells) >= 2 and not cells[-1] else (cells[-1] if cells else "")
        return not re.search(r"\bSENT\b", status, re.I)
    live = [l for l in rows if _live(l)]
    if len(live) >= 3:
        print(f"   ✅ {len(live)} target(s) banked for tomorrow's three")
    else:
        print(f"   \U0001f7e0 only {len(live)} target(s) banked — tomorrow's 3-3-3 cannot be filled from the board")
        print("      the afternoon block IS the refill: \"Where are my 3 send-outs for tomorrow?\"")
PY316

echo

echo
echo "[17] unreconciled agent findings (reconcile_findings.py)"
# WHY THIS STEP EXISTS. "Write agent findings back the same day" is the kind of rule that lives in
# prose and is enforced by nobody, and when it slips the ranker keeps offering companies an agent
# already disqualified, which reads to the user as the pipeline being broken. A rule stated in prose
# and reported by nothing is not enforced; find the code path that would have to consult the rule,
# and make something consult it.
# Reads the .reconciled sidecars only. Non-destructive, and it never writes.
FINDINGS_CODE=0
if [ -f scripts/reconcile_findings.py ]; then
  _fout=$(python3 - <<'PYFIND' 2>/dev/null
import sys, os
sys.path.insert(0, "scripts")
try:
    from reconcile_findings import unreconciled
    rows = unreconciled()
except Exception as e:
    print(f"⚠️  could not read findings ({type(e).__name__})")
    sys.exit(0)
if not rows:
    print("✅ every agent findings run is reconciled into the pool")
    sys.exit(0)
owed = sum(t - d for _r, t, d in rows)
print(f"🔴 {len(rows)} findings run(s) with {owed} verdict(s) never written back:")
for run, total, done in rows[:6]:
    print(f"   • {run}: {total - done} of {total} unreconciled")
if len(rows) > 6:
    print(f"   (+{len(rows) - 6} more)")
print("   fix: python3 scripts/reconcile_findings.py   (--dry-run to preview)")
sys.exit(1)
PYFIND
)
  FINDINGS_CODE=$?
  printf '%s\n' "$_fout" | sed 's/^/   /'
else
  echo "   ⚠️  reconcile_findings.py not present — skipped"
fi

echo
echo "[18] warm-network freshness (check_network_freshness.py)"
# WHY. Connections made after the last export exist in NO file in the repo, and nothing measured
# the lag: consistency-check, durability-check and session_start all had zero references to it. The pipeline is only as fresh as the last
# MANUAL export, so the gap widens silently and the only symptom is a daily "3 people" pick that
# quietly stops including anyone recent. Read-only; it never parses or writes.
NETFRESH_CODE=0
if [ -f scripts/check_network_freshness.py ]; then
  python3 scripts/check_network_freshness.py 2>/dev/null | sed 's/^/   /'
  NETFRESH_CODE=${PIPESTATUS[0]}
else
  echo "   ⚠️  check_network_freshness.py not present — skipped"
fi

echo
echo "[19] armed tripwires (check_tripwires.py)"
# WHY. A tripwire is a DATED, CONDITIONAL re-read of a live thread — your device for a decision you
# want to make later on evidence you do not have yet. In the source pipeline eight of them existed
# across four files and NOTHING read any of them: check_followups.py opens only outreach_log.md and
# matches only `FOLLOWUP-DUE:`, so seven sat in files it never opens and the eighth was prose it
# cannot parse. Two were days from firing. Same shape as the standing rule "a ruling recorded
# somewhere the code does not read is not a ruling", applied to a DATE: the entire value of a
# tripwire is being reminded ON THE DAY, which is precisely the day the thread has gone quiet and
# nothing else prompts a re-read. Read-only; it never writes.
TRIPWIRE_CODE=0
if [ -f scripts/check_tripwires.py ]; then
  python3 scripts/check_tripwires.py 2>/dev/null | sed 's/^/   /'
  TRIPWIRE_CODE=${PIPESTATUS[0]}
else
  echo "   ⚠️  check_tripwires.py not present — skipped"
fi

echo "[20] durable state store vs the markdown (backfill_as_of.py --check)"
# WHY. The standing rule: "whenever a phase writes a contract between two files, it also writes the
# check that reads BOTH sides." The contract here is documents/state/*.jsonl against the markdown
# stores it was built from. While the markdown stays hand-edited the store can fall behind it
# silently — and a store that silently lags its source is the same defect class the store was built
# to end.
#
# ADVISORY ON PURPOSE. Nothing consumes this store yet, so a lag costs nothing today. Promote it to
# hard drift on the day the first reader migrates — that is when a stale store starts producing
# wrong answers rather than unread ones. Same calibration [18] uses for its re-parse case: do not
# spend the operator's attention on a condition that is not yet costing anything.
STATE_CODE=0
if [ -f scripts/backfill_as_of.py ]; then
  python3 scripts/backfill_as_of.py --check 2>/dev/null | sed 's/^/   /'
  STATE_CODE=${PIPESTATUS[0]}
else
  echo "   ⚠️  backfill_as_of.py not present — skipped"
fi
if [ "$STATE_CODE" -ne 0 ]; then
  echo "   ⚪ advisory only until the first reader migrates onto the store (step [20])"
fi

echo "[21] veto lists agree (check_rulings.py)"
# WHY. employer-criteria-matrix.md asserts "Hard vetoes here must match HARD-INVARIANTS.md SCREEN
# GATE exactly" and nothing has ever read both sides. When they diverge it matters, because the
# screen-depth table sends warm and referred rungs to "Deal-breakers ONLY" — so the SHORTER list
# decides what a warm ask is screened against.
#
# ADVISORY, and deliberately so: the fix is a POLICY choice between widening HARD-INVARIANTS and
# narrowing the matrix's claim, and that is yours to make. Promoting it to hard drift would paint
# the sweep red every day until you rule, and a permanently red check is one nobody reads. Promote it
# the day you rule, so it never silently drifts back.
RULINGS_CODE=0
if [ -f scripts/check_rulings.py ]; then
  python3 scripts/check_rulings.py 2>/dev/null | sed 's/^/   /'
  RULINGS_CODE=${PIPESTATUS[0]}
else
  echo "   ⚠️  check_rulings.py not present — skipped"
fi
if [ "$RULINGS_CODE" -ne 0 ]; then
  echo "   ⚪ advisory until you rule on which list is authoritative (step [21])"
fi

echo "[22] revisit conditions (check_revisits.py)"
# WHY. Verdicts that carry a revisit CONDITION rather than a flat rejection are invisible until
# something evaluates them — which makes a conditional block indistinguishable from a permanent one.
# In the source pipeline one company's trigger ("a live remote product seat with a band above the
# floor") was met and nothing noticed.
#
# CLASSIFY-ONLY HERE, deliberately. The evaluating run needs the network, and a sweep that depends on
# third-party ATS uptime is a sweep that goes red for reasons the operator cannot fix — the same
# reasoning [18] uses for its re-parse case. Run `check_revisits.py --live` from the daily block,
# where a slow or failed probe is visible rather than mistaken for drift.
if [ -f scripts/check_revisits.py ]; then
  python3 scripts/check_revisits.py --quiet 2>/dev/null | sed 's/^/   /'
  echo "   ⚪ run 'python3 scripts/check_revisits.py --live' to evaluate against live ATS data"
else
  echo "   ⚠️  check_revisits.py not present — skipped"
fi

echo "[23] the durable pair gate (check_pair wiring + pair_brief)"
# WHY. The ladder+picker pair is owed at sign-in and again whenever work reaches a stopping point.
# It is mechanized, which moves the failure mode: it is no longer "the assistant forgot", it is
# "the wiring quietly went away". A hook script that ships with no hook is dead code that reports
# present, which is the false green this whole file exists to catch.
#
# HARD DRIFT, not advisory. The Stop-hook consumer triggers on this script's EXIT CODE, so an
# advisory here would be emitted and then discarded.
PAIR_CODE=0
if [ -f scripts/check_pair.py ] && [ -f scripts/pair_brief.py ]; then
  _settings=".claude/settings.json"
  [ -f "$_settings" ] || _settings=".claude/settings.example.json"
  if ! grep -q 'check_pair\.py.*--hook-ask' "$_settings" 2>/dev/null; then
    echo "   ⚠️  check_pair --hook-ask is NOT wired as a PreToolUse hook"; PAIR_CODE=1
  fi
  if ! grep -q 'check_pair\.py.*--hook-stop' "$_settings" 2>/dev/null; then
    echo "   ⚠️  check_pair --hook-stop is NOT wired as a Stop hook"; PAIR_CODE=1
  fi
  # The stamp is the mechanical heart; if it cannot be computed, both halves are decorative.
  if ! python3 scripts/pair_brief.py --stamp 2>/dev/null | grep -qE '^LADDER [0-9]{4}-[0-9]{2}-[0-9]{2} · sent [0-9]+ · replied [0-9]+ · rate [0-9.]+% · 3-3-3 [0-9]+/3$'; then
    echo "   ⚠️  pair_brief.py --stamp did not produce a well-formed LADDER stamp"; PAIR_CODE=1
  fi
  [ "$PAIR_CODE" -eq 0 ] && echo "   ✅ both hooks wired and the stamp computes"
else
  echo "   ⚠️  check_pair.py / pair_brief.py not present — skipped"
fi

if [ "$RESUME_CODE" -ne 0 ]; then
  echo "   🔴 résumé QA FAILED (verify_resume.py --all exit $RESUME_CODE)"
  CODE=1
fi
if [ "$PAIR_CODE" -ne 0 ]; then
  echo "   🔴 pair gate DRIFT: the ladder+picker pair is not fully wired (step [23])"
  CODE=1
fi
if [ "$TRIPWIRE_CODE" -ne 0 ]; then
  # Hard drift, not advisory. A tripwire's due date IS the decision point, so a tripwire that fires
  # unnoticed converts a deliberate "re-read this on the 30th" into a thread that simply went cold.
  # Undated tripwires stay advisory inside the script and never reach here: nothing can clear them,
  # and a permanently red check is one nobody reads (same rule as [18]'s re-parse case).
  echo "   🔴 TRIPWIRE date(s) DUE or overdue (check_tripwires.py exit $TRIPWIRE_CODE) (step [19])"
  CODE=1
fi
if [ "$NETFRESH_CODE" -ge 2 ]; then
  # Only exit 2 (the export ITSELF is stale) is hard drift. Exit 1 means a re-parse fixes it, which
  # is a chore, not drift — promoting that would make the check red for a condition the operator
  # cannot clear without a download, and a permanently red check is one nobody reads.
  echo "   🔴 warm-network data is stale and only a fresh LinkedIn export can fix it (step [18])"
  CODE=1
fi
if [ "$FINDINGS_CODE" -ne 0 ]; then
  # Promoted to hard drift, not left advisory. An agent verdict that never reaches the pool is
  # indistinguishable from never having screened at all, and the cost lands on a LATER session
  # that re-screens ground already covered. Same reasoning that promoted [9].
  echo "   🔴 agent findings captured but never reconciled into the pool (step [17])"
  CODE=1
fi
if [ "$FOLLOWUP_CODE" -ne 0 ]; then
  # Was advisory-only. Follow-up is the highest-frequency recurring obligation in the method, and
  # ~53 sends once went invisible for want of an armed date — an obligation that never affects the
  # exit code is one nobody has to answer for. Counts as hard drift now.
  echo "   🔴 follow-ups DUE or sends with no armed date (check_followups.py exit $FOLLOWUP_CODE)"
  CODE=1
fi

exit $CODE
