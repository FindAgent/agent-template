"""MCP tool definitions and the dispatcher.

Entry-tool contract (the platform draws its form panel from these, so all six must exist and work):
plan_inputs, open_form, run_form, run_full, list_capabilities, discover_intent. This agent's one
capability tool is check_crate; replace it with your own.

Missing or malformed arguments never raise: a tool that lacks its required input answers with a
structured `needs_input` payload (questions, a `next_question`, schema, an editable example) so the
host can ask the user and retry. open_form, plan_inputs and run_form answer in that shape and the
platform renders the form; this agent ships no form panel of its own. Its one panel draws RESULTS
(see panel/).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from .check import REQUEST_BUDGET, failure
from .crates import CRATES_HOST
from .intent import build_intent_dialogue
from .interactive import FieldSpec, check_required, needs_input
from .meta import AGENT_NAME
from .signals import MIN_CHECKED_FOR_VERDICT, SIGNAL_RULES

#: URI of the result panel. A tool result that carries a report is drawn by this one document.
PANEL_RESOURCE_URI = f"ui://{AGENT_NAME}/panel"

CRATE_DESCRIPTION = "A crate name as published on crates.io, for example serde or tokio. Case does not matter."
OWNERS_DESCRIPTION = (
    "Whether to also read the owners list. It costs one extra request; when it fails the check "
    "still completes and says the signal was not checked. Default true."
)

_CRATE_PROP: dict[str, Any] = {"type": "string", "description": CRATE_DESCRIPTION}
_OWNERS_PROP: dict[str, Any] = {"type": "boolean", "description": OWNERS_DESCRIPTION}


def _tool(name: str, title: str, description: str, input_schema: dict[str, Any]) -> dict[str, Any]:
    # Every tool here only reads a public API, so every tool says so.
    return {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "annotations": {"title": title, "readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    }


_RUN_PROPS: dict[str, Any] = {"crate": _CRATE_PROP, "owners": _OWNERS_PROP}

TOOLS: list[dict[str, Any]] = [
    _tool(
        "open_form",
        "Open the input form",
        "Use this the moment the user wants a Rust crate checked. It returns the questions to ask "
        "(the crate name, whether to include owners) so a form can be shown. Do NOT run a check "
        "before calling this; the form is the entry point.",
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
        "Check a crate",
        "Run the whole check end to end for one crate on crates.io: latest release age, yanked, license, "
        "source repository, recent downloads and owners, each with the rule and the API field behind it, "
        "then a verdict (healthy, watch, risky or unknown) with the reason. Use when the user names a crate "
        "and wants the full answer. Missing the crate name, it asks for it instead of failing.",
        {"type": "object", "properties": _RUN_PROPS},
    ),
    _tool(
        "check_crate",
        "Check one crate",
        "Check ONE crate from live crates.io data and return its signals and verdict. Same result as "
        "run_full; use it when the crate is already known and no form is needed. Reports a missing or "
        "unreachable crate as exactly that, never as a clean result.",
        {"type": "object", "properties": _RUN_PROPS, "required": ["crate"]},
    ),
    _tool(
        "list_capabilities",
        "List capabilities",
        "List what this agent checks, the rule and API field behind each signal, its request budget and "
        "its limits. Use for discovery before running a check.",
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
                "tool": {"type": "string", "description": "Which tool to plan inputs for (run_full or check_crate)."},
                "goal": {"type": "string", "description": "Optional freeform goal."},
                "provided": {"type": "object", "description": "Optional partial arguments already known."},
            },
        },
    ),
    _tool(
        "discover_intent",
        "Discover the intent",
        "Use when the user states a goal in their own words ('is this crate still maintained?'). It "
        "restates the goal, asks the few questions that pin the input down and proposes a ready-to-run "
        "input to confirm before running.",
        {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "What the user wants to find out about a crate."},
                "tool": {"type": "string", "description": "Which tool to plan for. Defaults to run_full."},
                "provided": {"type": "object", "description": "Optional partial args already known."},
            },
            "required": ["goal"],
        },
    ),
]

#: The tools that run a check when given their input. Only these may be upgraded to a native form.
RUNNING_TOOLS: frozenset[str] = frozenset({"run_full", "run_form", "check_crate"})


def panel_binding(uri: str) -> dict[str, Any]:
    """The `_meta` that binds a tool's result to the result panel and says the panel may NOT call the
    tool back: model-only on both hosts (MCP Apps `ui.visibility` and ChatGPT `widgetAccessible`).
    The panel calls no tool; anything it wants done goes back to the conversation as a message."""
    return {
        "ui": {"resourceUri": uri, "visibility": ["model"]},
        "openai/outputTemplate": uri,
        "openai/widgetAccessible": False,
    }


# -- FieldSpecs ----------------------------------------------------------------------------------

CRATE_SPEC = FieldSpec(
    name="crate",
    type="string",
    required=True,
    description=CRATE_DESCRIPTION,
    example="serde",
    question="Which crate should I check? (for example serde or tokio)",
)
OWNERS_SPEC = FieldSpec(
    name="owners",
    type="boolean",
    description=OWNERS_DESCRIPTION,
    example=True,
    question="Include the owners list? (one extra request; default yes)",
)
GOAL_SPEC = FieldSpec(
    name="goal",
    type="string",
    required=True,
    description="What the user wants to find out about a crate, in their own words.",
    example="Is serde still well maintained?",
    question="What do you want to find out about the crate?",
)

#: The questions open_form and run_full ask.
RUN_FULL_SPEC = [CRATE_SPEC, OWNERS_SPEC]

PLAN_SPECS: dict[str, tuple[list[FieldSpec], str]] = {
    "run_full": (RUN_FULL_SPEC, "Check a crate's health from live crates.io data."),
    "check_crate": (RUN_FULL_SPEC, "Check one crate's health from live crates.io data."),
}


# -- argument helpers ----------------------------------------------------------------------------


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


def _as_owners(value: object) -> tuple[bool, bool]:
    """(valid, owners). Absent means the default, true; "true" and "false" are accepted as strings."""
    if value is None:
        return True, True
    if isinstance(value, bool):
        return True, value
    if value in ("true", "false"):
        return True, value == "true"
    return False, True


# -- dispatcher ----------------------------------------------------------------------------------

#: What a check needs: (crate, owners) -> the result. The server supplies the real one.
CheckRunner = Callable[[object, bool], Awaitable[dict[str, Any]]]


async def _run_check(tool: str, args: dict[str, Any], run_check: CheckRunner) -> dict[str, Any]:
    raw = args.get("crate")
    brief = PLAN_SPECS["run_full"][1]
    need = check_required(tool, brief, RUN_FULL_SPEC, {"crate": _as_string(raw)})
    if need:
        # A value that is present but not a string is a wrong type, not a missing answer.
        if raw is not None and not isinstance(raw, str):
            return failure("", "invalid_input", "crate must be a string.", 0)
        return need
    valid, owners = _as_owners(args.get("owners"))
    if not valid:
        return failure(
            _as_string(raw) or "",
            "invalid_input",
            f"owners must be true or false (got {json.dumps(args.get('owners'))}).",
            0,
        )
    return await run_check(raw, owners)


def _capabilities() -> dict[str, Any]:
    return {
        "kind": "capabilities",
        "agent": AGENT_NAME,
        "tools": [t["name"] for t in TOOLS],
        "data_source": f"The public crates.io API ({CRATES_HOST}). GET only, no authentication, no credentials.",
        "signals": SIGNAL_RULES,
        "verdict": (
            "risky when any measured signal is a risk, watch when any is a warn, healthy otherwise; "
            f"unknown when fewer than {MIN_CHECKED_FOR_VERDICT} signals could be measured. "
            "A signal that could not be measured is reported as not checked with the reason and never scored as zero."
        ),
        "limits": {
            "requests_per_check": f"up to {REQUEST_BUDGET} (1 without owners)",
            "failures": (
                "invalid_input, not_found, rate_limited (with the reset time when the upstream gives one), "
                "timeout, network_error, upstream_error, malformed_response, response_too_large: "
                "each is reported as itself"
            ),
            "caching": "none; every check reads live data",
        },
        "model_use": "None. The result is deterministic and complete without a language model.",
    }


def _plan_target(args: dict[str, Any]) -> str:
    requested = _as_string(args.get("tool")) or "run_full"
    return requested if requested in PLAN_SPECS else "run_full"


async def dispatch_tool(name: str, args: dict[str, Any], run_check: CheckRunner) -> dict[str, Any]:
    match name:
        case "open_form":
            return needs_input("run_full", PLAN_SPECS["run_full"][1], RUN_FULL_SPEC, {})
        case "run_form":
            # Forward the WHOLE payload so the form and its handler cannot drift apart.
            return await dispatch_tool("run_full", dict(args), run_check)
        case "run_full" | "check_crate":
            return await _run_check(name, args, run_check)
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
