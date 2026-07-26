# builtin-cli

CLI for searching **US tech jobs** on [Built In](https://builtin.com) (builtin.com).

**Data source**: Built In public job pages. Search pages embed a schema.org `ItemList`
(JSON-LD); each job detail page embeds a full schema.org `JobPosting`. We parse the
JSON-LD and enrich search rows with the company name from the card markup.
**Authentication**: None required.
**Dependencies**: None (plain `bun` + `fetch`). `bun install` is optional and only pulls dev type defs.

> **Personal use only.** This uses Built In's public job pages. Keep volume low, don't
> use it commercially or for bulk data collection, and run it on your own responsibility.

## Installation

```bash
cd .agents/skills/builtin-search/cli
bun install   # optional — only installs TypeScript dev types
```

## Commands

| Command | Description |
|---------|-------------|
| `search` | Search for job listings (all flags optional) |
| `detail` | Fetch full detail for a single job listing |

`search` accepts `--format json|table|plain` (default `json`); `detail` accepts `--format json|plain`.
All errors are written to **stderr** as `{ "error": "...", "code": "..." }` with exit code `1`.

## Quick examples

```bash
# Data engineer roles updated in the last 14 days
bun run src/cli.ts search -q "data engineer" --jobage 14 --format table

# Remote product manager roles
bun run src/cli.ts search -q "product manager" --remote --format table

# Full detail for one job (by id or URL)
bun run src/cli.ts detail 10122783 --format plain
```

## Search flags

| Flag | Alias | Description |
|------|-------|-------------|
| `--query` | `-q` | Keywords (title / skill / role). Recommended. |
| `--jobage` | | Posted/updated within N days (e.g. `1`, `7`, `14`, `30`). |
| `--remote` | | Only remote-eligible roles. |
| `--page` | | 1-indexed page (25 results/page). |
| `--limit` | `-n` | Cap results emitted. |
| `--format` | | `json` \| `table` \| `plain`. |

## Notes

- Built In publishes US roles nationally (plus remote). The search-results page does
  not carry per-job location, so search rows leave `location` null; the `detail`
  command fills exact city/state/country from the JobPosting. Filter by location
  downstream in the fit review.
- The job ID is the trailing number in a `/job/<slug>/<id>` URL — pass it (or the full
  URL) to `detail`.

See `../SKILL.md` for the full flag reference and the personal-use note.
