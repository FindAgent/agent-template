"""The variants of this template must keep meeting the platform contract, and node/ and python/ stay one agent.

Run from the repository root:

    python scripts/check_conformance.py

It fails (exit 1) when
  * the Node and Python variants disagree on anything a buyer or the platform sees (the listing text, the allowed
    hosts, the tool list with each description and input schema, the result panel byte for byte);
  * a code variant (node, python, framework) stops carrying the six entry tools, a valid runtime version, a
    findagent.json v1.2 code-bundle, listing text within the platform limits, or (node) its build command;
  * the package variant stops being a valid skills package, or the actions variant stops binding every secret to
    the exact host it may reach;
  * a CI workflow runs the platform CLI unpinned.

This is an offline stand-in for part of `npx @findagent/cli check`, which CI also runs; it exists so a regression in
the template shows up here even when the CLI is not reachable. Standard library only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent

SHARED_FIELDS = [
    "schema_version",
    "kind",
    "name",
    "version",
    "tagline",
    "description",
    "example_prompts",
    "tags",
    "discipline",
    "category",
    "allowed_hosts",
    "serve",
    "ui",
    "skills",
]
CODE_VARIANTS = ("node", "python", "framework")
RUNTIMES = {"node": {"node"}, "python": {"python"}, "framework": {"python"}}
#: runtime.version the sandbox runs, per variant.
VERSIONS = {"node": {"22", "24"}, "python": {"3.13"}, "framework": {"3.13"}}
ENTRY_TOOLS = ("plan_inputs", "open_form", "run_form", "run_full", "list_capabilities", "discover_intent")
MAX_TOOLS, MAX_TOOL_DESCRIPTION, MAX_TAGLINE = 40, 500, 140
PACKAGE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest(variant: str) -> dict[str, Any]:
    parsed = load(ROOT / variant / "findagent.json")
    return parsed if isinstance(parsed, dict) else {}


def obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def same_text(a: Path, b: Path) -> bool:
    """Equal content regardless of line endings: a Windows checkout rewrites them, the blobs do not differ."""
    crlf, lf = bytes([13, 10]), bytes([10])
    return a.read_bytes().replace(crlf, lf) == b.read_bytes().replace(crlf, lf)


def code_variant_problems(variant: str, data: dict[str, Any]) -> list[str]:
    found: list[str] = []
    label = f"{variant}/findagent.json"
    if data.get("schema_version") != "1.2" or data.get("kind") != "code-bundle":
        found.append(f"{label} must be schema_version 1.2 and kind code-bundle")
    runtime = obj(data.get("runtime"))
    if runtime.get("kind") not in RUNTIMES[variant]:
        found.append(f"{label} runtime.kind is {runtime.get('kind')!r}")
    if str(runtime.get("version")) not in VERSIONS[variant]:
        allowed = sorted(VERSIONS[variant])
        found.append(f"{label} runtime.version is {runtime.get('version')!r}, the sandbox runs {allowed}")
    if variant == "node" and data.get("build_command") != "npm run build":
        found.append(f"{label} build_command must be `npm run build` (the sandbox installs and builds with npm)")
    skills = items(data.get("skills"))
    ids = [s.get("id") for s in skills if isinstance(s, dict)]
    for tool in ENTRY_TOOLS:
        if tool not in ids:
            found.append(f"{label} skills[] lacks the entry tool `{tool}`")
    if len(skills) != 7:
        found.append(f"{label} skills[] must list the seven tools (six entry tools and one domain tool)")
    if len(skills) > MAX_TOOLS:
        found.append(f"{label} lists more than {MAX_TOOLS} tools")
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        if skill.get("id") != skill.get("name"):
            found.append(f"{label} skill {skill.get('id')!r} has a different name")
        if len(str(skill.get("description", ""))) > MAX_TOOL_DESCRIPTION:
            found.append(f"{label} skill {skill.get('id')!r} description is over {MAX_TOOL_DESCRIPTION} characters")
        if not isinstance(skill.get("input_schema"), dict):
            found.append(f"{label} skill {skill.get('id')!r} has no typed input_schema")
    prompts = items(data.get("example_prompts"))
    if not 1 <= len(prompts) <= 5:
        found.append(f"{label} example_prompts needs 1 to 5 prompts")
    if len(str(data.get("tagline", ""))) > MAX_TAGLINE:
        found.append(f"{label} tagline is over {MAX_TAGLINE} characters")
    if "software-development" not in items(data.get("tags")):
        found.append(f"{label} tags must include software-development")
    if not same_text(ROOT / variant / "LICENSE", ROOT / "LICENSE"):
        found.append(f"{variant}/LICENSE differs from the root LICENSE")
    return found


def skill_header(text: str) -> dict[str, str]:
    """The `name` and `description` of a SKILL.md frontmatter (single-line values only, as the template writes them)."""
    match = re.match(r"^---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.DOTALL)
    header: dict[str, str] = {}
    for line in (match.group(1) if match else "").split("\n"):
        key, _, value = line.partition(":")
        header[key.strip()] = value.strip()
    return header


def package_problems() -> list[str]:
    found: list[str] = []
    plugin = load(ROOT / "package" / "plugin.json")
    if "agent-plugins.org" not in str(plugin.get("$schema", "")):
        found.append("package/plugin.json lacks the Agent Plugins $schema")
    if not PACKAGE_NAME.match(str(plugin.get("name", ""))):
        found.append("package/plugin.json name is not a valid package name")
    if not plugin.get("description") or not plugin.get("version"):
        found.append("package/plugin.json needs a description and a version")
    if not (ROOT / "package" / "skills" / "instructions" / "SKILL.md").exists():
        found.append("package/skills/instructions/SKILL.md (the standing instructions) is missing")
    folders = sorted(p for p in (ROOT / "package" / "skills").iterdir() if p.is_dir())
    if len(folders) > MAX_TOOLS:
        found.append(f"package has more than {MAX_TOOLS} skills")
    for folder in folders:
        skill = folder / "SKILL.md"
        if not skill.exists():
            found.append(f"package/skills/{folder.name} has no SKILL.md")
            continue
        header = skill_header(skill.read_text(encoding="utf-8"))
        if header.get("name") != folder.name or not SKILL_NAME.match(folder.name):
            found.append(f"package/skills/{folder.name}/SKILL.md name must equal its folder (lowercase, hyphens)")
        if not header.get("description") or len(header["description"]) > 1024:
            found.append(f"package/skills/{folder.name}/SKILL.md needs a description of at most 1024 characters")
    return found


def action_problems(tool: dict[str, Any], slots: dict[str, dict[str, Any]]) -> list[str]:
    name = tool.get("name")
    action = obj(tool.get("action"))
    url = urlsplit(str(action.get("url", "")))
    found: list[str] = []
    if url.scheme != "https":
        found.append(f"actions tool {name!r} must call an https:// URL")
    method = str(action.get("method", "")).upper()
    annotations = obj(tool.get("annotations"))
    if annotations.get("readOnlyHint") is True and method not in ("GET", "HEAD"):
        found.append(f"actions tool {name!r} is marked read-only but sends {method}")
    ref = action.get("auth_ref")
    if ref is None:
        return found
    slot = slots.get(str(ref))
    if slot is None:
        return [*found, f"actions tool {name!r} names the slot {ref!r}, which is not declared"]
    hosts = items(slot.get("allowed_hosts"))
    if "*" in hosts or any("*" in str(h) for h in hosts):
        found.append(f"actions slot {ref!r} lists a wildcard host")
    if not hosts and not slot.get("install_host"):
        found.append(f"actions slot {ref!r} has neither allowed_hosts nor install_host (the secret has no destination)")
    if hosts and url.hostname not in hosts:
        found.append(f"actions tool {name!r} calls {url.hostname}, outside the hosts of slot {ref!r}: {hosts}")
    return found


def actions_problems() -> list[str]:
    plugin = load(ROOT / "actions" / "plugin.json")
    block = obj(obj(obj(plugin.get("extensions")).get("cloud.findagent")).get("actions"))
    tools = items(block.get("tools"))
    slots = {str(s.get("ref")): s for s in items(block.get("credential_slots")) if isinstance(s, dict)}
    found: list[str] = []
    if not tools:
        found.append("actions/plugin.json declares no action tools")
    if len(tools) > MAX_TOOLS:
        found.append(f"actions/plugin.json declares more than {MAX_TOOLS} tools")
    for tool in tools:
        found += action_problems(obj(tool), slots)
    return found


def workflow_problems() -> list[str]:
    found: list[str] = []
    version = (ROOT / "scripts" / "cli-version.txt").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        found.append(f"scripts/cli-version.txt must hold one exact version, not {version!r}")
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        if "@findagent/cli@latest" in workflow.read_text(encoding="utf-8"):
            found.append(f"{workflow.name} runs the platform CLI unpinned; use scripts/cli-version.txt")
    return found


def problems() -> list[str]:
    found: list[str] = []
    node, python = manifest("node"), manifest("python")
    for field in SHARED_FIELDS:
        if node.get(field) != python.get(field):
            found.append(f"findagent.json differs between variants in `{field}`")
    for variant in CODE_VARIANTS:
        found += code_variant_problems(variant, manifest(variant))
    if not same_text(ROOT / "node" / "ui" / "index.html", ROOT / "python" / "ui" / "index.html"):
        found.append("the built panel (ui/index.html) differs between variants")
    for variant in ("package", "actions", "listing"):
        if not same_text(ROOT / variant / "LICENSE", ROOT / "LICENSE"):
            found.append(f"{variant}/LICENSE differs from the root LICENSE")
    if not (ROOT / "listing" / "listing.md").read_text(encoding="utf-8").strip():
        found.append("listing/listing.md is empty")
    return found + package_problems() + actions_problems() + workflow_problems()


def main() -> int:
    found = problems()
    for line in found:
        sys.stderr.write(f"conformance: {line}\n")
    if found:
        return 1
    sys.stdout.write(
        "conformance ok (node/ and python/ agree; node, python and framework meet the code contract; "
        "package and actions are valid; workflows pin the CLI)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
