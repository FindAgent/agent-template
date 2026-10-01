"""Interactive input layer for FindAgent code-bundle MCP tools.

When a user calls a tool without knowing the exact input shape, the tool must NOT raise. It returns a
structured `needs_input` payload instead: a brief, the missing fields, clarifying questions, a JSON
schema and a ready-to-edit example, so the host can ask the user, collect answers and retry. It works
on any MCP client, and the platform draws its form panel from this shape for `open_form`,
`plan_inputs` and `run_form`.

Where the client advertises the `elicitation` capability, the server upgrades it into a native form
(see mcp_server.py). This module is pure: no SDK, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FieldType = Literal["string", "number", "integer", "boolean", "array", "object"]

_HINT = (
    "Fill the example and call this tool again. Array/object args may be passed as JSON "
    "or as a JSON string — both are accepted."
)


@dataclass(frozen=True)
class FieldSpec:
    #: argument name as the tool reads it from its arguments
    name: str
    type: FieldType
    #: description of the field
    description: str
    #: a realistic example value for this field
    example: Any
    #: question to ask the user when the field is missing
    question: str
    required: bool = False
    #: for arrays/objects: a human description of the item/shape
    shape: str | None = None
    #: a closed set of allowed answers; a form renders them as a choice instead of a text box
    options: tuple[str, ...] | None = None


def is_missing(value: object, field_type: FieldType) -> bool:
    """Has this value gone missing, or become the wrong shape for `field_type`?"""
    if value is None:
        return True
    match field_type:
        case "array":
            return not isinstance(value, list) or len(value) == 0
        case "object":
            return not isinstance(value, dict) or len(value) == 0
        case "string":
            return not isinstance(value, str) or value == ""
        case "number" | "integer":
            return isinstance(value, bool) or not isinstance(value, int | float)
        case "boolean":
            return not isinstance(value, bool)


def _schema_for(spec: FieldSpec) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": spec.type, "description": spec.description}
    if spec.shape:
        schema["x-shape"] = spec.shape
    if spec.options:
        schema["enum"] = list(spec.options)
    return schema


def build_schema(specs: list[FieldSpec]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {s.name: _schema_for(s) for s in specs},
        "required": [s.name for s in specs if s.required],
    }


def build_example(specs: list[FieldSpec]) -> dict[str, Any]:
    return {s.name: s.example for s in specs}


def needs_input(
    tool: str,
    brief: str,
    specs: list[FieldSpec],
    present: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a needs_input payload. `present` is what was already supplied, so the questions
    focus on what is missing (plus the optional fields, for refinement)."""
    given = present or {}
    missing = [s.name for s in specs if s.required and is_missing(given.get(s.name), s.type)]
    questions: list[dict[str, Any]] = []
    for spec in specs:
        if spec.name not in missing and spec.required:
            continue
        question: dict[str, Any] = {
            "field": spec.name,
            "question": spec.question,
            "type": spec.type,
            "required": spec.required,
            "example": spec.example,
            "why": spec.description,
        }
        if spec.shape:
            question["shape"] = spec.shape
        if spec.options:
            question["options"] = list(spec.options)
        questions.append(question)
    lead = next((s for s in specs if s.name in missing), None) or next((s for s in specs if s.required), None)
    payload: dict[str, Any] = {
        "status": "needs_input",
        "tool": tool,
        "brief": brief,
        "missing": missing,
        "questions": questions,
        "schema": build_schema(specs),
        "example": build_example(specs),
    }
    if lead is not None:
        payload["next_question"] = {"field": lead.name, "question": lead.question, "why": lead.description}
    payload["hint"] = _HINT
    return payload


def check_required(tool: str, brief: str, specs: list[FieldSpec], args: dict[str, Any]) -> dict[str, Any] | None:
    """Guard for a dispatcher: a needs_input payload if a required field is missing, else None."""
    if any(s.required and is_missing(args.get(s.name), s.type) for s in specs):
        return needs_input(tool, brief, specs, args)
    return None
