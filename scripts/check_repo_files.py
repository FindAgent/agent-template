"""Check that an agent repository carries every file a complete agent repo has, and that they hold something.

    python scripts/check_repo_files.py <path-to-agent-repo> [--runtime node|python|framework|package|actions|listing]

The list lives in scripts/repo-files.json (one definition; init_agent.py creates the same set).
Besides existence it checks, cheaply, content: no required file is empty, every JSON file parses,
findagent.json carries the keys the platform needs, the entrypoint and the panel it names exist, and an
actions repository declares no plain-http URL. The platform's own whole-repo check is
`npx --yes @findagent/cli check .`; this script does not replace it.
Read-only. Exit code 1 when anything is missing or empty.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

LIST: dict[str, Any] = json.loads(Path(__file__).with_name("repo-files.json").read_text(encoding="utf-8"))

NON_CODE = ("package", "actions", "listing")
#: What a code agent's findagent.json must carry at the top level (the platform refuses a manifest without them).
MANIFEST_KEYS = (
    "schema_version",
    "kind",
    "name",
    "version",
    "tagline",
    "description",
    "example_prompts",
    "tags",
    "entrypoint",
    "runtime",
    "mcp",
    "allowed_hosts",
    "skills",
)
#: Files that may legitimately hold nothing.
MAY_BE_EMPTY = (".gitattributes",)


def out(line: str) -> None:
    sys.stdout.write(f"{line}\n")


def read_json(path: Path) -> tuple[Any, str | None]:
    """The parsed file, or None and the reason it could not be read."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as error:
        return None, str(error)


def ignored_by_git(root: Path, rel: str) -> bool:
    return subprocess.run(["git", "-C", str(root), "check-ignore", "-q", rel], capture_output=True).returncode == 0


def structure_problems(root: Path, wanted: list[str], json_files: list[str]) -> list[str]:
    """Missing, empty and unparsable files, and files .gitignore would hide from the repository."""
    problems = [f"missing: {rel}" for rel in wanted if not (root / rel).exists()]
    for rel in wanted:
        path = root / rel
        if path.is_file() and rel not in MAY_BE_EMPTY and not path.read_bytes().strip():
            problems.append(f"empty: {rel}")
    for rel in json_files:
        if (root / rel).exists():
            _, error = read_json(root / rel)
            if error:
                problems.append(f"invalid JSON: {rel} ({error})")
    if (root / ".git").exists():
        problems += [
            f"ignored by .gitignore (would never be committed): {rel}"
            for rel in wanted
            if (root / rel).exists() and ignored_by_git(root, rel)
        ]
    return problems


def manifest_problems(root: Path, manifest: dict[str, Any]) -> list[str]:
    """findagent.json of a code agent: the required keys, a tool list, the entrypoint and the panel."""
    problems = [f"findagent.json lacks `{key}`" for key in MANIFEST_KEYS if key not in manifest]
    if not manifest.get("skills"):
        problems.append("findagent.json `skills` is empty (the agent would be served with no tools)")
    prompts = manifest.get("example_prompts")
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= 5:
        problems.append("findagent.json `example_prompts` needs 1 to 5 prompts")
    entry = (manifest.get("entrypoint") or {}).get("path")
    built = bool(entry) and str(entry).split("/")[0] in ("dist", "build", "out")
    if entry and not built and not (root / entry).exists():
        problems.append(f"findagent.json entrypoint not found: {entry}")
    panel = (manifest.get("ui") or {}).get("path")
    if panel and not (root / panel).exists():
        problems.append(f"findagent.json ui.path not found: {panel}")
    return problems


def http_action_urls(node: Any) -> list[str]:
    """Every action URL under `node` that is not https."""
    found: list[str] = []
    if isinstance(node, dict):
        url = node.get("url")
        if node.get("type") == "http" and isinstance(url, str) and not url.startswith("https://"):
            found.append(url)
        for value in node.values():
            found += http_action_urls(value)
    elif isinstance(node, list):
        for value in node:
            found += http_action_urls(value)
    return found


def plugin_problems(root: Path, runtime: str) -> list[str]:
    plugin, error = read_json(root / "plugin.json")
    if error or not isinstance(plugin, dict):
        return []  # structure_problems already reported it
    problems = [f"plugin.json lacks `{key}`" for key in ("name", "description", "version") if not plugin.get(key)]
    if runtime == "actions":
        problems += [f"actions must use https: {url}" for url in http_action_urls(plugin)]
    return problems


def finish(problems: list[str], runtime: str) -> int:
    for problem in problems:
        out(f"FAIL {problem}")
    out(f"\n{'OK' if not problems else 'FAILED'}: {len(problems)} problem(s), runtime {runtime}")
    return 1 if problems else 0


def check_non_code(root: Path, runtime: str) -> int:
    """A package, actions or listing repository: the common files and the variant's own, valid JSON, nothing ignored."""
    wanted = LIST["common"] + LIST[runtime]
    problems = structure_problems(root, wanted, LIST["non_code_json_files"][runtime])
    if runtime in ("package", "actions"):
        problems += plugin_problems(root, runtime)
    return finish(problems, runtime)


def detect_runtime(root: Path, manifest: dict[str, Any]) -> str:
    if not (root / "findagent.json").exists():
        if (root / "plugin.json").exists():
            return "actions" if "cloud.findagent" in (root / "plugin.json").read_text(encoding="utf-8") else "package"
        if (root / "listing.md").exists():
            return "listing"
    kind = (manifest.get("runtime") or {}).get("kind")
    runtime = kind if kind in ("node", "python") else ("python" if (root / "pyproject.toml").exists() else "node")
    return "framework" if runtime == "python" and (root / "framework_agent").is_dir() else str(runtime)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        kinds = "node|python|framework|package|actions|listing"
        sys.stderr.write(f"usage: check_repo_files.py <path> [--runtime {kinds}]\n")
        return 2
    root = Path(args[0]).resolve()
    manifest: dict[str, Any] = {}
    if (root / "findagent.json").exists():
        parsed, _ = read_json(root / "findagent.json")
        manifest = parsed if isinstance(parsed, dict) else {}
    runtime = sys.argv[sys.argv.index("--runtime") + 1] if "--runtime" in sys.argv else detect_runtime(root, manifest)
    if runtime in NON_CODE:
        return check_non_code(root, runtime)

    wanted = LIST["all"] + LIST[runtime]
    problems = structure_problems(root, wanted, LIST["json_files"])
    if runtime == "node":
        problems += [
            f"missing one of: {', '.join(group)}"
            for group in LIST["node_one_of"]
            if not any((root / g).exists() for g in group)
        ]
    for options in LIST["dirs_with_files"].values():
        if not any((root / d).is_dir() and any((root / d).iterdir()) for d in options):
            problems.append(f"missing a non-empty {' or '.join(options)}/ directory")
    problems += manifest_problems(root, manifest)
    return finish(problems, runtime)


if __name__ == "__main__":
    sys.exit(main())
