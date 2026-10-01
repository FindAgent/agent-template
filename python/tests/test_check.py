from dataclasses import replace
from typing import Any

import httpx
import pytest

from agent_template.check import REQUEST_BUDGET, check_crate

from .conftest import NOW, TEST_CONFIG, Fake, Reply, crate_doc, routes_for

pytestmark = pytest.mark.anyio


async def run(
    name: object, fake: Fake, *, owners: bool = True, sleep: Any = None, config: Any = TEST_CONFIG
) -> dict[str, Any]:
    return await check_crate(name, client=fake.client, config=config, owners=owners, now=lambda: NOW, sleep=sleep)


async def test_a_healthy_crate_returns_every_signal_the_verdict_and_the_request_count() -> None:
    fake = Fake(routes_for("acme-widget", crate_doc()))
    result = await run("acme-widget", fake)
    assert (result["kind"], result["ok"], result["crate"], result["version"], result["verdict"]) == (
        "crate_check",
        True,
        "acme-widget",
        "2.0.0",
        "healthy",
    )
    assert result["checkedAt"] == "2026-10-01T12:00:00.000Z"
    assert result["requests"] == {"used": 2, "budget": REQUEST_BUDGET}
    assert result["notChecked"] == []
    assert len(result["signals"]) == 6
    assert fake.paths == ["/api/v1/crates/acme-widget", "/api/v1/crates/acme-widget/owners"]


async def test_owners_false_spends_one_request_and_reports_the_signal_as_not_checked() -> None:
    fake = Fake(routes_for("acme-widget", crate_doc()))
    result = await run("acme-widget", fake, owners=False)
    assert result["requests"]["used"] == 1
    assert [n["id"] for n in result["notChecked"]] == ["owners"]
    assert "switched off" in result["notChecked"][0]["reason"]
    assert len(fake.requests) == 1


async def test_reports_the_canonical_name_the_registry_returned_not_the_casing_asked_for() -> None:
    fake = Fake(
        {
            "crates.io/api/v1/crates/SERDE": Reply(body=crate_doc(name="serde")),
            "crates.io/api/v1/crates/SERDE/owners": Reply(body={"users": [{}, {}]}),
        }
    )
    assert (await run("SERDE", fake))["crate"] == "serde"


async def test_a_yanked_stale_crate_is_risky_and_the_summary_says_why() -> None:
    doc = crate_doc(name="old-thing", yanked=True, yank_message="use new-thing", published_days_ago=3000)
    result = await run("old-thing", Fake(routes_for("old-thing", doc)))
    assert (result["ok"], result["verdict"]) == (True, "risky")
    assert "use new-thing" in result["summary"]


@pytest.mark.parametrize(
    "reply",
    [
        Reply(429),
        Reply(404),
        Reply(503),
        Reply(raw="nope"),
        Reply(body={"users": "many"}),
    ],
    ids=["rate limited", "not found", "a server error", "not JSON", "the wrong shape"],
)
async def test_the_owners_read_failing_does_not_fail_the_check(reply: Reply) -> None:
    result = await run("acme-widget", Fake(routes_for("acme-widget", crate_doc(), reply)))
    assert result["ok"] is True
    assert result["requests"]["used"] == 2
    assert [n["id"] for n in result["notChecked"]] == ["owners"]
    assert result["notChecked"][0]["reason"].split(":")[0] in {
        "rate_limited",
        "not_found",
        "upstream_error",
        "malformed_response",
    }
    assert result["verdict"] == "healthy"


async def test_invalid_input_costs_no_request() -> None:
    fake = Fake({})
    for value in ["", "1bad", "../x", "a b", 7, None]:
        result = await run(value, fake)
        assert (result["kind"], result["ok"], result["failure"], result["requests"]["used"]) == (
            "crate_failure",
            False,
            "invalid_input",
            0,
        )
    assert fake.requests == []


async def test_not_found_is_not_found_and_spends_one_request_not_two() -> None:
    fake = Fake({"crates.io/api/v1/crates/ghost": Reply(404)})
    result = await run("ghost", fake)
    assert (result["failure"], result["status"], result["requests"]["used"]) == ("not_found", 404, 1)
    assert len(fake.requests) == 1


async def test_rate_limited_carries_the_reset_time_and_is_never_reported_as_not_found() -> None:
    fake = Fake({"crates.io/api/v1/crates/busy": Reply(429, headers={"retry-after": "60"})})
    result = await run("busy", fake)
    assert result["failure"] == "rate_limited"
    assert result["resetsAt"] == "2026-10-01T12:01:00.000Z"


async def test_a_403_is_upstream_error_not_not_found_a_refusal_is_not_an_absence() -> None:
    result = await run("walled", Fake({"crates.io/api/v1/crates/walled": Reply(403)}))
    assert (result["failure"], result["status"]) == ("upstream_error", 403)


@pytest.mark.parametrize(
    "name,reply,expected",
    [
        ("boom", Reply(500), "upstream_error"),
        ("junk", Reply(raw="<html>"), "malformed_response"),
        ("shape", Reply(body={"crate": {"name": "shape"}}), "malformed_response"),
    ],
)
async def test_each_remaining_class_keeps_its_own_name(name: str, reply: Reply, expected: str) -> None:
    result = await run(name, Fake({f"crates.io/api/v1/crates/{name}": reply}))
    assert result["failure"] == expected


async def test_a_network_failure_is_reported_as_one_not_as_a_missing_crate() -> None:
    async def down() -> httpx.Response:
        raise httpx.ConnectError("no route")

    result = await run("acme", Fake({"crates.io/api/v1/crates/acme": down}))
    assert result["failure"] == "network_error"


async def test_a_failure_never_reads_as_a_clean_verdict() -> None:
    result = await run("boom", Fake({"crates.io/api/v1/crates/boom": Reply(500)}))
    assert "verdict" not in result
    assert "signals" not in result


async def test_waits_the_configured_spacing_once_between_the_two_requests() -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    config = replace(TEST_CONFIG, spacing_ms=1000)
    await run("acme-widget", Fake(routes_for("acme-widget", crate_doc())), sleep=sleep, config=config)
    assert waits == [1.0]


async def test_does_not_wait_without_a_second_request_or_with_zero_spacing() -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    config = replace(TEST_CONFIG, spacing_ms=1000)
    await run("acme-widget", Fake(routes_for("acme-widget", crate_doc())), owners=False, sleep=sleep, config=config)
    await run("acme-widget", Fake(routes_for("acme-widget", crate_doc())), sleep=sleep)
    assert waits == []


async def test_the_second_request_really_comes_after_the_wait() -> None:
    order: list[str] = []
    fake = Fake(routes_for("acme-widget", crate_doc()))

    async def sleep(seconds: float) -> None:
        order.append("wait")

    original = fake._handle

    async def spying(request: httpx.Request) -> httpx.Response:
        order.append("owners" if request.url.path.endswith("/owners") else "crate")
        return await original(request)

    fake.client = httpx.AsyncClient(transport=httpx.MockTransport(spying), follow_redirects=False)
    await run("acme-widget", fake, sleep=sleep, config=replace(TEST_CONFIG, spacing_ms=50))
    assert order == ["crate", "wait", "owners"]
