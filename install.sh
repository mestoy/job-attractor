#!/usr/bin/env bash
# Job Attractor Kit installer — NON-DESTRUCTIVE (never overwrites your files).
# Sets up the skills + search CLIs, and seeds YOUR private working files in documents/.
# Usage: bash install.sh [TARGET_DIR]   (defaults to the current folder)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$PWD}"; mkdir -p "$TARGET"; TARGET="$(cd "$TARGET" && pwd)"

printf '\n  Job Attractor Kit — installing into: %s\n\n' "$TARGET"

# 1) Copy the shared TOOLING into the target — but only when installing FROM a separate
#    folder (the downloaded installer). If you cloned the repo and run in place, it's already here.
if [ "$HERE" != "$TARGET" ]; then
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --ignore-existing --exclude 'install.sh' --exclude 'documents' --exclude '.git' --exclude '.DS_Store' --exclude 'node_modules' "$HERE"/ "$TARGET"/
  else
    ( cd "$HERE" && for i in .[!.]* *; do
        case "$i" in install.sh|documents|.git) continue;; esac
        [ -e "$i" ] && cp -Rn "$i" "$TARGET"/ 2>/dev/null || true
      done )
  fi
  printf '  [ok] Shared tooling copied.\n'
fi

# 2) Seed YOUR private working files in documents/ (git-ignored) from the shipped templates — only if
#    missing. The scripts read the rulebook, checklists, and dedup stores from documents/, so every
#    shipped template + the operating rules doc get seeded here (that is what the gates look for).
mkdir -p "$TARGET/documents"
# 📄 /apply WRITES HERE, and neither directory existed (fixed 2026-08-05). `apply.md` references
# `cv/main_<COMPANY>.tex` and `cover_letters/cover_*.tex` nine times, and its "read an existing CV
# for structural reference" step found nothing on a first run. A command whose output directory does
# not exist fails in a way a new user reads as the command being broken.
mkdir -p "$TARGET/cv" "$TARGET/cover_letters"
for f in "$HERE"/partner-docs/*.md; do
  [ -f "$f" ] || continue; b="$(basename "$f")"
  [ -f "$TARGET/documents/$b" ] || cp "$f" "$TARGET/documents/$b"
done
# the operating rules ship at the repo root; the scripts cite documents/WORKFLOW-RULES.md
[ -f "$TARGET/documents/WORKFLOW-RULES.md" ] || { [ -f "$HERE/WORKFLOW-RULES.md" ] && cp "$HERE/WORKFLOW-RULES.md" "$TARGET/documents/WORKFLOW-RULES.md"; }
add() { [ -f "$TARGET/documents/$1" ] || printf '%b' "$2" > "$TARGET/documents/$1"; }
# a short layout guide (the /setup Path A references documents/README.md)
add README.md "# Your private working folder\n\nEverything here is git-ignored — your profile, résumés, logs, and dedup stores live here and are never pushed to the shared kit repo. Suggested subfolders to create as you need them: cv/ (résumé sources + PDFs), applications/ (per-role packets), references/. Back it up with: bash scripts/backup.sh (it snapshots this folder).\n"
add outreach-queue.md        "# Outreach Review Queue\n\nVetted, drafted emails for you to review and send. Nothing here is sent automatically. Status: NEW / SENT / DROP.\n"
add outreach-metrics.md      "# Outreach Metrics\n\n| Date | Discovered | Passed screen | Bosses verified | Drafts queued | Notes |\n|---|---|---|---|---|---|\n"
add boss-hunt-learning-log.md "# Boss-Hunt Learning Log\n\nPer outreach: match rationale, boss, the compliment + why, the suggested draft, then your actual sent version + a one-line lesson.\n"
add self-learning.md         "# Self-Learning\n\nWhat the assistant suggested vs. what you actually used, + a one-line lesson. Fold recurring lessons into documents/writing-style-guide.md.\n"
# dedup STORES that check_dup.py / consistency-check.sh look for — an absent store is a dedup blind spot
add outreach-queue-archive.md "# Outreach Queue Archive\n\nSENT and DROPPED items, moved out of the live queue.\n"
add discovery-board.md        "# Discovery Board\n\nCompanies surfaced but not yet screened.\n"
add correspondence-log.md     "# Correspondence Log\n\nVerbatim record of every message sent and received.\n"
add outreach-decision-log.md  "# Outreach Decision Log\n\nWhat you decided to build or skip, and why.\n"
add green-board.md            "# Green Board\n\nVetted, build-ready companies (the 6-gate bar). A row here is NOT build-approval.\n"
# The SEND LOG is the store the 10-rung ladder (scripts/rung_ladder.py) and the PAIR gate read on
# every turn. Seed it EMPTY so the store exists from day one: it is JSONL, so a zero-byte file is a
# valid, empty log, and the first thing a new partner is told to run should not have to cope with a
# store that was never created. CREATE-IF-ABSENT, never truncate: install.sh is re-run by the
# updater, and clobbering a real send log would erase the whole outreach history.
[ -f "$TARGET/documents/send-log.jsonl" ] || : > "$TARGET/documents/send-log.jsonl"
add BUG-LOG.md            "# 🐞 Bug Log\n\nThe durable record of defects you find in YOUR pipeline. \`pair_brief.py\` READS this file, so an OPEN row surfaces on its own as the LAST picker option, and never as the default.\n\n## ⛔ The pacing rule\n\nBugs and tests never interrupt the 3-3-3 unless you ask for them. The daily unit is 3 messages sent, and deskwork that displaces a send is deskwork. A bug that BLOCKS a send is not bug work, it is the send.\n\n## How a row works\n\n- \`- [ ]\` OPEN, \`- [x]\` FIXED. Only OPEN rows are counted.\n- Severity: 🔴 costs real work, 🟡 wrong output contained, 🟢 cosmetic.\n- Every row names where it was found, what it COST, and the fix. A row with no cost line is a preference, not a bug.\n- Never delete a fixed row. The record that a defect existed is what stops it reappearing.\n\n## OPEN\n\n## FIXED\n"
add partner-feedback.md       "# Partner Feedback (upstream)\n\nAppend-only. Entries here are defects in the SHIPPED kit that only the maintainer can fix. Format + rules: documents/partner-feedback-protocol.md. Send with: python3 scripts/send_feedback.py\n"
addroot() { [ -f "$TARGET/$1" ] || printf '%b' "$2" > "$TARGET/$1"; }
# ⛔ THIS SEED DOCUMENTED BEHAVIOR THAT WAS REMOVED (kit issue #17, 2026-08-10). It told every new
# install that a WARM send arms a follow-up with `status:armed` and a +7 day date. No rung has armed
# a follow-up since BUG-094 (2026-08-09); `mail-draft.sh`, `log_linkedin_send` and `check_followups`
# all write and expect `none`. The SEND GATE card was corrected and `install.sh` refreshes that card
# on every run, so it self-heals. **This text does not**: `addroot` writes only when the file is
# absent, so the retired instruction sat at the top of the very log the operator reads on every
# send, permanently, on every install ever made. A register that documents a mechanism which does
# not exist is the same defect as dead code, and harder to catch, because the next reader trusts it.
addroot outreach_log.md       "# Outreach Log\n\nOne block per send.\n\n⛔ NO RUNG ARMS A FOLLOW-UP. Every send records FOLLOWUP-DUE: none, warm included. The token must be PRESENT: omitting it makes the send look un-armed by accident, while 'none' records that you decided not to chase.\n\nChasing silence is retired on purpose (LaCivita p.11: you gain far more from reaching out to NEW people than from chasing someone who has not replied). A REPLY, a THANK-YOU and a new contact at the same company are all still fair game, because none of them chases silence. If you want a deliberate bump, you set the date yourself.\n"
addroot prospect_queue.md     "# Prospect Queue\n\nCompanies awaiting review.\n"

# ⚠️ TWO OUTREACH LOGS IS A REAL STATE AND THE TOOLING ONLY READS ONE (kit issue #17, 2026-08-10).
# `mail-draft.sh` resolves `_OLOG` to the REPO ROOT copy. An install was found carrying a second
# `documents/outreach_log.md` holding 329 lines of the operator's own screening narrative, culture
# verdicts and verbatim sent notes — none of it visible to any script. Nothing created that file and
# nothing forbids it, which is why it went unnoticed: both files look canonical to a human.
# ⛔ Report it, never merge or delete it. That content is the operator's and only they know which
# copy they meant.
if [ -f "$TARGET/documents/outreach_log.md" ]; then
  printf '  [!] TWO outreach logs exist, and the tooling reads only ONE:\n'
  printf '        reads:    %s\n' "$TARGET/outreach_log.md"
  printf '        IGNORED:  %s  (%s lines)\n' "$TARGET/documents/outreach_log.md" \
         "$(wc -l < "$TARGET/documents/outreach_log.md" | tr -d ' ')"
  printf '        Every script writes and reads the first one. Move anything you want the pipeline\n'
  printf '        to see into it; nothing here will merge them for you.\n'
fi
# The tracker is a STORE in check_dup.py, so an absent file is a HARD issue in consistency-check
# on day one — before you have done anything. That is the worst possible first impression for the
# Stop hook: it goes red immediately, stays red, and trains you to ignore the one surface that
# reports real drift. Seed it with the HEADER ROW ONLY (structure, never anyone's data).
addroot job_search_tracker.csv "date,company,sector,role,role_type,channel,status,contact_person,fit_rating,notes,cv_file,cover_letter_file,source\n"
# YOUR config is a git-IGNORED copy seeded from the tracked example. Keeping the live file out of
# git is what lets `Update Kit.command` pull cleanly forever: /setup fills this in, and a tracked
# file you were told to edit makes `git pull --ff-only` abort on every future update.
[ -f "$TARGET/scripts/kit_config.py" ] || { [ -f "$TARGET/scripts/kit_config.example.py" ] && \
  cp "$TARGET/scripts/kit_config.example.py" "$TARGET/scripts/kit_config.py"; }
printf '  [ok] Your working files + rulebook are in documents/ (git-ignored — private to you, never pushed).\n'

# ── UPGRADE PATH for an install that already exists ───────────────────────────────────────────
# Everything above is copy-IF-ABSENT, which is right on a first run and wrong forever after: a
# corrected gate card or a fixed enforcement hook would reach NEW installs only. This block runs
# on every install AND on every `Update Kit.command` (which re-runs this script after it pulls),
# so an existing kit converges on the shipped doctrine without ever touching your work.
# Anything replaced is copied to documents/.superseded/<timestamp>/ first.
_BK="$TARGET/documents/.superseded/$(date '+%Y-%m-%d-%H%M%S')"
_keep() { [ -f "$1" ] || return 0; mkdir -p "$_BK/$(dirname "${1#$TARGET/}")" 2>/dev/null; cp "$1" "$_BK/${1#$TARGET/}" 2>/dev/null; }

# 1. The ENFORCEMENT WIRING. .claude/settings.json is YOUR live copy, created by /setup from the
#    shipped example; git never manages it. So a fix to the example (for instance the Stop hook
#    learning to report résumé-QA failures, due follow-ups and stale network data instead of only
#    one alert class) would otherwise never reach you. Refresh it only when it still matches an
#    example this repo has shipped — that proves it is untouched. A hand-edited one is kept.
#    ⛔ Never CREATE it here: wiring hooks stays /setup's job, so a fresh install is unaffected.
_EX="$TARGET/.claude/settings.example.json"; _LIVE="$TARGET/.claude/settings.json"
if [ -f "$_EX" ] && [ -f "$_LIVE" ] && ! cmp -s "$_EX" "$_LIVE"; then
  _pristine=""
  if git -C "$TARGET" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    for _rev in $(git -C "$TARGET" log --format=%H -30 -- .claude/settings.example.json 2>/dev/null); do
      if git -C "$TARGET" show "$_rev:.claude/settings.example.json" 2>/dev/null | cmp -s - "$_LIVE"; then _pristine=1; break; fi
    done
  fi
  _keep "$_LIVE"
  if [ -n "$_pristine" ]; then
    cp "$_EX" "$_LIVE"; printf '  [ok] enforcement hooks updated (.claude/settings.json refreshed).\n'
  else
    printf '  [!] .claude/settings.json looks hand-edited — KEPT YOURS. New version: .claude/settings.example.json\n'
  fi
fi

# 2. The RULEBOOK. These are DOCTRINE, not your data.
#    ⛔ Deliberately excluded: PROFILE.md (yours), blocked-employers-list.md (your curated list),
#       segments.md and writing-style-guide.md (you tune those to yourself).
_ref=0
for _d in HARD-INVARIANTS.md ENFORCEMENT-REGISTER.md workflow-checklist.md apply-checklist.md \
          culture-screen-checklist.md boss-research-checklist.md email-body-checklist.md \
          resume-build-checklist.md HANDOFF.md MIGRATION-2026-07.md partner-feedback-protocol.md \
          RECLONE-PROCEDURE.md; do
  [ -f "$TARGET/partner-docs/$_d" ] || continue
  [ -f "$TARGET/documents/$_d" ] || continue          # not installed yet: the seeding above owns it
  cmp -s "$TARGET/partner-docs/$_d" "$TARGET/documents/$_d" && continue
  _keep "$TARGET/documents/$_d"; cp "$TARGET/partner-docs/$_d" "$TARGET/documents/$_d"; _ref=$((_ref+1))
done
[ "$_ref" -gt 0 ] && printf '  [ok] refreshed %s rulebook file(s) in documents/ (previous copies in documents/.superseded/).\n' "$_ref"

# 3) Search-CLI dependencies (needs bun)
printf '\n'

# ── PORTAL COVERAGE, MEASURED AGAINST A BASELINE (kit issue #20, 2026-08-10) ─────────────────
# ⛔ A HEADCOUNT WITH NO MEMORY REPORTS A SHRINK AS HEALTH. This step used to print "[ok] <name>"
# for whatever it found and nothing else. A partner install recloned on 2026-08-09 lost two
# operator-generated portals (dice-search, indeed-search) in the process; install.sh then reported
# "5 ok" and read as a clean run, and the loss surfaced three weeks later only because someone
# diffed a remote by hand before a force-push.
#
# ⚖️ PORTALS ADDED BY `/add-portal` ARE OPERATOR-GENERATED and live in `.agents/skills/`, outside
# anything the kit ships or tracks. So the kit cannot restore them and must not pretend to; what it
# CAN do is notice they are gone and say so while the previous copy may still exist somewhere.
#
# Enumerated INDEPENDENTLY of bun on purpose: the directories exist whether or not bun does, and
# conflating "could not install" with "not present" is how the count lies in the other direction.
_PORTAL_STAMP="$TARGET/documents/state/portals-installed.txt"
_portals_now="$(ls -d "$TARGET"/.agents/skills/*/ 2>/dev/null | xargs -n1 basename 2>/dev/null | sort)"

