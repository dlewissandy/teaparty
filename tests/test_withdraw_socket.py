"""Tests for issue #386: Withdraw button socket wiring.

The bridge locates the intervention socket at a well-known path:
  {teaparty_home}/sockets/{session_id}.sock

where teaparty_home = {repo_root}/.teaparty.  The InterventionListener
must bind directly at this path so the bridge's /api/withdraw endpoint
can reach it.  Per the cfa-extensions spec, the listener uses
unlink-before-bind to handle stale sockets from crashed sessions.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

from orchestrator.intervention_listener import (
    InterventionListener,
    InterventionRequest,
    make_intervention_request,
)


def _make_infra_dir(tmpdir: str, session_id: str) -> str:
    """Create a minimal infra dir with a CfA state file."""
    infra = os.path.join(tmpdir, 'jobs', session_id)
    os.makedirs(infra)
    cfa_path = os.path.join(infra, '.cfa-state.json')
    with open(cfa_path, 'w') as f:
        json.dump({'state': 'EXECUTING_WORK', 'phase': 'execute'}, f)
    hb_path = os.path.join(infra, '.heartbeat')
    with open(hb_path, 'w') as f:
        json.dump({'status': 'running'}, f)
    return infra


def _well_known_path(teaparty_home: str, session_id: str) -> str:
    """Mirror the bridge's _withdrawal_socket_path convention."""
    return os.path.join(teaparty_home, 'sockets', f'{session_id}.sock')


