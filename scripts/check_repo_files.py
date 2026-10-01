"""Check that a code-agent repository carries every file a complete agent repo has.

    python scripts/check_repo_files.py <path-to-agent-repo> [--runtime node|python]

The list lives in scripts/repo-files.json (one definition; init_agent.py creates the same set).
Also checks that every JSON file parses and that the findagent.json entrypoint exists.
Read-only. Exit code 1 when anything required is missing.
"""

import json
import sys
from pathlib import Path

LIST = json.loads((Path(__file__).with_name("repo-files.json")).read_text(encoding="utf-8"))


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: check_repo_files.py <path> [--runtime node|python]", file=sys.stderr)
        return 2
    root = Path(args[0]).resolve()
    runtime = None
    if "--runtime" in sys.argv:
        runtime = sys.argv[sys.argv.index("--runtime") + 1]
    manifest_path = root / "findagent.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError:
            manifest = {}
    if runtime is None:
        kind = (manifest.get("runtime") or {}).get("kind")
        runtime = kind if kind in ("node", "python") else ("python" if (root / "pyproject.toml").exists() else "node")

    problems: list[str] = []

    def need(rel: str) -> None:
        if not (root / rel).exists():
            problems.append(f"missing: {rel}")

    for rel in LIST["all"] + LIST[runtime]:
        need(rel)
    for group in LIST["node_one_of"] if runtime == "node" else []:
        if not any((root / g).exists() for g in group):
            problems.append(f"missing one of: {', '.join(group)}")
    for label, options in LIST["dirs_with_files"].items():
        if not any((root / d).is_dir() and any((root / d).iterdir()) for d in options):
            problems.append(f"missing a non-empty {' or '.join(options)}/ directory")
    for rel in LIST["json_files"]:
        p = root / rel
        if p.exists():
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except ValueError as e:
                problems.append(f"invalid JSON: {rel} ({e})")
    entry = (manifest.get("entrypoint") or {}).get("path")
    built = entry and entry.split("/")[0] in ("dist", "build", "out")
    if entry and not built and not (root / entry).exists():
        problems.append(f"findagent.json entrypoint not found: {entry}")

    for p in problems:
        print(f"FAIL {p}")
    print(f"\n{'OK' if not problems else 'FAILED'}: {len(problems)} problem(s), runtime {runtime}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
