/**
 * Pure, deterministic signals: no I/O, no clock of its own, no model. Every status comes from a
 * rule written down here, and every threshold is a number a fork is expected to replace for its
 * own domain. A signal that could not be measured is "not_checked" with a reason; it is never
 * scored as zero and never left out.
 */

import type { CrateDoc } from "./crates.js";
import type { Signal, SignalStatus, Verdict } from "./types.js";

export const THRESHOLDS = {
  /** Latest release older than this many days: warn. */
  staleWarnDays: 365,
  /** Latest release older than this many days: risk. */
  staleRiskDays: 730,
  /** Fewer owners than this: warn (a crate with one owner has no second pair of hands). */
  minOwners: 2,
  /** Fewer downloads than this in the last 90 days: warn. */
  lowRecentDownloads: 1000,
} as const;

const DAY_MS = 86_400_000;

export type OwnersInput =
  { state: "skipped" } | { state: "ok"; value: number } | { state: "failed"; reason: string };

const OWNERS_SOURCE = "owners (crates.io /owners)";
const DOWNLOADS_SOURCE = "crate.recent_downloads";
const AGE_SOURCE = "versions[latest].created_at";

/**
 * What each signal checks, in the words list_capabilities shows: one entry per signal, in the order
 * buildSignals emits them. test/signals.test.ts keeps the two in step.
 */
export const SIGNAL_RULES: ReadonlyArray<{ id: string; rule: string; field: string }> = [
  {
    id: "latest_release_age",
    rule: `warn at ${THRESHOLDS.staleWarnDays} days, risk at ${THRESHOLDS.staleRiskDays} days since the latest version was published`,
    field: AGE_SOURCE,
  },
  {
    id: "yanked",
    rule: "risk when the latest version has been yanked",
    field: "versions[latest].yanked",
  },
  {
    id: "license",
    rule: "warn when the latest version declares no license",
    field: "versions[latest].license",
  },
  {
    id: "repository",
    rule: "warn when the crate links no source repository",
    field: "crate.repository",
  },
  {
    id: "recent_downloads",
    rule: `warn below ${THRESHOLDS.lowRecentDownloads} downloads in the last 90 days`,
    field: DOWNLOADS_SOURCE,
  },
  { id: "owners", rule: `warn below ${THRESHOLDS.minOwners} owners`, field: OWNERS_SOURCE },
];

function notChecked(id: string, label: string, source: string, reason: string): Signal {
  return {
    id,
    label,
    status: "not_checked",
    value: null,
    detail: `Not checked: ${reason}.`,
    source,
    reason,
  };
}

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

