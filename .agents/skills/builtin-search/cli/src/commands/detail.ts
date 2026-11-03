import {
  SITE_ORIGIN,
  htmlFetch,
  parseJobDetail,
  idFromUrl,
  writeError,
} from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

/** True for a bare numeric job ID with no URL or path around it. */
export function isBareId(input: string): boolean {
  return /^\d{4,}$/.test(input.trim())
}

/** Accept a full `/job/<slug>/<id>` URL (or that path alone) and rebuild a fetch URL.
 *
 * kit#171: a bare numeric ID used to build `${SITE_ORIGIN}/job/x/<id>`, on the assumption
 * that Built In redirects that placeholder-slug form to the canonical page. Verified live: it
 * doesn't -- `/job/x/<id>` 404s outright, while the real `/job/<slug>/<id>` URL returns 200.
 * There is no other Built In endpoint that resolves a bare ID to its slug without another
 * fetch, so a bare ID is now refused with a clear pointer to the URL `search` already prints,
 * rather than silently building a URL that can never resolve.
 */
function normalizeUrl(input: string): string | null {
  const trimmed = input.trim()
  // A full Built In job URL.
  const full = trimmed.match(/https?:\/\/[^\s]*\/job\/[^/]+\/\d+/)
  if (full) return full[0].split("?")[0]
  // A path fragment like /job/<slug>/<id>.
  if (idFromUrl(trimmed)) return `${SITE_ORIGIN}${trimmed.startsWith("/") ? "" : "/"}${trimmed}`
  return null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  if (isBareId(opts.id)) {
    writeError(
      `A bare job ID ("${opts.id.trim()}") can't be resolved to a Built In URL on its own. ` +
        `Pass the full job URL instead -- "search" prints one per result.`,
      "BAD_ID",
    )
    return 1
  }
  const url = normalizeUrl(opts.id)
  if (!url) {
    writeError(`Could not parse a Built In job URL from "${opts.id}"`, "BAD_ID")
    return 1
  }
  const id = idFromUrl(url) ?? opts.id.trim()
  try {
    const html = await htmlFetch(url)
    if (!html) {
      writeError("Job not found", "NOT_FOUND")
      return 1
    }
    const job = parseJobDetail(html, id, url)
    if (!job) {
      writeError("No JobPosting data found on the page", "NO_DATA")
      return 1
    }

    if (opts.format === "plain") {
      const lines = [
        job.title,
        `${job.company || "—"} · ${job.location || "—"}${job.remote ? " · Remote" : ""}`,
        "",
        job.employmentType ? `Employment: ${job.employmentType}` : "",
        job.salary ? `Salary: ${job.salary}` : "",
        job.date ? `Posted: ${job.date}` : "",
        job.validThrough ? `Closes: ${job.validThrough}` : "",
        "",
        job.description || "(no description)",
        "",
        `URL: ${job.url}`,
      ].filter((l) => l !== "")
      process.stdout.write(lines.join("\n") + "\n")
    } else {
      process.stdout.write(JSON.stringify(job, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "DETAIL_FAILED")
    return 1
  }
}
