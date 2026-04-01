"""Tests for Issue #358: Bus dispatch — reinvoke_fn and CfA async state.

Acceptance criteria:
AC1. AWAITING_REPLIES is a valid execution state in the CfA state machine JSON.
AC2. Transition from TASK_IN_PROGRESS via 'send-and-wait' reaches AWAITING_REPLIES.
AC3. Transition from AWAITING_REPLIES via 'resume' reaches TASK_IN_PROGRESS.
AC4. engine._bus_reinvoke_agent exists and is wired as reinvoke_fn in BusEventListener.
AC5. BusEventListener only calls reinvoke_fn when pending_count reaches 0 (not on every reply).
AC6. reinvoke_fn is called with the PARENT context's session_id, not the worker's.
AC7. engine._bus_reinvoke_agent calls AgentSpawner.spawn with resume_session=session_id.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest

from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


def _run(coro):
    return asyncio.run(coro)


# ── AC1-AC3: CfA state machine — AWAITING_REPLIES ─────────────────────────────


class TestAwaitingRepliesState(unittest.TestCase):
    """AC1-AC3: AWAITING_REPLIES must exist and have correct transitions."""

    def _machine(self):
        import json
        path = _REPO_ROOT / 'cfa-state-machine.json'
        with open(path) as f:
            return json.load(f)

    def test_awaiting_replies_is_in_execution_states(self):
        """AC1: AWAITING_REPLIES must be listed in the execution phase states."""
        machine = self._machine()
        execution_states = machine['phases']['execution']['states']
        self.assertIn(
            'AWAITING_REPLIES',
            execution_states,
            'cfa-state-machine.json must include AWAITING_REPLIES in execution states',
        )

    def test_task_in_progress_has_send_and_wait_transition(self):
        """AC2: TASK_IN_PROGRESS must have a send-and-wait action leading to AWAITING_REPLIES."""
        machine = self._machine()
        edges = machine['transitions'].get('TASK_IN_PROGRESS', [])
        send_wait = [e for e in edges if e['action'] == 'send-and-wait']
        self.assertTrue(
            send_wait,
            "TASK_IN_PROGRESS must have a 'send-and-wait' transition edge",
        )
        self.assertEqual(
            send_wait[0]['to'],
            'AWAITING_REPLIES',
            "send-and-wait from TASK_IN_PROGRESS must lead to AWAITING_REPLIES",
        )

    def test_awaiting_replies_has_resume_transition_to_task_in_progress(self):
        """AC3: AWAITING_REPLIES must have a 'resume' action returning to TASK_IN_PROGRESS."""
        machine = self._machine()
        edges = machine['transitions'].get('AWAITING_REPLIES', [])
        resume_edges = [e for e in edges if e['action'] == 'resume']
        self.assertTrue(
            resume_edges,
            "AWAITING_REPLIES must have a 'resume' transition edge",
        )
        self.assertEqual(
            resume_edges[0]['to'],
            'TASK_IN_PROGRESS',
            "resume from AWAITING_REPLIES must lead to TASK_IN_PROGRESS",
        )

    def test_cfa_state_transition_send_and_wait(self):
        """AC2: cfa_state.transition() must move TASK_IN_PROGRESS → AWAITING_REPLIES via send-and-wait."""
        from scripts.cfa_state import make_initial_state, transition, set_state_direct

        cfa = make_initial_state()
        cfa = set_state_direct(cfa, 'TASK_IN_PROGRESS')
        cfa = transition(cfa, 'send-and-wait')
        self.assertEqual(cfa.state, 'AWAITING_REPLIES')
        self.assertEqual(cfa.phase, 'execution')

    def test_cfa_state_transition_resume(self):
        """AC3: cfa_state.transition() must move AWAITING_REPLIES → TASK_IN_PROGRESS via resume."""
        from scripts.cfa_state import set_state_direct, transition, make_initial_state

        cfa = make_initial_state()
        cfa = set_state_direct(cfa, 'AWAITING_REPLIES')
        cfa = transition(cfa, 'resume')
        self.assertEqual(cfa.state, 'TASK_IN_PROGRESS')

    def test_awaiting_replies_is_not_globally_terminal(self):
        """AWAITING_REPLIES must not be treated as a terminal state."""
        from scripts.cfa_state import is_globally_terminal, is_phase_terminal

        self.assertFalse(is_globally_terminal('AWAITING_REPLIES'))
        self.assertFalse(is_phase_terminal('AWAITING_REPLIES'))

    def test_awaiting_replies_phase_is_execution(self):
        """phase_for_state('AWAITING_REPLIES') must return 'execution'."""
        from scripts.cfa_state import phase_for_state

        self.assertEqual(phase_for_state('AWAITING_REPLIES'), 'execution')


# ── AC5-AC6: BusEventListener — pending_count-driven reinvoke ─────────────────


def _make_bus(tmpdir: str):
    from orchestrator.messaging import SqliteMessageBus
    return SqliteMessageBus(os.path.join(tmpdir, 'bus.db'))


def _run_async(coro):
    return asyncio.run(coro)


class TestBusEventListenerReinvokeTrigger(unittest.TestCase):
    """AC5-AC6: reinvoke_fn must only fire when pending_count reaches 0,
    using the parent context's session_id."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bus_db = os.path.join(self.tmpdir, 'bus.db')
        self.reinvoke_calls = []

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _setup_parent_and_worker(
        self,
        *,
        parent_ctx: str,
        parent_session: str,
        worker_ctx: str,
        worker_session: str,
        num_workers: int = 1,
    ):
        """Create parent context (with pending_count = num_workers) and one worker context.

        Uses create_agent_context_and_increment_parent so the worker's
        parent_context_id is set and the parent's pending_count is incremented
        atomically — matching how BusEventListener creates contexts in production.
        """
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(parent_ctx, 'proj/lead', 'proj/worker')
        bus.set_agent_context_session_id(parent_ctx, parent_session)
        # Create worker(s) with parent linkage; increment parent's pending_count
        bus.create_agent_context_and_increment_parent(
            worker_ctx,
            initiator_agent_id='proj/worker',
            recipient_agent_id='proj/sub',
            parent_context_id=parent_ctx,
        )
        bus.set_agent_context_session_id(worker_ctx, worker_session)
        # If num_workers > 1, add extra pending_count increments (simulating additional workers)
        for _ in range(num_workers - 1):
            bus.increment_pending_count(parent_ctx)
        bus.close()

    async def _captured_reinvoke(self, context_id: str, session_id: str, message: str) -> None:
        self.reinvoke_calls.append({
            'context_id': context_id,
            'session_id': session_id,
            'message': message,
        })

    def test_reinvoke_not_called_when_pending_count_above_zero(self):
        """AC5: reinvoke_fn must NOT be called when pending_count > 0 after decrement."""
        from orchestrator.bus_event_listener import BusEventListener

        PARENT_CTX = 'agent:proj/lead:proj/worker:uuid1'
        PARENT_SESSION = 'lead-session-111'
        WORKER_CTX = 'agent:proj/worker:proj/sub:uuid2'
        WORKER_SESSION = 'worker-session-222'

        # Two workers — reply from one still leaves pending_count = 1
        self._setup_parent_and_worker(
            parent_ctx=PARENT_CTX,
            parent_session=PARENT_SESSION,
            worker_ctx=WORKER_CTX,
            worker_session=WORKER_SESSION,
            num_workers=2,
        )

        listener = BusEventListener(
            bus_db_path=self.bus_db,
            reinvoke_fn=self._captured_reinvoke,
            current_context_id=WORKER_CTX,
        )

        # Simulate a Reply from the worker
        async def run():
            send_path, reply_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(reply_path)
                import json
                writer.write(json.dumps({'type': 'reply', 'message': 'done'}).encode() + b'\n')
                await writer.drain()
                await reader.readline()
                writer.close()
                await asyncio.sleep(0.1)
            finally:
                await listener.stop()

        _run_async(run())

        self.assertEqual(
            len(self.reinvoke_calls),
            0,
            'reinvoke_fn must not be called when pending_count is still > 0 after reply',
        )

    def test_reinvoke_called_when_pending_count_reaches_zero(self):
        """AC5: reinvoke_fn MUST be called when pending_count reaches 0."""
        from orchestrator.bus_event_listener import BusEventListener

        PARENT_CTX = 'agent:proj/lead:proj/worker:uuid3'
        PARENT_SESSION = 'lead-session-333'
        WORKER_CTX = 'agent:proj/worker:proj/sub:uuid4'
        WORKER_SESSION = 'worker-session-444'

        # One worker — reply makes pending_count = 0
        self._setup_parent_and_worker(
            parent_ctx=PARENT_CTX,
            parent_session=PARENT_SESSION,
            worker_ctx=WORKER_CTX,
            worker_session=WORKER_SESSION,
            num_workers=1,
        )

        listener = BusEventListener(
            bus_db_path=self.bus_db,
            reinvoke_fn=self._captured_reinvoke,
            current_context_id=WORKER_CTX,
        )

        async def run():
            send_path, reply_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(reply_path)
                import json
                writer.write(json.dumps({'type': 'reply', 'message': 'task complete'}).encode() + b'\n')
                await writer.drain()
                await reader.readline()
                writer.close()
                await asyncio.sleep(0.2)
            finally:
                await listener.stop()

        _run_async(run())

        self.assertEqual(
            len(self.reinvoke_calls),
            1,
            'reinvoke_fn must be called exactly once when pending_count reaches 0',
        )

    def test_reinvoke_called_with_parent_context_id(self):
        """AC6: reinvoke_fn must receive the PARENT context_id, not the worker's."""
        from orchestrator.bus_event_listener import BusEventListener

        PARENT_CTX = 'agent:proj/lead:proj/worker:uuid5'
        PARENT_SESSION = 'lead-session-555'
        WORKER_CTX = 'agent:proj/worker:proj/sub:uuid6'
        WORKER_SESSION = 'worker-session-666'

        self._setup_parent_and_worker(
            parent_ctx=PARENT_CTX,
            parent_session=PARENT_SESSION,
            worker_ctx=WORKER_CTX,
            worker_session=WORKER_SESSION,
            num_workers=1,
        )

        listener = BusEventListener(
            bus_db_path=self.bus_db,
            reinvoke_fn=self._captured_reinvoke,
            current_context_id=WORKER_CTX,
        )

        async def run():
            send_path, reply_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(reply_path)
                import json
                writer.write(json.dumps({'type': 'reply', 'message': 'done'}).encode() + b'\n')
                await writer.drain()
                await reader.readline()
                writer.close()
                await asyncio.sleep(0.2)
            finally:
                await listener.stop()

        _run_async(run())

        self.assertEqual(len(self.reinvoke_calls), 1)
        call = self.reinvoke_calls[0]
        self.assertEqual(
            call['context_id'],
            PARENT_CTX,
            f"reinvoke_fn must receive PARENT context_id '{PARENT_CTX}', got '{call['context_id']}'",
        )

    def test_reinvoke_called_with_parent_session_id_not_worker_session_id(self):
        """AC6: reinvoke_fn must receive the PARENT's session_id, not the worker's."""
        from orchestrator.bus_event_listener import BusEventListener

        PARENT_CTX = 'agent:proj/lead:proj/worker:uuid7'
        PARENT_SESSION = 'lead-session-777'
        WORKER_CTX = 'agent:proj/worker:proj/sub:uuid8'
        WORKER_SESSION = 'worker-session-888'

        self._setup_parent_and_worker(
            parent_ctx=PARENT_CTX,
            parent_session=PARENT_SESSION,
            worker_ctx=WORKER_CTX,
            worker_session=WORKER_SESSION,
            num_workers=1,
        )

        listener = BusEventListener(
            bus_db_path=self.bus_db,
            reinvoke_fn=self._captured_reinvoke,
            current_context_id=WORKER_CTX,
        )

        async def run():
            send_path, reply_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(reply_path)
                import json
                writer.write(json.dumps({'type': 'reply', 'message': 'done'}).encode() + b'\n')
                await writer.drain()
                await reader.readline()
                writer.close()
                await asyncio.sleep(0.2)
            finally:
                await listener.stop()

        _run_async(run())

        self.assertEqual(len(self.reinvoke_calls), 1)
        call = self.reinvoke_calls[0]
        self.assertEqual(
            call['session_id'],
            PARENT_SESSION,
            f"reinvoke_fn must receive PARENT session_id '{PARENT_SESSION}', got '{call['session_id']}'",
        )
        self.assertNotEqual(
            call['session_id'],
            WORKER_SESSION,
            'reinvoke_fn must NOT receive the worker session_id',
        )


