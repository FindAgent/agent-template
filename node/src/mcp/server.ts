import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListResourcesRequestSchema,
  ListToolsRequestSchema,
  ReadResourceRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { AGENT_NAME, AGENT_VERSION } from "../meta.js";
import {
  PANEL_RESOURCE_URI,
  RUNNING_TOOLS,
  dispatchTool,
  toCallToolResult,
  toolsWithPanel,
} from "./tools.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** The MCP Apps resource mime type (spec 2026-01-26). */
const PANEL_MIME_TYPE = "text/html;profile=mcp-app";

const server = new Server(
  { name: AGENT_NAME, version: AGENT_VERSION },
  { capabilities: { tools: {}, resources: {} } },
);

// Every registered tool is advertised, each bound to the result panel and model-only (the panel
// calls no tool).
server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: toolsWithPanel() }));

/**
 * The result panel: ONE self-contained HTML document (no external network, no CDN, no fetch).
 * `panel.html` is copied next to this file from `ui/index.html` by the build. The resource `_meta`
 * keeps the sandbox closed (`ui.csp: {}`) and leaves `ui.domain` unset: the host assigns its own
 * sandbox domain and rejects any other value.
 */
const PANEL_META = {
  ui: { csp: {}, prefersBorder: true },
  "openai/widgetCSP": { connect_domains: [], resource_domains: [] },
  "openai/widgetDescription": "The signals and verdict for a crate, or why the check failed.",
} as const;

function panelHtml(): string {
  return readFileSync(path.join(__dirname, "panel.html"), "utf-8");
}

server.setRequestHandler(ListResourcesRequestSchema, async () => ({
  resources: [
    {
      uri: PANEL_RESOURCE_URI,
      name: "Crate check panel",
      description: "Draws the signals and verdict of a crate check, or the failure.",
      mimeType: PANEL_MIME_TYPE,
      _meta: PANEL_META,
    },
  ],
}));

server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
  const { uri } = request.params;
  if (uri !== PANEL_RESOURCE_URI) {
    throw new Error(`Unknown resource: ${uri}`);
  }
  return {
    contents: [
      { uri: PANEL_RESOURCE_URI, mimeType: PANEL_MIME_TYPE, text: panelHtml(), _meta: PANEL_META },
    ],
  };
});

type NeedsInputResult = { status: "needs_input"; schema: Record<string, unknown> };

function isNeedsInput(r: unknown): r is NeedsInputResult {
  return (
    typeof r === "object" &&
    r !== null &&
    (r as { status?: unknown }).status === "needs_input" &&
    typeof (r as { schema?: unknown }).schema === "object"
  );
}

/**
 * Elicitation bridge (best-effort). When the connected client advertises the `elicitation`
 * capability AND a tool that runs a check came back asking for input, collect the missing fields
 * natively via `elicitation/create` and re-dispatch with the merged values. open_form and
 * plan_inputs are NOT upgraded: they exist to hand the questions to the platform's form (or to the
 * user), not to run anything. Any failure, a declined form or a client without the capability falls
 * through to the `needs_input` JSON, unchanged.
 */
async function tryElicit(
  name: string,
  args: Record<string, unknown>,
  needs: NeedsInputResult,
): Promise<unknown | null> {
  if (!RUNNING_TOOLS.has(name)) return null;
  try {
    if (!server.getClientCapabilities()?.elicitation) return null;
    const res = await server.elicitInput({
      message: "One more detail is needed to run this check.",
      requestedSchema: needs.schema as never,
    });
    if (res.action !== "accept" || !res.content) return null;
    return await dispatchTool(name, { ...args, ...res.content });
  } catch (err) {
    console.error(`elicitation failed, returning needs_input instead: ${(err as Error).message}`);
    return null;
  }
}

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  try {
    let result = await dispatchTool(name, args ?? {});
    if (isNeedsInput(result)) {
      const elicited = await tryElicit(name, args ?? {}, result);
      if (elicited !== null) result = elicited;
    }
    logOutcome(name, result);
    return toCallToolResult(result);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "unknown error";
    console.error(JSON.stringify({ event: "tool_error", tool: name, message: msg }));
    return { isError: true, content: [{ type: "text", text: msg }] };
  }
});

/**
 * One structured line on stderr for every failed check, so an operator reading the sandbox log
 * learns WHICH failure happened, for which crate, without reading code. Only the classified
 * facts are logged: no argument other than the public crate name, and never a response body.
 */
function logOutcome(tool: string, result: unknown): void {
  const r = result as {
    ok?: unknown;
    failure?: string;
    crate?: string;
    status?: number;
    requests?: unknown;
  } | null;
  if (r && r.ok === false) {
    console.error(
      JSON.stringify({
        event: "check_failed",
        tool,
        failure: r.failure,
        crate: r.crate,
        status: r.status,
        requests: r.requests,
      }),
    );
  }
}

// A protocol server must not die silently or hang on a bad day: log what happened, then exit so
// the host can restart it.
process.on("unhandledRejection", (reason) => {
  console.error(JSON.stringify({ event: "unhandled_rejection", message: String(reason) }));
  process.exit(1);
});
process.on("uncaughtException", (err) => {
  console.error(JSON.stringify({ event: "uncaught_exception", message: err.message }));
  process.exit(1);
});
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    void server.close().finally(() => process.exit(0));
  });
}

const transport = new StdioServerTransport();
await server.connect(transport);

// stderr only: stdout belongs to the MCP protocol.
console.error(`${AGENT_NAME} ${AGENT_VERSION} MCP server running on stdio`);
