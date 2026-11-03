import { describe, test, expect } from "bun:test"
import {
  parseSearchResults,
  parseJobDetail,
  collectJsonLd,
  idFromUrl,
  cleanDescription,
} from "../src/helpers"
import { isBareId } from "../src/commands/detail"

// The `+` in the ld+json script `type` is entity-encoded (application/ld&#x2B;json)
// on builtin.com, and the payload is wrapped in an @graph. Both are exercised here.
function searchPage(
  jobs: { id: string; title: string; company: string; snippet?: string }[],
): string {
  const items = jobs.map((j, i) => ({
    "@type": "ListItem",
    position: i + 1,
    name: j.title,
    url: `https://builtin.com/job/${j.title.toLowerCase().replace(/\s+/g, "-")}/${j.id}`,
    description: j.snippet ?? "",
  }))
  const ld = JSON.stringify({
    "@context": "https://schema.org",
    "@graph": [{ "@type": "ItemList", itemListElement: items }],
  })
  const cards = jobs
    .map(
      (j) =>
        `<a data-id="company-title" data-builtin-track-job-id="${j.id}" class="x"><span>${j.company}</span></a>`,
    )
    .join("\n")
  return `<html><body>${cards}
    <script type="application/ld&#x2B;json">${ld}</script></body></html>`
}

describe("collectJsonLd", () => {
  test("unwraps @graph and decodes the entity-encoded script type", () => {
    const html = searchPage([{ id: "111", title: "Data Engineer", company: "Acme" }])
    const nodes = collectJsonLd(html)
    expect(nodes.some((n) => n["@type"] === "ItemList")).toBe(true)
  })
})

describe("idFromUrl", () => {
  test("extracts the trailing numeric id from a /job/<slug>/<id> URL", () => {
    expect(idFromUrl("https://builtin.com/job/principal-data-engineer/10122783")).toBe("10122783")
  })
  test("returns null when there is no id", () => {
    expect(idFromUrl("https://builtin.com/jobs")).toBeNull()
  })
})

describe("parseSearchResults", () => {
  test("maps ItemList entries to job cards with company enrichment", () => {
    const html = searchPage([
      { id: "111", title: "Data Engineer", company: "Acme", snippet: "Build pipelines" },
      { id: "222", title: "Product Manager", company: "Globex" },
    ])
    const cards = parseSearchResults(html)
    expect(cards).toHaveLength(2)
    expect(cards[0]).toMatchObject({
      id: "111",
      title: "Data Engineer",
      company: "Acme",
      snippet: "Build pipelines",
    })
    expect(cards[1].company).toBe("Globex")
  })

  test("deduplicates repeated ids", () => {
    const html = searchPage([
      { id: "111", title: "Data Engineer", company: "Acme" },
      { id: "111", title: "Data Engineer", company: "Acme" },
    ])
    expect(parseSearchResults(html)).toHaveLength(1)
  })
})

describe("parseJobDetail", () => {
  const detailHtml = `<html><body>
    <script type="application/ld&#x2B;json">${JSON.stringify({
      "@context": "https://schema.org",
      "@type": "JobPosting",
      title: "Content Manager",
      datePosted: "2026-07-09",
      validThrough: "2026-08-08T18:47:11+00:00",
      employmentType: "FULL_TIME",
      description: "<p>Own editorial production.</p><ul><li>Edit daily</li></ul>",
      hiringOrganization: { "@type": "Organization", name: "Fake Therapy Co" },
      jobLocation: {
        "@type": "Place",
        address: {
          "@type": "PostalAddress",
          addressLocality: "New York",
          addressRegion: "New York",
          addressCountry: "USA",
        },
      },
      baseSalary: {
        "@type": "MonetaryAmount",
        currency: "USD",
        value: { "@type": "QuantitativeValue", minValue: 144000, maxValue: 168000, unitText: "YEAR" },
      },
    })}</script></body></html>`

  test("extracts company, location, salary and cleaned description", () => {
    const job = parseJobDetail(detailHtml, "123", "https://builtin.com/job/content-manager/123")
    expect(job).not.toBeNull()
    expect(job!.company).toBe("Fake Therapy Co")
    expect(job!.location).toBe("New York, New York, USA")
    expect(job!.employmentType).toBe("FULL_TIME")
    expect(job!.salary).toContain("144,000")
    expect(job!.salary).toContain("168,000")
    expect(job!.description).toContain("Own editorial production")
    expect(job!.description).toContain("Edit daily")
  })

  test("returns null when no JobPosting is present", () => {
    expect(parseJobDetail("<html><body>no data</body></html>", "1", "https://builtin.com/job/x/1")).toBeNull()
  })
})

describe("cleanDescription", () => {
  test("turns block tags into newlines and decodes entities", () => {
    const out = cleanDescription("<p>Line&nbsp;one</p><p>Caf&#233;</p>")
    expect(out).toBe("Line one\nCafé")
  })
  test("returns null for empty input", () => {
    expect(cleanDescription(null)).toBeNull()
  })
})

// kit#171: a bare numeric ID used to build https://builtin.com/job/x/<id>, on the assumption
// Built In redirects that placeholder-slug form to the canonical page. Verified live with curl:
// /job/x/<id> returns 404; the real /job/<slug>/<id> URL returns 200. There is no other Built
// In endpoint that resolves an ID to its slug without another fetch, so `detail` now refuses a
// bare ID outright and points at the URL, rather than silently building a URL that 404s.
describe("isBareId", () => {
  test("a bare numeric id is bare", () => {
    expect(isBareId("11340664")).toBe(true)
    expect(isBareId("  10122783  ")).toBe(true)
  })
  test("a full url is not bare", () => {
    expect(isBareId("https://builtin.com/job/loaniq-business-analyst/11340664")).toBe(false)
  })
  test("a path fragment is not bare", () => {
    expect(isBareId("/job/loaniq-business-analyst/11340664")).toBe(false)
  })
  test("fewer than 4 digits is not treated as a job id", () => {
    expect(isBareId("123")).toBe(false)
  })
})
