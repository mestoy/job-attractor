// Data source: Best PM Jobs (bestpmjobs.com), a product-management-specific job
// board built on the JobBoardly platform. Search pages are server-rendered HTML
// job cards with no JSON-LD; each job's detail page embeds a full schema.org
// `JobPosting` (same pattern as builtin-search), which we parse instead of the
// visual markup for the detail command.
//
// No authentication and zero runtime dependencies — it runs with just `bun`.
// The site nags visitors with a "subscribe" popup/sticky-bar (marketing, not an
// access wall) - robots.txt allows all paths and job descriptions are fully
// present in the public HTML/JSON-LD without login.

export const SEARCH_URL = "https://www.bestpmjobs.com/jobs"
export const SITE_ORIGIN = "https://www.bestpmjobs.com"

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

/** Fetch HTML with exponential backoff on 429/5xx. Returns "" on a 404. */
export async function htmlFetch(url: string): Promise<string> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: {
        "User-Agent": UA,
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
      },
      redirect: "follow",
    })
    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) {
        throw new Error(`Request failed: ${response.status} ${response.statusText}`)
      }
      const jitter = Math.floor(Math.random() * 500)
      await new Promise((r) => setTimeout(r, delay + jitter))
      delay = Math.min(delay * 2, 8000)
      continue
    }
    if (response.status === 404) return ""
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    }
    return response.text()
  }
  throw new Error("Request failed after max retries")
}

export interface JobCard {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string
  employmentType: string | null
}

export interface JobDetail extends JobCard {
  description: string | null
  remote: string | null
  validThrough: string | null
  applyUrl: string | null
}

function numericEntity(cp: number): string {
  return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
}

function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, dec) => numericEntity(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, hex) => numericEntity(parseInt(hex, 16)))
    .replace(/&nbsp;/g, " ")
}

function stripTags(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()
}

function clean(html: string): string {
  return decodeHtmlEntities(stripTags(html))
}

/** Turn a JobPosting description's HTML into readable prose. */
export function cleanDescription(html: string | null | undefined): string | null {
  if (!html) return null
  const withBreaks = html
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\/(p|li|ul|ol|div|h\d)>/gi, "\n")
  const text = decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, " "))
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
  return text || null
}

const LD_SCRIPT_RE =
  /<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi

/** Collect every JSON-LD node, flattening any `@graph` wrappers. */
export function collectJsonLd(html: string): Record<string, unknown>[] {
  const nodes: Record<string, unknown>[] = []
  let m: RegExpExecArray | null
  while ((m = LD_SCRIPT_RE.exec(html)) !== null) {
    let data: unknown
    try {
      data = JSON.parse(m[1].trim())
    } catch {
      continue
    }
    const push = (d: unknown) => {
      if (d && typeof d === "object") nodes.push(d as Record<string, unknown>)
    }
    if (Array.isArray(data)) {
      data.forEach(push)
    } else if (data && typeof data === "object") {
      const graph = (data as Record<string, unknown>)["@graph"]
      if (Array.isArray(graph)) graph.forEach(push)
      else push(data)
    }
  }
  return nodes
}

/** The job slug (e.g. "product-manager-1fdc0d00") doubles as its `id`. */
export function idFromUrl(url: string): string | null {
  const m = url.match(/\/jobs\/([a-z0-9-]+)(?:\?|$)/i)
  return m ? m[1] : null
}

/**
 * Parse a search-results page's job cards. Each card is an `<a href="/jobs/<slug>">`
 * wrapping an `<h3>` title, a `<p>` company name, an employment-type badge, and a
 * location line. We split on card anchors and parse each chunk independently so one
 * malformed card cannot break the rest. No posting date is present on the list page
 * (see `detail` for `datePosted`).
 */
