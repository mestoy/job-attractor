import { detailUrl, htmlFetch, parseNextData, toDetail, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const url = detailUrl(opts.id)
  if (!url) {
    writeError(`Could not parse a Hiring Cafe job id or URL from "${opts.id}"`, "BAD_ID")
    return 1
  }
  try {
    const html = await htmlFetch(url)
    if (!html) {
      writeError("Job not found", "NOT_FOUND")
      return 1
    }
    const pp = parseNextData(html)
    const hit = pp?.ssrHits?.[0]
    if (!hit) {
      writeError("No job data found on the page", "NO_DATA")
      return 1
    }
    const job = toDetail(hit)

    if (opts.format === "plain") {
      const lines = [
        job.title,
        `${job.company || "—"} · ${job.location || "—"}${
          job.workplaceType ? ` · ${job.workplaceType}` : ""
        }`,
        "",
        job.seniority ? `Seniority: ${job.seniority}` : "",
        job.commitment ? `Commitment: ${job.commitment}` : "",
        job.minYearsExperience != null ? `Min experience: ${job.minYearsExperience} yrs` : "",
        job.salary ? `Salary: ${job.salary}` : "",
        job.jobCategory ? `Category: ${job.jobCategory}` : "",
        job.companyIndustries.length ? `Industries: ${job.companyIndustries.join(", ")}` : "",
        job.companySize != null ? `Company size: ${job.companySize}` : "",
        job.date ? `Posted: ${job.date}` : "",
        "",
        job.description || "(no structured description — open the apply URL for the full posting)",
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
