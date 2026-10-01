"""The result panel, run for real: parsed, then rendered in headless Chromium inside a fake MCP Apps host
that resizes the frame the way real hosts do. Fixtures are the actual output of the check over the
httpx test double, pushed through the same wire mapping the server uses.

jsdom-style checks cannot see a panel that overflows a 390px phone, a height that never shrinks, or a
palette that does not apply in dark mode: those only exist once a browser lays the page out. Needs a
Chromium: `python -m playwright install chromium`.

Screenshots are written only when PANEL_SHOTS=1 (docs/screenshots), so a normal run leaves the tree clean.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Error, Frame, Page, sync_playwright

from agent_template.check import check_crate
from agent_template.mcp_server import to_call_tool_result
from agent_template.tools import dispatch_tool

from .conftest import NOW, TEST_CONFIG, Fake, Reply, crate_doc, routes_for

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
TAKE_SHOTS = os.environ.get("PANEL_SHOTS") == "1"

HOST_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0}
iframe{display:block;width:100%;border:0;height:var(--h)}
</style></head><body><iframe id="p" sandbox="allow-scripts allow-forms"></iframe>
<script>
window.__log = []; window.__sizes = []; window.__lastSizeAt = 0;
var cfg = null, frame = document.getElementById('p');
function reply(id, result, error) {
  var msg = { jsonrpc: '2.0', id: id };
  if (error) msg.error = error; else msg.result = result;
  window.__log.push({ dir: 'out', id: id, params: error ? { error: error } : result });
  frame.contentWindow.postMessage(msg, '*');
}
function push(method, params) {
  window.__log.push({ dir: 'out', method: method, params: params });
  frame.contentWindow.postMessage({ jsonrpc: '2.0', method: method, params: params }, '*');
}
window.addEventListener('message', function (ev) {
  if (ev.source !== frame.contentWindow) return;
  var m = ev.data; if (!m || typeof m !== 'object') return;
  window.__log.push({ dir: 'in', method: m.method, id: m.id, params: m.params });
  if (m.method === 'ui/initialize') {
    reply(m.id, { protocolVersion: '2026-01-26', hostInfo: { name: 'template-harness', version: '1' },
      hostCapabilities: cfg.hostCapabilities, hostContext: { theme: 'light', displayMode: 'inline' } });
    return;
  }
  if (m.method === 'ui/notifications/initialized') {
    if (cfg.toolResult) push('ui/notifications/tool-result', cfg.toolResult);
    return;
  }
  if (m.method === 'ui/notifications/size-changed') {
    var h = Math.round(Number(m.params && m.params.height) || 0);
    window.__sizes.push({ width: Number(m.params && m.params.width) || 0, height: h });
    window.__lastSizeAt = performance.now();
    if (h > 0) frame.style.setProperty('--h', h + 'px');
    return;
  }
  if (m.id != null && m.method === 'ui/message') {
    if (cfg.acceptMessages) reply(m.id, {});
    else reply(m.id, null, { code: -32000, message: 'host refuses messages' });
    return;
  }
  if (m.id != null) reply(m.id, null, { code: -32601, message: 'unhandled: ' + m.method });
});
window.__mount = function (c, html) {
  cfg = c; frame.style.setProperty('--h', '120px');
  frame.srcdoc = html;
};
</script></body></html>"""

WIRE_FRAME_MESSAGE = """(next) => {
  window.dispatchEvent(new MessageEvent("message", {
    data: { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: next },
    source: %s,
  }));
}"""


@dataclass
class Mounted:
    page: Page
    frame: Frame
    console_errors: list[str]

    def sizes(self) -> list[dict[str, int]]:
        return self.page.evaluate("window.__sizes")  # type: ignore[no-any-return]

    def frame_height(self) -> int:
        return self.page.evaluate("Math.round(document.getElementById('p').getBoundingClientRect().height)")  # type: ignore[no-any-return]

    def content_height(self) -> int:
        return self.frame.evaluate("Math.ceil(document.body.getBoundingClientRect().height)")  # type: ignore[no-any-return]

    def messages(self) -> list[dict[str, Any]]:
        return self.page.evaluate("window.__log")  # type: ignore[no-any-return]

    def text(self) -> str:
        return self.frame.evaluate("document.body.innerText")  # type: ignore[no-any-return]

    def settle(self, quiet_ms: int = 250) -> None:
        self.page.wait_for_timeout(quiet_ms)
        for _ in range(100):
            idle = self.page.evaluate("(q) => performance.now() - window.__lastSizeAt >= q", quiet_ms)
            if idle:
                return
            self.page.wait_for_timeout(50)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as pw:
        try:
            launched = pw.chromium.launch()
        except Error as problem:
            missing = "Executable doesn't exist" in str(problem) or "playwright install" in str(problem)
            hint = (
                "The panel tests drive a real Chromium and none is installed. "
                "Run: python -m playwright install chromium"
                if missing
                else "Chromium is installed but did not start for the panel tests."
            )
            raise RuntimeError(f"{hint}\n{problem}") from problem
        yield launched
        launched.close()


