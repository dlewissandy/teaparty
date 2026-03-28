#!/usr/bin/env python3
"""Tests for Issue #248: WITHDRAW as formal CfA event with hierarchical cascade.

Covers:
 1. EventType.WITHDRAW exists as a formal event type
 2. withdraw_session() publishes WITHDRAW event before killing processes
 3. Recursive cascade: kills processes in nested dispatch hierarchies
 4. Withdrawal records a learning signal (session.log entry via LOG event)
 5. WITHDRAW event includes context (session_id, phase, task)
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.tui.state_reader import SessionState, DispatchState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


def _make_session_state(
    infra_dir: str,
    cfa_state: str = 'TASK_IN_PROGRESS',
    cfa_phase: str = 'execution',
    status: str = 'active',
    dispatches: list | None = None,
    worktree_path: str = '/tmp/fake-worktree',
    task: str = 'test task',
    session_id: str = '20260327-120000',
) -> SessionState:
    """Build a minimal SessionState for testing."""
    return SessionState(
        project='test-project',
        session_id=session_id,
        worktree_name='session-120000--test',
        worktree_path=worktree_path,
        task=task,
        status=status,
        cfa_phase=cfa_phase,
        cfa_state=cfa_state,
        cfa_actor='uber_team',
        needs_input=False,
        is_orphaned=False,
        dispatches=dispatches or [],
        stream_age_seconds=10,
        duration_seconds=60,
        infra_dir=infra_dir,
    )


def _make_dispatch_state(infra_dir: str, status: str = 'active') -> DispatchState:
    """Build a minimal DispatchState for testing."""
    return DispatchState(
        team='coding',
        worktree_name='dispatch-test',
        worktree_path='/tmp/fake-dispatch-wt',
        task='dispatch task',
        status=status,
        cfa_state='TASK_IN_PROGRESS',
        cfa_phase='execution',
        is_running=True,
        infra_dir=infra_dir,
    )


def _make_nested_dispatch_tree(base_dir: str) -> dict:
    """Create a nested dispatch directory tree for testing recursive cascade.

    Structure:
      base_dir/                          (session infra)
        coding/20260327-130000/          (dispatch level 1)
          .running = 11111
          writing/20260327-130100/       (dispatch level 2 — nested)
            .running = 22222
    """
    # Level 1 dispatch
    dispatch_l1 = os.path.join(base_dir, 'coding', '20260327-130000')
    os.makedirs(dispatch_l1)
    with open(os.path.join(dispatch_l1, '.running'), 'w') as f:
        f.write('11111')

    # Level 2 dispatch (nested under level 1)
    dispatch_l2 = os.path.join(dispatch_l1, 'writing', '20260327-130100')
    os.makedirs(dispatch_l2)
    with open(os.path.join(dispatch_l2, '.running'), 'w') as f:
        f.write('22222')

    return {
        'l1_dir': dispatch_l1,
        'l1_pid': 11111,
        'l2_dir': dispatch_l2,
        'l2_pid': 22222,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestWithdrawEventType(unittest.TestCase):
    """WITHDRAW must be a formal EventType."""

    def test_withdraw_event_type_exists(self):
        """EventType must have a WITHDRAW member."""
        from projects.POC.orchestrator.events import EventType
        self.assertTrue(hasattr(EventType, 'WITHDRAW'),
                        'EventType.WITHDRAW does not exist')

    def test_withdraw_event_type_value(self):
        """EventType.WITHDRAW must have value 'withdraw'."""
        from projects.POC.orchestrator.events import EventType
        self.assertEqual(EventType.WITHDRAW.value, 'withdraw')


class TestWithdrawEventPublished(unittest.TestCase):
    """withdraw_session() must publish WITHDRAW event before killing processes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'session-infra')
        os.makedirs(self.infra_dir)

        self.cfa_path = os.path.join(self.infra_dir, '.cfa-state.json')
        cfa_data = {
            'phase': 'execution',
            'state': 'TASK_IN_PROGRESS',
            'actor': 'uber_team',
            'history': [],
        }
        with open(self.cfa_path, 'w') as f:
            json.dump(cfa_data, f)

        with open(os.path.join(self.infra_dir, '.running'), 'w') as f:
            f.write('99999')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_publishes_withdraw_event(self):
        """withdraw_session() must publish a WITHDRAW event on the EventBus."""
        from projects.POC.tui.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventBus, EventType

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()

        session = _make_session_state(self.infra_dir)
        _run(withdraw_session(session, event_bus=bus))

        event_types = [c.args[0].type for c in bus.publish.call_args_list]
        self.assertIn(EventType.WITHDRAW, event_types,
                      'WITHDRAW event was not published')

    def test_withdraw_event_before_session_completed(self):
        """WITHDRAW event must be published before SESSION_COMPLETED."""
        from projects.POC.tui.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventBus, EventType

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()

        session = _make_session_state(self.infra_dir)
        _run(withdraw_session(session, event_bus=bus))

        event_types = [c.args[0].type for c in bus.publish.call_args_list]
        withdraw_idx = event_types.index(EventType.WITHDRAW)
        completed_idx = event_types.index(EventType.SESSION_COMPLETED)
        self.assertLess(withdraw_idx, completed_idx,
                        'WITHDRAW must be published before SESSION_COMPLETED')

    def test_withdraw_event_carries_context(self):
        """WITHDRAW event must include session_id, phase, and task."""
        from projects.POC.tui.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventBus, EventType

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()

        session = _make_session_state(self.infra_dir, task='build widget')
        _run(withdraw_session(session, event_bus=bus))

        for c in bus.publish.call_args_list:
            evt = c.args[0]
            if evt.type == EventType.WITHDRAW:
                self.assertEqual(evt.session_id, session.session_id)
                self.assertEqual(evt.data['phase'], 'execution')
                self.assertEqual(evt.data['task'], 'build widget')
                break
        else:
            self.fail('WITHDRAW event not found')


