#!/usr/bin/env node
/**
 * Validate findagent.json against the REAL FindAgent schema (`agentManifestV12Schema`), not a copy.
 * Needs a checkout of the findagent repo with its dependencies installed, because the schema is
 * TypeScript source that lives there and is not published.
 *
 *   FINDAGENT_REPO=/path/to/findagent node scripts/validate-findagent-json.mjs
 *   (MANIFEST_FILE=/path/to/other/findagent.json checks a different file, e.g. the Python variant's)
 *
 * It re-runs itself through tsx so that the schema's .ts source can be imported.
 */
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = fileURLToPath(import.meta.url);
const ROOT = path.resolve(path.dirname(here), "..");

if (process.argv[2] !== "--inner") {
  const repo = process.env.FINDAGENT_REPO;
  if (!repo) {
    console.error(
      "Set FINDAGENT_REPO to a checkout of the findagent repository (with pnpm install run).",
    );
    process.exit(2);
  }
  const tsx = path.join(ROOT, "node_modules", "tsx", "dist", "cli.mjs");
  const run = spawnSync(process.execPath, [tsx, here, "--inner", path.resolve(repo)], {
    stdio: "inherit",
    cwd: ROOT,
  });
  process.exit(run.status ?? 1);
}

const repo = process.argv[3];
const schemaFile = path.join(repo, "packages", "schema", "src", "manifest.ts");
const { agentManifestV12Schema } = await import(pathToFileURL(schemaFile).href);
const manifest = JSON.parse(
  readFileSync(process.env.MANIFEST_FILE ?? path.join(ROOT, "findagent.json"), "utf8"),
);
const result = agentManifestV12Schema.safeParse(manifest);
if (result.success) {
  console.log(
    `findagent.json is valid against agentManifestV12Schema (${repo}): ` +
      `kind=${result.data.kind} runtime=${result.data.runtime.kind}@${result.data.runtime.version} ` +
      `allowed_hosts=${result.data.allowed_hosts.join(",")} skills=${result.data.skills?.length ?? 0}`,
  );
  process.exit(0);
}
console.error("findagent.json does NOT validate:");
console.error(JSON.stringify(result.error.issues, null, 2));
process.exit(1);
