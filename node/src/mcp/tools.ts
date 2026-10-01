/**
 * MCP tool definitions + dispatcher.
 *
 * Entry-tool contract (the platform draws its form panel from these, so all six must exist and
 * work): plan_inputs, open_form, run_form, run_full, list_capabilities, discover_intent.
 * This agent's one capability tool is check_crate; replace it with your own.
 *
 * Missing or malformed arguments never throw: a tool that lacks its required input answers with a
 * structured `needs_input` payload (questions, a `next_question`, schema, an editable example) so
 * the host can ask the user and retry. open_form, plan_inputs and run_form answer in that shape and
 * the platform renders the form; this agent ships no form panel of its own. Its one panel draws
 * RESULTS (see panel/).
 */

import type { CallToolResult, Tool } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import { REQUEST_BUDGET, checkCrate, failure, type CheckOptions } from "../check.js";
import { loadConfig } from "../config.js";
import { CRATES_HOST } from "../crates.js";
import { type FieldSpec, checkRequired, needsInput } from "../interactive.js";
import { buildIntentDialogue } from "../intent.js";
import { AGENT_NAME } from "../meta.js";
import { MIN_CHECKED_FOR_VERDICT, SIGNAL_RULES } from "../signals.js";

/** URI of the result panel. A tool result that carries a report is drawn by this one document. */
export const PANEL_RESOURCE_URI = `ui://${AGENT_NAME}/panel`;

const CRATE_DESCRIPTION =
  "A crate name as published on crates.io, for example serde or tokio. Case does not matter.";
const OWNERS_DESCRIPTION =
  "Whether to also read the owners list. It costs one extra request; when it fails the check still completes and says the signal was not checked. Default true.";

const crateProp = { type: "string", description: CRATE_DESCRIPTION } as const;
const ownersProp = { type: "boolean", description: OWNERS_DESCRIPTION } as const;

/** Every tool here only reads a public API, so every tool says so. */
const READ_ONLY = {
  readOnlyHint: true,
  idempotentHint: true,
  openWorldHint: true,
} as const;

export const TOOLS: Tool[] = [
  {
    name: "open_form",
    description:
      "Use this the moment the user wants a Rust crate checked. It returns the questions to ask (the crate name, whether to include owners) so a form can be shown. Do NOT run a check before calling this; the form is the entry point.",
    inputSchema: { type: "object", properties: {} },
    annotations: { title: "Open the input form", ...READ_ONLY },
  },
  {
    name: "run_form",
    description:
      "Internal: invoked when the user submits the form opened by open_form. Not for direct use.",
    inputSchema: {
      type: "object",
      properties: { crate: crateProp, owners: ownersProp },
    },
    annotations: { title: "Submit the form", ...READ_ONLY },
  },
  {
    name: "run_full",
    description:
      "Run the whole check end to end for one crate on crates.io: latest release age, yanked, license, source repository, recent downloads and owners, each with the rule and the API field behind it, then a verdict (healthy, watch, risky or unknown) with the reason. Use when the user names a crate and wants the full answer. Missing the crate name, it asks for it instead of failing.",
    inputSchema: {
      type: "object",
      properties: { crate: crateProp, owners: ownersProp },
    },
    annotations: { title: "Check a crate", ...READ_ONLY },
  },
  {
    name: "check_crate",
    description:
      "Check ONE crate from live crates.io data and return its signals and verdict. Same result as run_full; use it when the crate is already known and no form is needed. Reports a missing or unreachable crate as exactly that, never as a clean result.",
    inputSchema: {
      type: "object",
      properties: { crate: crateProp, owners: ownersProp },
      required: ["crate"],
    },
    annotations: { title: "Check one crate", ...READ_ONLY },
  },
  {
    name: "list_capabilities",
    description:
      "List what this agent checks, the rule and API field behind each signal, its request budget and its limits. Use for discovery before running a check.",
    inputSchema: { type: "object", properties: {} },
    annotations: { title: "List capabilities", ...READ_ONLY },
  },
  {
    name: "plan_inputs",
    description:
      "Plan the inputs for a tool before running it: returns the questions, the schema and a ready-to-edit example. Use when the user is unsure what to provide.",
    inputSchema: {
      type: "object",
      properties: {
        tool: {
          type: "string",
          description: "Which tool to plan inputs for (run_full or check_crate).",
        },
        goal: { type: "string", description: "Optional freeform goal." },
        provided: { type: "object", description: "Optional partial arguments already known." },
      },
    },
    annotations: { title: "Plan the inputs", ...READ_ONLY },
  },
  {
    name: "discover_intent",
    description:
      "Use when the user states a goal in their own words ('is this crate still maintained?'). It restates the goal, asks the few questions that pin the input down and proposes a ready-to-run input to confirm before running.",
    inputSchema: {
      type: "object",
      properties: {
        goal: { type: "string", description: "What the user wants to find out about a crate." },
        tool: { type: "string", description: "Which tool to plan for. Defaults to run_full." },
        provided: { type: "object", description: "Optional partial args already known." },
      },
      required: ["goal"],
    },
    annotations: { title: "Discover the intent", ...READ_ONLY },
  },
];

