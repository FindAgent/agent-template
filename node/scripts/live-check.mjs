#!/usr/bin/env node
/**
 * Live verification: the BUILT server over stdio, spoken to by the real MCP SDK client, against
 * the real crates.io API. No test double anywhere. Run `pnpm build` first.
 *
 *   node scripts/live-check.mjs
 *
 * It asserts on what is stable about live data (shapes, classes and facts that do not change), and prints the live figures so a person can read them. A package's
 * download count or release age is never asserted: those move.
 *
 * Exit 0: every check passed. Exit 1: a check failed. Exit 2: the registry could not be reached at
 * all, which says nothing about the agent.
 */
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function connect(env = {}) {
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [path.join(ROOT, "dist", "mcp", "server.js")],
    env: { ...process.env, ...env },
    stderr: "pipe",
  });
  const client = new Client({ name: "live-check", version: "1" }, { capabilities: {} });
  await client.connect(transport);
  return client;
}

const call = (c, name, args) => c.callTool({ name, arguments: args });
const show = (label, r) => {
  const s = r.structuredContent ?? {};
  const line =
    s.kind === "crate_check"
      ? `${s.crate}@${s.version} verdict=${s.verdict} requests=${s.requests.used}/${s.requests.budget} ` +
        s.signals
          .map((x) => `${x.id}=${x.status}${x.value === null ? "" : `(${x.value})`}`)
          .join(" ")
      : `${s.kind ?? s.status} failure=${s.failure ?? "-"} status=${s.status ?? "-"} ${s.message ?? ""}`;
  console.log(`${label.padEnd(36)} ${r.isError ? "isError " : ""}${line}`);
};

const client = await connect();
try {
  // 1. A popular crate: every signal is measured.
  const serde = await call(client, "run_full", { crate: "serde" });
  show("run_full serde", serde);
  if (serde.structuredContent?.failure === "network_error") {
    console.error("crates.io could not be reached from here; nothing was verified.");
    process.exit(2);
  }
  assert.equal(serde.isError, undefined);
  assert.equal(serde.structuredContent.kind, "crate_check");
  assert.equal(serde.structuredContent.signals.length, 6);
  assert.equal(serde.structuredContent.requests.used, 2);
  assert.deepEqual(serde.structuredContent.notChecked, []);
  assert.match(serde.structuredContent.version, /^\d+\.\d+\.\d+/);

  // 2. The same through the other tool, with a different casing: the canonical name comes back.
  const upper = await call(client, "check_crate", { crate: "SERDE_JSON", owners: false });
  show("check_crate SERDE_JSON (no owners)", upper);
  assert.equal(upper.structuredContent.crate, "serde_json");
  assert.equal(upper.structuredContent.requests.used, 1);
  assert.equal(upper.structuredContent.notChecked[0].id, "owners");

  // 3. Not found, which must be reported as not found.
  const ghost = await call(client, "run_full", { crate: "agent-template-no-such-crate-zq9x7" });
  show("run_full <no such crate>", ghost);
  assert.equal(ghost.isError, true);
  assert.equal(ghost.structuredContent.failure, "not_found");
  assert.equal(ghost.structuredContent.status, 404);
  assert.equal(ghost.structuredContent.requests.used, 1);

  // 4. Invalid input is refused before any request.
  const bad = await call(client, "run_full", { crate: "1 not/a crate" });
  show("run_full <invalid name>", bad);
  assert.equal(bad.structuredContent.failure, "invalid_input");
  assert.equal(bad.structuredContent.requests.used, 0);

  // 5. A missing argument asks, it does not fail.
  const ask = await call(client, "open_form", {});
  assert.equal(ask.structuredContent.status, "needs_input");
  console.log(
    `${"open_form".padEnd(36)} needs_input next=${ask.structuredContent.next_question.field}`,
  );
} finally {
  await client.close();
}

// 6. Limit paths against the REAL service: a knob shrinks a limit until the live answer hits it.
const tiny = await connect({ AGENT_MAX_BYTES: "50000" });
try {
  const big = await call(tiny, "run_full", { crate: "serde", owners: false });
  show("serde with AGENT_MAX_BYTES=50000", big);
  assert.equal(big.isError, true);
  assert.equal(big.structuredContent.failure, "response_too_large");
} finally {
  await tiny.close();
}

const impatient = await connect({ AGENT_TIMEOUT_MS: "1" });
try {
  const slow = await call(impatient, "run_full", { crate: "serde" });
  show("serde with AGENT_TIMEOUT_MS=1", slow);
  assert.equal(slow.isError, true);
  assert.equal(slow.structuredContent.failure, "timeout");
} finally {
  await impatient.close();
}

console.log("live check ok");
