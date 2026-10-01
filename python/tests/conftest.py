"""Shared test doubles. These live in tests/ only: nothing under agent_template/ knows they exist.

Routes are keyed by `host + path`; every request is recorded so a test can assert the request budget,
the method, the host and the headers.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from agent_template.config import DEFAULTS, Config

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)

#: The default limits with no pause between requests, so a test does not sit through the spacing.
TEST_CONFIG: Config = Config(timeout_ms=DEFAULTS.timeout_ms, max_bytes=DEFAULTS.max_bytes, spacing_ms=0)


def days_ago(n: float) -> str:
    return (NOW - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class Reply:
    status: int = 200
    body: Any = None
    raw: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


Route = Reply | Callable[[], Awaitable[httpx.Response]]


class Fake:
    """An httpx client that answers from a route table and records what it was asked."""

    def __init__(self, routes: dict[str, Route]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle), follow_redirects=False)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.url.host}{unquote(request.url.path)}"
        route = self.routes.get(key)
        if route is None:
            return httpx.Response(404, json={"errors": [{"detail": f"no route for {key}"}]})
        if callable(route):
            return await route()
        text = route.raw if route.raw is not None else json.dumps(route.body if route.body is not None else {})
        return httpx.Response(
            route.status, content=text.encode(), headers={"content-type": "application/json", **route.headers}
        )

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


def crate_doc(
    *,
    name: str = "acme-widget",
    latest: str = "2.0.0",
    published_days_ago: float = 30,
    yanked: bool = False,
    yank_message: str | None = None,
    license: str | None = "MIT OR Apache-2.0",
    repository: str | None = "__default__",
    recent_downloads: int | None = 250_000,
) -> dict[str, Any]:
    """A crates.io crate document, shaped like the real one for the fields the check reads."""
    return {
        "crate": {
            "id": name,
            "name": name,
            "max_version": latest,
            "max_stable_version": latest,
            "default_version": latest,
            "repository": f"https://github.com/acme/{name}" if repository == "__default__" else repository,
            "recent_downloads": recent_downloads,
            "downloads": 9_000_000,
        },
        "versions": [
            {"num": "1.0.0", "yanked": False, "created_at": days_ago(900), "license": "MIT"},
            {
                "num": latest,
                "yanked": yanked,
                "yank_message": yank_message,
                "created_at": days_ago(published_days_ago),
                "license": license,
            },
        ],
    }


def routes_for(name: str, doc: dict[str, Any], owners: Reply | int = 3) -> dict[str, Route]:
    reply = (
        Reply(body={"users": [{"id": i, "login": f"o{i}"} for i in range(owners)]})
        if isinstance(owners, int)
        else owners
    )
    return {
        f"crates.io/api/v1/crates/{name}": Reply(body=doc),
        f"crates.io/api/v1/crates/{name}/owners": reply,
    }
