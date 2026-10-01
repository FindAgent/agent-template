import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  PANEL_RESOURCE_URI,
  RUNNING_TOOLS,
  TOOLS,
  dispatchTool,
  panelBinding,
  toCallToolResult,
  toolsWithPanel,
} from "../src/mcp/tools.js";
import { TEST_CONFIG, NOW, crateDoc, fakeCrates, routesFor } from "./helpers/fakeCrates.js";

const ROOT = path.resolve(import.meta.dirname, "..");
const json = (f: string) =>
  JSON.parse(readFileSync(path.join(ROOT, f), "utf8")) as Record<string, any>;
const names = TOOLS.map((t) => t.name);

/** The six tools the platform requires of every code agent. */
const ENTRY_TOOLS = [
  "plan_inputs",
  "open_form",
  "run_form",
  "run_full",
  "list_capabilities",
  "discover_intent",
];

const seam = (fake: ReturnType<typeof fakeCrates>) => ({
  check: { config: TEST_CONFIG, fetchImpl: fake.fetch, now: () => NOW },
});

describe("the six entry tools", () => {
  it("all exist, and the only other tool is the capability", () => {
    for (const t of ENTRY_TOOLS) expect(names, `missing entry tool ${t}`).toContain(t);
    expect(names.filter((n) => !ENTRY_TOOLS.includes(n))).toEqual(["check_crate"]);
  });

  it("every tool has a description that says when to use it, an object schema and read-only annotations", () => {
    for (const t of TOOLS) {
      expect(t.description!.length, t.name).toBeGreaterThan(40);
      expect(t.inputSchema.type).toBe("object");
      for (const p of Object.values(t.inputSchema.properties ?? {}))
        expect(p).toHaveProperty("type");
      expect(t.annotations?.readOnlyHint, t.name).toBe(true);
    }
    expect(new Set(names).size).toBe(names.length);
    for (const n of names) expect(n).toMatch(/^[a-z]+(_[a-z]+)*$/);
  });

  it("every tool answers structured JSON without a network, or says why it cannot", async () => {
    const fake = fakeCrates({});
    for (const t of ENTRY_TOOLS) {
      const r = await dispatchTool(
        t,
        t === "discover_intent" ? { goal: "is it maintained" } : {},
        seam(fake),
      );
      expect(typeof r, t).toBe("object");
      expect(r, t).not.toBeNull();
      const wire = toCallToolResult(r);
      expect(JSON.parse((wire.content[0] as { text: string }).text)).toEqual(r);
      expect(wire.structuredContent, t).toBeDefined();
    }
    expect(fake.calls).toHaveLength(0);
  });
});

describe("a missing required argument answers needs_input and names the slot", () => {
  it("open_form, plan_inputs and run_full without a crate, at no cost", async () => {
    const fake = fakeCrates({});
    for (const [tool, args] of [
      ["open_form", {}],
      ["plan_inputs", {}],
      ["run_full", {}],
      ["run_full", { crate: "   " }],
      ["run_form", {}],
      ["check_crate", {}],
    ] as const) {
      const r = (await dispatchTool(tool, { ...args }, seam(fake))) as any;
      expect(r.status, tool).toBe("needs_input");
      expect(r.questions.length).toBeGreaterThan(0);
      expect(r.next_question.field).toBe("crate");
      expect(r.schema).toMatchObject({ type: "object", required: ["crate"] });
      expect(r.example).toEqual({ crate: "serde", owners: true });
      expect(Array.isArray(r.missing)).toBe(true);
      expect(typeof r.hint).toBe("string");
    }
    expect(fake.calls).toHaveLength(0);
  });

  it("the shape the platform draws its form from", async () => {
    const r = (await dispatchTool("open_form", {})) as any;
    expect(Object.keys(r).sort()).toEqual(
      [
        "brief",
        "example",
        "hint",
        "missing",
        "next_question",
        "questions",
        "schema",
        "status",
        "tool",
      ].sort(),
    );
    expect(r.missing).toEqual(["crate"]);
    const q = r.questions.find((x: any) => x.field === "crate");
    expect(q).toMatchObject({ required: true, type: "string", example: "serde" });
    expect(typeof q.question).toBe("string");
    const optional = r.questions.find((x: any) => x.field === "owners");
    expect(optional).toMatchObject({ required: false, type: "boolean" });
  });

  it("plan_inputs plans for the tool asked about, and falls back to run_full for an unknown one", async () => {
    expect(((await dispatchTool("plan_inputs", { tool: "check_crate" })) as any).tool).toBe(
      "check_crate",
    );
    expect(((await dispatchTool("plan_inputs", { tool: "nope" })) as any).tool).toBe("run_full");
  });

  it("answers already given are kept: only the missing slot is asked", async () => {
    const r = (await dispatchTool("plan_inputs", { provided: '{"crate":"serde"}' })) as any;
    expect(r.missing).toEqual([]);
  });

  it("a crate given as a non-string is invalid_input, not a missing answer", async () => {
    const r = (await dispatchTool("run_full", { crate: 42 })) as any;
    expect(r).toMatchObject({ ok: false, failure: "invalid_input" });
  });

  it("owners must be a boolean; the strings true and false are accepted, anything else is invalid_input", async () => {
    const fake = fakeCrates(routesFor("acme-widget", crateDoc()));
    expect(
      await dispatchTool("run_full", { crate: "acme-widget", owners: "false" }, seam(fake)),
    ).toMatchObject({
      ok: true,
      requests: { used: 1 },
    });
    expect(
      await dispatchTool("run_full", { crate: "acme-widget", owners: "maybe" }, seam(fake)),
    ).toMatchObject({
      ok: false,
      failure: "invalid_input",
    });
  });
});

