from dataclasses import replace

import pytest

from agent_template.crates import CrateDoc
from agent_template.signals import (
    LOW_RECENT_DOWNLOADS,
    MIN_CHECKED_FOR_VERDICT,
    MIN_OWNERS,
    SIGNAL_RULES,
    STALE_RISK_DAYS,
    STALE_WARN_DAYS,
    OwnersFailed,
    OwnersInput,
    OwnersMeasured,
    OwnersSkipped,
    Signal,
    build_signals,
    summarize,
    verdict_for,
)

from .conftest import NOW, days_ago

BASE = CrateDoc(
    name="acme",
    version="1.2.3",
    published_at=days_ago(10),
    yanked=False,
    yank_message=None,
    license="MIT",
    repository="https://github.com/acme/acme",
    recent_downloads=50_000,
)


def signals_for(owners: OwnersInput | None = None, **changes: object) -> list[Signal]:
    return build_signals(replace(BASE, **changes), owners or OwnersMeasured(3), NOW)  # type: ignore[arg-type]


def find(signals: list[Signal], signal_id: str) -> Signal:
    return next(s for s in signals if s.id == signal_id)


def test_release_age_is_ok_below_the_warn_line_warn_at_it_risk_at_the_risk_line() -> None:
    def at(days: int) -> str:
        return find(signals_for(published_at=days_ago(days)), "latest_release_age").status

    assert at(STALE_WARN_DAYS - 1) == "ok"
    assert at(STALE_WARN_DAYS) == "warn"
    assert at(STALE_RISK_DAYS - 1) == "warn"
    assert at(STALE_RISK_DAYS) == "risk"


def test_release_age_is_in_days_and_never_negative() -> None:
    assert find(signals_for(published_at=days_ago(10)), "latest_release_age").value == 10
    assert find(signals_for(published_at=days_ago(-5)), "latest_release_age").value == 0


def test_release_age_is_not_checked_with_the_reason_when_the_time_cannot_be_read() -> None:
    signal = find(signals_for(published_at="not a date"), "latest_release_age")
    assert (signal.status, signal.value) == ("not_checked", None)
    assert signal.reason is not None
    assert "publish time" in signal.reason


def test_a_yanked_latest_version_is_a_risk_and_quotes_the_message() -> None:
    signal = find(signals_for(yanked=True, yank_message="broken build"), "yanked")
    assert signal.status == "risk"
    assert "broken build" in signal.detail
    assert find(signals_for(), "yanked").status == "ok"


def test_a_missing_license_or_repository_is_a_warn() -> None:
    assert find(signals_for(license=None), "license").status == "warn"
    assert find(signals_for(), "license").status == "ok"
    assert find(signals_for(repository=None), "repository").status == "warn"
    assert find(signals_for(), "repository").status == "ok"


def test_recent_downloads_low_warns_zero_is_a_measured_zero_unknown_is_not_checked() -> None:
    def at(n: int | None) -> Signal:
        return find(signals_for(recent_downloads=n), "recent_downloads")

    assert at(LOW_RECENT_DOWNLOADS - 1).status == "warn"
    assert at(LOW_RECENT_DOWNLOADS).status == "ok"
    assert (at(0).status, at(0).value) == ("warn", 0)
    assert (at(None).status, at(None).value) == ("not_checked", None)


def test_owners_one_warns_two_do_not_skipped_and_failed_are_not_checked() -> None:
    def at(owners: OwnersInput) -> Signal:
        return find(signals_for(owners), "owners")

    assert at(OwnersMeasured(1)).status == "warn"
    assert at(OwnersMeasured(MIN_OWNERS)).status == "ok"
    assert (at(OwnersMeasured(0)).status, at(OwnersMeasured(0)).value) == ("warn", 0)
    skipped = at(OwnersSkipped())
    assert (skipped.status, skipped.value) == ("not_checked", None)
    assert skipped.reason is not None
    assert "switched off" in skipped.reason
    failed = at(OwnersFailed("rate_limited: slow down"))
    assert (failed.status, failed.value, failed.reason) == ("not_checked", None, "rate_limited: slow down")


def test_the_same_signals_come_in_the_same_order_as_the_documented_rules() -> None:
    ids = [s.id for s in signals_for()]
    assert ids == [r["id"] for r in SIGNAL_RULES]
    assert ids == ["latest_release_age", "yanked", "license", "repository", "recent_downloads", "owners"]


def test_every_signal_names_the_api_field_it_came_from() -> None:
    for signal in signals_for():
        assert len(signal.source) > 3
    for rule in SIGNAL_RULES:
        assert len(rule["field"]) > 3


def test_a_signal_serialises_without_an_empty_reason() -> None:
    assert "reason" not in find(signals_for(), "owners").to_dict()
    assert "reason" in find(signals_for(OwnersSkipped()), "owners").to_dict()


def test_verdict_any_risk_is_risky_any_warn_is_watch_else_healthy() -> None:
    assert verdict_for(signals_for(yanked=True))[0] == "risky"
    assert verdict_for(signals_for(license=None))[0] == "watch"
    assert verdict_for(signals_for())[0] == "healthy"


def test_risk_outranks_warn() -> None:
    assert verdict_for(signals_for(yanked=True, license=None))[0] == "risky"


def test_verdict_is_unknown_not_healthy_when_too_few_signals_could_be_measured() -> None:
    sparse = [replace(s, status="not_checked") if i < 4 else s for i, s in enumerate(signals_for())]
    assert len([s for s in sparse if s.status != "not_checked"]) < MIN_CHECKED_FOR_VERDICT
    verdict, reason = verdict_for(sparse)
    assert verdict == "unknown"
    assert "at least 3" in reason


def test_a_not_checked_signal_never_raises_or_lowers_the_verdict() -> None:
    assert verdict_for(signals_for(OwnersSkipped()))[0] == "healthy"


def test_summary_says_what_is_wrong_and_what_was_not_checked() -> None:
    signals = signals_for(OwnersSkipped(), yanked=True, yank_message="gone")
    text = summarize("acme", "1.2.3", signals, verdict_for(signals)[0])
    assert "acme@1.2.3 (verdict: risky)" in text
    assert "gone" in text
    assert "Not checked: owners." in text


def test_summary_keeps_sentences_apart_when_an_upstream_message_has_no_final_punctuation() -> None:
    signals = signals_for(yanked=True, yank_message="use other", license=None)
    assert "use other. The latest version declares no license." in summarize("acme", "1.2.3", signals, "risky")


def test_summary_says_plainly_when_nothing_raised_a_concern() -> None:
    assert (
        summarize("acme", "1.2.3", signals_for(), "healthy")
        == "acme@1.2.3: no signal raised a concern (verdict: healthy)."
    )


@pytest.mark.parametrize("count,word", [(1, "owner"), (2, "owners")])
def test_owner_wording_follows_the_count(count: int, word: str) -> None:
    assert f"{count} {word} can publish" in find(signals_for(OwnersMeasured(count)), "owners").detail
