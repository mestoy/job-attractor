// Data source: Welcome to the Jungle's public Algolia jobs index
// (`wk_cms_jobs_production`, app `CSEKHVMS53`). This is the same backend the
// welcometothejungle.com job search UI queries. Reads are unauthenticated beyond
// a public, search-only Algolia key — unlike an HTML scrape there is no markup to
// parse: we POST an Algolia query and reshape the JSON hits into the portal-skill
// contract's result fields.
//
// US roles are selected with `filters=offices.country_code:US`.
//
// ── The Algolia search key ──────────────────────────────────────────────────
// WTTJ rotates the public search key periodically. Override it with the
// WTTJ_ALGOLIA_KEY env var. If searches start returning 403 "Invalid
// Application-ID or API key", grab the current key from a browser: open
// welcometothejungle.com, search jobs, and in the Network tab copy the
// `x-algolia-api-key` header (or the `?x-algolia-api-key=` param) from any
// request to `csekhvms53-dsn.algolia.net`, then export it:
//   export WTTJ_ALGOLIA_KEY=<key>

export const ALGOLIA_APP_ID = "CSEKHVMS53"
export const ALGOLIA_HOST = "https://csekhvms53-dsn.algolia.net"
export const JOBS_INDEX = "wk_cms_jobs_production"

// Last-known public search key. Overridable via WTTJ_ALGOLIA_KEY (see note above).
const DEFAULT_ALGOLIA_KEY = "4bd8f6215d0cc52b26430765769e65a0"

export function algoliaKey(): string {
  return (process.env.WTTJ_ALGOLIA_KEY || "").trim() || DEFAULT_ALGOLIA_KEY
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "wttj-search-skill/1.0 (+https://www.welcometothejungle.com)"

export interface AlgoliaParams {
  query: string
  hitsPerPage: number
  page: number
  filters: string[]
}

/** Build the Algolia `params` querystring for one index query. */
function buildParams(p: AlgoliaParams): string {
  const parts = [
    `query=${encodeURIComponent(p.query)}`,
    `hitsPerPage=${p.hitsPerPage}`,
    `page=${p.page}`,
  ]
  if (p.filters.length) {
    parts.push(`filters=${encodeURIComponent(p.filters.join(" AND "))}`)
  }
  return parts.join("&")
}

interface AlgoliaResult {
  hits: WttjHit[]
  nbHits?: number
  nbPages?: number
  page?: number
}

/**
 * POST a single-index Algolia query. Retries 429/5xx with backoff. A 403 is
 * surfaced with an actionable message (the public key likely rotated).
 */
export async function algoliaSearch(p: AlgoliaParams): Promise<AlgoliaResult> {
  const url =
    `${ALGOLIA_HOST}/1/indexes/*/queries` +
    `?x-algolia-agent=${encodeURIComponent("Welcome to the Jungle job-search skill")}`
  const body = JSON.stringify({
    requests: [{ indexName: JOBS_INDEX, params: buildParams(p) }],
  })

  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    let response: Response
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          "User-Agent": UA,
          "Content-Type": "application/x-www-form-urlencoded",
          "x-algolia-application-id": ALGOLIA_APP_ID,
          "x-algolia-api-key": algoliaKey(),
        },
        body,
      })
    } catch (e) {
      throw new Error(
        `could not reach the WTTJ Algolia API (${e instanceof Error ? e.message : String(e)})`,
      )
    }

    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) {
        throw new Error(`WTTJ search failed: ${response.status} ${response.statusText}`)
      }
      await new Promise((r) => setTimeout(r, delay + Math.floor(Math.random() * 500)))
      delay = Math.min(delay * 2, 8000)
      continue
    }
    if (response.status === 403) {
      throw new Error(
        "WTTJ Algolia rejected the key (403). The public search key likely rotated — " +
          "set WTTJ_ALGOLIA_KEY to a current key (see the note in helpers.ts).",
      )
    }
    if (!response.ok) {
      throw new Error(`WTTJ search failed: ${response.status} ${response.statusText}`)
    }
    const json = (await response.json().catch(() => null)) as
      | { results?: AlgoliaResult[] }
      | null
    const result = json?.results?.[0]
    if (!result) throw new Error("WTTJ search returned an unexpected response body")
    return result
  }
  throw new Error("WTTJ search failed after retries")
}

