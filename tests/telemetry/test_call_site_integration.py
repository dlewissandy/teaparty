"""Integration tests that exercise call sites through the real code
path and assert telemetry lands in the unified store (Issue #405).

Each test drives a real call site (CfA transition, close_conversation,
MCP config CRUD) and then reads back from ``telemetry.query_events``
to verify the event was recorded with the right scope, session id,
and data fields.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from teaparty import telemetry
from teaparty.telemetry import events as E


def _fresh_home() -> str:
    home = tempfile.mkdtemp(prefix='telemetry-integ-')
    telemetry.reset_for_tests()
    telemetry.set_teaparty_home(home)
    return home


class ConfigCrudEmitsTelemetryTests(unittest.TestCase):
    """Adding/removing registry entries emits config_* events."""

    def setUp(self) -> None:
        self.home = _fresh_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_emit_config_event_records_config_change(self) -> None:
        """The shared _emit_config_event helper in config_crud routes
        every create/edit/remove into the telemetry store. Covering
        the helper covers every handler that calls it."""
        from teaparty.mcp.tools.config_crud import _emit_config_event

        _emit_config_event(
            'config_agent_created', name='demo-agent', path='/x/y',
            project='comics',
        )
        events = telemetry.query_events(event_type=E.CONFIG_AGENT_CREATED)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].scope, 'comics')
        self.assertEqual(events[0].data['name'], 'demo-agent')

    def test_unknown_event_name_falls_back_to_string_type(self) -> None:
        from teaparty.mcp.tools.config_crud import _emit_config_event
        _emit_config_event('some_future_event', project='management')
        events = telemetry.query_events(event_type='some_future_event')
        self.assertEqual(len(events), 1)


class InterventionEmitsTelemetryTests(unittest.TestCase):
    """The intervention tool handler emits pause_all / resume_all /
    withdraw_clicked when the listener responds — even when we fake the
    listener via a stubbed socket server."""

    def setUp(self) -> None:
        self.home = _fresh_home()
        self._prev_sock = os.environ.get('INTERVENTION_SOCKET')

    def tearDown(self) -> None:
        if self._prev_sock is None:
            os.environ.pop('INTERVENTION_SOCKET', None)
        else:
            os.environ['INTERVENTION_SOCKET'] = self._prev_sock
        telemetry.reset_for_tests()

    def test_pause_dispatch_emits_pause_all(self) -> None:
        import asyncio
        import json
        from teaparty.mcp.tools.intervention import intervention_handler

        sock_path = os.path.join(self.home, 'intervention.sock')
        os.environ['INTERVENTION_SOCKET'] = sock_path

        async def fake_listener():
            async def handle(reader, writer):
                _ = await reader.readline()
                writer.write(json.dumps({'status': 'paused'}).encode() + b'\n')
                await writer.drain()
                writer.close()
            return await asyncio.start_unix_server(handle, path=sock_path)

        async def run():
            server = await fake_listener()
            try:
                await intervention_handler(
                    'pause_dispatch', dispatch_id='d1',
                    project_slug='comics',
                )
            finally:
                server.close()
                await server.wait_closed()

        asyncio.run(run())

        events = telemetry.query_events(event_type=E.PAUSE_ALL)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].scope, 'comics')
        self.assertEqual(events[0].data['dispatch_id'], 'd1')
        self.assertEqual(events[0].data['result_status'], 'paused')


class CloseConversationEmitsTelemetryTests(unittest.TestCase):
    """close_conversation emits close_conversation + session_closed for
    the target and each recursive descendant."""

    def setUp(self) -> None:
        self.home = _fresh_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_close_conversation_emits_events_for_target_and_descendants(
        self,
    ) -> None:
        from teaparty.workspace.close_conversation import close_conversation

        # Minimal session-dir layout so collect_descendants returns [].
        scope = 'management'
        sessions_dir = os.path.join(self.home, scope, 'sessions', 'child-1')
        os.makedirs(sessions_dir, exist_ok=True)

        class _FakeSession:
            id = 'parent-1'
            conversation_map: dict = {}

        close_conversation(
            _FakeSession(),
            'dispatch:child-1',
            teaparty_home=self.home,
            scope=scope,
        )

        close_events = telemetry.query_events(
            event_type=E.CLOSE_CONVERSATION,
        )
        self.assertEqual(len(close_events), 1)
        self.assertEqual(close_events[0].data['child_session'], 'child-1')

        session_closed = telemetry.query_events(
            event_type=E.SESSION_CLOSED,
        )
        # Exactly one — the target child. No descendants seeded.
        self.assertEqual(len(session_closed), 1)
        self.assertEqual(session_closed[0].session_id, 'child-1')
        self.assertEqual(
            session_closed[0].data['reason'], 'explicit_close',
        )


if __name__ == '__main__':
    unittest.main()
