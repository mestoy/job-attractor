# Enforcement Register — which rules are mechanically enforced, which are honor-system

> A canonical map of rule → enforcement status → owning script. The recurring failure mode is **codified-but-not-enforced**: a rule is written down but no script FAILs on a violation, so it drifts under volume. **Meta-finding: strong scripts, weak triggering** — good checks can exist yet be honor-invoked; only the send gate (`mail-draft.sh`) and the `Stop` hook (→ `consistency-check.sh`) self-fire without you asking. Five hook events can be wired in `.claude/settings.json`: **PreToolUse** (check_preview), **PostToolUse** (record_decision), **UserPromptSubmit** (record_chat_ruling), **Stop** (consistency-check), **SessionStart** (session_start). **Never assert a hook type is unavailable without checking** — a wrong capability claim in a rule file becomes a permanent excuse for leaving a rule unenforced.

## ⚠️ HONEST NOTE ON "ENFORCED"

**The `Stop` hook cannot fail.** Its command ends in `… || exit 0`, so every hard issue `consistency-check.sh` finds is printed and then passed. Several rows below are marked ENFORCED on the strength of "it self-fires at Stop" — those are really **REPORTED**. This is deliberate and kept: a Stop hook that blocks can trap the agent in a loop, which is worse than a missed report. If you schedule a daily run of `consistency-check.sh` yourself, that is the backstop (the kit does not ship OS-level scheduling).

**The genuinely blocking surfaces are exactly two:** `check_preview.py` (PreToolUse on AskUserQuestion, `exit 2`) and `scripts/mail-draft.sh` (non-zero exits at the send boundary). There is **no hook on Bash, Write or Edit**. Read every ENFORCED below against that fact.

## Legend
✅ ENFORCED (a script FAILs on violation, and it self-triggers) · ⚠️ PARTIAL (script exists but honor-invoked, or checks presence not verdict) · ❌ HONOR-SYSTEM (no mechanical check)

## Already well-enforced — DO NOT re-engineer
- Email-body AI-tells / em-dash / spaced-slash / `•` bullets / sign-off / **signature format** (2 blanks + site URL) → `check_outreach.py`, hard-blocks via `mail-draft.sh`. ✅
- Retired figures/claims in **email bodies** (kit_config `RETIRED` / `RETIRED_PATTERNS`) → `check_outreach.py`. ✅ (ships empty — a no-op until you fill your own retired list.)
- Boss-praise researched + **primary-source URL** → `mail-draft.sh --praise-source` (must contain http(s)). ✅
- Boss-hunt A1–A10 method ran → `mail-draft.sh --lacivita-check pass`. ✅ (attestation, but gated)
- **Two-stage praise** Stage-2 phrasing is YOUR pick → `mail-draft.sh --praise-phrasing` verbatim-in-body. ✅
- Résumé: 1-page, reverse-chron, Summary ≤300, **subject-dropped (no 1st-person)**, 2-line bullets, ATS text-layer (literal email/phone, no cid) → `verify_resume.py`. ✅
- Cross-store drift, follow-up cadence, blocked-list sync, tex↔export → `consistency-check.sh` (Stop hook). ✅
- Delivery is a visible draft, never auto-sent → `mail-draft.sh` (AppleScript, no send). ✅

## Rule → enforcement map (the durable check set)

> The gaps below were the design targets for the kit's blocking checks. Each row names the class of failure and the owning script — this is what to re-verify if you change a script.

| # | Rule | Status | Owning script → check |
|---|------|--------|-----------------------|
| G1 | **Deal-breaker industries** have NO mechanical catch for a **new** company (`check_dup` only knows already-blocked ones) | ✅ | `check_screen_gate.py`: kit_config `INDUSTRY_VETO` regex sets → FAIL on a veto term unless an explicit `INDUSTRY: CLEARED` verdict token (`INDUSTRY_CLEARED`) is present |
| G2 | **Dedup / blocked-list not re-checked at the SEND boundary** — a blocked/dup company can reach a visible draft | ✅ | `mail-draft.sh --company` runs `check_dup.py`, blocks on 🔴 |
| G3 | **AskUserQuestion option PREVIEWS unlinted** — the outreach linter never sees previews | ✅ | `PreToolUse` hook → `check_preview.py` extracts option label/description text, runs the `check_outreach.py` BANNED regex, blocks on hit |
| G4 | **Résumé prose not held to the email honesty bar** — a banned word or wrong figure could reach a résumé | ✅ | `verify_resume.py` imports BANNED/RETIRED from kit_config; role-implication WARN + AI-tool-name-required check |
| G5 | **Screen gates reward MENTION, not VERDICT** — a card reading "hybrid, not remote" could PASS a naive "contains remote" check | ✅ | `check_screen_gate.py`: fail on disqualifying tokens (kit_config `REMOTE_DISQUAL` / `POLITICS_DISQUAL`) unless an offsetting verdict token (`REMOTE_CONFIRM` / `POLITICS_CLEAR`) is present |
| G6 | **Good gates don't self-trigger** — `check_dup`/`check_screen_gate`/`check_ats` are honor-invoked | ✅ | `check_screen_gate.py` runs inside `consistency-check.sh` (every Stop) over the green board |
| G7 | **Résumé attachment never verified at send** | ✅ | `mail-draft.sh` resolves `cv/main_<slug>.tex` from `--company` and **blocks** on a `verify_resume.py` FAIL |
| G8 | **Remote/travel not failed from JD text** — `check_ats.py` surfaces location but made no pass/fail | ✅ | `check_ats.py` verdict exit: **0 = live role, 1 = none → RADAR**; `jd_flags()` scans the JD and reports HYBRID / RELOCATION / ONSITE-REQUIRED / DAYS-IN-OFFICE / TRAVEL-% / NON-LOCAL-TZ-OVERLAP per role |
| G9 | **Comp floor** not compared to scraped band | ✅ | `check_ats.py comp_top()` parses the band and prints 🔴 UNDER FLOOR per role. REPORTED, not blocking: the 0/1 exit is a liveness CONTRACT callers branch on |
| G10 | **Résumé attached to EVERY outreach** — `--attach` was optional | ✅ | `mail-draft.sh` blocks without `--attach` unless an explicit opt-out flag is passed |
| G11 | Channel rule (email-only, no same-day connect), don't-open-boss-LinkedIn, one-at-a-time construction, open-JD-in-browser | ❌ | Interactional / not cleanly mechanizable → stay as checklist + gate re-read |

