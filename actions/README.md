# Actions agent (declarative API tools, no code)

A complete example of the **Actions** part of a [FindAgent](https://findagent.cloud) agent: tools whose whole
behaviour is a declared HTTP call that FindAgent's trusted runtime makes with the **buyer's own credential**. No code
ships and none runs. Read the [root README](../README.md) for the model and the code variants.

The example reads the signed-in GitHub account and the open issues of a repository, through `https://api.github.com`
with the buyer's GitHub token.

## Layout

| Path | What |
|---|---|
| `plugin.json` | identity plus `extensions["cloud.findagent"].actions = { tools, credential_slots }` |
| `skills/instructions/SKILL.md` | the standing instructions that tell the model when to call each tool and how to report a failure |

## The rules it follows

- Each tool has a `name` (MCP-safe, unique), a `description` of 10 to 500 characters that says *when* to call it, a typed `input_schema` and an `action`.
- An `http` action uses `https://` only. `{owner}` and `{repo}` in the URL are filled from the tool's arguments.
- **A credential slot declares a key, never a value.** `github_token` has `allowed_hosts: ["api.github.com"]`: the buyer's token is sent to that exact host and nowhere else. A slot with no host and no `install_host` is a dead credential and is refused at publish.
- Use `install_host: true` instead (and leave `allowed_hosts` empty) only when the address belongs to the buyer, for example a self-hosted tool; then the URL uses `{install_host}`.
- Annotations tell the truth: both tools read only, so `readOnlyHint` is true. A tool that changes something is not read-only, and a destructive one automatically gets a human approval floor.
- Never put a literal key in a header, an example or a description. The file scan reads `plugin.json` as written and blocks it.

## Make it yours

1. Replace the two tools with the calls your agent needs, and the slot with the vendor's key and exact host.
2. Declare the actions in **one** place: `plugin.json` here, or a `findagent.json`. Both is refused.
3. Rewrite the instructions for your tools. More than 40 tools is refused.
4. Starting from an OpenAPI spec? The web import takes it (source `openapi`) but stops at 40 operations with a warning, so choose the operations first.

## Check it

```
npx --yes @findagent/cli@0.4.2 check .
```

Offline and read-only: it validates the actions, the slot's host binding and the secret shapes. A live call needs a
real token; use your own through an environment variable you never print, and report "not checked: no credential"
when you have none.

## Assistant entry files become skills

`python scripts/init_agent.py` adds `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and the Copilot, Cursor and Aider files so an assistant can work on this repository. When FindAgent imports the repository, a root `AGENTS.md` and `.cursor/rules/*` are read as **skills** (they count toward the 40 and reach the buyer's model); `CLAUDE.md`, `GEMINI.md`, `CONVENTIONS.md` and `copilot-instructions.md` are not package parts. Run `npx --yes @findagent/cli@0.4.2 check .` to see exactly what is kept, and delete `AGENTS.md` and `.cursor/rules/` from the copy you submit (or keep them on purpose and write them for the buyer's model).

## Submit

At <https://findagent.cloud/submit>: **Agent**, then **Upload** or **GitHub**, or the Editor. Over MCP:
`findagent_create_draft`, then `findagent_submit_for_review`. You attest the files are your own; they are scanned and
a person reviews them. Nothing in this repository submits or publishes anything for you.
