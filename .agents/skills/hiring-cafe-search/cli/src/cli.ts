#!/usr/bin/env bun
// Self-contained CLI for searching US jobs on Hiring Cafe (hiring.cafe), a job
// aggregator that indexes company ATS postings. No external CLI framework, so it
// runs anywhere `bun` is available with zero install beyond the repo clone.
//
// Personal use only. This reads Hiring Cafe's public server-rendered search data;
// keep volume low and do not use it commercially or for bulk data collection.

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

const HELP = `hiring-cafe-cli — search US jobs on Hiring Cafe (hiring.cafe)

USAGE
  bun run src/cli.ts search [--query "<terms>"] [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill, or role). Recommended.
  --workplace <mode>      remote | hybrid | onsite (repeatable via comma, e.g. remote,hybrid).
  --remote                Shorthand for --workplace remote.
  --page <n>              0-indexed page (40 results/page). Default 0.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

NOTES
  Hiring Cafe aggregates US postings from company ATSes. Search is national; filter
  by city downstream in the fit review. Results carry company, location, workplace
  type, salary range, and seniority.

EXAMPLES
  bun run src/cli.ts search -q "data engineer" --format table
  bun run src/cli.ts search -q "product manager" --remote --format table
  bun run src/cli.ts search -q "nurse" --workplace onsite --page 1 --format table
  bun run src/cli.ts detail icims2___careers-sonalysts___2442 --format plain

Personal use only — uses Hiring Cafe's public pages; keep volume low.
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

    for (const name of ["page", "limit"] as const) {
      if (flags[name] !== undefined && typeof flags[name] !== "boolean") {
        const v = parseIntFlag(name, flags[name])
        if (v === null) return 1
        flags[name] = String(v)
      }
    }

    const modes = new Set<string>()
    if (flags.remote) modes.add("remote")
    if (typeof flags.workplace === "string") {
      flags.workplace.split(",").forEach((m) => modes.add(m.trim().toLowerCase()))
    }

    const opts: SearchOpts = {
      query: typeof flags.query === "string" ? flags.query : "",
      workplace: {
        remote: modes.has("remote"),
        hybrid: modes.has("hybrid"),
        onsite: modes.has("onsite") || modes.has("on-site"),
      },
      page: flags.page && typeof flags.page === "string" ? Math.max(0, parseInt(flags.page, 10)) : 0,
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
