import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULTS, loadConfig } from "../src/config.js";

afterEach(() => vi.restoreAllMocks());

describe("loadConfig", () => {
  it("uses the defaults when nothing is set", () => {
    expect(loadConfig({})).toEqual(DEFAULTS);
    expect(loadConfig({ AGENT_TIMEOUT_MS: "", AGENT_MAX_BYTES: "" })).toEqual(DEFAULTS);
  });

  it("reads both knobs", () => {
    expect(
      loadConfig({ AGENT_TIMEOUT_MS: "2500", AGENT_MAX_BYTES: "50000", AGENT_SPACING_MS: "0" }),
    ).toEqual({ timeoutMs: 2500, maxBytes: 50000, spacingMs: 0 });
  });

  it("ignores a value outside its bounds or not an integer, and says so on stderr", () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    for (const env of [
      { AGENT_TIMEOUT_MS: "banana" },
      { AGENT_TIMEOUT_MS: "0" },
      { AGENT_TIMEOUT_MS: "-5" },
      { AGENT_TIMEOUT_MS: "1.5" },
      { AGENT_TIMEOUT_MS: "999999" },
      { AGENT_MAX_BYTES: "10" },
      { AGENT_MAX_BYTES: "99999999999" },
      { AGENT_SPACING_MS: "-1" },
      { AGENT_SPACING_MS: "999999" },
    ]) {
      expect(loadConfig(env), JSON.stringify(env)).toEqual(DEFAULTS);
    }
    expect(err).toHaveBeenCalledTimes(9);
  });

  it("one bad knob does not discard the good one", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(loadConfig({ AGENT_TIMEOUT_MS: "x", AGENT_MAX_BYTES: "20000" })).toEqual({
      ...DEFAULTS,
      maxBytes: 20000,
    });
  });
});
