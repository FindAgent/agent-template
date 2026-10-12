"""The MCP server: the tools and the stdio loop.

stdout belongs to the MCP protocol. Everything this process says about itself goes to stderr through
`logging`; a stray print() would corrupt the stream, which is why ruff forbids it here.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .meta import AGENT_NAME, AGENT_VERSION
from .tools import TOOLS, dispatch_tool

log = logging.getLogger(AGENT_NAME)


def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=t["name"],
            description=t["description"],
            inputSchema=t["inputSchema"],
            annotations=types.ToolAnnotations(**t["annotations"]),
        )
        for t in TOOLS
    ]


def to_call_tool_result(result: dict[str, Any]) -> types.CallToolResult:
    """The JSON any host can read as text, plus the same object as structuredContent. A failed run is
    marked isError so a host treats it as a failure while the body keeps the classified reason."""
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))],
        structuredContent=result,
        isError=result.get("ok") is False,
    )


def build_server() -> Server[Any, Any]:
    server: Server[Any, Any] = Server(AGENT_NAME, version=AGENT_VERSION)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return list_tools()

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        try:
            result = dispatch_tool(name, arguments)
            if result.get("ok") is False:
                log.warning(json.dumps({"event": "run_failed", "tool": name, "failure": result.get("failure")}))
            return to_call_tool_result(result)
        except Exception as err:
            log.error(json.dumps({"event": "tool_error", "tool": name, "message": str(err)}))
            return types.CallToolResult(content=[types.TextContent(type="text", text=str(err))], isError=True)

    return server


async def serve() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        log.info("%s %s MCP server running on stdio", AGENT_NAME, AGENT_VERSION)
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
    logging.getLogger("mcp").setLevel(logging.WARNING)
    anyio.run(serve)
