import { describe, expect, it } from "vitest";
import type { CrateDoc } from "../src/crates.js";
import {
  MIN_CHECKED_FOR_VERDICT,
  SIGNAL_RULES,
  THRESHOLDS,
  buildSignals,
  summarize,
  verdictFor,
  type OwnersInput,
} from "../src/signals.js";
import { NOW, daysAgo } from "./helpers/fakeCrates.js";

const base: CrateDoc = {
  name: "acme",
  version: "1.2.3",
  publishedAt: daysAgo(10),
  yanked: false,
  yankMessage: null,
  license: "MIT",
  repository: "https://github.com/acme/acme",
  recentDownloads: 50_000,
};
const signalsFor = (c: Partial<CrateDoc>, o: OwnersInput = { state: "ok", value: 3 }) =>
  buildSignals({ ...base, ...c }, o, NOW);
const find = (s: ReturnType<typeof signalsFor>, id: string) => s.find((x) => x.id === id)!;

describe("latest release age", () => {
  it("is ok below the warn line, warn at it, risk at the risk line", () => {
    const at = (days: number) =>
      find(signalsFor({ publishedAt: daysAgo(days) }), "latest_release_age").status;
    expect(at(THRESHOLDS.staleWarnDays - 1)).toBe("ok");
    expect(at(THRESHOLDS.staleWarnDays)).toBe("warn");
    expect(at(THRESHOLDS.staleRiskDays - 1)).toBe("warn");
    expect(at(THRESHOLDS.staleRiskDays)).toBe("risk");
  });

  it("reports the age in days and never a negative one", () => {
    expect(find(signalsFor({ publishedAt: daysAgo(10) }), "latest_release_age").value).toBe(10);
    expect(find(signalsFor({ publishedAt: daysAgo(-5) }), "latest_release_age").value).toBe(0);
  });

  it("is not checked, with the reason, when the time cannot be read, and is never zero", () => {
    const s = find(signalsFor({ publishedAt: "not a date" }), "latest_release_age");
    expect(s.status).toBe("not_checked");
    expect(s.value).toBeNull();
    expect(s.reason).toMatch(/publish time/);
  });
});

describe("the other signals", () => {
  it("a yanked latest version is a risk and quotes the message", () => {
    const s = find(signalsFor({ yanked: true, yankMessage: "broken build" }), "yanked");
    expect(s.status).toBe("risk");
    expect(s.detail).toContain("broken build");
    expect(find(signalsFor({}), "yanked").status).toBe("ok");
  });

  it("a missing license is a warn", () => {
    expect(find(signalsFor({ license: null }), "license").status).toBe("warn");
    expect(find(signalsFor({ license: "MIT" }), "license").status).toBe("ok");
  });

  it("a missing repository is a warn", () => {
    expect(find(signalsFor({ repository: null }), "repository").status).toBe("warn");
    expect(find(signalsFor({}), "repository").status).toBe("ok");
  });

  it("recent downloads: low warns, zero is a measured zero, unknown is not checked", () => {
    const at = (n: number | null) => find(signalsFor({ recentDownloads: n }), "recent_downloads");
    expect(at(THRESHOLDS.lowRecentDownloads - 1).status).toBe("warn");
    expect(at(THRESHOLDS.lowRecentDownloads).status).toBe("ok");
    expect(at(0)).toMatchObject({ status: "warn", value: 0 });
    expect(at(null)).toMatchObject({ status: "not_checked", value: null });
  });

  it("owners: one warns, two do not, skipped and failed are not checked", () => {
    const at = (o: OwnersInput) => find(signalsFor({}, o), "owners");
    expect(at({ state: "ok", value: 1 }).status).toBe("warn");
    expect(at({ state: "ok", value: THRESHOLDS.minOwners }).status).toBe("ok");
    expect(at({ state: "ok", value: 0 })).toMatchObject({ status: "warn", value: 0 });
    const skipped = at({ state: "skipped" });
    expect(skipped).toMatchObject({ status: "not_checked", value: null });
    expect(skipped.reason).toMatch(/switched off/);
    expect(at({ state: "failed", reason: "rate_limited: slow down" })).toMatchObject({
      status: "not_checked",
      value: null,
      reason: "rate_limited: slow down",
    });
  });

  it("always yields the same signals in the same order, matching the documented rules", () => {
    const ids = signalsFor({}).map((s) => s.id);
    expect(ids).toEqual(SIGNAL_RULES.map((r) => r.id));
    expect(ids).toEqual([
      "latest_release_age",
      "yanked",
      "license",
      "repository",
      "recent_downloads",
      "owners",
    ]);
  });

  it("every signal names the API field it came from", () => {
    for (const s of signalsFor({})) expect(s.source.length).toBeGreaterThan(3);
    for (const r of SIGNAL_RULES) expect(r.field.length).toBeGreaterThan(3);
  });
});

describe("verdict", () => {
  it("any risk is risky, any warn is watch, else healthy", () => {
    expect(verdictFor(signalsFor({ yanked: true })).verdict).toBe("risky");
    expect(verdictFor(signalsFor({ license: null })).verdict).toBe("watch");
    expect(verdictFor(signalsFor({})).verdict).toBe("healthy");
  });

  it("risk outranks warn", () => {
    expect(verdictFor(signalsFor({ yanked: true, license: null })).verdict).toBe("risky");
  });

  it("is unknown, not healthy, when too few signals could be measured", () => {
    const sparse = signalsFor({}).map((s, i) =>
      i < 4 ? { ...s, status: "not_checked" as const } : s,
    );
    expect(sparse.filter((s) => s.status !== "not_checked").length).toBeLessThan(
      MIN_CHECKED_FOR_VERDICT,
    );
    const v = verdictFor(sparse);
    expect(v.verdict).toBe("unknown");
    expect(v.reason).toMatch(/at least 3/);
  });

  it("a not-checked signal never raises or lowers the verdict", () => {
    expect(verdictFor(signalsFor({}, { state: "skipped" })).verdict).toBe("healthy");
  });
});

describe("summary", () => {
  it("says what is wrong and what was not checked", () => {
    const s = signalsFor({ yanked: true, yankMessage: "gone" }, { state: "skipped" });
    const text = summarize("acme", "1.2.3", s, verdictFor(s).verdict);
    expect(text).toContain("acme@1.2.3 (verdict: risky)");
    expect(text).toContain("gone");
    expect(text).toContain("Not checked: owners.");
  });

  it("keeps sentences apart when an upstream message has no final punctuation", () => {
    const s = signalsFor({ yanked: true, yankMessage: "use other", license: null });
    expect(summarize("acme", "1.2.3", s, "risky")).toContain(
      "use other. The latest version declares no license.",
    );
  });

  it("says plainly when nothing raised a concern", () => {
    expect(summarize("acme", "1.2.3", signalsFor({}), "healthy")).toBe(
      "acme@1.2.3: no signal raised a concern (verdict: healthy).",
    );
  });
});
