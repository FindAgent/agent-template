# FindAgent code agent template

A working, copyable **code agent** for the [FindAgent](https://findagent.cloud) marketplace, in two
equal variants:

| Variant | Runtime | Folder |
|---|---|---|
| Node | Node 22 or 24 (TypeScript, pnpm) | [`node/`](node) |
| Python | Python 3.13 (pip) | [`python/`](python) |

**Node 22/24 or Python 3.13.** Those are the only runtimes the FindAgent sandbox runs. Each folder is a
complete agent on its own: copy one folder, never both.

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
both. Buyers use an agent two ways: **Connect** (it runs behind FindAgent's gateway, nothing to install)
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
   (Python). It fails in seconds on the things that otherwise sit in review.
6. **Submit** at <https://findagent.cloud/submit>: choose the GitHub door, pick your repository, and
   follow the steps (Validate builds it for real, then Submit unlocks).

Nothing in this repository submits or publishes anything for you.

## What every code agent must do (the checklist)

- [ ] **Six entry tools**, each answering structured JSON: `plan_inputs`, `open_form`, `run_form`,
      `run_full`, `list_capabilities`, `discover_intent`. The platform draws the input form from the
      first three, so never build your own form panel for them.
- [ ] **A missing required argument answers `needs_input`** and names the slot. It never throws.
- [ ] **A real `findagent.json`** at the repo root: `schema_version "1.2"`, `kind "code-bundle"`, `name`,
      `entrypoint`, `runtime`, plus the listing text and `skills[]`. A DXT `manifest.json` alone is
      replaced by a contract FindAgent guesses, and the hosts you declared are dropped.
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
tool the server registers (id, name, description). Without it the agent is served with an empty tool
list. `sync:manifest` / `sync_manifest.py` rewrites `skills[]` from the real server.

**b. Listing text.** `example_prompts` needs 1 to 5 prompts or Submit refuses; also a `tagline` (at most
140 characters), a `description` and `tags`.

**c. Category hints.** The category is guessed from your words. Put the discipline in `tags`
(`software-development` for a code agent) and avoid health, monitor, compliance and license-type words
in tags, because they send the agent to the wrong category.

**d. The panel never calls a tool.** A creator's panel may not use `tools/call`. It shows data that
arrives in the tool result and, to ask something, posts `ui/message` to the conversation. No
`ui.domain`, no network, tool binding visibility `["model"]`, `openai/widgetAccessible` false.

**e. Lockfile and build.** Node: commit `pnpm-lock.yaml`, no `package-lock.json`, a `build_command` that
matches the package manager, no tracked `pnpm-workspace.yaml` (pnpm may write one locally: git-ignore
it), and the entrypoint must exist once built. Python: `requirements.txt` of exact pins, nothing that
needs compiling, the panel built and committed.

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

## What `check:platform` checks

One command, both variants, the rules above as code: `findagent.json` shape and `skills[]` against the
real tool list, the listing text, category hints, the panel rules, the dependency and build rules for
the variant, and egress plus credential declarations. Each rule has a test that breaks one thing in a
copy of the repo and expects that exact finding, so the checker cannot silently stop checking.

## Layout

```
node/     findagent.json, src/, panel/, ui/ (built panel), scripts/, test/, pnpm-lock.yaml
python/   findagent.json, agent_template/, server.py, panel/, ui/ (built panel), scripts/, tests/
scripts/  conformance check: both variants keep the same tools, listing and panel
```

## License

MIT, see [`LICENSE`](LICENSE).