if [ -f "$_PORTAL_STAMP" ]; then
  _missing="$(comm -23 "$_PORTAL_STAMP" <(printf '%s\n' "$_portals_now") 2>/dev/null)"
  if [ -n "$_missing" ]; then
    printf '  [!] PORTAL COVERAGE SHRANK since the last install run. These were present before and are gone now:\n'
    printf '%s\n' "$_missing" | sed 's/^/        • /'
    printf '        These are YOUR portals (/add-portal output), not kit files, so the kit cannot restore them.\n'
    printf '        If this followed a reclone or a branch change, the previous copy is probably still on your\n'
    printf '        old remote or in a stale branch. Recover them BEFORE any force-push.\n'
    printf '        This warning REPEATS every run until the portals are back, or until you accept the loss\n'
    printf '        by deleting documents/state/portals-installed.txt.\n'
  fi
fi
# ⛔ NEVER RE-STAMP WHILE SOMETHING IS MISSING (kit issue #22, 2026-08-11). The first version
# guarded only the TOTAL loss (an empty enumeration) and re-stamped freely otherwise, so a PARTIAL
# shrink warned once, rewrote the baseline from 7 entries to 6, and went silent forever after. The
# reporter's words: a check that measures the drop, announces it once, then adopts it as the new
# truth "has measured it exactly one run's worth." That is #20's own defect with a longer fuse, and
# the warning scrolls past inside a long install run, so missing it is the expected case.
#
# ⚖️ So the baseline only moves FORWARD. It updates when nothing is missing, which still picks up
# newly added portals, and it is frozen while a loss is outstanding so the warning repeats until the
# operator resolves it. Accepting the loss is an explicit act: delete the stamp.
if [ -n "$_portals_now" ] && [ -z "${_missing:-}" ]; then
  mkdir -p "$(dirname "$_PORTAL_STAMP")"
  printf '%s\n' "$_portals_now" > "$_PORTAL_STAMP"
