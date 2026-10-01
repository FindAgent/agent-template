"""The two upstream reads, each validated at the boundary with pydantic.

A body that does not have the fields a signal needs is `malformed_response`, never a signal quietly
computed from nothing.

Host (keep in sync with `allowed_hosts` in findagent.json; tests/test_egress.py enforces it):
    crates.io   the crate document and its owners list

The crate name is the only caller-supplied part of a URL. It is validated against crates.io's own
naming rule and put in the PATH, so a caller can never choose the host.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError

from .config import Config
from .http import Failure, HttpFail, get_json

CRATES_HOST = "crates.io"

# crates.io's rule for a crate name: ASCII letters, digits, - and _, starting with a letter, at most 64.
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")


@dataclass(frozen=True)
class NameOk:
    name: str


@dataclass(frozen=True)
class NameBad:
    message: str


def parse_crate_name(value: object) -> NameOk | NameBad:
    if not isinstance(value, str) or value.strip() == "":
        return NameBad("crate must be a non-empty string.")
    name = value.strip()
    if not _NAME.fullmatch(name):
        shown = name[:80]
        return NameBad(
            f'"{shown}" is not a valid crate name '
            "(ASCII letters, digits, - and _, starting with a letter, at most 64 characters)."
        )
    return NameOk(name)


def _crate_url(name: str, suffix: str = "") -> str:
    return f"https://{CRATES_HOST}/api/v1/crates/{quote(name, safe='')}{suffix}"


class _Strict(BaseModel):
    # strict: "12" is not an integer and 1 is not a boolean; extra fields are allowed and ignored.
    model_config = ConfigDict(strict=True, extra="allow")


class _Version(_Strict):
    num: StrictStr
    yanked: StrictBool
    created_at: StrictStr
    license: StrictStr | None = None
    yank_message: StrictStr | None = None


class _Crate(_Strict):
    name: StrictStr
    max_version: StrictStr | None = None
    max_stable_version: StrictStr | None = None
    default_version: StrictStr | None = None
    repository: StrictStr | None = None
    recent_downloads: StrictInt | None = Field(default=None, ge=0)


class _CrateDoc(_Strict):
    crate: _Crate
    # Parsed lazily: a crate has many versions and only the latest is read.
    versions: list[Any]


class _Owners(_Strict):
    users: list[Any]


@dataclass(frozen=True)
class CrateDoc:
    name: str
    version: str
    #: ISO publish time of the version the checks are about.
    published_at: str
    yanked: bool
    yank_message: str | None
    license: str | None
    repository: str | None
    #: Downloads in the last 90 days, or None when crates.io gave none.
    recent_downloads: int | None


def _first_issue(err: ValidationError) -> str:
    loc = err.errors()[0]["loc"] if err.errors() else ()
    return ".".join(str(p) for p in loc) or "root"


def _passthrough(fail: HttpFail, crate: str) -> HttpFail:
    if fail.failure == "not_found":
        return HttpFail("not_found", f"crates.io has no crate named {crate}.", fail.status)
    return fail


async def fetch_crate(
    client: httpx.AsyncClient, name: str, config: Config, now: datetime | None = None
) -> CrateDoc | HttpFail:
    res = await get_json(client, _crate_url(name), config, now)
    if isinstance(res, HttpFail):
        return _passthrough(res, name)
    try:
        doc = _CrateDoc.model_validate(res.json)
    except ValidationError as err:
        return HttpFail(
            "malformed_response",
            f"The crate document is missing a field this check needs ({_first_issue(err)}).",
            res.status,
        )
    crate = doc.crate
    # The newest stable release, else the newest of any kind: the one a dependent would pick up.
    target = crate.max_stable_version or crate.max_version or crate.default_version
    version: _Version | None = None
    for raw in doc.versions:
        try:
            candidate = _Version.model_validate(raw)
        except ValidationError:
            continue
        if candidate.num == target:
            version = candidate
            break
    if target is None or version is None:
        return HttpFail(
            "malformed_response",
            "The crate document does not list the version it names as the latest.",
            res.status,
        )
    license_text = (version.license or "").strip()
    repository = (crate.repository or "").strip()
    return CrateDoc(
        name=crate.name,
        version=version.num,
        published_at=version.created_at,
        yanked=version.yanked,
        yank_message=version.yank_message,
        license=license_text or None,
        repository=repository or None,
        recent_downloads=crate.recent_downloads,
    )


async def fetch_owner_count(
    client: httpx.AsyncClient, name: str, config: Config, now: datetime | None = None
) -> int | HttpFail:
    """How many owners (people and teams) can publish the crate."""
    res = await get_json(client, _crate_url(name, "/owners"), config, now)
    if isinstance(res, HttpFail):
        return res
    try:
        return len(_Owners.model_validate(res.json).users)
    except ValidationError:
        return HttpFail("malformed_response", "The owners answer has no `users` list.", res.status)


__all__ = [
    "CRATES_HOST",
    "CrateDoc",
    "Failure",
    "HttpFail",
    "fetch_crate",
    "fetch_owner_count",
    "parse_crate_name",
]
