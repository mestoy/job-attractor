import { SITE_ORIGIN, htmlFetch, parseJobDetail, idFromUrl, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

/** Accept a raw slug (e.g. "product-manager-1fdc0d00") or a full job URL. */
function normalizeUrl(input: string): string | null {
  const trimmed = input.trim()
  const full = trimmed.match(/https?:\/\/[^\s]*\/jobs\/[a-z0-9-]+/i)
  if (full) return full[0].split("?")[0]
  if (/^[a-z0-9-]+$/i.test(trimmed)) return `${SITE_ORIGIN}/jobs/${trimmed}`
  return null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const url = normalizeUrl(opts.id)
  if (!url) {
    writeError(`Could not parse a Best PM Jobs slug or URL from "${opts.id}"`, "BAD_ID")
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
        `${job.company || "—"} · ${job.location || "—"}`,
        "",
        job.employmentType ? `Employment: ${job.employmentType}` : "",
        job.date ? `Posted: ${job.date}` : "",
        job.validThrough ? `Closes: ${job.validThrough}` : "",
        "",
        job.description || "(no description)",
        "",
        `URL: ${job.url}`,
        job.applyUrl ? `Apply: ${job.applyUrl}` : "",
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
