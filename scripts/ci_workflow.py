"""The CI workflow init_agent.py writes into a new agent repository.

Built from what the repository actually contains. It never copies the template's own CI, which
names the template's package and helper scripts and fails in any other agent.
"""

import re
from pathlib import Path

PYTHON_HEAD = """name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  gates:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install
        run: pip install -r requirements.txt -r requirements-dev.txt
"""


def python_package(dest: Path) -> str | None:
    pyproject = dest / "pyproject.toml"
    if pyproject.exists():
        found = re.search(r'files\s*=\s*\[\s*"([A-Za-z0-9_]+)"', pyproject.read_text(encoding="utf-8"))
        if found:
            return found.group(1)
    for d in sorted(dest.iterdir()):
        if d.is_dir() and (d / "__init__.py").exists() and d.name not in ("tests", "scripts"):
            return d.name
    return None


def python_ci(dest: Path) -> str:
    pyproject = dest / "pyproject.toml"
    configured = pyproject.exists() and "[tool.mypy]" in pyproject.read_text(encoding="utf-8")
    pkg = python_package(dest)
    targets = " ".join(t for t in (pkg, "server.py") if t and (dest / t).exists())
    steps = [("Lint", "ruff check .")]
    if configured and targets:
        steps.append(("Types", f"mypy {targets}"))
    if (dest / "tests").is_dir():
        steps.append(("Tests", "pytest"))
    steps.append(("Repository is complete", "python scripts/check_repo_files.py ."))
    return PYTHON_HEAD + "".join(f"      - name: {name}\n        run: {cmd}\n" for name, cmd in steps)


def node_ci(root: Path) -> str:
    text = (root / ".github" / "workflows" / "node.yml").read_text(encoding="utf-8")
    text = re.sub(r"\n    paths: \[[^\n]*\]", "", text)
    text = re.sub(r"\n    defaults:\n      run:\n        working-directory: \w+", "", text)
    text = re.sub(r"# Copying[^\n]*\n#[^\n]*\n", "", text)
    text = text.replace("working-directory: node/", "").replace("node/", "")
    return text.replace("name: Node agent", "name: CI", 1)


def ci_workflow(variant: str, dest: Path, template_root: Path) -> str:
    return node_ci(template_root) if variant == "node" else python_ci(dest)
