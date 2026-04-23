"""Source-level regression tests for issue #422.

Invariants:

- ``launch()`` is the only site that calls ``register_agent_mcp_routes``.
- ``Orchestrator`` builds an ``MCPRoutes`` bundle in ``run()`` right
  after ``BusEventListener.start()``.
- The CfA close-path special case is gone: no ``_handle_bus_close``,
  no ``_cleanup_bus_agent_worktree``, no ``close_conversation``
  branch in ``_poll_dispatch_bus``, no dispatch-bus fallback for
  close in ``mcp/tools/messaging.py``.
- The per-phase ``register_spawn_fn`` / ``register_escalation_route``
  block in ``Orchestrator._run_phase`` is gone.
"""
from __future__ import annotations

import os
import re
import unittest


_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(_REPO_ROOT, 'teaparty', 'cfa', 'engine.py')
_SESSION = os.path.join(_REPO_ROOT, 'teaparty', 'teams', 'session.py')
_LAUNCHER = os.path.join(_REPO_ROOT, 'teaparty', 'runners', 'launcher.py')
_MCP_MSG = os.path.join(_REPO_ROOT, 'teaparty', 'mcp', 'tools', 'messaging.py')


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


class TestLaunchIsSoleRegistrationSite(unittest.TestCase):
    """Every path that makes an agent subprocess registers routes via launch()."""

    def test_launch_calls_register_agent_mcp_routes(self) -> None:
        content = _read(_LAUNCHER)
        self.assertIn(
            'register_agent_mcp_routes(', content,
            'launch() must install MCP routes via register_agent_mcp_routes — '
            'issue #422 makes launch() the single registration site.',
        )

    def test_no_scattered_register_spawn_fn_outside_launcher(self) -> None:
        """Only launcher.py may call register_spawn_fn (via register_agent_mcp_routes)."""
        for path, label in (
            (_ENGINE, 'cfa/engine.py'),
            (_SESSION, 'teams/session.py'),
        ):
            content = _read(path)
            self.assertNotIn(
                'register_spawn_fn(', content,
                f'{label} must not call register_spawn_fn directly — '
                'MCP routes are installed at launch() time (#422).',
            )

    def test_no_scattered_register_close_fn_outside_launcher(self) -> None:
        for path, label in (
            (_ENGINE, 'cfa/engine.py'),
            (_SESSION, 'teams/session.py'),
        ):
            content = _read(path)
            self.assertNotIn(
                'register_close_fn(', content,
                f'{label} must not call register_close_fn directly — '
                'MCP routes are installed at launch() time (#422).',
            )

    def test_no_scattered_register_escalation_route_outside_launcher(self) -> None:
        for path, label in (
            (_ENGINE, 'cfa/engine.py'),
            (_SESSION, 'teams/session.py'),
        ):
            content = _read(path)
            self.assertNotIn(
                'register_escalation_route(', content,
                f'{label} must not call register_escalation_route directly — '
                'MCP routes are installed at launch() time (#422).',
            )


