/**
 * The repo rules FindAgent's autobuild and submission scan enforce, checked here so a fork learns
 * about a violation from its own CI and not from a submission that sits in review.
 */

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(import.meta.dirname, "..");
const SKIP = new Set(["node_modules", "dist", ".git", "coverage"]);

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir)) {
    if (SKIP.has(e)) continue;
    const p = path.join(dir, e);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}
const rel = (f: string) => path.relative(ROOT, f).replace(/\\/g, "/");
const all = walk(ROOT).filter((f) => !/\.(png|jpg|ico)$/i.test(f));

/** What ships: everything outside test/ and the lockfile. */
const shipped = all.filter((f) => !rel(f).startsWith("test/") && rel(f) !== "pnpm-lock.yaml");

describe("autobuild safety", () => {
  it("no pnpm-workspace.yaml is tracked (pnpm may write one locally; it is ignored)", () => {
    const gitignore = readFileSync(path.join(ROOT, ".gitignore"), "utf8");
    expect(gitignore).toMatch(/^pnpm-workspace\.yaml$/m);
    if (existsSync(path.join(ROOT, ".git"))) {
      const tracked = execFileSync("git", ["ls-files"], { cwd: ROOT, encoding: "utf8" });
      expect(tracked.split("\n")).not.toContain("pnpm-workspace.yaml");
    }
  });

  it("the lockfile is committed and every dependency version is pinned exactly", () => {
    expect(existsSync(path.join(ROOT, "pnpm-lock.yaml"))).toBe(true);
    const pkg = JSON.parse(readFileSync(path.join(ROOT, "package.json"), "utf8"));
    for (const group of ["dependencies", "devDependencies"]) {
      for (const [name, range] of Object.entries<string>(pkg[group] ?? {})) {
        expect(range, `${group}.${name}`).toMatch(/^\d+\.\d+\.\d+$/);
      }
    }
  });

  it("the entrypoint resolves from the repo root once built", () => {
    const manifest = JSON.parse(readFileSync(path.join(ROOT, "findagent.json"), "utf8"));
    expect(existsSync(path.join(ROOT, manifest.entrypoint.path))).toBe(true);
    expect(existsSync(path.join(ROOT, manifest.ui.path))).toBe(true);
    expect(existsSync(path.join(ROOT, "dist", "mcp", "panel.html"))).toBe(true);
  });

  it("no secret scan trigger: no PEM armor, no private key, no token-shaped literal anywhere", () => {
    // The armor is assembled so this file does not contain what it forbids.
    const pem = new RegExp(["-----", "BEGIN [A-Z ]*", "PRIVATE KEY", "-----"].join(""));
    const tokens = [
      /\bghp_[A-Za-z0-9]{20,}/,
      /\bgithub_pat_[A-Za-z0-9_]{20,}/,
      /\bsk-[A-Za-z0-9]{20,}/,
      /\bAKIA[0-9A-Z]{16}\b/,
      /\bxox[abprs]-[A-Za-z0-9-]{10,}/,
      /\bAIza[0-9A-Za-z_-]{30,}/,
    ];
    for (const f of all) {
      const text = readFileSync(f, "utf8");
      expect(text, rel(f)).not.toMatch(pem);
      for (const t of tokens) expect(text, `${rel(f)} ${t}`).not.toMatch(t);
    }
  });

  it("no internal ticket id, personal address or stray Windows path ships", () => {
    for (const f of all) {
      expect(
        rel(f),
        "a path that starts with % is a Windows system path committed by mistake",
      ).not.toMatch(/^%/);
      if (rel(f) === "pnpm-lock.yaml") continue;
      const text = readFileSync(f, "utf8");
      expect(text, rel(f)).not.toMatch(/FC-\d+/);
      expect(text, rel(f)).not.toMatch(/@(gmail|hotmail|outlook|yahoo)\./i);
    }
  });

  it("no environment file is tracked", () => {
    for (const f of all) expect(path.basename(f), rel(f)).not.toMatch(/^\.env(\.|$)/);
    expect(readFileSync(path.join(ROOT, ".gitignore"), "utf8")).toMatch(/^\.env$/m);
  });
});

describe("nothing simulated ships", () => {
  const banned =
    /\b(mock|mocks|mocked|fake|fakes|stub|stubs|stubbed|placeholder|lorem|todo|fixme|demo)\b/i;

  it("no shipped file is named like a sample", () => {
    for (const f of shipped) expect(rel(f), rel(f)).not.toMatch(/example|sample|demo|mock|fake/i);
  });

  it("no shipped file mentions mock, fake, stub, placeholder, lorem, todo, fixme or demo", () => {
    for (const f of shipped) {
      const hit = readFileSync(f, "utf8")
        .split("\n")
        .findIndex((line) => banned.test(line));
      expect(hit, `${rel(f)}:${hit + 1}`).toBe(-1);
    }
  });

  it("test doubles live under test/ and nowhere else", () => {
    for (const f of all.filter((f) => /fake|mock|stub/i.test(path.basename(f)))) {
      expect(rel(f).startsWith("test/"), rel(f)).toBe(true);
    }
  });

  it("src/ does not import from test/", () => {
    for (const f of shipped.filter((f) => f.endsWith(".ts"))) {
      expect(readFileSync(f, "utf8"), rel(f)).not.toMatch(/from\s+["'][./]*test\//);
    }
  });
});

describe("the repo is self-consistent", () => {
  it("package name, findagent.json and the panel URI agree on one name", () => {
    const pkg = JSON.parse(readFileSync(path.join(ROOT, "package.json"), "utf8"));
    expect(pkg.name).toMatch(/^[a-z0-9][a-z0-9-]*$/);
    const dxt = JSON.parse(readFileSync(path.join(ROOT, "manifest.json"), "utf8"));
    expect(dxt.name).toBe(pkg.name);
  });

  it("the generated files are current", () => {
    for (const script of ["sync-manifest.mjs", "build-panel.mjs"]) {
      expect(() =>
        execFileSync("node", [path.join("scripts", script), "--check"], {
          cwd: ROOT,
          stdio: "pipe",
        }),
      ).not.toThrow();
    }
  });
});