@contextmanager
def mount(
    browser: Browser,
    tool_result: dict[str, Any] | None,
    *,
    width: int = 720,
    scheme: str = "dark",
    accept_messages: bool = True,
) -> Iterator[Mounted]:
    context = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme)  # type: ignore[arg-type]
    page = context.new_page()
    page.set_default_timeout(6000)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
    page.set_content(HOST_HTML)
    page.evaluate(
        "([c, h]) => window.__mount(c, h)",
        [
            {
                "toolResult": tool_result,
                "acceptMessages": accept_messages,
                "hostCapabilities": {"message": {}, "openLinks": {}},
            },
            HTML,
        ],
    )
    frame: Frame | None = None
    for _ in range(100):
        frame = next((f for f in page.frames if f != page.main_frame), None)
        if frame:
            frame.wait_for_load_state("load")
            break
        page.wait_for_timeout(20)
    assert frame is not None, "panel iframe never appeared"
    mounted = Mounted(page, frame, errors)
    mounted.settle()
    try:
        yield mounted
    finally:
        context.close()


# ---- fixtures: the real output of the check, over the test double --------------------------------------


async def run_check(name: str, fake: Fake) -> dict[str, Any]:
    return await check_crate(name, client=fake.client, config=TEST_CONFIG, now=lambda: NOW)


def wire(result: dict[str, Any]) -> dict[str, Any]:
    return to_call_tool_result(result).model_dump(mode="json", exclude_none=True)


async def _build_fixtures() -> dict[str, dict[str, Any]]:
    healthy = await run_check("acme-widget", Fake(routes_for("acme-widget", crate_doc())))
    risky = await run_check(
        "old-thing",
        Fake(
            routes_for(
                "old-thing",
                crate_doc(
                    name="old-thing",
                    yanked=True,
                    yank_message="use new-thing",
                    published_days_ago=3000,
                    license=None,
                    repository=None,
                ),
                Reply(status=503),
            )
        ),
    )
    failure = await run_check("ghost", Fake({"crates.io/api/v1/crates/ghost": Reply(404)}))
    limited = await run_check(
        "busy", Fake({"crates.io/api/v1/crates/busy": Reply(429, headers={"retry-after": "600"})})
    )
    noop = Fake({})
    return {
        "healthy": wire(healthy),
        "risky": wire(risky),
        "failure": wire(failure),
        "rate_limited": wire(limited),
        "needs_input": wire(await dispatch_tool("open_form", {}, _unused(noop))),
        "capabilities": wire(await dispatch_tool("list_capabilities", {}, _unused(noop))),
        "text": {"content": [{"type": "text", "text": "Plain text from a tool."}]},
        "error_text": {"isError": True, "content": [{"type": "text", "text": "Unknown tool: nope"}]},
    }


def aio(coro: Any) -> Any:
    """Run a coroutine to completion on its own thread: sync Playwright owns this thread's event loop."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _unused(fake: Fake) -> Any:
    async def run_check_unused(crate: object, owners: bool) -> dict[str, Any]:
        raise AssertionError("an entry tool that needs no check must not run one")

    return run_check_unused


@pytest.fixture(scope="module")
def fixtures() -> dict[str, dict[str, Any]]:
    if TAKE_SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
    return aio(_build_fixtures())  # type: ignore[no-any-return]


KINDS = ["healthy", "risky", "failure", "rate_limited", "needs_input", "capabilities", "text", "error_text"]
VIEWPORTS = [("phone", 390), ("desktop", 1100)]
SCHEMES = ["dark", "light"]


# ---- the panel source ---------------------------------------------------------------------------------


def test_every_script_parses(browser: Browser) -> None:
    """Parsed by the browser's own engine: one bad escape kills the whole tag and the panel never renders."""
    scripts = re.findall(r"<script\b[^>]*>([\s\S]*?)</script>", HTML)
    assert scripts
    page = browser.new_page()
    try:
        for code in scripts:
            assert page.evaluate("(src) => { new Function(src); return true; }", code) is True
        with pytest.raises(Error):
            page.evaluate("(src) => { new Function(src); }", "var a = 'broken" + "\n" + "string';")
    finally:
        page.close()


