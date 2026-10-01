import { describe, expect, it } from "vitest";
import { fetchCrate, fetchOwnerCount, parseCrateName } from "../src/crates.js";
import { TEST_CONFIG, NOW, crateDoc, fakeCrates, routesFor } from "./helpers/fakeCrates.js";

const http = (fetchImpl: ReturnType<typeof fakeCrates>["fetch"]) => ({
  config: TEST_CONFIG,
  fetchImpl,
  now: () => NOW,
});

describe("crate names", () => {
  it("accepts what crates.io accepts", () => {
    for (const n of [
      "serde",
      "tokio",
      "a",
      "serde_json",
      "serde-json",
      "Rand",
      "x86_64",
      "a".repeat(64),
    ]) {
      expect(parseCrateName(n), n).toEqual({ ok: true, name: n });
    }
  });

  it("trims surrounding whitespace", () => {
    expect(parseCrateName("  serde ")).toEqual({ ok: true, name: "serde" });
  });

  it("rejects what crates.io would reject, and anything that could steer the URL", () => {
    for (const n of [
      "",
      "   ",
      "1abc",
      "-abc",
      "has space",
      "../etc/passwd",
      "a/b",
      "@scope/pkg",
      "serde?x=1",
      "serde#frag",
      "serde%2Fx",
      "https://evil.example/x",
      "evil.example:443/x",
      "a".repeat(65),
      "sérde",
    ]) {
      expect(parseCrateName(n).ok, JSON.stringify(n)).toBe(false);
    }
    expect(parseCrateName(42).ok).toBe(false);
    expect(parseCrateName(null).ok).toBe(false);
    expect(parseCrateName(undefined).ok).toBe(false);
  });

  it("an invalid name is quoted back only up to 80 characters", () => {
    const r = parseCrateName(`1${"x".repeat(500)}`);
    expect(r.ok).toBe(false);
    expect((r as { message: string }).message.length).toBeLessThan(250);
  });
});

describe("fetchCrate", () => {
  it("reads the newest stable version's fields", async () => {
    const fake = fakeCrates(routesFor("acme-widget", crateDoc({ recentDownloads: 12 })));
    const r = await fetchCrate("acme-widget", http(fake.fetch));
    expect(r).toEqual({
      ok: true,
      value: {
        name: "acme-widget",
        version: "2.0.0",
        publishedAt: expect.any(String),
        yanked: false,
        yankMessage: null,
        license: "MIT OR Apache-2.0",
        repository: "https://github.com/acme/acme-widget",
        recentDownloads: 12,
      },
    });
  });

  it("falls back to max_version when there is no stable one", async () => {
    const doc = crateDoc({ latest: "3.0.0-rc.1" });
    (doc["crate"] as Record<string, unknown>)["max_stable_version"] = null;
    const fake = fakeCrates(routesFor("acme-widget", doc));
    expect(await fetchCrate("acme-widget", http(fake.fetch))).toMatchObject({
      ok: true,
      value: { version: "3.0.0-rc.1" },
    });
  });

  it("reads a yanked version with its message, and treats blank text as absent", async () => {
    const fake = fakeCrates(
      routesFor(
        "acme-widget",
        crateDoc({ yanked: true, yankMessage: "broken build", license: "  ", repository: "" }),
      ),
    );
    expect(await fetchCrate("acme-widget", http(fake.fetch))).toMatchObject({
      ok: true,
      value: { yanked: true, yankMessage: "broken build", license: null, repository: null },
    });
  });

  it("a missing recent download count is null, never zero", async () => {
    const fake = fakeCrates(routesFor("acme-widget", crateDoc({ recentDownloads: null })));
    expect(await fetchCrate("acme-widget", http(fake.fetch))).toMatchObject({
      ok: true,
      value: { recentDownloads: null },
    });
  });

  it("a missing crate is not_found with the crate named", async () => {
    const fake = fakeCrates({ "crates.io/api/v1/crates/ghost": { status: 404 } });
    const r = await fetchCrate("ghost", http(fake.fetch));
    expect(r).toMatchObject({ ok: false, failure: "not_found" });
    expect((r as { message: string }).message).toContain("ghost");
  });

  it("a document without the fields the check needs is malformed_response", async () => {
    const good = crateDoc();
    for (const body of [
      [],
      "text",
      {},
      { crate: { name: "x" } },
      { crate: { name: "x" }, versions: [] },
      { ...good, versions: [] },
      { ...good, versions: [{ num: "2.0.0" }] },
      { ...good, versions: "no" },
      { ...good, crate: { ...(good["crate"] as object), recent_downloads: "many" } },
    ]) {
      const fake = fakeCrates({ "crates.io/api/v1/crates/x": { body } });
      const r = await fetchCrate("x", http(fake.fetch));
      expect(r, JSON.stringify(body).slice(0, 80)).toMatchObject({
        ok: false,
        failure: "malformed_response",
      });
    }
  });

  it("requests the crate path on crates.io only", async () => {
    const fake = fakeCrates(routesFor("Acme_Widget", crateDoc({ name: "Acme_Widget" })));
    await fetchCrate("Acme_Widget", http(fake.fetch));
    expect(fake.calls).toHaveLength(1);
    expect(fake.calls[0]!.url.host).toBe("crates.io");
    expect(fake.calls[0]!.url.pathname).toBe("/api/v1/crates/Acme_Widget");
  });

  it("passes upstream failures through unchanged", async () => {
    const fake = fakeCrates({
      "crates.io/api/v1/crates/x": { status: 429, headers: { "retry-after": "10" } },
    });
    expect(await fetchCrate("x", http(fake.fetch))).toMatchObject({
      ok: false,
      failure: "rate_limited",
      resetsAt: expect.any(String),
    });
  });
});

describe("fetchOwnerCount", () => {
  it("counts people and teams", async () => {
    const fake = fakeCrates(routesFor("acme-widget", crateDoc(), 4));
    expect(await fetchOwnerCount("acme-widget", http(fake.fetch))).toEqual({ ok: true, value: 4 });
    expect(fake.calls[0]!.url.pathname).toBe("/api/v1/crates/acme-widget/owners");
  });

  it("zero owners is a measured zero", async () => {
    const fake = fakeCrates(routesFor("acme-widget", crateDoc(), 0));
    expect(await fetchOwnerCount("acme-widget", http(fake.fetch))).toEqual({ ok: true, value: 0 });
  });

  it("a body without a users list is malformed_response", async () => {
    for (const body of [{}, { users: "x" }, [], null]) {
      const fake = fakeCrates(routesFor("acme-widget", crateDoc(), { body }));
      expect(await fetchOwnerCount("acme-widget", http(fake.fetch))).toMatchObject({
        ok: false,
        failure: "malformed_response",
      });
    }
  });
});
