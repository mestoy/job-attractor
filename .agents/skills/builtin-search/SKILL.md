---
name: builtin-search
version: 1.0.0
description: >
  Use this skill to search US tech and startup jobs on Built In (builtin.com):
  software, data, engineering, product, design, marketing, sales, and operations
  roles at US technology companies, including remote-eligible positions. Trigger
  phrases: find a tech job, startup jobs, Built In jobs, software jobs in the US,
  remote tech jobs, "are there any X jobs at startups", look up this Built In posting.
context: fork
allowed-tools: Bash(bun run .agents/skills/builtin-search/cli/src/cli.ts *)
---

# Built In Search Skill

Search live US tech-job listings from [Built In](https://builtin.com). No authentication,
no API key, and **zero runtime dependencies** — it runs with just `bun`.

> Built In is a US technology-and-startup job board. It publishes roles nationally
> (plus remote); precise per-job location comes from the `detail` command.

## ⚠️ Personal use only

This uses Built In's public job pages. **Keep volume low and don't use it commercially
or for bulk data collection.** Run it on your own responsibility.

## When to use this skill

- Search US tech/startup job openings by keyword and recency
- Filter to remote-eligible roles
- Get the full description, company, location, salary, and dates of a specific listing

## Commands

### Search job listings

```bash
bun run .agents/skills/builtin-search/cli/src/cli.ts search [--query "<terms>"] [flags]
```

Key flags:
- `--query <text>` / `-q <text>` — keyword search (title, skill, role). Recommended.
- `--jobage <days>` — posted/updated within N days: `1`, `7`, `14`, `30`. Omit for all.
- `--remote` — only remote-eligible roles.
- `--page <n>` — page number (1-indexed, 25 results per page).
- `--limit <n>` / `-n <n>` — cap total results emitted (client-side).
- `--format json|table|plain` — default `json`.

### Fetch full job detail

```bash
bun run .agents/skills/builtin-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

`id` is the trailing number in a `/job/<slug>/<id>` URL (e.g. `10122783`). You may also
pass the full Built In job URL. Returns the full description, company, location, employment
type, salary range, posted/closing dates, and apply link.

## Usage examples

```bash
# Data engineer roles updated in the last 14 days
bun run .agents/skills/builtin-search/cli/src/cli.ts search -q "data engineer" --jobage 14 --format table

# Remote product manager roles
bun run .agents/skills/builtin-search/cli/src/cli.ts search -q "product manager" --remote --format table

# Full detail for a specific job
bun run .agents/skills/builtin-search/cli/src/cli.ts detail 10122783 --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing IDs to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.

## Notes

- Data is from Built In's public pages — no credentials required.
- The search-results page has no per-job location; search rows leave `location` null and
  `detail` fills city/state/country from the JobPosting. Apply the location filter from
  `search-queries.md` during the fit review, not at search time.
- Built In may rate-limit; the CLI retries 429/5xx with exponential backoff. Keep volume low.
- Job IDs are numeric (e.g. `10122783`) — pass them (or the full URL) to `detail`.
