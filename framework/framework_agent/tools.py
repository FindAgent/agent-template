"""MCP tool definitions and the dispatcher.

Entry-tool contract (the platform draws its form panel from these, so all six must exist and work):
plan_inputs, open_form, run_form, run_full, list_capabilities, discover_intent. This agent's one
capability tool is triage_commits; replace it with your own.

Missing or malformed arguments never raise: a tool that lacks its required input answers with a
structured `needs_input` payload so the host can ask the user and retry. A failure is a classified
`ok: false` result with the reason, never an empty answer.
"""

from __future__ import annotations

import json
from typing import Any

from .agent_loop import MAX_TURNS, LoopError, Runner
from .intent import build_intent_dialogue
from .interactive import FieldSpec, needs_input
from .meta import AGENT_NAME
from .triage import GROUP_OF_TYPE, MAX_COMMITS, MAX_SUBJECT_CHARS, TRIAGE_AGENT

COMMITS_DESCRIPTION = (
    "Commit subjects, one string each, for example 'feat: add export' or 'fix(api): handle empty body'. "
    f"At most {MAX_COMMITS} subjects of {MAX_SUBJECT_CHARS} characters. A newline separated string is accepted."
)
_COMMITS_PROP: dict[str, Any] = {"type": "array", "items": {"type": "string"}, "description": COMMITS_DESCRIPTION}
_RUN_PROPS: dict[str, Any] = {"commits": _COMMITS_PROP}


def _tool(name: str, title: str, description: str, input_schema: dict[str, Any]) -> dict[str, Any]:
    # Nothing here writes or reaches a network, so every tool says so.
    return {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "annotations": {"title": title, "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    }


TOOLS: list[dict[str, Any]] = [
    _tool(
        "open_form",
        "Open the input form",
        "Use this the moment the user wants release notes made from commit subjects. It returns the "
        "questions to ask (the commit subjects) so a form can be shown. Do NOT run before calling this.",
        {"type": "object", "properties": {}},
    ),
    _tool(
        "run_form",
        "Submit the form",
        "Internal: invoked when the user submits the form opened by open_form. Not for direct use.",
        {"type": "object", "properties": _RUN_PROPS},
    ),
    _tool(
        "run_full",
        "Make release notes",
        "Run the whole agent end to end: group the commit subjects by their conventional-commit type, "
        "then write Markdown release notes and the counts per group. Use when the user gives commit "
        "subjects and wants the notes. Missing the subjects, it asks for them instead of failing.",
        {"type": "object", "properties": _RUN_PROPS},
    ),
    _tool(
        "triage_commits",
        "Triage commits",
        "Group commit subjects into features, fixes, maintenance and other, and write the release notes. "
        "Same result as run_full; use it when the subjects are already known and no form is needed. "
        "Reports bad input as invalid_input, never as an empty result.",
        {"type": "object", "properties": _RUN_PROPS, "required": ["commits"]},
    ),
    _tool(
        "list_capabilities",
        "List capabilities",
        "List what this agent does, the rule it applies and its limits. Use for discovery before running.",
        {"type": "object", "properties": {}},
    ),
    _tool(
        "plan_inputs",
        "Plan the inputs",
        "Plan the inputs for a tool before running it: returns the questions, the schema and a "
        "ready-to-edit example. Use when the user is unsure what to provide.",
        {
            "type": "object",
            "properties": {
                "tool": {
                    "type": "string",
                    "description": "Which tool to plan inputs for (run_full or triage_commits).",
                },
                "goal": {"type": "string", "description": "Optional freeform goal."},
                "provided": {"type": "object", "description": "Optional partial arguments already known."},
            },
        },
    ),
    _tool(
        "discover_intent",
        "Discover the intent",
        "Use when the user states a goal in their own words ('write the release notes for this tag'). It "
        "restates the goal, asks the few questions that pin the input down and proposes a ready-to-run "
        "input to confirm before running.",
        {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "What the user wants, in their own words."},
                "tool": {"type": "string", "description": "Which tool to plan for. Defaults to run_full."},
                "provided": {"type": "object", "description": "Optional partial args already known."},
            },
            "required": ["goal"],
        },
    ),
]

