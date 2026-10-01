"""Name, version and contact, read once from pyproject.toml so each has one source."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

_project: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

AGENT_NAME: str = _project["name"]
AGENT_VERSION: str = _project["version"]

_repository: str = _project.get("urls", {}).get("Repository", "").removesuffix(".git")

# crates.io refuses a request without a User-Agent and asks that it say who is calling and where to
# reach them, so the repository from pyproject.toml goes in: a fork that changes `Repository` there
# changes this header with it.
USER_AGENT: str = f"{AGENT_NAME}/{AGENT_VERSION} ({_repository})" if _repository else f"{AGENT_NAME}/{AGENT_VERSION}"
