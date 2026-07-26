# hiring-cafe-cli

CLI for searching **US jobs** on [Hiring Cafe](https://hiring.cafe) (hiring.cafe), a job
aggregator that indexes postings directly from company ATSes (Greenhouse, iCIMS, Lever,
Ashby, and more).

**Data source**: Hiring Cafe's public server-rendered search data (Next.js `__NEXT_DATA__`
`ssrHits`), driven by the `searchState` URL parameter. Results are **structured** (company,
location, workplace type, salary range, seniority, tools).
**Authentication**: None required.
**Dependencies**: None (plain `bun` + `fetch`). `bun install` is optional (dev types only).

> **Personal use only.** Keep volume low, don't use it commercially or for bulk data
> collection, and run it on your own responsibility.

## Installation

```bash
cd .agents/skills/hiring-cafe-search/cli
bun install   # optional — only installs TypeScript dev types
```

## Commands

| Command | Description |
|---------|-------------|
| `search` | Search for job listings (all flags optional) |
| `detail` | Fetch full detail for a single job by id or URL |

`search` accepts `--format json|table|plain` (default `json`); `detail` accepts `--format json|plain`.
All errors go to **stderr** as `{ "error": "...", "code": "..." }` with exit code `1`.

## Quick examples

```bash
# Data engineer roles
bun run src/cli.ts search -q "data engineer" --format table

# Remote product manager roles
bun run src/cli.ts search -q "product manager" --remote --format table

# Onsite nurse roles, page 2
bun run src/cli.ts search -q "nurse" --workplace onsite --page 1 --format table

# Full detail for one job
bun run src/cli.ts detail icims2___careers-sonalysts___2442 --format plain
```

## Search flags

| Flag | Alias | Description |
|------|-------|-------------|
| `--query` | `-q` | Keywords (title / skill / role). Recommended. |
| `--workplace` | | `remote`, `hybrid`, `onsite` — comma-separate to combine (e.g. `remote,hybrid`). |
| `--remote` | | Shorthand for `--workplace remote`. |
| `--page` | | 0-indexed page (40 results/page). |
| `--limit` | `-n` | Cap results emitted. |
| `--format` | | `json` \| `table` \| `plain`. |

## Notes

- Hiring Cafe is US-centric. Search is national; filter by city downstream in the fit
  review (each result carries a precise `location`).
- The job `id` looks like `icims2___careers-sonalysts___2442` (source␟board␟requisition).
  Pass it (or a `hiring.cafe/jobs/<id>` URL) to `detail`.
- `detail` returns the structured record (seniority, commitment, tools, company enrichment)
  and an assembled description; the raw full posting lives at the result's `applyUrl`.
- The `meta` block of a JSON search includes `totalCount`, `pageSize`, and `isLastPage`
  for paging.

See `../SKILL.md` for the full flag reference and the personal-use note.
