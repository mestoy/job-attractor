# Apply checklist — RUN FOR EVERY APPLICATION, REPORT EACH STEP

**Report ✅/❌/n-a per step.** This is the non-skippable, reported gate for `/apply`; it references the other checklists (no duplication). You are the human gate — you approve the fit call and you submit.

1. **☐ Dedup + prior-history** — `python3 scripts/check_dup.py "<company>"`; ask yourself "already applied anywhere?" (the tracker only knows this workspace). ALREADY-SEEN → review prior record first.
2. **☐ Verify role LIVE** — run `python3 scripts/check_ats.py "<company>"` (ATS API: Greenhouse/Ashby/Rippling/Lever) or careers page + recency. Not live → don't build; radar/boss-hunt instead. A résumé build is not apply-ready without a dated liveness result.
3. **☐ Screen** (order, stop at first fail → DROP with reason): blocked-list → hard filters (work-arrangement incl. required-travel cadence — verify from the JD, deal-breaker industries `INDUSTRY_VETO`, political/values `POLITICS_*`, ownership `PE_FLAG`, recurring layoffs, always-on) → culture/leadership/news (`documents/culture-screen-checklist.md`: 5 recent pos+neg, verbatim on flags; deeper-probe any disqualifying signal). Run `python3 scripts/check_screen_gate.py <scorecard.txt>` — it FAILs a write-up that mentions a veto term without a recorded verdict.
4. **☐ Fit analysis** — honest strong/partial/gap (`/jd-fit`); **open the JD in the browser**; present; **get your go** before building.
5. **☐ Build the résumé** → run **`documents/resume-build-checklist.md`** (report its steps too).
6. **☐ Cover letter** — a letter only if the form has NO free-response fields → append a tailored letter after the résumé as one combined PDF (`pdfunite`), matching the résumé's style; otherwise none. In your voice; name your AI tool (kit_config `AI_TOOL_NAME`) if AI tooling is mentioned.
7. **☐ Reviewer critique + revise** — research the company (verify every company-specific claim via WebFetch/WebSearch before including); apply structured + narrative feedback; never fabricate; keep honesty guardrails.
8. **☐ Compile + visually inspect PDFs** — résumé per its checklist; a letter is exactly 1 page, bullet font matches body, no spill.
9. **☐ Open the résumé PDF** for you to review; **you submit** (never auto-submit).
10. **☐ Paired outreach** — find the product lead and boss-hunt in parallel → run **`documents/workflow-checklist.md`**.
11. **☐ Commit everything** — `job_search_tracker.csv` (applied), `outreach_log.md` (if outreach) + `documents/correspondence-log.md`, résumé file path, any new rule → `documents/WORKFLOW-RULES.md`.
- **☐ Report** which steps ✅/❌, then `scripts/backup.sh` if meaningful changes.
