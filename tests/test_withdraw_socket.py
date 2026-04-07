"""Tests for issue #386: Withdraw button socket wiring.

The bridge locates the intervention socket at a well-known path:
  {teaparty_home}/sockets/{session_id}.sock

The engine must create this path when starting the InterventionListener
so the bridge's /api/withdraw endpoint can reach it.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

from orchestrator.intervention_listener import InterventionListener


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


class TestWithdrawSocketWiring(unittest.TestCase):
    """The bridge must be able to reach the InterventionListener via
    a well-known socket path at {teaparty_home}/sockets/{session_id}.sock.
    """

    def test_well_known_socket_created_on_start(self):
        """After engine starts the listener, a socket (or symlink) must
        exist at the well-known path for each registered session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-001'
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            listener = InterventionListener(
                resolver=resolver,
                teaparty_home=tmpdir,
            )

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(listener.start())

                well_known = os.path.join(
                    tmpdir, 'sockets', f'{session_id}.sock',
                )
                self.assertTrue(
                    os.path.exists(well_known),
                    f'Expected socket at {well_known}',
                )
            finally:
                loop.run_until_complete(listener.stop())
                loop.close()

    def test_bridge_can_withdraw_via_well_known_socket(self):
        """A withdraw request sent to the well-known socket path should
        reach the InterventionListener and return a successful response."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-002'
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            listener = InterventionListener(
                resolver=resolver,
                teaparty_home=tmpdir,
            )

            async def run():
                await listener.start()
                try:
                    well_known = os.path.join(
                        tmpdir, 'sockets', f'{session_id}.sock',
                    )
                    payload = json.dumps({
                        'type': 'withdraw_session',
                        'session_id': session_id,
                    })
                    reader, writer = await asyncio.open_unix_connection(
                        well_known,
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

    def test_well_known_socket_cleaned_up_on_stop(self):
        """After the listener stops, well-known socket paths should be
        removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = 'ses-test-003'
            infra = _make_infra_dir(tmpdir, session_id)
            resolver = {session_id: infra}

            listener = InterventionListener(
                resolver=resolver,
                teaparty_home=tmpdir,
            )

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(listener.start())
                well_known = os.path.join(
                    tmpdir, 'sockets', f'{session_id}.sock',
                )
                self.assertTrue(os.path.exists(well_known))
                loop.run_until_complete(listener.stop())
                self.assertFalse(
                    os.path.exists(well_known),
                    'Well-known socket should be cleaned up on stop',
                )
            finally:
                loop.close()


if __name__ == '__main__':
    unittest.main()
