---
name: add-a-feature-safely
description: >
  Discipline for adding a feature or change to an existing codebase without breaking what
  already works: inspect and plan first, wait for approval, then build inside existing
  patterns and verify before reporting done. Triggers on: add a feature, implement this,
  build this change, add-a-feature-safely, safe feature add.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, AskUserQuestion
---

# Add a Feature Safely

---

## Why this skill exists

Every requested addition is a chance to make an unrelated file worse. The discipline below
exists to keep a feature request from becoming a rewrite, and to keep "it compiles" from being
mistaken for "it works." It is a distillation of a battle-tested discipline pattern (originally
shared on r/BuildWithClaude as one of a set of prompts meant to slow an agent down before it
touches a real codebase), rebuilt here as house method rather than copied verbatim.

**This is a specific case of a general house rule, not a new one.** If your operating rules
(this kit ships them as `WORKFLOW-RULES.md`, or your own equivalent gate doc) already govern
build/plan/wait behavior for the task at hand, that governing doc wins — this skill exists for
the cases it does not name (general feature work), and cites the shared rules rather than
re-stating them.

---

## Phase 1 — Inspect and plan (read-only, no edits yet)

Before writing a single line:

1. **Restate the request** in your own words, including what you understand the operator wants
   and why, so a misunderstanding surfaces before it costs an edit.
2. **Name what you don't know yet.** If the request is ambiguous on scope, data shape, or
   expected behavior, ask rather than assume — a wrong assumption compounds through every
   later step.
3. **Trace the current flow.** Read the code path this feature will sit inside: what calls what,
   what state it touches, what already handles a similar case. A feature bolted onto a flow you
   have not traced is a feature that duplicates or contradicts existing logic.
4. **Find the precedent.** Search for how this codebase already handles functionality similar to
   what you are adding (a comparable form, a comparable API route, a comparable state machine).
   New code that ignores an existing pattern is the fastest way to produce two inconsistent ways
   of doing the same thing.
5. **List every file you expect to create or modify, and why each one is on the list.** A file
   that cannot be justified does not belong in the plan.
6. **Name the risk surface**: what could this change conflict with, what could it regress, does
   it touch auth/permissions/money/user data. Write the risk down as a checklist item, not a
   disclaimer buried in prose — a risk you named and then ignored is a worse failure than one you
   never noticed.
7. **Propose the SMALLEST implementation that satisfies the request.** Prefer extending an
   existing function or component over introducing a new abstraction; prefer the minimal diff
   that is still correct over the "nice to have while I'm in here" version.
8. **Present the plan and WAIT.** Show the restated request, the touched-files list with
   rationale, the risk surface, and the step-by-step build plan. **Do not proceed to Phase 2
   until the operator approves it.** A plan that skips this pause is not a smaller version of the
   discipline — it is the discipline skipped.

---

## Phase 2 — Build (only after approval)

1. **Follow the existing patterns you found in Phase 1.** Match naming, structure, error
   handling, and style already in use nearby — a feature that looks hand-copied from a different
   codebase is a maintenance cost for whoever reads it next.
2. **No unrelated rewrites.** Touch only what the approved plan named. If you discover something
   else that looks wrong while you're in a file, note it for a separate task rather than folding
   it into this diff — an approved small change that grows into an unrelated cleanup is exactly
   the failure this skill exists to prevent.
3. **Cover every UI/interaction state the feature can be in**, not just the happy path: loading,
   empty, error, disabled, and any permission-gated state a real user could hit.
4. **Respect existing auth/permission boundaries.** A new code path that bypasses an
   authorization check the rest of the codebase enforces is a security regression, not a
   shortcut.

---

## Phase 3 — Verify and report

1. **Test the full flow**, not just the new code in isolation: the happy path end to end, at
   least one invalid-input case, and at least one failure case (a dependency unavailable, a
   write that fails partway).
2. **Report every file touched**, with a one-line reason per file — the same list from Phase 1,
   now marked against what actually changed.
3. **State plainly what could NOT be verified** — a path that needs a service you don't have
   access to, a state that only reproduces in production, a permission tier you can't assume.
   An unverified path reported as verified is worse than an honest gap.

---

## Cross-reference

If this kit already runs a mandatory independent review pass on code changes (a
build-quality panel, a red-team suite, a required test run before a change is considered done),
that requirement is layered ON TOP of this skill, not replaced by it — check for it and run it.
This skill covers the individual-discipline half (inspect, plan, wait, build clean, verify); a
house-wide review-panel requirement is a separate, additional gate.
