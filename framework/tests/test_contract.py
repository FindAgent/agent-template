"""findagent.json and the server say the same thing, and the entry-tool contract holds."""

from __future__ import annotations

import json
from pathlib import Path

from framework_agent.tools import TOOLS

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "findagent.json").read_text(encoding="utf-8"))
SIX = {"plan_inputs", "open_form", "run_form", "run_full", "list_capabilities", "discover_intent"}


def test_the_six_entry_tools_exist() -> None:
    assert {t["name"] for t in TOOLS} >= SIX


def test_skills_list_every_tool_with_its_schema_and_stay_within_the_limits() -> None:
    skills = {s["id"]: s for s in MANIFEST["skills"]}
    assert set(skills) == {t["name"] for t in TOOLS}
    assert len(skills) <= 40
    for tool in TOOLS:
        skill = skills[tool["name"]]
        assert skill["name"] == tool["name"]
        assert skill["input_schema"] == tool["inputSchema"]
        assert len(skill["description"]) <= 500


def test_manifest_basics_match_the_platform_contract() -> None:
    assert MANIFEST["schema_version"] == "1.2"
    assert MANIFEST["kind"] == "code-bundle"
    assert MANIFEST["runtime"] == {"kind": "python", "version": "3.13"}
    assert 1 <= len(MANIFEST["example_prompts"]) <= 5
    assert (ROOT / MANIFEST["entrypoint"]["path"]).exists()
    assert MANIFEST["allowed_hosts"] == []


def test_every_requirement_is_pinned_exactly() -> None:
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if line.strip():
            assert "==" in line, line
