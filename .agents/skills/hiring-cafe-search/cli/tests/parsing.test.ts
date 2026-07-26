import { describe, test, expect } from "bun:test"
import {
  buildSearchUrl,
  jobUrlFromId,
  parseNextData,
  toResult,
  toDetail,
  detailUrl,
} from "../src/helpers"

const rawHit = {
  id: "icims2___careers-sonalysts___2442",
  apply_url: "https://careers-sonalysts.icims.com/jobs/2442/software-engineer/job",
  source: "icims2",
  board_token: "careers-sonalysts",
  job_information: { title: "Software Engineer" },
  v5_processed_job_data: {
    core_job_title: "Software Engineer",
    company_name: "Sonalysts, Inc.",
    workplace_type: "Onsite",
    formatted_workplace_location: "Waterford, Connecticut, United States",
    estimated_publish_date: "2026-07-09T23:59:23.833Z",
    yearly_min_compensation: 85000,
    yearly_max_compensation: 125000,
    commitment: ["Full Time"],
    seniority_level: "Senior Level",
    min_industry_and_role_yoe: 5,
    job_category: "Engineering",
    technical_tools: ["C#", "Java", "C++"],
    role_activities: ["Develop simulations", "Build GUIs"],
    requirements_summary: "U.S. citizen, bachelor's in CS, 5+ years.",
  },
  enriched_company_data: { name: "Sonalysts, Inc.", industries: ["Defense"], nb_employees: 400 },
}

function nextDataHtml(hits: unknown[], extra: Record<string, unknown> = {}): string {
  const payload = { props: { pageProps: { ssrHits: hits, ssrPage: 0, ssrTotalCount: 123, ...extra } } }
  return `<html><body><script id="__NEXT_DATA__" type="application/json">${JSON.stringify(
    payload,
  )}</script></body></html>`
}

describe("buildSearchUrl", () => {
  // Parse searchState back out the way a browser/server would (URLSearchParams
  // handles the `+`-for-space form encoding) and assert on the decoded JSON.
  const searchState = (url: string) => {
    const raw = new URL(url).searchParams.get("searchState")
    return JSON.parse(raw ?? "{}")
  }
  test("encodes searchQuery and omits page 0", () => {
    const url = buildSearchUrl("data engineer", {}, 0)
    expect(url).toContain("searchState=")
    expect(searchState(url).searchQuery).toBe("data engineer")
    expect(url).not.toContain("page=")
  })
  test("adds workplaceTypes and a page param", () => {
    const url = buildSearchUrl("swe", { remote: true, hybrid: true }, 2)
    expect(searchState(url).workplaceTypes).toEqual(["Remote", "Hybrid"])
    expect(url).toContain("page=2")
  })
})

describe("jobUrlFromId", () => {
  test("collapses underscore runs to single dashes", () => {
    expect(jobUrlFromId("icims2___careers-sonalysts___2442")).toBe(
      "https://hiring.cafe/jobs/icims2-careers-sonalysts-2442",
    )
  })
})

describe("parseNextData", () => {
  test("extracts pageProps.ssrHits", () => {
    const pp = parseNextData(nextDataHtml([rawHit]))
    expect(pp?.ssrHits).toHaveLength(1)
    expect(pp?.ssrTotalCount).toBe(123)
  })
  test("returns null without __NEXT_DATA__", () => {
    expect(parseNextData("<html></html>")).toBeNull()
  })
})

describe("toResult", () => {
  test("maps core fields and builds the canonical URL", () => {
    const r = toResult(rawHit)
    expect(r).toMatchObject({
      id: "icims2___careers-sonalysts___2442",
      title: "Software Engineer",
      company: "Sonalysts, Inc.",
      location: "Waterford, Connecticut, United States",
      workplaceType: "Onsite",
      date: "2026-07-09",
      url: "https://hiring.cafe/jobs/icims2-careers-sonalysts-2442",
      applyUrl: "https://careers-sonalysts.icims.com/jobs/2442/software-engineer/job",
    })
    expect(r.salary).toBe("$85,000–$125,000 / yr")
  })
})

describe("toDetail", () => {
  test("adds seniority, tools, and an assembled description", () => {
    const d = toDetail(rawHit)
    expect(d.seniority).toBe("Senior Level")
    expect(d.commitment).toBe("Full Time")
    expect(d.minYearsExperience).toBe(5)
    expect(d.technicalTools).toEqual(["C#", "Java", "C++"])
    expect(d.companyIndustries).toEqual(["Defense"])
    expect(d.companySize).toBe(400)
    expect(d.description).toContain("Requirements: U.S. citizen")
    expect(d.description).toContain("Develop simulations")
    expect(d.description).toContain("Tools: C#, Java, C++")
  })
})

describe("detailUrl", () => {
  test("accepts a raw id", () => {
    expect(detailUrl("icims2___careers-sonalysts___2442")).toBe(
      "https://hiring.cafe/jobs/icims2___careers-sonalysts___2442",
    )
  })
  test("extracts the id from a /jobs/ URL", () => {
    expect(detailUrl("https://hiring.cafe/jobs/icims2-careers-sonalysts-2442")).toBe(
      "https://hiring.cafe/jobs/icims2-careers-sonalysts-2442",
    )
  })
  test("rejects empty input", () => {
    expect(detailUrl("  ")).toBeNull()
  })
})