/** The tools that run a check when given their input. Only these may be upgraded to a native form. */
export const RUNNING_TOOLS: ReadonlySet<string> = new Set(["run_full", "run_form", "check_crate"]);

/**
 * The `_meta` that binds a tool's result to the result panel and says the panel may NOT call the
 * tool back: model-only on both hosts (MCP Apps `ui.visibility` and ChatGPT `widgetAccessible`).
 * The panel calls no tool; anything it wants done goes back to the conversation as a message.
 */
export function panelBinding(uri: string): { _meta: Record<string, unknown> } {
  return {
    _meta: {
      ui: { resourceUri: uri, visibility: ["model"] },
      "openai/outputTemplate": uri,
      "openai/widgetAccessible": false,
    },
  };
}

/** TOOLS with the panel binding on each; what `tools/list` serves. */
export function toolsWithPanel(uri: string = PANEL_RESOURCE_URI): Tool[] {
  return TOOLS.map((t) => ({ ...t, ...panelBinding(uri) }));
}

// -- FieldSpecs ------------------------------------------------------------------------------

const CRATE_SPEC: FieldSpec = {
  name: "crate",
  type: "string",
  required: true,
  description: CRATE_DESCRIPTION,
  example: "serde",
  question: "Which crate should I check? (for example serde or tokio)",
};

const OWNERS_SPEC: FieldSpec = {
  name: "owners",
  type: "boolean",
  required: false,
  description: OWNERS_DESCRIPTION,
  example: true,
  question: "Include the owners list? (one extra request; default yes)",
};

const GOAL_SPEC: FieldSpec = {
  name: "goal",
  type: "string",
  required: true,
  description: "What the user wants to find out about a crate, in their own words.",
  example: "Is serde still well maintained?",
  question: "What do you want to find out about the crate?",
};

/** The questions open_form and run_full ask. */
export const RUN_FULL_SPEC: FieldSpec[] = [CRATE_SPEC, OWNERS_SPEC];

const PLAN_SPECS: Record<string, { spec: FieldSpec[]; brief: string }> = {
  run_full: {
    spec: RUN_FULL_SPEC,
    brief: "Check a crate's health from live crates.io data.",
  },
  check_crate: {
    spec: RUN_FULL_SPEC,
    brief: "Check one crate's health from live crates.io data.",
  },
};

// -- argument helpers ------------------------------------------------------------------------

/** MCP clients often serialize array/object arguments as JSON strings. */
function coerceJson(v: unknown): unknown {
  if (typeof v !== "string") return v;
  const s = v.trim();
  if (!(s.startsWith("[") || s.startsWith("{"))) return v;
  try {
    return JSON.parse(s);
  } catch {
    return v;
  }
}

function asString(v: unknown): string | undefined {
  return typeof v === "string" && v.trim().length > 0 ? v.trim() : undefined;
}

