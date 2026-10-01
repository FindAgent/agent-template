"""Build the result panel: panel/template.html + panel/panel.css + panel/panel.js become ONE
self-contained document, written to ui/index.html (the file FindAgent captures at scan time and the
file the server serves).

    python scripts/build_panel.py          write ui/index.html
    python scripts/build_panel.py --check  exit 1 if ui/index.html is out of date

The document has no external reference of any kind: no script src, no stylesheet link, no image, no
font, no fetch. FindAgent's scan rejects a panel that loads anything that is not inline. The sandbox
only installs Python packages and has no step that could build this, so the built file is committed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "ui" / "index.html"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8").replace("\r\n", "\n")


def build_panel_html() -> str:
    template = read("panel/template.html")
    css = read("panel/panel.css").strip()
    js = read("panel/panel.js").strip()
    if "</script" in js:
        raise ValueError("panel.js must not contain </script")
    return template.replace("/*__CSS__*/", css).replace("/*__JS__*/", js)


def main(argv: list[str]) -> int:
    html = build_panel_html()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8").replace("\r\n", "\n") if TARGET.exists() else ""
        if current != html:
            sys.stderr.write("ui/index.html is out of date; run: python scripts/build_panel.py\n")
            return 1
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(html, encoding="utf-8", newline="\n")
    sys.stdout.write(f"panel: wrote ui/index.html ({len(html.encode())} bytes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
