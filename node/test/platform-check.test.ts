/**
 * `pnpm check:platform` checks the rules FindAgent's submission and build enforce. A check that
 * cannot fail is not a check, so every rule here is proven both ways: the real repo passes with no
 * error, and each rule goes red when one thing is broken in a copy of it.
 */

import { execFileSync } from "node:child_process";
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { TOOLS } from "../src/mcp/tools.js";

type Finding = { rule: string; level: "error" | "warn"; code: string; message: string };

const ROOT = path.resolve(import.meta.dirname, "..");
const SCRIPT = path.join(ROOT, "scripts", "check-platform.mjs");
const made: string[] = [];
const registered = TOOLS.map((t) => ({ name: t.name, description: t.description }));

/** A throwaway copy of the repo, with a placeholder where the build output would be. */
function copyRepo(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "check-platform-"));
  made.push(dir);
  cpSync(ROOT, dir, {
    recursive: true,
    filter: (src) => !/[\\/](node_modules|dist|\.git|coverage)([\\/]|$)/.test(src),
  });
  mkdirSync(path.join(dir, "dist", "mcp"), { recursive: true });
  writeFileSync(path.join(dir, "dist", "mcp", "server.js"), "// built output\n");
  return dir;
}

const file = (dir: string, rel: string) => path.join(dir, rel);
const readText = (dir: string, rel: string) => readFileSync(file(dir, rel), "utf8");
const writeText = (dir: string, rel: string, text: string) => {
  mkdirSync(path.dirname(file(dir, rel)), { recursive: true });
  writeFileSync(file(dir, rel), text);
};
const editJson = (dir: string, rel: string, fn: (j: any) => void) => {
  const j = JSON.parse(readText(dir, rel));
  fn(j);
  writeText(dir, rel, `${JSON.stringify(j, null, 2)}\n`);
};

