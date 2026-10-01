/**
 * The one place that talks to the network. GET only, JSON only, no credentials.
 *
 * Every way a request can go wrong is its own class (see FailureClass). Nothing here returns a
 * bare null or an empty value: a caller always learns WHICH condition it hit, because "not found",
 * "refused" and "could not reach" call for different things from the person asking.
 *
 * Egress is default-deny on the platform, so the hosts this module may reach are the
 * `allowed_hosts` in findagent.json. A redirect is never followed: the platform would refuse a
 * hop to an undeclared host, and an agent should not rely on being refused.
 */

import { USER_AGENT } from "./meta.js";
import type { Config } from "./config.js";
import type { FailureClass } from "./types.js";

export type FetchImpl = (input: string, init?: RequestInit) => Promise<Response>;

export interface HttpOptions {
  config: Config;
  /** Test seam: defaults to the platform fetch. */
  fetchImpl?: FetchImpl;
  /** Test seam: defaults to the wall clock. */
  now?: () => Date;
}

export type HttpResult =
  | { ok: true; json: unknown; status: number }
  | {
      ok: false;
      failure: Exclude<FailureClass, "invalid_input">;
      message: string;
      status?: number;
      resetsAt?: string;
    };

/** Retry-After is either a number of seconds or an HTTP date. Anything else yields no reset time. */
export function resetTime(header: string | null, now: Date): string | undefined {
  if (header === null) return undefined;
  const value = header.trim();
  if (/^\d+$/.test(value)) {
    return new Date(now.getTime() + Number(value) * 1000).toISOString();
  }
  const at = Date.parse(value);
  return Number.isNaN(at) ? undefined : new Date(at).toISOString();
}

interface NodeError {
  name?: string;
  code?: string;
  message?: string;
  cause?: unknown;
}

const TIMEOUT_CODES = new Set(["ETIMEDOUT", "UND_ERR_CONNECT_TIMEOUT", "UND_ERR_HEADERS_TIMEOUT"]);

/**
 * Classify a thrown fetch error. Node's fetch throws one opaque `TypeError: fetch failed` whose
 * real reason is on `cause`, so the code is read from there as well as from the error itself.
 */
export function classifyThrown(err: unknown): {
  failure: "timeout" | "network_error";
  message: string;
} {
  const e = (err ?? {}) as NodeError;
  const cause = (e.cause ?? {}) as NodeError;
  const code = cause.code ?? e.code;
  if (
    e.name === "AbortError" ||
    e.name === "TimeoutError" ||
    (code !== undefined && TIMEOUT_CODES.has(code))
  ) {
    return { failure: "timeout", message: "The upstream did not answer in time." };
  }
  const detail = code ?? cause.message ?? e.message ?? "unknown error";
  return { failure: "network_error", message: `Could not reach the upstream (${detail}).` };
}

/** Read a response body up to `maxBytes`. Returns null when the body is larger than the cap. */
async function readCapped(res: Response, maxBytes: number): Promise<string | null> {
  const declared = Number(res.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > maxBytes) {
    await res.body?.cancel();
    return null;
  }
  if (!res.body) return "";
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks).toString("utf-8");
}

export async function getJson(url: string, opts: HttpOptions): Promise<HttpResult> {
  const doFetch: FetchImpl = opts.fetchImpl ?? ((u, i) => fetch(u, i));
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.config.timeoutMs);
  try {
    const res = await doFetch(url, {
      method: "GET",
      redirect: "manual",
      signal: controller.signal,
      headers: { accept: "application/json", "user-agent": USER_AGENT },
    });

    if (res.status === 404) {
      await res.body?.cancel();
      return {
        ok: false,
        failure: "not_found",
        message: "The upstream has no such resource.",
        status: 404,
      };
    }
    if (res.status === 429) {
      await res.body?.cancel();
      const resetsAt = resetTime(
        res.headers.get("retry-after"),
        (opts.now ?? (() => new Date()))(),
      );
      return {
        ok: false,
        failure: "rate_limited",
        message: resetsAt
          ? `The upstream is rate limiting this client until ${resetsAt}.`
          : "The upstream is rate limiting this client and did not say when it lifts.",
        status: 429,
        ...(resetsAt ? { resetsAt } : {}),
      };
    }
    if (res.status >= 300 && res.status < 400) {
      await res.body?.cancel();
      return {
        ok: false,
        failure: "upstream_error",
        message: `The upstream answered with a redirect (${res.status}); redirects are not followed.`,
        status: res.status,
      };
    }
    if (!res.ok) {
      await res.body?.cancel();
      return {
        ok: false,
        failure: "upstream_error",
        message: `The upstream answered with HTTP ${res.status}.`,
        status: res.status,
      };
    }

    const text = await readCapped(res, opts.config.maxBytes);
    if (text === null) {
      return {
        ok: false,
        failure: "response_too_large",
        message: `The response is larger than the ${opts.config.maxBytes}-byte limit, so it was not read.`,
        status: res.status,
      };
    }
    try {
      return { ok: true, json: JSON.parse(text), status: res.status };
    } catch {
      return {
        ok: false,
        failure: "malformed_response",
        message: "The upstream answered 200 but the body is not valid JSON.",
        status: res.status,
      };
    }
  } catch (err) {
    return { ok: false, ...classifyThrown(err) };
  } finally {
    clearTimeout(timer);
  }
}
