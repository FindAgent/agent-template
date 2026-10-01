import { describe, expect, it } from "vitest";
import { classifyThrown, getJson, resetTime } from "../src/http.js";
import { NOW, TEST_CONFIG, fakeCrates } from "./helpers/fakeCrates.js";

const URL_ = "https://crates.io/api/v1/crates/thing";
const config = { ...TEST_CONFIG, timeoutMs: 200 };
const opts = (fetchImpl: ReturnType<typeof fakeCrates>["fetch"]) => ({
  config,
  fetchImpl,
  now: () => NOW,
});

describe("every failure is its own class", () => {
  it("200 with JSON is ok", async () => {
    const fake = fakeCrates({ "crates.io/api/v1/crates/thing": { body: { a: 1 } } });
    expect(await getJson(URL_, opts(fake.fetch))).toEqual({
      ok: true,
      json: { a: 1 },
      status: 200,
    });
  });

  it("404 is not_found, and only 404", async () => {
    const fake = fakeCrates({ "crates.io/api/v1/crates/thing": { status: 404 } });
    const r = await getJson(URL_, opts(fake.fetch));
    expect(r).toMatchObject({ ok: false, failure: "not_found", status: 404 });
  });

  it("429 is rate_limited and carries the reset time from Retry-After seconds", async () => {
    const fake = fakeCrates({
      "crates.io/api/v1/crates/thing": { status: 429, headers: { "retry-after": "120" } },
    });
    const r = await getJson(URL_, opts(fake.fetch));
    expect(r).toMatchObject({
      ok: false,
      failure: "rate_limited",
      status: 429,
      resetsAt: new Date(NOW.getTime() + 120_000).toISOString(),
    });
  });

  it("429 with an HTTP-date Retry-After is converted to an ISO time", async () => {
    const fake = fakeCrates({
      "crates.io/api/v1/crates/thing": {
        status: 429,
        headers: { "retry-after": "Thu, 01 Oct 2026 13:00:00 GMT" },
      },
    });
    const r = await getJson(URL_, opts(fake.fetch));
    expect(r).toMatchObject({ failure: "rate_limited", resetsAt: "2026-10-01T13:00:00.000Z" });
  });

  it("429 without a usable Retry-After says it does not know when, and invents no time", async () => {
    for (const headers of [{}, { "retry-after": "soon" }]) {
      const fake = fakeCrates({ "crates.io/api/v1/crates/thing": { status: 429, headers } });
      const r = await getJson(URL_, opts(fake.fetch));
      expect(r).toMatchObject({ ok: false, failure: "rate_limited" });
      expect(r).not.toHaveProperty("resetsAt");
      expect((r as { message: string }).message).toMatch(/did not say when/);
    }
  });

  it("a 5xx and an unexpected 4xx are upstream_error with their status, never not_found", async () => {
    for (const status of [500, 502, 503, 401, 403, 418]) {
      const fake = fakeCrates({ "crates.io/api/v1/crates/thing": { status } });
      const r = await getJson(URL_, opts(fake.fetch));
      expect(r).toMatchObject({ ok: false, failure: "upstream_error", status });
    }
  });

  it("a redirect is refused and never followed", async () => {
    const fake = fakeCrates({
      "crates.io/api/v1/crates/thing": {
        status: 301,
        headers: { location: "https://evil.example/x" },
      },
    });
    const r = await getJson(URL_, opts(fake.fetch));
    expect(r).toMatchObject({ ok: false, failure: "upstream_error", status: 301 });
    expect(fake.calls).toHaveLength(1);
    expect(fake.calls[0]!.init?.redirect).toBe("manual");
  });

  it("a 200 that is not JSON is malformed_response", async () => {
    const fake = fakeCrates({ "crates.io/api/v1/crates/thing": { rawBody: "<html>oops</html>" } });
    expect(await getJson(URL_, opts(fake.fetch))).toMatchObject({
      ok: false,
      failure: "malformed_response",
    });
  });

  it("a body over the byte cap is response_too_large and is not parsed", async () => {
    const fake = fakeCrates({
      "crates.io/api/v1/crates/thing": { rawBody: JSON.stringify({ x: "y".repeat(5000) }) },
    });
    const r = await getJson(URL_, { ...opts(fake.fetch), config: { ...config, maxBytes: 1000 } });
    expect(r).toMatchObject({ ok: false, failure: "response_too_large" });
  });

  it("a declared Content-Length over the cap is refused before reading", async () => {
    const fake = fakeCrates({
      "crates.io/api/v1/crates/thing": { body: { a: 1 }, headers: { "content-length": "999999" } },
    });
    const r = await getJson(URL_, { ...opts(fake.fetch), config: { ...config, maxBytes: 1000 } });
    expect(r).toMatchObject({ ok: false, failure: "response_too_large" });
  });

  it("a request that never answers is a timeout, not a network_error", async () => {
    const hang: ReturnType<typeof fakeCrates>["fetch"] = (_u, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const e = new Error("aborted");
          e.name = "AbortError";
          reject(e);
        });
      });
    const r = await getJson(URL_, opts(hang));
    expect(r).toMatchObject({ ok: false, failure: "timeout" });
  });

  it("a connection that fails is network_error and names the cause", async () => {
    const down: ReturnType<typeof fakeCrates>["fetch"] = async () => {
      throw Object.assign(new TypeError("fetch failed"), { cause: { code: "ENOTFOUND" } });
    };
    const r = await getJson(URL_, opts(down));
    expect(r).toMatchObject({ ok: false, failure: "network_error" });
    expect((r as { message: string }).message).toContain("ENOTFOUND");
  });

  it("sends GET with a user agent and asks for JSON", async () => {
    const fake = fakeCrates({ "crates.io/api/v1/crates/thing": { body: {} } });
    await getJson(URL_, opts(fake.fetch));
    const init = fake.calls[0]!.init!;
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>)["user-agent"]).toMatch(/^agent-template\//);
    expect((init.headers as Record<string, string>)["accept"]).toBe("application/json");
  });
});

