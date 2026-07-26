// Data source: Hiring Cafe (hiring.cafe), a US-focused job aggregator that pulls
// postings from company ATSes (Greenhouse, iCIMS, Lever, Ashby, …). The search
// page server-renders its results into the Next.js `__NEXT_DATA__` payload as
// `pageProps.ssrHits` — structured, no auth, no API key. We drive the search
// through the `searchState` URL parameter and parse the SSR JSON.
//
// A search is `https://hiring.cafe/?searchState=<url-encoded JSON>&page=<n>`.
// A single job is `https://hiring.cafe/jobs/<id>` (same ssrHits shape, one hit).
//
// No authentication and zero runtime dependencies — it runs with just `bun`.
// Hiring Cafe is US-centric; precise per-city filtering is left to the fit review
// (search is national + an optional remote/hybrid/onsite workplace filter).

export const SITE_ORIGIN = "https://hiring.cafe"
export const PAGE_SIZE = 40 // Hiring Cafe returns 40 hits per page.

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

export interface WorkplaceFilter {
  remote?: boolean
  hybrid?: boolean
  onsite?: boolean
}

/** Build a Hiring Cafe search URL from a keyword, workplace filter, and page. */
export function buildSearchUrl(
  query: string,
  workplace: WorkplaceFilter,
  page: number,
): string {
  const searchState: Record<string, unknown> = {}
  if (query) searchState.searchQuery = query
  const types: string[] = []
  if (workplace.remote) types.push("Remote")
  if (workplace.hybrid) types.push("Hybrid")
  if (workplace.onsite) types.push("Onsite")
  if (types.length) searchState.workplaceTypes = types

  const params = new URLSearchParams()
  params.set("searchState", JSON.stringify(searchState))
  if (page > 0) params.set("page", String(page))
  return `${SITE_ORIGIN}/?${params.toString()}`
}

/** Canonical Hiring Cafe job URL. The site collapses `_` runs to single dashes. */
export function jobUrlFromId(id: string): string {
  return `${SITE_ORIGIN}/jobs/${id.replace(/_+/g, "-")}`
}

export interface SsrPageProps {
  ssrHits?: RawHit[]
  ssrPage?: number
  ssrTotalCount?: number
  ssrPageSize?: number
  ssrIsLastPage?: boolean
}

interface RawHit {
  id?: string
  apply_url?: string
  source?: string
  board_token?: string
  job_information?: { title?: string; job_title_raw?: string }
  v5_processed_job_data?: Record<string, unknown>
  enriched_company_data?: Record<string, unknown>
}

/** Extract `pageProps` from a page's Next.js `__NEXT_DATA__` script. */
export function parseNextData(html: string): SsrPageProps | null {
  const m = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/)
  if (!m) return null
  let data: unknown
  try {
    data = JSON.parse(m[1])
  } catch {
    return null
  }
  const pp = (data as { props?: { pageProps?: SsrPageProps } })?.props?.pageProps
  return pp ?? null
}

export interface JobResult {
  id: string
  title: string
  company: string | null
  location: string | null
  workplaceType: string | null
  date: string | null
  salary: string | null
  url: string
  applyUrl: string | null
}

export interface JobDetail extends JobResult {
  seniority: string | null
  commitment: string | null
  minYearsExperience: number | null
  technicalTools: string[]
  jobCategory: string | null
  companyIndustries: string[]
  companySize: number | null
  description: string | null
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v.trim() : null
}

function strArray(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []
}

/** ISO date (YYYY-MM-DD) from Hiring Cafe's estimated_publish_date, or null. */
function isoDate(v: unknown): string | null {
  const s = str(v)
  return s ? s.slice(0, 10) : null
}

/** Human-readable yearly salary from the v5 compensation fields, or null. */
function formatSalary(v5: Record<string, unknown>): string | null {
  const min = v5.yearly_min_compensation
  const max = v5.yearly_max_compensation
  const num = (n: unknown) => (typeof n === "number" ? `$${n.toLocaleString("en-US")}` : "")
  if (typeof min === "number" && typeof max === "number") return `${num(min)}–${num(max)} / yr`
  if (typeof min === "number" || typeof max === "number")
    return `${num(typeof min === "number" ? min : max)} / yr`
  return null
}

/** Reshape a raw SSR hit into the contract search-result fields. */
export function toResult(hit: RawHit): JobResult {
  const v5 = hit.v5_processed_job_data ?? {}
  const ec = hit.enriched_company_data ?? {}
  const id = hit.id ?? ""
  return {
    id,
    title: str(hit.job_information?.title) ?? str(v5.core_job_title) ?? "(untitled)",
    company: str(v5.company_name) ?? str(ec.name),
    location: str(v5.formatted_workplace_location),
    workplaceType: str(v5.workplace_type),
    date: isoDate(v5.estimated_publish_date),
    salary: formatSalary(v5),
    url: id ? jobUrlFromId(id) : SITE_ORIGIN,
    applyUrl: str(hit.apply_url),
  }
}

/** Reshape a raw SSR hit into a full detail result with an assembled description. */
export function toDetail(hit: RawHit): JobDetail {
  const v5 = hit.v5_processed_job_data ?? {}
  const ec = hit.enriched_company_data ?? {}
  const commitment = strArray(v5.commitment)
  const tools = strArray(v5.technical_tools)
  const activities = strArray(v5.role_activities)

  const descParts: string[] = []
  const reqs = str(v5.requirements_summary)
  if (reqs) descParts.push(`Requirements: ${reqs}`)
  if (activities.length) descParts.push("Role activities:\n- " + activities.join("\n- "))
  if (tools.length) descParts.push("Tools: " + tools.join(", "))

  const minYoe = v5.min_industry_and_role_yoe
  return {
    ...toResult(hit),
    seniority: str(v5.seniority_level),
    commitment: commitment.length ? commitment.join(", ") : null,
    minYearsExperience: typeof minYoe === "number" ? minYoe : null,
    technicalTools: tools,
    jobCategory: str(v5.job_category),
    companyIndustries: strArray(ec.industries),
    companySize: typeof ec.nb_employees === "number" ? ec.nb_employees : null,
    description: descParts.length ? descParts.join("\n\n") : null,
  }
}

/** Accept a raw Hiring Cafe job id or a `/jobs/<id>` URL, and return a fetch URL. */
export function detailUrl(input: string): string | null {
  const trimmed = input.trim()
  if (!trimmed) return null
  const m = trimmed.match(/\/jobs\/([^/?#]+)/)
  if (m) return `${SITE_ORIGIN}/jobs/${m[1]}`
  // A raw id (with ___ or - separators). The site normalizes _ runs to - on fetch.
  if (/^[a-z0-9]+([_-]+[a-z0-9]+)+$/i.test(trimmed)) return `${SITE_ORIGIN}/jobs/${trimmed}`
  return null
}
