"""The agent loop, the triage tools and the dispatcher, driven without a server."""

from __future__ import annotations

import json
from typing import Any

import pytest

from framework_agent.agent_loop import MAX_TURNS, Agent, Final, LoopError, Runner, ToolCall, function_tool
from framework_agent.tools import TOOLS, dispatch_tool
from framework_agent.triage import classify_commits, render_notes

SUBJECTS = [
    "feat: add CSV export",
    "fix(api): handle an empty body",
    "docs: update the readme",
    "Merge branch 'main'",
    "feat(ui)!: new layout",
]


def test_classify_groups_by_conventional_type_and_keeps_unknown_subjects_whole() -> None:
    groups = classify_commits.fn(SUBJECTS)
    assert groups["features"] == ["add CSV export", "new layout"]
    assert groups["fixes"] == ["handle an empty body"]
    assert groups["maintenance"] == ["update the readme"]
    assert groups["other"] == ["Merge branch 'main'"]


def test_render_leaves_out_an_empty_group() -> None:
    notes = render_notes.fn({"features": ["a"], "fixes": [], "maintenance": [], "other": []})
    assert notes == "## Features\n\n- a"


def test_run_full_runs_the_loop_and_reports_the_trace() -> None:
    result = dispatch_tool("run_full", {"commits": SUBJECTS})
    assert result["ok"] is True
    assert result["counts"] == {"features": 2, "fixes": 1, "maintenance": 1, "other": 1}
    assert [t["tool"] for t in result["trace"]] == ["classify_commits", "render_notes"]
    assert "## Fixes" in result["notes"]


def test_a_newline_separated_string_and_a_json_string_are_accepted() -> None:
    by_lines = dispatch_tool("triage_commits", {"commits": "feat: a\nfix: b"})
    by_json = dispatch_tool("triage_commits", {"commits": json.dumps(["feat: a", "fix: b"])})
    assert by_lines["counts"] == by_json["counts"] == {"features": 1, "fixes": 1, "maintenance": 0, "other": 0}


@pytest.mark.parametrize("tool", ["run_full", "run_form", "triage_commits", "open_form"])
def test_missing_commits_is_needs_input_not_an_error(tool: str) -> None:
    result = dispatch_tool(tool, {})
    assert result["status"] == "needs_input"
    assert result["next_question"]["field"] == "commits"


@pytest.mark.parametrize(
    "bad",
    [42, {"a": 1}, [1, 2], ["x" * 301], ["feat: a"] * 501],
)
def test_bad_input_is_a_classified_failure(bad: Any) -> None:
    result = dispatch_tool("run_full", {"commits": bad})
    assert result["ok"] is False
    assert result["failure"] == "invalid_input"


def test_an_unknown_tool_raises_so_the_server_can_answer_isError() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        dispatch_tool("nope", {})


def test_the_loop_stops_on_an_unknown_tool_and_on_too_many_turns() -> None:
    class Forever:
        def next_step(self, goal: Any, history: list[Any]) -> ToolCall | Final:
            return ToolCall("echo", {"x": 1})

    class Unknown:
        def next_step(self, goal: Any, history: list[Any]) -> ToolCall | Final:
            return ToolCall("missing", {})

    @function_tool
    def echo(x: int) -> int:
        """Return the input."""
        return x

    with pytest.raises(LoopError, match=f"{MAX_TURNS} turns"):
        Runner.run_sync(Agent("a", "i", (echo,), Forever()), None)
    with pytest.raises(LoopError, match="unknown tool"):
        Runner.run_sync(Agent("a", "i", (echo,), Unknown()), None)


def test_a_tool_that_raises_is_a_loop_error_with_the_tool_name() -> None:
    @function_tool
    def boom() -> None:
        """Always fails."""
        raise RuntimeError("no")

    class Once:
        def next_step(self, goal: Any, history: list[Any]) -> ToolCall | Final:
            return ToolCall("boom", {})

    with pytest.raises(LoopError, match="tool boom failed"):
        Runner.run_sync(Agent("a", "i", (boom,), Once()), None)


def test_every_tool_is_read_only_and_closed_world() -> None:
    for tool in TOOLS:
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["annotations"]["openWorldHint"] is False
