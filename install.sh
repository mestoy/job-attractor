#!/usr/bin/env bash
# Job Attractor Kit installer — NON-DESTRUCTIVE (never overwrites your files).
# Sets up the skills + search CLIs, and seeds YOUR private working files in documents/.
# Usage: bash install.sh [TARGET_DIR]   (defaults to the current folder)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$PWD}"; mkdir -p "$TARGET"; TARGET="$(cd "$TARGET" && pwd)"

printf '\n  Job Attractor Kit — installing into: %s\n\n' "$TARGET"

# 0) What the kit needs before anything else (pre-launch audit 2026-09-14, F10): python3 3.9 or
#    newer and git. Stock macOS ships neither until the Xcode Command Line Tools are installed,
#    and a missing python3 used to read as an opt-out further down. Stop here, in plain words.
_need=""
if ! command -v git >/dev/null 2>&1; then
  _need="git"
fi
if ! command -v python3 >/dev/null 2>&1; then
  _need="${_need:+$_need and }python3 3.9 or newer"
else
  _pv="$(python3 --version 2>&1 | sed -n 's/^Python \([0-9]*\)\.\([0-9]*\).*/\1 \2/p')"
  _pmaj="${_pv%% *}"; _pmin="${_pv##* }"
  if [ -z "$_pmaj" ] || [ "$_pmaj" -lt 3 ] || { [ "$_pmaj" -eq 3 ] && [ "$_pmin" -lt 9 ]; }; then
    _need="${_need:+$_need and }python3 3.9 or newer (you have $(python3 --version 2>&1))"
  fi
fi
if [ -n "$_need" ]; then
  printf '  This kit needs %s before it can install.\n' "$_need"
  printf '  On a Mac, install the Xcode Command Line Tools once:  xcode-select --install\n'
  printf '  On Linux:  sudo apt-get install git python3\n'
  printf '  Then run this installer again. Nothing was changed.\n\n'
  exit 1
