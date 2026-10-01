"""Egress is default-deny on the platform: a host the code calls that is not in `allowed_hosts` is a
request the sandbox refuses at run time. These tests make the two sides agree before it ships, in both
directions: nothing is called that is not declared, and nothing is declared that is not called.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = sorted((ROOT / "agent_template").glob("*.py"))
DECLARED: list[str] = json.loads((ROOT / "findagent.json").read_text(encoding="utf-8"))["allowed_hosts"]
HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def code(path: Path) -> str:
    """Source with comments removed, so a host named in prose is not read as a host that is called."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return re.sub(r"(^|[^:\"'])#.*$", r"\1", text, flags=re.MULTILINE)


def hosts_called() -> list[str]:
    found: set[str] = set()
    for path in SRC:
        text = code(path)
        found.update(h.lower() for h in re.findall(r"https?://([a-z0-9.-]+)", text, flags=re.IGNORECASE))
        found.update(h.lower() for h in re.findall(r"""_HOST\s*=\s*["']([a-z0-9.-]+)["']""", text, flags=re.IGNORECASE))
    return sorted(found)


def test_allowed_hosts_is_exactly_the_set_of_hosts_the_source_calls() -> None:
    assert hosts_called() == sorted(DECLARED)


def test_allowed_hosts_holds_plain_host_names_not_a_scheme_path_port_wildcard_or_address() -> None:
    for host in DECLARED:
        assert HOSTNAME.match(host), host
        assert not re.match(r"^\d+\.\d+\.\d+\.\d+$", host), host


def test_allowed_hosts_is_not_empty_because_the_agent_does_call_out() -> None:
    assert DECLARED


def test_only_http_py_touches_the_network_and_only_through_one_function() -> None:
    sending = [p.name for p in SRC if re.search(r"\bclient\.(get|send|request|stream|post|put|delete)\(", code(p))]
    assert sending == ["http.py"], sending
    assert len(re.findall(r"client\.stream\(", code(ROOT / "agent_template" / "http.py"))) == 1


def test_no_url_is_built_from_a_tool_argument_without_going_through_the_name_check() -> None:
    crates = code(ROOT / "agent_template" / "crates.py")
    urls = re.findall(r"""f["'](https://[^"']*)["']""", crates)
    assert urls
    for url in urls:
        assert re.match(r"^https://\{[A-Z_]*HOST\}/", url), url
    assert "quote(" in crates


def test_redirects_are_never_followed_by_the_request_or_by_the_client() -> None:
    assert re.search(r"follow_redirects\s*=\s*False", code(ROOT / "agent_template" / "http.py"))
    assert re.search(r"AsyncClient\(follow_redirects\s*=\s*False", code(ROOT / "agent_template" / "mcp_server.py"))


def test_no_tool_takes_a_url_or_a_host_as_input() -> None:
    tools = code(ROOT / "agent_template" / "tools.py")
    assert not re.search(r"""["'](url|host|endpoint|base_?url)["']\s*:\s*\{""", tools, flags=re.IGNORECASE)
