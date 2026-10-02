"""`python scripts/check_platform.py` checks the rules FindAgent's submission and build enforce.

A check that cannot fail is not a check, so every rule is proven both ways: the real repository passes
with no error, and each rule goes red when one thing is broken in a copy of it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_template.tools import TOOLS

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_platform.py"
REGISTERED = [{"name": t["name"], "description": t["description"]} for t in TOOLS]
TRACKED = ["findagent.json", "manifest.json", "requirements.txt", ".gitignore", "server.py"]
SKIPPED = shutil.ignore_patterns(".venv", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")

Finding = dict[str, str]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway copy of the repository."""
    target = tmp_path / "repo"
    shutil.copytree(ROOT, target, ignore=SKIPPED)
    return target


def text(repo: Path, rel: str) -> str:
    return (repo / rel).read_text(encoding="utf-8")


def write(repo: Path, rel: str, content: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(content, encoding="utf-8")


def edit_json(repo: Path, rel: str, change: Callable[[Any], None]) -> None:
    data = json.loads(text(repo, rel))
    change(data)
    write(repo, rel, json.dumps(data, indent=2) + "\n")


def replace(repo: Path, rel: str, old: str, new: str) -> None:
    """Replace one thing, and prove the replacement landed (a mutation that changed nothing proves nothing)."""
    source = text(repo, rel)
    assert source.count(old) >= 1, f"mutation did not land: {old!r} not found in {rel}"
    write(repo, rel, source.replace(old, new))


def run(
    repo: Path,
    tmp_path: Path,
    tools: list[dict[str, str]] | None = None,
    tracked: list[str] | None = None,
    load_tools: bool = False,
) -> list[Finding]:
    """Run the real script as a program. `load_tools` makes it import the tool list from the copy itself."""
    tools_file = tmp_path / "tools.json"
    tracked_file = tmp_path / "tracked.json"
    tools_file.write_text(json.dumps(REGISTERED if tools is None else tools), encoding="utf-8")
    tracked_file.write_text(json.dumps(TRACKED if tracked is None else tracked), encoding="utf-8")
    command = [sys.executable, str(SCRIPT), "--root", str(repo), "--tracked", str(tracked_file), "--json"]
    if not load_tools:
        command += ["--tools", str(tools_file)]
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    assert done.returncode in (0, 1), done.stderr
    findings: list[Finding] = json.loads(done.stdout)
    return findings


def errors(findings: list[Finding]) -> list[str]:
    return [f["code"] for f in findings if f["level"] == "error"]


class Harness:
    def __init__(self, repo: Path, tmp_path: Path) -> None:
        self.repo = repo
        self.tmp_path = tmp_path

    def found(
        self, tools: list[dict[str, str]] | None = None, tracked: list[str] | None = None, load_tools: bool = False
    ) -> list[str]:
        return errors(run(self.repo, self.tmp_path, tools, tracked, load_tools))

    def expect(
        self,
        code: str,
        tools: list[dict[str, str]] | None = None,
        tracked: list[str] | None = None,
        load_tools: bool = False,
    ) -> None:
        got = self.found(tools, tracked, load_tools)
        assert code in got, f"expected {code}, got {got}"


@pytest.fixture
def h(repo: Path, tmp_path: Path) -> Harness:
    return Harness(repo, tmp_path)


def manifest(h: Harness, change: Callable[[Any], None]) -> None:
    edit_json(h.repo, "findagent.json", change)


# ---- the repository as shipped -------------------------------------------------------------------------


def test_the_repository_as_shipped_passes_every_rule_with_no_error_and_no_warning(h: Harness) -> None:
    findings = run(h.repo, h.tmp_path)
    assert errors(findings) == []
    assert [f for f in findings if f["level"] == "warn"] == []


def test_the_command_line_passes_on_the_repo_and_exits_one_on_a_broken_copy(h: Harness) -> None:
    ok = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "check_platform ok" in ok.stdout
    manifest(h, lambda j: j.pop("skills"))
    broken = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(h.repo), "--tracked", str(h.tmp_path / "t.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert broken.returncode == 1


# ---- (a) findagent.json ----------------------------------------------------------------------------------


def write_dxt(h: Harness, version: str | None = None, drop: str | None = None) -> None:
    current = json.loads(text(h.repo, "findagent.json"))["version"]
    dxt: dict[str, Any] = {
        "dxt_version": "0.1",
        "name": "x",
        "version": version or current,
        "server": {"type": "python"},
    }
    if drop:
        dxt.pop(drop)
    write(h.repo, "manifest.json", json.dumps(dxt))


class TestRuleA:
    def test_a_missing_findagent_json(self, h: Harness) -> None:
        (h.repo / "findagent.json").unlink()
        h.expect("findagent_json_missing")

    def test_a_dxt_manifest_alone_is_not_enough(self, h: Harness) -> None:
        write(
            h.repo, "manifest.json", json.dumps({"dxt_version": "0.1", "name": "x", "version": "0.3.0", "server": {}})
        )
        (h.repo / "findagent.json").unlink()
        h.expect("findagent_json_missing")

    def test_an_invalid_findagent_json(self, h: Harness) -> None:
        write(h.repo, "findagent.json", "{ nope")
        h.expect("invalid_json")

    def test_the_wrong_schema_version(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(schema_version="1.1"))
        h.expect("schema_version")

    def test_the_wrong_kind(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(kind="mcp-tool"))
        h.expect("kind")

    def test_an_empty_skills_would_serve_an_empty_tool_list(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(skills=[]))
        h.expect("skills_empty")

    def test_a_registered_tool_that_skills_does_not_list(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(skills=[s for s in j["skills"] if s["id"] != "open_form"]))
        h.expect("skills_missing_tool")

    def test_a_skill_the_server_does_not_register(self, h: Harness) -> None:
        manifest(h, lambda j: j["skills"].append({"id": "ghost_tool", "name": "ghost_tool", "description": "x" * 50}))
        h.expect("skills_unknown_tool")

    def test_a_skill_without_a_description(self, h: Harness) -> None:
        manifest(h, lambda j: j["skills"][0].update(description=""))
        h.expect("skill_incomplete")

    def test_a_skill_whose_id_and_name_differ(self, h: Harness) -> None:
        manifest(h, lambda j: j["skills"][0].update(name="other"))
        h.expect("skill_id_mismatch")

    def test_a_tool_description_the_served_list_would_cut_at_500_characters(self, h: Harness) -> None:
        manifest(h, lambda j: j["skills"][0].update(description="x" * 501))
        h.expect("skill_description_cut")

    def test_more_than_40_skills(self, h: Harness) -> None:
        def add(j: dict) -> None:
            for i in range(40):
                j["skills"].append({"id": f"extra_{i}", "name": f"extra_{i}", "description": "x" * 50})

        manifest(h, add)
        h.expect("skills_too_many")

    def test_an_input_schema_that_is_not_an_object_schema(self, h: Harness) -> None:
        manifest(h, lambda j: j["skills"][0].update(input_schema={"type": "array"}))
        h.expect("skill_schema_type")

    def test_a_skill_description_that_drifted_from_the_servers(self, h: Harness) -> None:
        manifest(h, lambda j: j["skills"][0].update(description=j["skills"][0]["description"] + " (edited by hand)"))
        h.expect("skill_description_drift")

    def test_the_tool_list_cannot_be_read(self, h: Harness) -> None:
        write(h.repo, "agent_template/tools.py", "raise RuntimeError('broken')\n")
        h.expect("tools_unreadable", load_tools=True)

    def test_a_dxt_manifest_that_drifted(self, h: Harness) -> None:
        write_dxt(h, version="9.9.9")
        h.expect("dxt_version_drift")

    def test_an_incomplete_dxt_manifest(self, h: Harness) -> None:
        write_dxt(h, drop="server")
        h.expect("dxt_incomplete")

    def test_a_findagent_json_version_that_differs_from_pyproject(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(version="9.9.9"))
        h.expect("version_drift")

    def test_a_non_python_runtime_is_refused_by_the_python_checker(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(runtime={"kind": "node", "version": "22"}))
        h.expect("runtime_mismatch")


# ---- (b) listing text -------------------------------------------------------------------------------------


class TestRuleB:
    def test_a_missing_or_short_description(self, h: Harness) -> None:
        manifest(h, lambda j: j.pop("description"))
        h.expect("description")
        manifest(h, lambda j: j.update(description="short"))
        h.expect("description")

    def test_a_missing_or_over_long_tagline(self, h: Harness) -> None:
        manifest(h, lambda j: j.pop("tagline"))
        h.expect("tagline")
        manifest(h, lambda j: j.update(tagline="t" * 141))
        h.expect("tagline")

    def test_no_example_prompts_or_too_many(self, h: Harness) -> None:
        manifest(h, lambda j: j.pop("example_prompts"))
        h.expect("example_prompts")
        manifest(h, lambda j: j.update(example_prompts=list("abcdef")))
        h.expect("example_prompts")

    def test_no_tags(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(tags=[]))
        h.expect("tags")


# ---- (c) category hints -----------------------------------------------------------------------------------


class TestRuleC:
    @pytest.mark.parametrize("bad", ["health", "monitoring", "compliance", "license", "legal", "email"])
    def test_a_tag_containing_a_misleading_word_is_refused(self, h: Harness, bad: str) -> None:
        manifest(h, lambda j: j["tags"].append(f"{bad}-tool"))
        h.expect("tag_misleads")

    def test_tags_must_name_the_discipline(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(tags=[t for t in j["tags"] if t != "software-development"]))
        h.expect("tag_discipline_missing")

    def test_a_tag_must_be_a_lowercase_slug(self, h: Harness) -> None:
        manifest(h, lambda j: j["tags"].append("Not A Slug"))
        h.expect("tag_shape")

    def test_misleading_words_in_the_text_only_warn(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(description=j["description"] + " It also does health monitoring."))
        findings = run(h.repo, h.tmp_path)
        assert errors(findings) == []
        warn = next(f for f in findings if f["code"] == "text_misleads")
        assert warn["level"] == "warn"
        assert "health" in warn["message"]

    def test_a_plain_word_that_merely_contains_a_flagged_one_does_not_match(self, h: Harness) -> None:
        manifest(h, lambda j: j["tags"].append("healthy-things"))
        assert "tag_misleads" not in h.found()


# ---- (d) the panel ----------------------------------------------------------------------------------------


def panel(h: Harness, old: str, new: str) -> None:
    replace(h.repo, "ui/index.html", old, new)


class TestRuleD:
    @pytest.mark.parametrize("call", ['request("tools/call", {})', "app.callServerTool(x)", "client.callTool (x)"])
    def test_a_panel_that_asks_the_host_to_call_a_tool(self, h: Harness, call: str) -> None:
        panel(h, "</script>", f"{call};</script>")
        h.expect("ui_calls_tools")

    def test_a_panel_that_loads_something_from_outside(self, h: Harness) -> None:
        panel(h, "<head>", '<head><script src="x.js"></script>')
        h.expect("ui_external")

    def test_a_panel_with_a_stylesheet_link(self, h: Harness) -> None:
        panel(h, "<head>", '<head><link rel="stylesheet" href="a.css">')
        h.expect("ui_external")

    def test_a_panel_that_names_a_url(self, h: Harness) -> None:
        panel(h, "</body>", "<a>https://example.org</a></body>")
        h.expect("ui_url")

    def test_a_panel_that_uses_the_network(self, h: Harness) -> None:
        panel(h, "</script>", "fetch(x);</script>")
        h.expect("ui_network")

    def test_a_panel_that_ignores_light_and_dark(self, h: Harness) -> None:
        write(h.repo, "ui/index.html", text(h.repo, "ui/index.html").replace("prefers-color-scheme", "prefers-nothing"))
        h.expect("ui_theme")

    def test_a_panel_that_ignores_the_phone(self, h: Harness) -> None:
        panel(h, 'name="viewport"', 'name="other"')
        h.expect("ui_viewport")

    def test_a_missing_oversized_or_non_html_panel(self, h: Harness) -> None:
        panel_path = h.repo / "ui" / "index.html"
        original = panel_path.read_text(encoding="utf-8")
        write(h.repo, "ui/index.html", original + "<!--" + "x" * 600 * 1024 + "-->")
        h.expect("ui_size")
        write(h.repo, "ui/index.html", "just text")
        h.expect("ui_not_html")
        panel_path.unlink()
        h.expect("ui_missing")

    def test_an_unsafe_panel_path(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(ui={"path": "../ui.html"}))
        h.expect("ui_path")

    def test_a_panel_resource_that_sets_a_domain(self, h: Harness) -> None:
        write(
            h.repo,
            "agent_template/mcp_server.py",
            text(h.repo, "agent_template/mcp_server.py") + '\nX = {"ui": {"domain": "a.example"}}\n',
        )
        h.expect("ui_domain")

    def test_a_tool_binding_that_lets_the_panel_call_back(self, h: Harness) -> None:
        replace(h.repo, "agent_template/tools.py", '"visibility": ["model"]', '"visibility": ["model", "app"]')
        h.expect("ui_visibility")

    def test_a_tool_binding_that_makes_the_widget_accessible(self, h: Harness) -> None:
        replace(
            h.repo, "agent_template/tools.py", '"openai/widgetAccessible": False', '"openai/widgetAccessible": True'
        )
        h.expect("ui_widget_accessible")

    def test_an_agent_with_no_panel_has_nothing_to_check(self, h: Harness) -> None:
        manifest(h, lambda j: j.pop("ui"))
        shutil.rmtree(h.repo / "ui")
        assert h.found() == []


# ---- (e) the build passes on the sandbox ------------------------------------------------------------------


class TestRuleE:
    def test_requirements_missing(self, h: Harness) -> None:
        (h.repo / "requirements.txt").unlink()
        h.expect("requirements_missing")

    @pytest.mark.parametrize("line", ["httpx>=0.28", "httpx~=0.28.1", "httpx", "httpx==0.28.*", "httpx<1"])
    def test_a_dependency_that_is_not_an_exact_pin(self, h: Harness, line: str) -> None:
        write(h.repo, "requirements.txt", text(h.repo, "requirements.txt") + line + "\n")
        h.expect("requirement_not_pinned")

    @pytest.mark.parametrize(
        "line",
        [
            "git+https://example.org/x.git",
            "./local",
            "-e .",
            "--index-url https://x.example",
            "pkg @ https://x.example/p.whl",
        ],
    )
    def test_a_dependency_from_a_url_a_path_or_an_option(self, h: Harness, line: str) -> None:
        write(h.repo, "requirements.txt", text(h.repo, "requirements.txt") + line + "\n")
        h.expect("requirement_unsafe")

    def test_a_second_lockfile(self, h: Harness) -> None:
        for other in ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Pipfile.lock"]:
            write(h.repo, other, "{}")
            h.expect("second_lockfile")
            (h.repo / other).unlink()

    def test_a_lockfile_the_sandbox_ignores_warns(self, h: Harness) -> None:
        write(h.repo, "poetry.lock", "")
        findings = run(h.repo, h.tmp_path)
        assert "lockfile_ignored" in [f["code"] for f in findings if f["level"] == "warn"]
        assert errors(findings) == []

    def test_gitignore_must_keep_the_environment_and_vendored_dependencies_out(self, h: Harness) -> None:
        write(h.repo, ".gitignore", "*.log\n")
        h.expect("gitignore_missing")

    @pytest.mark.parametrize(
        "name", [".venv/lib/x.py", ".findagent_pydeps/mcp/x.py", "%SystemDrive%/x", "pkg/__pycache__/a.pyc", "a.pyc"]
    )
    def test_a_tracked_cache_dependency_or_system_path(self, h: Harness, name: str) -> None:
        h.expect("stray_file", tracked=[*TRACKED, name])

    def test_a_build_command_that_runs_a_javascript_package_manager(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(build_command="npm run build"))
        h.expect("build_wrong_manager")

    def test_the_entrypoint_must_exist_and_stay_inside_the_repo(self, h: Harness) -> None:
        (h.repo / "server.py").unlink()
        h.expect("entrypoint_missing")
        manifest(h, lambda j: j.update(entrypoint={"path": "../server.py", "export": "main"}))
        h.expect("entrypoint_unsafe")

    def test_the_python_version_must_be_the_one_the_sandbox_runs(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(runtime={"kind": "python", "version": "3.12"}))
        h.expect("runtime_version")

    def test_a_print_corrupts_the_mcp_stream(self, h: Harness) -> None:
        write(h.repo, "agent_template/crates.py", text(h.repo, "agent_template/crates.py") + '\nprint("hello")\n')
        h.expect("stdout_print")

    def test_a_write_to_stdout_corrupts_the_mcp_stream(self, h: Harness) -> None:
        write(
            h.repo,
            "agent_template/crates.py",
            text(h.repo, "agent_template/crates.py") + '\nimport sys\nsys.stdout.write("x")\n',
        )
        h.expect("stdout_print")

    def test_printing_to_stderr_is_allowed(self, h: Harness) -> None:
        write(
            h.repo,
            "agent_template/crates.py",
            text(h.repo, "agent_template/crates.py") + '\nimport sys\nsys.stderr.write("x")\n',
        )
        assert "stdout_print" not in h.found()

    @pytest.mark.parametrize("path", ["/etc/passwd", "~/secrets", "../outside.txt", "C:\\\\data\\\\x"])
    def test_a_file_read_outside_the_repository(self, h: Harness, path: str) -> None:
        write(h.repo, "agent_template/crates.py", text(h.repo, "agent_template/crates.py") + f'\nopen("{path}")\n')
        h.expect("file_outside_repo")

    def test_a_source_file_that_does_not_compile(self, h: Harness) -> None:
        write(h.repo, "agent_template/broken.py", "def (:\n")
        h.expect("syntax_error")

    def test_a_secret_or_a_private_key_in_the_tree(self, h: Harness) -> None:
        header = "-----" + "BEGIN RSA " + "PRIVATE KEY" + "-----"
        write(h.repo, "notes.txt", header + "\n")
        h.expect("secret_shape")
        (h.repo / "notes.txt").unlink()
        write(h.repo, "notes.txt", "token ghp_" + "a" * 30 + "\n")
        h.expect("secret_shape")

    def test_an_environment_file(self, h: Harness) -> None:
        write(h.repo, ".env", "X=1\n")
        h.expect("env_file")


# ---- (f) egress and credentials ----------------------------------------------------------------------------

SLOT = {
    "ref": "crates_key",
    "label": "Crates key",
    "env": "CRATES_API_KEY",
    "allowed_hosts": ["crates.io"],
    "required": False,
}


def with_slot(h: Harness, **changes: Any) -> None:
    slot = {**SLOT, **changes}
    manifest(h, lambda j: j.update(credential_slots=[slot]))


class TestRuleF:
    def test_allowed_hosts_must_be_a_list(self, h: Harness) -> None:
        manifest(h, lambda j: j.pop("allowed_hosts"))
        h.expect("allowed_hosts_missing")

    @pytest.mark.parametrize(
        "host", ["https://crates.io", "crates.io/api", "crates.io:443", "*.crates.io", "10.0.0.1", "localhost"]
    )
    def test_an_allowed_host_must_be_a_plain_host_name(self, h: Harness, host: str) -> None:
        manifest(h, lambda j: j["allowed_hosts"].append(host))
        h.expect("allowed_host_shape")

    def test_a_host_the_code_calls_but_does_not_declare(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(allowed_hosts=[]))
        h.expect("host_not_declared")

    def test_a_declared_host_the_code_never_calls(self, h: Harness) -> None:
        manifest(h, lambda j: j["allowed_hosts"].append("example.org"))
        h.expect("host_not_called")

    def test_a_slot_that_is_not_an_object(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(credential_slots=["x"]))
        h.expect("slot_shape")

    def test_an_empty_slot_list_is_refused_not_ignored(self, h: Harness) -> None:
        manifest(h, lambda j: j.update(credential_slots=[]))
        h.expect("slots_empty")

    def test_a_valid_slot_is_accepted(self, h: Harness) -> None:
        with_slot(h)
        assert h.found() == []

    def test_a_slot_that_holds_a_value(self, h: Harness) -> None:
        with_slot(h, value="abc")
        h.expect("slot_unknown_key")

    def test_a_slot_ref_must_not_be_an_object_property_name(self, h: Harness) -> None:
        with_slot(h, ref="__proto__")
        h.expect("slot_ref")

    def test_a_slot_needs_a_label_and_an_explicit_required(self, h: Harness) -> None:
        with_slot(h, label="")
        h.expect("slot_label")
        with_slot(h, required="yes")
        h.expect("slot_required")

    def test_a_secret_needs_a_destination(self, h: Harness) -> None:
        with_slot(h, allowed_hosts=[])
        h.expect("slot_no_audience")

    def test_a_slot_cannot_have_two_audiences(self, h: Harness) -> None:
        with_slot(h, install_host=True)
        h.expect("slot_two_audiences")

    def test_install_host_with_no_fixed_hosts_is_accepted(self, h: Harness) -> None:
        with_slot(h, allowed_hosts=[], install_host=True)
        assert "slot_no_audience" not in h.found()
        assert "slot_two_audiences" not in h.found()

    def test_a_slot_host_must_be_a_plain_host_name_and_reachable(self, h: Harness) -> None:
        with_slot(h, allowed_hosts=["https://crates.io"])
        h.expect("slot_host_shape")
        with_slot(h, allowed_hosts=["example.org"])
        h.expect("slot_host_unreachable")

    def test_a_slot_that_holds_a_real_looking_secret(self, h: Harness) -> None:
        with_slot(h, description="use ghp_" + "b" * 30)
        h.expect("slot_holds_secret")

    def test_a_credential_the_code_reads_but_no_slot_declares(self, h: Harness) -> None:
        write(
            h.repo,
            "agent_template/crates.py",
            text(h.repo, "agent_template/crates.py") + '\nimport os\nKEY = os.environ["CRATES_API_KEY"]\n',
        )
        h.expect("credential_not_declared")

    def test_a_declared_credential_the_code_reads_is_accepted(self, h: Harness) -> None:
        with_slot(h)
        write(
            h.repo,
            "agent_template/crates.py",
            text(h.repo, "agent_template/crates.py") + '\nimport os\nKEY = os.environ["CRATES_API_KEY"]\n',
        )
        assert "credential_not_declared" not in h.found()