fi

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
# ⛔ THIS LOOP USED TO ITERATE ZERO TIMES IN SILENCE (BUG-045, kit #60, 2026-09-12). With no
# partner-docs/ folder beside install.sh, `for f in partner-docs/*.md` matches nothing, seeds
# nothing, and the run still printed DONE. A partner then saw doctor.py say "run install.sh" on a
# loop, and resolved it by hand with `git show kit/main:partner-docs/<file>`. So: count what was
# seeded, fall back to the kit remote's history when the folder is gone, and when neither source
# exists say SKIPPED where the eye lands and exit non-zero. A seed that cannot run must say so.
_SEED_SKIPPED=""; _seeded=0; _kept=0
_kit_remote() { # the remote whose URL is the kit (the same resolution kit_update.py makes); empty if none
  git -C "$1" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
  for _r in $(git -C "$1" remote 2>/dev/null); do
    case "$(git -C "$1" remote get-url "$_r" 2>/dev/null)" in *job-attractor*) printf '%s' "$_r"; return 0;; esac
  done
}
# MAINTAINER-ONLY docs never seeded into a partner's documents/ (H4): they describe how the
# MAINTAINER pulls a merged public PR back into the kit lineage, a step no partner install ever
# runs, and PUBLIC-PR-INGESTION.md names the maintainer's own public repo remote as its worked
# example. Seeding it put that remote on every partner's disk for no operational reason. The
# unrelated github.com/mestoy/job-attractor-kit line further down (the git-history fallback's own
# instructions) stays — partners really do clone that repo, so it is an address, not a leak.
_MAINTAINER_ONLY_DOCS="PUBLIC-PR-INGESTION.md"
_seed_skip() { case " $_MAINTAINER_ONLY_DOCS " in *" $1 "*) return 0;; esac; return 1; }
if [ -d "$HERE/partner-docs" ] && ls "$HERE"/partner-docs/*.md >/dev/null 2>&1; then
  for f in "$HERE"/partner-docs/*.md; do
    [ -f "$f" ] || continue; b="$(basename "$f")"
    _seed_skip "$b" && continue
    if [ -f "$TARGET/documents/$b" ]; then _kept=$((_kept+1)); else cp "$f" "$TARGET/documents/$b"; _seeded=$((_seeded+1)); fi
  done
  printf '  [ok] seeded %s template(s) from partner-docs/ into documents/ (%s already there, kept as yours).\n' "$_seeded" "$_kept"
else
  _KR="$(_kit_remote "$HERE")"
  _hist=""
  [ -n "$_KR" ] && _hist="$(git -C "$HERE" ls-tree --name-only "$_KR/main" partner-docs/ 2>/dev/null)" || true
  if [ -n "$_hist" ]; then
    for _pth in $_hist; do
      case "$_pth" in *.md) ;; *) continue;; esac
      b="$(basename "$_pth")"
      _seed_skip "$b" && continue
      if [ -f "$TARGET/documents/$b" ]; then _kept=$((_kept+1))
      else git -C "$HERE" show "$_KR/main:$_pth" > "$TARGET/documents/$b" 2>/dev/null && _seeded=$((_seeded+1)); fi
    done
    printf '  [!] partner-docs/ is ABSENT from this checkout, so the templates were seeded from git history\n'
    printf '        (%s/main:partner-docs/): %s seeded, %s already there and kept. Restore the folder with:\n' "$_KR" "$_seeded" "$_kept"
    printf '          git -C "%s" checkout %s/main -- partner-docs/\n' "$HERE" "$_KR"
  else
    _SEED_SKIPPED=1
    printf '  [!] SEEDING SKIPPED: %s/partner-docs/ is missing (or holds no .md), and no kit remote\n' "$HERE"
    printf '        with partner-docs/ in its history could be found. NOTHING was copied into documents/, so\n'
    printf '        PROFILE.md, employer-criteria-matrix.md, segments.md, writing-samples.md and the rulebook\n'
    printf '        stay ABSENT until you seed them. Next step (works without the folder), from %s:\n' "$TARGET"
    printf '          git remote add kit <the private kit address from your invitation> && git fetch kit\n'
    printf '          for f in $(git ls-tree --name-only kit/main partner-docs/); do\n'
    printf '            [ -f "documents/$(basename $f)" ] || git show "kit/main:$f" > "documents/$(basename $f)"; done\n'
    printf '        then re-run: bash install.sh .\n'
  fi
fi
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

# DECISION-LEDGER KEY (kit #121). Create this install's signing key and take the one-time
# snapshot of rulings signed with the old per-HOME key now, at install or update time, so it
# holds rows present when the update ran. Runs after kit_config.py is seeded so the owner's
# ledger settings are used. Errors stay visible; a failure never stops the install.
if command -v python3 >/dev/null 2>&1 && [ -f "$TARGET/scripts/record_decision.py" ]; then
  if python3 "$TARGET/scripts/record_decision.py" --migrate >/dev/null; then
    printf '  [ok] decision-ledger signing key ready for this install.\n'
  else
    printf '  [!] decision-ledger signing key could not be set up. Run: python3 scripts/doctor.py\n'
  fi
fi
printf '  [ok] Your working files + rulebook are in documents/ (git-ignored — private to you, never pushed).\n'

# ── SKILLS → WHERE CLAUDE CODE ACTUALLY LOADS THEM ──────────────────────────────
# ⛔ Claude Code reads .claude/skills/<name>/SKILL.md and nothing else. The shipped kit carries
# them in that shape already. The tree they are MAINTAINED in carries them flat, as
# skills/<name>.md, and backup.sh does the conversion on the way out:
#     _kitsync "skills/$_sk.md"  ".claude/skills/$_sk/SKILL.md"
# This installer copies the tree across wholesale and never did that conversion, so an install
# from the source tree left every skill in a folder Claude Code does not read, with nothing
# reporting it: gates wired, templates seeded, doctor happy, and /apply and the house style simply
# absent. Copy-if-absent, so a skill already there is left exactly as it is.
if [ -d "$TARGET/skills" ]; then
  _sk_added=0
  for _f in "$TARGET"/skills/*.md; do
    [ -f "$_f" ] || continue
    _sn="$(basename "$_f" .md)"
    if [ ! -f "$TARGET/.claude/skills/$_sn/SKILL.md" ]; then
      mkdir -p "$TARGET/.claude/skills/$_sn"
      cp "$_f" "$TARGET/.claude/skills/$_sn/SKILL.md"
      _sk_added=$((_sk_added+1))
    fi
  done
  [ "$_sk_added" -gt 0 ] && printf '  [ok] %s skill(s) installed to .claude/skills/ (where Claude Code reads them).\n' "$_sk_added"
fi

# ── OPTIONAL SKILLS (BUG-212, kit #81) — OPT-IN, never enabled by default ───────────────────
# Code-discipline skills (add-a-feature-safely, investigate-a-bug-first, pre-launch-audit) ship
# under optional-skills/<name>/SKILL.md, a folder Claude Code does NOT load. They reach
# .claude/skills/ only when their name is listed in KIT_OPTIONAL_SKILLS in scripts/kit_config.py.
# Copy-if-absent, like everything else here; an unknown name is NAMED, never skipped in silence.
_OPT_SRC=""
# ⛔ SAME TWO-NAMES SPLIT AS skills/ ABOVE. The kit carries optional-skills/<name>/SKILL.md; the
# source tree carries them flat as skills-optional/<name>.md, and backup.sh converts on the way
# out. Without this, an install from the source tree finds no optional-skills/ folder, prints
# nothing about them, and KIT_OPTIONAL_SKILLS can never enable a skill this kit does ship.
for _c in "$HERE/skills-optional" "$TARGET/skills-optional"; do
  if [ -d "$_c" ] && ls "$_c"/*.md >/dev/null 2>&1; then
    for _f in "$_c"/*.md; do
      _on2="$(basename "$_f" .md)"
      [ -f "$TARGET/optional-skills/$_on2/SKILL.md" ] && continue
      mkdir -p "$TARGET/optional-skills/$_on2"; cp "$_f" "$TARGET/optional-skills/$_on2/SKILL.md"
    done
    break
  fi
done
for _c in "$HERE/optional-skills" "$TARGET/optional-skills"; do [ -d "$_c" ] && { _OPT_SRC="$_c"; break; }; done
_OPT_CFG="$TARGET/scripts/kit_config.py"; [ -f "$_OPT_CFG" ] || _OPT_CFG="$TARGET/scripts/kit_config.example.py"
_opt_list=""
if [ -f "$_OPT_CFG" ] && command -v python3 >/dev/null 2>&1; then
  _opt_list="$(python3 - "$_OPT_CFG" <<'PY2' 2>/dev/null || true
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"^KIT_OPTIONAL_SKILLS\s*=\s*(\[[^\]]*\])", src, re.M)
print(" ".join(re.findall(r"[\"']([^\"']+)[\"']", m.group(1))) if m else "")
PY2
)"
fi
if [ -n "$_OPT_SRC" ] && [ -n "$_opt_list" ]; then
  _on=""; _unknown=""
  for _n in $_opt_list; do
    if [ -f "$_OPT_SRC/$_n/SKILL.md" ]; then
      if [ ! -f "$TARGET/.claude/skills/$_n/SKILL.md" ]; then
        mkdir -p "$TARGET/.claude/skills/$_n"; cp "$_OPT_SRC/$_n/SKILL.md" "$TARGET/.claude/skills/$_n/SKILL.md"
      fi
      _on="$_on $_n"
    else _unknown="$_unknown $_n"; fi
  done
  [ -n "$_on" ] && printf '  [ok] optional skills enabled (KIT_OPTIONAL_SKILLS):%s\n' "$_on"
  [ -n "$_unknown" ] && printf '  [!] KIT_OPTIONAL_SKILLS names a skill this kit does not ship:%s (see optional-skills/)\n' "$_unknown"
elif [ -n "$_OPT_SRC" ]; then
  printf '  [--] optional skills NOT enabled (opt in by listing names in KIT_OPTIONAL_SKILLS, scripts/kit_config.py):'
  for _d in "$_OPT_SRC"/*/; do [ -f "$_d/SKILL.md" ] && printf ' %s' "$(basename "$_d")"; done; printf '\n'