class TestOrchestratorBuildsMCPRoutes(unittest.TestCase):
    """The CfA engine builds an MCPRoutes bundle in Orchestrator.run()."""

    def test_orchestrator_builds_mcp_routes(self) -> None:
        content = _read(_ENGINE)
        self.assertIn(
            'MCPRoutes(', content,
            'Orchestrator.run must construct an MCPRoutes bundle (#422).',
        )
        self.assertIn(
            'self._mcp_routes', content,
            'Orchestrator must store the built MCPRoutes on self for the '
            'actor and spawn paths to thread through launch() calls.',
        )

    def test_orchestrator_threads_mcp_routes_through_every_launch(self) -> None:
        """Every ``await _launch(``/``await launch(`` in the CfA tree
        passes ``mcp_routes=`` — so children, grandchildren, and resumes
        all install routes the same way.
        """
        engine = _read(_ENGINE)
        # Each launch() block passes mcp_routes=self._mcp_routes
        pattern = re.compile(
            r'await\s+_launch\(\s*(?P<body>.*?)\)\s*\n',
            re.DOTALL,
        )
        launch_blocks = pattern.findall(engine)
        self.assertGreater(
            len(launch_blocks), 0,
            'expected at least one _launch(...) call in cfa/engine.py',
        )
        missing = [
            b for b in launch_blocks if 'mcp_routes=' not in b
        ]
        self.assertEqual(
            missing, [],
            'every CfA _launch(...) must pass mcp_routes= (#422). '
            f'Missing in {len(missing)} block(s).',
        )

    def test_actors_launch_threads_mcp_routes_from_context(self) -> None:
        actors_path = os.path.join(_REPO_ROOT, 'teaparty', 'cfa', 'actors.py')
        content = _read(actors_path)
        self.assertIn(
            'mcp_routes=ctx.mcp_routes', content,
            'cfa/actors.py launch() must thread ctx.mcp_routes through '
            '— the phase lead needs the bundle registered by launch() '
            'so Send, CloseConversation, AskQuestion all work (#422).',
        )


class TestPerPhaseRegistrationRemoved(unittest.TestCase):
    """_run_phase no longer contains scattered MCP route registrations."""

    def test_run_phase_has_no_register_calls(self) -> None:
        engine = _read(_ENGINE)
        m = re.search(
            r'async def _run_phase\b.*?(?=\n    (?:async )?def )',
            engine, re.DOTALL,
        )
        self.assertIsNotNone(
            m, 'could not locate _run_phase in cfa/engine.py',
        )
        body = m.group(0)
        for symbol in (
            'register_spawn_fn',
            'register_close_fn',
            'register_escalation_route',
        ):
            self.assertNotIn(
                symbol, body,
                f'_run_phase must not call {symbol} — routes are now '
                'installed by launch() via the top-level MCPRoutes bundle '
                '(#422).',
            )


class TestCfaCloseSpecialCaseRemoved(unittest.TestCase):
    """The CfA close-path special case is gone — one codepath."""

    def test_handle_bus_close_is_gone(self) -> None:
        engine = _read(_ENGINE)
        self.assertNotIn(
            'async def _handle_bus_close', engine,
            '_handle_bus_close must be deleted — CloseConversation goes '
            'through the in-process registry (#422).',
        )

    def test_cleanup_bus_agent_worktree_is_gone(self) -> None:
        engine = _read(_ENGINE)
        self.assertNotIn(
            'async def _cleanup_bus_agent_worktree', engine,
            '_cleanup_bus_agent_worktree must be deleted — the shared '
            'close_fn handles merge + rmtree via close_conversation() '
            '(#422).',
        )

    def test_poll_dispatch_bus_no_close_branch(self) -> None:
        engine = _read(_ENGINE)
        m = re.search(
            r"async def _poll_dispatch_bus\b.*?(?=\n    (?:async )?def )",
            engine, re.DOTALL,
        )
        self.assertIsNotNone(m, 'could not locate _poll_dispatch_bus')
        body = m.group(0)
        self.assertNotIn(
            "'close_conversation'", body,
            "_poll_dispatch_bus must not have a 'close_conversation' branch — "
            'the in-process registry handles close for both tiers (#422).',
        )

    def test_no_dispatch_bus_fallback_for_close(self) -> None:
        msg = _read(_MCP_MSG)
        m = re.search(
            r"async def _default_close_conv_post\b.*?(?=\n(?:async )?def |\Z)",
            msg, re.DOTALL,
        )
        self.assertIsNotNone(m, 'could not locate _default_close_conv_post')
        body = m.group(0)
        self.assertNotIn(
            "'type': 'close_conversation'", body,
            'close_conversation_handler must not have a dispatch-bus fallback '
            '— both tiers register close_fn in the in-process registry '
            '(#422).',
        )


if __name__ == '__main__':
    unittest.main()
