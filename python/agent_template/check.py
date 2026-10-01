"""The check: validate the name, read the crate, optionally read its owners, build the signals.

Two requests at most, and the report says how many it used. The deterministic result is complete on
its own; no model is involved anywhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from .clock import iso_utc
from .config import Config
from .crates import CrateDoc, NameBad, fetch_crate, fetch_owner_count, parse_crate_name
from .http import HttpFail
from .signals import (
    OwnersFailed,
    OwnersInput,
    OwnersMeasured,
    OwnersSkipped,
    build_signals,
    summarize,
    verdict_for,
)

#: The most upstream requests one check may spend.
REQUEST_BUDGET = 2

METHOD = (
    "Deterministic rules over the public crates.io API. GET only, no credentials, no model. "
    "The thresholds are listed by list_capabilities."
)

Sleep = Callable[[float], Awaitable[None]]


def failure(
    crate: str,
    failure_class: str,
    message: str,
    used: int,
    *,
    status: int | None = None,
    resets_at: str | None = None,
) -> dict[str, Any]:
    """A failed check, as the JSON the tool returns. Each class is a different condition."""
    result: dict[str, Any] = {
        "kind": "crate_failure",
        "ok": False,
        "crate": crate,
        "failure": failure_class,
        "message": message,
    }
    if status is not None:
        result["status"] = status
    if resets_at is not None:
        result["resetsAt"] = resets_at
    result["requests"] = {"used": used, "budget": REQUEST_BUDGET}
    return result


async def check_crate(
    value: object,
    *,
    client: httpx.AsyncClient,
    config: Config,
    owners: bool = True,
    now: Callable[[], datetime] | None = None,
    sleep: Sleep | None = None,
) -> dict[str, Any]:
    parsed = parse_crate_name(value)
    if isinstance(parsed, NameBad):
        shown = value.strip()[:80] if isinstance(value, str) else ""
        return failure(shown, "invalid_input", parsed.message, 0)
    name = parsed.name
    clock = now or (lambda: datetime.now(UTC))
    moment = clock()

    used = 1
    doc = await fetch_crate(client, name, config, moment)
    if isinstance(doc, HttpFail):
        return failure(name, doc.failure, doc.message, used, status=doc.status, resets_at=doc.resets_at)

    owners_input: OwnersInput = OwnersSkipped()
    if owners:
        used += 1
        # The upstream asks for at most one request a second: wait before the second one.
        if config.spacing_ms > 0:
            await (sleep or asyncio.sleep)(config.spacing_ms / 1000)
        count = await fetch_owner_count(client, name, config, moment)
        # The owners read is one signal. Its failure is reported as that signal being not checked,
        # with the failure class kept in the reason; it does not fail the whole check.
        owners_input = (
            OwnersFailed(f"{count.failure}: {count.message}") if isinstance(count, HttpFail) else OwnersMeasured(count)
        )

    return _report(doc, owners_input, moment, used)


def _report(doc: CrateDoc, owners: OwnersInput, moment: datetime, used: int) -> dict[str, Any]:
    signals = build_signals(doc, owners, moment)
    verdict, reason = verdict_for(signals)
    return {
        "kind": "crate_check",
        "ok": True,
        "crate": doc.name,
        "version": doc.version,
        "checkedAt": iso_utc(moment),
        "verdict": verdict,
        "verdictReason": reason,
        "summary": summarize(doc.name, doc.version, signals, verdict),
        "signals": [s.to_dict() for s in signals],
        "notChecked": [
            {"id": s.id, "reason": s.reason or "not measured"} for s in signals if s.status == "not_checked"
        ],
        "requests": {"used": used, "budget": REQUEST_BUDGET},
        "method": METHOD,
    }
