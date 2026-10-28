"""Write the per-assistant entry files of this repository from their single source, AGENTS.md.

    python scripts/build_adapters.py          write them
    python scripts/build_adapters.py --check  fail when one is missing or stale (CI)

AGENTS.md is the one place the instructions are written. These files only point at it, so every assistant
(Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, Aider) lands on the same text:

    CLAUDE.md, GEMINI.md, CONVENTIONS.md, .aider.conf.yml, .github/copilot-instructions.md,
    .cursor/rules/findagent-code-agent.mdc

The variant list in the pointer is read from the folders that exist, and every variant must be named in AGENTS.md,
so adding a variant without documenting it fails here. This is the template's own entry files; a new agent's are
written by scripts/init_agent.py. Standard library only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Display order of the variants. A folder that is not listed here fails the run, so the list cannot go stale.
VARIANT_ORDER = ("node", "python", "framework", "package", "actions", "listing")
CODE_VARIANTS = ("node", "python", "framework")
MARKERS = ("findagent.json", "plugin.json", "listing.md")


def variants() -> list[str]:
    """The variant folders present, in display order; a marked folder with no place in the order is an error."""
    present = {d.name for d in ROOT.iterdir() if d.is_dir() and any((d / m).exists() for m in MARKERS)}
    unknown = present - set(VARIANT_ORDER)
    missing = set(VARIANT_ORDER) - present
    if unknown or missing:
        raise SystemExit(
            f"build_adapters: variant folders changed (new: {sorted(unknown)}, gone: {sorted(missing)}); "
            "update VARIANT_ORDER"
        )
    return list(VARIANT_ORDER)


def pointer(names: list[str]) -> str:
    folders = ", ".join(f"`{n}/`" for n in names[:-1]) + f" or `{names[-1]}/`"
    code = ", ".join(f"`{n}/`" for n in CODE_VARIANTS)
    return (
        "# FindAgent code agent template\n\n"
        f"Read `AGENTS.md` first and follow it. Pick one variant ({folders}); the code variants ({code}) keep the six "
        "entry tools. Run the variant's gates, and never submit or publish for the user.\n"
    )


def render() -> dict[str, str]:
    names = variants()
    source = (ROOT / "AGENTS.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    absent = [n for n in names if f"`{n}/`" not in source and f"`{n}`" not in source]
    if absent:
        raise SystemExit(f"build_adapters: AGENTS.md does not name the variant(s): {', '.join(absent)}")
    text = pointer(names)
    return {
        "CLAUDE.md": "@AGENTS.md\n",
        "GEMINI.md": "@AGENTS.md\n",
        "CONVENTIONS.md": text,
        ".aider.conf.yml": "read:\n  - AGENTS.md\n",
        ".github/copilot-instructions.md": text,
        # alwaysApply: true. This rule only points at AGENTS.md and is the one thing that tells Cursor where the
        # instructions are, so it must load on every request; `false` with no globs loads it only when Cursor
        # guesses from the description that it applies, and a missed load means the assistant never reads AGENTS.md.
        ".cursor/rules/findagent-code-agent.mdc": (
            "---\ndescription: Build a FindAgent agent from this template\nalwaysApply: true\n---\n\n" + text
        ),
    }


def main() -> int:
    check = "--check" in sys.argv
    stale = 0
    for rel, content in render().items():
        path = ROOT / rel
        current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
        if current == content:
            continue
        if check:
            sys.stderr.write(f"stale: {rel}\n")
            stale += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            sys.stdout.write(f"wrote {rel}\n")
    if stale:
        sys.stderr.write("run: python scripts/build_adapters.py\n")
        return 1
    sys.stdout.write("adapters up to date\n" if check else "done\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