describe("hostile input", () => {
  it("a tool name that is an Object.prototype member plans for run_full instead of crashing", async () => {
    for (const tool of ["constructor", "__proto__", "toString", "hasOwnProperty"]) {
      const r = (await dispatchTool("plan_inputs", { tool })) as any;
      expect(r.tool, tool).toBe("run_full");
      const d = (await dispatchTool("discover_intent", { goal: "x", tool })) as any;
      expect(d.tool, tool).toBe("run_full");
    }
  });

  it("discover_intent carries over only fields the tool declares", async () => {
    const r = (await dispatchTool("discover_intent", {
      goal: "x",
      provided: { crate: "serde", injected: "<b>boo</b>", __proto__: { polluted: true } },
    })) as any;
    expect(Object.keys(r.proposed_input).sort()).toEqual(["crate", "owners"]);
    expect(({} as any).polluted).toBeUndefined();
  });

  it("a very long goal is cut, not echoed whole", async () => {
    const r = (await dispatchTool("discover_intent", { goal: "g".repeat(5000) })) as any;
    expect(r.restated_goal.length).toBeLessThan(400);
    expect(r.restated_goal.endsWith("...")).toBe(true);
  });

  it("a crate argument that is an object, array or number is invalid_input, never a crash", async () => {
    for (const bad of [{}, [], 7, true, { toString: 1 }]) {
      const r = (await dispatchTool("run_full", { crate: bad })) as any;
      expect(r, JSON.stringify(bad)).toMatchObject({ ok: false, failure: "invalid_input" });
    }
  });

  it("a malformed JSON string for provided is ignored", async () => {
    const r = (await dispatchTool("plan_inputs", { provided: "{not json" })) as any;
    expect(r.status).toBe("needs_input");
  });
});

describe("discover_intent", () => {
  it("without a goal asks for it, naming the slot", async () => {
    for (const args of [{}, { goal: "  " }]) {
      const r = (await dispatchTool("discover_intent", args)) as any;
      expect(r.status).toBe("needs_input");
      expect(r.next_question.field).toBe("goal");
      expect(r.missing).toEqual(["goal"]);
    }
  });

  it("restates the goal, asks questions and proposes a runnable input", async () => {
    const r = (await dispatchTool("discover_intent", {
      goal: "is serde still maintained",
      provided: { crate: "serde" },
    })) as any;
    expect(r.status).toBe("intent_discovery");
    expect(r.restated_goal).toContain("is serde still maintained");
    expect(r.proposed_input).toMatchObject({ crate: "serde" });
    expect(r.questions.length).toBeGreaterThan(0);
    expect(r.confirm_prompt).toContain("run_full");
  });
});

describe("run_form and run_full", () => {
  it("run_form forwards its whole payload to run_full", async () => {
    const fake = fakeCrates(routesFor("acme-widget", crateDoc()));
    const r = (await dispatchTool(
      "run_form",
      { crate: "acme-widget", owners: false },
      seam(fake),
    )) as any;
    expect(r.kind).toBe("crate_check");
    expect(r.requests.used).toBe(1);
  });

  it("run_full and check_crate give the same report", async () => {
    const a = await dispatchTool(
      "run_full",
      { crate: "acme-widget" },
      seam(fakeCrates(routesFor("acme-widget", crateDoc()))),
    );
    const b = await dispatchTool(
      "check_crate",
      { crate: "acme-widget" },
      seam(fakeCrates(routesFor("acme-widget", crateDoc()))),
    );
    expect(a).toEqual(b);
  });

  it("a failed check is marked isError and keeps its class in the body", async () => {
    const fake = fakeCrates({ "crates.io/api/v1/crates/ghost": { status: 404 } });
    const wire = toCallToolResult(await dispatchTool("run_full", { crate: "ghost" }, seam(fake)));
    expect(wire.isError).toBe(true);
    expect(wire.structuredContent).toMatchObject({ kind: "crate_failure", failure: "not_found" });
  });

  it("a report is not marked isError", async () => {
    const fake = fakeCrates(routesFor("acme-widget", crateDoc()));
    const wire = toCallToolResult(
      await dispatchTool("run_full", { crate: "acme-widget" }, seam(fake)),
    );
    expect(wire.isError).toBeUndefined();
  });

  it("an unknown tool throws rather than answering", async () => {
    await expect(dispatchTool("nope", {})).rejects.toThrow(/Unknown tool/);
  });
});

