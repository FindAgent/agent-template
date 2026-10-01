"""Pure, deterministic signals: no I/O, no clock of its own, no model.

Every status comes from a rule written down here, and every threshold is a number a fork is expected
to replace for its own domain. A signal that could not be measured is "not_checked" with a reason; it
is never scored as zero and never left out.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from .crates import CrateDoc

Status = Literal["ok", "warn", "risk", "not_checked"]
Verdict = Literal["healthy", "watch", "risky", "unknown"]

STALE_WARN_DAYS = 365
STALE_RISK_DAYS = 730
#: Fewer owners than this: warn (a crate with one owner has no second pair of hands).
MIN_OWNERS = 2
#: Fewer downloads than this in the last 90 days: warn.
LOW_RECENT_DOWNLOADS = 1000
#: The fewest signals that must be measured before a verdict is given at all.
MIN_CHECKED_FOR_VERDICT = 3

_DAY_SECONDS = 86_400

OWNERS_SOURCE = "owners (crates.io /owners)"
DOWNLOADS_SOURCE = "crate.recent_downloads"
AGE_SOURCE = "versions[latest].created_at"


@dataclass(frozen=True)
class Signal:
    id: str
    label: str
    status: Status
    #: The measured value, or None when the signal was not checked.
    value: str | int | bool | None
    #: One sentence: what was measured and what the status rule said about it.
    detail: str
    #: The API field the value came from, so a finding can be walked back to its source.
    source: str
    #: Why the signal was not checked. Present only when status is "not_checked".
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if not (k == "reason" and v is None)}


@dataclass(frozen=True)
class OwnersSkipped:
    pass


@dataclass(frozen=True)
class OwnersMeasured:
    value: int


@dataclass(frozen=True)
class OwnersFailed:
    reason: str


OwnersInput = OwnersSkipped | OwnersMeasured | OwnersFailed

#: What each signal checks, in the words list_capabilities shows, in the order build_signals emits them.
SIGNAL_RULES: list[dict[str, str]] = [
    {
        "id": "latest_release_age",
        "rule": (
            f"warn at {STALE_WARN_DAYS} days, risk at {STALE_RISK_DAYS} days since the latest version was published"
        ),
        "field": AGE_SOURCE,
    },
    {"id": "yanked", "rule": "risk when the latest version has been yanked", "field": "versions[latest].yanked"},
    {
        "id": "license",
        "rule": "warn when the latest version declares no license",
        "field": "versions[latest].license",
    },
    {"id": "repository", "rule": "warn when the crate links no source repository", "field": "crate.repository"},
    {
        "id": "recent_downloads",
        "rule": f"warn below {LOW_RECENT_DOWNLOADS} downloads in the last 90 days",
        "field": DOWNLOADS_SOURCE,
    },
    {"id": "owners", "rule": f"warn below {MIN_OWNERS} owners", "field": OWNERS_SOURCE},
]


def _not_checked(signal_id: str, label: str, source: str, reason: str) -> Signal:
    return Signal(signal_id, label, "not_checked", None, f"Not checked: {reason}.", source, reason)


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _parse_time(text: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def build_signals(crate: CrateDoc, owners: OwnersInput, now: datetime) -> list[Signal]:
    signals: list[Signal] = []

    # Latest release age
    published = _parse_time(crate.published_at)
    if published is None:
        signals.append(
            _not_checked(
                "latest_release_age",
                "Latest release age",
                AGE_SOURCE,
                "the publish time of the latest version could not be read as a date",
            )
        )
    else:
        days = max(0, int((now - published).total_seconds() // _DAY_SECONDS))
        status: Status = "risk" if days >= STALE_RISK_DAYS else "warn" if days >= STALE_WARN_DAYS else "ok"
        signals.append(
            Signal(
                "latest_release_age",
                "Latest release age",
                status,
                days,
                f"Version {crate.version} was published {days} days ago "
                f"(warn at {STALE_WARN_DAYS}, risk at {STALE_RISK_DAYS}).",
                AGE_SOURCE,
            )
        )

    # Yanked
    if crate.yanked:
        yank_detail = f"Version {crate.version} has been yanked" + (
            f": {crate.yank_message}" if crate.yank_message else ""
        )
    else:
        yank_detail = f"Version {crate.version} has not been yanked."
    signals.append(
        Signal(
            "yanked", "Yanked", "risk" if crate.yanked else "ok", crate.yanked, yank_detail, "versions[latest].yanked"
        )
    )

    # License
    signals.append(
        Signal(
            "license",
            "License",
            "warn" if crate.license is None else "ok",
            crate.license,
            "The latest version declares no license."
            if crate.license is None
            else f"The latest version declares the license {crate.license}.",
            "versions[latest].license",
        )
    )

    # Source repository
    signals.append(
        Signal(
            "repository",
            "Source repository",
            "warn" if crate.repository is None else "ok",
            crate.repository,
            "The crate links no source repository, so its code cannot be audited from here."
            if crate.repository is None
            else f"The crate links its source at {crate.repository}.",
            "crate.repository",
        )
    )

    # Recent downloads
    if crate.recent_downloads is None:
        signals.append(
            _not_checked(
                "recent_downloads",
                "Recent downloads",
                DOWNLOADS_SOURCE,
                "crates.io reports no recent download count for this crate",
            )
        )
    else:
        signals.append(
            Signal(
                "recent_downloads",
                "Recent downloads",
                "warn" if crate.recent_downloads < LOW_RECENT_DOWNLOADS else "ok",
                crate.recent_downloads,
                f"{crate.recent_downloads} downloads in the last 90 days (warn below {LOW_RECENT_DOWNLOADS}).",
                DOWNLOADS_SOURCE,
            )
        )

    # Owners
    match owners:
        case OwnersMeasured(value=count):
            signals.append(
                Signal(
                    "owners",
                    "Owners",
                    "warn" if count < MIN_OWNERS else "ok",
                    count,
                    f"{count} {_plural(count, 'owner', 'owners')} can publish (warn below {MIN_OWNERS}).",
                    OWNERS_SOURCE,
                )
            )
        case OwnersSkipped():
            signals.append(_not_checked("owners", "Owners", OWNERS_SOURCE, "owners were switched off for this run"))
        case OwnersFailed(reason=why):
            signals.append(_not_checked("owners", "Owners", OWNERS_SOURCE, why))

    return signals


def verdict_for(signals: list[Signal]) -> tuple[Verdict, str]:
    checked = [s for s in signals if s.status != "not_checked"]
    if len(checked) < MIN_CHECKED_FOR_VERDICT:
        return (
            "unknown",
            f"Only {len(checked)} of {len(signals)} signals could be measured; "
            f"at least {MIN_CHECKED_FOR_VERDICT} are needed for a verdict.",
        )
    risks = [s for s in checked if s.status == "risk"]
    if risks:
        return "risky", f"Risk: {', '.join(s.label.lower() for s in risks)}."
    warns = [s for s in checked if s.status == "warn"]
    if warns:
        return "watch", f"Worth a look: {', '.join(s.label.lower() for s in warns)}."
    return "healthy", f"All {len(checked)} measured signals are within their thresholds."


def _sentence(text: str) -> str:
    """A detail that quotes upstream text may end without punctuation; a sentence always does."""
    return text if text[-1:] in ".!?" else f"{text}."


def summarize(crate: str, version: str, signals: list[Signal], verdict: Verdict) -> str:
    """One deterministic paragraph: what is wrong, or that nothing is."""
    concerns = [s for s in signals if s.status in ("risk", "warn")]
    unmeasured = [s for s in signals if s.status == "not_checked"]
    if concerns:
        head = f"{crate}@{version} (verdict: {verdict}): " + " ".join(_sentence(s.detail) for s in concerns)
    else:
        head = f"{crate}@{version}: no signal raised a concern (verdict: {verdict})."
    if not unmeasured:
        return head
    return f"{head} Not checked: {', '.join(s.label.lower() for s in unmeasured)}."
