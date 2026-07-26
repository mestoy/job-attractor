---
name: hiring-cafe-search
version: 1.0.0
description: >
  Use this skill to search US jobs on Hiring Cafe (hiring.cafe), a job aggregator
  that indexes postings directly from company ATSes (Greenhouse, iCIMS, Lever,
  Ashby, etc.). Covers software, data, healthcare, sales, operations, and most
  other US roles, including remote and hybrid. Trigger phrases: Hiring Cafe jobs,
  hiring.cafe, find a job in the US, aggregator jobs, ATS jobs, remote jobs,
  "are there any X jobs", look up this Hiring Cafe posting.
context: fork
allowed-tools: Bash(bun run .agents/skills/hiring-cafe-search/cli/src/cli.ts *)
---

# Hiring Cafe Search Skill

Search live US job listings from [Hiring Cafe](https://hiring.cafe), which aggregates
postings straight from company applicant-tracking systems. No HTML-card scraping — results
come from the page's server-rendered JSON, so they're **structured** (company, location,
workplace type, salary range, seniority, tools). **Zero runtime dependencies** — it runs
with just `bun`.

## ⚠️ Personal use only

Keep volume low and don't use it commercially or for bulk data collection. Run it on your
own responsibility.

## When to use this skill

- Search US job openings by keyword and workplace type (remote / hybrid / onsite)
- Get the structured detail (company, location, salary, seniority, tools, apply link) of a listing

## Commands

### Search job listings

```bash
bun run .agents/skills/hiring-cafe-search/cli/src/cli.ts search [--query "<terms>"] [flags]
```

Key flags:
- `--query <text>` / `-q <text>` — keyword search (title, skill, role). Recommended.
- `--workplace <mode>` — `remote`, `hybrid`, `onsite`; comma-separate to combine.
- `--remote` — shorthand for `--workplace remote`.
- `--page <n>` — 0-indexed page (40 results per page).
- `--limit <n>` / `-n <n>` — cap total results emitted (client-side).
- `--format json|table|plain` — default `json`.

### Fetch full job detail

```bash
bun run .agents/skills/hiring-cafe-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

`id` is the `id` from `search` results (e.g. `icims2___careers-sonalysts___2442`). You may
also pass a `hiring.cafe/jobs/<id>` URL. Returns seniority, commitment, min experience,
tools, company enrichment, an assembled description, and the external apply link.

## Usage examples

```bash
# Data engineer roles
bun run .agents/skills/hiring-cafe-search/cli/src/cli.ts search -q "data engineer" --format table

# Remote product manager roles
bun run .agents/skills/hiring-cafe-search/cli/src/cli.ts search -q "product manager" --remote --format table

# Full detail for a specific job
bun run .agents/skills/hiring-cafe-search/cli/src/cli.ts detail icims2___careers-sonalysts___2442 --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing IDs to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.

## Notes

- Data is from Hiring Cafe's public server-rendered search — no credentials required.
- Hiring Cafe is US-centric; search is national. Each result carries a precise `location`,
  so apply the location filter from `search-queries.md` during the fit review.
- The JSON search `meta` block carries `totalCount`, `pageSize`, and `isLastPage` for paging
  (use `--page` to advance, 0-indexed).
- The full raw posting lives at each result's `applyUrl` (the company's ATS).
