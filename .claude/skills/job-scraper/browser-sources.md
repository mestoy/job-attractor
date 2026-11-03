# Browser-Assisted Sources (Indeed, Glassdoor, Wellfound)

Indeed, Glassdoor, and Wellfound sit behind **Cloudflare + CAPTCHA**, so they have no
zero-dependency CLI (a raw scraper only gets `403`s, and bypassing bot-detection is out of
scope). There are two ways `/scrape` can still reach them:

1. **Browser-assisted (preferred)** — drive the user's own logged-in Chrome via the
   Claude-in-Chrome tools. The user's real browser session handles login and solves any
   CAPTCHA; the agent only *reads* the rendered page. Richer and more complete than search.
2. **WebSearch fallback** — `site:` queries (see `search-queries.md`). Always available, no
   browser needed, but returns listing pages/snippets rather than full result sets.

Use browser-assisted mode **only when the Claude-in-Chrome browser is connected**. Otherwise
fall back to WebSearch. Never treat a walled response as "no jobs" — note the mode used.

---

## Prerequisites (browser-assisted mode)

- The `mcp__claude-in-chrome__*` tools are available AND the extension is connected
  (a `tabs_context_mcp` call succeeds). If it returns "not connected", **stop and use the
  WebSearch fallback** — do not retry in a loop.
- Chrome is open and the user is signed in to Indeed / Glassdoor if they have accounts
  (optional, but yields more results and fewer interstitials).

## The CAPTCHA / login rule (mandatory)

If a page shows a Cloudflare challenge, CAPTCHA, or login/consent wall, **do not attempt to
solve or click through it.** Pause, tell the user exactly what you see, and ask them to
complete it in their browser window. Resume reading once they confirm. You solve nothing;
the human does.

---

## Workflow

For each target site, per active query from `search-queries.md`:

1. **Open a tab** (`tabs_create_mcp`), then `navigate` to the search URL (patterns below).
2. **Wait for render**, then read the results with `get_page_text` (fast, returns the
   rendered text) or `read_page` / a `snapshot` for structure. Do **not** parse raw HTTP —
   read the *rendered* page.
3. **If a challenge/login appears**, apply the CAPTCHA/login rule above.
4. **Extract each job card**: title, company, location, salary (if shown), posted date, and
   the posting URL. Tag each with its source site.
5. **For a promising hit**, `navigate` to its posting URL and `get_page_text`; many detail
   pages embed a schema.org `JobPosting` (title, description, salary, dates) you can lift.
6. Feed results into the normal `/scrape` pipeline (Step 2 onward): dedupe against
   `seen_jobs.json` + the tracker, quick fit assessment, present.

Keep volume low (a few queries per site per run) — this is personal use in a real browser.

---

## Site URL patterns

Substitute the user's query and location. Add recency/remote where useful.

### Indeed
```
https://www.indeed.com/jobs?q=<QUERY>&l=<CITY, STATE>&fromage=14&sort=date
```
- `q` = keywords, `l` = location (`Remote` for remote), `fromage` = max age in days
  (`1`, `3`, `7`, `14`), `sort=date` for newest first.
- Result cards render as a list; each has title, company, location, and often a salary
  estimate and "Posted N days ago". The card title links to `/viewjob?jk=<id>` — open that
  for the full description (Indeed embeds a `JobPosting` JSON-LD on the view page).

### Glassdoor
```
https://www.glassdoor.com/Job/jobs.htm?sc.keyword=<QUERY>&locKeyword=<CITY, STATE>
```
- `sc.keyword` = keywords, `locKeyword` = location. Glassdoor may redirect to an SEO
  `.../Job/<loc>-<query>-jobs-SRCH_...htm` URL — that's fine, read the rendered result list.
- Cards carry title, company (with rating), location, and often a salary range. The job
  detail pane / page embeds a `JobPosting` JSON-LD with the full description and pay.

### Wellfound (startups)
```
https://wellfound.com/role/l/<role-slug>/<city-slug>      e.g. /role/l/software-engineer/austin
https://wellfound.com/jobs                                 (then filter in-page)
```
- Startup-focused. Cards carry role, company, location, and often equity/salary ranges.
  Signing in shows more. Read the rendered list the same way.

---

## Output contract

Normalize every browser-sourced job to the same shape the CLIs emit, so Step 2+ treats them
uniformly:

```
{ "source": "indeed|glassdoor|wellfound", "title": ..., "company": ..., "location": ...,
  "date": ..., "salary": ... | null, "url": ..., "snippet": ... | null }
```

Missing values are `null`, never omitted. If you could not read a field from the rendered
page, leave it `null` rather than guessing.
