import {
  SEARCH_URL,
  htmlFetch,
  parseSearchResults,
  writeError,
  type JobCard,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  jobage: number
  remote?: string // "remote" only (Built In supports a remote toggle)
  page: number
  limit?: number
  format: "json" | "table" | "plain"
}

function buildUrl(opts: SearchOpts): string {
  const params = new URLSearchParams()
  if (opts.query) params.set("search", opts.query)
  // Built In recency filter, in days.
  if (opts.jobage && opts.jobage > 0 && opts.jobage < 9999) {
    params.set("daysSinceUpdated", String(opts.jobage))
  }
  if ((opts.remote || "").toLowerCase() === "remote") params.set("remote", "true")
  if (opts.page > 1) params.set("page", String(opts.page))
  const qs = params.toString()
  return qs ? `${SEARCH_URL}?${qs}` : SEARCH_URL
}

function renderTable(cards: JobCard[]): string {
  if (cards.length === 0) return "No results."
  const rows = cards.map((c) => {
    const title = (c.title || "").slice(0, 44).padEnd(44)
    const company = (c.company || "—").slice(0, 26).padEnd(26)
    const date = c.date || "—"
    return `${c.id.padEnd(10)} ${title} ${company} ${date}`
  })
  const header =
    "ID".padEnd(10) + " " + "TITLE".padEnd(44) + " " + "COMPANY".padEnd(26) + " DATE"
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const html = await htmlFetch(buildUrl(opts))
    let cards = parseSearchResults(html)
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)

    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards
          .map(
            (c) =>
              `${c.title}\n  ${c.company || "—"} · ${c.date || "—"}\n  id: ${c.id}\n  ${c.url}${
                c.snippet ? `\n  ${c.snippet}` : ""
              }`,
          )
          .join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify(
          { meta: { count: cards.length, page: opts.page }, results: cards },
          null,
          2,
        ) + "\n",
      )
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
