import pytest

from agent_template.crates import CrateDoc, NameBad, NameOk, fetch_crate, fetch_owner_count, parse_crate_name
from agent_template.http import HttpFail

from .conftest import NOW, TEST_CONFIG, Fake, Reply, crate_doc, routes_for

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("name", ["serde", "tokio", "a", "serde_json", "serde-json", "Rand", "x86_64", "a" * 64])
def test_accepts_what_crates_io_accepts(name: str) -> None:
    assert parse_crate_name(name) == NameOk(name)


def test_trims_surrounding_whitespace() -> None:
    assert parse_crate_name("  serde ") == NameOk("serde")


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "1abc",
        "-abc",
        "has space",
        "../etc/passwd",
        "a/b",
        "@scope/pkg",
        "serde?x=1",
        "serde#frag",
        "serde%2Fx",
        "https://evil.example/x",
        "evil.example:443/x",
        "a" * 65,
        "s" + chr(0xE9) + "rde",
        chr(0x661) + "abc",
    ],
)
def test_rejects_what_crates_io_would_reject_and_anything_that_could_steer_the_url(name: str) -> None:
    assert isinstance(parse_crate_name(name), NameBad)


@pytest.mark.parametrize("value", [42, None, [], {}, True])
def test_a_non_string_is_not_a_name(value: object) -> None:
    assert isinstance(parse_crate_name(value), NameBad)


def test_an_invalid_name_is_quoted_back_only_up_to_80_characters() -> None:
    result = parse_crate_name("1" + "x" * 500)
    assert isinstance(result, NameBad)
    assert len(result.message) < 250


async def test_reads_the_newest_stable_versions_fields() -> None:
    fake = Fake(routes_for("acme-widget", crate_doc(recent_downloads=12)))
    result = await fetch_crate(fake.client, "acme-widget", TEST_CONFIG, NOW)
    assert isinstance(result, CrateDoc)
    assert (result.name, result.version, result.yanked, result.license, result.recent_downloads) == (
        "acme-widget",
        "2.0.0",
        False,
        "MIT OR Apache-2.0",
        12,
    )
    assert result.repository == "https://github.com/acme/acme-widget"


async def test_falls_back_to_max_version_when_there_is_no_stable_one() -> None:
    doc = crate_doc(latest="3.0.0-rc.1")
    doc["crate"]["max_stable_version"] = None
    fake = Fake(routes_for("acme-widget", doc))
    result = await fetch_crate(fake.client, "acme-widget", TEST_CONFIG, NOW)
    assert isinstance(result, CrateDoc)
    assert result.version == "3.0.0-rc.1"


async def test_reads_a_yanked_version_with_its_message_and_treats_blank_text_as_absent() -> None:
    doc = crate_doc(yanked=True, yank_message="broken build", license="  ", repository="")
    fake = Fake(routes_for("acme-widget", doc))
    result = await fetch_crate(fake.client, "acme-widget", TEST_CONFIG, NOW)
    assert isinstance(result, CrateDoc)
    assert (result.yanked, result.yank_message, result.license, result.repository) == (True, "broken build", None, None)


async def test_a_missing_recent_download_count_is_none_never_zero() -> None:
    fake = Fake(routes_for("acme-widget", crate_doc(recent_downloads=None)))
    result = await fetch_crate(fake.client, "acme-widget", TEST_CONFIG, NOW)
    assert isinstance(result, CrateDoc)
    assert result.recent_downloads is None


async def test_a_missing_crate_is_not_found_with_the_crate_named() -> None:
    fake = Fake({"crates.io/api/v1/crates/ghost": Reply(404)})
    result = await fetch_crate(fake.client, "ghost", TEST_CONFIG, NOW)
    assert isinstance(result, HttpFail)
    assert result.failure == "not_found"
    assert "ghost" in result.message


def _bad_documents() -> list[object]:
    good = crate_doc()
    return [
        [],
        "text",
        {},
        {"crate": {"name": "x"}},
        {"crate": {"name": "x"}, "versions": []},
        {**good, "versions": []},
        {**good, "versions": [{"num": "2.0.0"}]},
        {**good, "versions": "no"},
        {**good, "crate": {**good["crate"], "recent_downloads": "many"}},
        {**good, "crate": {**good["crate"], "recent_downloads": -1}},
        {**good, "crate": {**good["crate"], "recent_downloads": True}},
    ]


@pytest.mark.parametrize("body", _bad_documents())
async def test_a_document_without_the_fields_the_check_needs_is_malformed_response(body: object) -> None:
    fake = Fake({"crates.io/api/v1/crates/x": Reply(body=body)})
    result = await fetch_crate(fake.client, "x", TEST_CONFIG, NOW)
    assert isinstance(result, HttpFail)
    assert result.failure == "malformed_response"


async def test_requests_the_crate_path_on_crates_io_only() -> None:
    fake = Fake(routes_for("Acme_Widget", crate_doc(name="Acme_Widget")))
    await fetch_crate(fake.client, "Acme_Widget", TEST_CONFIG, NOW)
    assert len(fake.requests) == 1
    assert fake.requests[0].url.host == "crates.io"
    assert fake.requests[0].url.path == "/api/v1/crates/Acme_Widget"


async def test_passes_upstream_failures_through_unchanged() -> None:
    fake = Fake({"crates.io/api/v1/crates/x": Reply(429, headers={"retry-after": "10"})})
    result = await fetch_crate(fake.client, "x", TEST_CONFIG, NOW)
    assert isinstance(result, HttpFail)
    assert result.failure == "rate_limited"
    assert result.resets_at is not None


async def test_owner_count_counts_people_and_teams() -> None:
    fake = Fake(routes_for("acme-widget", crate_doc(), 4))
    assert await fetch_owner_count(fake.client, "acme-widget", TEST_CONFIG, NOW) == 4
    assert fake.requests[0].url.path == "/api/v1/crates/acme-widget/owners"


async def test_zero_owners_is_a_measured_zero() -> None:
    fake = Fake(routes_for("acme-widget", crate_doc(), 0))
    assert await fetch_owner_count(fake.client, "acme-widget", TEST_CONFIG, NOW) == 0


@pytest.mark.parametrize("body", [{}, {"users": "x"}, [], None])
async def test_an_owners_body_without_a_users_list_is_malformed_response(body: object) -> None:
    fake = Fake(routes_for("acme-widget", crate_doc(), Reply(body=body)))
    result = await fetch_owner_count(fake.client, "acme-widget", TEST_CONFIG, NOW)
    assert isinstance(result, HttpFail)
    assert result.failure == "malformed_response"
