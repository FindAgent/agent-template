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
