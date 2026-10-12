"""The domain: sort commit subjects into release-note groups.

These are the two tools the agent loop calls, written as plain functions so they can be tested alone
and wrapped by any framework. Replace them, and the planner below, with your own agent's logic.
"""

from __future__ import annotations

import re
from typing import Any

from .agent_loop import Agent, Final, FunctionTool, ToolCall, Turn, function_tool

MAX_COMMITS = 500
MAX_SUBJECT_CHARS = 300

#: Conventional-commit types and the release-note group each belongs to. Anything else is "other".
GROUP_OF_TYPE: dict[str, str] = {
    "feat": "features",
    "fix": "fixes",
    "perf": "fixes",
    "docs": "maintenance",
    "chore": "maintenance",
    "refactor": "maintenance",
    "test": "maintenance",
    "ci": "maintenance",
    "build": "maintenance",
    "style": "maintenance",
}
GROUPS = ("features", "fixes", "maintenance", "other")
GROUP_TITLES = {"features": "Features", "fixes": "Fixes", "maintenance": "Maintenance", "other": "Other changes"}

_TYPE = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]*\))?!?:\s*(?P<text>.+)$", re.IGNORECASE)


@function_tool
def classify_commits(subjects: list[str]) -> dict[str, list[str]]:
    """Group commit subjects by their conventional-commit type (feat, fix, and so on)."""
    groups: dict[str, list[str]] = {name: [] for name in GROUPS}
    for subject in subjects:
        match = _TYPE.match(subject.strip())
        group = GROUP_OF_TYPE.get(match.group("type").lower(), "other") if match else "other"
        groups[group].append(match.group("text").strip() if match and group != "other" else subject.strip())
    return groups


@function_tool
def render_notes(groups: dict[str, list[str]]) -> str:
    """Write the groups as Markdown release notes; a group with no entries is left out."""
    sections = [
        f"## {GROUP_TITLES[name]}\n\n" + "\n".join(f"- {line}" for line in groups[name])
        for name in GROUPS
        if groups.get(name)
    ]
    return "\n\n".join(sections)


class TriagePlanner:
    """Classify first, render second, then answer. A model-driven planner would decide this order itself."""

    def next_step(self, goal: Any, history: list[Turn]) -> ToolCall | Final:
        if not history:
            return ToolCall("classify_commits", {"subjects": goal})
        if len(history) == 1:
            return ToolCall("render_notes", {"groups": history[0].result})
        groups: dict[str, list[str]] = history[0].result
        return Final(
            {
                "counts": {name: len(groups[name]) for name in GROUPS},
                "groups": groups,
                "notes": history[1].result,
            }
        )


TRIAGE_TOOLS: tuple[FunctionTool, ...] = (classify_commits, render_notes)

TRIAGE_AGENT = Agent(
    name="commit-triage",
    instructions="Sort commit subjects into release-note groups and write the notes. Never invent a commit.",
    tools=TRIAGE_TOOLS,
    planner=TriagePlanner(),
)