class TestRecursiveCascade(unittest.TestCase):
    """withdraw_session() must recursively kill nested dispatch hierarchies."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'session-infra')
        os.makedirs(self.infra_dir)

        self.cfa_path = os.path.join(self.infra_dir, '.cfa-state.json')
        with open(self.cfa_path, 'w') as f:
            json.dump({
                'phase': 'execution', 'state': 'TASK_IN_PROGRESS',
                'actor': 'uber_team', 'history': [],
            }, f)

        with open(os.path.join(self.infra_dir, '.running'), 'w') as f:
            f.write('99999')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_kills_nested_dispatch_pids(self):
        """Must kill PIDs in nested dispatch dirs, not just direct children."""
        from projects.POC.tui.withdraw import withdraw_session

        # Create nested dispatch tree under a dispatch's infra dir
        dispatch_l1_infra = os.path.join(self.tmpdir, 'dispatch-l1')
        os.makedirs(dispatch_l1_infra)
        with open(os.path.join(dispatch_l1_infra, '.running'), 'w') as f:
            f.write('11111')

        # Nested dispatch dir under the L1 dispatch
        dispatch_l2 = os.path.join(dispatch_l1_infra, 'coding', '20260327-130100')
        os.makedirs(dispatch_l2)
        with open(os.path.join(dispatch_l2, '.running'), 'w') as f:
            f.write('22222')

        dispatch = _make_dispatch_state(dispatch_l1_infra)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        with patch('projects.POC.tui.withdraw._kill_pid') as mock_kill:
            _run(withdraw_session(session))

            killed_pids = [c.args[0] for c in mock_kill.call_args_list]
            self.assertIn(99999, killed_pids, 'Session PID not killed')
            self.assertIn(11111, killed_pids, 'L1 dispatch PID not killed')
            self.assertIn(22222, killed_pids, 'L2 nested dispatch PID not killed')

    def test_sets_withdrawn_state_on_nested_dispatches(self):
        """Must write WITHDRAWN to .cfa-state.json in nested dispatch dirs."""
        from projects.POC.tui.withdraw import withdraw_session

        dispatch_l1_infra = os.path.join(self.tmpdir, 'dispatch-l1')
        os.makedirs(dispatch_l1_infra)
        with open(os.path.join(dispatch_l1_infra, '.running'), 'w') as f:
            f.write('11111')
        # Write CfA state for L1 dispatch
        with open(os.path.join(dispatch_l1_infra, '.cfa-state.json'), 'w') as f:
            json.dump({'state': 'TASK_IN_PROGRESS', 'phase': 'execution',
                       'actor': 'coding', 'history': []}, f)

        # Nested L2 dispatch
        dispatch_l2 = os.path.join(dispatch_l1_infra, 'coding', '20260327-130100')
        os.makedirs(dispatch_l2)
        with open(os.path.join(dispatch_l2, '.running'), 'w') as f:
            f.write('22222')
        with open(os.path.join(dispatch_l2, '.cfa-state.json'), 'w') as f:
            json.dump({'state': 'TASK_IN_PROGRESS', 'phase': 'execution',
                       'actor': 'coding', 'history': []}, f)

        dispatch = _make_dispatch_state(dispatch_l1_infra)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        _run(withdraw_session(session))

        # Check L2 dispatch got WITHDRAWN state
        with open(os.path.join(dispatch_l2, '.cfa-state.json')) as f:
            cfa = json.load(f)
        self.assertEqual(cfa['state'], 'WITHDRAWN')


class TestWithdrawLearningSignal(unittest.TestCase):
    """Withdrawal must record a learning signal."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'session-infra')
        os.makedirs(self.infra_dir)

        self.cfa_path = os.path.join(self.infra_dir, '.cfa-state.json')
        with open(self.cfa_path, 'w') as f:
            json.dump({
                'phase': 'execution', 'state': 'TASK_IN_PROGRESS',
                'actor': 'uber_team', 'history': [],
            }, f)

        with open(os.path.join(self.infra_dir, '.running'), 'w') as f:
            f.write('99999')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_emits_log_event_for_learning(self):
        """withdraw_session() must emit a LOG event recording the withdrawal as a learning signal."""
        from projects.POC.tui.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventBus, EventType

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()

        session = _make_session_state(self.infra_dir, task='build widget',
                                       cfa_phase='execution')
        _run(withdraw_session(session, event_bus=bus))

        log_events = [c.args[0] for c in bus.publish.call_args_list
                      if c.args[0].type == EventType.LOG]
        # At least one LOG event should mention withdrawal
        withdrawal_logs = [e for e in log_events if 'withdraw' in e.data.get('message', '').lower()]
        self.assertTrue(len(withdrawal_logs) > 0,
                        'No LOG event recording withdrawal as learning signal')

    def test_learning_signal_includes_phase_and_task(self):
        """The withdrawal learning signal must include the phase and task context."""
        from projects.POC.tui.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventBus, EventType

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()

        session = _make_session_state(self.infra_dir, task='build widget',
                                       cfa_phase='planning')
        _run(withdraw_session(session, event_bus=bus))

        log_events = [c.args[0] for c in bus.publish.call_args_list
                      if c.args[0].type == EventType.LOG]
        withdrawal_logs = [e for e in log_events if 'withdraw' in e.data.get('message', '').lower()]
        self.assertTrue(len(withdrawal_logs) > 0, 'No withdrawal LOG event')
        msg = withdrawal_logs[0].data['message']
        self.assertIn('planning', msg, 'Learning signal must include phase')
        self.assertIn('build widget', msg, 'Learning signal must include task')


