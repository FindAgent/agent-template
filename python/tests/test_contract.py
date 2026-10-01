"""The six entry tools, the needs_input shapes the platform draws its form from, and the manifest."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_template.check import check_crate
from agent_template.config import DEFAULTS
from agent_template.crates import fetch_crate  # noqa: F401  (imported to prove the module loads)
from agent_template.mcp_server import list_tools, to_call_tool_result
from agent_template.tools import PANEL_RESOURCE_URI, RUNNING_TOOLS, TOOLS, dispatch_tool, panel_binding

from .conftest import NOW, TEST_CONFIG, Fake, crate_doc, routes_for

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parent.parent
NAMES = [t["name"] for t in TOOLS]

#: The six tools the platform requires of every code agent.
ENTRY_TOOLS = ["plan_inputs", "open_form", "run_form", "run_full", "list_capabilities", "discover_intent"]


def runner(fake: Fake) -> Any:
    async def run_check(crate: object, owners: bool) -> dict[str, Any]:
        return await check_crate(crate, client=fake.client, config=TEST_CONFIG, owners=owners, now=lambda: NOW)

    return run_check


async def call(name: str, args: dict[str, Any] | None = None, fake: Fake | None = None) -> dict[str, Any]:
    return await dispatch_tool(name, args or {}, runner(fake or Fake({})))


def test_all_six_entry_tools_exist_and_the_only_other_tool_is_the_capability() -> None:
    for tool in ENTRY_TOOLS:
        assert tool in NAMES, f"missing entry tool {tool}"
    assert [n for n in NAMES if n not in ENTRY_TOOLS] == ["check_crate"]
    assert len(set(NAMES)) == len(NAMES)


def test_every_tool_says_when_to_use_it_has_an_object_schema_and_read_only_annotations() -> None:
    for tool in TOOLS:
        assert len(tool["description"]) > 40, tool["name"]
        assert tool["inputSchema"]["type"] == "object"
        for prop in tool["inputSchema"]["properties"].values():
            assert "type" in prop
        assert tool["annotations"]["readOnlyHint"] is True, tool["name"]
        assert tool["name"].replace("_", "").isalpha()


async def test_every_entry_tool_answers_structured_json_without_a_network() -> None:
    fake = Fake({})
    for tool in ENTRY_TOOLS:
        result = await call(tool, {"goal": "is it maintained"} if tool == "discover_intent" else {}, fake)
        wire = to_call_tool_result(result)
        assert wire.structuredContent == result
        assert json.loads(wire.content[0].text) == result  # type: ignore[union-attr]
    assert fake.requests == []


@pytest.mark.parametrize(
    "tool,args",
    [
        ("open_form", {}),
        ("plan_inputs", {}),
        ("run_full", {}),
        ("run_full", {"crate": "   "}),
        ("run_form", {}),
        ("check_crate", {}),
    ],
)
async def test_a_missing_crate_answers_needs_input_and_names_the_slot_at_no_cost(
    tool: str, args: dict[str, Any]
) -> None:
    fake = Fake({})
    result = await call(tool, args, fake)
    assert result["status"] == "needs_input"
    assert result["questions"]
    assert result["next_question"]["field"] == "crate"
    assert result["schema"]["required"] == ["crate"]
    assert result["example"] == {"crate": "serde", "owners": True}
    assert result["missing"] == ["crate"]
    assert isinstance(result["hint"], str)
    assert fake.requests == []


async def test_needs_input_has_exactly_the_shape_the_platform_draws_its_form_from() -> None:
    result = await call("open_form")
    assert sorted(result) == sorted(
        ["brief", "example", "hint", "missing", "next_question", "questions", "schema", "status", "tool"]
    )
    question = next(q for q in result["questions"] if q["field"] == "crate")
    assert (question["required"], question["type"], question["example"]) == (True, "string", "serde")
    assert isinstance(question["question"], str)
    optional = next(q for q in result["questions"] if q["field"] == "owners")
    assert (optional["required"], optional["type"]) == (False, "boolean")


async def test_plan_inputs_plans_for_the_tool_asked_about_and_falls_back_for_an_unknown_one() -> None:
    assert (await call("plan_inputs", {"tool": "check_crate"}))["tool"] == "check_crate"
    assert (await call("plan_inputs", {"tool": "nope"}))["tool"] == "run_full"


async def test_answers_already_given_are_kept_only_the_missing_slot_is_asked() -> None:
    assert (await call("plan_inputs", {"provided": '{"crate":"serde"}'}))["missing"] == []


async def test_a_crate_given_as_a_non_string_is_invalid_input_not_a_missing_answer() -> None:
    for bad in [42, {}, [], True]:
        result = await call("run_full", {"crate": bad})
        assert (result["ok"], result["failure"]) == (False, "invalid_input"), bad


async def test_owners_must_be_a_boolean_and_the_strings_true_and_false_are_accepted() -> None:
    fake = Fake(routes_for("acme-widget", crate_doc()))
    ok = await call("run_full", {"crate": "acme-widget", "owners": "false"}, fake)
    assert (ok["ok"], ok["requests"]["used"]) == (True, 1)
    bad = await call("run_full", {"crate": "acme-widget", "owners": "maybe"}, fake)
    assert (bad["ok"], bad["failure"]) == (False, "invalid_input")


async def test_hostile_tool_names_plan_for_run_full_instead_of_crashing() -> None:
    for tool in ["constructor", "__proto__", "toString", "hasOwnProperty", "__class__"]:
        assert (await call("plan_inputs", {"tool": tool}))["tool"] == "run_full"
        assert (await call("discover_intent", {"goal": "x", "tool": tool}))["tool"] == "run_full"


async def test_discover_intent_carries_over_only_fields_the_tool_declares() -> None:
    result = await call(
        "discover_intent", {"goal": "x", "provided": {"crate": "serde", "injected": "<b>boo</b>", "__proto__": 1}}
    )
    assert sorted(result["proposed_input"]) == ["crate", "owners"]


async def test_a_very_long_goal_is_cut_not_echoed_whole() -> None:
    result = await call("discover_intent", {"goal": "g" * 5000})
    assert len(result["restated_goal"]) < 400
    assert result["restated_goal"].endswith("...")


async def test_discover_intent_without_a_goal_asks_for_it_naming_the_slot() -> None:
    for args in [{}, {"goal": "  "}]:
        result = await call("discover_intent", args)
        assert (result["status"], result["next_question"]["field"], result["missing"]) == (
            "needs_input",
            "goal",
            ["goal"],
        )


async def test_discover_intent_restates_the_goal_and_proposes_a_runnable_input() -> None:
    result = await call("discover_intent", {"goal": "is serde still maintained", "provided": {"crate": "serde"}})
    assert result["status"] == "intent_discovery"
    assert "is serde still maintained" in result["restated_goal"]
    assert result["proposed_input"]["crate"] == "serde"
    assert result["questions"]
    assert "run_full" in result["confirm_prompt"]


async def test_a_malformed_json_string_for_provided_is_ignored() -> None:
    assert (await call("plan_inputs", {"provided": "{not json"}))["status"] == "needs_input"


async def test_run_form_forwards_its_whole_payload_to_run_full() -> None:
    fake = Fake(routes_for("acme-widget", crate_doc()))
    result = await call("run_form", {"crate": "acme-widget", "owners": False}, fake)
    assert (result["kind"], result["requests"]["used"]) == ("crate_check", 1)


async def test_run_full_and_check_crate_give_the_same_report() -> None:
    a = await call("run_full", {"crate": "acme-widget"}, Fake(routes_for("acme-widget", crate_doc())))
    b = await call("check_crate", {"crate": "acme-widget"}, Fake(routes_for("acme-widget", crate_doc())))
    assert a == b


async def test_a_failed_check_is_marked_is_error_and_keeps_its_class_in_the_body() -> None:
    from .conftest import Reply

    wire = to_call_tool_result(
        await call("run_full", {"crate": "ghost"}, Fake({"crates.io/api/v1/crates/ghost": Reply(404)}))
    )
    assert wire.isError is True
    assert wire.structuredContent is not None
    assert (wire.structuredContent["kind"], wire.structuredContent["failure"]) == ("crate_failure", "not_found")


async def test_a_report_and_a_needs_input_are_not_marked_is_error() -> None:
    fake = Fake(routes_for("acme-widget", crate_doc()))
    assert to_call_tool_result(await call("run_full", {"crate": "acme-widget"}, fake)).isError is False
    assert to_call_tool_result(await call("open_form")).isError is False


async def test_an_unknown_tool_raises_rather_than_answering() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await call("nope")


async def test_list_capabilities_lists_every_signal_with_its_rule_the_host_and_the_limits() -> None:
    result = await call("list_capabilities")
    assert result["kind"] == "capabilities"
    assert result["tools"] == NAMES
    assert [s["id"] for s in result["signals"]] == [
        "latest_release_age",
        "yanked",
        "license",
        "repository",
        "recent_downloads",
        "owners",
    ]
    assert all(isinstance(s["rule"], str) and isinstance(s["field"], str) for s in result["signals"])
    assert "crates.io" in result["data_source"]
    assert result["model_use"].startswith("None")


def test_every_tool_is_bound_to_the_panel_and_is_model_only_on_both_hosts() -> None:
    for tool in list_tools():
        meta = tool.meta or {}
        assert meta["ui"] == {"resourceUri": PANEL_RESOURCE_URI, "visibility": ["model"]}
        assert meta["openai/outputTemplate"] == PANEL_RESOURCE_URI
        assert meta["openai/widgetAccessible"] is False
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
    assert panel_binding("ui://x/y")["openai/widgetAccessible"] is False
    assert PANEL_RESOURCE_URI.startswith("ui://")


def test_only_the_tools_that_run_a_check_may_be_upgraded_to_a_native_form() -> None:
    assert sorted(RUNNING_TOOLS) == ["check_crate", "run_form", "run_full"]
    for tool in ["open_form", "plan_inputs", "discover_intent", "list_capabilities"]:
        assert tool not in RUNNING_TOOLS


def test_the_defaults_are_the_ones_the_hosted_sandbox_runs() -> None:
    assert (DEFAULTS.timeout_ms, DEFAULTS.max_bytes, DEFAULTS.spacing_ms) == (10_000, 5 * 1024 * 1024, 1000)


class TestManifest:
    manifest = json.loads((ROOT / "findagent.json").read_text(encoding="utf-8"))

    def test_findagent_json_is_a_v1_2_code_bundle_with_the_required_fields(self) -> None:
        m = self.manifest
        assert (m["schema_version"], m["kind"]) == ("1.2", "code-bundle")
        assert 3 <= len(m["name"]) <= 80
        assert m["entrypoint"] == {"path": "server.py", "export": "main"}
        assert m["runtime"] == {"kind": "python", "version": "3.13"}
        assert m["mcp"] == {"mode": "native", "command": "python3", "args": ["server.py"]}
        assert len(m["description"]) <= 4000
        assert len(m["tagline"]) <= 140
        assert 1 <= len(m["example_prompts"]) <= 5
        assert (ROOT / m["entrypoint"]["path"]).is_file()

    def test_skills_is_exactly_the_registered_tools_with_the_same_descriptions_and_schemas(self) -> None:
        assert [s["id"] for s in self.manifest["skills"]] == NAMES
        for skill in self.manifest["skills"]:
            tool = next(t for t in TOOLS if t["name"] == skill["id"])
            assert skill["name"] == skill["id"]
            assert skill["description"] == tool["description"]
            assert skill["input_schema"] == tool["inputSchema"]

    def test_no_credential_slot_because_the_agent_needs_no_secret(self) -> None:
        assert "credential_slots" not in self.manifest

    def test_serves_hosted_only_and_declares_a_panel_that_exists(self) -> None:
        assert self.manifest["serve"] == ["hosted"]
        assert self.manifest["ui"] == {"path": "ui/index.html"}
        assert (ROOT / "ui" / "index.html").is_file()
        assert '"domain"' not in json.dumps(self.manifest)

    def test_no_build_command_because_a_python_agent_has_nothing_to_compile(self) -> None:
        assert "build_command" not in self.manifest
