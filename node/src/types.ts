/** What a check returns. Every shape carries `kind` so a panel and a test can tell them apart. */

export type SignalStatus = "ok" | "warn" | "risk" | "not_checked";

export interface Signal {
  id: string;
  label: string;
  status: SignalStatus;
  /** The measured value, or null when the signal was not checked. */
  value: string | number | boolean | null;
  /** One sentence: what was measured and what the status rule said about it. */
  detail: string;
  /** The API field the value came from, so a finding can be walked back to its source. */
  source: string;
  /** Why the signal was not checked. Present only when status is "not_checked". */
  reason?: string;
}

export type Verdict = "healthy" | "watch" | "risky" | "unknown";

/** Upstream requests spent by one check, against what it was allowed. */
export interface RequestCount {
  used: number;
  budget: number;
}

export interface CrateReport {
  kind: "crate_check";
  ok: true;
  crate: string;
  version: string;
  checkedAt: string;
  verdict: Verdict;
  verdictReason: string;
  summary: string;
  signals: Signal[];
  /** Signals that could not be measured, with the reason. Never scored as zero, never dropped. */
  notChecked: Array<{ id: string; reason: string }>;
  requests: RequestCount;
  method: string;
}

/**
 * Each class is a different condition with a different next step. They are never merged:
 * "not found" is a statement about the world and must never be said for a refusal.
 */
export type FailureClass =
  | "invalid_input"
  | "not_found"
  | "rate_limited"
  | "timeout"
  | "network_error"
  | "upstream_error"
  | "malformed_response"
  | "response_too_large";

export interface CrateFailure {
  kind: "crate_failure";
  ok: false;
  crate: string;
  failure: FailureClass;
  message: string;
  /** HTTP status when the upstream answered. */
  status?: number;
  /** When a rate limit lifts, ISO-8601. Present only for rate_limited and only when the upstream said. */
  resetsAt?: string;
  requests: RequestCount;
}

export type CrateResult = CrateReport | CrateFailure;
