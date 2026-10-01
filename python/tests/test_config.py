import logging

import pytest

from agent_template.config import DEFAULTS, Config, load_config


def test_defaults_when_nothing_is_set() -> None:
    assert load_config({}) == DEFAULTS
    assert load_config({"AGENT_TIMEOUT_MS": "", "AGENT_MAX_BYTES": ""}) == DEFAULTS


def test_reads_all_knobs() -> None:
    env = {"AGENT_TIMEOUT_MS": "2500", "AGENT_MAX_BYTES": "50000", "AGENT_SPACING_MS": "0"}
    assert load_config(env) == Config(timeout_ms=2500, max_bytes=50000, spacing_ms=0)


@pytest.mark.parametrize(
    "env",
    [
        {"AGENT_TIMEOUT_MS": "banana"},
        {"AGENT_TIMEOUT_MS": "0"},
        {"AGENT_TIMEOUT_MS": "-5"},
        {"AGENT_TIMEOUT_MS": "1.5"},
        {"AGENT_TIMEOUT_MS": "999999"},
        {"AGENT_TIMEOUT_MS": "1_000"},
        {"AGENT_MAX_BYTES": "10"},
        {"AGENT_MAX_BYTES": "99999999999"},
        {"AGENT_SPACING_MS": "-1"},
        {"AGENT_SPACING_MS": "999999"},
    ],
)
def test_a_value_outside_its_bounds_is_ignored_with_a_warning(
    env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert load_config(env) == DEFAULTS
    assert len(caplog.records) == 1


def test_one_bad_knob_does_not_discard_the_good_one() -> None:
    config = load_config({"AGENT_TIMEOUT_MS": "x", "AGENT_MAX_BYTES": "20000"})
    assert config == Config(timeout_ms=DEFAULTS.timeout_ms, max_bytes=20000, spacing_ms=DEFAULTS.spacing_ms)
