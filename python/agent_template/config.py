"""Runtime knobs. None is a secret and none is required.

The defaults are what the hosted sandbox runs. The knobs exist so a limit can be exercised against
the real upstream (see scripts/live_check.py) and so a local run can be tuned. A value outside its
bounds is ignored with a warning on stderr (stdout belongs to the MCP protocol).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    #: Per-request wall clock, in milliseconds.
    timeout_ms: int = 10_000
    #: The most response bytes read from one upstream request.
    max_bytes: int = 5 * 1024 * 1024
    #: Pause between two requests of one check. crates.io asks crawlers for at most one a second.
    spacing_ms: int = 1000


DEFAULTS = Config()

_INTEGER = re.compile(r"-?[0-9]+")

# env name -> (field, minimum, maximum)
_BOUNDS: dict[str, tuple[str, int, int]] = {
    "AGENT_TIMEOUT_MS": ("timeout_ms", 1, 60_000),
    "AGENT_MAX_BYTES": ("max_bytes", 1_000, 50 * 1024 * 1024),
    "AGENT_SPACING_MS": ("spacing_ms", 0, 10_000),
}


def load_config(env: Mapping[str, str] | None = None) -> Config:
    source = os.environ if env is None else env
    config = DEFAULTS
    for name, (field, low, high) in _BOUNDS.items():
        raw = source.get(name, "")
        if raw == "":
            continue
        value = int(raw) if _INTEGER.fullmatch(raw) else None
        if value is None or not low <= value <= high:
            log.warning(
                "%s=%r is not an integer between %d and %d; using the default %d.",
                name,
                raw,
                low,
                high,
                getattr(DEFAULTS, field),
            )
            continue
        config = replace(config, **{field: value})
    return config
