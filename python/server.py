"""Entry point: `python3 server.py` starts the MCP server on stdio.

findagent.json names this file as the entrypoint; the sandbox runs it from the repository root with
the vendored dependencies on PYTHONPATH.
"""

from agent_template.mcp_server import main

if __name__ == "__main__":
    main()