# ── AC4/AC7: engine._bus_reinvoke_agent ───────────────────────────────────────


class TestEngineReinvokeAgent(unittest.TestCase):
    """AC4/AC7: engine._bus_reinvoke_agent must exist and call AgentSpawner.spawn with resume_session."""

    def test_engine_has_bus_reinvoke_agent_method(self):
        """AC4: Orchestrator must have a _bus_reinvoke_agent method."""
        from orchestrator.engine import Orchestrator
        self.assertTrue(
            hasattr(Orchestrator, '_bus_reinvoke_agent'),
            'Orchestrator must have a _bus_reinvoke_agent method',
        )

    def test_bus_reinvoke_agent_is_async(self):
        """AC7: _bus_reinvoke_agent must be an async method (runs blocking spawn in executor)."""
        from orchestrator.engine import Orchestrator

        self.assertTrue(
            asyncio.iscoroutinefunction(Orchestrator._bus_reinvoke_agent),
            '_bus_reinvoke_agent must be an async method',
        )

    def test_engine_wires_reinvoke_fn_to_bus_event_listener(self):
        """AC4: Orchestrator.run must pass _bus_reinvoke_agent as reinvoke_fn to BusEventListener."""
        import inspect
        from orchestrator.engine import Orchestrator

        source = inspect.getsource(Orchestrator.run)
        self.assertIn(
            'reinvoke_fn',
            source,
            'Orchestrator.run must pass reinvoke_fn= to BusEventListener',
        )
        self.assertIn(
            '_bus_reinvoke_agent',
            source,
            'Orchestrator.run must wire _bus_reinvoke_agent as reinvoke_fn',
        )

    def test_bus_reinvoke_agent_calls_spawn_with_correct_session_id(self):
        """AC7: _bus_reinvoke_agent must call AgentSpawner.spawn with resume_session=session_id at runtime."""
        import unittest.mock
        from orchestrator.engine import Orchestrator

        # Build a minimal Orchestrator with the fields _bus_reinvoke_agent accesses.
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, 'project')
            os.makedirs(project_dir)
            infra_dir = os.path.join(tmpdir, 'infra', 'agents')
            os.makedirs(infra_dir)

            orch = object.__new__(Orchestrator)
            orch.poc_root = tmpdir
            orch.project_workdir = project_dir
            orch.infra_dir = os.path.join(tmpdir, 'infra')
            orch._mcp_config = {}

            spawn_calls = []

            def fake_spawn(_self, task_message, *, worktree, role, project_dir, mcp_config=None, resume_session='', **kw):
                spawn_calls.append({'resume_session': resume_session, 'role': role})
                return 'new-session-id'

            with unittest.mock.patch('orchestrator.agent_spawner.AgentSpawner.spawn', fake_spawn), \
                 unittest.mock.patch('subprocess.run') as mock_run, \
                 unittest.mock.patch('orchestrator.messaging.inject_composite_into_history'):
                mock_run.return_value = unittest.mock.MagicMock(returncode=0)
                asyncio.run(orch._bus_reinvoke_agent(
                    'agent:proj/lead:proj/worker:uuid1',
                    'test-session-abc',
                    'reply text',
                ))

        self.assertEqual(len(spawn_calls), 1, '_bus_reinvoke_agent must call spawner.spawn exactly once')
        self.assertEqual(
            spawn_calls[0]['resume_session'],
            'test-session-abc',
            '_bus_reinvoke_agent must pass the caller session_id as resume_session',
        )

    def test_bus_reinvoke_agent_injects_reply_into_history_before_spawn(self):
        """Finding 1: _bus_reinvoke_agent must inject reply into caller history before --resume.

        Spec (conversation-model.md step 4): 'appends it to the caller's local
        conversation history file, then re-invokes caller via --resume $SESSION_ID.'
        inject_composite_into_history must be called before spawner.spawn.
        """
        import unittest.mock
        from orchestrator.engine import Orchestrator

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, 'project')
            os.makedirs(project_dir)
            os.makedirs(os.path.join(tmpdir, 'infra', 'agents'))

            orch = object.__new__(Orchestrator)
            orch.poc_root = tmpdir
            orch.project_workdir = project_dir
            orch.infra_dir = os.path.join(tmpdir, 'infra')
            orch._mcp_config = {}

            call_order = []

            def fake_inject(session_file, composite, session_id, cwd, **kw):
                call_order.append(('inject', session_id, composite))

            def fake_spawn(_self, task_message, *, worktree, role, project_dir, mcp_config=None, resume_session='', **kw):
                call_order.append(('spawn', resume_session))
                return 'new-session-id'

            with unittest.mock.patch('orchestrator.agent_spawner.AgentSpawner.spawn', fake_spawn), \
                 unittest.mock.patch('subprocess.run') as mock_run, \
                 unittest.mock.patch('orchestrator.messaging.inject_composite_into_history', fake_inject):
                mock_run.return_value = unittest.mock.MagicMock(returncode=0)
                asyncio.run(orch._bus_reinvoke_agent(
                    'agent:proj/lead:proj/worker:uuid2',
                    'caller-session-xyz',
                    'worker reply content',
                ))

        self.assertIn(
            ('inject', 'caller-session-xyz', 'worker reply content'),
            call_order,
            '_bus_reinvoke_agent must call inject_composite_into_history with session_id and reply',
        )
        inject_idx = next(i for i, c in enumerate(call_order) if c[0] == 'inject')
        spawn_idx = next(i for i, c in enumerate(call_order) if c[0] == 'spawn')
        self.assertLess(
            inject_idx, spawn_idx,
            'inject_composite_into_history must be called BEFORE spawner.spawn',
        )


