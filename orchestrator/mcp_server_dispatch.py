"""Lean MCP server entry point for dispatched agents.

Identical to mcp_server.main() but forces AGENT_TOOL_SCOPE=dispatch
before create_server() runs. This sidesteps Claude Code's MCP subprocess
isolation — the scope is hardcoded in the module, not passed via env/file.

Usage in mcp_config args: ["-m", "orchestrator.mcp_server_dispatch"]
"""
import os

os.environ['AGENT_TOOL_SCOPE'] = 'dispatch'

from orchestrator.mcp_server import main  # noqa: E402

if __name__ == '__main__':
    main()