describe("classifyThrown", () => {
  it("reads the code from the cause, which is where Node puts it", () => {
    expect(
      classifyThrown(Object.assign(new TypeError("fetch failed"), { cause: { code: "ETIMEDOUT" } }))
        .failure,
    ).toBe("timeout");
    expect(
      classifyThrown(
        Object.assign(new TypeError("fetch failed"), {
          cause: { code: "UND_ERR_CONNECT_TIMEOUT" },
        }),
      ).failure,
    ).toBe("timeout");
    expect(
      classifyThrown(
        Object.assign(new TypeError("fetch failed"), { cause: { code: "ECONNRESET" } }),
      ).failure,
    ).toBe("network_error");
  });

  it("an AbortError and a TimeoutError are timeouts", () => {
    expect(classifyThrown(Object.assign(new Error("x"), { name: "AbortError" })).failure).toBe(
      "timeout",
    );
    expect(classifyThrown(Object.assign(new Error("x"), { name: "TimeoutError" })).failure).toBe(
      "timeout",
    );
  });

  it("anything else is network_error, even a thrown string", () => {
    expect(classifyThrown("boom").failure).toBe("network_error");
    expect(classifyThrown(undefined).failure).toBe("network_error");
  });
});

describe("resetTime", () => {
  it("handles seconds, dates, junk and absence", () => {
    expect(resetTime("30", NOW)).toBe(new Date(NOW.getTime() + 30_000).toISOString());
    expect(resetTime("Thu, 01 Oct 2026 13:00:00 GMT", NOW)).toBe("2026-10-01T13:00:00.000Z");
    expect(resetTime("nonsense", NOW)).toBeUndefined();
    expect(resetTime(null, NOW)).toBeUndefined();
  });
});