fi

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
#    A fresh install CREATES it from the example (2026-09-14, the never-installed rehearsal found
#    every gate off after a clean install on the /app path, with the only fix a terminal command
#    the person was promised they would not need). /setup still refreshes it on its own path.
_EX="$TARGET/.claude/settings.example.json"; _LIVE="$TARGET/.claude/settings.json"
if [ -f "$_EX" ] && [ ! -f "$_LIVE" ]; then
  cp "$_EX" "$_LIVE"
  printf '  [ok] enforcement hooks wired: every gate is on from your first session, nothing to type.\n'
fi
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
# `|| true`: with NO portal directories GNU xargs runs `basename` once with no argument, exits 123,
# and under set -e/pipefail that killed the whole install at this line, silently, after the
# "[ok] Your working files" line (found while reproducing BUG-045 in an empty tree).
_portals_now="$(ls -d "$TARGET"/.agents/skills/*/ 2>/dev/null | xargs -n1 basename 2>/dev/null | sort)" || true

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

if [ -f "$HERE/.public-snapshot" ]; then
  # The public CLI copy (scripts/publish-public.sh writes this marker): the app is not part of it.
  printf '\n  DONE. Your next steps:\n'
  printf '     1) Open %s in Claude Code and type: /setup\n' "$TARGET"
  printf '        It interviews you and writes EVERYTHING: your profile, your identity in\n'
  printf '        scripts/kit_config.py, your deal-breakers, and the enforcement hooks.\n'
  printf '        You never edit a config file by hand. Then start: /matrix-hunt  (or /apply <job posting>)\n\n'
