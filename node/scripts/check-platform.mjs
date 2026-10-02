#!/usr/bin/env node
/**
 * pnpm check:platform: does this repo satisfy what FindAgent's submission and build expect of a
 * code agent? Each rule below is one that a real submission has tripped over, and each one fails
 * here, in seconds, instead of in review.
 *
 *   (a) findagent.json is the contract: schema 1.2, kind code-bundle, and `skills[]` lists EVERY
 *       tool the server registers. The submit form prefills the tool list from it; without it the
 *       agent is served with an empty tool list.
 *   (b) listing text: description, tagline, 1-5 example prompts, tags.
 *   (c) category hints: tags carry the discipline, and no tag is a word that sends the
 *       auto-categoriser to the wrong place.
 *   (d) a panel only displays, or answers with ui/message. It never asks the host to call a tool.
 *   (e) the build passes on the sandbox: one package manager, a lockfile that matches package.json,
 *       exact versions, no workspace file, a build command that exists, an entrypoint that exists
 *       after the build.
 *   (f) allowed_hosts is exactly the hosts the code calls; credential slots are declarations only.
 *
 * Run it after `pnpm build`: it reads the compiled tool list and the built entrypoint.
 *
 *   node scripts/check-platform.mjs
 *
 * Exit 0: no error. Exit 1: at least one error (warnings never fail it).
 *
 * Tool list: a Node agent's tools are read from dist/mcp/tools.js (`TOOLS`). An agent in another
 * language replaces `loadRegisteredTools` with a function that returns its `[{ name, description }]`.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parse as parseYaml } from "yaml";

const DEFAULT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// ---- constants shared by the rules -------------------------------------------------------------

/** The panel rule FindAgent's preflight applies to a creator's panel. Same expression, on purpose. */
const PANEL_CALLS_A_TOOL = /tools\/call|callServerTool|\.callTool\s*\(/;
const MAX_PANEL_BYTES = 512 * 1024;
/** The platform's caps on `skills[]`: at most 40 entries, and a tool description is cut at 500. */
const MAX_SKILLS = 40;
const MAX_TOOL_DESCRIPTION = 500;

const LOCKFILES_OTHER_THAN_PNPM = [
  "package-lock.json",
  "npm-shrinkwrap.json",
  "yarn.lock",
  "bun.lock",
  "bun.lockb",
];

const SLOT_KEYS = new Set([
  "ref",
  "label",
  "description",
  "env",
  "allowed_hosts",
  "install_host",
  "host_example",
  "type",
  "required",
  "auth_scheme",
  "header_name",
  "prefix",
  "auth_acquisition",
  "provider",
]);

/**
 * Words that send the auto-categoriser somewhere other than where a code agent belongs. A code
 * agent is always filed under the Software Development discipline; the four first words are the
 * ones that were seen to mislead a real submission, the rest are the needles of the platform's
 * keyword table for the non-engineering categories (a snapshot of the table in FindAgent's
 * importer, kept here because this repo cannot import it: refresh it when that table changes).
 */
const MISLEADING = new Map([
  ...["health", "healthcare", "monitor", "monitoring", "compliance", "license", "licence"].map(
    (w) => [w, "health, monitoring and licensing words"],
  ),
  ...[
    "scrape",
    "scraper",
    "scraping",
    "crawl",
    "crawler",
    "fetch",
    "search",
    "serp",
    "browse",
    "extract",
    "research",
  ].map((w) => [w, "research"]),
  ...[
    "analytics",
    "ga4",
    "chart",
    "charts",
    "metric",
    "metrics",
    "dashboard",
    "report",
    "reporting",
    "kpi",
    "visualization",
  ].map((w) => [w, "data analytics"]),
  ...["campaign", "email", "newsletter", "sms", "ads", "seo", "social", "audience", "segment"].map(
    (w) => [w, "marketing"],
  ),
  ...["crm", "lead", "leads", "prospect", "outreach", "pipeline"].map((w) => [w, "sales"]),
  ...["ticket", "helpdesk", "support", "faq", "chatbot"].map((w) => [w, "customer support"]),
  ...["invoice", "accounting", "ledger", "payment", "tax", "payroll", "expense"].map((w) => [
    w,
    "finance",
  ]),
  ...["workflow", "automation", "schedule", "ops", "admin", "inventory", "fulfillment"].map((w) => [
    w,
    "operations",
  ]),
  ...["blog", "article", "essay", "draft", "proofread", "rewrite", "translate", "caption"].map(
    (w) => [w, "writing"],
  ),
  ...["design", "figma", "image", "logo", "illustration", "mockup"].map((w) => [w, "design"]),
  ...["recruit", "candidate", "resume", "hiring", "applicant", "onboarding"].map((w) => [
    w,
    "recruiting",
  ]),
  ...["contract", "legal", "gdpr", "clause", "litigation", "nda"].map((w) => [w, "legal"]),
]);

/** The discipline tag every code agent carries. */
const DISCIPLINE_TAG = "software-development";

const SECRET_SHAPES = [
  new RegExp(["-----", "BEGIN [A-Z ]*", "PRIVATE KEY", "-----"].join("")),
  /\bghp_[A-Za-z0-9]{20,}/,
  /\bgithub_pat_[A-Za-z0-9_]{20,}/,
  /\bsk-[A-Za-z0-9]{20,}/,
  /\bAKIA[0-9A-Z]{16}\b/,
  /\bxox[abprs]-[A-Za-z0-9-]{10,}/,
  /\bAIza[0-9A-Za-z_-]{30,}/,
];

const EXACT_VERSION = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const HOSTNAME = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/;
const IPV4 = /^\d+\.\d+\.\d+\.\d+$/;
const SAFE_REL_PATH = /^[A-Za-z0-9._][A-Za-z0-9._/-]*$/;
const CREDENTIAL_ENV =
  /process\.env\.([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*)/g;
const PROTOTYPE_NAMES = new Set(["__proto__", "constructor", "prototype"]);

// ---- small helpers -----------------------------------------------------------------------------

const SKIP_DIRS = new Set(["node_modules", "dist", ".git", "coverage"]);

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue;
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const read = (root, rel) => readFileSync(path.join(root, rel), "utf8").replace(/\r\n/g, "\n");

function readJson(root, rel, findings, rule) {
  const file = path.join(root, rel);
  if (!existsSync(file)) return undefined;
  try {
    return JSON.parse(read(root, rel));
  } catch (err) {
    findings.push({
      rule,
      level: "error",
      code: "invalid_json",
      message: `${rel} is not valid JSON: ${err.message}`,
    });
    return undefined;
  }
}

/** Source with comments removed, so a host named in prose is not read as a host that is called. */
function withoutComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

function words(text) {
  return String(text)
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

/** The tracked files, or null when this is not a git work tree (then every file on disk counts). */
function trackedFiles(root) {
  try {
    const run = (args) =>
      execFileSync("git", args, {
        cwd: root,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
      });
    if (run(["rev-parse", "--is-inside-work-tree"]).trim() !== "true") return null;
    return run(["ls-files"]).split("\n").filter(Boolean);
  } catch {
    return null;
  }
}

async function loadRegisteredTools(root) {
  const file = path.join(root, "dist", "mcp", "tools.js");
  if (!existsSync(file)) return undefined;
  const mod = await import(pathToFileURL(file).href);
  return mod.TOOLS.map((t) => ({ name: t.name, description: t.description }));
}

// ---- the rules ---------------------------------------------------------------------------------

/**
 * Run every rule against `root`. `tools` and `tracked` can be injected (the tests do);
 * otherwise they are read from the built output and from git.
 */
export async function checkPlatform({ root = DEFAULT_ROOT, tools, tracked } = {}) {
  const findings = [];
  const add = (rule, level, code, message) => findings.push({ rule, level, code, message });
  const err = (rule, code, message) => add(rule, "error", code, message);
  const warn = (rule, code, message) => add(rule, "warn", code, message);

  const manifest = readJson(root, "findagent.json", findings, "a");
  const pkg = readJson(root, "package.json", findings, "e");
  const dxt = readJson(root, "manifest.json", findings, "a");
  const registered = tools ?? (await loadRegisteredTools(root));
  const gitFiles = tracked ?? trackedFiles(root);
  const files = gitFiles ?? walk(root).map((f) => path.relative(root, f).replace(/\\/g, "/"));

  // (a) findagent.json -------------------------------------------------------------------------
  if (!manifest) {
    err(
      "a",
      "findagent_json_missing",
      "findagent.json is missing. A DXT manifest.json alone is replaced by a contract FindAgent guesses, and the hosts you declared are dropped.",
    );
  } else {
    if (manifest.schema_version !== "1.2")
      err(
        "a",
        "schema_version",
        `schema_version must be "1.2" (found ${JSON.stringify(manifest.schema_version)}).`,
      );
    if (manifest.kind !== "code-bundle")
      err("a", "kind", `kind must be "code-bundle" (found ${JSON.stringify(manifest.kind)}).`);
    if (typeof manifest.name !== "string" || manifest.name.length < 3 || manifest.name.length > 80)
      err("a", "name", "name must be a string of 3 to 80 characters.");
    if (!manifest.entrypoint || typeof manifest.entrypoint.path !== "string")
      err("a", "entrypoint", "entrypoint.path is required.");
    if (!manifest.runtime || !["node", "python"].includes(manifest.runtime.kind))
      err("a", "runtime", 'runtime.kind must be "node" or "python".');
    if (!manifest.mcp || !["native", "wrap"].includes(manifest.mcp.mode))
      err("a", "mcp", 'mcp.mode must be "native" or "wrap".');
    else if (manifest.mcp.mode === "native" && typeof manifest.mcp.command !== "string")
      err("a", "mcp", "a native MCP server needs mcp.command.");

    const skills = Array.isArray(manifest.skills) ? manifest.skills : [];
    if (skills.length === 0) {
      err(
        "a",
        "skills_empty",
        "skills[] is empty: the agent would be served with an empty tool list. List every tool with id, name and description.",
      );
    }
    if (skills.length > MAX_SKILLS) {
      err(
        "a",
        "skills_too_many",
        `skills[] lists ${skills.length} tools; the platform refuses more than ${MAX_SKILLS}.`,
      );
    }
    for (const s of skills) {
      if (typeof s?.description === "string" && s.description.length > MAX_TOOL_DESCRIPTION)
        err(
          "a",
          "skill_description_cut",
          `skills[] ${s.id} has a ${s.description.length}-character description; the served tool list cuts it at ${MAX_TOOL_DESCRIPTION}, mid-sentence. Shorten it and end on a full stop.`,
        );
      if (typeof s?.id === "string" && s.id.length > 64)
        err("a", "skill_id_long", `skills[] id ${s.id} is longer than 64 characters.`);
      if (typeof s?.name === "string" && s.name.length > 120)
        err("a", "skill_name_long", `skills[] name ${s.name} is longer than 120 characters.`);
      if (s?.input_schema !== undefined && s.input_schema?.type !== "object")
        err(
          "a",
          "skill_schema_type",
          `skills[] ${s.id} has an input_schema whose type is not "object"; the platform refuses it.`,
        );
      if (
        !s ||
        typeof s.id !== "string" ||
        typeof s.name !== "string" ||
        typeof s.description !== "string" ||
        s.description.trim() === ""
      ) {
        err(
          "a",
          "skill_incomplete",
          `every skills[] entry needs id, name and description (offender: ${JSON.stringify(s?.id ?? s)}).`,
        );
      } else if (s.id !== s.name) {
        err(
          "a",
          "skill_id_mismatch",
          `skills[] entry ${s.id} must have id equal to name (found name ${s.name}).`,
        );
      }
    }
    if (!registered) {
      err(
        "a",
        "tools_unreadable",
        "The registered tool list could not be read (is dist/mcp/tools.js built? run pnpm build first).",
      );
    } else {
      const have = new Set(skills.map((s) => s?.id));
      for (const t of registered) {
        if (!have.has(t.name))
          err(
            "a",
            "skills_missing_tool",
            `the server registers the tool ${t.name} but skills[] does not list it.`,
          );
      }
      const real = new Set(registered.map((t) => t.name));
      for (const s of skills) {
        if (s?.id && !real.has(s.id))
          err(
            "a",
            "skills_unknown_tool",
            `skills[] lists ${s.id}, which the server does not register.`,
          );
      }
      for (const s of skills) {
        const t = registered.find((x) => x.name === s?.id);
        if (t && s.description !== t.description)
          err(
            "a",
            "skill_description_drift",
            `skills[] description of ${s.id} differs from the server's (run pnpm sync:manifest).`,
          );
      }
    }
    if (dxt) {
      if (!dxt.dxt_version || !dxt.name || !dxt.server)
        err("a", "dxt_incomplete", "manifest.json needs dxt_version, name and server.");
      if (dxt.version !== manifest.version)
        err(
          "a",
          "dxt_version_drift",
          `manifest.json version ${dxt.version} differs from findagent.json ${manifest.version}.`,
        );
      if (registered) {
        const dxtTools = new Set((dxt.tools ?? []).map((t) => t.name));
        for (const t of registered) {
          if (!dxtTools.has(t.name))
            err("a", "dxt_tool_missing", `manifest.json does not list the tool ${t.name}.`);
        }
      }
      if (dxt.server?.entry_point !== manifest.entrypoint?.path)
        err(
          "a",
          "dxt_entrypoint_drift",
          "manifest.json server.entry_point differs from findagent.json entrypoint.path.",
        );
    }
    if (pkg && manifest.version !== pkg.version)
      err(
        "a",
        "version_drift",
        `findagent.json version ${manifest.version} differs from package.json ${pkg.version} (run pnpm sync:manifest).`,
      );
  }

  // (b) listing text ---------------------------------------------------------------------------
  if (manifest) {
    const d = manifest.description;
    if (typeof d !== "string" || d.trim().length < 40)
      err("b", "description", "description must be a real paragraph (at least 40 characters).");
    else if (d.length > 4000)
      err("b", "description", "description is longer than 4000 characters.");
    const t = manifest.tagline;
    if (typeof t !== "string" || t.trim() === "")
      err("b", "tagline", "tagline is required (one line, at most 140 characters).");
    else if (t.length > 140)
      err("b", "tagline", `tagline is ${t.length} characters; the limit is 140.`);
    const ep = manifest.example_prompts;
    if (!Array.isArray(ep) || ep.length < 1 || ep.length > 5)
      err(
        "b",
        "example_prompts",
        "example_prompts needs between 1 and 5 prompts: submitting is refused without them.",
      );
    else
      for (const p of ep)
        if (typeof p !== "string" || p.trim() === "" || p.length > 500)
          err(
            "b",
            "example_prompts",
            "every example prompt must be a non-empty string of at most 500 characters.",
          );
    const tags = manifest.tags;
    if (!Array.isArray(tags) || tags.length < 1 || tags.length > 16)
      err("b", "tags", "tags needs between 1 and 16 entries.");
  }

  // (c) category hints -------------------------------------------------------------------------
  if (manifest && Array.isArray(manifest.tags)) {
    for (const tag of manifest.tags) {
      if (typeof tag !== "string" || !SLUG.test(tag) || tag.length > 40) {
        err(
          "c",
          "tag_shape",
          `tag ${JSON.stringify(tag)} must be a lowercase slug (a-z, 0-9, single dashes), at most 40 characters.`,
        );
        continue;
      }
      for (const w of words(tag)) {
        if (MISLEADING.has(w))
          err(
            "c",
            "tag_misleads",
            `tag ${JSON.stringify(tag)} contains "${w}", which the auto-categoriser reads as ${MISLEADING.get(w)}. Name the discipline instead.`,
          );
      }
    }
    if (!manifest.tags.includes(DISCIPLINE_TAG)) {
      err(
        "c",
        "tag_discipline_missing",
        `tags must include "${DISCIPLINE_TAG}": a code agent is filed under that discipline, and saying so explicitly keeps the categoriser from guessing.`,
      );
    }
    for (const field of ["name", "tagline", "description"]) {
      const hits = [...new Set(words(manifest[field] ?? "").filter((w) => MISLEADING.has(w)))];
      if (hits.length > 0) {
        warn(
          "c",
          "text_misleads",
          `${field} contains ${hits.map((w) => `"${w}"`).join(", ")}, which the auto-categoriser reads as another category (${[...new Set(hits.map((w) => MISLEADING.get(w)))].join(", ")}). Reword it if the guess is wrong.`,
        );
      }
    }
  }

  // (d) panel ----------------------------------------------------------------------------------
  if (manifest?.ui) {
    const uiPath = manifest.ui.path;
    if (typeof uiPath !== "string" || !SAFE_REL_PATH.test(uiPath) || uiPath.includes("..")) {
      err("d", "ui_path", "ui.path must be a safe relative path.");
    } else if (!existsSync(path.join(root, uiPath))) {
      err(
        "d",
        "ui_missing",
        `ui.path points at ${uiPath}, which does not exist. Commit the built panel (the sandbox only installs and builds; it does not render your panel from source).`,
      );
    } else {
      const html = read(root, uiPath);
      if (Buffer.byteLength(html) > MAX_PANEL_BYTES)
        err("d", "ui_size", `the panel is larger than ${MAX_PANEL_BYTES} bytes.`);
      if (!/<html[\s>]/i.test(html)) err("d", "ui_not_html", "the panel is not an HTML document.");
      if (PANEL_CALLS_A_TOOL.test(html))
        err(
          "d",
          "ui_calls_tools",
          "the panel asks the host to call a tool (tools/call, callServerTool or .callTool). A creator's panel may not: send the answer to the conversation with ui/message instead.",
        );
      if (/<script[^>]+\bsrc=|<link\b|<img\b|<iframe\b|@import|url\(\s*["']?(?!data:)/i.test(html))
        err(
          "d",
          "ui_external",
          "the panel loads something that is not inside the document (script src, link, img, iframe, @import or url()). It must be one self-contained file.",
        );
      if (/https?:\/\//i.test(html))
        err(
          "d",
          "ui_url",
          "the panel contains an http(s) URL. The sandbox is closed and the platform rejects references to other origins.",
        );
      if (/\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b/.test(html))
        err("d", "ui_network", "the panel uses the network. Its data arrives in the tool result.");
      if (!/prefers-color-scheme/.test(html))
        err(
          "d",
          "ui_theme",
          "the panel has no prefers-color-scheme rule: it must work in light and dark.",
        );
      if (!/name="viewport"/.test(html))
        err("d", "ui_viewport", "the panel has no viewport meta, so it will not fit a phone.");
    }
    const serverPath = typeof manifest.entrypoint?.path === "string" ? null : null;
    void serverPath;
    const serverSrc = existsSync(path.join(root, "src", "mcp", "server.ts"))
      ? withoutComments(read(root, "src/mcp/server.ts"))
      : "";
    if (/\bdomain\s*:/.test(serverSrc))
      err(
        "d",
        "ui_domain",
        "the panel resource sets a domain. Leave `ui.domain` unset: the host assigns its own sandbox domain and rejects any other.",
      );
    const toolsSrc = existsSync(path.join(root, "src", "mcp", "tools.ts"))
      ? withoutComments(read(root, "src/mcp/tools.ts"))
      : "";
    if (serverSrc || toolsSrc) {
      if (!/visibility:\s*\[\s*["']model["']\s*\]/.test(toolsSrc + serverSrc))
        err("d", "ui_visibility", 'the tool binding must set ui.visibility to ["model"].');
      if (!/["']openai\/widgetAccessible["']\s*:\s*false/.test(toolsSrc + serverSrc))
        err(
          "d",
          "ui_widget_accessible",
          'the tool binding must set "openai/widgetAccessible": false.',
        );
    }
  }

  // (e) the build passes on the sandbox ---------------------------------------------------------
  if (!pkg) {
    err("e", "package_json_missing", "package.json is missing.");
  } else {
    const present = (f) => existsSync(path.join(root, f));
    if (!present("pnpm-lock.yaml"))
      err(
        "e",
        "lockfile_missing",
        "pnpm-lock.yaml is not committed: the dependency tree must be reproducible.",
      );
    for (const other of LOCKFILES_OTHER_THAN_PNPM) {
      if (present(other) || files.includes(other))
        err(
          "e",
          "second_lockfile",
          `${other} exists next to pnpm-lock.yaml. One package manager only: a stale second lockfile fails the install on the sandbox.`,
        );
    }
    if (files.includes("pnpm-workspace.yaml")) {
      err(
        "e",
        "workspace_file_tracked",
        "pnpm-workspace.yaml is tracked. FindAgent reads it as a monorepo with no members and the build fails. Delete it and keep it in .gitignore.",
      );
    }
    const ignore = present(".gitignore") ? read(root, ".gitignore") : "";
    if (!/^pnpm-workspace\.yaml$/m.test(ignore))
      err(
        "e",
        "workspace_file_unignored",
        "pnpm-workspace.yaml is not in .gitignore: pnpm writes one on some versions and it must never be committed.",
      );

    // exact versions, and a lockfile that says the same
    const declared = { ...(pkg.dependencies ?? {}), ...(pkg.devDependencies ?? {}) };
    for (const [name, range] of Object.entries(declared)) {
      if (typeof range !== "string" || !EXACT_VERSION.test(range))
        err(
          "e",
          "version_not_pinned",
          `${name} is "${range}": pin an exact version (for example 1.2.3), not a range, tag or URL.`,
        );
    }
    if (present("pnpm-lock.yaml")) {
      let lock;
      try {
        lock = parseYaml(read(root, "pnpm-lock.yaml"));
      } catch (e) {
        err("e", "lockfile_unreadable", `pnpm-lock.yaml could not be read: ${e.message}`);
      }
      const importer = lock?.importers?.["."] ?? lock;
      if (lock) {
        const locked = { ...(importer?.dependencies ?? {}), ...(importer?.devDependencies ?? {}) };
        for (const [name, range] of Object.entries(declared)) {
          const entry = locked[name];
          if (!entry)
            err(
              "e",
              "lockfile_stale",
              `${name} is in package.json but not in pnpm-lock.yaml (run pnpm install and commit the lockfile).`,
            );
          else if ((entry.specifier ?? entry) !== range)
            err(
              "e",
              "lockfile_stale",
              `${name} is "${range}" in package.json but the lockfile says "${entry.specifier}" (run pnpm install and commit the lockfile).`,
            );
        }
        for (const name of Object.keys(locked)) {
          if (!(name in declared))
            err(
              "e",
              "lockfile_stale",
              `${name} is in pnpm-lock.yaml but not in package.json (run pnpm install and commit the lockfile).`,
            );
        }
      }
    }

    // the build command
    const bc = manifest?.build_command;
    if (typeof bc !== "string" || bc.trim() === "") {
      err(
        "e",
        "build_command_missing",
        "findagent.json has no build_command. The sandbox runs it after installing; without it a TypeScript agent never produces its entrypoint.",
      );
    } else {
      const scripts = pkg.scripts ?? {};
      for (const m of bc.matchAll(/\b(?:npm|pnpm)\s+(?:run\s+)?([A-Za-z0-9:_-]+)/g)) {
        const script = m[1];
        if (["install", "i", "ci", "run", "exec", "dlx"].includes(script)) continue;
        if (!(script in scripts))
          err(
            "e",
            "build_script_missing",
            `build_command runs "${script}", which is not a script in package.json.`,
          );
      }
      if (/\byarn\b|\bbun\b/.test(bc))
        err(
          "e",
          "build_wrong_manager",
          "build_command uses yarn or bun, but the committed lockfile is pnpm's. Use one package manager.",
        );
      if (/\b(pnpm|yarn|bun)\b/.test(bc))
        warn(
          "e",
          "build_command_not_npm",
          "build_command uses a package manager other than npm. The sandbox's own install step is npm, and this repo could not verify that pnpm, yarn or bun exist in the build sandbox. `npm run build` is the safe form.",
        );
      if (/\bnpm\s+(ci|install|i)\b/.test(bc))
        err(
          "e",
          "build_installs_with_npm",
          "build_command installs with npm, which reads package-lock.json, and this repo has none. The sandbox installs for you; the build command only builds.",
        );
      if (/\bpnpm\s+(install|i)\b/.test(bc) && !/--frozen-lockfile/.test(bc))
        err(
          "e",
          "build_not_frozen",
          "build_command runs pnpm install without --frozen-lockfile, which may rewrite the lockfile.",
        );
    }

    // the entrypoint, after the build
    const ep = manifest?.entrypoint?.path;
    if (typeof ep === "string") {
      if (!SAFE_REL_PATH.test(ep) || ep.includes("..") || ep.startsWith("/"))
        err(
          "e",
          "entrypoint_unsafe",
          "entrypoint.path must be a relative path with no .. segments.",
        );
      else if (!existsSync(path.join(root, ep)))
        err(
          "e",
          "entrypoint_missing",
          `entrypoint.path ${ep} does not exist after the build. Run pnpm build; if it still does not exist, the build does not produce what findagent.json names.`,
        );
    }
    if (
      manifest?.runtime?.kind === "node" &&
      manifest.runtime.version &&
      !["22", "24"].includes(String(manifest.runtime.version))
    ) {
      err(
        "e",
        "runtime_version",
        `runtime.version ${manifest.runtime.version} is not one of 22, 24, the only Node versions the sandbox runs (the schema's own runtime enum).`,
      );
    }
  }

  // (e) secrets in the tree ---------------------------------------------------------------------
  for (const file of walk(root)) {
    const rel = path.relative(root, file).replace(/\\/g, "/");
    if (rel === "pnpm-lock.yaml" || /\.(png|jpg|ico|gif)$/i.test(rel)) continue;
    const text = readFileSync(file, "utf8");
    for (const shape of SECRET_SHAPES) {
      if (shape.test(text))
        err(
          "e",
          "secret_shape",
          `${rel} contains something shaped like a secret or a private key. The submission scan refuses it; remove it, and if it was real, rotate it.`,
        );
    }
    if (/^\.env(\.|$)/.test(path.basename(rel)) && rel !== ".env.example")
      err("e", "env_file", `${rel} is an environment file. Never commit one.`);
  }

  // (f) egress and credentials ------------------------------------------------------------------
  if (manifest) {
    const hosts = manifest.allowed_hosts;
    if (!Array.isArray(hosts)) {
      err(
        "f",
        "allowed_hosts_missing",
        "allowed_hosts must be a list (it may be empty only if the code calls nothing).",
      );
    } else {
      for (const h of hosts) {
        if (typeof h !== "string" || !HOSTNAME.test(h) || IPV4.test(h))
          err(
            "f",
            "allowed_host_shape",
            `allowed_hosts entry ${JSON.stringify(h)} must be a plain host name: no scheme, path, port, wildcard or IP address.`,
          );
      }
      const called = new Set();
      const srcRoot = path.join(root, "src");
      const srcFiles = existsSync(srcRoot)
        ? walk(srcRoot).filter((f) => /\.(ts|js|mjs|py)$/.test(f))
        : [];
      for (const f of srcFiles) {
        const text = withoutComments(readFileSync(f, "utf8"));
        for (const m of text.matchAll(/https?:\/\/([a-z0-9.-]+)/gi)) called.add(m[1].toLowerCase());
        for (const m of text.matchAll(/_HOST\s*=\s*"([a-z0-9.-]+)"/gi))
          called.add(m[1].toLowerCase());
      }
      for (const h of called) {
        if (!hosts.includes(h))
          err(
            "f",
            "host_not_declared",
            `the code calls ${h}, which is not in allowed_hosts. The sandbox refuses every host that is not listed.`,
          );
      }
      for (const h of hosts) {
        if (!called.has(h))
          err(
            "f",
            "host_not_called",
            `allowed_hosts lists ${h}, which the code never calls. Declare only what you call.`,
          );
      }
    }

    const slots = manifest.credential_slots;
    const slotEnvs = new Set();
    if (slots !== undefined) {
      if (!Array.isArray(slots) || slots.length === 0) {
        err(
          "f",
          "slots_empty",
          "credential_slots is present but empty. If the agent needs no secret, leave the field out: do not add an optional slot for later.",
        );
      } else {
        for (const s of slots) {
          const where = `credential_slots[${JSON.stringify(s?.ref)}]`;
          if (!s || typeof s !== "object") {
            err("f", "slot_shape", "a credential slot must be an object.");
            continue;
          }
          for (const k of Object.keys(s)) {
            if (!SLOT_KEYS.has(k))
              err(
                "f",
                "slot_unknown_key",
                `${where} has the key "${k}". A slot is a declaration (ref, label, hosts, required ...); it never holds a value.`,
              );
          }
          if (typeof s.ref !== "string" || s.ref === "" || PROTOTYPE_NAMES.has(s.ref))
            err(
              "f",
              "slot_ref",
              `${where}: ref must be a non-empty string and not an object property name.`,
            );
          if (typeof s.label !== "string" || s.label.trim() === "")
            err("f", "slot_label", `${where}: label is required.`);
          if (typeof s.required !== "boolean")
            err(
              "f",
              "slot_required",
              `${where}: required must be true or false, stated explicitly.`,
            );
          const fixed = Array.isArray(s.allowed_hosts) && s.allowed_hosts.length > 0;
          if (s.install_host === true) {
            if (fixed)
              err(
                "f",
                "slot_two_audiences",
                `${where}: install_host is true, so allowed_hosts must be empty (the buyer supplies the host).`,
              );
          } else if (!fixed) {
            err(
              "f",
              "slot_no_audience",
              `${where}: a secret needs a destination. Give allowed_hosts (one vendor, known now) or install_host: true (an address the buyer owns).`,
            );
          } else {
            for (const h of s.allowed_hosts) {
              if (!HOSTNAME.test(h) || IPV4.test(h))
                err(
                  "f",
                  "slot_host_shape",
                  `${where}: ${JSON.stringify(h)} must be a plain host name.`,
                );
              if (Array.isArray(manifest.allowed_hosts) && !manifest.allowed_hosts.includes(h))
                err(
                  "f",
                  "slot_host_unreachable",
                  `${where}: ${h} is not in the top-level allowed_hosts, so the sandbox would refuse the request that carries the secret.`,
                );
            }
          }
          if (s.env) slotEnvs.add(s.env);
          for (const [k, v] of Object.entries(s)) {
            if (typeof v === "string" && SECRET_SHAPES.some((re) => re.test(v)))
              err(
                "f",
                "slot_holds_secret",
                `${where}.${k} looks like a real secret. A slot is a declaration, never a value.`,
              );
          }
        }
      }
    }
    const srcRoot = path.join(root, "src");
    if (existsSync(srcRoot)) {
      for (const f of walk(srcRoot).filter((x) => /\.(ts|js|mjs)$/.test(x))) {
        const text = withoutComments(readFileSync(f, "utf8"));
        for (const m of text.matchAll(CREDENTIAL_ENV)) {
          if (!slotEnvs.has(m[1]))
            err(
              "f",
              "credential_not_declared",
              `${path.relative(root, f).replace(/\\/g, "/")} reads ${m[1]}, which looks like a credential, but no credential_slots entry has env "${m[1]}". The buyer would never be asked for it.`,
            );
        }
      }
    }
  }

  return findings;
}

// ---- command line ------------------------------------------------------------------------------

/**
 * Options (all optional): --root <dir> check another directory; --tools <file.json> read the tool
 * list from a JSON file instead of dist/mcp/tools.js; --tracked <file.json> use this list of
 * tracked files instead of git; --json print the findings as JSON.
 */
function option(name) {
  const at = process.argv.indexOf(name);
  return at === -1 ? undefined : process.argv[at + 1];
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const toolsFile = option("--tools");
  const trackedFile = option("--tracked");
  const findings = await checkPlatform({
    root: option("--root") ? path.resolve(option("--root")) : DEFAULT_ROOT,
    ...(toolsFile ? { tools: JSON.parse(readFileSync(toolsFile, "utf8")) } : {}),
    ...(trackedFile ? { tracked: JSON.parse(readFileSync(trackedFile, "utf8")) } : {}),
  });
  const errors = findings.filter((f) => f.level === "error");
  if (process.argv.includes("--json")) {
    console.log(JSON.stringify(findings));
    process.exit(errors.length === 0 ? 0 : 1);
  }
  for (const f of findings)
    console.log(`${f.level === "error" ? "ERROR" : "warn "} (${f.rule}) ${f.code}: ${f.message}`);
  if (errors.length === 0) {
    console.log(
      `check:platform ok (rules a-f${findings.length ? `, ${findings.length} warning(s)` : ""})`,
    );
    process.exit(0);
  }
  console.error(`check:platform failed: ${errors.length} error(s)`);
  process.exit(1);
}
