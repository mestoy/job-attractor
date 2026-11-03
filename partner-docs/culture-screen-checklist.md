# Culture-screen checklist — the DEEP probe, run for EVERY finalist before a 🟢 or a send

> **The Glassdoor headline/overall rating is a FALSE-POSITIVE risk and is NEVER sufficient** — a clean-looking overall can hide a deal-breaker. A discovery agent's light culture note is a candidate FLAG, not a screen. Run this deep probe at the finalist gate — before presenting a 🟢, before any send — and **report the ✅/⚠️/❌ result**. Judgment-heavy + Glassdoor is often bot-walled, so this is a reported (agent-driven) gate, not a script; `scripts/check_screen_gate.py` checks that the evidence is PRESENT.

## Run per finalist
1. **Entity-disambiguation (first).** Confirm you're reading the RIGHT company — same-name collisions are common (an ad agency vs a healthtech; a scary review that turns out to be a foreign namesake). Verify the entity ID / domain match before trusting any number.
2. **All sub-ratings, not just overall:** Work-Life-Balance, Culture & Values, **Senior Leadership**, Career Opportunities, Comp & Benefits, **% recommend to a friend**, **% CEO approval**. Report each.
3. **Probe the reviews — 5 most-RECENT positive + 5 most-RECENT negative, quoted VERBATIM** with date + role + current/former. Scan YOUR function (product/data/the hiring team) + the deal-breakers below.
4. **TREND analysis (the requirement that catches the false positives):**
   - Rating **trajectory** — are recent reviews worse than older ones? Is the score sliding?
   - **Recency** of the bad reviews — current, or pre-event (pre-buyout/pre-acquisition/pre-new-leadership)?
   - **Headcount direction** — contraction = quiet layoffs (cross-check RepVue/LinkedIn/news).
   - **Recurring-RIF / "restructure"=layoff** pattern (every restructure = a workforce reduction).
   - **Leadership churn** over time; any inflection (acquisition, PE buyout, funding, RTO, founder demotion).
   - **Bimodal split** (glowing eng vs scathing leadership/sales) — CALL IT OUT, never average it away.
5. **Cross-source:** RepVue (Culture & Leadership sub-score), Blind, layoffs.fyi / layoffhedge, recent news. **Volume-vs-amplification:** how many DISTINCT reviewers raise a flag vs one much-quoted review.

## Gates (any → not a 🟢)
- **WLB sub-rating below your tolerance = SKIP** (an always-on/WLB sensitivity is a common hard filter).
- **Leadership instability / recurring-RIF / autocratic-whiplash = SKIP** (if leadership stability is your top factor).
- **PE-OWNED = DEFAULT SKIP (if ownership is one of your filters).** State **ownership** (PE / VC / bootstrapped / public) for every finalist. Majority private-equity ownership / buyout / PE-firm portfolio company → pass by default (PE margin-extraction → churn/layoffs). VC-backed (seed/Series A-B) is NOT this flag; bootstrapped/founder-owned is a PLUS. Driven by kit_config `PE_FLAG` / `PE_CLEARED`.
- **Broken-remote / RTO-drift = SKIP** (if remote is absolute for you).
- **Aggressive-growth / grindset / "sweatshop" / in-group-clique / DEI-sexism = SKIP.**
- **Conduct/ethics news** overrides a strong internal score.
- **Too-thin (few reviews) = ⚪ UNPROVEN, NOT clean** — never a 🟢 on a 3-review 5.0; pull whatever founder-culture signal exists (blog/podcasts/public ethos) and say the data is thin.
- **Don't hard-block a 4.x/founder-stable co on a few snippets** without a confirmed layoff/leadership event — the TREND + volume-vs-amplification read resolves this.

## Verdict
Report **🟢 CLEAN / 🟡 WATCH / 🔴 SKIP / ⚪ UNPROVEN** with: the sub-ratings, the 5+5 verbatim (or thin-note), the TREND read, and a 1-2 sentence synthesis weighed against your deal-breakers. Ties: `documents/WORKFLOW-RULES.md` §2, `documents/HARD-INVARIANTS.md` SCREEN GATE.
