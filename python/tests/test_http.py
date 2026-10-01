import asyncio
from datetime import timedelta

import httpx
import pytest

from agent_template.config import Config
from agent_template.http import HttpFail, HttpOk, classify_error, get_json, reset_time

from .conftest import NOW, TEST_CONFIG, Fake, Reply

URL = "https://crates.io/api/v1/crates/thing"
KEY = "crates.io/api/v1/crates/thing"
CONFIG = Config(timeout_ms=200, max_bytes=TEST_CONFIG.max_bytes, spacing_ms=0)

pytestmark = pytest.mark.anyio


async def get(fake: Fake, config: Config = CONFIG) -> HttpOk | HttpFail:
    return await get_json(fake.client, URL, config, NOW)


async def test_200_with_json_is_ok() -> None:
    assert await get(Fake({KEY: Reply(body={"a": 1})})) == HttpOk({"a": 1}, 200)


async def test_404_is_not_found_and_only_404() -> None:
    assert await get(Fake({KEY: Reply(404)})) == HttpFail("not_found", "The upstream has no such resource.", 404)


async def test_429_is_rate_limited_with_the_reset_time_from_retry_after_seconds() -> None:
    result = await get(Fake({KEY: Reply(429, headers={"retry-after": "120"})}))
    assert isinstance(result, HttpFail)
    assert (result.failure, result.status) == ("rate_limited", 429)
    assert result.resets_at == (NOW + timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def test_429_with_an_http_date_is_converted_to_iso() -> None:
    result = await get(Fake({KEY: Reply(429, headers={"retry-after": "Thu, 01 Oct 2026 13:00:00 GMT"})}))
    assert isinstance(result, HttpFail)
    assert result.resets_at == "2026-10-01T13:00:00.000Z"


@pytest.mark.parametrize("headers", [{}, {"retry-after": "soon"}, {"retry-after": ""}])
async def test_429_without_a_usable_retry_after_invents_no_time(headers: dict[str, str]) -> None:
    result = await get(Fake({KEY: Reply(429, headers=headers)}))
    assert isinstance(result, HttpFail)
    assert result.failure == "rate_limited"
    assert result.resets_at is None
    assert "did not say when" in result.message


@pytest.mark.parametrize("status", [500, 502, 503, 401, 403, 418])
async def test_5xx_and_unexpected_4xx_are_upstream_error_never_not_found(status: int) -> None:
    result = await get(Fake({KEY: Reply(status)}))
    assert isinstance(result, HttpFail)
    assert (result.failure, result.status) == ("upstream_error", status)


async def test_a_redirect_is_refused_and_never_followed() -> None:
    fake = Fake({KEY: Reply(301, headers={"location": "https://evil.example/x"})})
    result = await get(fake)
    assert isinstance(result, HttpFail)
    assert (result.failure, result.status) == ("upstream_error", 301)
    assert len(fake.requests) == 1


async def test_a_200_that_is_not_json_is_malformed_response() -> None:
    result = await get(Fake({KEY: Reply(raw="<html>oops</html>")}))
    assert isinstance(result, HttpFail)
    assert result.failure == "malformed_response"


async def test_a_body_over_the_byte_cap_is_response_too_large() -> None:
    fake = Fake({KEY: Reply(raw='{"x": "' + "y" * 5000 + '"}')})
    result = await get(fake, Config(timeout_ms=200, max_bytes=1000, spacing_ms=0))
    assert isinstance(result, HttpFail)
    assert result.failure == "response_too_large"


async def test_a_declared_content_length_over_the_cap_is_refused_before_reading() -> None:
    fake = Fake({KEY: Reply(body={"a": 1}, headers={"content-length": "999999"})})
    result = await get(fake, Config(timeout_ms=200, max_bytes=1000, spacing_ms=0))
    assert isinstance(result, HttpFail)
    assert result.failure == "response_too_large"


async def test_a_request_that_never_answers_is_a_timeout_not_a_network_error() -> None:
    async def hang() -> httpx.Response:
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    result = await get(Fake({KEY: hang}))
    assert isinstance(result, HttpFail)
    assert result.failure == "timeout"


async def test_an_httpx_timeout_is_a_timeout() -> None:
    async def slow() -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    result = await get(Fake({KEY: slow}))
    assert isinstance(result, HttpFail)
    assert result.failure == "timeout"


async def test_a_connection_that_fails_is_network_error_and_names_the_cause() -> None:
    async def down() -> httpx.Response:
        raise httpx.ConnectError("all connection attempts failed")

    result = await get(Fake({KEY: down}))
    assert isinstance(result, HttpFail)
    assert result.failure == "network_error"
    assert "ConnectError" in result.message


async def test_sends_get_with_a_user_agent_and_asks_for_json() -> None:
    fake = Fake({KEY: Reply(body={})})
    await get(fake)
    request = fake.requests[0]
    assert request.method == "GET"
    assert request.headers["user-agent"].startswith("agent-template/")
    assert request.headers["accept"] == "application/json"


def test_classify_error_separates_timeout_from_network() -> None:
    assert classify_error(httpx.ConnectTimeout("x")).failure == "timeout"
    assert classify_error(httpx.PoolTimeout("x")).failure == "timeout"
    assert classify_error(httpx.ConnectError("x")).failure == "network_error"
    assert classify_error(httpx.RemoteProtocolError("x")).failure == "network_error"


def test_reset_time_handles_seconds_dates_junk_and_absence() -> None:
    assert reset_time("30", NOW) == "2026-10-01T12:00:30.000Z"
    assert reset_time("Thu, 01 Oct 2026 13:00:00 GMT", NOW) == "2026-10-01T13:00:00.000Z"
    assert reset_time("nonsense", NOW) is None
    assert reset_time(None, NOW) is None
    assert reset_time("²", NOW) is None
