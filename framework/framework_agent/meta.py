"""Name and version, read once from pyproject.toml so each has one source."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

_project: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

AGENT_NAME: str = _project["name"]
AGENT_VERSION: str = _project["version"]
