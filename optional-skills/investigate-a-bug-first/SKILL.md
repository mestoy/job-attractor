---
name: investigate-a-bug-first
description: >
  Discipline for diagnosing a bug before touching code: verify the root cause with evidence,
  rank competing hypotheses, and hold off on any edit until the cause is confirmed. Triggers
  on: investigate this bug, why is this broken, debug this, find the root cause,
  investigate-a-bug-first.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, AskUserQuestion
---

# Investigate a Bug First

---

## Why this skill exists

The fastest way to ship a second bug is to fix the first one before you know what caused it. A
plausible guess that happens to make the symptom go away is not a fix — it is a coincidence that
will surface again, usually somewhere harder to trace. This skill is a distillation of a
battle-tested discipline pattern (originally shared on r/BuildWithClaude), rebuilt here as house
method rather than copied verbatim.

**This overlaps existing house discipline and does not replace it.** Two rules already govern
part of this: run the check you already know about before acting, rather than guessing past it —
and when you claim a check now catches a bug, prove the check actually goes red on that bug and
prove the proof ran, rather than asserting it from the fix's logic. If your operating rules name those
rules (this kit ships them as `WORKFLOW-RULES.md`), that source is the rule; this
skill cites it rather than re-deriving it, and exists to structure the investigation steps that
come before either of those rules is reachable.

---

## Phase 1 — Investigate (no edits yet)

1. **Restate the bug** in your own words: what is observed, what was expected instead, and under
   what conditions it happens (always / intermittently / one specific input).
2. **Trace the expected execution flow end to end.** Walk the path from trigger to the point
   where the wrong behavior shows up, through every layer it passes (UI, API, business logic,
   data layer, external call) — a bug diagnosed from only the layer where the symptom appears is
   a bug diagnosed from the wrong end.
3. **Inspect the actual files before concluding anything.** Read the code on the path you traced.
   A hypothesis formed from a function's name or a variable's name, without reading its body, is
   a guess wearing the shape of a diagnosis.
4. **Build a RANKED list of root-cause hypotheses.** For each hypothesis, state:
   - the evidence FOR it (a specific line, a specific log entry, a specific reproduced behavior)
   - the evidence AGAINST it, if any (do not omit a fact that weakens your favorite hypothesis)
   - the exact file and function where the cause would live
   - how to VERIFY it (a log line to add, a test to run, a value to print, a state to inspect)
5. **No guessing past this step.** Do not propose a fix for a hypothesis that has not been
   verified. If verification requires a resource you do not have (production data, a specific
   environment, a credential), say so explicitly and rank the hypothesis as unconfirmed rather
   than treating it as the answer.
6. **Confirm the cause before writing a structured report.** The report at minimum states: the
   symptom, the expected flow, the ranked hypotheses with their evidence, and — once verified —
   which hypothesis is confirmed and how it was verified.

---

## Phase 2 — Fix (only after the cause is verified)

1. **Propose the smallest safe fix that addresses the CONFIRMED cause.** Not the first cause you
   suspected, not a defensive fix for a hypothesis you never verified — the one you proved.
2. **Wait for approval before applying it**, the same pause this kit's build-gate
   discipline requires before any change goes in — see the note under Cross-reference.
3. **Fix only the confirmed cause.** Resist folding in an unrelated cleanup or a fix for a
   different suspected issue found along the way; log that separately instead.
4. **Regression test.** Confirm the original symptom is gone AND that the surrounding behavior
   the fix touches still works — a fix that clears the reported symptom while breaking an
   adjacent path is not done.

---

## Cross-reference

- **Run the check you already know about before acting.** If a linter, test, or gate already
  exists that would have caught this bug, run it and read its output before writing a new
  diagnosis by hand — do not treat a known check as optional under time pressure.
- **Prove the check goes red on this specific bug, and prove the proof ran.** If your fix
  includes or relies on a new or existing check, demonstrate the check fails BEFORE the fix and
  passes AFTER it — an unverified claim that "the test would have caught this" is not evidence.
- If this kit has a documented BUILD-gate pause (plan → wait for explicit approval → build
  → verify), that gate governs the fix step above; this skill exists to make sure a correct cause
  reaches that gate, not to bypass it.
