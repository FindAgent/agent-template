"""Scaffold a variant into a temporary directory and run the gates of the repository it produced.

    python scripts/check_scaffold.py <variant> [--keep] [--skip <text>]...

The gates are the `run:` steps of the generated `.github/workflows/ci.yml`, executed in order in the new repository,
plus the platform CLI check at the version pinned in scripts/cli-version.txt (never `latest`). So a defect that
`init_agent.py` bakes into every new agent (a lint error in a copied script, a generated file that is stale on the
first run) fails here, in the template's CI, and not in a stranger's first push.

    --keep        leave the temporary directory in place and print it
    --skip TEXT   skip the CI steps whose command contains TEXT (for a machine that already has, say, Chromium)

Every step's exit code is printed. Exit 0 only when init and every step exited 0.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VARIANTS = ("node", "python", "framework", "package", "actions", "listing")
UNPINNED = "@findagent/cli@latest"


def out(line: str) -> None:
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def ci_steps(ci: str) -> list[tuple[str, str]]:
    """(name, command) of every single-line `run:` step of a generated workflow, in order."""
    return re.findall(r"- name: ([^\n]+)\n\s+run: ([^\n]+)\n", ci)


def run(command: str, cwd: Path, env: dict[str, str]) -> int:
    # shell=True: the commands are the ones our own generator wrote (some chain with `&&`), never user input.
    return subprocess.call(command, cwd=cwd, shell=True, env=env)


def main() -> int:
    args = sys.argv[1:]
    variant = next((a for a in args if a in VARIANTS), None)
    if variant is None:
        out(__doc__ or "")
        return 2
    skips = [args[i + 1] for i, a in enumerate(args) if a == "--skip" and i + 1 < len(args)]
    pin = (ROOT / "scripts" / "cli-version.txt").read_text(encoding="utf-8").strip()
    pinned = f"@findagent/cli@{pin}"

    work = Path(tempfile.mkdtemp(prefix=f"scaffold-{variant}-"))
    dest = work / "agent"
    init_script = str(ROOT / "scripts" / "init_agent.py")
    init = subprocess.call([sys.executable, "-I", init_script, variant, str(dest), "--name", f"CI {variant}"])
    out(f"EXIT={init} init {variant}")
    failed = [] if init == 0 else ["init"]

    ci = (dest / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8") if init == 0 else ""
    steps = ci_steps(ci)
    if init == 0 and not steps:
        out("EXIT=1 the generated ci.yml has no steps")
        failed.append("ci.yml")
    env = {**os.environ, "pnpm_config_strict_dep_builds": "false"}
    ran_cli = False
    for name, command in steps:
        command = command.replace(UNPINNED, pinned)
        ran_cli = ran_cli or pinned in command
        if any(s in command for s in skips):
            out(f"SKIP {name}: {command}")
            continue
        out(f"--- {name}: {command}")
        code = run(command, dest, env)
        out(f"EXIT={code} {name}")
        if code != 0:
            failed.append(name)
    if init == 0 and not ran_cli:
        command = f"npx --yes {pinned} check ."
        out(f"--- Platform rules (the CLI's whole-repo check): {command}")
        code = run(command, dest, env)
        out(f"EXIT={code} Platform rules (the CLI's whole-repo check)")
        if code != 0:
            failed.append("cli check")
    if "--keep" in args:
        out(f"kept: {dest}")
    out(f"{'FAILED: ' + ', '.join(failed) if failed else 'OK'} ({variant})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
