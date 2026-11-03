// kit#95: no baked-in Algolia key; a missing or rejected key is a NAMED error, not an empty result.
import { describe, test, expect, beforeEach, afterEach } from "bun:test"
import { algoliaKey, algoliaSearch, errorCode, WttjKeyError } from "../src/helpers"

const saved = { key: process.env.WTTJ_ALGOLIA_KEY, fetch: globalThis.fetch }
beforeEach(() => {
  delete process.env.WTTJ_ALGOLIA_KEY
})
afterEach(() => {
  if (saved.key === undefined) delete process.env.WTTJ_ALGOLIA_KEY
  else process.env.WTTJ_ALGOLIA_KEY = saved.key
  globalThis.fetch = saved.fetch
})

describe("algoliaKey", () => {
  test("throws WTTJ_KEY_MISSING when the env var is unset", () => {
    expect(() => algoliaKey()).toThrow(WttjKeyError)
    try {
      algoliaKey()
    } catch (e) {
      expect((e as WttjKeyError).code).toBe("WTTJ_KEY_MISSING")
      expect((e as WttjKeyError).message).toContain("WTTJ_ALGOLIA_KEY")
      expect((e as WttjKeyError).message).toContain("csekhvms53-dsn.algolia.net")
    }
  })
  test("a blank value counts as missing", () => {
    process.env.WTTJ_ALGOLIA_KEY = "   "
    expect(() => algoliaKey()).toThrow(/WTTJ_ALGOLIA_KEY/)
  })
  test("returns the trimmed env value", () => {
    process.env.WTTJ_ALGOLIA_KEY = " abc "
    expect(algoliaKey()).toBe("abc")
  })
})

describe("algoliaSearch on 403", () => {
  test("throws WTTJ_KEY_REJECTED naming the fix, without retrying", async () => {
    process.env.WTTJ_ALGOLIA_KEY = "stale"
    let calls = 0
    globalThis.fetch = (async () => {
      calls++
      return new Response('{"status":403}', { status: 403, statusText: "Forbidden" })
    }) as typeof fetch
    let caught: unknown
    try {
      await algoliaSearch({ query: "pm", hitsPerPage: 1, page: 0, filters: [] })
    } catch (e) {
      caught = e
    }
    expect(caught).toBeInstanceOf(WttjKeyError)
    expect((caught as WttjKeyError).code).toBe("WTTJ_KEY_REJECTED")
    expect((caught as WttjKeyError).message).toContain("403")
    expect((caught as WttjKeyError).message).toContain("x-algolia-api-key")
    expect(calls).toBe(1)
  })
  test("a missing key throws before any network call", async () => {
    let calls = 0
    globalThis.fetch = (async () => {
      calls++
      return new Response("{}", { status: 200 })
    }) as typeof fetch
    await expect(algoliaSearch({ query: "", hitsPerPage: 1, page: 0, filters: [] })).rejects.toThrow(
      /WTTJ_ALGOLIA_KEY/,
    )
    expect(calls).toBe(0)
  })
})

describe("errorCode", () => {
  test("keeps a key error's own code and falls back otherwise", () => {
    expect(errorCode(new WttjKeyError("WTTJ_KEY_REJECTED", "x"), "SEARCH_FAILED")).toBe("WTTJ_KEY_REJECTED")
    expect(errorCode(new Error("boom"), "SEARCH_FAILED")).toBe("SEARCH_FAILED")
  })
})
