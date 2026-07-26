import { describe, test, expect } from "bun:test"
import { toResult, toDetail, jobUrl, normalizeRef, cleanHtml, type WttjHit } from "../src/helpers"

const hit: WttjHit = {
  name: "Senior Data Engineer",
  slug: "senior-data-engineer_new-york",
  reference: "12345678-1234-1234-1234-123456789abc",
  contract_type: "full_time",
  remote: "fulltime",
  published_at: 1_752_000_000, // unix seconds
  salary_min: 150000,
  salary_max: 190000,
  salary_currency: "USD",
  salary_period: "YEAR",
  experience_level_minimum: 5,
  language: "en",
  description: "<p>Build data platforms.</p><ul><li>Own the warehouse</li></ul>",
  organization: { name: "Acme", slug: "acme" },
  offices: [{ city: "New York", state: "NY", country_code: "US", country: "United States" }],
}

describe("jobUrl", () => {
  test("builds a canonical company/job URL", () => {
    expect(jobUrl(hit)).toBe(
      "https://www.welcometothejungle.com/en/companies/acme/jobs/senior-data-engineer_new-york",
    )
  })
  test("falls back to the jobs page without slugs", () => {
    expect(jobUrl({})).toBe("https://www.welcometothejungle.com/en/jobs")
  })
})

describe("toResult", () => {
  test("maps the core fields, using reference as id", () => {
    const r = toResult(hit)
    expect(r).toMatchObject({
      id: "12345678-1234-1234-1234-123456789abc",
      title: "Senior Data Engineer",
      company: "Acme",
      company_slug: "acme",
      location: "New York, NY",
      contract_type: "full_time",
      remote: "fulltime",
    })
  })
  test("converts a unix-seconds published_at to an ISO date", () => {
    expect(toResult(hit).date).toBe(new Date(1_752_000_000 * 1000).toISOString().slice(0, 10))
  })
  test("treats remote:'no' as not remote", () => {
    expect(toResult({ ...hit, remote: "no" }).remote).toBeNull()
  })
})

describe("toDetail", () => {
  test("adds salary, experience and a cleaned description", () => {
    const d = toDetail(hit)
    expect(d.salary).toBe("USD 150,000–190,000 / year")
    expect(d.experience).toBe("5+ years")
    expect(d.description).toBe("Build data platforms.\nOwn the warehouse")
  })
})

describe("cleanHtml", () => {
  test("decodes entities and normalizes whitespace", () => {
    expect(cleanHtml("<p>Caf&#233;&nbsp;lead</p>")).toBe("Café lead")
  })
  test("returns null for empty input", () => {
    expect(cleanHtml(undefined)).toBeNull()
  })
})

describe("normalizeRef", () => {
  test("extracts a uuid reference", () => {
    expect(normalizeRef("ref 12345678-1234-1234-1234-123456789abc here")).toBe(
      "12345678-1234-1234-1234-123456789abc",
    )
  })
  test("extracts a slug from a job URL", () => {
    expect(
      normalizeRef("https://www.welcometothejungle.com/en/companies/acme/jobs/senior-data-engineer_ny"),
    ).toBe("senior-data-engineer_ny")
  })
  test("accepts a bare slug", () => {
    expect(normalizeRef("data-engineer")).toBe("data-engineer")
  })
  test("rejects empty input", () => {
    expect(normalizeRef("   ")).toBeNull()
  })
})
