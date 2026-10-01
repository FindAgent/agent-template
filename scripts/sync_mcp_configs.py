"""Writes the MCP client configs of each variant from its findagent.json (the single source).

    python scripts/sync_mcp_configs.py          write them
    python scripts/sync_mcp_configs.py --check  fail when one is stale (CI)

Each variant (node/, python/) is the root of a new agent, so each gets the local stdio launcher in
the shapes the common assistants read: mcp.json, .mcp.json (Claude Code), .cursor/mcp.json (Cursor)
and .vscode/mcp.json (VS Code / GitHub Copilot). Other MCP clients take mcp.json. Hosted use needs
no file: add the gateway address FindAgent shows on the agent's page.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK = "--check" in sys.argv


def server_name(manifest: dict, fallback: str) -> str:
    raw = str(manifest.get("name") or fallback).lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or fallback


def render(variant: Path) -> dict[str, str]:
    manifest = json.loads((variant / "findagent.json").read_text(encoding="utf-8"))
    mcp = manifest["mcp"]
    name = server_name(manifest, variant.name)
    stdio = {"command": mcp["command"], "args": list(mcp.get("args", []))}
    mcp_servers = json.dumps({"mcpServers": {name: stdio}}, indent=2) + "\n"
    return {
        "mcp.json": mcp_servers,
        ".mcp.json": mcp_servers,
        ".cursor/mcp.json": mcp_servers,
        ".vscode/mcp.json": json.dumps({"servers": {name: {"type": "stdio", **stdio}}}, indent=2) + "\n",
    }


def main() -> int:
    stale = 0
    for variant in (ROOT / "node", ROOT / "python"):
        for rel, content in render(variant).items():
            path = variant / rel
            current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
            if current == content:
                continue
            if CHECK:
                print(f"stale: {path.relative_to(ROOT)}", file=sys.stderr)
                stale += 1
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="\n")
                print(f"wrote {path.relative_to(ROOT)}")
    if CHECK and stale:
        print("run: python scripts/sync_mcp_configs.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
