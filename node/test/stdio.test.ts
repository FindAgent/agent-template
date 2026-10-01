/**
 * The built server, spoken to over stdio by the real MCP SDK client. Nothing here reaches the
 * network: every call either asks for input or names an invalid crate, both of which are
 * answered before any request is made. Live behaviour against the real registry is
 * scripts/live-check.mjs.
 */

import path from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { ElicitRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { afterEach, describe, expect, it } from "vitest";
import { TOOLS } from "../src/mcp/tools.js";

const ROOT = path.resolve(import.meta.dirname, "..");
const open: Client[] = [];

async function connect(
  caps: Record<string, unknown> = {},
  env: Record<string, string> = {},
): Promise<Client> {
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [path.join(ROOT, "dist", "mcp", "server.js")],
    env: { ...(process.env as Record<string, string>), ...env },
    stderr: "pipe",
  });
  const client = new Client({ name: "test-client", version: "1" }, { capabilities: caps });
  await client.connect(transport);
  open.push(client);
  return client;
}

afterEach(async () => {
  await Promise.all(open.splice(0).map((c) => c.close()));
});

type Wire = { isError?: boolean; structuredContent?: Record<string, any>; content: any[] };
const call = (c: Client, name: string, args: Record<string, unknown> = {}) =>
  c.callTool({ name, arguments: args }) as Promise<Wire>;

describe("the served tool surface", () => {
  it("lists every tool, each bound to the panel and model-only", async () => {
    const c = await connect();
    const { tools } = await c.listTools();
    expect(tools.map((t) => t.name).sort()).toEqual(TOOLS.map((t) => t.name).sort());
    for (const t of tools) {
      const meta = t._meta as any;
      expect(meta.ui.visibility).toEqual(["model"]);
      expect(meta["openai/widgetAccessible"]).toBe(false);
      expect(meta.ui.resourceUri).toMatch(/^ui:\/\//);
      expect(t.annotations?.readOnlyHint).toBe(true);
    }
  });

  it("serves the panel as one closed document with no domain", async () => {
    const c = await connect();
    const { resources } = await c.listResources();
    expect(resources).toHaveLength(1);
    const res = resources[0]!;
    expect(res.mimeType).toBe("text/html;profile=mcp-app");
    expect((res._meta as any).ui).toEqual({ csp: {}, prefersBorder: true });
    expect((res._meta as any).ui).not.toHaveProperty("domain");
    expect((res._meta as any)["openai/widgetCSP"]).toEqual({
      connect_domains: [],
      resource_domains: [],
    });
    const read = await c.readResource({ uri: res.uri });
    const doc = read.contents[0] as { text: string; mimeType: string };
    expect(doc.mimeType).toBe("text/html;profile=mcp-app");
    expect(doc.text).toContain("ui/initialize");
  });

  it("refuses an unknown resource", async () => {
    const c = await connect();
    await expect(c.readResource({ uri: "ui://nope/none" })).rejects.toThrow();
  });
});

describe("answers over the wire", () => {
  it("a missing crate is needs_input, not an error", async () => {
    const c = await connect();
    const r = await call(c, "run_full");
    expect(r.isError).toBeUndefined();
    expect(r.structuredContent).toMatchObject({ status: "needs_input", missing: ["crate"] });
    expect(JSON.parse(r.content[0].text)).toEqual(r.structuredContent);
  });

  it("an invalid crate is isError with the class in the body, at no network cost", async () => {
    const c = await connect();
    const r = await call(c, "run_full", { crate: "Not A Package" });
    expect(r.isError).toBe(true);
    expect(r.structuredContent).toMatchObject({
      kind: "crate_failure",
      failure: "invalid_input",
      requests: { used: 0 },
    });
  });

  it("an unknown tool is an error result, not a crash", async () => {
    const c = await connect();
    const r = await call(c, "no_such_tool");
    expect(r.isError).toBe(true);
    expect(r.content[0].text).toMatch(/Unknown tool/);
    expect((await call(c, "list_capabilities")).structuredContent?.["kind"]).toBe("capabilities");
  });

  it("a bad AGENT_TIMEOUT_MS is ignored with a warning, and the server still serves", async () => {
    const c = await connect({}, { AGENT_TIMEOUT_MS: "banana" });
    expect((await call(c, "list_capabilities")).isError).toBeUndefined();
  });
});

describe("native elicitation, for a client that can show a form", () => {
  it("a run tool missing its input asks the client and re-runs with the answer", async () => {
    const c = await connect({ elicitation: {} });
    let asked = 0;
    c.setRequestHandler(ElicitRequestSchema, async () => {
      asked += 1;
      // An invalid name keeps this test off the network while proving the answer was used.
      return { action: "accept", content: { crate: "Not A Package" } };
    });
    const r = await call(c, "run_full");
    expect(asked).toBe(1);
    expect(r.structuredContent).toMatchObject({ failure: "invalid_input" });
  });

  it("a declined form falls back to the needs_input answer", async () => {
    const c = await connect({ elicitation: {} });
    c.setRequestHandler(ElicitRequestSchema, async () => ({ action: "decline" }));
    const r = await call(c, "run_full");
    expect(r.structuredContent).toMatchObject({ status: "needs_input" });
  });

  it("open_form and plan_inputs are never turned into a form: they hand over the questions", async () => {
    const c = await connect({ elicitation: {} });
    let asked = 0;
    c.setRequestHandler(ElicitRequestSchema, async () => {
      asked += 1;
      return { action: "accept", content: { crate: "Not A Package" } };
    });
    for (const tool of ["open_form", "plan_inputs"]) {
      const r = await call(c, tool);
      expect(r.structuredContent, tool).toMatchObject({ status: "needs_input" });
    }
    expect(asked).toBe(0);
  });

  it("a client without the capability gets needs_input", async () => {
    const c = await connect();
    expect((await call(c, "run_full")).structuredContent).toMatchObject({ status: "needs_input" });
  });
});
