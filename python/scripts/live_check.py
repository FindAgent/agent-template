"""Live verification: the server over stdio, spoken to by the real MCP SDK client, against the real
crates.io API. No test double anywhere.

    python scripts/live_check.py

It asserts on what is stable about live data (shapes, classes and facts that do not change) and prints the
live figures so a person can read them. A crate's download count or release age is never asserted.

Exit 0: every check passed. Exit 1: a check failed. Exit 2: the registry could not be reached at all,
which says nothing about the agent.
"""

import asyncio
import os
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def connect(env: dict[str, str] | None = None) -> AsyncIterator[ClientSession]:
    # The client starts the server with a minimal environment: pass the module path on, as the sandbox does.
    passed = {**(env or {}), **({"PYTHONPATH": os.environ["PYTHONPATH"]} if "PYTHONPATH" in os.environ else {})}
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")], cwd=str(ROOT), env=passed)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def call(session: ClientSession, name: str, args: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    result = await session.call_tool(name, args)
    return bool(result.isError), dict(result.structuredContent or {})


def show(label: str, error: bool, body: dict[str, Any]) -> None:
    if body.get("kind") == "crate_check":
        signals = " ".join(
            f"{s['id']}={s['status']}" + ("" if s.get("value") is None else f"({s['value']})") for s in body["signals"]
        )
        line = (
            f"{body['crate']}@{body['version']} verdict={body['verdict']} "
            f"requests={body['requests']['used']}/{body['requests']['budget']} {signals}"
        )
    else:
        line = (
            f"{body.get('kind') or body.get('status')} failure={body.get('failure', '-')} "
            f"status={body.get('status', '-')}"
        )
    sys.stdout.write(f"{label:<36} {'isError ' if error else ''}{line}\n")


async def main() -> int:
    async with connect() as session:
        error, serde = await call(session, "run_full", {"crate": "serde"})
        show("run_full serde", error, serde)
        if serde.get("failure") == "network_error":
            sys.stderr.write("crates.io could not be reached from here; nothing was verified.\n")
            return 2
        assert not error
        assert serde["kind"] == "crate_check"
        assert len(serde["signals"]) == 6
        assert serde["requests"]["used"] == 2
        assert serde["notChecked"] == []
        assert re.match(r"^\d+\.\d+\.\d+", serde["version"])

        error, upper = await call(session, "check_crate", {"crate": "SERDE_JSON", "owners": False})
        show("check_crate SERDE_JSON (no owners)", error, upper)
        assert upper["crate"] == "serde_json"
        assert upper["requests"]["used"] == 1
        assert upper["notChecked"][0]["id"] == "owners"

        error, ghost = await call(session, "run_full", {"crate": "agent-template-no-such-crate-zq9x7"})
        show("run_full <no such crate>", error, ghost)
        assert error
        assert ghost["failure"] == "not_found"
        assert ghost["status"] == 404
        assert ghost["requests"]["used"] == 1

        error, bad = await call(session, "run_full", {"crate": "1 not/a crate"})
        show("run_full <invalid name>", error, bad)
        assert bad["failure"] == "invalid_input"
        assert bad["requests"]["used"] == 0

        _, ask = await call(session, "open_form", {})
        assert ask["status"] == "needs_input"
        sys.stdout.write(f"{'open_form':<36} needs_input next={ask['next_question']['field']}\n")

    async with connect({"AGENT_MAX_BYTES": "50000"}) as tiny:
        error, big = await call(tiny, "run_full", {"crate": "serde", "owners": False})
        show("serde with AGENT_MAX_BYTES=50000", error, big)
        assert error
        assert big["failure"] == "response_too_large"

    async with connect({"AGENT_TIMEOUT_MS": "1"}) as impatient:
        error, slow = await call(impatient, "run_full", {"crate": "serde"})
        show("serde with AGENT_TIMEOUT_MS=1", error, slow)
        assert error
        assert slow["failure"] == "timeout"

    sys.stdout.write("live check ok\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