describe("list_capabilities", () => {
  it("lists every signal with its rule and field, the hosts and the limits", async () => {
    const r = (await dispatchTool("list_capabilities", {})) as any;
    expect(r.kind).toBe("capabilities");
    expect(r.tools).toEqual(names);
    expect(r.signals.map((s: any) => s.id)).toEqual([
      "latest_release_age",
      "yanked",
      "license",
      "repository",
      "recent_downloads",
      "owners",
    ]);
    for (const s of r.signals) {
      expect(typeof s.rule).toBe("string");
      expect(typeof s.field).toBe("string");
    }
    expect(r.data_source).toContain("crates.io");
    expect(r.model_use).toMatch(/^None/);
  });
});

describe("the panel binding", () => {
  it("every tool is bound to the panel and is model-only on both hosts", () => {
    for (const t of toolsWithPanel()) {
      const meta = t._meta as Record<string, unknown>;
      expect(meta["ui"]).toEqual({ resourceUri: PANEL_RESOURCE_URI, visibility: ["model"] });
      expect(meta["openai/outputTemplate"]).toBe(PANEL_RESOURCE_URI);
      expect(meta["openai/widgetAccessible"]).toBe(false);
    }
    expect(panelBinding("ui://x/y")._meta["openai/widgetAccessible"]).toBe(false);
  });

  it("the panel URI uses the ui:// scheme", () => {
    expect(PANEL_RESOURCE_URI).toMatch(/^ui:\/\/[a-z0-9-]+\/panel$/);
  });

  it("only the tools that run a check may be upgraded to a native form", () => {
    expect([...RUNNING_TOOLS].sort()).toEqual(["check_crate", "run_form", "run_full"]);
    for (const t of ["open_form", "plan_inputs", "discover_intent", "list_capabilities"]) {
      expect(RUNNING_TOOLS.has(t)).toBe(false);
    }
  });
});

describe("the manifests describe the server that exists", () => {
  const manifest = json("findagent.json");
  const dxt = json("manifest.json");

  it("findagent.json is a v1.2 code-bundle with the required fields", () => {
    expect(manifest["schema_version"]).toBe("1.2");
    expect(manifest["kind"]).toBe("code-bundle");
    expect(manifest["name"].length).toBeGreaterThanOrEqual(3);
    expect(manifest["name"].length).toBeLessThanOrEqual(80);
    expect(manifest["entrypoint"].path).toBe("dist/mcp/server.js");
    expect(manifest["runtime"]).toEqual({ kind: "node", version: "22" });
    expect(manifest["mcp"]).toEqual({
      mode: "native",
      command: "node",
      args: ["dist/mcp/server.js"],
    });
    expect(manifest["description"].length).toBeLessThanOrEqual(4000);
    expect(manifest["tagline"].length).toBeLessThanOrEqual(140);
    expect(manifest["example_prompts"].length).toBeGreaterThanOrEqual(1);
    expect(manifest["example_prompts"].length).toBeLessThanOrEqual(5);
    expect(manifest["version"]).toBe(json("package.json")["version"]);
  });

  it("skills[] is exactly the registered tools, with the same descriptions and schemas", () => {
    expect(manifest["skills"].map((s: any) => s.id)).toEqual(names);
    for (const s of manifest["skills"]) {
      const tool = TOOLS.find((t) => t.name === s.id)!;
      expect(s.description).toBe(tool.description);
      expect(s.input_schema).toEqual(tool.inputSchema);
    }
  });

  it("the DXT manifest lists the same tools and the same version", () => {
    expect(dxt["tools"].map((t: any) => t.name)).toEqual(names);
    expect(dxt["version"]).toBe(manifest["version"]);
    expect(dxt["server"].entry_point).toBe(manifest["entrypoint"].path);
  });

  it("declares no credential slot, because the agent needs no secret", () => {
    expect(manifest["credential_slots"]).toBeUndefined();
  });

  it("declares a panel and nothing that could widen it", () => {
    expect(manifest["ui"]).toEqual({ path: "ui/index.html" });
    expect(JSON.stringify(manifest)).not.toMatch(/"domain"/);
  });

  it("serves hosted only: nothing here is meant to run on the buyer's machine", () => {
    expect(manifest["serve"]).toEqual(["hosted"]);
  });
});
