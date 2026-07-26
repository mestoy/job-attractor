#!/usr/bin/env bun
// Self-contained CLI for searching US tech jobs on Built In (builtin.com).
// No external CLI framework, so it runs anywhere `bun` is available with zero
// install beyond the repo clone.
//
// Personal use only. This reads Built In's public job pages; keep volume low and
// do not use it commercially or for bulk data collection. Run it on your own
// responsibility.

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

const HELP = `builtin-cli — search US tech jobs on Built In (builtin.com)

USAGE
  bun run src/cli.ts search [--query "<terms>"] [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill, or role). Recommended.
  --jobage <days>         Posted/updated within N days (e.g. 1, 7, 14, 30). Default: all.
  --remote                Only remote-eligible roles.
  --page <n>              1-indexed page (25 results/page). Default 1.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

NOTES
  Built In lists US roles nationally (plus remote); precise per-job location comes
  from the 'detail' command's JobPosting. Filter by city downstream in fit review.

EXAMPLES
  bun run src/cli.ts search -q "data engineer" --jobage 14 --format table
  bun run src/cli.ts search -q "product manager" --remote --format table
  bun run src/cli.ts detail 10122783 --format plain
  bun run src/cli.ts detail https://builtin.com/job/principal-data-engineer-remote/10122783 --format plain

Personal use only — uses Built In's public pages; keep volume low.
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

    for (const name of ["jobage", "page", "limit"] as const) {
      if (flags[name] !== undefined && typeof flags[name] !== "boolean") {
        const v = parseIntFlag(name, flags[name])
        if (v === null) return 1
        flags[name] = String(v)
      }
    }

    const opts: SearchOpts = {
      query: typeof flags.query === "string" ? flags.query : undefined,
      jobage: flags.jobage && typeof flags.jobage === "string" ? parseInt(flags.jobage, 10) : 9999,
      remote: flags.remote ? "remote" : undefined,
      page: flags.page && typeof flags.page === "string" ? Math.max(1, parseInt(flags.page, 10)) : 1,
      limit: flags.limit && typeof flags.limit === "string" ? parseInt(flags.limit, 10) : undefined,
      format: (["json", "table", "plain"].includes(fmt) ? fmt : "json") as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(JSON.stringify({ error: "detail requires an <id|url>", code: "NO_ID" }) + "\n")
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
