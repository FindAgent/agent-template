/**
 * The two upstream reads, each validated at the boundary with zod. A body that does not have the
 * fields a signal needs is `malformed_response`, never a signal quietly computed from nothing.
 *
 * Host (keep in sync with `allowed_hosts` in findagent.json; test/egress.test.ts enforces it):
 *   crates.io   the crate document and its owners list
 *
 * The crate name is the only caller-supplied part of a URL. It is validated against crates.io's
 * own naming rule and put in the PATH, so a caller can never choose the host.
 */

import { z } from "zod";
import { getJson, type HttpOptions } from "./http.js";
import type { FailureClass } from "./types.js";

export const CRATES_HOST = "crates.io";

/** crates.io's rule for a crate name: ASCII letters, digits, - and _, starting with a letter, at most 64. */
const NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;

export type NameCheck = { ok: true; name: string } | { ok: false; message: string };

export function parseCrateName(input: unknown): NameCheck {
  if (typeof input !== "string" || input.trim() === "") {
    return { ok: false, message: "crate must be a non-empty string." };
  }
  const name = input.trim();
  if (!NAME_PATTERN.test(name)) {
    return {
      ok: false,
      message: `${JSON.stringify(name.slice(0, 80))} is not a valid crate name (ASCII letters, digits, - and _, starting with a letter, at most 64 characters).`,
    };
  }
  return { ok: true, name };
}

const crateUrl = (name: string, suffix = ""): string =>
  `https://${CRATES_HOST}/api/v1/crates/${encodeURIComponent(name)}${suffix}`;

const versionSchema = z
  .object({
    num: z.string(),
    yanked: z.boolean(),
    created_at: z.string(),
    license: z.string().nullable().optional(),
    yank_message: z.string().nullable().optional(),
  })
  .passthrough();

const crateDocSchema = z
  .object({
    crate: z
      .object({
        name: z.string(),
        max_version: z.string().nullable().optional(),
        max_stable_version: z.string().nullable().optional(),
        default_version: z.string().nullable().optional(),
        repository: z.string().nullable().optional(),
        recent_downloads: z.number().int().nonnegative().nullable().optional(),
      })
      .passthrough(),
    versions: z.array(z.unknown()),
  })
  .passthrough();

export interface CrateDoc {
  name: string;
  version: string;
  /** ISO publish time of the version the checks are about. */
  publishedAt: string;
  yanked: boolean;
  yankMessage: string | null;
  license: string | null;
  repository: string | null;
  /** Downloads in the last 90 days, or null when crates.io gave none. */
  recentDownloads: number | null;
}

export type Failed = {
  ok: false;
  failure: Exclude<FailureClass, "invalid_input">;
  message: string;
  status?: number;
  resetsAt?: string;
};

export async function fetchCrate(
  name: string,
  opts: HttpOptions,
): Promise<{ ok: true; value: CrateDoc } | Failed> {
  const res = await getJson(crateUrl(name), opts);
  if (!res.ok) {
    return res.failure === "not_found"
      ? { ...res, message: `crates.io has no crate named ${name}.` }
      : res;
  }
  const doc = crateDocSchema.safeParse(res.json);
  if (!doc.success) {
    return {
      ok: false,
      failure: "malformed_response",
      message: `The crate document is missing a field this check needs (${doc.error.issues[0]?.path.join(".") || "root"}).`,
      status: res.status,
    };
  }
  const { crate } = doc.data;
  // The newest stable release, else the newest of any kind: the one a dependent would pick up.
  const target = crate.max_stable_version ?? crate.max_version ?? crate.default_version ?? null;
  const match = doc.data.versions
    .map((v) => versionSchema.safeParse(v))
    .find((v) => v.success && v.data.num === target);
  if (target === null || !match || !match.success) {
    return {
      ok: false,
      failure: "malformed_response",
      message: "The crate document does not list the version it names as the latest.",
      status: res.status,
    };
  }
  const version = match.data;
  return {
    ok: true,
    value: {
      name: crate.name,
      version: version.num,
      publishedAt: version.created_at,
      yanked: version.yanked,
      yankMessage: version.yank_message ?? null,
      license: version.license?.trim() ? version.license.trim() : null,
      repository: crate.repository?.trim() ? crate.repository.trim() : null,
      recentDownloads: crate.recent_downloads ?? null,
    },
  };
}

const ownersSchema = z.object({ users: z.array(z.unknown()) }).passthrough();

/** How many owners (people and teams) can publish the crate. */
export async function fetchOwnerCount(
  name: string,
  opts: HttpOptions,
): Promise<{ ok: true; value: number } | Failed> {
  const res = await getJson(crateUrl(name, "/owners"), opts);
  if (!res.ok) return res;
  const body = ownersSchema.safeParse(res.json);
  if (!body.success) {
    return {
      ok: false,
      failure: "malformed_response",
      message: "The owners answer has no `users` list.",
      status: res.status,
    };
  }
  return { ok: true, value: body.data.users.length };
}
