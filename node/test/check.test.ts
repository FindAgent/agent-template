import { describe, expect, it } from "vitest";
import { REQUEST_BUDGET, checkCrate } from "../src/check.js";
import { TEST_CONFIG, NOW, crateDoc, fakeCrates, routesFor } from "./helpers/fakeCrates.js";

const run = (
  name: unknown,
  fake: ReturnType<typeof fakeCrates>,
  extra: { owners?: boolean } = {},
) => checkCrate(name, { config: TEST_CONFIG, fetchImpl: fake.fetch, now: () => NOW, ...extra });

describe("a healthy crate", () => {
  it("returns a report with every signal, the verdict and the request count", async () => {
    const fake = fakeCrates(routesFor("acme-widget", crateDoc()));
    const r = await run("acme-widget", fake);
    expect(r).toMatchObject({
      kind: "crate_check",
      ok: true,
      crate: "acme-widget",
      version: "2.0.0",
      verdict: "healthy",
      checkedAt: NOW.toISOString(),
      requests: { used: 2, budget: REQUEST_BUDGET },
      notChecked: [],
    });
    expect((r as { signals: unknown[] }).signals).toHaveLength(6);
    expect(fake.calls.map((c) => c.url.pathname)).toEqual([
      "/api/v1/crates/acme-widget",
      "/api/v1/crates/acme-widget/owners",
    ]);
  });

  it("owners: false spends one request and reports the signal as not checked", async () => {
    const fake = fakeCrates(routesFor("acme-widget", crateDoc()));
    const r = await run("acme-widget", fake, { owners: false });
    expect(r).toMatchObject({
      ok: true,
      requests: { used: 1 },
      notChecked: [{ id: "owners", reason: expect.stringMatching(/switched off/) }],
    });
    expect(fake.calls).toHaveLength(1);
  });

  it("reports the canonical name the registry returned, not the casing asked for", async () => {
    const fake = fakeCrates({
      "crates.io/api/v1/crates/SERDE": { body: crateDoc({ name: "serde" }) },
      "crates.io/api/v1/crates/SERDE/owners": { body: { users: [{}, {}] } },
    });
    expect(await run("SERDE", fake)).toMatchObject({ ok: true, crate: "serde" });
  });
});

describe("politeness toward the upstream", () => {
  const withSleep = async (config: typeof TEST_CONFIG, extra: { owners?: boolean } = {}) => {
    const waits: number[] = [];
    const fake = fakeCrates(routesFor("acme-widget", crateDoc()));
    await checkCrate("acme-widget", {
      config,
      fetchImpl: fake.fetch,
      now: () => NOW,
      sleep: async (ms) => {
        waits.push(ms);
      },
      ...extra,
    });
    return waits;
  };

  it("waits the configured spacing once, between the two requests", async () => {
    expect(await withSleep({ ...TEST_CONFIG, spacingMs: 1000 })).toEqual([1000]);
  });

  it("does not wait when there is no second request, or when spacing is 0", async () => {
    expect(await withSleep({ ...TEST_CONFIG, spacingMs: 1000 }, { owners: false })).toEqual([]);
    expect(await withSleep({ ...TEST_CONFIG, spacingMs: 0 })).toEqual([]);
  });

  it("the second request really does come after the wait", async () => {
    const order: string[] = [];
    const fake = fakeCrates(routesFor("acme-widget", crateDoc()));
    await checkCrate("acme-widget", {
      config: { ...TEST_CONFIG, spacingMs: 50 },
      fetchImpl: async (u, i) => {
        order.push(new URL(u).pathname.endsWith("/owners") ? "owners" : "crate");
        return fake.fetch(u, i);
      },
      now: () => NOW,
      sleep: async () => {
        order.push("wait");
      },
    });
    expect(order).toEqual(["crate", "wait", "owners"]);
  });
});

