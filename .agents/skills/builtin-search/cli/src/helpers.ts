// Data source: Built In (builtin.com), a US tech-job board. Search pages are
// server-rendered HTML that embeds a schema.org `ItemList` (JSON-LD) of the jobs
// on the page; each job's detail page embeds a full schema.org `JobPosting`.
// We parse the JSON-LD (stable, well-specified) rather than the visual markup,
// and enrich search rows with the company name from the card HTML.
//
// No authentication and zero runtime dependencies — it runs with just `bun`.
// Built In publishes US roles nationally (plus remote); precise per-job location
// comes from the `detail` command's JobPosting.

export const SEARCH_URL = "https://builtin.com/jobs"
export const SITE_ORIGIN = "https://builtin.com"

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
  snippet: string | null
}

export interface JobDetail extends JobCard {
  description: string | null
  employmentType: string | null
  remote: string | null
  salary: string | null
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

/**
 * Turn a JobPosting description's HTML into readable prose: block/line-break
 * tags become newlines, entities are decoded, tags removed. Null for empty.
 */
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

/** The `+` in the ld+json script `type` is HTML-entity-encoded on builtin.com. */
const LD_SCRIPT_RE =
  /<script[^>]*type="application\/ld[^"]*json"[^>]*>([\s\S]*?)<\/script>/gi

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

/** The Built In job ID is the last path segment of a `/job/<slug>/<id>` URL. */
export function idFromUrl(url: string): string | null {
  const m = url.match(/\/job\/[^/]+\/(\d+)/) || url.match(/(\d{5,})\/?$/)
  return m ? m[1] : null
}

/**
 * Parse a search-results page. The `ItemList` JSON-LD gives title, url and a
 * description snippet per job; we map the company name in from the visual card
 * (keyed by `data-builtin-track-job-id`). Location is absent on the list page
 * and left null — `detail` fills it from the JobPosting.
 */
export function parseSearchResults(html: string): JobCard[] {
  const companyById = parseCompanyMap(html)
  const results: JobCard[] = []
  const seen = new Set<string>()

  for (const node of collectJsonLd(html)) {
    if (node["@type"] !== "ItemList") continue
    const items = node["itemListElement"]
    if (!Array.isArray(items)) continue
    for (const raw of items) {
      const item = raw as Record<string, unknown>
      const url = typeof item.url === "string" ? item.url : ""
      const id = url ? idFromUrl(url) : null
      if (!id || seen.has(id)) continue
      const title = typeof item.name === "string" ? item.name.trim() : ""
      if (!title) continue
      seen.add(id)
      const snippet =
        typeof item.description === "string" && item.description.trim()
          ? item.description.trim()
          : null
      results.push({
        id,
        title,
        company: companyById.get(id) ?? null,
        location: null,
        date: null,
        url: url.split("?")[0],
        snippet,
      })
    }
  }
  return results
}

/** Map job ID -> company name from the search-page card anchors. */
function parseCompanyMap(html: string): Map<string, string> {
  const map = new Map<string, string>()
  const re =
    /data-id="company-title"[^>]*data-builtin-track-job-id="(\d+)"[^>]*>\s*<span>([^<]*)<\/span>/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    const name = decodeHtmlEntities(m[2]).trim()
    if (name) map.set(m[1], name)
  }
  return map
}

/** Assemble a human-readable location from a schema.org PostalAddress. */
function formatAddress(addr: Record<string, unknown> | undefined): string | null {
  if (!addr) return null
  const parts = [addr.addressLocality, addr.addressRegion, addr.addressCountry]
    .filter((p): p is string => typeof p === "string" && p.trim() !== "")
  return parts.length ? parts.join(", ") : null
}

/** Human-readable salary line from a schema.org MonetaryAmount, or null. */
function formatSalary(base: Record<string, unknown> | undefined): string | null {
  if (!base) return null
  const value = base.value as Record<string, unknown> | undefined
  if (!value) return null
  const cur = typeof base.currency === "string" ? base.currency : ""
  const min = value.minValue
  const max = value.maxValue
  const single = value.value
  const unit =
    typeof value.unitText === "string" ? ` / ${value.unitText.toLowerCase()}` : ""
  const num = (n: unknown) =>
    typeof n === "number" ? n.toLocaleString("en-US") : String(n)
  if (min != null && max != null) return `${cur} ${num(min)}–${num(max)}${unit}`.trim()
  if (min != null || max != null) return `${cur} ${num(min ?? max)}${unit}`.trim()
  if (single != null) return `${cur} ${num(single)}${unit}`.trim()
  return null
}

/** Parse a job detail page from its schema.org `JobPosting` JSON-LD. */
export function parseJobDetail(html: string, id: string, url: string): JobDetail | null {
  const posting = collectJsonLd(html).find((n) => n["@type"] === "JobPosting")
  if (!posting) return null

  const org = posting.hiringOrganization as Record<string, unknown> | undefined
  const company = org && typeof org.name === "string" ? org.name : null

  const loc = posting.jobLocation as
    | Record<string, unknown>
    | Record<string, unknown>[]
    | undefined
  const firstLoc = Array.isArray(loc) ? loc[0] : loc
  const location = formatAddress(firstLoc?.address as Record<string, unknown> | undefined)

  const remote =
    typeof posting.jobLocationType === "string" &&
    posting.jobLocationType.toUpperCase() === "TELECOMMUTE"
      ? "Remote"
      : null

  return {
    id,
    title: typeof posting.title === "string" ? posting.title.trim() : "(untitled)",
    company,
    location,
    date: typeof posting.datePosted === "string" ? posting.datePosted : null,
    url: url.split("?")[0],
    snippet: null,
    description: cleanDescription(
      typeof posting.description === "string" ? posting.description : null,
    ),
    employmentType:
      typeof posting.employmentType === "string" ? posting.employmentType : null,
    remote,
    salary: formatSalary(posting.baseSalary as Record<string, unknown> | undefined),
    validThrough:
      typeof posting.validThrough === "string" ? posting.validThrough : null,
    applyUrl: typeof posting.url === "string" ? posting.url : url.split("?")[0],
  }
}
