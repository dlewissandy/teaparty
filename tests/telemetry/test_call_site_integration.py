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

    def test_unknown_event_name_raises_assertion_error(self) -> None:
        """A typo in the event_type must fail immediately, not fall back
        silently to a raw string (no-silent-fallbacks standard)."""
        from teaparty.mcp.tools.config_crud import _emit_config_event
        with self.assertRaises(AssertionError):
            _emit_config_event('some_future_event', project='management')


class InterventionEmitsTelemetryTests(unittest.TestCase):
    """The intervention tool handler emits pause_all / resume_all /
    withdraw_clicked when the listener responds — even when we fake the
    listener via a stubbed bus reply."""

    def setUp(self) -> None:
        self.home = _fresh_home()
        self._prev_bus = os.environ.get('INTERVENTION_BUS_DB')
        self._prev_conv = os.environ.get('INTERVENTION_CONV_ID')

    def tearDown(self) -> None:
        for key, prev in (
            ('INTERVENTION_BUS_DB', self._prev_bus),
            ('INTERVENTION_CONV_ID', self._prev_conv),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
        telemetry.reset_for_tests()

    def test_intervention_handler_emits_telemetry_for_all_four_types(
        self,
    ) -> None:
        """Each intervention type maps to a distinct telemetry event."""
        import asyncio
        import json
        from teaparty.mcp.tools.intervention import intervention_handler
        from teaparty.messaging.conversations import SqliteMessageBus

        cases = [
            ('pause_dispatch', E.PAUSE_ALL, {'dispatch_id': 'd1'}),
            ('resume_dispatch', E.RESUME_ALL, {'dispatch_id': 'd2'}),
            ('withdraw_session', E.WITHDRAW_CLICKED, {'session_id': 's1'}),
            ('reprioritize_dispatch', E.REPRIORITIZE_DISPATCH_CLICKED,
             {'dispatch_id': 'd3', 'priority': 5}),
        ]

        for request_type, expected_event, extra_kwargs in cases:
            with self.subTest(request_type=request_type):
                telemetry.reset_for_tests()
                self.home = _fresh_home()
                bus_db = os.path.join(self.home, 'messages.db')
                conv_id = f'intervention:test-{request_type}'
                os.environ['INTERVENTION_BUS_DB'] = bus_db
                os.environ['INTERVENTION_CONV_ID'] = conv_id

                # Stub the orchestrator: poll for the agent message, post a
                # canned 'ok' reply.
                async def fake_orchestrator():
                    bus = SqliteMessageBus(bus_db)
                    for _ in range(100):
                        msgs = bus.receive(conv_id, since_timestamp=0)
                        if any(m.sender == 'agent' for m in msgs):
                            bus.send(
                                conv_id, 'orchestrator',
                                json.dumps({'status': 'ok'}),
                            )
                            return
                        await asyncio.sleep(0.01)

                async def run():
                    server_task = asyncio.create_task(fake_orchestrator())
                    try:
                        await intervention_handler(
                            request_type,
                            project_slug='comics',
                            **extra_kwargs,
                        )
                    finally:
                        server_task.cancel()
                        try:
                            await server_task
                        except (asyncio.CancelledError, Exception):
                            pass

                asyncio.run(run())
                events = telemetry.query_events(event_type=expected_event)
                self.assertEqual(
                    len(events), 1,
                    f'{request_type} must emit exactly one '
                    f'{expected_event} event, got {len(events)}',
                )
                self.assertEqual(events[0].scope, 'comics')


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
        import asyncio
        from teaparty.workspace.close_conversation import close_conversation
        from teaparty.messaging.conversations import (
            ConversationState, ConversationType, SqliteMessageBus,
        )

        scope = 'management'
        sessions_base = os.path.join(self.home, scope, 'sessions')

        # Two-level tree registered in the bus (#422 — single source of truth).
        child_dir = os.path.join(sessions_base, 'child-1')
        gc_dir = os.path.join(sessions_base, 'grandchild-1')
        os.makedirs(child_dir, exist_ok=True)
        os.makedirs(gc_dir, exist_ok=True)
        bus = SqliteMessageBus(os.path.join(self.home, 'bus.db'))
        bus.create_conversation(
            ConversationType.DISPATCH, 'child-1',
            agent_name='child',
            parent_conversation_id='dispatch:parent-1',
            state=ConversationState.ACTIVE,
        )
        bus.create_conversation(
            ConversationType.DISPATCH, 'grandchild-1',
            agent_name='grandchild',
            parent_conversation_id='dispatch:child-1',
            state=ConversationState.ACTIVE,
        )

        class _FakeSession:
            id = 'parent-1'

        result = close_conversation(
            _FakeSession(),
            'dispatch:child-1',
            teaparty_home=self.home,
            scope=scope,
            bus=bus,
        )
        if asyncio.iscoroutine(result):
            asyncio.run(result)

        close_events = telemetry.query_events(
            event_type=E.CLOSE_CONVERSATION,
        )
        self.assertEqual(len(close_events), 1)
        self.assertEqual(close_events[0].data['child_session'], 'child-1')
        self.assertEqual(
            close_events[0].data['descendants'], 1,
            'one descendant (grandchild-1) must be counted',
        )

        session_closed = telemetry.query_events(
            event_type=E.SESSION_CLOSED,
        )
        self.assertEqual(
            len(session_closed), 2,
            'both the target and the grandchild must emit session_closed',
        )
        reasons = {e.session_id: e.data['reason'] for e in session_closed}
        self.assertEqual(
            reasons['child-1'], 'explicit_close',
            'target must be explicit_close',
        )
        self.assertEqual(
            reasons['grandchild-1'], 'recursive_cascade',
            'descendant must be recursive_cascade',
        )


if __name__ == '__main__':
    unittest.main()
