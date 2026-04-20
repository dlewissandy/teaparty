"""Regression test: CfA agent launches must wire up the MCP server.

The bug: ``actors.AgentRunner.run`` called ``launch(...)`` without
passing ``mcp_port``, so ``compose_launch_worktree`` skipped writing
``.mcp.json`` to the worktree.  ``claude -p`` then had no knowledge of
the ``teaparty-config`` MCP server, even though the agent's
``permissions.allow`` listed ``mcp__teaparty-config__Send`` etc.
Result: the project-lead reported "delegation tools not exposed in
this session" and fell back to solo authoring.

The source-level check below asserts that ``actors.py`` passes
``mcp_port`` into ``launch(...)``.  Combined with the existing tests
for ``compose_launch_worktree`` writing ``.mcp.json`` when
``mcp_port`` is truthy, this locks in the full contract: an agent
launched through the CfA path can actually call the MCP tools in its
allow list.
"""
from __future__ import annotations

import os
import re
import unittest


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ACTORS_PATH = os.path.join(_REPO_ROOT, 'teaparty', 'cfa', 'actors.py')


class CfaLaunchPassesMcpPortTest(unittest.TestCase):
    """actors.py must pass ``mcp_port=...`` into its launch() call."""

    def test_launch_call_includes_mcp_port(self) -> None:
        with open(_ACTORS_PATH) as f:
            content = f.read()
        # Find the `result = await launch(` block and its kwargs.
        m = re.search(
            r'result\s*=\s*await\s+launch\(\s*(?P<body>.*?)\)\s*\n',
            content, re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            'could not find ``result = await launch(...)`` in actors.py',
        )
        launch_body = m.group('body')
        self.assertIn(
            'mcp_port=', launch_body,
            'actors.py launch() call must pass ``mcp_port=`` so '
            '``compose_launch_worktree`` writes ``.mcp.json`` to the '
            'worktree.  Without it, claude -p has no knowledge of the '
            'teaparty-config MCP server and the agent cannot call Send, '
            'CloseConversation, AskQuestion, etc. — even though the '
            'allow list grants them.',
        )

    def test_mcp_port_derives_from_teaparty_bridge_port_env(self) -> None:
        """The port comes from ``TEAPARTY_BRIDGE_PORT`` (default 9000).

        Matches the pattern already used by every dispatch path in
        ``engine.py``.  Hardcoding would make the port ungovernable
        in tests / non-default deployments.
        """
        with open(_ACTORS_PATH) as f:
            content = f.read()
        self.assertIn(
            "os.environ.get('TEAPARTY_BRIDGE_PORT'", content,
            'actors.py must read the MCP port from ``TEAPARTY_BRIDGE_PORT`` '
            'env (matching engine.py dispatch paths); hardcoded port is a '
            'regression trap.',
        )


if __name__ == '__main__':
    unittest.main()