COMMITS_SPEC = FieldSpec(
    name="commits",
    type="array",
    required=True,
    description=COMMITS_DESCRIPTION,
    example=["feat: add CSV export", "fix(api): handle an empty body", "docs: update the readme"],
    question="Which commit subjects should I write release notes for? (one per line)",
    shape="array of commit subject strings",
)
GOAL_SPEC = FieldSpec(
    name="goal",
    type="string",
    required=True,
    description="What the user wants, in their own words.",
    example="Write the release notes for version 2.0.",
    question="What do you want to produce?",
)
RUN_SPEC = [COMMITS_SPEC]
PLAN_SPECS: dict[str, tuple[list[FieldSpec], str]] = {
    "run_full": (RUN_SPEC, "Write release notes from commit subjects."),
    "triage_commits": (RUN_SPEC, "Group commit subjects and write release notes."),
}


def failure(code: str, message: str) -> dict[str, Any]:
    return {"kind": "triage_failure", "ok": False, "failure": code, "message": message}


def _coerce_json(value: object) -> object:
    """MCP clients often serialize array/object arguments as JSON strings."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text.startswith(("[", "{")):
        return value
    try:
        return json.loads(text)
    except ValueError:
        return value


def _as_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _as_object(value: object) -> dict[str, Any]:
    coerced = _coerce_json(value)
    return coerced if isinstance(coerced, dict) else {}


def _subjects(value: object) -> list[str] | dict[str, Any]:
    """The cleaned subjects, or a failure result when the value is the wrong shape or over a limit."""
    coerced = _coerce_json(value)
    items = coerced.splitlines() if isinstance(coerced, str) else coerced
    if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
        return failure("invalid_input", "commits must be a list of strings.")
    subjects = [s.strip() for s in items if s.strip()]
    if len(subjects) > MAX_COMMITS:
        return failure("invalid_input", f"at most {MAX_COMMITS} commit subjects (got {len(subjects)}).")
    if any(len(s) > MAX_SUBJECT_CHARS for s in subjects):
        return failure("invalid_input", f"a commit subject is longer than {MAX_SUBJECT_CHARS} characters.")
    return subjects


def _run(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    raw = args.get("commits")
    subjects = _subjects(raw) if raw is not None else []
    if isinstance(subjects, dict):
        return subjects
    if not subjects:
        return needs_input(tool, PLAN_SPECS["run_full"][1], RUN_SPEC, {})
    try:
        outcome = Runner.run_sync(TRIAGE_AGENT, subjects)
    except LoopError as err:
        return failure("agent_error", str(err))
    trace = [{"turn": t.number, "tool": t.tool} for t in outcome.turns]
    return {"kind": "triage", "ok": True, **outcome.output, "trace": trace}


def _capabilities() -> dict[str, Any]:
    return {
        "kind": "capabilities",
        "agent": AGENT_NAME,
        "tools": [t["name"] for t in TOOLS],
        "rule": "A subject's conventional-commit type decides its group: " + ", ".join(sorted(GROUP_OF_TYPE)) + ".",
        "limits": {
            "commits": f"at most {MAX_COMMITS} subjects of {MAX_SUBJECT_CHARS} characters",
            "turns": f"the agent loop stops after {MAX_TURNS} turns",
            "failures": "invalid_input and agent_error, each reported as itself",
        },
        "data_source": "None. The agent reads only the subjects it is given and calls no network.",
        "model_use": "None. The result is deterministic and complete without a language model.",
    }


def _plan_target(args: dict[str, Any]) -> str:
    requested = _as_string(args.get("tool")) or "run_full"
    return requested if requested in PLAN_SPECS else "run_full"


def dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    match name:
        case "open_form":
            return needs_input("run_full", PLAN_SPECS["run_full"][1], RUN_SPEC, {})
        case "run_form":
            # Forward the WHOLE payload so the form and its handler cannot drift apart.
            return dispatch_tool("run_full", dict(args))
        case "run_full" | "triage_commits":
            return _run(name, args)
        case "list_capabilities":
            return _capabilities()
        case "plan_inputs":
            tool = _plan_target(args)
            specs, brief = PLAN_SPECS[tool]
            return needs_input(tool, brief, specs, _as_object(args.get("provided")))
        case "discover_intent":
            tool = _plan_target(args)
            goal = _as_string(args.get("goal"))
            if goal is None:
                return needs_input(
                    "discover_intent",
                    "Understand the goal, then co-design the exact input before running.",
                    [GOAL_SPEC],
                    {},
                )
            provided = {k: _coerce_json(v) for k, v in _as_object(args.get("provided")).items()}
            return build_intent_dialogue(tool, goal, PLAN_SPECS[tool][0], provided)
        case _:
            raise ValueError(f"Unknown tool: {name}")