export function buildSignals(c: CrateDoc, owners: OwnersInput, now: Date): Signal[] {
  const signals: Signal[] = [];

  // Latest release age
  const publishedMs = Date.parse(c.publishedAt);
  if (Number.isNaN(publishedMs)) {
    signals.push(
      notChecked(
        "latest_release_age",
        "Latest release age",
        AGE_SOURCE,
        "the publish time of the latest version could not be read as a date",
      ),
    );
  } else {
    const days = Math.max(0, Math.floor((now.getTime() - publishedMs) / DAY_MS));
    const status: SignalStatus =
      days >= THRESHOLDS.staleRiskDays ? "risk" : days >= THRESHOLDS.staleWarnDays ? "warn" : "ok";
    signals.push({
      id: "latest_release_age",
      label: "Latest release age",
      status,
      value: days,
      detail: `Version ${c.version} was published ${days} days ago (warn at ${THRESHOLDS.staleWarnDays}, risk at ${THRESHOLDS.staleRiskDays}).`,
      source: AGE_SOURCE,
    });
  }

  // Yanked
  signals.push({
    id: "yanked",
    label: "Yanked",
    status: c.yanked ? "risk" : "ok",
    value: c.yanked,
    detail: c.yanked
      ? `Version ${c.version} has been yanked${c.yankMessage ? `: ${c.yankMessage}` : ""}`
      : `Version ${c.version} has not been yanked.`,
    source: "versions[latest].yanked",
  });

  // License
  signals.push({
    id: "license",
    label: "License",
    status: c.license === null ? "warn" : "ok",
    value: c.license,
    detail:
      c.license === null
        ? "The latest version declares no license."
        : `The latest version declares the license ${c.license}.`,
    source: "versions[latest].license",
  });

  // Source repository
  signals.push({
    id: "repository",
    label: "Source repository",
    status: c.repository === null ? "warn" : "ok",
    value: c.repository,
    detail:
      c.repository === null
        ? "The crate links no source repository, so its code cannot be audited from here."
        : `The crate links its source at ${c.repository}.`,
    source: "crate.repository",
  });

  // Recent downloads
  if (c.recentDownloads === null) {
    signals.push(
      notChecked(
        "recent_downloads",
        "Recent downloads",
        DOWNLOADS_SOURCE,
        "crates.io reports no recent download count for this crate",
      ),
    );
  } else {
    signals.push({
      id: "recent_downloads",
      label: "Recent downloads",
      status: c.recentDownloads < THRESHOLDS.lowRecentDownloads ? "warn" : "ok",
      value: c.recentDownloads,
      detail: `${c.recentDownloads} downloads in the last 90 days (warn below ${THRESHOLDS.lowRecentDownloads}).`,
      source: DOWNLOADS_SOURCE,
    });
  }

  // Owners
  if (owners.state === "ok") {
    signals.push({
      id: "owners",
      label: "Owners",
      status: owners.value < THRESHOLDS.minOwners ? "warn" : "ok",
      value: owners.value,
      detail: `${owners.value} ${plural(owners.value, "owner", "owners")} can publish (warn below ${THRESHOLDS.minOwners}).`,
      source: OWNERS_SOURCE,
    });
  } else {
    signals.push(
      notChecked(
        "owners",
        "Owners",
        OWNERS_SOURCE,
        owners.state === "skipped" ? "owners were switched off for this run" : owners.reason,
      ),
    );
  }

  return signals;
}

/** The fewest signals that must be measured before a verdict is given at all. */
export const MIN_CHECKED_FOR_VERDICT = 3;

export function verdictFor(signals: Signal[]): { verdict: Verdict; reason: string } {
  const checked = signals.filter((s) => s.status !== "not_checked");
  if (checked.length < MIN_CHECKED_FOR_VERDICT) {
    return {
      verdict: "unknown",
      reason: `Only ${checked.length} of ${signals.length} signals could be measured; at least ${MIN_CHECKED_FOR_VERDICT} are needed for a verdict.`,
    };
  }
  const risks = checked.filter((s) => s.status === "risk");
  if (risks.length > 0) {
    return {
      verdict: "risky",
      reason: `Risk: ${risks.map((s) => s.label.toLowerCase()).join(", ")}.`,
    };
  }
  const warns = checked.filter((s) => s.status === "warn");
  if (warns.length > 0) {
    return {
      verdict: "watch",
      reason: `Worth a look: ${warns.map((s) => s.label.toLowerCase()).join(", ")}.`,
    };
  }
  return {
    verdict: "healthy",
    reason: `All ${checked.length} measured signals are within their thresholds.`,
  };
}

/** A detail that quotes upstream text may end without punctuation; a sentence always does. */
function sentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

/** One deterministic paragraph: what is wrong, or that nothing is. */
export function summarize(
  crate: string,
  version: string,
  signals: Signal[],
  verdict: Verdict,
): string {
  const concerns = signals.filter((s) => s.status === "risk" || s.status === "warn");
  const unmeasured = signals.filter((s) => s.status === "not_checked");
  const head =
    concerns.length === 0
      ? `${crate}@${version}: no signal raised a concern (verdict: ${verdict}).`
      : `${crate}@${version} (verdict: ${verdict}): ${concerns.map((s) => sentence(s.detail)).join(" ")}`;
  return unmeasured.length === 0
    ? head
    : `${head} Not checked: ${unmeasured.map((s) => s.label.toLowerCase()).join(", ")}.`;
}
