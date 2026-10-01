#!/usr/bin/env node
/**
 * Build the result panel: panel/template.html + panel/panel.css + panel/panel.js become ONE
 * self-contained document, written to ui/index.html (the file FindAgent captures at scan time)
 * and copied to dist/mcp/panel.html (the file the stdio server serves).
 *
 *   node scripts/build-panel.mjs          write ui/index.html and dist/mcp/panel.html
 *   node scripts/build-panel.mjs --check  exit 1 if ui/index.html is out of date
 *
 * The document has no external reference of any kind: no script src, no stylesheet link, no
 * image, no font, no fetch. FindAgent's scan rejects a panel that loads anything non-inline.
 */
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (f) => readFileSync(path.join(ROOT, f), "utf8").replace(/\r\n/g, "\n");

export function buildPanelHtml() {
  const template = read("panel/template.html");
  const css = read("panel/panel.css").trim();
  const js = read("panel/panel.js").trim();
  if (js.includes("</script")) throw new Error("panel.js must not contain </script");
  return template.replace("/*__CSS__*/", () => css).replace("/*__JS__*/", () => js);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const html = buildPanelHtml();
  const target = path.join(ROOT, "ui", "index.html");
  if (process.argv.includes("--check")) {
    let current = "";
    try {
      current = readFileSync(target, "utf8").replace(/\r\n/g, "\n");
    } catch {
      /* missing counts as stale */
    }
    if (current !== html) {
      console.error("ui/index.html is out of date; run: node scripts/build-panel.mjs");
      process.exit(1);
    }
  } else {
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, html);
    mkdirSync(path.join(ROOT, "dist", "mcp"), { recursive: true });
    copyFileSync(target, path.join(ROOT, "dist", "mcp", "panel.html"));
    console.log(`panel: wrote ui/index.html (${html.length} bytes) and dist/mcp/panel.html`);
  }
}
