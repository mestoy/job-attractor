# Résumé-build checklist — THE GOVERNING DOC · READ BEFORE GENERATING · REPORT EACH STEP

**This is the durable source of résumé conventions + tripwires. `Read` it BEFORE generating any résumé**, not just after — the point is polished, consistent, correct output every time, enforced mechanically rather than from memory. **Report ✅/❌/n-a per step.** Steps 3-7b + the tripwire are scriptable — run them, don't claim them. The mechanical tripwire is **`scripts/verify_resume.py` (must be 🟢 GREEN — every FAIL blocks export)**. (Compile engine: `pdflatex` for a 1-page plain-professional/`article` template — TinyTeX needs `ragged2e`; `lualatex` for a 2-page moderncv.)

### Voice & consistency conventions (the résumé's own voice — distinct from outreach)
- **Summary uses the SAME subject-dropped voice as the experience bullets — NO first person** ("Drove X…", never "I drove…"; no "my"/"me"). First person in the Summary while bullets are subject-dropped is an inconsistency. *Outreach EMAILS stay first-person — this rule is résumé-only.* Enforced by the `Summary voice (no 1st-person)` tripwire in `verify_resume.py`.
- Consistent tense: past-tense accomplishments; consistent `•`/`$\cdot$` separators; no em dashes; no spaces around slashes.

1. **☐ Source + tailor** — clone the newest plain-professional `cv/main_<recent>.tex` → `cv/main_<company>.tex`; tailor Summary + Core Skills to the role's angle; keep honesty-vetted bullets. Any prose in YOUR voice (`documents/writing-style-guide.md`), following the Voice & consistency conventions above.
2. **☐ Honesty guardrails** — no figure or claim in kit_config `RETIRED` / `RETIRED_PATTERNS` (the linter fails any that reappear); scope every metric to a primary source; obey the role-authorship guardrails (kit_config `EMPLOYERS` / `SELF_BUILT` / `ROLE_IMPLY` — don't claim an employer's engineering artifact as personally built, don't imply an engineering background you don't have); name your AI tool (kit_config `AI_TOOL_NAME`) whenever agentic/AI work is referenced; **no em dashes; no spaces around slashes**.
3. **☐ Compile clean** — `pdflatex`/`lualatex -interaction=nonstopmode -halt-on-error`; fix + recompile until no errors.
4. **☐ Page count exact** — 1 page (plain-professional) / 2 (moderncv). Verify: `mdls -name kMDItemNumberOfPages -raw "<pdf>"`.
5. **☐ Layout** — 0 `Overfull \hbox`; no orphaned `\cventry`/entry titles; no awkward gaps.
6. **☐ ATS text layer** — `pdftotext -layout`; email + phone (your kit_config identity) appear as LITERAL text; no `(cid:` / no `�`; reading order matches visual; dates present.
7. **☐ Keyword coverage** — posting keywords covered or honestly absent; **never stuff**.
7b. **☐ Tripwire GREEN** — `python3 scripts/verify_resume.py cv/main_<company>.tex` must be 🟢 (Summary ≤300 + no-1st-person + reverse-chron + no-em-dash + 2-line bullets + page count + ATS). Any ❌ blocks export — fix and rebuild.
8. **☐ Export** to `documents/cv/<Your Name> - Resume - <Company>.pdf` (the LaTeX build stays `cv/main_<company>.tex/.pdf`). **ATTACH THIS DELIVERABLE, never the internal `main_<co>.pdf`** — the recipient sees the filename, and "main_<co>.pdf" reads as a draft. `mail-draft.sh` WARNs if `--attach` doesn't match your kit_config `RESUME_FILENAME_PATTERNS` (default "<Your Name> - Resume - …").
9. **☐ Clean artifacts** — delete `.aux/.log/.out`; keep `.tex` + `.pdf`.
10. **☐ Sent-is-sent** — do NOT re-edit an already-SENT variant unless you re-engage that org.
- **☐ Report** which steps ✅/❌.