fi

if command -v bun >/dev/null 2>&1; then
  printf '  Installing search-CLI dependencies with bun...\n'
  for d in "$TARGET"/.agents/skills/*/cli; do
    [ -d "$d" ] || continue; name="$(basename "$(dirname "$d")")"
    if ( cd "$d" && bun install >/dev/null 2>&1 ); then printf '    [ok] %s\n' "$name"
    else printf '    [!] %s — run "bun install" there later\n' "$name"; fi
  done
else
  printf '  NOTE: "bun" is not installed, so the search CLIs are not ready yet (everything else works).\n'
  printf '        Enable later: curl -fsSL https://bun.sh/install | bash\n'
  printf '          then: for d in "%s"/.agents/skills/*/cli; do (cd "$d" && bun install); done\n' "$TARGET"
fi

# 4) Résumé toolchain — the /apply résumé path needs a TeX engine (pdflatex) to build the PDF
#    and poppler (pdftotext) to verify its ATS text layer. Graceful-degrade like bun: the rest
#    of the kit works without them; only résumé build/verify is blocked until they're installed.
printf '\n'
if command -v pdflatex >/dev/null 2>&1 && command -v pdftotext >/dev/null 2>&1; then
  printf '  [ok] TeX (pdflatex) + poppler (pdftotext) found — the résumé build/verify path is ready.\n'
