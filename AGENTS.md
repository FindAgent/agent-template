# Instructions for an AI assistant building a FindAgent code agent from this repository

You were pointed at this repo to produce a **code agent** for the FindAgent marketplace. Work like this.

1. **Pick one variant** and treat its folder as the repo root of the new agent: `node/` (Node 22 or 24,
   TypeScript, pnpm) or `python/` (Python 3.13, pip). Never mix them. Do not edit the other folder.
2. **Read first**: `README.md` (the platform checklist and pitfalls), then the variant's `README.md`, its
   `findagent.json`, its tools file (`node/src/mcp/tools.ts` or `python/agent_template/tools.py`) and its
   checker (`node/scripts/check-platform.mjs` or `python/scripts/check_platform.py`).
3. **Replace only the domain**: the files that talk to crates.io and compute the verdict
   (`crates`, `signals`, `check`). Keep the six entry tools (`plan_inputs`, `open_form`, `run_form`,
   `run_full`, `list_capabilities`, `discover_intent`), the `needs_input` response shapes, `http` as the
   only code that touches the network, and the panel mechanism.
4. **Update the contract with the code**: change `TOOLS`, regenerate `skills[]` (`pnpm sync:manifest` or
   `python scripts/sync_manifest.py`), set `allowed_hosts` to exactly the hosts the new code calls, and
   write a real `description`, `tagline`, 1 to 5 `example_prompts` and `tags` that include
   `software-development`. Avoid health, monitor, compliance and license-type words in tags.
   Keep each tool description at most 500 characters (the served tool list cuts there), at most 40
   tools, and `runtime.version` `22` or `24` (Node) or `3.13` (Python).
5. **Rules that must never be broken**: no secret in any file, no private-key armor, no URL taken from a
   caller, no network from the panel, no `tools/call` from the panel, no `print()` to stdout in Python,
   no sample data, no demo mode, no unfinished-work markers in shipped code. A failure is never reported
   as "not found", and a signal that could not be measured is "not checked: <reason>", never zero.
6. **Verify before you say done**: run the variant's full gates (install, typecheck or lint, tests,
   `check:platform` / `check_platform.py`) and the live script (`pnpm live` / `python scripts/live_check.py`)
   against the real upstream, and show their real output. Then stop: **do not submit or publish**. The
   person submits at https://findagent.cloud/submit through the GitHub door.

7. **MCP client configs** (`mcp.json`, `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`) are generated from
   `findagent.json` by `python scripts/sync_mcp_configs.py` (CI runs it with `--check`). Run it after changing
   `mcp` in `findagent.json`; never edit them by hand. To submit over MCP instead of the web, connect the
   FindAgent platform MCP (`https://mcp.findagent.cloud/mcp`) and use `findagent_create_code_draft`; the
   provider-neutral playbooks are at https://github.com/FindAgent/agent-creators.

8. **Start a complete repo in one command**: `python scripts/init_agent.py <node|python> <dir> --name "My Agent"` copies a variant and
   adds every file a complete agent repo carries (assistant entry files, SECURITY.md, CHANGELOG.md, CI, DXT manifest, MCP configs);
   `python scripts/check_repo_files.py <dir>` verifies it. The list is `scripts/repo-files.json`.

9. **Install and versions.** The platform sandbox installs with npm and ignores `pnpm-lock.yaml`, so pin exact
   versions in `package.json`; keep `build_command` as `npm run build`. A published agent is updated by a
   re-pull (`findagent_new_version` over MCP, patch bump unless `bump` says otherwise). A re-pull keeps the
   `skills[]` ids and typed `input_schema` you declare in `findagent.json`; still keep `manifest.json` in step
   (`sync:manifest`) and read the stored tool list once after a re-pull.

10. **Agent memory** is optional. A hosted run delivers the previous state as a file: read
    `FINDAGENT_MEMORY_FILE` first (a path relative to the working directory; the file holds the JSON text).
    `FINDAGENT_MEMORY` (the same JSON as an environment variable) is only a fallback and is ABSENT when the
    memory is large, because the sandbox environment has a hard 4096-byte limit (credentials and platform
    variables are refused above about 4000 bytes with the creator-facing reason `code_bundle_env_too_large`).
    Return new state as an object under `__memory` in the structured result: it must stay under 64 KB or the
    write is rejected and the old memory is kept. One user and one agent, hosted runs only, never a secret.
    Keep caches bounded (newest N entries, a size cap).

11. **Say what you ran.** In your hand-off name the assistant and tools you used and every gate you actually
    executed; write "not checked: <reason>" for anything you did not run. The template's own README lists
    which assistants it has been exercised with.
