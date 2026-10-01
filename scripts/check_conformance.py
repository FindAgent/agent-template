"""The two variants are one agent in two languages. This keeps them from drifting apart.

Run from the repository root:

    python scripts/check_conformance.py

It fails (exit 1) when the Node and Python variants disagree on anything a buyer or the platform sees:
the listing text, the allowed hosts, the tool list with each description and input schema, the result
panel (byte for byte), or when a variant stops being a valid code-bundle contract. Standard library only.
"""

import json
import sys
from pathlib import Path

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
RUNTIMES = {"node": {"node"}, "python": {"python"}}


def load(variant: str) -> dict[str, object]:
    return json.loads((ROOT / variant / "findagent.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def problems() -> list[str]:
    found: list[str] = []
    node, python = load("node"), load("python")
    for field in SHARED_FIELDS:
        if node.get(field) != python.get(field):
            found.append(f"findagent.json differs between variants in `{field}`")
    for variant, manifest in (("node", node), ("python", python)):
        runtime = manifest.get("runtime")
        kind = runtime.get("kind") if isinstance(runtime, dict) else None
        if kind not in RUNTIMES[variant]:
            found.append(f"{variant}/findagent.json runtime.kind is {kind!r}")
        skills = manifest.get("skills")
        if not isinstance(skills, list) or len(skills) != 7:
            found.append(f"{variant}/findagent.json skills[] must list the seven tools")
    if (ROOT / "node" / "ui" / "index.html").read_bytes() != (ROOT / "python" / "ui" / "index.html").read_bytes():
        found.append("the built panel (ui/index.html) differs between variants")
    for name in ("LICENSE",):
        if (ROOT / "node" / name).read_bytes() != (ROOT / name).read_bytes():
            found.append(f"node/{name} differs from the root {name}")
        if (ROOT / "python" / name).read_bytes() != (ROOT / name).read_bytes():
            found.append(f"python/{name} differs from the root {name}")
    return found


def main() -> int:
    found = problems()
    for line in found:
        sys.stderr.write(f"conformance: {line}\n")
    if found:
        return 1
    sys.stdout.write("conformance ok (listing, tools, hosts and panel agree across node/ and python/)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