export function parseJobCards(html: string): JobCard[] {
  const results: JobCard[] = []
  const chunks = html.split(/<a class="block rounded-xl border"/).slice(1)

  for (const chunk of chunks) {
    const hrefMatch = chunk.match(/^[^>]*href="(\/jobs\/[a-z0-9-]+)"/i)
    if (!hrefMatch) continue
    const path = hrefMatch[1]
    const id = idFromUrl(path)
    if (!id) continue

    const h3 = chunk.match(/<h3[^>]*>([\s\S]*?)<\/h3>/i)
    const title = h3 ? clean(h3[1]) : ""
    if (!title) continue

    // Company name: the first <p> immediately following the </h3>.
    const afterTitle = h3 ? chunk.slice((h3.index ?? 0) + h3[0].length) : chunk
    const pMatch = afterTitle.match(/<p[^>]*>([\s\S]*?)<\/p>/i)
    const company = pMatch ? clean(pMatch[1]) || null : null

    const badge = chunk.match(/text-xs font-medium[^>]*>([\s\S]*?)<\/p>/i)
    const employmentType = badge ? clean(badge[1]) || null : null

    // Location: the <span class="truncate"> that follows the location pin SVG,
    // not the (optional, mobile-only) employment-type span that precedes it.
    const spans = [...chunk.matchAll(/<span class="truncate">([\s\S]*?)<\/span>/gi)].map(
      (m) => clean(m[1]),
    )
    const location = spans.find((s) => s && s !== employmentType) ?? null

    results.push({
      id,
      title,
      company,
      location: location || null,
      date: null,
      url: `${SITE_ORIGIN}${path}`,
      employmentType,
    })
  }

  return results
}

/** Assemble a human-readable location from the JobPosting's remote/country fields. */
function formatLocation(posting: Record<string, unknown>): string | null {
  const isRemote =
    typeof posting.jobLocationType === "string" &&
    posting.jobLocationType.toUpperCase() === "TELECOMMUTE"
  const req = posting.applicantLocationRequirements as
    | Record<string, unknown>
    | Record<string, unknown>[]
    | undefined
  const reqs = Array.isArray(req) ? req : req ? [req] : []
  const countries = reqs
    .map((r) => (typeof r.name === "string" ? r.name : null))
    .filter((n): n is string => !!n)

  if (isRemote) {
    return countries.length ? `Remote (${countries.join(", ")})` : "Remote"
  }

  const loc = posting.jobLocation as
    | Record<string, unknown>
    | Record<string, unknown>[]
    | undefined
  const firstLoc = Array.isArray(loc) ? loc[0] : loc
  const addr = firstLoc?.address as Record<string, unknown> | undefined
  if (addr) {
    const parts = [addr.addressLocality, addr.addressRegion, addr.addressCountry].filter(
      (p): p is string => typeof p === "string" && p.trim() !== "",
    )
    if (parts.length) return parts.join(", ")
  }
  return countries.length ? countries.join(", ") : null
}

/** Parse a job detail page from its schema.org `JobPosting` JSON-LD. */
export function parseJobDetail(html: string, id: string, url: string): JobDetail | null {
  const posting = collectJsonLd(html).find((n) => n["@type"] === "JobPosting")
  if (!posting) return null

  const org = posting.hiringOrganization as Record<string, unknown> | undefined
  const company = org && typeof org.name === "string" ? org.name : null

  const isRemote =
    typeof posting.jobLocationType === "string" &&
    posting.jobLocationType.toUpperCase() === "TELECOMMUTE"

  // Prefer the site's own apply-tracking link (data-action="click->job#onApply")
  // over posting.url, which just points back at this same detail page.
  const applyMatch = html.match(/id="apply-btn"[^>]*href="([^"]+)"/i)
  const applyUrl = applyMatch ? decodeHtmlEntities(applyMatch[1]) : null

  return {
    id,
    title: typeof posting.title === "string" ? posting.title.trim() : "(untitled)",
    company,
    location: formatLocation(posting),
    date: typeof posting.datePosted === "string" ? posting.datePosted : null,
    url: url.split("?")[0],
    employmentType:
      typeof posting.employmentType === "string" ? posting.employmentType : null,
    description: cleanDescription(
      typeof posting.description === "string" ? posting.description : null,
    ),
    remote: isRemote ? "Remote" : null,
    validThrough: typeof posting.validThrough === "string" ? posting.validThrough : null,
    applyUrl,
  }
}
