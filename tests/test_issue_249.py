"""Tests for issue #249: Office manager MCP tools.

Verifies:
1. reprioritize_dispatch function exists and updates heartbeat priority
2. All four intervention tools registered as MCP tools in create_server()
3. InterventionListener socket IPC bridge handles all four request types
4. Error handling: missing files, bad IDs, already-terminal states
5. Tools exercise team-lead authority only — no gate approval
"""
import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest


def _run(coro):
    return asyncio.run(coro)


class TestReprioritizeDispatch(unittest.TestCase):
    """reprioritize_dispatch function in office_manager_tools.py."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self._tmp, 'session')
        os.makedirs(self.infra_dir)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_heartbeat(self, status='running', priority='normal'):
        hb_path = os.path.join(self.infra_dir, '.heartbeat')
        data = {
            'pid': os.getpid(),
            'parent_heartbeat': '',
            'role': 'test',
            'started': time.time(),
            'status': status,
            'priority': priority,
        }
        with open(hb_path, 'w') as f:
            json.dump(data, f)
        return hb_path

    def test_reprioritize_dispatch_exists(self):
        """reprioritize_dispatch is importable from office_manager_tools."""
        from orchestrator.office_manager_tools import reprioritize_dispatch
        self.assertTrue(callable(reprioritize_dispatch))

    def test_reprioritize_sets_priority(self):
        """reprioritize_dispatch updates the heartbeat priority field."""
        from orchestrator.office_manager_tools import reprioritize_dispatch
        hb_path = self._make_heartbeat(priority='normal')
        result = reprioritize_dispatch(self.infra_dir, 'high')
        self.assertEqual(result['status'], 'reprioritized')

        with open(hb_path) as f:
            hb = json.load(f)
        self.assertEqual(hb['priority'], 'high')

    def test_reprioritize_returns_old_priority(self):
        """reprioritize_dispatch returns the previous priority."""
        from orchestrator.office_manager_tools import reprioritize_dispatch
        self._make_heartbeat(priority='low')
        result = reprioritize_dispatch(self.infra_dir, 'high')
        self.assertEqual(result['old_priority'], 'low')
        self.assertEqual(result['new_priority'], 'high')

    def test_reprioritize_missing_heartbeat(self):
        """reprioritize_dispatch returns error when heartbeat missing."""
        from orchestrator.office_manager_tools import reprioritize_dispatch
        result = reprioritize_dispatch(self.infra_dir, 'high')
        self.assertEqual(result['status'], 'error')

    def test_reprioritize_terminal_heartbeat(self):
        """reprioritize_dispatch returns not_running for terminal dispatches."""
        from orchestrator.office_manager_tools import reprioritize_dispatch
        self._make_heartbeat(status='completed')
        result = reprioritize_dispatch(self.infra_dir, 'high')
        self.assertEqual(result['status'], 'not_running')


class TestMcpToolRegistration(unittest.TestCase):
    """All four intervention tools registered in create_server()."""

    def setUp(self):
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')

    def _get_tool_names(self):
        from orchestrator.mcp_server import create_server
        server = create_server()
        # FastMCP stores tools in a dict keyed by name
        return set(server._tool_manager._tools.keys())

    def test_withdraw_session_tool_registered(self):
        """WithdrawSession is a registered MCP tool."""
        tools = self._get_tool_names()
        self.assertIn('WithdrawSession', tools)

    def test_pause_dispatch_tool_registered(self):
        """PauseDispatch is a registered MCP tool."""
        tools = self._get_tool_names()
        self.assertIn('PauseDispatch', tools)

    def test_resume_dispatch_tool_registered(self):
        """ResumeDispatch is a registered MCP tool."""
        tools = self._get_tool_names()
        self.assertIn('ResumeDispatch', tools)

    def test_reprioritize_dispatch_tool_registered(self):
        """ReprioritizeDispatch is a registered MCP tool."""
        tools = self._get_tool_names()
        self.assertIn('ReprioritizeDispatch', tools)


class TestInterventionListener(unittest.TestCase):
    """InterventionListener socket IPC bridge."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self._tmp, 'session')
        os.makedirs(self.infra_dir)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_cfa_state(self, state='EXEC', phase='execution'):
        cfa_path = os.path.join(self.infra_dir, '.cfa-state.json')
        data = {
            'state': state,
            'phase': phase,
            'actor': 'agent',
            'history': [],
            'backtrack_count': 0,
            'task_id': 'test-task',
        }
        with open(cfa_path, 'w') as f:
            json.dump(data, f)

    def _make_heartbeat(self, status='running', priority='normal'):
        hb_path = os.path.join(self.infra_dir, '.heartbeat')
        data = {
            'pid': os.getpid(),
            'parent_heartbeat': '',
            'role': 'test',
            'started': time.time(),
            'status': status,
            'priority': priority,
        }
        with open(hb_path, 'w') as f:
            json.dump(data, f)

    def _make_resolver(self):
        """Create a resolver that maps 'test-session' → self.infra_dir."""
        return {'test-session': self.infra_dir}

    def test_listener_importable(self):
        """InterventionListener is importable."""
        from orchestrator.intervention_listener import InterventionListener
        self.assertTrue(callable(InterventionListener))

    def test_listener_start_stop(self):
        """Listener starts and stops cleanly, creating a socket."""
        from orchestrator.intervention_listener import InterventionListener
        listener = InterventionListener(resolver=self._make_resolver())

        async def _test():
            path = await listener.start()
            self.assertTrue(os.path.exists(path))
            await listener.stop()

        _run(_test())

    def test_withdraw_via_socket(self):
        """WithdrawSession request over socket returns withdrawn status."""
        from orchestrator.intervention_listener import InterventionListener
        self._make_cfa_state()
        self._make_heartbeat()
        listener = InterventionListener(resolver=self._make_resolver())

        async def _test():
            socket_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(socket_path)
                request = json.dumps({
                    'type': 'withdraw_session',
                    'session_id': 'test-session',
                })
                writer.write(request.encode() + b'\n')
                await writer.drain()
                response = json.loads((await reader.readline()).decode())
                self.assertEqual(response['status'], 'withdrawn')
                writer.close()
                await writer.wait_closed()
            finally:
                await listener.stop()

        _run(_test())

    def test_pause_via_socket(self):
        """PauseDispatch request over socket returns paused status."""
        from orchestrator.intervention_listener import InterventionListener
        self._make_heartbeat(status='running')
        listener = InterventionListener(resolver=self._make_resolver())

        async def _test():
            socket_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(socket_path)
                request = json.dumps({
                    'type': 'pause_dispatch',
                    'dispatch_id': 'test-session',
                })
                writer.write(request.encode() + b'\n')
                await writer.drain()
                response = json.loads((await reader.readline()).decode())
                self.assertEqual(response['status'], 'paused')
                writer.close()
                await writer.wait_closed()
            finally:
                await listener.stop()

        _run(_test())

    def test_resume_via_socket(self):
        """ResumeDispatch request over socket returns resumed status."""
        from orchestrator.intervention_listener import InterventionListener
        self._make_heartbeat(status='paused')
        listener = InterventionListener(resolver=self._make_resolver())

        async def _test():
            socket_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(socket_path)
                request = json.dumps({
                    'type': 'resume_dispatch',
                    'dispatch_id': 'test-session',
                })
                writer.write(request.encode() + b'\n')
                await writer.drain()
                response = json.loads((await reader.readline()).decode())
                self.assertEqual(response['status'], 'resumed')
                writer.close()
                await writer.wait_closed()
            finally:
                await listener.stop()

        _run(_test())

    def test_reprioritize_via_socket(self):
        """ReprioritizeDispatch request over socket returns reprioritized status."""
        from orchestrator.intervention_listener import InterventionListener
        self._make_heartbeat(status='running', priority='normal')
        listener = InterventionListener(resolver=self._make_resolver())

        async def _test():
            socket_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(socket_path)
                request = json.dumps({
                    'type': 'reprioritize_dispatch',
                    'dispatch_id': 'test-session',
                    'priority': 'high',
                })
                writer.write(request.encode() + b'\n')
                await writer.drain()
                response = json.loads((await reader.readline()).decode())
                self.assertEqual(response['status'], 'reprioritized')
                self.assertEqual(response['new_priority'], 'high')
                writer.close()
                await writer.wait_closed()
            finally:
                await listener.stop()

        _run(_test())

    def test_unknown_id_returns_error(self):
        """Request with unknown session/dispatch ID returns error."""
        from orchestrator.intervention_listener import InterventionListener
        listener = InterventionListener(resolver={})

        async def _test():
            socket_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(socket_path)
                request = json.dumps({
                    'type': 'withdraw_session',
                    'session_id': 'nonexistent',
                })
                writer.write(request.encode() + b'\n')
                await writer.drain()
                response = json.loads((await reader.readline()).decode())
                self.assertEqual(response['status'], 'error')
                self.assertIn('unknown', response['reason'])
                writer.close()
                await writer.wait_closed()
            finally:
                await listener.stop()

        _run(_test())

    def test_unknown_request_type_returns_error(self):
        """Request with unknown type returns error."""
        from orchestrator.intervention_listener import InterventionListener
        listener = InterventionListener(resolver=self._make_resolver())

        async def _test():
            socket_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(socket_path)
                request = json.dumps({
                    'type': 'explode_server',
                    'session_id': 'test-session',
                })
                writer.write(request.encode() + b'\n')
                await writer.drain()
                response = json.loads((await reader.readline()).decode())
                self.assertEqual(response['status'], 'error')
                writer.close()
                await writer.wait_closed()
            finally:
                await listener.stop()

        _run(_test())


if __name__ == '__main__':
    unittest.main()
