"""Keep findagent.json identical to the server that actually exists.

`skills[]` is rewritten from the tools the server registers and `version` from pyproject.toml, so the
listing can never advertise a tool the server does not have (or hide one it does). The top-level
fields (name, tagline, description, example_prompts, tags, allowed_hosts, credential_slots ...) are
yours to edit by hand.

    python scripts/sync_manifest.py          rewrite findagent.json
    python scripts/sync_manifest.py --check  exit 1 if findagent.json is out of date
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_template.meta import AGENT_VERSION  # noqa: E402
from agent_template.tools import TOOLS  # noqa: E402

TARGET = ROOT / "findagent.json"


def render() -> str:
    manifest: dict[str, Any] = json.loads(TARGET.read_text(encoding="utf-8"))
    manifest["version"] = AGENT_VERSION
    manifest["skills"] = [
        {"id": t["name"], "name": t["name"], "description": t["description"], "input_schema": t["inputSchema"]}
        for t in TOOLS
    ]
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    nxt = render()
    current = TARGET.read_text(encoding="utf-8").replace("\r\n", "\n")
    if current == nxt:
        return 0
    if "--check" in argv:
        sys.stderr.write("findagent.json is out of date; run: python scripts/sync_manifest.py\n")
        return 1
    TARGET.write_text(nxt, encoding="utf-8", newline="\n")
    sys.stdout.write("updated findagent.json\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