class TestWithdrawSocketWiring(unittest.TestCase):
    """The bridge must be able to reach the InterventionListener via
    a well-known socket path at {teaparty_home}/sockets/{session_id}.sock.
    """

    def test_socket_bound_at_well_known_path(self):
        """The listener binds directly at the well-known path, not at a
        temp directory with a symlink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-001'
            teaparty_home = os.path.join(tmpdir, '.teaparty')
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            listener = InterventionListener(
                resolver=resolver,
                teaparty_home=teaparty_home,
            )

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(listener.start())

                expected = _well_known_path(teaparty_home, session_id)
                self.assertEqual(listener.socket_path, expected)
                self.assertTrue(
                    os.path.exists(expected),
                    f'Expected socket at {expected}',
                )
            finally:
                loop.run_until_complete(listener.stop())
                loop.close()

    def test_bridge_can_withdraw_via_well_known_socket(self):
        """A withdraw request sent to the well-known socket path should
        reach the InterventionListener and return a successful response."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-002'
            teaparty_home = os.path.join(tmpdir, '.teaparty')
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            listener = InterventionListener(
                resolver=resolver,
                teaparty_home=teaparty_home,
            )

            async def run():
                await listener.start()
                try:
                    sock = _well_known_path(teaparty_home, session_id)
                    payload = json.dumps({
                        'type': 'withdraw_session',
                        'session_id': session_id,
                    })
                    reader, writer = await asyncio.open_unix_connection(sock)
                    writer.write(payload.encode() + b'\n')
                    await writer.drain()
                    line = await reader.readline()
                    writer.close()
                    await writer.wait_closed()
                    return json.loads(line.decode())
                finally:
                    await listener.stop()

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(run())
            finally:
                loop.close()

            self.assertEqual(result['status'], 'withdrawn')

    def test_socket_cleaned_up_on_stop(self):
        """After the listener stops, the well-known socket is removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-003'
            teaparty_home = os.path.join(tmpdir, '.teaparty')
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            listener = InterventionListener(
                resolver=resolver,
                teaparty_home=teaparty_home,
            )

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(listener.start())
                expected = _well_known_path(teaparty_home, session_id)
                self.assertTrue(os.path.exists(expected))
                loop.run_until_complete(listener.stop())
                self.assertFalse(
                    os.path.exists(expected),
                    'Socket should be cleaned up on stop',
                )
            finally:
                loop.close()

    def test_unlink_before_bind_handles_stale_socket(self):
        """If a stale socket exists from a crashed session, the listener
        removes it and binds successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-004'
            teaparty_home = os.path.join(tmpdir, '.teaparty')
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            # Create a stale socket file at the well-known path.
            sockets_dir = os.path.join(teaparty_home, 'sockets')
            os.makedirs(sockets_dir)
            stale_path = _well_known_path(teaparty_home, session_id)
            with open(stale_path, 'w') as f:
                f.write('stale')

            listener = InterventionListener(
                resolver=resolver,
                teaparty_home=teaparty_home,
            )

            async def run():
                await listener.start()
                try:
                    payload = json.dumps({
                        'type': 'withdraw_session',
                        'session_id': session_id,
                    })
                    reader, writer = await asyncio.open_unix_connection(
                        stale_path,
                    )
                    writer.write(payload.encode() + b'\n')
                    await writer.drain()
                    line = await reader.readline()
                    writer.close()
                    await writer.wait_closed()
                    return json.loads(line.decode())
                finally:
                    await listener.stop()

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(run())
            finally:
                loop.close()

            self.assertEqual(result['status'], 'withdrawn')


    def test_unknown_session_id_returns_error(self):
        """When the bridge sends a session_id not in the resolver, the
        listener returns an error response (not a crash or hang)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-005'
            teaparty_home = os.path.join(tmpdir, '.teaparty')
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            listener = InterventionListener(
                resolver=resolver,
                teaparty_home=teaparty_home,
            )

            async def run():
                await listener.start()
                try:
                    sock = _well_known_path(teaparty_home, session_id)
                    # Send a withdraw for a session_id NOT in the resolver.
                    payload = json.dumps(make_intervention_request(
                        'withdraw_session', session_id='unknown-session',
                    ))
                    reader, writer = await asyncio.open_unix_connection(sock)
                    writer.write(payload.encode() + b'\n')
                    await writer.drain()
                    line = await reader.readline()
                    writer.close()
                    await writer.wait_closed()
                    return json.loads(line.decode())
                finally:
                    await listener.stop()

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(run())
            finally:
                loop.close()

            self.assertEqual(result['status'], 'error')
            self.assertIn('unknown', result.get('reason', ''))


    def test_on_withdraw_callback_fires_after_successful_withdrawal(self):
        """When withdrawal succeeds, the on_withdraw callback is called
        with the session_id so the engine can update its in-memory state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-006'
            teaparty_home = os.path.join(tmpdir, '.teaparty')
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            callback_calls: list[str] = []

            listener = InterventionListener(
                resolver=resolver,
                teaparty_home=teaparty_home,
                on_withdraw=lambda sid: callback_calls.append(sid),
            )

            async def run():
                await listener.start()
                try:
                    sock = _well_known_path(teaparty_home, session_id)
                    payload = json.dumps(make_intervention_request(
                        'withdraw_session', session_id=session_id,
                    ))
                    reader, writer = await asyncio.open_unix_connection(sock)
                    writer.write(payload.encode() + b'\n')
                    await writer.drain()
                    line = await reader.readline()
                    writer.close()
                    await writer.wait_closed()
                    return json.loads(line.decode())
                finally:
                    await listener.stop()

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(run())
            finally:
                loop.close()

            self.assertEqual(result['status'], 'withdrawn')
            self.assertEqual(callback_calls, [session_id])

    def test_on_withdraw_callback_not_called_on_already_terminal(self):
        """The callback should NOT fire if the session is already terminal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-007'
            teaparty_home = os.path.join(tmpdir, '.teaparty')
            infra = _make_infra_dir(tmpdir, session_id)
            # Overwrite state to already-terminal
            cfa_path = os.path.join(infra, '.cfa-state.json')
            with open(cfa_path, 'w') as f:
                json.dump({'state': 'COMPLETED_WORK', 'phase': 'terminal'}, f)
            resolver = {session_id: infra}

            callback_calls: list[str] = []

            listener = InterventionListener(
                resolver=resolver,
                teaparty_home=teaparty_home,
                on_withdraw=lambda sid: callback_calls.append(sid),
            )

            async def run():
                await listener.start()
                try:
                    sock = _well_known_path(teaparty_home, session_id)
                    payload = json.dumps(make_intervention_request(
                        'withdraw_session', session_id=session_id,
                    ))
                    reader, writer = await asyncio.open_unix_connection(sock)
                    writer.write(payload.encode() + b'\n')
                    await writer.drain()
                    line = await reader.readline()
                    writer.close()
                    await writer.wait_closed()
                    return json.loads(line.decode())
                finally:
                    await listener.stop()

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(run())
            finally:
                loop.close()

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
