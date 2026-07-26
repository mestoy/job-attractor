import { algoliaSearch, toDetail, normalizeRef, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const ref = normalizeRef(opts.id)
  if (!ref) {
    writeError(`Could not parse a WTTJ job reference or slug from "${opts.id}"`, "BAD_ID")
    return 1
  }
  // A reference is a uuid; a slug is anything else. Filter the index by whichever
  // we have and take the single matching hit.
  const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(ref)
  const filters = [`${isUuid ? "reference" : "slug"}:${ref}`]

  try {
    const result = await algoliaSearch({ query: "", hitsPerPage: 1, page: 0, filters })
    const hit = result.hits[0]
    if (!hit) {
      writeError("Job not found", "NOT_FOUND")
      return 1
    }
    const job = toDetail(hit)

    if (opts.format === "plain") {
      const lines = [
        job.title,
        `${job.company || "—"} · ${job.location || "—"}`,
        "",
        job.contract_type ? `Contract: ${job.contract_type}` : "",
        job.remote ? `Remote: ${job.remote}` : "",
        job.experience ? `Experience: ${job.experience}` : "",
        job.salary ? `Salary: ${job.salary}` : "",
        job.date ? `Posted: ${job.date}` : "",
        "",
        job.description || "(no description in the index — open the URL for the full posting)",
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
