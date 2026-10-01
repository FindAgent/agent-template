"""The one place that talks to the network. GET only, JSON only, no credentials.

Every way a request can go wrong is its own class. Nothing here returns a bare None or an empty
value: a caller always learns WHICH condition it hit, because "not found", "refused" and "could not
reach" call for different things from the person asking.

Egress is default-deny on the platform, so the hosts this module may reach are the
`allowed_hosts` in findagent.json. A redirect is never followed: the platform would refuse a hop to
an undeclared host, and an agent should not rely on being refused.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx

from .clock import iso_utc
from .config import Config
from .meta import USER_AGENT

Failure = Literal[
    "not_found",
    "rate_limited",
    "timeout",
    "network_error",
    "upstream_error",
    "malformed_response",
    "response_too_large",
]


@dataclass(frozen=True)
class HttpOk:
    json: Any
    status: int


@dataclass(frozen=True)
class HttpFail:
    failure: Failure
    message: str
    status: int | None = None
    resets_at: str | None = None


def reset_time(header: str | None, now: datetime) -> str | None:
    """Retry-After is either a number of seconds or an HTTP date. Anything else yields no reset time."""
    if header is None:
        return None
    value = header.strip()
    if value.isascii() and value.isdigit():
        return iso_utc(now + timedelta(seconds=int(value)))
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return iso_utc(when)


def classify_error(err: httpx.HTTPError) -> HttpFail:
    """A timeout and a failed connection are different conditions; a transport error names its cause."""
    if isinstance(err, httpx.TimeoutException):
        return HttpFail("timeout", "The upstream did not answer in time.")
    cause = err.__cause__ or err.__context__
    detail = type(cause).__name__ if cause is not None else type(err).__name__
    return HttpFail("network_error", f"Could not reach the upstream ({detail}).")


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes | None:
    """Read a body up to `max_bytes`. Returns None when the body is larger than the cap."""
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def _fetch(client: httpx.AsyncClient, url: str, config: Config, now: datetime) -> HttpOk | HttpFail:
    async with client.stream(
        "GET",
        url,
        headers={"accept": "application/json", "user-agent": USER_AGENT},
        follow_redirects=False,
    ) as response:
        status = response.status_code
        if status == 404:
            return HttpFail("not_found", "The upstream has no such resource.", 404)
        if status == 429:
            resets_at = reset_time(response.headers.get("retry-after"), now)
            message = (
                f"The upstream is rate limiting this client until {resets_at}."
                if resets_at
                else "The upstream is rate limiting this client and did not say when it lifts."
            )
            return HttpFail("rate_limited", message, 429, resets_at)
        if 300 <= status < 400:
            return HttpFail(
                "upstream_error",
                f"The upstream answered with a redirect ({status}); redirects are not followed.",
                status,
            )
        if not response.is_success:
            return HttpFail("upstream_error", f"The upstream answered with HTTP {status}.", status)

        body = await _read_capped(response, config.max_bytes)
        if body is None:
            return HttpFail(
                "response_too_large",
                f"The response is larger than the {config.max_bytes}-byte limit, so it was not read.",
                status,
            )
        try:
            return HttpOk(json.loads(body), status)
        except ValueError:
            return HttpFail("malformed_response", "The upstream answered 200 but the body is not valid JSON.", status)


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    config: Config,
    now: datetime | None = None,
) -> HttpOk | HttpFail:
    """GET `url` and return the parsed JSON, or the classified reason it could not be had.

    The whole request, body included, shares one deadline of `config.timeout_ms`.
    """
    moment = now or datetime.now(UTC)
    try:
        async with asyncio.timeout(config.timeout_ms / 1000):
            return await _fetch(client, url, config, moment)
    except TimeoutError:
        return HttpFail("timeout", "The upstream did not answer in time.")
    except httpx.HTTPError as err:
        return classify_error(err)
