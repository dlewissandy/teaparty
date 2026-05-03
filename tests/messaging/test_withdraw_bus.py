"""Tests for the bus-backed intervention listener.

The orchestrator starts an ``InterventionListener`` that consumes an
``intervention:{session_id}`` bus conversation.  Agent-side intervention
tools (WithdrawSession, PauseDispatch, etc.) write their requests as
sender ``agent`` and poll for sender ``orchestrator`` replies.

Issue #249 (original) / Issue #419 (transport migration to bus).
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

from teaparty.cfa.gates.intervention_listener import (
    InterventionListener,
    InterventionRequest,
    make_intervention_request,
)
from teaparty.messaging.conversations import SqliteMessageBus


def _make_infra_dir(tmpdir: str, session_id: str) -> str:
    """Create a minimal infra dir with a CfA state file."""
    infra = os.path.join(tmpdir, 'jobs', session_id)
    os.makedirs(infra)
    cfa_path = os.path.join(infra, '.cfa-state.json')
    with open(cfa_path, 'w') as f:
        json.dump({'state': 'EXECUTE', 'phase': 'execution'}, f)
    hb_path = os.path.join(infra, '.heartbeat')
    with open(hb_path, 'w') as f:
        json.dump({'status': 'running'}, f)
    return infra


async def _request_and_wait(bus_db: str, conv_id: str, request: dict) -> dict:
    """Post a request on the bus and poll for the orchestrator's reply."""
    bus = SqliteMessageBus(bus_db)
    import time as _time
    since = _time.time()
    bus.send(conv_id, 'agent', json.dumps(request))
    deadline = _time.time() + 10
    while _time.time() < deadline:
        msgs = bus.receive(conv_id, since_timestamp=since)
        replies = [m for m in msgs if m.sender == 'orchestrator']
        if replies:
            return json.loads(replies[0].content)
        await asyncio.sleep(0.05)
    raise AssertionError('orchestrator did not reply within deadline')


class TestInterventionBusWiring(unittest.TestCase):
    """The InterventionListener consumes an agent→orchestrator bus
    conversation and writes the reply back on the same conversation.
    """

    def test_withdraw_via_bus(self):
        """A withdraw request on the bus reaches the listener and returns
        a successful response."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-withdraw'
            bus_db = os.path.join(tmpdir, 'messages.db')
            conv_id = f'intervention:{session_id}'
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            listener = InterventionListener(
                resolver=resolver,
                bus_db_path=bus_db,
                conv_id=conv_id,
            )

            async def run():
                await listener.start()
                try:
                    return await _request_and_wait(bus_db, conv_id, {
                        'type': 'withdraw_session',
                        'session_id': session_id,
                    })
                finally:
                    await listener.stop()

            result = asyncio.run(run())
            self.assertEqual(result['status'], 'withdrawn')

    def test_unknown_session_id_returns_error(self):
        """A request referencing a session not in the resolver returns an
        error response (no crash or hang)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-unknown'
            bus_db = os.path.join(tmpdir, 'messages.db')
            conv_id = f'intervention:{session_id}'
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            listener = InterventionListener(
                resolver=resolver,
                bus_db_path=bus_db,
                conv_id=conv_id,
            )

            async def run():
                await listener.start()
                try:
                    return await _request_and_wait(bus_db, conv_id, {
                        'type': 'withdraw_session',
                        'session_id': 'unknown-session',
                    })
                finally:
                    await listener.stop()

            result = asyncio.run(run())
            self.assertEqual(result['status'], 'error')
            self.assertIn('unknown', result.get('reason', ''))

    def test_on_withdraw_callback_fires_on_success(self):
        """The on_withdraw callback fires with the session_id after a
        successful withdrawal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-cb'
            bus_db = os.path.join(tmpdir, 'messages.db')
            conv_id = f'intervention:{session_id}'
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}
            callback_calls: list[str] = []

            listener = InterventionListener(
                resolver=resolver,
                bus_db_path=bus_db,
                conv_id=conv_id,
                on_withdraw=lambda sid: callback_calls.append(sid),
            )

            async def run():
                await listener.start()
                try:
                    return await _request_and_wait(bus_db, conv_id, {
                        'type': 'withdraw_session',
                        'session_id': session_id,
                    })
                finally:
                    await listener.stop()

            result = asyncio.run(run())
            self.assertEqual(result['status'], 'withdrawn')
            self.assertEqual(callback_calls, [session_id])

    def test_on_withdraw_not_called_on_already_terminal(self):
        """The callback does not fire when the session is already terminal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-terminal'
            bus_db = os.path.join(tmpdir, 'messages.db')
            conv_id = f'intervention:{session_id}'
            infra = _make_infra_dir(tmpdir, session_id)
            cfa_path = os.path.join(infra, '.cfa-state.json')
            with open(cfa_path, 'w') as f:
                json.dump({'state': 'DONE', 'phase': 'terminal'}, f)
            resolver = {session_id: infra}
            callback_calls: list[str] = []

            listener = InterventionListener(
                resolver=resolver,
                bus_db_path=bus_db,
                conv_id=conv_id,
                on_withdraw=lambda sid: callback_calls.append(sid),
            )

            async def run():
                await listener.start()
                try:
                    return await _request_and_wait(bus_db, conv_id, {
                        'type': 'withdraw_session',
                        'session_id': session_id,
                    })
                finally:
                    await listener.stop()

            result = asyncio.run(run())
            self.assertEqual(result['status'], 'already_terminal')
            self.assertEqual(callback_calls, [])


class TestInterventionRequest(unittest.TestCase):
    """The shared InterventionRequest type and factory function."""

    def test_make_intervention_request_withdraw(self):
        req = make_intervention_request(
            'withdraw_session', session_id='ses-abc',
        )
        self.assertEqual(req['type'], 'withdraw_session')
        self.assertEqual(req['session_id'], 'ses-abc')

    def test_make_intervention_request_reprioritize(self):
        req = make_intervention_request(
            'reprioritize_dispatch',
            dispatch_id='d-1',
            priority='high',
        )
        self.assertEqual(req['type'], 'reprioritize_dispatch')
        self.assertEqual(req['dispatch_id'], 'd-1')
        self.assertEqual(req['priority'], 'high')

    def test_intervention_request_is_json_serializable(self):
        req = make_intervention_request(
            'pause_dispatch', dispatch_id='d-2',
        )
        roundtripped = json.loads(json.dumps(req))
        self.assertEqual(roundtripped, req)


if __name__ == '__main__':
    unittest.main()
