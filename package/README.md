# Package agent (instructions and skills, no code)

A complete example of the **Instructions + Skills** part of a [FindAgent](https://findagent.cloud) agent, as an
[Agent Plugins 1.0](https://agent-plugins.org) package. There is no code, no server and nothing to build: the files
are text that the buyer's assistant reads. Read the [root README](../README.md) for the model and the code variants.

## Layout

| Path | What |
|---|---|
| `plugin.json` | identity: `$schema`, `name` (`^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$`), `description`, `version` |
| `skills/instructions/SKILL.md` | the reserved skill that carries the agent's standing instructions |
| `skills/summarize-meeting/SKILL.md` | one example skill (frontmatter `name` equal to the folder, a `description` that says when to use it) |
| `skills/summarize-meeting/references/` | text the skill links to by relative path; kept whole |
| `commands/notes.md` | a ready-made command, served in Connect as the prompt `command-notes` |

## Make it yours

1. Rename: `name` and `description` in `plugin.json`, then replace `skills/instructions/SKILL.md` with your agent's role, boundaries and output shape.
2. One folder per skill under `skills/`, at most **40** for one agent (more is refused, never cut; split a big collection into several agents).
3. Do not add `hooks/`, `scripts/`, `bin/` or a launcher unless you mean them. They are stored and scanned, but today they reach no buyer: Connect never serves them and the public plugin catalog exports an agent without that content.
4. Never put a key, token or password in any file. The scan reads every file and a hit blocks the submit.
5. Do not hand-write `mcp.json`: FindAgent writes the gateway address when it exports the package.

## Check it

```
npx --yes @findagent/cli@0.4.2 check .
```

It runs the platform's own package normaliser offline (parts kept, binaries left out, warnings, secret shapes). No
account, nothing is uploaded. Fix every FAIL and explain every WARN.

## Assistant entry files become skills

`python scripts/init_agent.py` adds `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and the Copilot, Cursor and Aider files so an assistant can work on this repository. When FindAgent imports the repository, a root `AGENTS.md` and `.cursor/rules/*` are read as **skills** (they count toward the 40 and reach the buyer's model); `CLAUDE.md`, `GEMINI.md`, `CONVENTIONS.md` and `copilot-instructions.md` are not package parts. Run `npx --yes @findagent/cli@0.4.2 check .` to see exactly what is kept, and delete `AGENTS.md` and `.cursor/rules/` from the copy you submit (or keep them on purpose and write them for the buyer's model).

## Submit

At <https://findagent.cloud/submit>: **Agent**, then **Upload** (a zip of this folder) or the **GitHub** door. You
attest the files are your own; they are scanned and a person reviews them. Over MCP: `findagent_create_package_draft`,
then `findagent_submit_for_review`. Nothing in this repository submits or publishes anything for you.
