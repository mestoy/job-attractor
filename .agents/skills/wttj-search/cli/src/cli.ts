#!/usr/bin/env bun
// Self-contained CLI for searching jobs on Welcome to the Jungle (US) via its
// public Algolia jobs index. No external CLI framework, so it runs anywhere `bun`
// is available with zero install beyond the repo clone.
//
// Personal use only. This reads WTTJ's public job search backend; keep volume low
// and do not use it commercially or for bulk data collection.
//
// If searches return a 403, the public Algolia key rotated — set WTTJ_ALGOLIA_KEY
// to a current key (see the note at the top of src/helpers.ts).

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", n: "limit" }
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

const HELP = `wttj-cli — search US jobs on Welcome to the Jungle

USAGE
  bun run src/cli.ts search [--query "<terms>"] [flags]
  bun run src/cli.ts detail <reference|slug|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill, or role). Recommended.
  --contract <type>       Contract type, e.g. full_time, internship, apprenticeship, temporary.
  --remote                Only fully-remote roles.
  --worldwide             Do NOT restrict to US roles (default is US only).
  --page <n>              0-indexed Algolia page. Default 0.
  --hits <n>              Results per page (max 100). Default 20.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

EXAMPLES
  bun run src/cli.ts search -q "data engineer" --format table
  bun run src/cli.ts search -q "product manager" --remote --format table
  bun run src/cli.ts search -q "software engineer" --contract internship --format table
  bun run src/cli.ts detail 12345678-1234-1234-1234-123456789abc --format plain

Personal use only. If you get a 403, set WTTJ_ALGOLIA_KEY (see src/helpers.ts).
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
        process.stderr.write(
          JSON.stringify({ error: `--${name} must be a number, got "${raw}"`, code: "BAD_ARG" }) +
            "\n",
        )
        return null
      }
      return val
    }

    for (const name of ["page", "hits", "limit"] as const) {
      if (flags[name] !== undefined && typeof flags[name] !== "boolean") {
        const v = parseIntFlag(name, flags[name])
        if (v === null) return 1
        flags[name] = String(v)
      }
    }

    const hits =
      flags.hits && typeof flags.hits === "string"
        ? Math.min(100, Math.max(1, parseInt(flags.hits, 10)))
        : 20

    const opts: SearchOpts = {
      query: typeof flags.query === "string" ? flags.query : "",
      hitsPerPage: hits,
      page: flags.page && typeof flags.page === "string" ? Math.max(0, parseInt(flags.page, 10)) : 0,
      contractType: typeof flags.contract === "string" ? flags.contract : undefined,
      remoteOnly: !!flags.remote,
      usOnly: !flags.worldwide,
      limit: flags.limit && typeof flags.limit === "string" ? parseInt(flags.limit, 10) : undefined,
      format: (["json", "table", "plain"].includes(fmt) ? fmt : "json") as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(
        JSON.stringify({ error: "detail requires a <reference|slug|url>", code: "NO_ID" }) + "\n",
      )
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

main().then((code) => process.exit(code))
