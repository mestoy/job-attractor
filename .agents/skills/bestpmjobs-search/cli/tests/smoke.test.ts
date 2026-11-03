import { describe, expect, test } from "bun:test";
import { runCLI, parseJSON } from "./helpers.js";
import type { JobCard, JobDetail } from "../src/helpers.js";

describe("search", () => {
  test("returns real results for a live query", async () => {
    const result = await runCLI(["search", "-q", "product manager", "--limit", "5"]);
    const data = parseJSON<{ meta: { count: number }; results: JobCard[] }>(result);
    expect(data.results.length).toBeGreaterThan(0);
    const first = data.results[0];
    expect(first.id).toBeTruthy();
    expect(first.title).toBeTruthy();
    expect(first.url).toContain("bestpmjobs.com");
  });

  test("detail resolves a real posting from a search result", async () => {
    const search = await runCLI(["search", "-q", "product manager", "--limit", "1"]);
    const { results } = parseJSON<{ results: JobCard[] }>(search);
    expect(results.length).toBeGreaterThan(0);

    const detail = await runCLI(["detail", results[0].id, "--format", "json"]);
    const job = parseJSON<JobDetail>(detail);
    expect(job.title).toBeTruthy();
    expect(job.description && job.description.length).toBeGreaterThan(0);
  });
});

describe("flag validation", () => {
  test("a bogus numeric flag exits 1 with a JSON error on stderr", async () => {
    const result = await runCLI(["search", "--page", "not-a-number"]);
    expect(result.exitCode).toBe(1);
    const err = JSON.parse(result.stderr);
    expect(err.code).toBe("BAD_ARG");
  });

  test("detail with no id exits 1 with a JSON error on stderr", async () => {
    const result = await runCLI(["detail"]);
    expect(result.exitCode).toBe(1);
    const err = JSON.parse(result.stderr);
    expect(err.code).toBe("NO_ID");
  });
});
