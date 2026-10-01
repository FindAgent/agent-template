/**
 * Runtime knobs. None is a secret and none is required: the defaults are what the hosted sandbox
 * runs. They exist so a limit can be exercised against the real upstream (see scripts/live-check.mjs)
 * and so a local run can be tuned. A value outside its bounds is ignored with a warning on stderr
 * (stdout belongs to the MCP protocol).
 */

export interface Config {
  /** Per-request wall clock, in milliseconds. */
  timeoutMs: number;
  /** The most response bytes read from one upstream request. */
  maxBytes: number;
  /** Pause between two requests of one check. crates.io asks crawlers for at most one request a second. */
  spacingMs: number;
}

export const DEFAULTS: Config = { timeoutMs: 10_000, maxBytes: 5 * 1024 * 1024, spacingMs: 1000 };

const BOUNDS = {
  AGENT_TIMEOUT_MS: { key: "timeoutMs", min: 1, max: 60_000 },
  AGENT_MAX_BYTES: { key: "maxBytes", min: 1_000, max: 50 * 1024 * 1024 },
  AGENT_SPACING_MS: { key: "spacingMs", min: 0, max: 10_000 },
} as const;

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const config: Config = { ...DEFAULTS };
  for (const [name, bound] of Object.entries(BOUNDS)) {
    const raw = env[name];
    if (raw === undefined || raw === "") continue;
    const n = Number(raw);
    if (!Number.isInteger(n) || n < bound.min || n > bound.max) {
      console.error(
        `${name}=${JSON.stringify(raw)} is not an integer between ${bound.min} and ${bound.max}; using the default ${DEFAULTS[bound.key]}.`,
      );
      continue;
    }
    config[bound.key] = n;
  }
  return config;
}