else
  printf '  NOTE: the résumé path needs a TeX engine + poppler and one or both is missing\n'
  printf '        (pdflatex builds the PDF; pdftotext checks its ATS text layer). Everything else works.\n'
  printf '        macOS:  brew install --cask basictex   &&  brew install poppler\n'
  printf '        Linux:  sudo apt-get install texlive-latex-recommended poppler-utils\n'
  printf '        Then confirm the template compiles: pdflatex templates/cv/plain-professional/template.tex\n'
fi

printf '\n  DONE. Your next steps:\n'
printf '     1) Open %s in Claude Code and run: /setup\n' "$TARGET"
printf '        It interviews you and writes EVERYTHING: your profile, your identity in\n'
printf '        scripts/kit_config.py, your deal-breakers, and the enforcement hooks.\n'
printf '        You never edit a config file by hand.\n\n'
printf '     2) Then start: /matrix-hunt   (or /apply <job posting>)\n\n'
printf '  Something not working? Run: python3 scripts/doctor.py\n'
printf '  It changes nothing and tells you exactly what is missing.\n\n'
printf '  Back up your private work anytime with: bash scripts/backup.sh. Nothing is ever sent without you.\n\n'

# Closing note: how fresh is the network data the warm rungs run on? Degrade-silent (|| true —
# this file runs under set -e and an install must never fail on an informational check).
command -v python3 >/dev/null 2>&1 && python3 "$TARGET/scripts/check_network_freshness.py" 2>/dev/null || true
