---
name: wttj-search
version: 1.0.0
description: >
  Use this skill to search US jobs on Welcome to the Jungle (welcometothejungle.com):
  software, data, product, design, marketing, sales, operations and other roles at
  companies hiring in the United States, including remote positions and internships.
  Trigger phrases: Welcome to the Jungle jobs, WTTJ jobs, find a job in the US,
  startup jobs, remote jobs, internships, "are there any X jobs", look up this WTTJ posting.
context: fork
allowed-tools: Bash(bun run .agents/skills/wttj-search/cli/src/cli.ts *)
---

# Welcome to the Jungle Search Skill

Search live US job listings from [Welcome to the Jungle](https://www.welcometothejungle.com)
via its public Algolia jobs index. No HTML scraping — results come back **structured**
(company, offices, contract type, remote policy, salary, experience). **Zero runtime
dependencies** — it runs with just `bun`.

## ⚠️ Personal use only

Keep volume low and don't use it commercially or for bulk data collection. Run it on your
own responsibility.

## ⚠️ The Algolia key may need refreshing

WTTJ rotates its public search key. The CLI ships with a last-known key and defaults to
**US roles**. If a search returns a `403`, set a current key and retry:

```bash
export WTTJ_ALGOLIA_KEY=<current key>
```

Find the current key in a browser: open welcometothejungle.com, search jobs, and copy the
`x-algolia-api-key` header from any Network-tab request to `csekhvms53-dsn.algolia.net`.
(If the key can't be refreshed, the `/scrape` skill falls back to WebSearch for this portal.)

## When to use this skill

- Search US job openings by keyword, contract type, or remote policy
- Get the full detail (company, location, salary, experience, description) of a listing

## Commands

### Search job listings

```bash
bun run .agents/skills/wttj-search/cli/src/cli.ts search [--query "<terms>"] [flags]
```

Key flags:
- `--query <text>` / `-q <text>` — keyword search (title, skill, role). Recommended.
- `--contract <type>` — `full_time`, `internship`, `apprenticeship`, `temporary`, …
- `--remote` — only fully-remote roles.
- `--worldwide` — do **not** restrict to US (default is US only).
- `--page <n>` — 0-indexed Algolia page.
- `--hits <n>` — results per page (max 100, default 20).
- `--limit <n>` / `-n <n>` — cap total results emitted (client-side).
- `--format json|table|plain` — default `json`.

### Fetch full job detail

```bash
bun run .agents/skills/wttj-search/cli/src/cli.ts detail <reference|slug|url> [--format json|plain]
```

`reference` is the uuid `id` from `search` results. You may also pass a job slug or a full
WTTJ job URL. Returns company, location, contract, remote policy, salary, experience, and
(when present in the index) the full description.

## Usage examples

```bash
# Data engineer roles in the US
bun run .agents/skills/wttj-search/cli/src/cli.ts search -q "data engineer" --format table

# Remote product manager roles
bun run .agents/skills/wttj-search/cli/src/cli.ts search -q "product manager" --remote --format table

# Full detail for a specific job
bun run .agents/skills/wttj-search/cli/src/cli.ts detail 12345678-1234-1234-1234-123456789abc --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing IDs to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.

## Notes

- Data is from WTTJ's public Algolia index — the same one the website search uses.
- Search defaults to US roles; pass `--worldwide` to widen.
- Algolia caps total reachable results at ~1000 per query; narrow with `--query` /
  `--contract` rather than paging deeply.
- `id` in results is the WTTJ **reference** (uuid) — pass it to `detail`.
