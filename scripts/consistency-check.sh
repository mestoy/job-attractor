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

if [ "$RESUME_CODE" -ne 0 ]; then
  echo "   🔴 résumé QA FAILED (verify_resume.py --all exit $RESUME_CODE)"
  CODE=1
fi
if [ "$FOLLOWUP_CODE" -ne 0 ]; then
  echo "   ⚠️  follow-up cadence flagged (check_followups.py exit $FOLLOWUP_CODE) — advisory"
fi

if [ "$FINDINGS_CODE" -ne 0 ]; then
  # Promoted to hard drift, not left advisory. An agent verdict that never reaches the pool is
  # indistinguishable from never having screened at all, and the cost lands on a LATER session
  # that re-screens ground already covered.
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
