"""Create a complete code-agent repository from a variant of this template.

    python scripts/init_agent.py <variant> <destination-dir> [--name "My Agent"] [--slug my-agent]
    python scripts/init_agent.py --fill <existing-agent-repo>   # add only what is missing

Variants:
    node, python, framework   code agents (Node 22/24, Python 3.13, a Python agent in the shape of an agent framework)
    package                   instructions and skills (Agent Plugins package), no code
    actions                   declarative API tools that use the buyer's own credentials, no code
    listing                   a checklist for listing an MCP server somebody already runs, no manifest

Copies the variant as the new repository root and adds everything a complete agent repo carries
(scripts/repo-files.json is the one list): the assistant entry files (AGENTS.md, CLAUDE.md,
GEMINI.md, CONVENTIONS.md, .aider.conf.yml, Copilot and Cursor rules), SECURITY.md, CHANGELOG.md, the
CI workflow, and for a code variant a DXT manifest.json (Python and framework) and the MCP client configs
generated from findagent.json. It then runs the completeness check. It never overwrites an existing file.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE_VARIANTS = ("node", "python", "framework")
NON_CODE_VARIANTS = ("package", "actions", "listing")
VARIANTS = CODE_VARIANTS + NON_CODE_VARIANTS
# Local build output and machine-local files never belong in a new agent. `pnpm-workspace.yaml` in particular is
# written by pnpm on install and a tracked copy makes the platform build read the agent as a memberless monorepo.
SKIP = shutil.ignore_patterns(
    "node_modules",
    "dist",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "screenshots",
    "pnpm-workspace.yaml",
    "*.tsbuildinfo",
    ".eslintcache",
    ".prettiercache",
    ".env",
    ".env.*",
    "*.log",
)


def arg(flag: str, default: str) -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def write(dest: Path, rel: str, text: str) -> None:
    path = dest / rel
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


sys.path.insert(0, str(ROOT / "scripts"))
from ci_workflow import ci_workflow, non_code_ci  # noqa: E402

NON_CODE_RULES = {
    "package": (
        "This is a FindAgent instructions and skills package (Agent Plugins 1.0): text only, no code.\n\n"
        "## Rules\n\n- Never put a secret in any file.\n"
        "- `plugin.json` needs the `$schema`, a `name` matching `^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$`, a description and a version.\n"
        "- One folder per skill under `skills/<id>/SKILL.md`: frontmatter `name` (lowercase, digits, single hyphens, equal to the "
        "folder) and a `description` of at most 1024 characters that says when to use the skill. At most 40 skills per agent; more "
        "is refused, so split a big collection into several agents.\n"
        "- Standing instructions are the reserved skill `skills/instructions/SKILL.md`. Rule files such as `CLAUDE.md` are not "
        "package parts.\n"
        "- `hooks/`, `scripts/` and executables are stored and scanned but reach no buyer today; do not rely on them.\n"
        "- Check with `npx --yes @findagent/cli@latest check .` before saying anything works.\n"
    ),
    "actions": (
        "This is a FindAgent actions agent: declarative HTTP tools in `plugin.json` under "
        '`extensions["cloud.findagent"].actions`, no code.\n\n'
        "## Rules\n\n- Never put a secret in any file. A credential slot declares a key (`ref`, `label`, `allowed_hosts`), never a "
        "value.\n"
        "- Every action URL is `https://`; the slot an action names in `auth_ref` lists the exact host the secret may reach, and "
        "the URL host is inside it.\n"
        "- Annotations tell the truth: a tool that changes something is not read-only.\n"
        "- At most 40 tools. Declare actions in one place only (`plugin.json` or a `findagent.json`).\n"
        "- Check with `npx --yes @findagent/cli@latest check .` before saying anything works.\n"
    ),
    "listing": (
        "This is a checklist for listing an MCP server somebody already runs on FindAgent. There is no code and no manifest.\n\n"
        "## Rules\n\n- Never put a secret in any file.\n"
        "- A listing is not an agent: FindAgent never runs the server, and the entry carries no price and no category.\n"
        "- Tools come from an introspected `tools/list`, never from a hand-typed list.\n"
        "- Work through `listing.md` and write `not checked: <reason>` for anything you did not look at.\n"
    ),
}


def detect_variant(dest: Path) -> str | None:
    """The variant of an existing repository, from what it carries."""
    manifest = dest / "findagent.json"
    if manifest.exists():
        kind = (json.loads(manifest.read_text(encoding="utf-8")).get("runtime") or {}).get("kind")
        if kind == "python":
            return "framework" if (dest / "framework_agent").is_dir() else "python"
        return "node"
    plugin = dest / "plugin.json"
    if plugin.exists():
        return "actions" if "cloud.findagent" in plugin.read_text(encoding="utf-8") else "package"
    return "listing" if (dest / "listing.md").exists() else None


def scaffold_non_code(variant: str, dest: Path, fill: bool) -> int:
    """A package, actions or listing repository: no manifest to read and no MCP configs (FindAgent writes the gateway entry)."""
    defaults = {"package": "My Package Agent", "actions": "My Actions Agent", "listing": "My MCP Server Listing"}
    name = arg("--name", defaults[variant])
    slug = arg("--slug", re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:63].strip("-"))
    tagline = {
        "package": "Instructions and skills for an AI assistant, as an Agent Plugins package.",
        "actions": "Declarative API tools that use the buyer's own credentials.",
        "listing": "A checklist for listing an MCP server on FindAgent.",
    }[variant]
    plugin = dest / "plugin.json"

    if variant in ("package", "actions") and plugin.exists():
        data = json.loads(plugin.read_text(encoding="utf-8"))
        if not fill:
            data["name"] = slug
            plugin.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        tagline = str(data.get("description", tagline))

    pointer = f"# {name}\n\nRead `AGENTS.md` first and follow it.\n"
    entry = (
        f"# {name}: instructions for an AI assistant\n\n{tagline}\n\n{NON_CODE_RULES[variant]}\n"
        "Say which assistant and tools you used and which checks you ran. Do not submit or publish for the user: they submit at "
        "https://findagent.cloud/submit, or over MCP.\n\n"
        "Reference: https://github.com/FindAgent/agent-template and the playbooks in https://github.com/FindAgent/agent-creators.\n"
    )
    write(dest, "AGENTS.md", entry)
    write(dest, "CLAUDE.md", "@AGENTS.md\n")
    write(dest, "GEMINI.md", "@AGENTS.md\n")
    write(dest, "CONVENTIONS.md", pointer)
    write(dest, ".aider.conf.yml", "read:\n  - AGENTS.md\n")
    write(dest, ".github/copilot-instructions.md", pointer)
    write(dest, ".cursor/rules/findagent-code-agent.mdc",
          f"---\ndescription: Work on {name}, a FindAgent {variant} repository\nalwaysApply: true\n---\n\n{pointer}")
    write(dest, "SECURITY.md",
          f"# Security\n\nReport a vulnerability privately to the maintainers of {name} (use the repository's security advisory "
          "form). Do not open a public issue for a vulnerability. Never include a real credential in a report.\n")
    write(dest, "CHANGELOG.md", "# Changelog\n\n## 0.1.0\n\n- Initial release.\n")
    write(dest, ".github/workflows/ci.yml", non_code_ci(variant))
    for script in ("check_repo_files.py", "repo-files.json"):
        write(dest, f"scripts/{script}", (ROOT / "scripts" / script).read_text(encoding="utf-8"))

    if not (dest / ".git").exists():
        subprocess.call(["git", "init", "-q", str(dest)])

    checker = ROOT / "scripts" / "check_repo_files.py"
    return subprocess.call([sys.executable, str(checker), str(dest), "--runtime", variant])


def main() -> int:
    pos = [a for a in sys.argv[1:] if not a.startswith("--") and a not in (arg("--name", ""), arg("--slug", ""))]
    fill = "--fill" in sys.argv

    if fill:
        found = detect_variant(Path(pos[0]).resolve()) if len(pos) == 1 else None
        if found is None:
            print(__doc__)
            return 2
        dest = Path(pos[0]).resolve()
        variant = found
    else:
        if len(pos) < 2 or pos[0] not in VARIANTS:
            print(__doc__)
            return 2
        variant, dest = pos[0], Path(pos[1]).resolve()
        if dest.exists() and any(dest.iterdir()):
            print(f"refusing: {dest} is not empty", file=sys.stderr)
            return 2
        shutil.copytree(ROOT / variant, dest, ignore=SKIP, dirs_exist_ok=True)

    if variant in NON_CODE_VARIANTS:
        return scaffold_non_code(variant, dest, fill)

    manifest = json.loads((dest / "findagent.json").read_text(encoding="utf-8"))
    name = arg("--name", manifest.get("name", "My agent"))
    slug = arg("--slug", re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"))

    if not fill:
        manifest["name"] = name
        (dest / "findagent.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    if variant in ("python", "framework"):
        server = manifest["mcp"]
        write(dest, "manifest.json", json.dumps({
            "dxt_version": "0.1",
            "name": slug,
            "display_name": name,
            "version": manifest.get("version", "0.1.0"),
            "description": manifest.get("tagline", ""),
            "author": {"name": "FindAgent", "url": "https://findagent.cloud"},
            "license": "MIT",
            "server": {"type": "python", "entry_point": manifest["entrypoint"]["path"],
                       "mcp_config": {"command": server["command"], "args": ["${__dirname}/" + a for a in server.get("args", [])]}},
        }, indent=2) + "\n")

    entry = (
        f"# {name}: instructions for an AI assistant\n\n"
        f"{manifest.get('tagline', '')}\n\nThis is a FindAgent {variant} code agent. It works with any assistant that can read "
        "files and run commands (Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, Aider).\n\n"
        "## Rules\n\n- Never put a secret in any file. Credentials are declared in `findagent.json` (`credential_slots`), never valued.\n"
        "- Keep the six entry tools (`plan_inputs`, `open_form`, `run_form`, `run_full`, `list_capabilities`, `discover_intent`).\n"
        "- `allowed_hosts` lists exactly the hosts the code calls; the sandbox egress is default-deny.\n"
        "- `skills[]` lists every tool (at most 40), each description at most 500 characters because the served tool list cuts there. "
        "`runtime.version` is 22 or 24 (Node) or 3.13 (Python).\n"
        "- After changing `mcp` in `findagent.json`, run `python scripts/sync_mcp_configs.py` if present, or regenerate the MCP configs.\n"
        "- Optional agent memory: when `FINDAGENT_MEMORY_FILE` is set, read it first (a path relative to the working directory, JSON text; unset means no memory); "
        "`FINDAGENT_MEMORY` is only a fallback and is absent for large memory (the sandbox env is capped at 4096 bytes; credentials and "
        "platform variables above about 4000 bytes are refused as `code_bundle_env_too_large`). Return new state under `__memory` "
        "(under 64 KB or the write is rejected and the old memory kept; bounded caches; one user and one agent, hosted runs only, never a secret).\n"
        "- A published agent is updated by a re-pull (`findagent_new_version` over MCP; patch bump by default). "
        "A re-pull keeps the `skills[]` you declare in `findagent.json`; keep `manifest.json` in step anyway.\n"
        "- Say which assistant and tools you used and which gates you ran; write `not checked: <reason>` for anything you did not run.\n"
        "- Run the gates in README.md before saying anything works. Do not submit or publish for the user: they submit at "
        "https://findagent.cloud/submit, or over MCP with `findagent_create_code_draft`.\n\n"
        "Reference: https://github.com/FindAgent/agent-template and the playbooks in https://github.com/FindAgent/agent-creators.\n"
    )
    pointer = f"# {name}\n\nRead `AGENTS.md` first and follow it.\n"
    write(dest, "AGENTS.md", entry)
    write(dest, "CLAUDE.md", "@AGENTS.md\n")
    write(dest, "GEMINI.md", "@AGENTS.md\n")
    write(dest, "CONVENTIONS.md", pointer)
    write(dest, ".aider.conf.yml", "read:\n  - AGENTS.md\n")
    write(dest, ".github/copilot-instructions.md", pointer)
    write(dest, ".cursor/rules/findagent-code-agent.mdc",
          f"---\ndescription: Work on {name}, a FindAgent code agent\nalwaysApply: true\n---\n\n{pointer}")
    write(dest, "SECURITY.md",
          f"# Security\n\nReport a vulnerability privately to the maintainers of {name} (use the repository's security advisory "
          "form). Do not open a public issue for a vulnerability. Never include a real credential in a report.\n")
    write(dest, "CHANGELOG.md", f"# Changelog\n\n## {manifest.get('version', '0.1.0')}\n\n- Initial release.\n")
    write(dest, ".github/workflows/ci.yml", ci_workflow(variant, dest, ROOT))
    for name in ("check_repo_files.py", "repo-files.json"):
        write(dest, f"scripts/{name}", (ROOT / "scripts" / name).read_text(encoding="utf-8"))

    # Generate the MCP client configs from findagent.json with the same function the template uses.
    sys.path.insert(0, str(ROOT / "scripts"))
    import sync_mcp_configs  # noqa: PLC0415

    for rel, content in sync_mcp_configs.render(dest).items():
        write(dest, rel, content)

    if not (dest / ".git").exists():
        subprocess.call(["git", "init", "-q", str(dest)])

    checker = ROOT / "scripts" / "check_repo_files.py"
    return subprocess.call([sys.executable, str(checker), str(dest), "--runtime", variant])


if __name__ == "__main__":
    sys.exit(main())