/** The WTTJ job fields this skill reads (the wire shape carries more). */
export interface WttjHit {
  name?: string
  slug?: string
  reference?: string
  contract_type?: string
  remote?: string
  published_at?: number | string
  published_at_date?: string
  salary_min?: number
  salary_max?: number
  salary_currency?: string
  salary_period?: string
  experience_level_minimum?: number
  language?: string
  description?: string
  profile?: string
  organization?: { name?: string; slug?: string; reference?: string }
  offices?: Array<{
    city?: string
    state?: string
    country?: string
    country_code?: string
  }>
  [k: string]: unknown
}

export interface JobResult {
  id: string // the WTTJ reference (uuid) — what `detail` consumes
  title: string
  company: string | null
  company_slug: string | null
  location: string | null
  contract_type: string | null
  remote: string | null
  date: string | null
  url: string
}

export interface JobDetailResult extends JobResult {
  salary: string | null
  experience: string | null
  language: string | null
  description: string | null
}

/** Canonical job URL from the org + job slugs (falls back to a search deep-link). */
export function jobUrl(hit: WttjHit): string {
  const org = hit.organization?.slug
  if (org && hit.slug) {
    return `https://www.welcometothejungle.com/en/companies/${org}/jobs/${hit.slug}`
  }
  return "https://www.welcometothejungle.com/en/jobs"
}

/** First office formatted as "City, State" / "City, COUNTRY", or null. */
function formatOffice(hit: WttjHit): string | null {
  const o = hit.offices?.[0]
  if (!o) return null
  const parts = [o.city, o.state || o.country_code || o.country].filter(
    (p): p is string => typeof p === "string" && p.trim() !== "",
  )
  return parts.length ? parts.join(", ") : null
}

/** Posting date as an ISO date (YYYY-MM-DD), from whichever field is present. */
function postedDate(hit: WttjHit): string | null {
  if (typeof hit.published_at_date === "string") return hit.published_at_date.slice(0, 10)
  if (typeof hit.published_at === "string") return hit.published_at.slice(0, 10)
  if (typeof hit.published_at === "number") {
    // Algolia stores this as a unix timestamp (seconds).
    const ms = hit.published_at < 1e12 ? hit.published_at * 1000 : hit.published_at
    return new Date(ms).toISOString().slice(0, 10)
  }
  return null
}

/** Reshape an Algolia hit into the contract search-result fields. */
export function toResult(hit: WttjHit): JobResult {
  return {
    id: hit.reference || hit.slug || "",
    title: hit.name || "(untitled)",
    company: hit.organization?.name || null,
    company_slug: hit.organization?.slug || null,
    location: formatOffice(hit),
    contract_type: hit.contract_type || null,
    remote: hit.remote && hit.remote !== "no" ? hit.remote : null,
    date: postedDate(hit),
    url: jobUrl(hit),
  }
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

/** Strip a WTTJ description's HTML into readable prose. Null for empty input. */
export function cleanHtml(html: string | null | undefined): string | null {
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

/** Human-readable salary line, or null when absent. */
function formatSalary(hit: WttjHit): string | null {
  if (hit.salary_min == null && hit.salary_max == null) return null
  const cur = hit.salary_currency ? `${hit.salary_currency} ` : ""
  const per = hit.salary_period ? ` / ${hit.salary_period.toLowerCase()}` : ""
  const num = (n: number) => n.toLocaleString("en-US")
  if (hit.salary_min != null && hit.salary_max != null) {
    return `${cur}${num(hit.salary_min)}–${num(hit.salary_max)}${per}`
  }
  return `${cur}${num((hit.salary_min ?? hit.salary_max) as number)}${per}`
}

/** Reshape an Algolia hit into a full detail result. */
export function toDetail(hit: WttjHit): JobDetailResult {
  const desc = cleanHtml(hit.description) || cleanHtml(hit.profile)
  return {
    ...toResult(hit),
    salary: formatSalary(hit),
    experience:
      typeof hit.experience_level_minimum === "number"
        ? `${hit.experience_level_minimum}+ years`
        : null,
    language: hit.language || null,
    description: desc,
  }
}

/** Extract a WTTJ reference (uuid) or slug from a raw value or a job URL. */
export function normalizeRef(input: string): string | null {
  const trimmed = input.trim()
  if (!trimmed) return null
  // A UUID reference.
  const uuid = trimmed.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i)
  if (uuid) return uuid[0]
  // A job URL: .../jobs/<slug>
  const url = trimmed.match(/\/jobs\/([^/?#]+)/)
  if (url) return url[1]
  // A bare slug.
  if (/^[a-z0-9][a-z0-9-]*$/i.test(trimmed)) return trimmed
  return null
}
