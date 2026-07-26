---
name: bestpmjobs-search
version: 1.0.0
description: >
  Use this skill to search Best PM Jobs (bestpmjobs.com), a niche job board
  built specifically for product managers: PM, Senior PM, Staff/Principal PM,
  Director/Head of Product, and AI Product Manager roles at tech companies,
  including remote-eligible positions. Trigger phrases: Best PM Jobs, PM job
  board, product manager jobs, find a PM job, product management openings,
  "are there any PM jobs", look up this Best PM Jobs posting.
context: fork
allowed-tools: Bash(bun run .agents/skills/bestpmjobs-search/cli/src/cli.ts *)
---

# Best PM Jobs Search Skill

Search live product-management job listings from [Best PM Jobs](https://www.bestpmjobs.com),
a job board built specifically for PM roles ("built by Product Managers, for Product
Managers"). No authentication, no API key, and **zero runtime dependencies** — it runs
with just `bun`.

> Best PM Jobs is a PM-specific board (not geo-restricted) that aggregates roles across
> seniority levels — Associate through Principal/Staff and Director/Head of Product —
> mostly at US-headquartered tech companies, many remote-eligible.

## ⚠️ Personal use only

This uses Best PM Jobs' public job pages. **Keep volume low and don't use it commercially
or for bulk data collection.** Run it on your own responsibility. The site shows a
marketing "subscribe" popup/sticky-bar to browsers — this is not an access wall; job
descriptions are fully present in the public HTML without login.

## When to use this skill

- Search PM-specific job openings by keyword, location, and remote eligibility
- Get the full description, company, location, employment type, dates, and apply link
  of a specific listing

## Commands

### Search job listings

```bash
bun run .agents/skills/bestpmjobs-search/cli/src/cli.ts search [--query "<terms>"] [flags]
```

Key flags:
- `--query <text>` / `-q <text>` — keyword search (title, skill, role). Recommended.
- `--location <text>` / `-l <text>` — free-text place filter (city/state/country). Optional.
- `--remote` — only remote-eligible roles.
- `--page <n>` — 1-indexed page.
- `--limit <n>` / `-n <n>` — cap total results emitted (client-side).
- `--format json|table|plain` — default `json`.

No `--jobage` flag: the site has no posting-age filter and search-result cards carry no
date — only `detail` resolves a posting's exact `datePosted`.

### Fetch full job detail

```bash
bun run .agents/skills/bestpmjobs-search/cli/src/cli.ts detail <slug|url> [--format json|plain]
```

`slug` is the trailing path segment of a `/jobs/<slug>` URL (e.g.
`staff-product-manager-9870498c`). You may also pass the full Best PM Jobs job URL.
Returns the full description, company, location (remote + eligible countries, or a
city/region/country for non-remote roles), employment type, posted/closing dates, and
the external apply link (the company's own ATS, e.g. Ashby/Greenhouse/Lever).

## Usage examples

```bash
# Remote product manager roles
bun run .agents/skills/bestpmjobs-search/cli/src/cli.ts search -q "product manager" --remote --format table

# AI product manager roles, US-based
bun run .agents/skills/bestpmjobs-search/cli/src/cli.ts search -q "AI product manager" -l "United States" --format table

# Full detail for a specific job
bun run .agents/skills/bestpmjobs-search/cli/src/cli.ts detail staff-product-manager-9870498c --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing slugs to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.

## Notes

- Data is from Best PM Jobs' public pages — no credentials required. `robots.txt` allows
  all paths (`Allow: /`).
- The search-results page is plain server-rendered HTML with no JSON-LD; the CLI parses
  the visible job cards (title, company, employment-type badge, location text) directly.
  Each job's **detail** page embeds a full `schema.org JobPosting` JSON-LD block (same
  pattern as `builtin-search`), which the CLI parses instead of the visual markup —
  more reliable for description, dates, and location.
- Search-result cards carry no posting date; `detail` fills `datePosted`/`validThrough`
  from the JobPosting.
- The site is built on the "JobBoardly" white-label job-board platform; other
  JobBoardly-hosted niche boards likely share this same markup/JSON-LD pattern if a
  similar skill is ever needed for one.
- The `applyUrl` returned by `detail` is the site's own tracked apply link, which
  redirects to the company's actual ATS (Ashby/Greenhouse/Lever/etc.) — use it directly
  rather than the Best PM Jobs URL when handing a posting off for application.