class TestWithdrawMemoryChunk(unittest.TestCase):
    """Withdrawal must record an ACT-R memory chunk in the proxy DB."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create a realistic directory hierarchy:
        # {tmpdir}/test-project/.sessions/20260327-120000/
        self.project_dir = os.path.join(self.tmpdir, 'test-project')
        sessions_dir = os.path.join(self.project_dir, '.sessions')
        self.infra_dir = os.path.join(sessions_dir, '20260327-120000')
        os.makedirs(self.infra_dir)

        self.cfa_path = os.path.join(self.infra_dir, '.cfa-state.json')
        with open(self.cfa_path, 'w') as f:
            json.dump({
                'phase': 'execution', 'state': 'TASK_IN_PROGRESS',
                'actor': 'uber_team', 'history': [],
            }, f)

        with open(os.path.join(self.infra_dir, '.running'), 'w') as f:
            f.write('99999')

        # Create a proxy memory DB
        from projects.POC.orchestrator.proxy_memory import open_proxy_db
        self.db_path = os.path.join(self.project_dir, '.proxy-memory.db')
        conn = open_proxy_db(self.db_path)
        conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_records_withdrawal_memory_chunk(self):
        """withdraw_session() must store a 'withdrawal' type chunk in proxy_memory.db."""
        from projects.POC.tui.withdraw import withdraw_session
        from projects.POC.orchestrator.proxy_memory import open_proxy_db

        session = _make_session_state(
            self.infra_dir, task='build widget', cfa_phase='execution',
            cfa_state='TASK_IN_PROGRESS',
        )
        _run(withdraw_session(session))

        conn = open_proxy_db(self.db_path)
        try:
            rows = conn.execute(
                "SELECT type, state, outcome, content FROM proxy_chunks WHERE type='withdrawal'"
            ).fetchall()
            self.assertEqual(len(rows), 1, 'Expected exactly one withdrawal chunk')
            row = rows[0]
            self.assertEqual(row[0], 'withdrawal')
            self.assertEqual(row[1], 'TASK_IN_PROGRESS')
            self.assertEqual(row[2], 'withdrawn')
            self.assertIn('build widget', row[3])
            self.assertIn('execution', row[3])
        finally:
            conn.close()

    def test_no_chunk_when_db_missing(self):
        """If proxy_memory.db doesn't exist, withdrawal still succeeds (no crash)."""
        from projects.POC.tui.withdraw import withdraw_session

        os.unlink(self.db_path)
        session = _make_session_state(self.infra_dir)
        result = _run(withdraw_session(session))
        self.assertTrue(result, 'Withdrawal should succeed even without proxy DB')


if __name__ == '__main__':
    unittest.main()
