# FindAgent code agent template

Working, copyable starting points for the [FindAgent](https://findagent.cloud) marketplace. Pick the
lightest kind that is honest:

| Variant | Kind | Folder |
|---|---|---|
| Node | **Code agent**, Node 22 or 24 (TypeScript, pnpm) | [`node/`](node) |
| Python | **Code agent**, Python 3.13 (pip) | [`python/`](python) |
| Framework | **Code agent**, Python 3.13, an agent written in the shape of an agent framework, wrapped as an MCP server | [`framework/`](framework) |
| Package | **Instructions and skills** (Agent Plugins package), no code | [`package/`](package) |
| Actions | **Declarative API tools** that use the buyer's own credentials, no code | [`actions/`](actions) |
| Listing | A checklist to list an **MCP server somebody already runs**; no manifest | [`listing/`](listing) |

**Node 22/24 or Python 3.13.** Those are the only runtimes the FindAgent sandbox runs; Go, Rust, Java and other
runtimes cannot be code agents (list the server you already run with `listing/`, or port it). Each folder is a
complete repository on its own: copy one folder, never two. `python scripts/init_agent.py <variant> <dir>` copies one
and adds everything a complete repository carries; `python scripts/check_repo_files.py <dir>` verifies it.

The rest of this README describes the code agents (`node/`, `python/`, `framework/`); the other three have their own
README.

The agent in it is real, not a skeleton: it checks the health of a Rust crate on crates.io (latest
release age, yanked, license, repository, recent downloads, owners) and answers with a verdict, a
result panel inside the chat, and honest errors. It exists so you can read one finished agent that
meets every platform rule, then replace the crates.io part with your own.

## How an agent is made on FindAgent

Every agent is **one package of four parts**: Instructions, Skills, Actions and Code. On disk that is
`plugin.json`, `skills/<id>/SKILL.md`, `commands/`, `agents/`, an optional `hooks/` and `scripts/` (which
run on the buyer's machine only with install and consent) and `mcp.json`.

This template covers the **Code** part: a *code-bundle* that runs in FindAgent's isolated sandbox
(hosted), or on the buyer's own machine with informed consent if its `serve` field says `local` or
both. **The code is never part of the package.** A code agent may also carry the text parts: add a `plugin.json`
and `skills/<id>/SKILL.md` (the standing instructions are the reserved skill `skills/instructions/SKILL.md`) beside
the code, and FindAgent stores, scans and attaches them with the version. Only `plugin.json`, `skills/`, `commands/`
and `agents/` are taken; the server, `scripts/`, `tests/`, `ui/` and the generated MCP client configs are not, and
actions are not declared there (a code agent's tools come from `findagent.json`). `findagent check` shows what will be
attached. Buyers use an agent two ways: **Connect** (it runs behind FindAgent's gateway, nothing to install)
or **Install** (the files go on their machine). A code agent is submitted at
<https://findagent.cloud/submit> through the GitHub door, is scanned and human-reviewed, and you attest
that it is your own work.

## The 5-minute path

1. **Copy** one folder (`node/` or `python/`) into a new GitHub repository of your own, as the repo root.
2. **Rename.** Change the name in `package.json` (Node) or `pyproject.toml` (Python), then `name`,
   `tagline`, `description`, `example_prompts` and `tags` in `findagent.json`.
3. **Edit** `findagent.json` for your agent: `allowed_hosts` is exactly the hosts your code calls
   (nothing else is reachable), and `credential_slots` appears only if you need a secret from the buyer.
4. **Build and test.**
   - Node: `pnpm install --frozen-lockfile && pnpm test` (with pnpm 11, set
     `pnpm_config_strict_dep_builds=false` for the install: see `node/README.md`)
   - Python: `python -m venv .venv`, activate it, `pip install -r requirements-dev.txt`, `pytest`
5. **Check the platform rules**: `pnpm check:platform` (Node) or `python scripts/check_platform.py`
   (Python). It fails in seconds on the things that otherwise sit in review. For the platform's own
   whole-repo check (six entry tools, egress, lockfile, secret shapes), run `npx --yes @findagent/cli@latest check .`:
   it is offline and read-only, and narrower than `check:platform`: it does not yet enforce the 500-character tool
   description, a wildcard host, a credential slot without a host or the runtime version, so run both.
6. **Submit** at <https://findagent.cloud/submit>: choose **Agent**, then the **GitHub** door (a code agent
   comes in from a repository; Upload and the Editor take instructions, skills and actions only), pick your
   repository and follow the steps: We found, Basics (title, tagline, description, example prompts, a
   Discipline **and** a sub-discipline), Credentials, Manifest, Review. On Review, **Run preflight**: it
   checks the manifest and categories and dry-runs the build in the sandbox, which takes minutes and
   re-checks itself. **Submit for review** unlocks only when the build passed; then tick the two
   confirmations (it is your own work; no prohibited category). A repository that already has a draft
   resumes where it stopped and is not pulled again. Over MCP, the same flow is
   `findagent_create_code_draft`, then `findagent_preflight`, then `findagent_submit_for_review`.

Nothing in this repository submits or publishes anything for you.

## Other kinds of agent

The six folders above are the kinds that have a template. For the rest, use the playbooks in
[FindAgent/agent-creators](https://github.com/FindAgent/agent-creators) (plain Markdown; any assistant that can read
files and run commands can follow them):

| You want | Start with |
|---|---|
| A **department** (a team of published agents) | [`department-creator`](https://github.com/FindAgent/agent-creators/blob/main/playbooks/agents/department-creator.md) |
| To wrap an **OpenAPI** spec as tools | [`actions/`](actions) here for the shape, then [`actions-agent-creator`](https://github.com/FindAgent/agent-creators/blob/main/playbooks/agents/actions-agent-creator.md); the web import takes an OpenAPI file directly and stops at 40 operations |
| To list an **MCP server** somebody runs | [`listing/`](listing) here, then [`mcp-listing-creator`](https://github.com/FindAgent/agent-creators/blob/main/playbooks/agents/mcp-listing-creator.md) |
| To **port an existing repository** (a skills collection, a vendor plugin, a rules repo, an MCP server, a framework agent) | [`port-agent-creator`](https://github.com/FindAgent/agent-creators/blob/main/playbooks/agents/port-agent-creator.md), which hands the work to the matching creator |

`scripts/init_agent.py` needs Python 3.10 or newer and nothing else (standard library only), even for a Node agent. With
no Python, copy the folder by hand and follow the 5-minute path.

## Which assistants this was checked with

The instructions are plain Markdown (`AGENTS.md` is the entry point; `CLAUDE.md`, `GEMINI.md`,
`CONVENTIONS.md`, `.aider.conf.yml`, `.github/copilot-instructions.md` and `.cursor/rules/` only point at it),
so any assistant that can read files and run commands can follow them. The scripts and tests were run by
hand and by CI (Node 22 and Python 3.13). The hand-off in `AGENTS.md` was last exercised end to end with
Claude Code only; Codex, Cursor, Gemini CLI, GitHub Copilot and Aider read the same files but have not
been run against this template.

## What every code agent must do (the checklist)

- [ ] **Six entry tools**, each answering structured JSON: `plan_inputs`, `open_form`, `run_form`,
      `run_full`, `list_capabilities`, `discover_intent`. The platform draws the input form from the
      first three, so never build your own form panel for them.
- [ ] **A missing required argument answers `needs_input`** and names the slot. It never throws.
- [ ] **A real `findagent.json`** at the repo root: `schema_version "1.2"`, `kind "code-bundle"`, `name`,
      `entrypoint`, `runtime`, `mcp`, plus the listing text and `skills[]` (at most 40, each tool
      description at most 500 characters because the served tool list cuts there). A DXT `manifest.json`
      alone is replaced by a contract FindAgent infers, and the hosts you declared are dropped; preflight
      warns about it (`findagent_json_missing`).
- [ ] **Egress is default-deny.** `allowed_hosts` is every host you call and nothing else. Never fetch a
      URL a caller supplied: take the content as input instead.
- [ ] **Credentials are declarations, never values** (see below).
- [ ] **Autobuild safe**: one lockfile or pinned requirements, no tracked `pnpm-workspace.yaml`, no
      private-key armor anywhere, no compiled dependencies in Python, the entrypoint exists after build.
- [ ] **The panel only displays.** One self-contained HTML file, no network, no `tools/call`, light and
      dark, usable at 390px. It answers the chat with `ui/message`.
- [ ] **Honest failures.** Not found, rate limited (with the reset time), a network failure, a malformed
      body and "nothing to report" are different answers. A signal you could not measure says
      `not checked: <reason>`; it is never scored as zero.
- [ ] **Nothing simulated ships.** No sample data, no demo mode, no placeholder tools. Test doubles
      live under `test/` or `tests/` only.

## Pitfalls (each one has stranded a real submission)

**a. `findagent.json` and `skills[]`.** Schema 1.2, kind `code-bundle`, and `skills[]` lists *every*
tool the server registers (`id` and `name` equal to the tool's real name, a description, and the tool's
`input_schema`, which is what a client uses to name the arguments). Without `skills[]` the agent is
served with an empty tool list. `sync:manifest` / `sync_manifest.py` rewrites `skills[]` from the real
server. Set `runtime.version` to `22` or `24` for Node and `3.13` for Python: those are the versions this
template is built and tested on. Any other value is not guaranteed: the platform does not tie the field to a list
today, so a build may run on a different runtime than the one you wrote.

**b. Listing text.** `example_prompts` needs 1 to 5 prompts or Submit refuses; also a `tagline` (at most
140 characters), a `description` and `tags`.

**c. Category hints.** The wizard pre-selects a category only on a strong match, and you confirm it: you
must pick a Discipline **and** one sub-discipline under it (a top level with no sub is refused), and
the preflight judges what is on screen. Still put the discipline in `tags` (`software-development` for
a code agent) and avoid health, monitor, compliance and license-type words there, because they are
what pulled a real submission toward Legal and Agriculture.

**d. The panel never calls a tool.** A creator's panel may not use `tools/call`. It shows data that
arrives in the tool result and, to ask something, posts `ui/message` to the conversation. No
`ui.domain`, no network, tool binding visibility `["model"]`, `openai/widgetAccessible` false.

**e. Lockfile and build.** The sandbox installs with **npm**: `npm ci` when `package-lock.json` (or
`npm-shrinkwrap.json`) is committed, otherwise a fresh `npm install --no-package-lock`. It does **not**
read `pnpm-lock.yaml`, `yarn.lock` or `bun.lock`. This template keeps `pnpm-lock.yaml` for local and CI
installs, so what makes the hosted install reproducible is **exact versions in `package.json`** (no `^`,
no `~`); transitive dependencies still resolve fresh. Keep one lockfile, a `build_command` of
`npm run build` (devDependencies are installed whenever a build runs), no tracked `pnpm-workspace.yaml`
(pnpm may write one locally: git-ignore it), and make sure the entrypoint exists once built. Python:
`requirements.txt` of exact pins, nothing that needs compiling, the panel built and committed.

**f. Hosts and secrets.** `allowed_hosts` exactly the hosts called, no more and no fewer.
`credential_slots` hold labels and destinations, never values.

### Python-only pitfalls

- A dependency that needs compiling (no binary wheel for Linux, Python 3.13) fails the build. Run
  `python scripts/check_platform.py --wheels` to ask PyPI.
- A `requirements.txt` that is missing, or has a range instead of `==`, installs something else tomorrow.
- Reading a file outside the repository (`/etc/...`, `~/...`, `../`) fails: the sandbox bundle is the only
  filesystem you have.
- **`print()` to stdout corrupts the MCP stream.** stdout belongs to the protocol. Log to stderr.
- Do not collapse "rate limited" into "not found". A refusal is not a finding.

### Credential slots: `allowed_hosts` or `install_host`

A slot is a declaration of a secret you need and where it may go. If you call **one known vendor**, set
the slot's `allowed_hosts` to that vendor's host (and list the host in the top-level `allowed_hosts` too).
If the address belongs to the **buyer** (a self-hosted tool, a per-customer API), set
`install_host: true` and leave `allowed_hosts` empty: the buyer supplies the host when they connect, and
the secret is only ever sent there. Never leave a slot with neither. If the agent needs no secret,
declare no slot at all.

## Agent memory (optional)

A hosted run can keep a small amount of state per buyer and per agent. The platform writes the stored JSON
to a file in the working directory and names it in the environment variable `FINDAGENT_MEMORY_FILE` (a path
relative to the working directory, JSON text inside): **read that file first when the variable is set** (it is
not set on a first run or when the memory is empty, so treat a missing variable as no memory). `FINDAGENT_MEMORY` (the same
JSON as an environment variable) is only a fallback and is **absent when the memory is large**, because the
sandbox environment has a hard limit of 4096 bytes in total: credentials and platform variables above about
4000 bytes are refused before the sandbox starts, with the creator-facing reason `code_bundle_env_too_large`.
To change the memory, return a JSON object under the key `__memory` in the tool's structured result. The
platform stores it (replacing the previous value) and strips `__memory` before the result reaches the model
and the buyer. A value of 64 KB or more, or one that contains a secret, is rejected and the old memory is
kept, so keep what you return bounded (newest N entries, a size cap per entry). It exists for hosted
code-bundle runs only (a local run has no memory), it is private to one user and one agent, and it is a cache,
not a database: do not keep credentials in it. This template does not use it; the checker does not require it. A commented example is in [`node/README.md`](node/README.md#optional-a-credential-memory-and-local-serving).

## Updating a published agent

A new version of a live agent is a **re-pull** of its repository: `findagent_new_version` over MCP (it
routes on the agent's kind), `findagent_repull`, or **Publish new version** on the dashboard. The version
number goes up by a **patch** unless you pass `bump` (`minor` or `major`). The new version is scanned,
rebuilt and reviewed; the live version keeps serving until it is approved. A buyer who already connected
is held on the old version until they acknowledge an update that widens permissions: a new credential
slot, a new host on a slot, a new destructive tool, or a changed `auth_scheme`. Copy-only changes and new
read or write tools do not hold anyone.

A re-pull keeps the `skills[]` ids and typed `input_schema` that `findagent.json` declares (an earlier
platform defect that re-derived them from the DXT `manifest.json` is fixed). Keep `manifest.json` in step
anyway (`sync:manifest` does) and read the stored tool list once after a re-pull.

## What preflight tells you

Besides the hard failures (invalid manifest, missing build, bad categories), preflight reports advisories
that never block Submit: `form_panel_tools_missing` (one of `open_form`, `plan_inputs`, `run_form` is not
declared, so a department shows a plain tool instead of a form), `panel_cannot_call_tools` (your panel
script calls `tools/call`, which the platform refuses for every creator panel),
`open_input_schema` (a tool with no typed `input_schema`), `code_bundle_no_skills`, `connectors_hosts_missing`
and `findagent_json_missing`. A smoke call of one tool in the sandbox is opt-in and advisory as well.

## If your tool checks something, end with a decision line

An agent that reviews, tests or audits is often one member of a department, and the department can only act on
what it can read. End such a tool's answer with one fixed line, for example `VERDICT: PASS` or
`VERDICT: BLOCKED`, and say so in the tool description. A workflow department can match that line with its
`contains` condition; a hub department quotes it in its report instructions. Keep the checker a different
agent from the one that produced the work, and read the producer's output rather than its summary.

Keep that answer short. A hosted department run gets about 740 seconds, nearly all of it spent writing the members'
answers, so the answers of every member together have to fit. A run the clock stops is continued as a new run (at most
twice) with the finished work carried over, but every continuation spends its tokens again. Give a member a length
budget in its description, write one line per row, and carry earlier notes as they stand instead of retyping them.

## What `check:platform` checks

One command, both variants, the rules above as code: `findagent.json` shape and `skills[]` against the
real tool list, the listing text, category hints, the panel rules, the dependency and build rules for
the variant, and egress plus credential declarations. Each rule has a test that breaks one thing in a
copy of the repo and expects that exact finding, so the checker cannot silently stop checking.

## Layout

```
node/     findagent.json, src/, panel/, ui/ (built panel), scripts/, test/, pnpm-lock.yaml
python/   findagent.json, agent_template/, server.py, panel/, ui/ (built panel), scripts/, tests/
scripts/  init_agent.py (scaffold), check_repo_files.py (completeness), check_conformance.py (the variants meet the
          contract), check_scaffold.py (scaffold a variant and run its gates), build_adapters.py (assistant files
          from AGENTS.md), cli-version.txt (the platform CLI version CI runs)
```

## License

MIT, see [`LICENSE`](LICENSE).