# ── Finding 2: per-agent re-invocation lock ────────────────────────────────────


class TestPerAgentReinvokeLock(unittest.TestCase):
    """Finding 2: BusEventListener must serialize concurrent --resume calls per agent.

    Spec (conversation-model.md): 'Only one --resume call for a given agent_id
    can be active at a time. A second re-invocation request queues until the
    first completes.'
    """

    def test_locked_reinvoke_serializes_concurrent_calls_for_same_context(self):
        """Concurrent _locked_reinvoke calls for the same context_id must run sequentially."""
        from orchestrator.bus_event_listener import BusEventListener

        order = []
        gate = asyncio.Event()

        async def slow_reinvoke(context_id: str, session_id: str, message: str) -> None:
            order.append(f'start:{message}')
            await gate.wait()
            order.append(f'end:{message}')

        listener = BusEventListener(reinvoke_fn=slow_reinvoke)

        async def run():
            # Schedule both concurrently — second must wait for first to finish.
            t1 = asyncio.create_task(listener._locked_reinvoke('ctx-A', 's1', 'first'))
            t2 = asyncio.create_task(listener._locked_reinvoke('ctx-A', 's1', 'second'))
            await asyncio.sleep(0.05)  # let both tasks start competing for the lock
            gate.set()                  # unblock first; second should then run
            await asyncio.gather(t1, t2)

        asyncio.run(run())

        self.assertEqual(
            order,
            ['start:first', 'end:first', 'start:second', 'end:second'],
            'reinvoke calls for the same context_id must be fully serialized',
        )

    def test_locked_reinvoke_allows_concurrent_calls_for_different_contexts(self):
        """Concurrent _locked_reinvoke calls for DIFFERENT context_ids must run in parallel."""
        from orchestrator.bus_event_listener import BusEventListener

        started = []
        gate = asyncio.Event()

        async def gated_reinvoke(context_id: str, session_id: str, message: str) -> None:
            started.append(context_id)
            await gate.wait()

        listener = BusEventListener(reinvoke_fn=gated_reinvoke)

        async def run():
            t1 = asyncio.create_task(listener._locked_reinvoke('ctx-A', 's1', 'msg'))
            t2 = asyncio.create_task(listener._locked_reinvoke('ctx-B', 's2', 'msg'))
            await asyncio.sleep(0.05)  # both should have started before gate opens
            gate.set()
            await asyncio.gather(t1, t2)

        asyncio.run(run())

        self.assertEqual(
            set(started),
            {'ctx-A', 'ctx-B'},
            'reinvoke calls for different context_ids must be allowed to run concurrently',
        )


if __name__ == '__main__':
    unittest.main()
