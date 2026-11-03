---
name: pre-launch-audit
description: >
  Read-only audit before shipping or launching a feature: walks the per-flow test matrix,
  greps for common leftover risks, classifies findings by severity with evidence, and closes
  with a readiness score, top risks, and a rollback plan. Triggers on: pre-launch audit,
  audit before we ship, is this ready to launch, launch readiness check, pre-launch-audit.
allowed-tools: Read, Grep, Glob, Bash, AskUserQuestion
---

# Pre-Launch Audit

---

## Why this skill exists

A feature that passes its own happy-path test is not the same thing as a feature that is safe to
ship. This skill is a read-only pass across the areas that a normal build-and-test cycle tends to
skip: the states nobody manually clicks through, the leftovers a fast build leaves behind, and
the honest gaps in what was actually checked. It is a distillation of a battle-tested discipline
pattern (originally shared on r/BuildWithClaude), rebuilt here as house method rather than copied
verbatim.

**This is read-only.** Do not fix anything found during the audit — report it. Fixing belongs to
a separate pass (see `add-a-feature-safely` or `investigate-a-bug-first` in this skill set) so
the audit stays a clean, unbiased read of current state rather than a mix of findings and
in-flight patches.

**This overlaps existing house discipline and does not replace it.** If your operating rules (this kit
ships them as `WORKFLOW-RULES.md`) already mandate an independent review pass — a panel, a
red-team suite, a required gate — before high-stakes or outward-facing work ships, that
requirement stands on its own and this audit does not substitute for it. Run both.

---

## Step 1 — Walk the per-flow test matrix

For every user-facing flow the feature touches, check it against each of the following states.
Do not assume a state is handled because the adjacent state is — verify each one:

- **Success** — the intended happy path
- **Invalid input** — malformed, out-of-range, wrong type
- **Missing input** — a required field, param, or record absent
- **Failed dependency** — a downstream call, service, or write fails mid-flow
- **Expired** — a token, session, link, or time-boxed state has lapsed
- **Unauthorized** — the actor lacks permission for this action
- **Duplicate** — the action is submitted twice (double-click, retried request, replayed event)
- **Direct URL / deep link** — the flow is entered by URL rather than through the normal UI path
- **Refresh mid-flow** — the page or session is reloaded partway through
- **Mobile / small viewport** — layout and interaction on a constrained screen

For each cell in the matrix, record: checked / not checked, and if checked, what you found.

---

## Step 2 — Grep for common leftover risks

Search the changed surface (and, budget permitting, the surrounding area) for:

- **Secrets** — API keys, tokens, credentials, connection strings committed in code or config
- **Client-only permission checks** — an authorization check that exists in the frontend but has
  no matching enforcement on the server/API side
- **Silent failures** — a caught exception, a swallowed error, a `catch` block that does nothing
  observable
- **Debug output** — `console.log`/`print`/debug flags left enabled, verbose logging that could
  leak sensitive data
- **Placeholder data** — TODO/FIXME/lorem-ipsum/test values/hardcoded sample IDs left in a path
  that will run in production

Report each hit with file, line, and a one-line read of whether it is a real risk or a false
positive — do not just paste the grep output.

---

## Step 3 — Classify and score

Classify every finding as:

- **Critical** — breaks the flow, exposes data, or bypasses auth
- **High** — degrades the flow badly or is likely to be hit in normal use
- **Medium** — an edge case that will eventually be hit but is not the common path
- **Low** — cosmetic or very unlikely to matter

Every finding needs its evidence (file/line/reproduction), not just a label.

---

## Step 4 — Close with a readiness verdict

End the audit with:

1. **A readiness score or verdict** (e.g. ready / ready with caveats / not ready), stated
   plainly, not buried in the findings list.
2. **The top risks**, ranked, even if the overall verdict is "ready" — a shippable feature can
   still carry a known Medium risk worth tracking.
3. **A rollback plan** — how to undo this if it breaks something after launch (a flag to flip, a
   revert commit, a migration to reverse).
4. **What could NOT be verified** — an environment you don't have access to, a scale you can't
   simulate, a third-party integration you can't safely test against. State this explicitly
   rather than letting an unchecked area read as a checked one.
