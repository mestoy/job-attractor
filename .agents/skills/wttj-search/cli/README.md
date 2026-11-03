# wttj-cli

CLI for searching **US jobs** on [Welcome to the Jungle](https://www.welcometothejungle.com)
via its public Algolia jobs index.

**Data source**: WTTJ's public Algolia index `wk_cms_jobs_production` (app `CSEKHVMS53`) —
the same backend the website's job search uses. Results come back **structured** (company,
offices, contract type, remote policy, salary, experience), not as HTML.
**Authentication**: A public, search-only Algolia key (WTTJ rotates it — see below).
**Dependencies**: None (plain `bun` + `fetch`). `bun install` is optional (dev types only).

> **Personal use only.** Keep volume low, don't use it commercially or for bulk data
> collection, and run it on your own responsibility.

## The Algolia key (required)

The CLI ships **no** key (kit#95: the baked-in one went stale and every search 403'd). Set
`WTTJ_ALGOLIA_KEY` before running:

```bash
export WTTJ_ALGOLIA_KEY=<current key>
```

This is WTTJ's own public, search-only Algolia key. It sits in the site's browser bundle and is
sent on every search the site makes, so it is not a secret, but WTTJ rotates it, and the site's
CDN refuses non-browser page fetches, so the CLI cannot harvest it at runtime.

To find the current key: open welcometothejungle.com in a browser, run a job search, and in
DevTools > **Network** copy the `x-algolia-api-key` header (or `?x-algolia-api-key=` param)
from any request to `csekhvms53-dsn.algolia.net`.

A key problem never comes back as an empty result. The CLI exits 1 with one JSON line on stderr:

| code | meaning | fix |
|---|---|---|
| `WTTJ_KEY_MISSING` | `WTTJ_ALGOLIA_KEY` is unset | export it |
| `WTTJ_KEY_REJECTED` | Algolia answered 403, the key rotated | refresh it as above |

## Installation

```bash
cd .agents/skills/wttj-search/cli
bun install   # optional — only installs TypeScript dev types
```

## Commands

| Command | Description |
|---------|-------------|
| `search` | Search for job listings (all flags optional; US-only by default) |
| `detail` | Fetch full detail for a single job by reference or slug |

`search` accepts `--format json|table|plain` (default `json`); `detail` accepts `--format json|plain`.
All errors go to **stderr** as `{ "error": "...", "code": "..." }` with exit code `1`.

## Quick examples

```bash
# Data engineer roles in the US
bun run src/cli.ts search -q "data engineer" --format table

# Remote product manager roles
bun run src/cli.ts search -q "product manager" --remote --format table

# Internships
bun run src/cli.ts search -q "software engineer" --contract internship --format table

# Full detail for one job (by reference uuid, slug, or URL)
bun run src/cli.ts detail 12345678-1234-1234-1234-123456789abc --format plain
```

## Search flags

| Flag | Alias | Description |
|------|-------|-------------|
| `--query` | `-q` | Keywords (title / skill / role). Recommended. |
| `--contract` | | Contract type: `full_time`, `internship`, `apprenticeship`, `temporary`, … |
| `--remote` | | Only fully-remote roles. |
| `--worldwide` | | Do **not** restrict to US (default is US only). |
| `--page` | | 0-indexed Algolia page. |
| `--hits` | | Results per page (max 100, default 20). |
| `--limit` | `-n` | Cap results emitted. |
| `--format` | | `json` \| `table` \| `plain`. |

## Notes

- Algolia caps total reachable results at ~1000 per query. Narrow with `--query` /
  `--contract` rather than paging deeply.
- `id` in results is the WTTJ **reference** (a uuid) — pass it to `detail`.
- Some postings carry the full description in the index; when they don't, `detail`
  returns the metadata plus the job URL to open.

See `../SKILL.md` for the full flag reference and the personal-use note.
