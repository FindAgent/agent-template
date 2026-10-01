"""Time as text: one format for every timestamp this agent returns."""

from __future__ import annotations

from datetime import UTC, datetime


def iso_utc(moment: datetime) -> str:
    """ISO-8601 in UTC with millisecond precision and a Z, the same text on every platform."""
    utc = moment.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"
