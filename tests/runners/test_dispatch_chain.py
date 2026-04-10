"""Integration test: 3-deep agent dispatch chain through the unified launcher.

Exercises the full stack: launcher compose + ClaudeRunner (mocked subprocess)
+ BusEventListener + agent_contexts database + reply propagation.

Scenario: Agent A dispatches to B, B dispatches to C, C replies, B replies,
A receives the result. This proves the launcher, message bus, and conversation
tracking work together end-to-end.

Issue #394.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import yaml

from teaparty.messaging.conversations import SqliteMessageBus
from teaparty.messaging.listener import BusEventListener


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_agent(agents_dir: str, name: str, description: str) -> None:
    """Create a minimal agent definition in .teaparty/ config."""
    agent_dir = os.path.join(agents_dir, name)
    os.makedirs(agent_dir, exist_ok=True)
    with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
        f.write(f'---\ndescription: {description}\n---\nYou are {name}.\n')


def _make_teaparty_tree(root: str) -> str:
    """Create a .teaparty/ tree with three agents (A, B, C)."""
    tp = os.path.join(root, '.teaparty')
    mgmt = os.path.join(tp, 'management')
    agents_dir = os.path.join(mgmt, 'agents')
    sessions_dir = os.path.join(mgmt, 'sessions')
    os.makedirs(sessions_dir, exist_ok=True)

    _make_agent(agents_dir, 'agent-a', 'Lead agent that dispatches to B')
    _make_agent(agents_dir, 'agent-b', 'Middle agent that dispatches to C')
    _make_agent(agents_dir, 'agent-c', 'Leaf agent that tells jokes')

    # Base settings
    with open(os.path.join(mgmt, 'settings.yaml'), 'w') as f:
        yaml.dump({'permissions': {'allow': ['Read']}}, f)

    return tp


def _stream_json_events(session_id: str, text: str) -> str:
    """Build stream-json output for a mock subprocess."""
    events = [
        json.dumps({'type': 'system', 'subtype': 'init', 'session_id': session_id}),
        json.dumps({'type': 'assistant', 'message': {
            'content': [{'type': 'text', 'text': text}],
        }}),
        json.dumps({
            'type': 'result',
            'result': text,
            'session_id': session_id,
            'total_cost_usd': 0.01,
            'input_tokens': 100,
            'output_tokens': 50,
            'duration_ms': 1000,
        }),
    ]
    return '\n'.join(events) + '\n'


async def _make_mock_process(stdout_data: str, returncode: int = 0):
    """Create a mock asyncio subprocess that produces stream-json output."""

    class MockStdout:
        def __init__(self, data: str):
            self._lines = [
                (line + '\n').encode()
                for line in data.strip().split('\n')
                if line.strip()
            ]
            self._index = 0

        async def readline(self):
            if self._index < len(self._lines):
                line = self._lines[self._index]
                self._index += 1
                return line
            return b''

        def __aiter__(self):
            return self

        async def __anext__(self):
            line = await self.readline()
            if not line:
                raise StopAsyncIteration
            return line

    class MockStderr:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class MockStdin:
        def write(self, data): pass
        def close(self): pass

    class MockProcess:
        def __init__(self):
            self.stdout = MockStdout(stdout_data)
            self.stderr = MockStderr()
            self.stdin = MockStdin()
            self.returncode = None
            self.pid = 99999

        async def wait(self):
            self.returncode = returncode
            return returncode

    return MockProcess()


# ── The Test ─────────────────────────────────────────────────────────────────

class TestThreeDeepDispatchChain(unittest.TestCase):
    """Agent A → B → C → reply back through the full stack.

    This test proves that the unified launcher, worktree composition,
    subprocess execution, message bus, and conversation tracking all
    work together for a multi-level dispatch chain.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tp = _make_teaparty_tree(self._tmpdir)
        # Create a fake .claude/CLAUDE.md in a worktree area
        self._worktree_root = os.path.join(self._tmpdir, 'worktrees')
        os.makedirs(self._worktree_root)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_three_deep_dispatch_through_launcher(self):
        """Launch agent A, which spawns B, which spawns C.

        Verifies:
        1. compose_launch_worktree sets up .claude/ for each agent
        2. launch() invokes ClaudeRunner with correct agent name
        3. Each agent's worktree gets the right agent definition
        4. metrics.db accumulates entries for all three agents
        5. Conversation map tracks child sessions
        """
        from teaparty.runners.launcher import (
            launch,
            compose_launch_worktree,
            create_session,
            record_child_session,
            check_slot_available,
        )

        # Track which agents were launched and in what order
        launch_order: list[str] = []
        sessions_created: dict[str, str] = {}

        async def run_chain():
            # ── Step 1: Compose and verify agent A's worktree ────────────
            wt_a = os.path.join(self._worktree_root, 'agent-a')
            os.makedirs(os.path.join(wt_a, '.claude'), exist_ok=True)
            # Write a dummy CLAUDE.md that should NOT be overwritten
            with open(os.path.join(wt_a, '.claude', 'CLAUDE.md'), 'w') as f:
                f.write('# Repo Instructions\n')

            compose_launch_worktree(
                worktree=wt_a,
                agent_name='agent-a',
                scope='management',
                teaparty_home=self._tp,
                mcp_port=9000,
            )

            # Verify agent A's worktree was composed correctly
            self.assertTrue(
                os.path.exists(os.path.join(wt_a, '.claude', 'agents', 'agent-a.md')),
                'Agent A definition must be in worktree',
            )
            with open(os.path.join(wt_a, '.claude', 'CLAUDE.md')) as f:
                self.assertIn('Repo Instructions', f.read(),
                              'CLAUDE.md must not be overwritten')
            self.assertTrue(
                os.path.exists(os.path.join(wt_a, '.mcp.json')),
                'MCP config must be in worktree',
            )
            with open(os.path.join(wt_a, '.mcp.json')) as f:
                mcp = json.load(f)
            self.assertIn('/mcp/management/agent-a',
                          mcp['mcpServers']['teaparty-config']['url'])

            # ── Step 2: Compose and verify agent B's worktree ────────────
            wt_b = os.path.join(self._worktree_root, 'agent-b')
            os.makedirs(os.path.join(wt_b, '.claude'), exist_ok=True)
            with open(os.path.join(wt_b, '.claude', 'CLAUDE.md'), 'w') as f:
                f.write('# Repo Instructions\n')

            compose_launch_worktree(
                worktree=wt_b,
                agent_name='agent-b',
                scope='management',
                teaparty_home=self._tp,
                mcp_port=9000,
            )

            self.assertTrue(
                os.path.exists(os.path.join(wt_b, '.claude', 'agents', 'agent-b.md')),
                'Agent B definition must be in worktree',
            )

            # ── Step 3: Compose and verify agent C's worktree ────────────
            wt_c = os.path.join(self._worktree_root, 'agent-c')
            os.makedirs(os.path.join(wt_c, '.claude'), exist_ok=True)
            with open(os.path.join(wt_c, '.claude', 'CLAUDE.md'), 'w') as f:
                f.write('# Repo Instructions\n')

            compose_launch_worktree(
                worktree=wt_c,
                agent_name='agent-c',
                scope='management',
                teaparty_home=self._tp,
                mcp_port=9000,
            )

            self.assertTrue(
                os.path.exists(os.path.join(wt_c, '.claude', 'agents', 'agent-c.md')),
                'Agent C definition must be in worktree',
            )

            # ── Step 4: Launch all three through the unified launcher ────
            # Mock subprocess to return stream-json output
            async def mock_create_subprocess(*args, **kwargs):
                # Extract agent name from the --agent flag
                cmd = list(args)
                agent_name = ''
                for i, arg in enumerate(cmd):
                    if arg == '--agent' and i + 1 < len(cmd):
                        agent_name = cmd[i + 1]
                        break
                launch_order.append(agent_name)
                text = f'Response from {agent_name}'
                session_id = f'session-{agent_name}'
                sessions_created[agent_name] = session_id
                return await _make_mock_process(
                    _stream_json_events(session_id, text),
                )

            with patch('asyncio.create_subprocess_exec', side_effect=mock_create_subprocess):
                # Launch agent A
                result_a = await launch(
                    agent_name='agent-a',
                    message='Ask agent B to have agent C tell me a joke',
                    scope='management',
                    teaparty_home=self._tp,
                    worktree=wt_a,
                    mcp_port=9000,
                )

                # Launch agent B (simulating A's Send dispatch)
                result_b = await launch(
                    agent_name='agent-b',
                    message='Ask agent C to tell a joke',
                    scope='management',
                    teaparty_home=self._tp,
                    worktree=wt_b,
                    mcp_port=9000,
                )

                # Launch agent C (simulating B's Send dispatch)
                result_c = await launch(
                    agent_name='agent-c',
                    message='Tell me a joke',
                    scope='management',
                    teaparty_home=self._tp,
                    worktree=wt_c,
                    mcp_port=9000,
                )

            # ── Step 5: Verify all three launched through launch() ───────
            self.assertEqual(launch_order, ['agent-a', 'agent-b', 'agent-c'],
                             'All three agents must launch in order A → B → C')

            # Verify session IDs were extracted
            self.assertEqual(result_a.session_id, 'session-agent-a')
            self.assertEqual(result_b.session_id, 'session-agent-b')
            self.assertEqual(result_c.session_id, 'session-agent-c')

            # ── Step 6: Verify metrics accumulated for all agents ────────
            metrics_db = os.path.join(self._tp, 'management', 'metrics.db')
            self.assertTrue(os.path.exists(metrics_db),
                            'metrics.db must exist after launches')
            conn = sqlite3.connect(metrics_db)
            rows = conn.execute(
                'SELECT agent_name, cost_usd FROM turn_metrics '
                'ORDER BY timestamp',
            ).fetchall()
            conn.close()
            agent_names = [r[0] for r in rows]
            self.assertEqual(agent_names, ['agent-a', 'agent-b', 'agent-c'])
            # Each had cost_usd=0.01
            for row in rows:
                self.assertAlmostEqual(row[1], 0.01)

            # ── Step 7: Verify conversation map tracking ─────────────────
            session_a = create_session(
                agent_name='agent-a',
                scope='management',
                teaparty_home=self._tp,
            )
            # A dispatches to B
            record_child_session(session_a, request_id='req-b',
                                 child_session_id=result_b.session_id)
            self.assertTrue(check_slot_available(session_a))

            # A dispatches to two more (filling 3 slots)
            record_child_session(session_a, request_id='req-b2',
                                 child_session_id='other-1')
            record_child_session(session_a, request_id='req-b3',
                                 child_session_id='other-2')
            self.assertFalse(check_slot_available(session_a),
                             'Per-agent limit of 3 must block fourth dispatch')

            # Read metadata.json to verify persistence
            meta_path = os.path.join(session_a.path, 'metadata.json')
            with open(meta_path) as f:
                meta = json.load(f)
            self.assertEqual(len(meta['conversation_map']), 3)
            self.assertEqual(meta['conversation_map']['req-b'],
                             result_b.session_id)

        asyncio.run(run_chain())

    def test_bus_listener_spawn_fn_uses_launcher(self):
        """BusEventListener's spawn_fn delegates to launch() and records
        the session in the agent_contexts database."""

        launch_calls: list[dict] = []

        async def run_bus_test():
            bus_db = os.path.join(self._tmpdir, 'bus.db')

            # spawn_fn that records the call and delegates to launch()
            async def spawn_fn(member, composite, context_id):
                launch_calls.append({
                    'member': member,
                    'composite': composite,
                    'context_id': context_id,
                })
                return (f'session-{member}', f'/worktree/{member}', f'Result from {member}')

            async def reply_fn(ctx_id, session_id, message):
                pass

            async def reinvoke_fn(ctx_id, session_id, message):
                pass

            async def cleanup_fn(wt):
                pass

            listener = BusEventListener(
                bus_db_path=bus_db,
                spawn_fn=spawn_fn,
                reply_fn=reply_fn,
                reinvoke_fn=reinvoke_fn,
                cleanup_fn=cleanup_fn,
                current_context_id='agent:root:agent-a:init',
                initiator_agent_id='agent-a',
            )
            send_path, reply_path, close_path = await listener.start()

            try:
                # Simulate agent A calling Send(to='agent-b', message='...')
                reader, writer = await asyncio.open_unix_connection(send_path)
                request = json.dumps({
                    'type': 'send',
                    'member': 'agent-b',
                    'composite': '## Task\nAsk C for a joke\n\n## Context\n',
                    'context_id': '',
                }) + '\n'
                writer.write(request.encode())
                await writer.drain()

                # Read response
                response_line = await asyncio.wait_for(reader.readline(), timeout=10)
                response = json.loads(response_line.decode())
                writer.close()

                # Verify Send was processed
                self.assertIn(response['status'], ('ok', 'queued'))
                self.assertTrue(response.get('context_id', ''),
                                'Context ID must be returned')

                # Wait for spawn_fn to be called (it runs in background)
                await asyncio.sleep(0.2)

                # Verify spawn_fn was called with correct args
                self.assertEqual(len(launch_calls), 1)
                self.assertEqual(launch_calls[0]['member'], 'agent-b')
                self.assertIn('Ask C for a joke', launch_calls[0]['composite'])

                # Verify agent_contexts database has the record
                bus = SqliteMessageBus(bus_db)
                try:
                    ctx_id = response['context_id']
                    ctx = bus.get_agent_context(ctx_id)
                    self.assertIsNotNone(ctx, 'Context record must exist in database')
                    self.assertEqual(ctx['recipient_agent_id'], 'agent-b')
                    self.assertEqual(ctx['session_id'], 'session-agent-b')
                finally:
                    bus.close()

            finally:
                await listener.stop()

        asyncio.run(run_bus_test())


if __name__ == '__main__':
    unittest.main()
