# /jd-fit - Honest JD Fit Analysis

Produce an honest analysis of how you fit a specific job description, at the **decision point** (before deciding whether to apply). The role is provided as `$ARGUMENTS`: a JD URL, an ATS job URL, a "Company - Role" string, or pasted JD text.

This is the front-of-funnel evaluation that pairs with `/apply` (which builds the application). Run it whenever a role is surfaced for a go/no-go decision. Be honest, specific, and evidence-backed. Never inflate fit; central gaps stay visible.

## Steps

### 1. Get the full JD (liveness-first) and open it
- If `$ARGUMENTS` is a company/role or a search/aggregator link (not full pasted text): detect the ATS and **confirm the role is LIVE via the authoritative ATS API** before analyzing — do not analyze a ghost posting. Common ATS endpoints: Greenhouse `boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true`, Ashby `api.ashbyhq.com/posting-api/job-board/<token>?includeCompensation=true` → `descriptionPlain`, plus Lever and Rippling. Pull the full description + comp.
- **`open` the actual JD URL in the browser** so you read the real posting yourself.
- Extract: required qualifications, nice-to-haves, key responsibilities, comp, location/remote/timezone.

### 2. Load your profile (if not already in context)
- `documents/PROFILE.md` — your identity, experience, skills, deal-breakers, and preferences (the single source of truth). Include easily-missed adjacent credentials (earlier roles, ops/tooling history, domain exposure) — they often match a requirement the headline profile hides.
- If present, `.claude/skills/job-application-assistant/04-job-evaluation.md` — your deal-breakers and calibrations.

### 3. Map each requirement to you
For **each** required qualification AND each key responsibility, classify with specific evidence:
- **STRONG** — genuine match; cite the concrete evidence.
- **PARTIAL** — adjacent or reframable; name the exact reframe and apply the interview-backtrack test (could you explain it without saying "well, what I actually meant...").
- **GAP** — honest gap; label it **central** (core to the product/role) or **peripheral**.
Do the same for the nice-to-haves. A strong nice-to-have match is worth surfacing prominently.

### 4. Behavioral / culture / logistics fit
Weigh against your standing preferences and deal-breakers from `documents/PROFILE.md` (arrangement/remote, pace, IC vs management track, any values or political filter, comp target). Flag any hard-filter risk explicitly — a hard-filter fail is a drop, not a "maybe."

### 5. Verdict + recommendation (honest)
- **One-line fit verdict:** clean bullseye / strong / genuine stretch / weak — with the WHY in a phrase (e.g. "exceptional on the AI half, gapped on the distributed-systems half").
- **If applyable:** how to FRAME it — lead with the STRONG dimensions, and own the central gap **plainly** (per your writing-style honesty rules), never hide or spin it.
- **If weak:** say so and recommend passing / keep the liveness sweep going.
- Present as prose with light structure, then a clear ask: build it (strength-forward, gap-honest) or keep mining.

## Rules
- **Honesty first.** Every classification cites real evidence from your profile. No fabricated skills/experience. Central gaps are never hidden or spun.
- **Liveness before analysis** (don't analyze dead postings); **open the JD** at the start.
- Complements `/apply` (build) and the discovery liveness sweep. This is the evaluation gate that decides whether to invoke `/apply` at all.