else
  printf '\n  DONE. Your next steps:\n'
  printf '     1) Open %s in Claude Code and type: /app\n' "$TARGET"
  printf '        It builds your page, publishes it, and prints a link. Open the link and press Start:\n'
  printf '        the app asks six short questions and saves each answer as you go. When you press\n'
  printf '        Finish, come back here and type /app again. From then on everything to your first\n'
  printf '        boss-hunting message happens in the app. It never sends anything for you.\n'
  printf '        On its second screen the app asks how much help you want: full service (it does the\n'
  printf '        finding, screening and drafting; you decide and send), self-guided (each step shown\n'
  printf '        with a hint; you do the work), or do it yourself (the controls and your record, no hints).\n\n'
  printf '     2) Prefer the terminal? Run: /setup\n'
  printf '        It interviews you and writes EVERYTHING: your profile, your identity in\n'
  printf '        scripts/kit_config.py, your deal-breakers, and the enforcement hooks.\n'
  printf '        You never edit a config file by hand. Then start: /matrix-hunt  (or /apply <job posting>)\n\n'
fi
printf '  Something not working? Run: python3 scripts/doctor.py\n'
printf '  It changes nothing and tells you exactly what is missing.\n\n'
printf '  Back up your private work anytime with: bash scripts/backup.sh. It saves a snapshot and commits\n'
printf '  locally; it pushes only to a fork you own and never pushes into someone else'"'"'s repo.\n\n'

# Closing note: how fresh is the network data the warm rungs run on? Degrade-silent (|| true —
# this file runs under set -e and an install must never fail on an informational check).
command -v python3 >/dev/null 2>&1 && python3 "$TARGET/scripts/check_network_freshness.py" 2>/dev/null || true

# ── THE DOCTOR RUNS, AND ITS VERDICT IS HONORED (K3) ─────────────────────────────────────────
# ⛔ THIS USED TO BE A SUGGESTION. The install printed "Something not working? Run: doctor.py" and
# exited 0, so a stranger's first minute ended on DONE for an install doctor.py would have refused,
# and nothing told them. A check that is named and never run is an empty check passing at the worst
# possible moment.
# doctor.py's own contract: 0 = ready, warnings are fine; 1 = something blocking is unconfigured.
# `set -e` is on, so the call is guarded to capture the code rather than abort the script here.
# ⛔ THE SKIPPED SEED IS REPORTED BEFORE THE DOCTOR RUNS, and it used to be reported after.
# It is the more specific failure and it carries its own one-liner, so it must be the last thing
# on screen rather than being buried under a doctor report that lists it again among a dozen other
# lines. It exits non-zero either way, which is the part that matters: an install whose templates
# never arrived must not end on DONE.
if [ -n "$_SEED_SKIPPED" ]; then
  printf '\n  ⚠️  SEEDING SKIPPED — documents/ is missing its templates (partner-docs/ was not found).\n'
  printf '      Scroll up to "[!] SEEDING SKIPPED" for the git show one-liner, then re-run install.sh.\n\n'
  exit 2
fi

printf '\n  Checking the install...\n\n'
# ⛔ THE CHECKER ITSELF CAN BE ABSENT, and that is a different problem with a different answer.
# Running a missing file gives a python traceback and exit 2, which reads as "the installer
# crashed" when what happened is that this copy of the kit does not carry its own doctor. Say
# which one it is. Either way the install is NOT ready and must not end on DONE.
if [ ! -f "$TARGET/scripts/doctor.py" ]; then
  printf '  ⚠️  THIS KIT IS INCOMPLETE: scripts/doctor.py is missing, so the install cannot be\n'
  printf '      checked and nothing can tell you what is or is not configured.\n'
  printf '      Update the kit: double-click \x27Update Kit.command\x27, or run: git pull && bash install.sh .\n\n'
  exit 1
fi
_DOCTOR_RC=0
python3 "$TARGET/scripts/doctor.py" || _DOCTOR_RC=$?
if [ "$_DOCTOR_RC" -ne 0 ]; then
  printf '\n  ⚠️  THE INSTALL IS NOT READY. The lines above say what is unconfigured and how to fix\n'
  printf '      each one. Nothing here is broken; these are things only you can answer.\n'
  printf '      Fix them, then run: python3 scripts/doctor.py\n\n'
  exit "$_DOCTOR_RC"
fi

# BUG-045: repeat the skipped seed where the eye lands, after DONE, and exit non-zero so a caller
# (Update Kit.command, a script, a person reading $?) cannot take this run for a complete one.
