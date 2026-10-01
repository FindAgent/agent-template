/**
 * A fake MCP Apps host, so the result panel is measured in a real browser the way a host runs it.
 *
 * jsdom does no layout, so a panel that overflows a 390px phone, a height that never shrinks, or a
 * dark/light palette that does not apply only exist once a browser lays the page out. What this
 * host does:
 * - answers `ui/initialize` and, once the panel says it is initialized, pushes the tool result;
 * - RESIZES THE IFRAME to every `ui/notifications/size-changed`, shrinking included;
 * - answers `ui/message` from a switch the test controls (accept or refuse), and logs every
 *   message in both directions so a test can assert what a control actually asked for;
 * - runs the panel in the strict `allow-scripts allow-forms` sandbox, with no same-origin access.
 */

import { chromium, type Browser, type Frame, type Page } from "@playwright/test";

export interface HostOptions {
  /** The `ui/notifications/tool-result` params: `{ structuredContent, content, isError }`. */
  toolResult?: Record<string, unknown>;
  /** Whether the host takes `ui/message`. Default true. */
  acceptMessages?: boolean;
  width?: number;
  height?: number;
  colorScheme?: "light" | "dark";
  hostCapabilities?: Record<string, unknown>;
}

export interface HostMessage {
  dir: "in" | "out";
  method?: string;
  id?: number | string;
  params?: unknown;
}

export interface MountedPanel {
  page: Page;
  frame: Frame;
  sizes(): Promise<Array<{ width: number; height: number }>>;
  frameHeight(): Promise<number>;
  contentHeight(): Promise<number>;
  messages(): Promise<HostMessage[]>;
  consoleErrors: string[];
  settle(quietMs?: number): Promise<void>;
  close(): Promise<void>;
}

const HOST_HTML = `<!doctype html><html><head><meta charset="utf-8"><style>
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
</script></body></html>`;

let browser: Browser | null = null;

export async function openBrowser(): Promise<Browser> {
  if (!browser) {
    try {
      browser = await chromium.launch();
    } catch (e) {
      const msg = (e as Error).message;
      const missing = /Executable doesn't exist|playwright install/i.test(msg);
      throw new Error(
        missing
          ? `The panel tests drive a real Chromium and none is installed. Run: npx playwright install chromium\n${msg}`
          : `Chromium is installed but did not start for the panel tests:\n${msg}`,
      );
    }
  }
  return browser;
}

export async function closeBrowser(): Promise<void> {
  await browser?.close();
  browser = null;
}

export async function mountPanel(html: string, opts: HostOptions = {}): Promise<MountedPanel> {
  const b = await openBrowser();
  const context = await b.newContext({
    viewport: { width: opts.width ?? 720, height: opts.height ?? 900 },
    colorScheme: opts.colorScheme ?? "dark",
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(6000);
  const consoleErrors: string[] = [];
  page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(`console: ${m.text()}`);
  });

  await page.setContent(HOST_HTML);
  await page.evaluate(
    ([c, h]) => (window as unknown as { __mount(c: unknown, h: string): void }).__mount(c, h),
    [
      {
        toolResult: opts.toolResult ?? null,
        acceptMessages: opts.acceptMessages ?? true,
        hostCapabilities: opts.hostCapabilities ?? { message: {}, openLinks: {} },
      },
      html,
    ] as const,
  );

  const frame = await waitForFrame(page);
  const panel: MountedPanel = {
    page,
    frame,
    consoleErrors,
    sizes: () => page.evaluate(() => (window as unknown as { __sizes: never }).__sizes),
    frameHeight: () =>
      page.evaluate(() => Math.round(document.getElementById("p")!.getBoundingClientRect().height)),
    contentHeight: () =>
      frame.evaluate(() => Math.ceil(document.body.getBoundingClientRect().height)),
    messages: () => page.evaluate(() => (window as unknown as { __log: never }).__log),
    settle: (quietMs = 250) => settle(page, quietMs),
    close: async () => {
      await page.close();
      await context.close();
    },
  };
  await panel.settle();
  return panel;
}

async function waitForFrame(page: Page): Promise<Frame> {
  for (let i = 0; i < 100; i++) {
    const f = page.frames().find((fr) => fr !== page.mainFrame());
    if (f) {
      await f.waitForLoadState("load");
      return f;
    }
    await page.waitForTimeout(20);
  }
  throw new Error("panel iframe never appeared");
}

async function settle(page: Page, quietMs: number): Promise<void> {
  const deadline = Date.now() + 5000;
  await page.waitForTimeout(quietMs);
  while (Date.now() < deadline) {
    const idle = await page.evaluate(
      (q) => performance.now() - (window as unknown as { __lastSizeAt: number }).__lastSizeAt >= q,
      quietMs,
    );
    if (idle) return;
    await page.waitForTimeout(50);
  }
}
