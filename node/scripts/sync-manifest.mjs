#!/usr/bin/env node
/**
 * Keep the two manifests identical to what the server actually registers, so a listing can never
 * advertise a tool the server does not have (or hide one it does).
 *
 *   findagent.json  the FindAgent contract. You edit its top-level fields by hand (name, tagline,
 *                   description, example_prompts, tags, allowed_hosts, credential_slots ...);
 *                   this script rewrites `version` and `skills[]` from package.json and the
 *                   compiled tools.
 *   manifest.json   the Desktop Extension (DXT) manifest. It is GENERATED, never edited: every
 *                   field comes from findagent.json, package.json and the compiled tools, so the
 *                   two files cannot disagree. FindAgent reads findagent.json and, where it is
 *                   absent, falls back to a contract synthesised from manifest.json that DROPS
 *                   declared credential hosts, so findagent.json is the one that matters.
 *
 *   node scripts/sync-manifest.mjs          rewrite both from package.json + dist/mcp/tools.js
 *   node scripts/sync-manifest.mjs --check  exit 1 if either file is out of date
 *
 * Run `pnpm build` first: this reads the compiled tools.
 */
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const check = process.argv.includes("--check");
const { TOOLS } = await import(pathToFileURL(path.join(ROOT, "dist", "mcp", "tools.js")).href);

const readJson = (f) => JSON.parse(readFileSync(path.join(ROOT, f), "utf8"));
const fmt = (o) => JSON.stringify(o, null, 2) + "\n";

const pkg = readJson("package.json");
const findagent = readJson("findagent.json");
findagent.version = pkg.version;
findagent.skills = TOOLS.map((t) => ({
  id: t.name,
  name: t.name,
  description: t.description,
  input_schema: t.inputSchema,
}));

const repoUrl = pkg.repository.url.replace(/\.git$/, "");
const dxt = {
  dxt_version: "0.1",
  name: pkg.name,
  display_name: findagent.name,
  version: pkg.version,
  description: findagent.tagline,
  long_description: findagent.description,
  author: pkg.author,
  homepage: repoUrl,
  repository: pkg.repository,
  license: pkg.license,
  keywords: findagent.tags,
  server: {
    type: "node",
    entry_point: findagent.entrypoint.path,
    mcp_config: { command: "node", args: [`\${__dirname}/${findagent.entrypoint.path}`] },
  },
  tools: TOOLS.map((t) => ({ name: t.name, description: t.description })),
  tools_generated: false,
  compatibility: { platforms: ["darwin", "linux", "win32"], runtimes: { node: pkg.engines.node } },
};

let stale = false;
for (const [file, next] of [
  ["findagent.json", findagent],
  ["manifest.json", dxt],
]) {
  const target = path.join(ROOT, file);
  let current = "";
  try {
    current = readFileSync(target, "utf8").replace(/\r\n/g, "\n");
  } catch {
    /* a missing file counts as stale */
  }
  if (current === fmt(next)) continue;
  if (check) {
    console.error(`${file} is out of date; run: pnpm sync:manifest`);
    stale = true;
  } else {
    writeFileSync(target, fmt(next));
    console.log(`updated ${file}`);
  }
}
process.exit(stale ? 1 : 0);
