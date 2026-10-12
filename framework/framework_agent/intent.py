"""Intent discovery: the user states a goal, the agent proposes the exact input.

It extends the interactive layer. Where `needs_input` reacts to a missing argument, this is proactive:
it restates the goal in one line, asks the few questions that pin the input down, proposes a concrete
input object that matches the target tool's schema, and asks the user to confirm before running.

The scaffold is deterministic (it comes only from the FieldSpec list in tools.py) and uses no model.
"""

from __future__ import annotations

from typing import Any

from .interactive import FieldSpec, build_example, build_schema

#: A restated goal is one line; anything longer is cut, never echoed whole.
MAX_GOAL_CHARS = 300


def _restate(goal: str | None, tool: str) -> str:
    text = (goal or "").strip()
    if not text:
        return f"Plan and run `{tool}` for you."
    return f"You want to: {text[:MAX_GOAL_CHARS]}..." if len(text) > MAX_GOAL_CHARS else f"You want to: {text}"


def _propose_input(specs: list[FieldSpec], provided: dict[str, Any]) -> dict[str, Any]:
    proposed = build_example(specs)
    # Only fields the tool declares are carried over: a caller cannot make the agent echo arbitrary keys.
    for spec in specs:
        value = provided.get(spec.name)
        if value is not None:
            proposed[spec.name] = value
    return proposed


def build_intent_dialogue(
    tool: str,
    goal: str | None,
    specs: list[FieldSpec],
    provided: dict[str, Any] | None = None,
) -> dict[str, Any]:
    given = provided or {}
    unspecified = [s for s in specs if given.get(s.name) is None]
    source = unspecified or specs
    return {
        "status": "intent_discovery",
        "tool": tool,
        "restated_goal": _restate(goal, tool),
        "questions": [{"field": s.name, "question": s.question, "why": s.description} for s in source[:4]],
        "proposed_input": _propose_input(specs, given),
        "schema": build_schema(specs),
        "confirm_prompt": (
            f'Review the proposed input above. Reply "run" to proceed, or edit any field, then call `{tool}`.'
        ),
    }
