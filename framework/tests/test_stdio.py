"""The real server, spoken to over stdio by the real MCP SDK client. Nothing here reaches a network."""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parent.parent
SIX = {"plan_inputs", "open_form", "run_form", "run_full", "list_capabilities", "discover_intent"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@asynccontextmanager
async def connect() -> AsyncIterator[ClientSession]:
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")], cwd=str(ROOT))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def test_lists_the_six_entry_tools_and_the_capability_tool() -> None:
    async with connect() as session:
        names = {t.name for t in (await session.list_tools()).tools}
    assert names >= SIX
    assert "triage_commits" in names


async def test_run_full_over_stdio_returns_structured_notes() -> None:
    async with connect() as session:
        result = await session.call_tool("run_full", {"commits": ["feat: a", "fix: b"]})
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["counts"]["features"] == 1
    assert json.loads(result.content[0].text)["ok"] is True  # type: ignore[union-attr]


async def test_missing_input_is_needs_input_and_bad_input_is_is_error() -> None:
    async with connect() as session:
        missing = await session.call_tool("run_full", {})
        bad = await session.call_tool("run_full", {"commits": 42})
        unknown = await session.call_tool("no_such_tool", {})
        alive = await session.call_tool("list_capabilities", {})
    assert missing.isError is False and missing.structuredContent is not None
    assert missing.structuredContent["status"] == "needs_input"
    assert bad.isError is True and bad.structuredContent is not None
    assert bad.structuredContent["failure"] == "invalid_input"
    assert unknown.isError is True
    assert alive.isError is False