def test_references_nothing_outside_the_document_and_never_reaches_the_network() -> None:
    for pattern in [
        r"<script[^>]+\bsrc=",
        r"<link\b",
        r"<img\b",
        r"<iframe\b",
        r"https?:",
        r"url\(",
        r"@import",
        r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b",
        r"\bimport\s*\(",
        r"\.innerHTML\s*=|insertAdjacentHTML|document\.write|\beval\(",
    ]:
        assert not re.search(pattern, HTML, flags=re.IGNORECASE), pattern


def test_never_asks_the_host_to_call_a_tool_and_sets_no_domain() -> None:
    assert "tools/call" not in HTML
    assert not re.search(r"\bdomain\b", HTML, flags=re.IGNORECASE)


def test_declares_light_and_dark_through_custom_properties() -> None:
    assert "prefers-color-scheme: light" in HTML
    assert 'name="color-scheme"' in HTML
    assert "width=device-width" in HTML


def test_ui_index_html_is_what_panel_builds() -> None:
    done = subprocess.run(
        [sys.executable, "scripts/build_panel.py", "--check"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr


# ---- rendering every kind, both sizes, both schemes ------------------------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("viewport", VIEWPORTS, ids=[v[0] for v in VIEWPORTS])
@pytest.mark.parametrize("kind", KINDS)
def test_renders_every_result_kind_at_both_sizes_in_both_color_schemes(
    browser: Browser, fixtures: dict[str, dict[str, Any]], kind: str, viewport: tuple[str, int], scheme: str
) -> None:
    name, width = viewport
    with mount(browser, fixtures[kind], width=width, scheme=scheme) as p:
        state = p.frame.evaluate(
            """() => ({ loading: !!document.getElementById("state"), text: document.body.innerText.length,
              scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth })"""
        )
        assert state["loading"] is False, "still on the loading state"
        assert state["text"] > 20
        assert state["scrollW"] <= state["clientW"] + 1, "horizontal overflow"
        assert state["clientW"] <= width
        assert p.console_errors == []
        assert len(p.sizes()) > 0
        assert abs(p.frame_height() - p.content_height()) <= 3
        if TAKE_SHOTS and kind in {"healthy", "risky", "rate_limited"}:
            p.page.screenshot(path=str(SHOTS / f"{kind}-{name}-{scheme}.png"), full_page=True)


# ---- what each view says ----------------------------------------------------------------------------------


def test_a_report_shows_the_verdict_every_signal_in_words_and_the_request_count(
    browser: Browser, fixtures: dict[str, dict[str, Any]]
) -> None:
    with mount(browser, fixtures["risky"], width=390) as p:
        text = p.text()
        assert "old-thing@" in text
        assert re.search(r"Risky", text)
        for label in ["Latest release age", "Yanked", "License", "Source repository", "Recent downloads", "Owners"]:
            assert label in text
        for word in ["Not checked", "Risk", "Warn"]:
            assert word in text
        assert re.search(r"using 2 of 2 allowed requests", text)


def test_a_failure_names_its_class_and_for_a_rate_limit_when_to_try_again(
    browser: Browser, fixtures: dict[str, dict[str, Any]]
) -> None:
    with mount(browser, fixtures["rate_limited"], width=390) as p:
        text = p.text()
        assert "Rate limited" in text
        assert re.search(r"Try again after 2026-10-01T12:10:00", text)
    with mount(browser, fixtures["failure"], width=390) as q:
        assert "Crate not found" in q.text()


def test_needs_input_is_read_only_it_lists_the_questions_and_offers_no_field(
    browser: Browser, fixtures: dict[str, dict[str, Any]]
) -> None:
    with mount(browser, fixtures["needs_input"], width=390) as p:
        assert p.frame.locator("input, textarea, select").count() == 0
        assert re.search(r"crate", p.text())


def test_a_plain_text_error_result_is_drawn_as_a_failure_not_as_working(
    browser: Browser, fixtures: dict[str, dict[str, Any]]
) -> None:
    with mount(browser, fixtures["error_text"], width=390) as p:
        text = p.text()
        assert "Unknown tool: nope" in text
        assert not re.search(r"Loading|Waiting", text)


def test_dark_and_light_actually_differ_inside_the_frame(browser: Browser, fixtures: dict[str, dict[str, Any]]) -> None:
    backgrounds = []
    for scheme in SCHEMES:
        with mount(browser, fixtures["healthy"], scheme=scheme) as p:
            backgrounds.append(p.frame.evaluate("getComputedStyle(document.body).backgroundColor"))
    assert backgrounds[0] != backgrounds[1]


# ---- interaction ------------------------------------------------------------------------------------------


def test_opening_a_signal_grows_the_frame_and_closing_it_shrinks_it_back(
    browser: Browser, fixtures: dict[str, dict[str, Any]]
) -> None:
    with mount(browser, fixtures["risky"], width=390) as p:
        summary = p.frame.locator(".pc-signals summary").first
        before = p.frame_height()
        summary.click()
        p.settle()
        assert p.frame_height() > before
        summary.click()
        p.settle()
        assert abs(p.frame_height() - before) <= 3
        assert p.console_errors == []


def test_a_signal_opens_and_closes_from_the_keyboard(browser: Browser, fixtures: dict[str, dict[str, Any]]) -> None:
    with mount(browser, fixtures["healthy"], width=390) as p:
        summary = p.frame.locator(".pc-signals summary").nth(1)
        details = p.frame.locator(".pc-signals details").nth(1)
        summary.focus()
        p.page.keyboard.press("Enter")
        assert details.evaluate("(d) => d.open") is True
        p.page.keyboard.press("Enter")
        assert details.evaluate("(d) => d.open") is False


def test_the_ask_button_posts_one_ui_message_and_never_a_tool_call(
    browser: Browser, fixtures: dict[str, dict[str, Any]]
) -> None:
    with mount(browser, fixtures["risky"], width=390) as p:
        p.frame.get_by_role("button", name=re.compile("Ask what to do")).click()
        p.settle()
        log = p.messages()
        sent = [m for m in log if m["dir"] == "in" and m.get("method") == "ui/message"]
        assert len(sent) == 1
        assert "old-thing" in json.dumps(sent[0]["params"])
        assert not any(m.get("method") == "tools/call" for m in log)
        assert re.search(r"Sent", p.text())


def test_a_host_that_refuses_the_message_gets_its_text_to_copy_and_no_false_sent(
    browser: Browser, fixtures: dict[str, dict[str, Any]]
) -> None:
    with mount(browser, fixtures["risky"], width=390, accept_messages=False) as p:
        p.frame.get_by_role("button", name=re.compile("Ask what to do")).click()
        p.settle()
        text = p.text()
        assert re.search(r"did not take the message", text)
        assert not re.search(r"Sent\. The assistant", text)
        assert "old-thing" in p.frame.locator(".pc-fallback").inner_text()


def test_a_second_result_replaces_the_first_and_leaves_no_status_behind(
    browser: Browser, fixtures: dict[str, dict[str, Any]]
) -> None:
    with mount(browser, fixtures["risky"], width=390) as p:
        p.frame.evaluate(WIRE_FRAME_MESSAGE % "window.parent", fixtures["failure"])
        p.settle()
        text = p.text()
        assert "Crate not found" in text
        assert "old-thing@" not in text


# ---- a result is data, never markup -------------------------------------------------------------------------


def test_html_in_a_yank_message_is_shown_as_text(browser: Browser) -> None:
    evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>'
    result = aio(
        run_check(
            "acme-widget",
            Fake(routes_for("acme-widget", crate_doc(yanked=True, yank_message=evil, published_days_ago=5))),
        )
    )
    with mount(browser, wire(result), width=390) as p:
        p.frame.locator(".pc-signals summary").nth(1).click()
        p.settle()
        assert p.frame.evaluate("window.__pwned") is None
        assert p.frame.locator(".pc-signals img, .pc-signals script").count() == 0
        assert "<img src=x" in p.text()
        assert p.console_errors == []


def test_only_the_hosts_window_may_deliver_a_result(browser: Browser, fixtures: dict[str, dict[str, Any]]) -> None:
    with mount(browser, fixtures["healthy"], width=390) as p:
        p.frame.evaluate(WIRE_FRAME_MESSAGE % "window", fixtures["failure"])
        p.settle()
        assert "acme-widget@" in p.text()
