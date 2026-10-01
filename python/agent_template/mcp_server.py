"""The MCP server: tools, the result panel, elicitation, and the stdio loop.

stdout belongs to the MCP protocol. Everything this process says about itself goes to stderr through
`logging`; a stray print() would corrupt the stream, which is why ruff forbids it here.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import anyio
import httpx
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from pydantic import AnyUrl

from .check import check_crate
from .config import load_config
from .meta import AGENT_NAME, AGENT_VERSION
from .tools import PANEL_RESOURCE_URI, RUNNING_TOOLS, TOOLS, dispatch_tool, panel_binding

log = logging.getLogger(AGENT_NAME)

#: The MCP Apps resource mime type (spec 2026-01-26).
PANEL_MIME_TYPE = "text/html;profile=mcp-app"

#: The result panel: ONE self-contained HTML document, built from panel/ and committed (the sandbox
#: only installs Python packages, it has no step that could build it).
PANEL_FILE = Path(__file__).resolve().parent.parent / "ui" / "index.html"

# The resource `_meta` keeps the sandbox closed (`ui.csp: {}`) and leaves `ui.domain` unset: the host
# assigns its own sandbox domain and rejects any other value.
PANEL_META: dict[str, Any] = {
    "ui": {"csp": {}, "prefersBorder": True},
    "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    "openai/widgetDescription": "The signals and verdict for a crate, or why the check failed.",
}


def list_tools() -> list[types.Tool]:
    """Every registered tool is advertised, each bound to the result panel and model-only."""
    return [
        types.Tool(
            name=t["name"],
            description=t["description"],
            inputSchema=t["inputSchema"],
            annotations=types.ToolAnnotations(**t["annotations"]),
            _meta=panel_binding(PANEL_RESOURCE_URI),
        )
        for t in TOOLS
    ]


def to_call_tool_result(result: dict[str, Any]) -> types.CallToolResult:
    """The wire result: the JSON any host can read as text, plus the same object as structuredContent
    for a panel. A failed check is marked isError so a host treats it as a failure while the body
    keeps the classified reason."""
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))],
        structuredContent=result,
        isError=result.get("ok") is False,
    )


def log_outcome(tool: str, result: dict[str, Any]) -> None:
    """One structured line on stderr for every failed check, so an operator reading the sandbox log
    learns WHICH failure happened, for which crate, without reading code. Only classified facts are
    logged: no argument other than the public crate name, and never a response body."""
    if result.get("ok") is False:
        log.warning(
            json.dumps(
                {
                    "event": "check_failed",
                    "tool": tool,
                    "failure": result.get("failure"),
                    "crate": result.get("crate"),
                    "status": result.get("status"),
                    "requests": result.get("requests"),
                }
            )
        )


def build_server() -> Server[Any, Any]:
    server: Server[Any, Any] = Server(AGENT_NAME, version=AGENT_VERSION)

    async def run_check(crate: object, owners: bool) -> dict[str, Any]:
        config = load_config()
        # One client per check; redirects are never followed (see http.py), and the timeout is the
        # one deadline http.get_json enforces around the whole request.
        async with httpx.AsyncClient(follow_redirects=False, timeout=None) as client:
            return await check_crate(crate, client=client, config=config, owners=owners)

    async def try_elicit(name: str, args: dict[str, Any], need: dict[str, Any]) -> dict[str, Any] | None:
        """Best-effort native form. Only the tools that run a check are upgraded: open_form and
        plan_inputs exist to hand the questions to the platform's form (or the user), not to run
        anything. Any failure, a declined form or a client without the capability falls through to the
        needs_input JSON, unchanged."""
        if name not in RUNNING_TOOLS:
            return None
        session = server.request_context.session
        if not session.check_client_capability(types.ClientCapabilities(elicitation=types.ElicitationCapability())):
            return None
        try:
            answer = await session.elicit(
                message="One more detail is needed to run this check.", requestedSchema=need["schema"]
            )
        except Exception as err:
            log.warning("elicitation failed, returning needs_input instead: %s", err)
            return None
        if answer.action != "accept" or not answer.content:
            return None
        return await dispatch_tool(name, {**args, **answer.content}, run_check)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return list_tools()

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        try:
            result = await dispatch_tool(name, arguments, run_check)
            if result.get("status") == "needs_input" and isinstance(result.get("schema"), dict):
                elicited = await try_elicit(name, arguments, result)
                if elicited is not None:
                    result = elicited
            log_outcome(name, result)
            return to_call_tool_result(result)
        except Exception as err:
            log.error(json.dumps({"event": "tool_error", "tool": name, "message": str(err)}))
            return types.CallToolResult(content=[types.TextContent(type="text", text=str(err))], isError=True)

    @server.list_resources()
    async def _list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=AnyUrl(PANEL_RESOURCE_URI),
                name="Crate check panel",
                description="Draws the signals and verdict of a crate check, or the failure.",
                mimeType=PANEL_MIME_TYPE,
                _meta=PANEL_META,
            )
        ]

    @server.read_resource()
    async def _read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        if str(uri) != PANEL_RESOURCE_URI:
            raise ValueError(f"Unknown resource: {uri}")
        return [
            ReadResourceContents(
                content=PANEL_FILE.read_text(encoding="utf-8"), mime_type=PANEL_MIME_TYPE, meta=PANEL_META
            )
        ]

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
