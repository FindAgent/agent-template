"""check:platform: does this repo satisfy what FindAgent's submission and build expect of a code agent?

Each rule below is one that a real submission has tripped over, and each one fails here, in seconds,
instead of in review. The Node variant ships the same rules (same letters, same finding codes where the
rule is the same) in scripts/check-platform.mjs.

  (a) findagent.json is the contract: schema 1.2, kind code-bundle, and `skills[]` lists EVERY tool the
      server registers. The submit form prefills the tool list from it; without it the agent is served
      with an empty tool list.
  (b) listing text: description, tagline, 1-5 example prompts, tags.
  (c) category hints: tags carry the discipline, and no tag is a word that sends the auto-categoriser
      to the wrong place.
  (d) a panel only displays, or answers with ui/message. It never asks the host to call a tool.
  (e) the build passes on the sandbox: a requirements.txt of exact pins, the prebuilt panel committed,
      stdout left to the MCP stream, no file read outside the repository, an entrypoint that exists.
  (f) allowed_hosts is exactly the hosts the code calls; credential slots are declarations only.

    python scripts/check_platform.py            check this repository
    python scripts/check_platform.py --wheels   also ask PyPI whether every pin has a binary wheel
                                                for the sandbox (Linux, Python 3.13); needs the network

Exit 0: no error. Exit 1: at least one error (warnings never fail it). Standard library only.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).resolve().parent.parent

# The panel rule FindAgent's preflight applies to a creator's panel. Same expression, on purpose.
PANEL_CALLS_A_TOOL = re.compile(r"tools/call|callServerTool|\.callTool\s*\(")
MAX_PANEL_BYTES = 512 * 1024

OTHER_LOCKFILES = ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "Pipfile.lock"]
IGNORED_LOCKFILES = ["poetry.lock", "uv.lock", "pdm.lock"]

SLOT_KEYS = {
    "ref",
    "label",
    "description",
    "env",
    "allowed_hosts",
    "install_host",
    "host_example",
    "type",
    "required",
    "auth_scheme",
    "header_name",
    "prefix",
    "auth_acquisition",
    "provider",
}

DISCIPLINE_TAG = "software-development"

# Words that send the auto-categoriser somewhere other than where a code agent belongs. A code agent
# is always filed under the Software Development discipline; the first group are the words seen to
# mislead a real submission, the rest are the needles of the platform's keyword table for the
# non-engineering categories (a snapshot of the table in FindAgent's importer, kept here because this
# repository cannot import it: refresh it when that table changes).
MISLEADING: dict[str, str] = {}
for _group, _words in {
    "health, monitoring and licensing words": "health healthcare monitor monitoring compliance license licence",
    "research": "scrape scraper scraping crawl crawler fetch search serp browse extract research",
    "data analytics": "analytics ga4 chart charts metric metrics dashboard report reporting kpi visualization",
    "marketing": "campaign email newsletter sms ads seo social audience segment",
    "sales": "crm lead leads prospect outreach pipeline",
    "customer support": "ticket helpdesk support faq chatbot",
    "finance": "invoice accounting ledger payment tax payroll expense",
    "operations": "workflow automation schedule ops admin inventory fulfillment",
    "writing": "blog article essay draft proofread rewrite translate caption",
    "design": "design figma image logo illustration mockup",
    "recruiting": "recruit candidate resume hiring applicant onboarding",
    "legal": "contract legal gdpr clause litigation nda",
}.items():
    for _word in _words.split():
        MISLEADING[_word] = _group

SECRET_SHAPES = [
    re.compile("-----" + "BEGIN [A-Z ]*" + "PRIVATE KEY" + "-----"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
]

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
SAFE_REL_PATH = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$")
PIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?==[0-9][A-Za-z0-9.+!_-]*$")
CREDENTIAL_ENV = re.compile(
    r"""(?:os\.environ\[|os\.environ\.get\(|os\.getenv\()\s*["']"""
    r"""([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*)["']"""
)
PROTOTYPE_NAMES = {"__proto__", "constructor", "prototype"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".findagent_pydeps", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


@dataclass(frozen=True)
class Finding:
    rule: str
    level: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "level": self.level, "code": self.code, "message": self.message}


def walk(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not (set(path.relative_to(root).parts) & SKIP_DIRS):
            out.append(path)
    return out


def words(text: object) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", str(text).lower()) if w]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def python_sources(root: Path) -> list[Path]:
    """The code that ships: the package and the entrypoint, not the tests or the operator scripts."""
    found = [p for p in walk(root) if p.suffix == ".py"]
    return [p for p in found if p.relative_to(root).parts[0] not in {"tests", "scripts"}]


def strip_comments(source: str) -> str:
    return re.sub(r"(^|[^:\"'])#.*$", r"\1", source, flags=re.MULTILINE)


def tracked_files(root: Path) -> list[str] | None:
    """The tracked files, or None when this is not a git work tree (then every file on disk counts)."""
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, text=True, check=True
        )
        if inside.stdout.strip() != "true":
            return None
        listed = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [line for line in listed.stdout.split("\n") if line]


def load_registered_tools(root: Path) -> list[dict[str, str]] | None:
    sys.path.insert(0, str(root))
    try:
        sys.modules.pop("agent_template", None)
        sys.modules.pop("agent_template.tools", None)
        module = importlib.import_module("agent_template.tools")
        return [{"name": t["name"], "description": t["description"]} for t in module.TOOLS]
    except Exception:
        return None
    finally:
        sys.path.remove(str(root))


def check_platform(
    root: Path = DEFAULT_ROOT,
    tools: list[dict[str, str]] | None = None,
    tracked: list[str] | None = None,
    wheels: bool = False,
) -> list[Finding]:
    findings: list[Finding] = []

    def err(rule: str, code: str, message: str) -> None:
        findings.append(Finding(rule, "error", code, message))

    def warn(rule: str, code: str, message: str) -> None:
        findings.append(Finding(rule, "warn", code, message))

    def read_json(name: str, rule: str) -> Any:
        path = root / name
        if not path.exists():
            return None
        try:
            return json.loads(read(path))
        except ValueError as problem:
            err(rule, "invalid_json", f"{name} is not valid JSON: {problem}")
            return None

    manifest: dict[str, Any] | None = read_json("findagent.json", "a")
    dxt: dict[str, Any] | None = read_json("manifest.json", "a")
    registered = tools if tools is not None else load_registered_tools(root)
    git_files = tracked if tracked is not None else tracked_files(root)
    files = git_files if git_files is not None else [str(p.relative_to(root)).replace("\\", "/") for p in walk(root)]

    # (a) findagent.json -----------------------------------------------------------------------------
    if manifest is None:
        err(
            "a",
            "findagent_json_missing",
            "findagent.json is missing. A DXT manifest.json alone is replaced by a "
            "contract FindAgent guesses, and the hosts you declared are dropped.",
        )
    else:
        if manifest.get("schema_version") != "1.2":
            err(
                "a",
                "schema_version",
                f'schema_version must be "1.2" (found {json.dumps(manifest.get("schema_version"))}).',
            )
        if manifest.get("kind") != "code-bundle":
            err("a", "kind", f'kind must be "code-bundle" (found {json.dumps(manifest.get("kind"))}).')
        name = manifest.get("name")
        if not isinstance(name, str) or not 3 <= len(name) <= 80:
            err("a", "name", "name must be a string of 3 to 80 characters.")
        entrypoint = manifest.get("entrypoint")
        if not isinstance(entrypoint, dict) or not isinstance(entrypoint.get("path"), str):
            err("a", "entrypoint", "entrypoint.path is required.")
        runtime = manifest.get("runtime")
        if not isinstance(runtime, dict) or runtime.get("kind") not in {"node", "python"}:
            err("a", "runtime", 'runtime.kind must be "node" or "python".')
        mcp = manifest.get("mcp")
        if not isinstance(mcp, dict) or mcp.get("mode") not in {"native", "wrap"}:
            err("a", "mcp", 'mcp.mode must be "native" or "wrap".')
        elif mcp["mode"] == "native" and not isinstance(mcp.get("command"), str):
            err("a", "mcp", "a native MCP server needs mcp.command.")

        raw_skills = manifest.get("skills")
        skills: list[Any] = raw_skills if isinstance(raw_skills, list) else []
        if not skills:
            err(
                "a",
                "skills_empty",
                "skills[] is empty: the agent would be served with an empty tool list. "
                "List every tool with id, name and description.",
            )
        for skill in skills:
            if not (
                isinstance(skill, dict)
                and isinstance(skill.get("id"), str)
                and isinstance(skill.get("name"), str)
                and isinstance(skill.get("description"), str)
                and skill["description"].strip()
            ):
                err(
                    "a",
                    "skill_incomplete",
                    "every skills[] entry needs id, name and description "
                    f"(offender: {json.dumps(skill.get('id') if isinstance(skill, dict) else skill)}).",
                )
            elif skill["id"] != skill["name"]:
                err(
                    "a",
                    "skill_id_mismatch",
                    f"skills[] entry {skill['id']} must have id equal to name (found name {skill['name']}).",
                )
        if registered is None:
            err(
                "a",
                "tools_unreadable",
                "The registered tool list could not be read (does `import agent_template.tools` work?).",
            )
        else:
            have = {s.get("id") for s in skills if isinstance(s, dict)}
            for tool in registered:
                if tool["name"] not in have:
                    err(
                        "a",
                        "skills_missing_tool",
                        f"the server registers the tool {tool['name']} but skills[] does not list it.",
                    )
            real = {t["name"] for t in registered}
            for skill in skills:
                if isinstance(skill, dict) and skill.get("id") and skill["id"] not in real:
                    err(
                        "a", "skills_unknown_tool", f"skills[] lists {skill['id']}, which the server does not register."
                    )
            for skill in skills:
                match = next((t for t in registered if isinstance(skill, dict) and t["name"] == skill.get("id")), None)
                if match and skill.get("description") != match["description"]:
                    err(
                        "a",
                        "skill_description_drift",
                        f"skills[] description of {skill['id']} differs from the server's "
                        "(run python scripts/sync_manifest.py).",
                    )
        if dxt is not None:
            if not (dxt.get("dxt_version") and dxt.get("name") and dxt.get("server")):
                err("a", "dxt_incomplete", "manifest.json needs dxt_version, name and server.")
            if dxt.get("version") != manifest.get("version"):
                err(
                    "a",
                    "dxt_version_drift",
                    f"manifest.json version {dxt.get('version')} differs from "
                    f"findagent.json {manifest.get('version')}.",
                )
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            match_version = re.search(r'^version\s*=\s*"([^"]+)"', read(pyproject), flags=re.MULTILINE)
            if match_version and manifest.get("version") != match_version.group(1):
                err(
                    "a",
                    "version_drift",
                    f"findagent.json version {manifest.get('version')} differs from "
                    f"pyproject.toml {match_version.group(1)} (run python scripts/sync_manifest.py).",
                )

    # (b) listing text -------------------------------------------------------------------------------
    if manifest is not None:
        description = manifest.get("description")
        if not isinstance(description, str) or len(description.strip()) < 40:
            err("b", "description", "description must be a real paragraph (at least 40 characters).")
        elif len(description) > 4000:
            err("b", "description", "description is longer than 4000 characters.")
        tagline = manifest.get("tagline")
        if not isinstance(tagline, str) or not tagline.strip():
            err("b", "tagline", "tagline is required (one line, at most 140 characters).")
        elif len(tagline) > 140:
            err("b", "tagline", f"tagline is {len(tagline)} characters; the limit is 140.")
        prompts = manifest.get("example_prompts")
        if not isinstance(prompts, list) or not 1 <= len(prompts) <= 5:
            err(
                "b",
                "example_prompts",
                "example_prompts needs between 1 and 5 prompts: submitting is refused without them.",
            )
        else:
            for prompt in prompts:
                if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 500:
                    err(
                        "b",
                        "example_prompts",
                        "every example prompt must be a non-empty string of at most 500 characters.",
                    )
        tags = manifest.get("tags")
        if not isinstance(tags, list) or not 1 <= len(tags) <= 16:
            err("b", "tags", "tags needs between 1 and 16 entries.")

    # (c) category hints -----------------------------------------------------------------------------
    if manifest is not None and isinstance(manifest.get("tags"), list):
        for tag in manifest["tags"]:
            if not isinstance(tag, str) or not SLUG.match(tag) or len(tag) > 40:
                err(
                    "c",
                    "tag_shape",
                    f"tag {json.dumps(tag)} must be a lowercase slug (a-z, 0-9, single dashes), at most 40 characters.",
                )
                continue
            for word in words(tag):
                if word in MISLEADING:
                    err(
                        "c",
                        "tag_misleads",
                        f'tag {json.dumps(tag)} contains "{word}", which the auto-categoriser reads as '
                        f"{MISLEADING[word]}. Name the discipline instead.",
                    )
        if DISCIPLINE_TAG not in manifest["tags"]:
            err(
                "c",
                "tag_discipline_missing",
                f'tags must include "{DISCIPLINE_TAG}": a code agent is filed under that '
                "discipline, and saying so explicitly keeps the categoriser from guessing.",
            )
        for field in ("name", "tagline", "description"):
            hits = sorted({w for w in words(manifest.get(field, "")) if w in MISLEADING})
            if hits:
                groups = ", ".join(sorted({MISLEADING[w] for w in hits}))
                warn(
                    "c",
                    "text_misleads",
                    f"{field} contains {', '.join(chr(34) + w + chr(34) for w in hits)}, which the "
                    f"auto-categoriser reads as another category ({groups}). Reword it if the guess is wrong.",
                )

    # (d) panel --------------------------------------------------------------------------------------
    ui = manifest.get("ui") if manifest else None
    if ui:
        ui_path = ui.get("path") if isinstance(ui, dict) else None
        if not isinstance(ui_path, str) or not SAFE_REL_PATH.match(ui_path) or ".." in ui_path:
            err("d", "ui_path", "ui.path must be a safe relative path.")
        elif not (root / ui_path).exists():
            err(
                "d",
                "ui_missing",
                f"ui.path points at {ui_path}, which does not exist. The panel must be PREBUILT and "
                "committed: the sandbox only installs Python packages and has no step that could build it.",
            )
        else:
            html = read(root / ui_path)
            if len(html.encode()) > MAX_PANEL_BYTES:
                err("d", "ui_size", f"the panel is larger than {MAX_PANEL_BYTES} bytes.")
            if not re.search(r"<html[\s>]", html, flags=re.IGNORECASE):
                err("d", "ui_not_html", "the panel is not an HTML document.")
            if PANEL_CALLS_A_TOOL.search(html):
                err(
                    "d",
                    "ui_calls_tools",
                    "the panel asks the host to call a tool (tools/call, callServerTool or .callTool). "
                    "A creator's panel may not: send the answer to the conversation with ui/message instead.",
                )
            if re.search(
                r"""<script[^>]+\bsrc=|<link\b|<img\b|<iframe\b|@import|url\(\s*["']?(?!data:)""",
                html,
                flags=re.IGNORECASE,
            ):
                err(
                    "d",
                    "ui_external",
                    "the panel loads something that is not inside the document (script src, link, img, "
                    "iframe, @import or url()). It must be one self-contained file.",
                )
            if re.search(r"https?://", html, flags=re.IGNORECASE):
                err(
                    "d",
                    "ui_url",
                    "the panel contains an http(s) URL. The sandbox is closed and the platform rejects "
                    "references to other origins.",
                )
            if re.search(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b", html):
                err("d", "ui_network", "the panel uses the network. Its data arrives in the tool result.")
            if "prefers-color-scheme" not in html:
                err("d", "ui_theme", "the panel has no prefers-color-scheme rule: it must work in light and dark.")
            if 'name="viewport"' not in html:
                err("d", "ui_viewport", "the panel has no viewport meta, so it will not fit a phone.")
        server_src = ""
        for relative in ("agent_template/mcp_server.py", "agent_template/tools.py"):
            if (root / relative).exists():
                server_src += strip_comments(read(root / relative)) + "\n"
        if re.search(r"""["']domain["']\s*:""", server_src):
            err(
                "d",
                "ui_domain",
                "the panel resource sets a domain. Leave `ui.domain` unset: the host assigns its own "
                "sandbox domain and rejects any other.",
            )
        if server_src:
            if not re.search(r"""["']visibility["']\s*:\s*\[\s*["']model["']\s*\]""", server_src):
                err("d", "ui_visibility", 'the tool binding must set ui.visibility to ["model"].')
            if not re.search(r"""["']openai/widgetAccessible["']\s*:\s*False""", server_src):
                err("d", "ui_widget_accessible", 'the tool binding must set "openai/widgetAccessible": False.')

    # (e) the build passes on the sandbox -----------------------------------------------------------
    requirements = root / "requirements.txt"
    if not requirements.exists():
        err(
            "e",
            "requirements_missing",
            "requirements.txt is missing. The sandbox runs `pip install -r requirements.txt` and "
            "nothing else: without it your dependencies are not installed.",
        )
    else:
        pins: list[str] = []
        for number, raw in enumerate(read(requirements).split("\n"), start=1):
            line = raw.split(" #")[0].strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("-", "git+", ".", "/")) or "://" in line or " @ " in line:
                err(
                    "e",
                    "requirement_unsafe",
                    f"requirements.txt line {number} ({line}) is an option, a URL or a path. "
                    "Only exact pins from PyPI are allowed.",
                )
            elif not PIN.match(line):
                err(
                    "e",
                    "requirement_not_pinned",
                    f"requirements.txt line {number} ({line}) is not an exact pin (name==1.2.3). "
                    "A range resolves differently tomorrow.",
                )
            else:
                pins.append(line)
        if wheels and pins:
            err_codes = check_wheels(pins)
            for line in err_codes:
                err(
                    "e",
                    "no_binary_wheel",
                    f"{line} has no binary wheel for the sandbox (Linux, Python 3.13). "
                    "The sandbox does not compile: pick a version that ships a wheel or drop the dependency.",
                )
    for other in OTHER_LOCKFILES:
        if (root / other).exists() or other in files:
            err("e", "second_lockfile", f"{other} exists next to requirements.txt. One package manager only.")
    for ignored in IGNORED_LOCKFILES:
        if (root / ignored).exists():
            warn(
                "e",
                "lockfile_ignored",
                f"{ignored} is not read by the sandbox: only requirements.txt decides what is installed.",
            )
    gitignore = read(root / ".gitignore") if (root / ".gitignore").exists() else ""
    for needed in (".venv", ".findagent_pydeps"):
        if needed not in gitignore:
            err(
                "e",
                "gitignore_missing",
                f"{needed} is not in .gitignore: the local environment and the vendored "
                "dependencies must never be committed.",
            )
    for tracked_name in files:
        if tracked_name.startswith("%") or "__pycache__" in tracked_name or tracked_name.endswith(".pyc"):
            err(
                "e",
                "stray_file",
                f"{tracked_name} is tracked. It is a system path or build cache committed by mistake.",
            )
        if tracked_name.startswith((".venv/", ".findagent_pydeps/")):
            err(
                "e",
                "stray_file",
                f"{tracked_name} is tracked: dependencies are installed by the sandbox, not committed.",
            )

    if manifest is not None:
        build_command = manifest.get("build_command")
        if isinstance(build_command, str) and re.search(r"\b(npm|pnpm|yarn|bun)\b", build_command):
            err("e", "build_wrong_manager", "build_command uses a JavaScript package manager in a Python agent.")
        entry = (manifest.get("entrypoint") or {}).get("path") if isinstance(manifest.get("entrypoint"), dict) else None
        if isinstance(entry, str):
            if not SAFE_REL_PATH.match(entry) or ".." in entry or entry.startswith("/"):
                err("e", "entrypoint_unsafe", "entrypoint.path must be a relative path with no .. segments.")
            elif not (root / entry).exists():
                err("e", "entrypoint_missing", f"entrypoint.path {entry} does not exist in the repository root.")
        runtime = manifest.get("runtime")
        if isinstance(runtime, dict) and runtime.get("kind") == "python" and str(runtime.get("version")) != "3.13":
            err(
                "e",
                "runtime_version",
                f"runtime.version {runtime.get('version')} is not 3.13, the only Python the sandbox runs.",
            )
        if isinstance(runtime, dict) and runtime.get("kind") == "node":
            err("e", "runtime_mismatch", "this is the Python checker but findagent.json declares a node runtime.")

    for source in python_sources(root):
        relative = str(source.relative_to(root)).replace("\\", "/")
        text = read(source)
        try:
            tree = ast.parse(text)
        except SyntaxError as problem:
            err("e", "syntax_error", f"{relative} does not compile: {problem}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = node.func
                if isinstance(target, ast.Name) and target.id == "print":
                    err(
                        "e",
                        "stdout_print",
                        f"{relative}:{node.lineno} calls print(). stdout belongs to the MCP stream and a "
                        "stray line corrupts it: log to stderr.",
                    )
                if isinstance(target, ast.Attribute) and target.attr in {"write", "flush"}:
                    base = target.value
                    if (
                        isinstance(base, ast.Attribute)
                        and base.attr == "stdout"
                        and isinstance(base.value, ast.Name)
                        and base.value.id == "sys"
                    ):
                        err(
                            "e",
                            "stdout_print",
                            f"{relative}:{node.lineno} writes to sys.stdout, which belongs to the MCP stream.",
                        )
                if isinstance(target, ast.Name) and target.id == "open" and node.args:
                    first = node.args[0]
                    if (
                        isinstance(first, ast.Constant)
                        and isinstance(first.value, str)
                        and (
                            first.value.startswith(("/", "~"))
                            or ".." in first.value
                            or re.match(r"^[A-Za-z]:[\\/]", first.value)
                        )
                    ):
                        err(
                            "e",
                            "file_outside_repo",
                            f"{relative}:{node.lineno} opens {first.value!r}, outside the repository. "
                            "The sandbox bundle is the only filesystem you can rely on.",
                        )
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and re.match(r"^(/(etc|home|root|usr|var|tmp)/|~/|[A-Za-z]:[\\/])", node.value)
            ):
                err(
                    "e",
                    "file_outside_repo",
                    f"{relative}:{node.lineno} names the path {node.value!r}, outside the repository.",
                )

    for path in walk(root):
        relative = str(path.relative_to(root)).replace("\\", "/")
        if path.suffix in {".png", ".jpg", ".ico", ".gif", ".pyc"} or relative == "requirements.txt":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for shape in SECRET_SHAPES:
            if shape.search(text):
                err(
                    "e",
                    "secret_shape",
                    f"{relative} contains something shaped like a secret or a private key. The submission "
                    "scan refuses it; remove it, and if it was real, rotate it.",
                )
        if re.match(r"^\.env(\.|$)", path.name) and relative != ".env.example":
            err("e", "env_file", f"{relative} is an environment file. Never commit one.")

    # (f) egress and credentials ---------------------------------------------------------------------
    if manifest is not None:
        hosts = manifest.get("allowed_hosts")
        if not isinstance(hosts, list):
            err(
                "f",
                "allowed_hosts_missing",
                "allowed_hosts must be a list (it may be empty only if the code calls nothing).",
            )
        else:
            for host in hosts:
                if not isinstance(host, str) or not HOSTNAME.match(host) or IPV4.match(host):
                    err(
                        "f",
                        "allowed_host_shape",
                        f"allowed_hosts entry {json.dumps(host)} must be a plain host name: no scheme, "
                        "path, port, wildcard or IP address.",
                    )
            called: set[str] = set()
            for source in python_sources(root):
                text = strip_comments(read(source))
                called.update(m.lower() for m in re.findall(r"https?://([a-z0-9.-]+)", text, flags=re.IGNORECASE))
                called.update(
                    m.lower() for m in re.findall(r"""_HOST\s*=\s*["']([a-z0-9.-]+)["']""", text, flags=re.IGNORECASE)
                )
            for host in sorted(called):
                if host not in hosts:
                    err(
                        "f",
                        "host_not_declared",
                        f"the code calls {host}, which is not in allowed_hosts. The sandbox refuses "
                        "every host that is not listed.",
                    )
            for host in hosts:
                if host not in called:
                    err(
                        "f",
                        "host_not_called",
                        f"allowed_hosts lists {host}, which the code never calls. Declare only what you call.",
                    )

        slots = manifest.get("credential_slots")
        slot_envs: set[str] = set()
        if slots is not None:
            if not isinstance(slots, list) or not slots:
                err(
                    "f",
                    "slots_empty",
                    "credential_slots is present but empty. If the agent needs no secret, leave the field "
                    "out: do not add an optional slot for later.",
                )
            else:
                for slot in slots:
                    where = f"credential_slots[{json.dumps(slot.get('ref') if isinstance(slot, dict) else None)}]"
                    if not isinstance(slot, dict):
                        err("f", "slot_shape", "a credential slot must be an object.")
                        continue
                    for key in slot:
                        if key not in SLOT_KEYS:
                            err(
                                "f",
                                "slot_unknown_key",
                                f'{where} has the key "{key}". A slot is a declaration (ref, label, hosts, '
                                "required ...); it never holds a value.",
                            )
                    ref = slot.get("ref")
                    if not isinstance(ref, str) or ref == "" or ref in PROTOTYPE_NAMES:
                        err(
                            "f", "slot_ref", f"{where}: ref must be a non-empty string and not an object property name."
                        )
                    label = slot.get("label")
                    if not isinstance(label, str) or not label.strip():
                        err("f", "slot_label", f"{where}: label is required.")
                    if not isinstance(slot.get("required"), bool):
                        err("f", "slot_required", f"{where}: required must be true or false, stated explicitly.")
                    slot_hosts = slot.get("allowed_hosts")
                    fixed = isinstance(slot_hosts, list) and len(slot_hosts) > 0
                    if slot.get("install_host") is True:
                        if fixed:
                            err(
                                "f",
                                "slot_two_audiences",
                                f"{where}: install_host is true, so allowed_hosts must be empty "
                                "(the buyer supplies the host).",
                            )
                    elif not fixed:
                        err(
                            "f",
                            "slot_no_audience",
                            f"{where}: a secret needs a destination. Give allowed_hosts (one vendor, known "
                            "now) or install_host: true (an address the buyer owns).",
                        )
                    else:
                        assert isinstance(slot_hosts, list)
                        for host in slot_hosts:
                            if not isinstance(host, str) or not HOSTNAME.match(host) or IPV4.match(host):
                                err("f", "slot_host_shape", f"{where}: {json.dumps(host)} must be a plain host name.")
                            elif isinstance(hosts, list) and host not in hosts:
                                err(
                                    "f",
                                    "slot_host_unreachable",
                                    f"{where}: {host} is not in the top-level allowed_hosts, so the "
                                    "sandbox would refuse the request that carries the secret.",
                                )
                    if isinstance(slot.get("env"), str):
                        slot_envs.add(slot["env"])
                    for key, value in slot.items():
                        if isinstance(value, str) and any(shape.search(value) for shape in SECRET_SHAPES):
                            err(
                                "f",
                                "slot_holds_secret",
                                f"{where}.{key} looks like a real secret. A slot is a declaration, never a value.",
                            )
        for source in python_sources(root):
            text = strip_comments(read(source))
            for env_name in CREDENTIAL_ENV.findall(text):
                if env_name not in slot_envs:
                    err(
                        "f",
                        "credential_not_declared",
                        f"{str(source.relative_to(root)).replace(chr(92), '/')} reads {env_name}, which "
                        f'looks like a credential, but no credential_slots entry has env "{env_name}". '
                        "The buyer would never be asked for it.",
                    )

    return findings


def check_wheels(pins: Iterable[str]) -> list[str]:
    """Pins that have no binary wheel for the sandbox. Asks pip, so it needs the network."""
    missing: list[str] = []
    for pin in pins:
        with tempfile.TemporaryDirectory() as scratch:
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "download",
                    "--no-deps",
                    "--only-binary=:all:",
                    "--platform",
                    "manylinux2014_x86_64",
                    "--platform",
                    "manylinux_2_28_x86_64",
                    "--platform",
                    "any",
                    "--python-version",
                    "3.13",
                    "--implementation",
                    "cp",
                    "--dest",
                    scratch,
                    pin,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        if run.returncode != 0:
            missing.append(pin)
    return missing


def main(argv: list[str]) -> int:
    def option(name: str) -> str | None:
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None

    root = Path(option("--root") or DEFAULT_ROOT).resolve()
    tools_file = option("--tools")
    tracked_file = option("--tracked")
    tools = json.loads(Path(tools_file).read_text(encoding="utf-8")) if tools_file else None
    tracked = json.loads(Path(tracked_file).read_text(encoding="utf-8")) if tracked_file else None
    findings = check_platform(root, tools, tracked, wheels="--wheels" in argv)
    errors = [f for f in findings if f.level == "error"]
    if "--json" in argv:
        sys.stdout.write(json.dumps([f.to_dict() for f in findings]) + "\n")
        return 1 if errors else 0
    for finding in findings:
        label = "ERROR" if finding.level == "error" else "warn "
        sys.stdout.write(f"{label} ({finding.rule}) {finding.code}: {finding.message}\n")
    if not errors:
        extra = f", {len(findings)} warning(s)" if findings else ""
        sys.stdout.write(f"check_platform ok (rules a-f{extra})\n")
        return 0
    sys.stderr.write(f"check_platform failed: {len(errors)} error(s)\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