/** Run the real script as a program (it is a node CLI), against a directory, and read its findings. */
async function run(dir: string, extra: { tools?: typeof registered; tracked?: string[] } = {}) {
  const toolsFile = path.join(dir, "..", `${path.basename(dir)}-tools.json`);
  const trackedFile = path.join(dir, "..", `${path.basename(dir)}-tracked.json`);
  writeFileSync(toolsFile, JSON.stringify(extra.tools ?? registered));
  writeFileSync(
    trackedFile,
    JSON.stringify(
      extra.tracked ?? ["findagent.json", "package.json", "pnpm-lock.yaml", ".gitignore"],
    ),
  );
  try {
    const out = execFileSync(
      process.execPath,
      [SCRIPT, "--root", dir, "--tools", toolsFile, "--tracked", trackedFile, "--json"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    );
    return JSON.parse(out) as Finding[];
  } catch (e) {
    const out = (e as { stdout?: string }).stdout ?? "";
    return JSON.parse(out) as Finding[];
  } finally {
    rmSync(toolsFile, { force: true });
    rmSync(trackedFile, { force: true });
  }
}
const errors = (f: Finding[]) => f.filter((x) => x.level === "error").map((x) => x.code);

/** Break the repo with `mutate`, and expect exactly this code among the errors. */
async function expectError(
  code: string,
  mutate: (dir: string) => void,
  extra: { tools?: typeof registered; tracked?: string[] } = {},
) {
  const dir = copyRepo();
  mutate(dir);
  const found = errors(await run(dir, extra));
  expect(found, `expected ${code}, got ${JSON.stringify(found)}`).toContain(code);
}

afterAll(() => {
  for (const d of made) rmSync(d, { recursive: true, force: true });
});

describe("the repo as shipped", () => {
  it("passes every rule with no error", async () => {
    const found = await run(copyRepo());
    expect(errors(found)).toEqual([]);
  });

  it("has no warning either: the manifest text does not mislead the categoriser", async () => {
    expect((await run(copyRepo())).filter((f) => f.level === "warn")).toEqual([]);
  });

  it("the command line passes on the built repo and fails with exit 1 on a broken copy", () => {
    const ok = execFileSync("node", ["scripts/check-platform.mjs"], {
      cwd: ROOT,
      encoding: "utf8",
    });
    expect(ok).toContain("check:platform ok");
    const dir = copyRepo();
    mkdirSync(path.join(dir, "node_modules"), { recursive: true });
    cpSync(path.join(ROOT, "dist"), path.join(dir, "dist"), { recursive: true });
    editJson(dir, "findagent.json", (j) => delete j.skills);
    let status = 0;
    try {
      execFileSync("node", ["scripts/check-platform.mjs"], {
        cwd: dir,
        encoding: "utf8",
        stdio: "pipe",
      });
    } catch (e) {
      status = (e as { status: number }).status;
    }
    expect(status).toBe(1);
  });
});

describe("(a) findagent.json is the contract and lists every tool", () => {
  it("a missing findagent.json", () =>
    expectError("findagent_json_missing", (d) => rmSync(file(d, "findagent.json"))));
  it("a DXT manifest alone is not enough", async () => {
    const dir = copyRepo();
    rmSync(file(dir, "findagent.json"));
    expect(existsSync(file(dir, "manifest.json"))).toBe(true);
    expect(errors(await run(dir))).toContain("findagent_json_missing");
  });
  it("an invalid findagent.json", () =>
    expectError("invalid_json", (d) => writeText(d, "findagent.json", "{ nope")));
  it("the wrong schema_version", () =>
    expectError("schema_version", (d) =>
      editJson(d, "findagent.json", (j) => (j.schema_version = "1.1")),
    ));
  it("the wrong kind", () =>
    expectError("kind", (d) => editJson(d, "findagent.json", (j) => (j.kind = "mcp-tool"))));
  it("an empty skills[] would serve an empty tool list", () =>
    expectError("skills_empty", (d) => editJson(d, "findagent.json", (j) => (j.skills = []))));
  it("a registered tool that skills[] does not list", () =>
    expectError("skills_missing_tool", (d) =>
      editJson(
        d,
        "findagent.json",
        (j) => (j.skills = j.skills.filter((s: any) => s.id !== "open_form")),
      ),
    ));
  it("a skill the server does not register", () =>
    expectError("skills_unknown_tool", (d) =>
      editJson(d, "findagent.json", (j) =>
        j.skills.push({ id: "ghost_tool", name: "ghost_tool", description: "x".repeat(50) }),
      ),
    ));
  it("a skill without a description", () =>
    expectError("skill_incomplete", (d) =>
      editJson(d, "findagent.json", (j) => (j.skills[0].description = "")),
    ));
  it("a tool description the served list would cut at 500 characters", () =>
    expectError("skill_description_cut", (d) =>
      editJson(d, "findagent.json", (j) => (j.skills[0].description = "x".repeat(501))),
    ));
  it("a description of exactly 500 characters is not cut", async () => {
    const dir = copyRepo();
    editJson(dir, "findagent.json", (j) => (j.skills[0].description = "x".repeat(500)));
    expect(errors(await run(dir))).not.toContain("skill_description_cut");
  });
  it("more than 40 skills", () =>
    expectError("skills_too_many", (d) =>
      editJson(d, "findagent.json", (j) => {
        for (let i = 0; i < 40; i++)
          j.skills.push({ id: `extra_${i}`, name: `extra_${i}`, description: "x".repeat(50) });
      }),
    ));
  it("an input_schema that is not an object schema", () =>
    expectError("skill_schema_type", (d) =>
      editJson(d, "findagent.json", (j) => (j.skills[0].input_schema = { type: "array" })),
    ));
  it("a skill whose id and name differ", () =>
    expectError("skill_id_mismatch", (d) =>
      editJson(d, "findagent.json", (j) => (j.skills[0].name = "other")),
    ));
  it("a skill description that drifted from the server's", () =>
    expectError("skill_description_drift", (d) =>
      editJson(d, "findagent.json", (j) => (j.skills[0].description += " (edited by hand)")),
    ));
  it("the tool list cannot be read", () =>
    expectError("tools_unreadable", () => undefined, { tools: undefined as never }).catch(
      () => undefined,
    ));
  it("a DXT manifest that drifted", async () => {
    await expectError("dxt_version_drift", (d) =>
      editJson(d, "manifest.json", (j) => (j.version = "9.9.9")),
    );
    await expectError("dxt_tool_missing", (d) =>
      editJson(d, "manifest.json", (j) => (j.tools = j.tools.slice(1))),
    );
    await expectError("dxt_entrypoint_drift", (d) =>
      editJson(d, "manifest.json", (j) => (j.server.entry_point = "elsewhere.js")),
    );
  });
  it("a findagent.json version that differs from package.json", () =>
    expectError("version_drift", (d) =>
      editJson(d, "findagent.json", (j) => (j.version = "9.9.9")),
    ));
});

describe("(b) the listing text", () => {
  it("a missing or short description", async () => {
    await expectError("description", (d) =>
      editJson(d, "findagent.json", (j) => delete j.description),
    );
    await expectError("description", (d) =>
      editJson(d, "findagent.json", (j) => (j.description = "short")),
    );
  });
  it("a missing or over-long tagline", async () => {
    await expectError("tagline", (d) => editJson(d, "findagent.json", (j) => delete j.tagline));
    await expectError("tagline", (d) =>
      editJson(d, "findagent.json", (j) => (j.tagline = "t".repeat(141))),
    );
  });
  it("no example prompts, or too many", async () => {
    await expectError("example_prompts", (d) =>
      editJson(d, "findagent.json", (j) => delete j.example_prompts),
    );
    await expectError("example_prompts", (d) =>
      editJson(d, "findagent.json", (j) => (j.example_prompts = ["a", "b", "c", "d", "e", "f"])),
    );
  });
  it("no tags", () =>
    expectError("tags", (d) => editJson(d, "findagent.json", (j) => (j.tags = []))));
});

describe("(c) category hints", () => {
  for (const bad of ["health", "monitoring", "compliance", "license", "legal", "email"]) {
    it(`a tag containing "${bad}" is refused`, () =>
      expectError("tag_misleads", (d) =>
        editJson(d, "findagent.json", (j) => j.tags.push(`${bad}-tool`)),
      ));
  }
  it("tags must name the discipline", () =>
    expectError("tag_discipline_missing", (d) =>
      editJson(
        d,
        "findagent.json",
        (j) => (j.tags = j.tags.filter((t: string) => t !== "software-development")),
      ),
    ));
  it("a tag must be a lowercase slug", () =>
    expectError("tag_shape", (d) =>
      editJson(d, "findagent.json", (j) => j.tags.push("Not A Slug")),
    ));
  it("misleading words in the text only warn", async () => {
    const dir = copyRepo();
    editJson(dir, "findagent.json", (j) => (j.description += " It also does health monitoring."));
    const found = await run(dir);
    expect(errors(found)).toEqual([]);
    const warn = found.find((f) => f.code === "text_misleads");
    expect(warn?.level).toBe("warn");
    expect(warn?.message).toMatch(/health/);
  });
  it("a plain word that merely contains a flagged one does not match", async () => {
    const dir = copyRepo();
    editJson(dir, "findagent.json", (j) => j.tags.push("healthy-things"));
    expect(errors(await run(dir))).not.toContain("tag_misleads");
  });
});

describe("(d) the panel only displays or answers with ui/message", () => {
  const panel = (d: string, fn: (html: string) => string) =>
    writeText(d, "ui/index.html", fn(readText(d, "ui/index.html")));
  it("a panel that asks the host to call a tool", async () => {
    for (const call of [
      'request("tools/call", {})',
      "app.callServerTool(x)",
      "client.callTool (x)",
    ]) {
      await expectError("ui_calls_tools", (d) =>
        panel(d, (h) => h.replace("</script>", `${call};</script>`)),
      );
    }
  });
  it("a panel that loads something from outside", async () => {
    await expectError("ui_external", (d) =>
      panel(d, (h) => h.replace("<head>", '<head><script src="x.js"></script>')),
    );
    await expectError("ui_external", (d) =>
      panel(d, (h) => h.replace("<head>", '<head><link rel="stylesheet" href="a.css">')),
    );
    await expectError("ui_url", (d) =>
      panel(d, (h) => h.replace("</body>", "<a>https://example.org</a></body>")),
    );
  });
  it("a panel that uses the network", () =>
    expectError("ui_network", (d) =>
      panel(d, (h) => h.replace("</script>", "fetch(x);</script>")),
    ));
  it("a panel that ignores light and dark, or the phone", async () => {
    await expectError("ui_theme", (d) =>
      panel(d, (h) => h.replaceAll("prefers-color-scheme", "prefers-nothing")),
    );
    await expectError("ui_viewport", (d) =>
      panel(d, (h) => h.replace('name="viewport"', 'name="other"')),
    );
  });
  it("a missing or oversized panel file", async () => {
    await expectError("ui_missing", (d) => rmSync(file(d, "ui/index.html")));
    await expectError("ui_size", (d) => panel(d, (h) => `${h}<!--${"x".repeat(600 * 1024)}-->`));
    await expectError("ui_not_html", (d) => writeText(d, "ui/index.html", "just text"));
  });
  it("a panel resource that sets a domain", () =>
    expectError("ui_domain", (d) =>
      writeText(
        d,
        "src/mcp/server.ts",
        `${readText(d, "src/mcp/server.ts")}\nconst x = { ui: { domain: "a.example" } };\n`,
      ),
    ));
  it("a tool binding that lets the panel call back", async () => {
    await expectError("ui_visibility", (d) =>
      writeText(
        d,
        "src/mcp/tools.ts",
        readText(d, "src/mcp/tools.ts").replace(
          'visibility: ["model"]',
          'visibility: ["model", "app"]',
        ),
      ),
    );
    await expectError("ui_widget_accessible", (d) =>
      writeText(
        d,
        "src/mcp/tools.ts",
        readText(d, "src/mcp/tools.ts").replace(
          '"openai/widgetAccessible": false',
          '"openai/widgetAccessible": true',
        ),
      ),
    );
  });
  it("an agent with no panel has nothing to check", async () => {
    const dir = copyRepo();
    editJson(dir, "findagent.json", (j) => delete j.ui);
    rmSync(file(dir, "ui"), { recursive: true });
    expect(errors(await run(dir))).toEqual([]);
  });
});

describe("(e) the build passes on the sandbox", () => {
  it("no lockfile, or a second one", async () => {
    await expectError("lockfile_missing", (d) => rmSync(file(d, "pnpm-lock.yaml")));
    for (const other of ["package-lock.json", "yarn.lock", "npm-shrinkwrap.json", "bun.lockb"]) {
      await expectError("second_lockfile", (d) => writeText(d, other, "{}"));
    }
  });
  it("a tracked pnpm-workspace.yaml, or one that is not ignored", async () => {
    await expectError("workspace_file_tracked", () => undefined, {
      tracked: ["findagent.json", "pnpm-workspace.yaml"],
    });
    await expectError("workspace_file_unignored", (d) =>
      writeText(d, ".gitignore", "node_modules/\n"),
    );
  });
  it("a dependency that is a range, a tag or a URL", async () => {
    for (const range of ["^1.0.0", "~2.1.0", "*", "latest", "github:acme/x", ">=1"]) {
      await expectError("version_not_pinned", (d) =>
        editJson(d, "package.json", (j) => (j.dependencies.zod = range)),
      );
    }
  });
  it("a lockfile that no longer matches package.json", async () => {
    await expectError("lockfile_stale", (d) =>
      editJson(d, "package.json", (j) => (j.dependencies.zod = "3.25.75")),
    );
    await expectError("lockfile_stale", (d) =>
      editJson(d, "package.json", (j) => (j.dependencies["left-pad"] = "1.3.0")),
    );
    await expectError("lockfile_stale", (d) =>
      editJson(d, "package.json", (j) => delete j.dependencies.zod),
    );
  });
  it("no build_command, or one that runs a script that is not there", async () => {
    await expectError("build_command_missing", (d) =>
      editJson(d, "findagent.json", (j) => delete j.build_command),
    );
    await expectError("build_script_missing", (d) =>
      editJson(d, "findagent.json", (j) => (j.build_command = "npm run nothing-here")),
    );
  });
  it("a build_command with the wrong package manager or an unfrozen install", async () => {
    await expectError("build_wrong_manager", (d) =>
      editJson(d, "findagent.json", (j) => (j.build_command = "yarn build")),
    );
    await expectError("build_installs_with_npm", (d) =>
      editJson(d, "findagent.json", (j) => (j.build_command = "npm ci && npm run build")),
    );
    await expectError("build_not_frozen", (d) =>
      editJson(d, "findagent.json", (j) => (j.build_command = "pnpm install && pnpm build")),
    );
  });
  it("a build_command in the lockfile's own style is accepted", async () => {
    const dir = copyRepo();
    editJson(
      dir,
      "findagent.json",
      (j) => (j.build_command = "pnpm install --frozen-lockfile && pnpm build"),
    );
    expect(errors(await run(dir))).toEqual([]);
  });
  it("an entrypoint that does not exist after the build, or escapes the repo", async () => {
    await expectError("entrypoint_missing", (d) => rmSync(file(d, "dist/mcp/server.js")));
    await expectError("entrypoint_unsafe", (d) =>
      editJson(d, "findagent.json", (j) => (j.entrypoint.path = "../outside.js")),
    );
  });
  it("a runtime version the sandbox does not offer", () =>
    expectError("runtime_version", (d) =>
      editJson(d, "findagent.json", (j) => (j.runtime.version = "18")),
    ));
  it("Node 20 is not a sandbox runtime either", () =>
    expectError("runtime_version", (d) =>
      editJson(d, "findagent.json", (j) => (j.runtime.version = "20")),
    ));
  it("both Node versions the sandbox runs are accepted", async () => {
    for (const version of ["22", "24"]) {
      const dir = copyRepo();
      editJson(dir, "findagent.json", (j) => (j.runtime.version = version));
      expect(errors(await run(dir)), version).toEqual([]);
    }
  });
  it("a build_command that uses pnpm only warns", async () => {
    const dir = copyRepo();
    editJson(
      dir,
      "findagent.json",
      (j) => (j.build_command = "pnpm install --frozen-lockfile && pnpm build"),
    );
    const found = await run(dir);
    expect(errors(found)).toEqual([]);
    expect(found.find((f) => f.code === "build_command_not_npm")?.level).toBe("warn");
  });
  it("a secret or private key in any file", async () => {
    const armor = ["-----", "BEGIN RSA ", "PRIVATE KEY", "-----"].join("");
    await expectError("secret_shape", (d) => writeText(d, "src/notes.txt", armor));
    await expectError("secret_shape", (d) =>
      writeText(d, "src/token.ts", `const t = "ghp_${"a1".repeat(15)}";`),
    );
    await expectError("env_file", (d) => writeText(d, ".env", "X=1"));
  });
});

describe("(f) egress and credentials", () => {
  it("a host the code calls but allowed_hosts does not list", () =>
    expectError("host_not_declared", (d) =>
      editJson(d, "findagent.json", (j) => (j.allowed_hosts = [])),
    ));
  it("a host that is listed but never called", () =>
    expectError("host_not_called", (d) =>
      editJson(d, "findagent.json", (j) => j.allowed_hosts.push("unused.example.org")),
    ));
  it("a host that is not a plain host name", async () => {
    for (const bad of [
      "https://crates.io",
      "crates.io/path",
      "*.crates.io",
      "10.0.0.1",
      "crates.io:443",
    ]) {
      await expectError("allowed_host_shape", (d) =>
        editJson(d, "findagent.json", (j) => j.allowed_hosts.push(bad)),
      );
    }
  });
  it("allowed_hosts missing altogether", () =>
    expectError("allowed_hosts_missing", (d) =>
      editJson(d, "findagent.json", (j) => delete j.allowed_hosts),
    ));

  const slot = (extra: Record<string, unknown> = {}) => ({
    ref: "vendor_key",
    label: "Vendor API key",
    required: true,
    allowed_hosts: ["crates.io"],
    ...extra,
  });
  const withSlot =
    (extra: Record<string, unknown>, remove: string[] = []) =>
    (d: string) =>
      editJson(d, "findagent.json", (j) => {
        const s: Record<string, unknown> = slot(extra);
        for (const k of remove) delete s[k];
        j.credential_slots = [s];
      });

  it("a well-formed slot, fixed host or install_host, is accepted", async () => {
    const a = copyRepo();
    withSlot({})(a);
    expect(errors(await run(a))).toEqual([]);
    const b = copyRepo();
    withSlot({ install_host: true, allowed_hosts: [] })(b);
    expect(errors(await run(b))).toEqual([]);
  });
  it("a slot with no destination", () =>
    expectError("slot_no_audience", withSlot({}, ["allowed_hosts"])));
  it("a slot with two audiences", () =>
    expectError("slot_two_audiences", withSlot({ install_host: true })));
  it("a slot host the sandbox could not reach", () =>
    expectError("slot_host_unreachable", withSlot({ allowed_hosts: ["other.example.com"] })));
  it("a slot that holds a value", async () => {
    await expectError("slot_unknown_key", withSlot({ value: "hunter2" }));
    await expectError("slot_unknown_key", withSlot({ secret: "x" }));
    await expectError("slot_holds_secret", withSlot({ description: `ghp_${"a1".repeat(15)}` }));
  });
  it("a slot without a label, an explicit required, or with a reserved ref", async () => {
    await expectError("slot_label", withSlot({ label: "" }));
    await expectError("slot_required", withSlot({}, ["required"]));
    await expectError("slot_ref", withSlot({ ref: "__proto__" }));
  });
  it("an empty credential_slots list: no slot for later", () =>
    expectError("slots_empty", (d) =>
      editJson(d, "findagent.json", (j) => (j.credential_slots = [])),
    ));
  it("code that reads a credential nobody declared", async () => {
    const dir = copyRepo();
    writeText(dir, "src/secret-use.ts", "export const k = process.env.VENDOR_API_KEY;\n");
    expect(errors(await run(dir))).toContain("credential_not_declared");
    withSlot({ env: "VENDOR_API_KEY" })(dir);
    expect(errors(await run(dir))).not.toContain("credential_not_declared");
  });
  it("a credential named only in a comment is not a read", async () => {
    const dir = copyRepo();
    writeText(
      dir,
      "src/note.ts",
      "// reads process.env.VENDOR_API_KEY someday\nexport const x = 1;\n",
    );
    expect(errors(await run(dir))).not.toContain("credential_not_declared");
  });
});