function asObject(v: unknown): Record<string, unknown> {
  const value = coerceJson(v);
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

const ownersArg = z
  .union([
    z.boolean(),
    z.literal("true").transform(() => true),
    z.literal("false").transform(() => false),
  ])
  .optional();

export interface DispatchOptions {
  /** Test seam: forwarded to the check (fetch, clock, config). */
  check?: Partial<CheckOptions>;
}

/**
 * Map a dispatch result to the wire result: the JSON any host can read as text, plus the same
 * object as `structuredContent` for a panel. A failed check is marked `isError` so a host treats
 * it as a failure while the body keeps the classified reason. A host without MCP Apps never needs
 * the structured half: the text alone is the complete answer.
 */
export function toCallToolResult(result: unknown): CallToolResult {
  const failed =
    typeof result === "object" && result !== null && (result as { ok?: unknown }).ok === false;
  const structured =
    typeof result === "object" && result !== null && !Array.isArray(result)
      ? (result as Record<string, unknown>)
      : undefined;
  return {
    content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    ...(structured ? { structuredContent: structured } : {}),
    ...(failed ? { isError: true } : {}),
  };
}

// -- dispatcher ------------------------------------------------------------------------------

async function runCheck(
  tool: string,
  args: Record<string, unknown>,
  opts: DispatchOptions,
): Promise<unknown> {
  const rawName = args["crate"];
  const need = checkRequired(tool, PLAN_SPECS["run_full"]!.brief, RUN_FULL_SPEC, {
    crate: asString(rawName),
  });
  if (need) {
    // A value that is present but not a string is a wrong type, not a missing answer.
    if (rawName !== undefined && rawName !== null && typeof rawName !== "string") {
      return failure("", "invalid_input", "crate must be a string.", 0);
    }
    return need;
  }
  const owners = ownersArg.safeParse(args["owners"]);
  if (!owners.success) {
    return failure(
      asString(rawName) ?? "",
      "invalid_input",
      `owners must be true or false (got ${JSON.stringify(args["owners"])}).`,
      0,
    );
  }
  return checkCrate(rawName, {
    config: loadConfig(),
    ...opts.check,
    owners: owners.data ?? true,
  });
}

export async function dispatchTool(
  name: string,
  args: Record<string, unknown>,
  opts: DispatchOptions = {},
): Promise<unknown> {
  switch (name) {
    case "open_form":
      return needsInput("run_full", PLAN_SPECS["run_full"]!.brief, RUN_FULL_SPEC, {});

    case "run_form":
      // Forward the WHOLE payload so the form and its handler cannot drift apart.
      return dispatchTool("run_full", { ...args }, opts);

    case "run_full":
    case "check_crate":
      return runCheck(name, args, opts);

    case "list_capabilities":
      return {
        kind: "capabilities",
        agent: AGENT_NAME,
        tools: TOOLS.map((t) => t.name),
        data_source: `The public crates.io API (${CRATES_HOST}). GET only, no authentication, no credentials.`,
        signals: SIGNAL_RULES,
        verdict: `risky when any measured signal is a risk, watch when any is a warn, healthy otherwise; unknown when fewer than ${MIN_CHECKED_FOR_VERDICT} signals could be measured. A signal that could not be measured is reported as not checked with the reason and never scored as zero.`,
        limits: {
          requests_per_check: `up to ${REQUEST_BUDGET} (1 without owners)`,
          failures:
            "invalid_input, not_found, rate_limited (with the reset time when the upstream gives one), timeout, network_error, upstream_error, malformed_response, response_too_large: each is reported as itself",
          caching: "none; every check reads live data",
        },
        model_use: "None. The result is deterministic and complete without a language model.",
      };

    case "plan_inputs": {
      const requested = asString(args["tool"]) ?? "run_full";
      const tool = Object.hasOwn(PLAN_SPECS, requested) ? requested : "run_full";
      const entry = PLAN_SPECS[tool]!;
      return needsInput(tool, entry.brief, entry.spec, asObject(args["provided"]));
    }

    case "discover_intent": {
      const requested = asString(args["tool"]) ?? "run_full";
      const tool = Object.hasOwn(PLAN_SPECS, requested) ? requested : "run_full";
      const goal = asString(args["goal"]);
      if (goal === undefined) {
        return needsInput(
          "discover_intent",
          "Understand the goal, then co-design the exact input before running.",
          [GOAL_SPEC],
          {},
        );
      }
      const provided: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(asObject(args["provided"]))) provided[k] = coerceJson(v);
      return buildIntentDialogue(tool, goal, PLAN_SPECS[tool]!.spec, provided);
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}
