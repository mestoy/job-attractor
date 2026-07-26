import { algoliaSearch, toResult, writeError, type JobResult } from "../helpers.js"

export interface SearchOpts {
  query: string
  hitsPerPage: number
  page: number
  contractType?: string // e.g. "full_time", "internship", "apprenticeship"
  remoteOnly: boolean
  usOnly: boolean
  limit?: number
  format: "json" | "table" | "plain"
}

function buildFilters(opts: SearchOpts): string[] {
  const filters: string[] = []
  if (opts.usOnly) filters.push("offices.country_code:US")
  if (opts.contractType) filters.push(`contract_type:${opts.contractType}`)
  if (opts.remoteOnly) filters.push("remote:fulltime")
  return filters
}

function renderTable(cards: JobResult[]): string {
  if (cards.length === 0) return "No results."
  const rows = cards.map((c) => {
    const title = (c.title || "").slice(0, 40).padEnd(40)
    const company = (c.company || "—").slice(0, 24).padEnd(24)
    const loc = (c.location || "—").slice(0, 22).padEnd(22)
    const date = c.date || "—"
    return `${title} ${company} ${loc} ${date}`
  })
  const header =
    "TITLE".padEnd(40) + " " + "COMPANY".padEnd(24) + " " + "LOCATION".padEnd(22) + " DATE"
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const result = await algoliaSearch({
      query: opts.query,
      hitsPerPage: opts.hitsPerPage,
      page: opts.page,
      filters: buildFilters(opts),
    })
    let cards = result.hits.map(toResult)
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)

    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards
          .map(
            (c) =>
              `${c.title}\n  ${c.company || "—"} · ${c.location || "—"} · ${c.contract_type || "—"}${
                c.remote ? ` · remote:${c.remote}` : ""
              } · ${c.date || "—"}\n  id: ${c.id}\n  ${c.url}`,
          )
          .join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify(
          {
            meta: {
              count: cards.length,
              page: result.page ?? opts.page,
              nbHits: result.nbHits,
              nbPages: result.nbPages,
            },
            results: cards,
          },
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