## G12 — the BUILD GATE

**The gap that had no G-row.** `workflow-checklist.md` step 4 (live-role verify) and step 6 (scorecard + PAUSE) had **zero mechanical representation** and appeared on no gate card — so the two steps between SCREEN and SEND were unguarded. You can re-read the invariants faithfully and still skip both.

**Why these two specifically.** Sort the steps by output: the culture screen (a verdict) and boss research (sourced angles) tend to get done thoroughly; live-JD verify (a fact that could stop the build) and scorecard+PAUSE (a pause) get dropped. **The steps whose output is friction rather than product are the ones that get rationalized away** — under a one-word go-ahead, a long session, or parallel work.

**The fix — non-forgeable evidence.** Every prior gate is satisfied by evidence *the agent supplies* (`--lacivita-check pass` is the agent typing a word). So:

- **`scripts/record_decision.py`** — a **`PostToolUse`** hook on `AskUserQuestion` that appends your **actual answer** to the decision ledger (question, answer, ruling, company, timestamp). Written by the harness from your real response; **the agent cannot forge it.** Classification is conservative: BUILD only on an affirmative ruling; ambiguity is never BUILD.
- **`scripts/check_preview.py`** — the `PreToolUse` hook. It **hard-blocks (exit 2)** any question carrying drafted outreach voice unless the ledger holds a real BUILD ruling. Fail-open on any error. Three independent detectors, any one of which blocks: **(a)** a greeting addressed to a name, **(b)** a first-person credential claim near one of your `PROOF_POINTS`, **(c)** one of your `VOICE_MARKERS`.
  > ⚠️ **Corrected 2026-08-09 (BUG-104).** This line used to say the gate read `VOICE_MARKERS` **and** `VOICE_MARKER_PATTERNS`, *"two independent signals required"*. Both halves were wrong. `VOICE_MARKER_PATTERNS` fed a compiled list that **nothing ever read**, and the detectors are **OR**, not AND, so requiring two would have described a far weaker gate than the one that ships. The pattern list and its config knob are now retired. **A register that documents a mechanism which does not exist is the same defect as the dead code it describes**, and it is harder to catch, because the next reader trusts the register.
- **`HARD-INVARIANTS.md`** — a **BUILD GATE** section between SCREEN and SEND carrying both steps, plus: one scorecard = one build; a short go-ahead authorizes the activity, not a boss; a green-board `READY` row has **not** passed this gate.

**Also closed:** the doc-drift cause. Many documents can restate the workflow order; if the copies drift, the lossy ones drop exactly the gates that stop a bad build. New rule: **no document restates the step order** — all reference `workflow-checklist.md`, and the checklist wins any disagreement.

## The structural fix
Extend the one proven pattern — **a wrapper that calls the checker and blocks on non-zero** (as in `mail-draft.sh`) — to the **screen-time** and **résumé-build** boundaries, and keep the **`PreToolUse` hook** so AskUserQuestion previews and builds can be gated before the action.

## Transferable lessons (the reason this file exists)

These recur across every adversarial re-test; the pattern matters more than any individual bug. **In nearly every case the defective gate reported PASS.**

1. **A fix at the matcher is not a fix if the pre-filter shares the bug.** A "fixed" check can still be live one layer up (in the pre-filter, or in a second code path). Fix every layer, and reproduce the **real payload shape** in the test — a regression matrix that feeds single-field payloads tests the harness, not the gate.
2. **Testing a helper in isolation proves the helper, never the wiring.** Unit tests can be green while nothing consumes the function — a computed flag that is never read still prints a false PASS.
3. **The hardened copy of a duplicated rule drifts from the copy nobody re-reads.** When a rule lives in two scripts (e.g. an advisory pre-check and the irreversible send gate), the send gate is the one that matters and is often the weaker copy. Harden the boundary that ships the action.
4. **Changes interact.** A good fix can silently void a different good fix when both key on the same signal (e.g. a rung change reopening a hole a résumé-QA fix had closed). Re-run the whole suite after any signal change.
5. **Cross-store redundancy masks per-store regressions.** A defect is invisible when a second store happens to carry the same company. Test with a name in ONE store only.
6. **Substring tests are false-PASS factories.** Company-match, "SENT"-detection, and blocked-name matching must use word boundaries, not bare substrings, or any company whose name merely *contains* the substring "sent" reads as sent and a short token authorizes an unrelated company.
7. **A break-test that partially reverts a defense-in-depth fix reports a false alarm** — only a full revert is a real regression when a fix has two redundant guards.

## Test infrastructure
The lessons above only hold if they are wired into tests. Build a sandboxed harness (redirected HOME/project dir + PATH stubs so no test can reach Apple Mail, the network, or live data), a runner that fails if any test mutates a live store, and a break-test that reverts each fix and proves its test goes red. **Do not hand-maintain a test count in prose** — a fixed number is its own drift source. The authority is the runner's exit code and the CI job, not a number written here.
