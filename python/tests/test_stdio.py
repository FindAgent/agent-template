"""The real server, spoken to over stdio by the real MCP SDK client.

Nothing here reaches the network: every call either asks for input or names an invalid crate, both
answered before any request is made. Live behaviour against crates.io is scripts/live_check.py.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import mcp.types as types
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.context import RequestContext

from agent_template.tools import TOOLS

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def connect(*, elicit: Any = None, env: dict[str, str] | None = None) -> AsyncIterator[ClientSession]:
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")], cwd=str(ROOT), env=env)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write, elicitation_callback=elicit) as session,
    ):
        await session.initialize()
        yield session


async def call(session: ClientSession, name: str, args: dict[str, Any] | None = None) -> types.CallToolResult:
    return await session.call_tool(name, args or {})


async def test_lists_every_tool_each_bound_to_the_panel_and_model_only() -> None:
    async with connect() as session:
        tools = (await session.list_tools()).tools
    assert sorted(t.name for t in tools) == sorted(t["name"] for t in TOOLS)
    for tool in tools:
        meta = tool.meta or {}
        assert meta["ui"]["visibility"] == ["model"]
        assert meta["openai/widgetAccessible"] is False
        assert meta["ui"]["resourceUri"].startswith("ui://")
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True


async def test_serves_the_panel_as_one_closed_document_with_no_domain() -> None:
    async with connect() as session:
        resources = (await session.list_resources()).resources
        assert len(resources) == 1
        resource = resources[0]
        assert resource.mimeType == "text/html;profile=mcp-app"
        meta = resource.meta or {}
        assert meta["ui"] == {"csp": {}, "prefersBorder": True}
        assert "domain" not in meta["ui"]
        assert meta["openai/widgetCSP"] == {"connect_domains": [], "resource_domains": []}
        read = await session.read_resource(resource.uri)
    content = read.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.mimeType == "text/html;profile=mcp-app"
    assert "ui/initialize" in content.text
    assert content.text == (ROOT / "ui" / "index.html").read_text(encoding="utf-8")


async def test_refuses_an_unknown_resource() -> None:
    async with connect() as session:
        with pytest.raises(Exception, match=r"Unknown resource|error"):
            await session.read_resource("ui://nope/none")  # type: ignore[arg-type]


async def test_a_missing_crate_is_needs_input_not_an_error() -> None:
    async with connect() as session:
        result = await call(session, "run_full")
    assert result.isError is False
    assert result.structuredContent is not None
    assert (result.structuredContent["status"], result.structuredContent["missing"]) == ("needs_input", ["crate"])


async def test_an_invalid_crate_is_is_error_with_the_class_in_the_body_at_no_network_cost() -> None:
    async with connect() as session:
        result = await call(session, "run_full", {"crate": "Not A Crate"})
    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["kind"] == "crate_failure"
    assert result.structuredContent["failure"] == "invalid_input"
    assert result.structuredContent["requests"]["used"] == 0


async def test_an_unknown_tool_is_an_error_result_not_a_crash_and_the_server_keeps_serving() -> None:
    async with connect() as session:
        result = await call(session, "no_such_tool")
        assert result.isError is True
        assert "Unknown tool" in result.content[0].text  # type: ignore[union-attr]
        assert (await call(session, "list_capabilities")).isError is False


async def test_a_bad_knob_is_ignored_and_the_server_still_serves() -> None:
    async with connect(env={"AGENT_TIMEOUT_MS": "banana"}) as session:
        assert (await call(session, "list_capabilities")).isError is False


async def test_stdout_carries_protocol_only_so_a_plain_call_never_corrupts_the_stream() -> None:
    # If anything wrote a non-JSON line to stdout, the client would fail to parse and the call would
    # raise. Many calls in a row exercise every handler.
    async with connect() as session:
        for tool in ["open_form", "plan_inputs", "list_capabilities", "run_full", "discover_intent"]:
            result = await call(session, tool, {"goal": "x"} if tool == "discover_intent" else {})
            assert result.structuredContent is not None, tool


async def test_a_run_tool_missing_its_input_asks_the_client_and_re_runs_with_the_answer() -> None:
    asked: list[types.ElicitRequestParams] = []

    async def elicit(
        context: RequestContext[ClientSession, Any], params: types.ElicitRequestParams
    ) -> types.ElicitResult:
        asked.append(params)
        # An invalid name keeps this test off the network while proving the answer was used.
        return types.ElicitResult(action="accept", content={"crate": "Not A Crate"})

    async with connect(elicit=elicit) as session:
        result = await call(session, "run_full")
    assert len(asked) == 1
    assert result.structuredContent is not None
    assert result.structuredContent["failure"] == "invalid_input"


async def test_a_declined_form_falls_back_to_the_needs_input_answer() -> None:
    async def elicit(
        context: RequestContext[ClientSession, Any], params: types.ElicitRequestParams
    ) -> types.ElicitResult:
        return types.ElicitResult(action="decline")

    async with connect(elicit=elicit) as session:
        result = await call(session, "run_full")
    assert result.structuredContent is not None
    assert result.structuredContent["status"] == "needs_input"


async def test_open_form_and_plan_inputs_are_never_turned_into_a_form() -> None:
    asked: list[object] = []

    async def elicit(
        context: RequestContext[ClientSession, Any], params: types.ElicitRequestParams
    ) -> types.ElicitResult:
        asked.append(params)
        return types.ElicitResult(action="accept", content={"crate": "Not A Crate"})

    async with connect(elicit=elicit) as session:
        for tool in ["open_form", "plan_inputs"]:
            result = await call(session, tool)
            assert result.structuredContent is not None
            assert result.structuredContent["status"] == "needs_input", tool
    assert asked == []


async def test_a_client_without_the_capability_gets_needs_input() -> None:
    async with connect() as session:
        result = await call(session, "run_full")
    assert result.structuredContent is not None
    assert result.structuredContent["status"] == "needs_input"
