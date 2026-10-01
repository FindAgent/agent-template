/**
 * The check: validate the name, read the crate, optionally read its owners, build the signals.
 * Two requests at most, and the report says how many it used. The deterministic result is complete
 * on its own; no model is involved anywhere.
 */

import type { Config } from "./config.js";
import { fetchCrate, fetchOwnerCount, parseCrateName } from "./crates.js";
import type { FetchImpl } from "./http.js";
import { buildSignals, summarize, verdictFor, type OwnersInput } from "./signals.js";
import type { CrateFailure, CrateReport, CrateResult, FailureClass } from "./types.js";

export interface CheckOptions {
  config: Config;
  /** Whether to spend the second request on the owners list. Default true. */
  owners?: boolean;
  fetchImpl?: FetchImpl;
  now?: () => Date;
  /** Test seam: defaults to a real timer. */
  sleep?: (ms: number) => Promise<void>;
}

const realSleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** The most upstream requests one check may spend. */
export const REQUEST_BUDGET = 2;

const METHOD =
  "Deterministic rules over the public crates.io API. GET only, no credentials, no model. The thresholds are listed by list_capabilities.";

export function failure(
  crate: string,
  failureClass: FailureClass,
  message: string,
  used: number,
  extra: { status?: number; resetsAt?: string } = {},
): CrateFailure {
  return {
    kind: "crate_failure",
    ok: false,
    crate,
    failure: failureClass,
    message,
    ...(extra.status === undefined ? {} : { status: extra.status }),
    ...(extra.resetsAt === undefined ? {} : { resetsAt: extra.resetsAt }),
    requests: { used, budget: REQUEST_BUDGET },
  };
}

export async function checkCrate(input: unknown, opts: CheckOptions): Promise<CrateResult> {
  const parsed = parseCrateName(input);
  if (!parsed.ok) {
    return failure(
      typeof input === "string" ? input.trim().slice(0, 80) : "",
      "invalid_input",
      parsed.message,
      0,
    );
  }
  const name = parsed.name;
  const http = {
    config: opts.config,
    ...(opts.fetchImpl ? { fetchImpl: opts.fetchImpl } : {}),
    ...(opts.now ? { now: opts.now } : {}),
  };
  const now = (opts.now ?? (() => new Date()))();

  let used = 1;
  const doc = await fetchCrate(name, http);
  if (!doc.ok) {
    return failure(name, doc.failure, doc.message, used, {
      ...(doc.status === undefined ? {} : { status: doc.status }),
      ...(doc.resetsAt === undefined ? {} : { resetsAt: doc.resetsAt }),
    });
  }

  let owners: OwnersInput = { state: "skipped" };
  if (opts.owners !== false) {
    used += 1;
    // The upstream asks for at most one request a second: wait before the second one.
    if (opts.config.spacingMs > 0) await (opts.sleep ?? realSleep)(opts.config.spacingMs);
    const o = await fetchOwnerCount(name, http);
    owners = o.ok
      ? { state: "ok", value: o.value }
      : {
          state: "failed",
          // The owners read is one signal. Its failure is reported as that signal being not
          // checked, with the failure class kept in the reason; it does not fail the whole check.
          reason: `${o.failure}: ${o.message}`,
        };
  }

  const signals = buildSignals(doc.value, owners, now);
  const { verdict, reason } = verdictFor(signals);
  const report: CrateReport = {
    kind: "crate_check",
    ok: true,
    crate: doc.value.name,
    version: doc.value.version,
    checkedAt: now.toISOString(),
    verdict,
    verdictReason: reason,
    summary: summarize(doc.value.name, doc.value.version, signals, verdict),
    signals,
    notChecked: signals
      .filter((s) => s.status === "not_checked")
      .map((s) => ({ id: s.id, reason: s.reason ?? "not measured" })),
    requests: { used, budget: REQUEST_BUDGET },
    method: METHOD,
  };
  return report;
}
