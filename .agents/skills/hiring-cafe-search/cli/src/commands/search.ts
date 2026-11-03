import {
  buildSearchUrl,
  htmlFetch,
  parseNextData,
  toResult,
  writeError,
  type JobResult,
  type WorkplaceFilter,
} from "../helpers.js"

export interface SearchOpts {
  query: string
  workplace: WorkplaceFilter
  page: number
  limit?: number
  format: "json" | "table" | "plain"
}

function renderTable(cards: JobResult[]): string {
  if (cards.length === 0) return "No results."
  const rows = cards.map((c) => {
    const title = (c.title || "").slice(0, 38).padEnd(38)
    const company = (c.company || "—").slice(0, 22).padEnd(22)
    const loc = (c.location || "—").slice(0, 24).padEnd(24)
    const wt = (c.workplaceType || "—").slice(0, 7).padEnd(7)
    const date = c.date || "—"
    return `${title} ${company} ${loc} ${wt} ${date}`
  })
  const header =
    "TITLE".padEnd(38) +
    " " +
    "COMPANY".padEnd(22) +
    " " +
    "LOCATION".padEnd(24) +
    " " +
    "TYPE".padEnd(7) +
    " DATE"
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const html = await htmlFetch(buildSearchUrl(opts.query, opts.workplace, opts.page))
    const pp = parseNextData(html)
    if (!pp) {
      writeError("Could not parse search results from the page", "NO_DATA")
      return 1
    }
    let cards = (pp.ssrHits ?? []).map(toResult)
    if (opts.limit !== undefined && opts.limit >= 0) cards = cards.slice(0, opts.limit)

    if (opts.format === "table") {
      process.stdout.write(renderTable(cards) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        cards
          .map(
            (c) =>
              `${c.title}\n  ${c.company || "—"} · ${c.location || "—"} · ${
                c.workplaceType || "—"
              }${c.salary ? ` · ${c.salary}` : ""} · ${c.date || "—"}\n  id: ${c.id}\n  ${c.url}`,
          )
          .join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify(
          {
            meta: {
              count: cards.length,
              page: pp.ssrPage ?? opts.page,
              totalCount: pp.ssrTotalCount,
              pageSize: pp.ssrPageSize,
              isLastPage: pp.ssrIsLastPage,
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
