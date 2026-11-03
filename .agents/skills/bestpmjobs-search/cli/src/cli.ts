#!/usr/bin/env bun
// Self-contained CLI for searching Best PM Jobs (bestpmjobs.com), a niche
// product-management-specific job board. No external CLI framework, so it
// runs anywhere `bun` is available with zero install beyond the repo clone.
//
// Personal use only. This reads Best PM Jobs' public job pages; keep volume low
// and do not use it commercially or for bulk data collection. Run it on your
// own responsibility.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit" }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a.startsWith("--") || a.startsWith("-")) {
      const key = alias[a.replace(/^-+/, "")] ?? a.replace(/^-+/, "")
      const next = argv[i + 1]
      if (next === undefined || next.startsWith("-")) {
        flags[key] = true
      } else {
        flags[key] = next
        i++
      }
    } else {
      ;(flags._ as string[]).push(a)
    }
  }
  return flags
}

const HELP = `bestpmjobs-cli — search Best PM Jobs (bestpmjobs.com), a PM-specific job board

USAGE
  bun run src/cli.ts search [--query "<terms>"] [flags]
  bun run src/cli.ts detail <slug|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill, or role). Recommended.
  --location, -l <text>   Free-text place filter (city/state/country). Optional.
  --remote                Only remote-eligible roles.
  --page <n>              1-indexed page. Default 1.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

NOTES
  Best PM Jobs has no posting-age filter, so there is no --jobage flag; use
  'detail' on a promising result for its exact datePosted. The search-results
  page has no per-job date either — only 'detail' resolves it.

EXAMPLES
  bun run src/cli.ts search -q "product manager" --remote --format table
  bun run src/cli.ts search -q "AI product manager" -l "United States" --format table
  bun run src/cli.ts detail product-manager-1fdc0d00 --format plain
  bun run src/cli.ts detail https://www.bestpmjobs.com/jobs/staff-product-manager-9870498c --format plain

Personal use only — uses Best PM Jobs' public pages; keep volume low.
`

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const flags = parseFlags(argv)
  const cmd = (flags._ as string[])[0]

  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return cmd ? 0 : 1
  }

  if (cmd === "search") {
    const fmt = (flags.format as string) || "json"

    const parseIntFlag = (name: string, raw: string | boolean | string[]): number | null => {
      const val = parseInt(raw as string, 10)
      if (isNaN(val)) {
        writeBadArg(name, raw)
        return null
      }
      return val
    }

    for (const name of ["page", "limit"] as const) {
      if (flags[name] !== undefined && typeof flags[name] !== "boolean") {
        const v = parseIntFlag(name, flags[name])
        if (v === null) return 1
        flags[name] = String(v)
      }
    }

    const opts: SearchOpts = {
      query: typeof flags.query === "string" ? flags.query : undefined,
      location: typeof flags.location === "string" ? flags.location : undefined,
      remote: Boolean(flags.remote),
      page: flags.page && typeof flags.page === "string" ? Math.max(1, parseInt(flags.page, 10)) : 1,
      limit: flags.limit && typeof flags.limit === "string" ? parseInt(flags.limit, 10) : undefined,
      format: (["json", "table", "plain"].includes(fmt) ? fmt : "json") as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(JSON.stringify({ error: "detail requires a <slug|url>", code: "NO_ID" }) + "\n")
      return 1
    }
    const fmt = (flags.format as string) || "json"
    const opts: DetailOpts = {
      id,
      format: (fmt === "plain" ? "plain" : "json") as DetailOpts["format"],
    }
    return runDetail(opts)
  }

  process.stderr.write(JSON.stringify({ error: `Unknown command "${cmd}"`, code: "BAD_CMD" }) + "\n")
  return 1
}

function writeBadArg(name: string, raw: unknown): void {
  process.stderr.write(JSON.stringify({ error: `--${name} must be a number, got "${raw}"`, code: "BAD_ARG" }) + "\n")
}

main().then((code) => process.exit(code))
