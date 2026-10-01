/**
 * Egress is default-deny on the platform: a host the code calls that is not in `allowed_hosts` is a
 * request the sandbox refuses at run time. These tests make the two sides agree before it ships,
 * in both directions: nothing is called that is not declared, and nothing is declared that is not
 * called.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir)) {
    const p = path.join(dir, e);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

/** Source with comments removed, so a host named in prose is not read as a host that is called. */
function code(file: string): string {
  return readFileSync(file, "utf8")
    .replace(/\r\n/g, "\n")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const srcFiles = walk(path.join(ROOT, "src")).filter((f) => f.endsWith(".ts"));
const declared: string[] = JSON.parse(readFileSync(path.join(ROOT, "findagent.json"), "utf8"))[
  "allowed_hosts"
];

function hostsCalled(): string[] {
  const found = new Set<string>();
  for (const f of srcFiles) {
    const text = code(f);
    for (const m of text.matchAll(/https?:\/\/([a-z0-9.-]+)/gi)) found.add(m[1]!.toLowerCase());
    // A host constant (`export const FOO_HOST = "registry.npmjs.org"`) is how a URL is built.
    for (const m of text.matchAll(/_HOST\s*=\s*"([a-z0-9.-]+)"/gi)) found.add(m[1]!.toLowerCase());
  }
  return [...found].sort();
}

describe("allowed_hosts", () => {
  it("is exactly the set of hosts the source calls", () => {
    expect(hostsCalled()).toEqual([...declared].sort());
  });

  it("holds plain host names: no scheme, path, port, wildcard or address", () => {
    for (const h of declared) {
      expect(h).toMatch(/^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/);
      expect(h).not.toMatch(/^\d+\.\d+\.\d+\.\d+$/);
    }
  });

  it("is not empty, because the agent does call out", () => {
    expect(declared.length).toBeGreaterThan(0);
  });
});

describe("a caller can never choose where a request goes", () => {
  it("only src/http.ts touches the network, and only through one function", () => {
    const users = srcFiles.filter((f) => /\bfetch\s*\(/.test(code(f)));
    expect(users.map((f) => path.relative(ROOT, f).replace(/\\/g, "/"))).toEqual(["src/http.ts"]);
  });

  it("no URL is built from a tool argument without going through the name check", () => {
    const crates = code(path.join(ROOT, "src", "crates.ts"));
    // every URL in crates.ts is `https://<constant host>/<encoded path>`
    const urls = [...crates.matchAll(/`(https:\/\/[^`]*)`/g)].map((m) => m[1]!);
    expect(urls.length).toBeGreaterThan(0);
    for (const u of urls) expect(u).toMatch(/^https:\/\/\$\{[A-Z_]+HOST\}\//);
    expect(crates).toContain("encodeURIComponent(name)");
  });

  it("redirects are never followed", () => {
    expect(code(path.join(ROOT, "src", "http.ts"))).toMatch(/redirect:\s*"manual"/);
  });

  it("no tool takes a URL or a host as input", () => {
    const tools = code(path.join(ROOT, "src", "mcp", "tools.ts"));
    expect(tools).not.toMatch(/\b(url|host|endpoint|baseUrl)\s*:\s*\{/i);
  });
});
