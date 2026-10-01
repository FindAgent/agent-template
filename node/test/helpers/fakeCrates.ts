/**
 * A fetch double and fixture builders for tests. This lives in test/ only: nothing under src/ knows
 * it exists. Routes are keyed by `host + pathname`; every call is recorded so a test can assert the
 * request budget, the method and the host.
 */

import { DEFAULTS, type Config } from "../../src/config.js";
import type { FetchImpl } from "../../src/http.js";

export interface Reply {
  status?: number;
  body?: unknown;
  rawBody?: string;
  headers?: Record<string, string>;
}

export type Route = Reply | (() => Reply | Promise<Reply>);

export interface Fake {
  fetch: FetchImpl;
  calls: Array<{ url: URL; init: RequestInit | undefined }>;
}

/** The default limits with no pause between requests, so a test does not sit through the spacing. */
export const TEST_CONFIG: Config = { ...DEFAULTS, spacingMs: 0 };

export const NOW = new Date("2026-10-01T12:00:00Z");
export const daysAgo = (n: number): string =>
  new Date(NOW.getTime() - n * 86_400_000).toISOString();

export function fakeCrates(routes: Record<string, Route>): Fake {
  const calls: Fake["calls"] = [];
  const fetch: FetchImpl = async (input, init) => {
    const url = new URL(input);
    calls.push({ url, init });
    const route = routes[`${url.host}${url.pathname}`];
    if (!route) {
      return new Response(
        JSON.stringify({ errors: [{ detail: `no route for ${url.pathname}` }] }),
        {
          status: 404,
        },
      );
    }
    const reply = typeof route === "function" ? await route() : route;
    return new Response(reply.rawBody ?? JSON.stringify(reply.body ?? {}), {
      status: reply.status ?? 200,
      headers: { "content-type": "application/json", ...(reply.headers ?? {}) },
    });
  };
  return { fetch, calls };
}

export interface CrateOptions {
  name?: string;
  latest?: string;
  publishedDaysAgo?: number;
  yanked?: boolean;
  yankMessage?: string | null;
  license?: string | null;
  repository?: string | null;
  recentDownloads?: number | null;
}

/** A crates.io crate document, shaped like the real one for the fields the check reads. */
export function crateDoc(o: CrateOptions = {}): Record<string, unknown> {
  const name = o.name ?? "acme-widget";
  const latest = o.latest ?? "2.0.0";
  return {
    crate: {
      id: name,
      name,
      max_version: latest,
      max_stable_version: latest,
      default_version: latest,
      repository: o.repository === undefined ? `https://github.com/acme/${name}` : o.repository,
      recent_downloads: o.recentDownloads === undefined ? 250_000 : o.recentDownloads,
      downloads: 9_000_000,
    },
    versions: [
      {
        num: "1.0.0",
        yanked: false,
        created_at: daysAgo(900),
        license: "MIT",
      },
      {
        num: latest,
        yanked: o.yanked ?? false,
        yank_message: o.yankMessage ?? null,
        created_at: daysAgo(o.publishedDaysAgo ?? 30),
        license: o.license === undefined ? "MIT OR Apache-2.0" : o.license,
      },
    ],
  };
}

export function routesFor(
  name: string,
  doc: Record<string, unknown>,
  owners: Reply | number = 3,
): Record<string, Route> {
  const own: Reply =
    typeof owners === "number"
      ? { body: { users: Array.from({ length: owners }, (_, i) => ({ id: i, login: `o${i}` })) } }
      : owners;
  return {
    [`crates.io/api/v1/crates/${name}`]: { body: doc },
    [`crates.io/api/v1/crates/${name}/owners`]: own,
  };
}