describe("a crate with problems", () => {
  it("a yanked, stale crate is risky and the summary says why", async () => {
    const fake = fakeCrates(
      routesFor(
        "old-thing",
        crateDoc({
          name: "old-thing",
          yanked: true,
          yankMessage: "use new-thing",
          publishedDaysAgo: 3000,
        }),
      ),
    );
    const r = await run("old-thing", fake);
    expect(r).toMatchObject({ ok: true, verdict: "risky" });
    expect((r as { summary: string }).summary).toContain("use new-thing");
  });
});

describe("the owners read failing does not fail the check", () => {
  for (const [label, reply] of [
    ["rate limited", { status: 429 }],
    ["not found", { status: 404 }],
    ["a server error", { status: 503 }],
    ["not JSON", { rawBody: "nope" }],
    ["the wrong shape", { body: { users: "many" } }],
  ] as const) {
    it(`${label}: the signal is not checked, with the class in the reason, and the rest stand`, async () => {
      const fake = fakeCrates(routesFor("acme-widget", crateDoc(), reply));
      const r = await run("acme-widget", fake);
      expect(r).toMatchObject({ ok: true, requests: { used: 2 } });
      const report = r as { notChecked: Array<{ id: string; reason: string }>; verdict: string };
      expect(report.notChecked).toHaveLength(1);
      expect(report.notChecked[0]!.id).toBe("owners");
      expect(report.notChecked[0]!.reason).toMatch(
        /^(rate_limited|not_found|upstream_error|malformed_response): /,
      );
      expect(report.verdict).toBe("healthy");
    });
  }
});

describe("failures of the crate read are returned as themselves", () => {
  it("invalid input costs no request", async () => {
    const fake = fakeCrates({});
    for (const input of ["", "1bad", "../x", "a b", 7, undefined]) {
      const r = await run(input, fake);
      expect(r).toMatchObject({
        kind: "crate_failure",
        ok: false,
        failure: "invalid_input",
        requests: { used: 0 },
      });
    }
    expect(fake.calls).toHaveLength(0);
  });

  it("not_found is not_found and spends one request, not two", async () => {
    const fake = fakeCrates({ "crates.io/api/v1/crates/ghost": { status: 404 } });
    expect(await run("ghost", fake)).toMatchObject({
      ok: false,
      failure: "not_found",
      status: 404,
      requests: { used: 1 },
    });
    expect(fake.calls).toHaveLength(1);
  });

  it("rate_limited carries the reset time, and is never reported as not_found", async () => {
    const fake = fakeCrates({
      "crates.io/api/v1/crates/busy": { status: 429, headers: { "retry-after": "60" } },
    });
    expect(await run("busy", fake)).toMatchObject({
      ok: false,
      failure: "rate_limited",
      resetsAt: new Date(NOW.getTime() + 60_000).toISOString(),
    });
  });

  it("a 403 is upstream_error, not not_found: a refusal is not an absence", async () => {
    const fake = fakeCrates({ "crates.io/api/v1/crates/walled": { status: 403 } });
    expect(await run("walled", fake)).toMatchObject({
      ok: false,
      failure: "upstream_error",
      status: 403,
    });
  });

  it("each remaining class keeps its own name", async () => {
    const cases: Array<[string, Parameters<typeof fakeCrates>[0][string], string]> = [
      ["boom", { status: 500 }, "upstream_error"],
      ["junk", { rawBody: "<html>" }, "malformed_response"],
      ["shape", { body: { crate: { name: "shape" } } }, "malformed_response"],
    ];
    for (const [name, route, expected] of cases) {
      const fake = fakeCrates({ [`crates.io/api/v1/crates/${name}`]: route });
      expect(await run(name, fake)).toMatchObject({ ok: false, failure: expected });
    }
  });

  it("a failure never reads as a clean verdict", async () => {
    const fake = fakeCrates({ "crates.io/api/v1/crates/boom": { status: 500 } });
    const r = await run("boom", fake);
    expect(r).not.toHaveProperty("verdict");
    expect(r).not.toHaveProperty("signals");
  });
});
