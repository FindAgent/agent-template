"""Create a complete code-agent repository from a variant of this template.

    python scripts/init_agent.py <node|python> <destination-dir> [--name "My Agent"] [--slug my-agent]

Copies the variant as the new repository root and adds everything a complete agent repo carries
(scripts/repo-files.json is the one list): the assistant entry files (AGENTS.md, CLAUDE.md,
GEMINI.md, CONVENTIONS.md, .aider.conf.yml, Copilot and Cursor rules), SECURITY.md, CHANGELOG.md, the
CI workflow, a DXT manifest.json for the Python variant, and the MCP client configs generated from
findagent.json. It then runs the completeness check. It never overwrites an existing file.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = shutil.ignore_patterns("node_modules", "dist", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "screenshots")


def arg(flag: str, default: str) -> str:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def write(dest: Path, rel: str, text: str) -> None:
    path = dest / rel
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def ci_workflow(variant: str) -> str:
    text = (ROOT / ".github" / "workflows" / f"{variant}.yml").read_text(encoding="utf-8")
    text = re.sub(r"\n    paths: \[[^\n]*\]", "", text)
    text = re.sub(r"\n    defaults:\n      run:\n        working-directory: \w+", "", text)
    text = re.sub(r"# Copying[^\n]*\n#[^\n]*\n", "", text)
    text = text.replace(f"working-directory: {variant}/", "").replace(f"{variant}/", "")
    return text.replace(f"name: {variant.capitalize()} agent", "name: CI", 1)


def main() -> int:
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(pos) < 2 or pos[0] not in ("node", "python"):
        print(__doc__)
        return 2
    variant, dest = pos[0], Path(pos[1]).resolve()
    if dest.exists() and any(dest.iterdir()):
        print(f"refusing: {dest} is not empty", file=sys.stderr)
        return 2
    shutil.copytree(ROOT / variant, dest, ignore=SKIP, dirs_exist_ok=True)

    manifest = json.loads((dest / "findagent.json").read_text(encoding="utf-8"))
    name = arg("--name", manifest.get("name", "My agent"))
    slug = arg("--slug", re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"))
    manifest["name"] = name
    (dest / "findagent.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    if variant == "python":
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
        "- After changing `mcp` in `findagent.json`, run `python scripts/sync_mcp_configs.py` if present, or regenerate the MCP configs.\n"
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
    write(dest, ".github/workflows/ci.yml", ci_workflow(variant))

    # Generate the MCP client configs from findagent.json with the same function the template uses.
    sys.path.insert(0, str(ROOT / "scripts"))
    import sync_mcp_configs  # noqa: PLC0415

    for rel, content in sync_mcp_configs.render(dest).items():
        write(dest, rel, content)

    checker = ROOT / "scripts" / "check_repo_files.py"
    return subprocess.call([sys.executable, str(checker), str(dest), "--runtime", variant])


if __name__ == "__main__":
    sys.exit(main())
