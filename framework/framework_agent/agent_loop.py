"""A tiny local agent loop shaped like the agent frameworks.

The common frameworks (the OpenAI Agents SDK, LangChain and LangGraph, CrewAI, LlamaIndex) all have the
same four parts: an agent that holds instructions and tools, a tool decorated from a plain function, a
runner that loops "pick a tool, run it, feed the result back" until the agent answers, and a trace of
what happened. This module is those four parts with no dependency, so the template runs anywhere and
the mapping to a real framework is one file: replace `Agent`, `function_tool` and `Runner` with the
framework's own and keep `tools.py` and `mcp_server.py` as they are (see the README).

The planner here is a deterministic function, not a model. That is the honest default for an agent the
platform serves: the result is complete and repeatable without a language model. A framework agent
would put a model call in `Planner.next_step` instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

#: A loop that does not finish is a bug in the planner, never an endless run.
MAX_TURNS = 8


@dataclass(frozen=True)
class FunctionTool:
    """A plain function the agent may call, with the name and description a model would be shown."""

    name: str
    description: str
    fn: Callable[..., Any]


def function_tool(fn: Callable[..., Any]) -> FunctionTool:
    """Turn a function into a tool. The first docstring line is its description (as the SDKs do)."""
    doc = (fn.__doc__ or "").strip().splitlines()
    return FunctionTool(name=fn.__name__, description=doc[0] if doc else fn.__name__, fn=fn)


@dataclass(frozen=True)
class ToolCall:
    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Final:
    """The planner is done; `output` is the agent's answer."""

    output: dict[str, Any]


@dataclass(frozen=True)
class Turn:
    """One recorded step of the loop: which tool ran, with what, and what came back."""

    number: int
    tool: str
    arguments: dict[str, Any]
    result: Any


class Planner(Protocol):
    def next_step(self, goal: Any, history: list[Turn]) -> ToolCall | Final: ...


@dataclass(frozen=True)
class Agent:
    name: str
    instructions: str
    tools: tuple[FunctionTool, ...]
    planner: Planner

    def tool(self, name: str) -> FunctionTool:
        for candidate in self.tools:
            if candidate.name == name:
                return candidate
        raise LoopError(f"the planner asked for an unknown tool: {name}")


@dataclass(frozen=True)
class RunResult:
    output: dict[str, Any]
    turns: list[Turn] = field(default_factory=list)


class LoopError(Exception):
    """The loop could not finish: an unknown tool, a tool that raised, or too many turns."""


class Runner:
    @staticmethod
    def run_sync(agent: Agent, goal: Any) -> RunResult:
        history: list[Turn] = []
        for number in range(1, MAX_TURNS + 1):
            step = agent.planner.next_step(goal, history)
            if isinstance(step, Final):
                return RunResult(output=step.output, turns=history)
            tool = agent.tool(step.tool)
            try:
                result = tool.fn(**step.arguments)
            except Exception as err:
                raise LoopError(f"tool {tool.name} failed: {err}") from err
            history.append(Turn(number=number, tool=tool.name, arguments=step.arguments, result=result))
        raise LoopError(f"the agent did not finish in {MAX_TURNS} turns")
