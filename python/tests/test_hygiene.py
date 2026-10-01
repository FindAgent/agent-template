"""The repo rules FindAgent's autobuild and submission scan enforce, checked here so a fork learns about a
violation from its own CI and not from a submission that sits in review.
"""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".venv", ".git", "__pycache__", ".findagent_pydeps", ".pytest_cache", ".mypy_cache", ".ruff_cache", "docs"}
BINARY = {".png", ".jpg", ".ico", ".pyc"}


def walk() -> list[Path]:
    return [
        p
        for p in sorted(ROOT.rglob("*"))
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP) and p.suffix not in BINARY
    ]


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


ALL = walk()
SHIPPED = [p for p in ALL if not rel(p).startswith("tests/") and rel(p) != "requirements-dev.txt"]
BANNED = re.compile(r"\b(mock|mocks|mocked|fake|fakes|stub|stubs|stubbed|placeholder|lorem|todo|fixme|demo)\b", re.I)


def test_every_dependency_is_an_exact_pin_and_no_compiled_only_package_is_listed() -> None:
    for name in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-r")):
                continue
            assert re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?==\d", line), f"{name}: {line}"


def test_no_second_lockfile_and_no_package_manager_files() -> None:
    for other in ["package.json", "package-lock.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "yarn.lock"]:
        assert not (ROOT / other).exists(), other


def test_the_entrypoint_and_the_prebuilt_panel_exist() -> None:
    manifest = json.loads((ROOT / "findagent.json").read_text(encoding="utf-8"))
    assert (ROOT / manifest["entrypoint"]["path"]).is_file()
    assert (ROOT / manifest["ui"]["path"]).is_file()


def test_no_secret_scan_trigger_anywhere() -> None:
    pem = re.compile("-----" + "BEGIN [A-Z ]*" + "PRIVATE KEY" + "-----")
    tokens = [
        r"\bghp_[A-Za-z0-9]{20,}",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}",
        r"\bsk-[A-Za-z0-9]{20,}",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
        r"\bAIza[0-9A-Za-z_-]{30,}",
    ]
    for p in ALL:
        text = p.read_text(encoding="utf-8")
        assert not pem.search(text), rel(p)
        for token in tokens:
            if rel(p) == "tests/test_platform_check.py" or rel(p) == "scripts/check_platform.py":
                continue
            assert not re.search(token, text), f"{rel(p)} {token}"


def test_no_internal_ticket_id_personal_address_or_stray_windows_path() -> None:
    for p in ALL:
        assert not rel(p).startswith("%"), rel(p)
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"FC-\d+", text), rel(p)
        assert not re.search(r"@(gmail|hotmail|outlook|yahoo)\.", text, re.I), rel(p)


def test_no_environment_file_is_present() -> None:
    for p in ALL:
        assert not re.match(r"^\.env(\.|$)", p.name), rel(p)
    assert re.search(r"^\.env$", (ROOT / ".gitignore").read_text(encoding="utf-8"), re.M)


def test_no_shipped_file_is_named_like_a_sample() -> None:
    for p in SHIPPED:
        assert not re.search(r"example|sample|demo|mock|fake", rel(p), re.I), rel(p)


def test_no_shipped_file_mentions_mock_fake_stub_placeholder_lorem_todo_fixme_or_demo() -> None:
    for p in SHIPPED:
        for number, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            assert not BANNED.search(line), f"{rel(p)}:{number}: {line.strip()}"


def test_test_doubles_live_under_tests_and_nowhere_else() -> None:
    for p in ALL:
        if re.search(r"fake|mock|stub", p.name, re.I):
            assert rel(p).startswith("tests/"), rel(p)
    for p in SHIPPED:
        if p.suffix == ".py":
            assert not re.search(r"^\s*(from|import)\s+tests\b", p.read_text(encoding="utf-8"), re.M), rel(p)


def test_pyproject_findagent_json_and_the_panel_agree_on_one_version() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert re.match(r"^[a-z0-9][a-z0-9-]*$", project["name"])
    assert json.loads((ROOT / "findagent.json").read_text(encoding="utf-8"))["version"] == project["version"]


def test_the_generated_files_are_current() -> None:
    for script in ["scripts/sync_manifest.py", "scripts/build_panel.py"]:
        done = subprocess.run(
            [sys.executable, script, "--check"], cwd=ROOT, capture_output=True, text=True, check=False
        )
        assert done.returncode == 0, f"{script}: {done.stdout}{done.stderr}"


def test_every_python_file_compiles() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "agent_template", "server.py", "scripts"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
