# MCP server listing (no code, no manifest)

A checklist repository for putting an **MCP server somebody already runs** into the [FindAgent](https://findagent.cloud)
directory. A listing is not an agent: FindAgent never runs the server, the buyer connects to it directly, and the page
says so. There is nothing to build here and no manifest to lint; the entry is created at submit time from the server
itself. Read the [root README](../README.md) for the code variants.

Use this folder to prepare the facts, then follow [`listing.md`](listing.md). If you want FindAgent to run the logic,
you want a code agent (`node/`, `python/`, `framework/`) or an actions agent (`actions/`) instead.

## Hosted or local

| | Hosted | Local |
|---|---|---|
| What it is | A server you run at an `https://` MCP endpoint | A server the buyer starts on their own machine over stdio (normally `npx <package>` or a repository's documented run command) |
| What the entry needs | The endpoint URL | A public source repository and the exact launch command, so the buyer can read what they will run |
| Who runs it | You or the vendor | The buyer. FindAgent only shows how |
| Claim proof | A DNS TXT record on the exact endpoint host | Admin permission on the declared GitHub repository |

The connection model is derived from what you declare, never typed by hand.

## How the entry is made

1. At <https://findagent.cloud/submit> choose the **MCP server** door, or over MCP call `findagent_create_remote_mcp`.
2. FindAgent introspects the server (`initialize` and `tools/list`) and records the tool list. A server that refuses an anonymous list is OAuth-gated: the entry then says "tools not yet known" until a signed-in owner runs **Load tools** once.
3. A person reviews the entry. Nothing here auto-approves.
4. Later changes go through `findagent_reintrospect_mcp`.

A listing is not a package: do not put an `AGENTS.md` or `.cursor/rules/` file in the repository you list. FindAgent reads both as
skills of a package. `python scripts/init_agent.py listing` writes the assistant instructions to `CONVENTIONS.md`, which it ignores.

Nothing in this repository submits or publishes anything for you.
