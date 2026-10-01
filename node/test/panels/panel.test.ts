/**
 * The result panel, run for real: parsed, then rendered in headless Chromium inside a host that
 * resizes the frame the way MCP Apps hosts do. Fixtures are the actual output of the check over the
 * registry test double, pushed through the same wire mapping the server uses.
 *
 * Screenshots are written only when PANEL_SHOTS=1 (docs/screenshots), so a normal run leaves the
 * tree clean.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { checkCrate } from "../../src/check.js";
import { dispatchTool, toCallToolResult } from "../../src/mcp/tools.js";
import { TEST_CONFIG, NOW, crateDoc, fakeCrates, routesFor } from "../helpers/fakeCrates.js";
import { closeBrowser, mountPanel, type MountedPanel } from "./host-harness.js";

const ROOT = path.resolve(import.meta.dirname, "..", "..");
const SHOTS = path.join(ROOT, "docs", "screenshots");
const html = readFileSync(path.join(ROOT, "ui", "index.html"), "utf8");
const takeShots = process.env["PANEL_SHOTS"] === "1";

type Wire = ReturnType<typeof toCallToolResult>;
const fixtures: Record<string, Wire> = {};
const KINDS = [
  "healthy",
  "risky",
  "failure",
  "rate_limited",
  "needs_input",
  "capabilities",
  "text",
  "error_text",
];

const run = (name: string, fake: ReturnType<typeof fakeCrates>) =>
  checkCrate(name, { config: TEST_CONFIG, fetchImpl: fake.fetch, now: () => NOW });

beforeAll(async () => {
  fixtures["healthy"] = toCallToolResult(
    await run("acme-widget", fakeCrates(routesFor("acme-widget", crateDoc()))),
  );
  fixtures["risky"] = toCallToolResult(
    await run(
      "old-thing",
      fakeCrates(
        routesFor(
          "old-thing",
          crateDoc({
            name: "old-thing",
            yanked: true,
            yankMessage: "use new-thing",
            publishedDaysAgo: 3000,
            license: null,
            repository: null,
          }),
          { status: 503 },
        ),
      ),
    ),
  );
  fixtures["failure"] = toCallToolResult(
    await run("ghost", fakeCrates({ "crates.io/api/v1/crates/ghost": { status: 404 } })),
  );
  fixtures["rate_limited"] = toCallToolResult(
    await run(
      "busy",
      fakeCrates({
        "crates.io/api/v1/crates/busy": { status: 429, headers: { "retry-after": "600" } },
      }),
    ),
  );
  fixtures["needs_input"] = toCallToolResult(await dispatchTool("open_form", {}));
  fixtures["capabilities"] = toCallToolResult(await dispatchTool("list_capabilities", {}));
  fixtures["text"] = { content: [{ type: "text", text: "Plain text from a tool." }] };
  fixtures["error_text"] = {
    isError: true,
    content: [{ type: "text", text: "Unknown tool: nope" }],
  };
  if (takeShots) mkdirSync(SHOTS, { recursive: true });
}, 60_000);

afterAll(async () => {
  await closeBrowser();
});

describe("the panel source", () => {
  it("every script parses", () => {
    const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]!);
    expect(scripts.length).toBeGreaterThan(0);
    for (const code of scripts) expect(() => new vm.Script(code)).not.toThrow();
  });

  it("references nothing outside the document and never reaches the network", () => {
    expect(html).not.toMatch(/<script[^>]+\bsrc=/i);
    expect(html).not.toMatch(/<link\b/i);
    expect(html).not.toMatch(/<img\b/i);
    expect(html).not.toMatch(/<iframe\b/i);
    expect(html).not.toMatch(/https?:/i);
    expect(html).not.toMatch(/url\(/i);
    expect(html).not.toMatch(/@import/i);
    expect(html).not.toMatch(/\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b/);
    expect(html).not.toMatch(/\bimport\s*\(/);
    expect(html).not.toMatch(/\.innerHTML\s*=|insertAdjacentHTML|document\.write|\beval\(/);
  });

  it("never asks the host to call a tool, and sets no domain", () => {
    expect(html).not.toContain("tools/call");
    expect(html).not.toMatch(/\bdomain\b/i);
  });

  it("declares light and dark through custom properties", () => {
    expect(html).toContain("prefers-color-scheme: light");
    expect(html).toContain('name="color-scheme"');
    expect(html).toContain("width=device-width");
  });

  it("ui/index.html is what panel/ builds", () => {
    expect(() =>
      execFileSync("node", ["scripts/build-panel.mjs", "--check"], { cwd: ROOT, stdio: "pipe" }),
    ).not.toThrow();
  });
});

const VIEWPORTS = [
  { name: "phone", width: 390 },
  { name: "desktop", width: 1100 },
] as const;
const SCHEMES = ["dark", "light"] as const;

describe("renders every result kind at both sizes in both color schemes", () => {
  for (const kind of KINDS) {
    for (const vp of VIEWPORTS) {
      for (const scheme of SCHEMES) {
        it(`${kind} / ${vp.name} / ${scheme}`, async () => {
          const p = await mountPanel(html, {
            toolResult: fixtures[kind]!,
            width: vp.width,
            colorScheme: scheme,
          });
          try {
            await assertSound(p, vp.width);
            if (takeShots && ["healthy", "risky", "rate_limited"].includes(kind)) {
              await p.page.screenshot({
                path: path.join(SHOTS, `${kind}-${vp.name}-${scheme}.png`),
                fullPage: true,
              });
            }
          } finally {
            await p.close();
          }
        }, 30_000);
      }
    }
  }
});

async function assertSound(p: MountedPanel, width: number): Promise<void> {
  const state = await p.frame.evaluate(() => ({
    loading: !!document.getElementById("state"),
    text: document.body.innerText.length,
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
  }));
  expect(state.loading, "still on the loading state").toBe(false);
  expect(state.text).toBeGreaterThan(20);
  expect(state.scrollW, "horizontal overflow").toBeLessThanOrEqual(state.clientW + 1);
  expect(state.clientW).toBeLessThanOrEqual(width);
  expect(p.consoleErrors).toEqual([]);
  const sizes = await p.sizes();
  expect(sizes.length).toBeGreaterThan(0);
  expect(Math.abs((await p.frameHeight()) - (await p.contentHeight()))).toBeLessThanOrEqual(3);
}

describe("what each view says", () => {
  it("a report shows the verdict, every signal with its status in words, and the request count", async () => {
    const p = await mountPanel(html, { toolResult: fixtures["risky"]!, width: 390 });
    try {
      const text = await p.frame.evaluate(() => document.body.innerText);
      expect(text).toContain("old-thing@");
      expect(text).toMatch(/Risky/);
      for (const label of [
        "Latest release age",
        "Yanked",
        "License",
        "Source repository",
        "Recent downloads",
        "Owners",
      ]) {
        expect(text).toContain(label);
      }
      expect(text).toContain("Not checked");
      expect(text).toContain("Risk");
      expect(text).toContain("Warn");
      expect(text).toMatch(/using 2 of 2 allowed requests/);
    } finally {
      await p.close();
    }
  }, 30_000);

  it("a failure names its class and, for a rate limit, when to try again", async () => {
    const p = await mountPanel(html, { toolResult: fixtures["rate_limited"]!, width: 390 });
    try {
      const text = await p.frame.evaluate(() => document.body.innerText);
      expect(text).toContain("Rate limited");
      expect(text).toMatch(/Try again after 2026-10-01T12:10:00\.000Z/);
    } finally {
      await p.close();
    }
    const q = await mountPanel(html, { toolResult: fixtures["failure"]!, width: 390 });
    try {
      expect(await q.frame.evaluate(() => document.body.innerText)).toContain("Crate not found");
    } finally {
      await q.close();
    }
  }, 30_000);

  it("needs_input is read-only: it lists the questions and offers no field to type into", async () => {
    const p = await mountPanel(html, { toolResult: fixtures["needs_input"]!, width: 390 });
    try {
      expect(await p.frame.locator("input, textarea, select").count()).toBe(0);
      expect(await p.frame.evaluate(() => document.body.innerText)).toMatch(/crate/);
    } finally {
      await p.close();
    }
  }, 30_000);

  it("a plain-text error result is drawn as a failure, not as 'Working'", async () => {
    const p = await mountPanel(html, { toolResult: fixtures["error_text"]!, width: 390 });
    try {
      const text = await p.frame.evaluate(() => document.body.innerText);
      expect(text).toContain("Unknown tool: nope");
      expect(text).not.toMatch(/Loading|Waiting/);
    } finally {
      await p.close();
    }
  }, 30_000);
});

describe("theme", () => {
  it("dark and light actually differ inside the frame", async () => {
    const bgs: string[] = [];
    for (const scheme of SCHEMES) {
      const p = await mountPanel(html, { toolResult: fixtures["healthy"]!, colorScheme: scheme });
      bgs.push(await p.frame.evaluate(() => getComputedStyle(document.body).backgroundColor));
      await p.close();
    }
    expect(bgs[0]).not.toBe(bgs[1]);
  }, 30_000);
});

describe("interaction", () => {
  it("opening a signal grows the frame and closing it shrinks it back", async () => {
    const p = await mountPanel(html, { toolResult: fixtures["risky"]!, width: 390 });
    try {
      const summary = p.frame.locator(".pc-signals summary").first();
      const before = await p.frameHeight();
      await summary.click();
      await p.settle();
      expect(await p.frameHeight()).toBeGreaterThan(before);
      await summary.click();
      await p.settle();
      expect(Math.abs((await p.frameHeight()) - before)).toBeLessThanOrEqual(3);
      expect(p.consoleErrors).toEqual([]);
    } finally {
      await p.close();
    }
  }, 30_000);

  it("a signal opens and closes from the keyboard", async () => {
    const p = await mountPanel(html, { toolResult: fixtures["healthy"]!, width: 390 });
    try {
      const summary = p.frame.locator(".pc-signals summary").nth(1);
      const details = p.frame.locator(".pc-signals details").nth(1);
      await summary.focus();
      await p.page.keyboard.press("Enter");
      expect(await details.evaluate((d) => (d as HTMLDetailsElement).open)).toBe(true);
      await p.page.keyboard.press("Enter");
      expect(await details.evaluate((d) => (d as HTMLDetailsElement).open)).toBe(false);
    } finally {
      await p.close();
    }
  }, 30_000);

  it("the ask button posts ONE ui/message to the conversation and never a tool call", async () => {
    const p = await mountPanel(html, { toolResult: fixtures["risky"]!, width: 390 });
    try {
      await p.frame.getByRole("button", { name: /Ask what to do/ }).click();
      await p.settle();
      const log = await p.messages();
      const sent = log.filter((m) => m.dir === "in" && m.method === "ui/message");
      expect(sent).toHaveLength(1);
      expect(JSON.stringify(sent[0]!.params)).toContain("old-thing");
      expect(log.some((m) => m.method === "tools/call")).toBe(false);
      expect(await p.frame.evaluate(() => document.body.innerText)).toMatch(/Sent/);
    } finally {
      await p.close();
    }
  }, 30_000);

  it("a host that refuses the message gets its text shown to copy, and no false 'Sent'", async () => {
    const p = await mountPanel(html, {
      toolResult: fixtures["risky"]!,
      width: 390,
      acceptMessages: false,
    });
    try {
      await p.frame.getByRole("button", { name: /Ask what to do/ }).click();
      await p.settle();
      const text = await p.frame.evaluate(() => document.body.innerText);
      expect(text).toMatch(/did not take the message/);
      expect(text).not.toMatch(/Sent\. The assistant/);
      expect(await p.frame.locator(".pc-fallback").innerText()).toContain("old-thing");
    } finally {
      await p.close();
    }
  }, 30_000);

  it("a second result replaces the first and does not leave its status behind", async () => {
    const p = await mountPanel(html, { toolResult: fixtures["risky"]!, width: 390 });
    try {
      await p.frame.evaluate((next) => {
        window.dispatchEvent(
          new MessageEvent("message", {
            data: { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: next },
            source: window.parent,
          }),
        );
      }, fixtures["failure"]!);
      await p.settle();
      const text = await p.frame.evaluate(() => document.body.innerText);
      expect(text).toContain("Crate not found");
      expect(text).not.toContain("old-thing@");
    } finally {
      await p.close();
    }
  }, 30_000);
});

describe("a result is data, never markup", () => {
  it("HTML in a crate name or a yank message is shown as text", async () => {
    const evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>';
    const fake = fakeCrates(
      routesFor("acme-widget", crateDoc({ yanked: true, yankMessage: evil, publishedDaysAgo: 5 })),
    );
    const wire = toCallToolResult(await run("acme-widget", fake));
    const p = await mountPanel(html, { toolResult: wire, width: 390 });
    try {
      await p.frame.locator(".pc-signals summary").nth(1).click();
      await p.settle();
      expect(
        await p.frame.evaluate(() => (window as unknown as { __pwned?: number }).__pwned),
      ).toBeUndefined();
      expect(await p.frame.locator(".pc-signals img, .pc-signals script").count()).toBe(0);
      expect(await p.frame.evaluate(() => document.body.innerText)).toContain("<img src=x");
      expect(p.consoleErrors).toEqual([]);
    } finally {
      await p.close();
    }
  }, 30_000);

  it("only the host's window may deliver a result", async () => {
    const p = await mountPanel(html, { toolResult: fixtures["healthy"]!, width: 390 });
    try {
      await p.frame.evaluate((next) => {
        window.dispatchEvent(
          new MessageEvent("message", {
            data: { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: next },
            source: window,
          }),
        );
      }, fixtures["failure"]!);
      await p.settle();
      expect(await p.frame.evaluate(() => document.body.innerText)).toContain("acme-widget@");
    } finally {
      await p.close();
    }
  }, 30_000);
});
