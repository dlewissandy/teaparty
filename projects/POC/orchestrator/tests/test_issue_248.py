#!/usr/bin/env python3
"""Tests for Issue #248: WITHDRAW as formal CfA event with hierarchical cascade.

Spec requirements tested (from cfa-extensions/proposal.md and issue #248):

  EventBus integration:
   1. EventType.WITHDRAW exists with value 'withdraw'
   2. WITHDRAW event published before process termination
   3. WITHDRAW event carries context: session_id, phase, state, task
   4. Event ordering: WITHDRAW → LOG → SESSION_COMPLETED (strict)
   5. WITHDRAW event published before _kill_pid is called

  Cascading process termination:
   6. Session PID killed
   7. Direct dispatch PIDs killed
   8. Nested dispatch PIDs killed recursively (3 levels: session → L1 → L2)
   9. Multiple teams at same level all killed
  10. Non-dispatch entries (files, non-digit dirs) ignored
  11. SIGTERM sent first, SIGKILL fallback if process survives

  State cascade:
  12. Session .cfa-state.json set to WITHDRAWN
  13. L1 dispatch .cfa-state.json set to WITHDRAWN
  14. L2 nested dispatch .cfa-state.json set to WITHDRAWN
  15. Sentinels cleaned at nested dispatch levels
  16. history[] entry appended with actor='tui-withdraw'

  Learning signal:
  17. LOG event emitted with withdrawal context (phase, task)
  18. Memory chunk stored in proxy_memory.db with type='withdrawal'
  19. Memory chunk has correct state, outcome, task_type, content fields
  20. Withdrawal succeeds gracefully when proxy DB doesn't exist

  Guard rails:
  21. Terminal sessions (COMPLETED_WORK, WITHDRAWN) are no-ops
  22. Depth bounded — recursion stops at depth 10
"""
import asyncio
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.state_reader import SessionState, DispatchState
from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir


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
    worktree_path: str = '',
    task: str = 'test task',
    session_id: str = '20260327-120000',
    project: str = 'test-project',
) -> SessionState:
    """Build a minimal SessionState for testing."""
    if not worktree_path:
        worktree_path = infra_dir
    return SessionState(
        project=project,
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


def _make_dispatch_state(infra_dir: str, status: str = 'active',
                          team: str = 'coding') -> DispatchState:
    """Build a minimal DispatchState for testing."""
    return DispatchState(
        team=team,
        worktree_name=f'dispatch-{team}',
        worktree_path=infra_dir,
        task='dispatch task',
        status=status,
        cfa_state='TASK_IN_PROGRESS',
        cfa_phase='execution',
        is_running=True,
        infra_dir=infra_dir,
    )


def _make_infra_dir(base_dir: str, name: str = 'session-infra',
                     cfa_state: str = 'TASK_IN_PROGRESS',
                     cfa_phase: str = 'execution',
                     pid: int = 99999) -> str:
    """Create an infra directory with .cfa-state.json and .running."""
    infra = os.path.join(base_dir, name)
    os.makedirs(infra, exist_ok=True)
    with open(os.path.join(infra, '.cfa-state.json'), 'w') as f:
        json.dump({
            'phase': cfa_phase, 'state': cfa_state,
            'actor': 'uber_team', 'history': [],
        }, f)
    with open(os.path.join(infra, '.running'), 'w') as f:
        f.write(str(pid))
    return infra


def _make_nested_dispatch_dir(parent_dir: str, team: str, ts: str,
                               pid: int, cfa_state: str = 'TASK_IN_PROGRESS') -> str:
    """Create a nested dispatch directory: {parent}/{team}/{ts}/ with .running and .cfa-state.json."""
    d = os.path.join(parent_dir, team, ts)
    os.makedirs(d)
    with open(os.path.join(d, '.running'), 'w') as f:
        f.write(str(pid))
    with open(os.path.join(d, '.cfa-state.json'), 'w') as f:
        json.dump({'state': cfa_state, 'phase': 'execution',
                   'actor': team, 'history': []}, f)
    return d


def _make_project_dir_with_proxy_db(base_dir: str, project: str = 'test-project',
                                      session_ts: str = '20260327-120000') -> tuple:
    """Create a realistic project dir hierarchy with proxy_memory.db.

    Returns (infra_dir, project_dir, db_path).
    """
    from projects.POC.orchestrator.proxy_memory import open_proxy_db

    project_dir = os.path.join(base_dir, project)
    sessions_dir = os.path.join(project_dir, '.sessions')
    infra_dir = os.path.join(sessions_dir, session_ts)
    os.makedirs(infra_dir)

    with open(os.path.join(infra_dir, '.cfa-state.json'), 'w') as f:
        json.dump({
            'phase': 'execution', 'state': 'TASK_IN_PROGRESS',
            'actor': 'uber_team', 'history': [],
        }, f)
    with open(os.path.join(infra_dir, '.running'), 'w') as f:
        f.write('99999')

    db_path = os.path.join(project_dir, '.proxy-memory.db')
    conn = open_proxy_db(db_path)
    conn.close()

    return infra_dir, project_dir, db_path


def _read_cfa_state(infra_dir: str) -> dict:
    """Read .cfa-state.json from an infra dir."""
    with open(os.path.join(infra_dir, '.cfa-state.json')) as f:
        return json.load(f)


def _mock_bus():
    """Create a mock EventBus with async publish."""
    from projects.POC.orchestrator.events import EventBus
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _event_types_published(bus) -> list:
    """Extract ordered list of EventTypes from mock bus publish calls."""
    return [c.args[0].type for c in bus.publish.call_args_list]


def _find_event(bus, event_type):
    """Find the first event of a given type from mock bus publish calls."""
    for c in bus.publish.call_args_list:
        if c.args[0].type == event_type:
            return c.args[0]
    return None


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestWithdrawEventType(unittest.TestCase):
    """Spec: WITHDRAW is a formal CfA event type on the EventBus."""

    def test_withdraw_event_type_exists(self):
        """EventType must have a WITHDRAW member."""
        from projects.POC.orchestrator.events import EventType
        self.assertTrue(hasattr(EventType, 'WITHDRAW'),
                        'EventType.WITHDRAW does not exist')

    def test_withdraw_event_type_value(self):
        """EventType.WITHDRAW must have value 'withdraw'."""
        from projects.POC.orchestrator.events import EventType
        self.assertEqual(EventType.WITHDRAW.value, 'withdraw')


class TestWithdrawEventPublishing(unittest.TestCase):
    """Spec: WITHDRAW event published before killing, with full context."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = _make_infra_dir(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_publishes_withdraw_event(self):
        """withdraw_session() must publish a WITHDRAW event on the EventBus."""
        from projects.POC.orchestrator.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventType

        bus = _mock_bus()
        session = _make_session_state(self.infra_dir)
        _run(withdraw_session(session, event_bus=bus))

        self.assertIn(EventType.WITHDRAW, _event_types_published(bus),
                      'WITHDRAW event was not published')

    def test_event_ordering_withdraw_before_log_before_completed(self):
        """Strict ordering: WITHDRAW → LOG → SESSION_COMPLETED."""
        from projects.POC.orchestrator.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventType

        bus = _mock_bus()
        session = _make_session_state(self.infra_dir)
        _run(withdraw_session(session, event_bus=bus))

        types = _event_types_published(bus)
        withdraw_idx = types.index(EventType.WITHDRAW)
        log_idx = types.index(EventType.LOG)
        completed_idx = types.index(EventType.SESSION_COMPLETED)
        self.assertLess(withdraw_idx, log_idx,
                        'WITHDRAW must come before LOG')
        self.assertLess(log_idx, completed_idx,
                        'LOG must come before SESSION_COMPLETED')

    def test_withdraw_event_before_kill(self):
        """WITHDRAW event must be published before _kill_pid is called."""
        from projects.POC.orchestrator.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventType

        call_order = []

        bus = _mock_bus()
        original_publish = bus.publish

        async def tracking_publish(event):
            call_order.append(('publish', event.type))
            return await original_publish(event)
        bus.publish = tracking_publish

        def tracking_kill(pid):
            call_order.append(('kill', pid))

        session = _make_session_state(self.infra_dir)
        with patch('projects.POC.orchestrator.withdraw._kill_pid', side_effect=tracking_kill):
            _run(withdraw_session(session, event_bus=bus))

        # WITHDRAW event must appear before any kill
        withdraw_pos = next(i for i, (action, _) in enumerate(call_order)
                           if action == 'publish' and _ == EventType.WITHDRAW)
        first_kill_pos = next(i for i, (action, _) in enumerate(call_order)
                             if action == 'kill')
        self.assertLess(withdraw_pos, first_kill_pos,
                        'WITHDRAW event must be published before any process is killed')

    def test_withdraw_event_carries_context(self):
        """WITHDRAW event must include session_id, phase, state, and task."""
        from projects.POC.orchestrator.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventType

        bus = _mock_bus()
        session = _make_session_state(self.infra_dir, task='build widget',
                                       cfa_phase='planning', cfa_state='DRAFT')
        _run(withdraw_session(session, event_bus=bus))

        evt = _find_event(bus, EventType.WITHDRAW)
        self.assertIsNotNone(evt, 'WITHDRAW event not found')
        self.assertEqual(evt.session_id, '20260327-120000')
        self.assertEqual(evt.data['phase'], 'planning')
        self.assertEqual(evt.data['state'], 'DRAFT')
        self.assertEqual(evt.data['task'], 'build widget')


class TestCascadingProcessTermination(unittest.TestCase):
    """Spec: "cascading process termination ... sends SIGTERM down the tree, falling back to SIGKILL"."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = _make_infra_dir(self.tmpdir, pid=99999)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_kills_session_pid(self):
        """Session's own PID must be killed."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        session = _make_session_state(self.infra_dir)
        with patch('projects.POC.orchestrator.withdraw._kill_pid') as mock_kill:
            _run(withdraw_session(session))
            killed = [c.args[0] for c in mock_kill.call_args_list]
            self.assertIn(99999, killed)

    def test_kills_direct_dispatch_pid(self):
        """Direct dispatch PIDs must be killed."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        d1 = _make_infra_dir(self.tmpdir, 'dispatch-1', pid=11111)
        dispatch = _make_dispatch_state(d1)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        with patch('projects.POC.orchestrator.withdraw._kill_pid') as mock_kill:
            _run(withdraw_session(session))
            killed = [c.args[0] for c in mock_kill.call_args_list]
            self.assertIn(11111, killed, 'Direct dispatch PID not killed')

    def test_kills_nested_l2_dispatch_pid(self):
        """Nested dispatch PIDs (L2 under L1) must be killed recursively."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        d1 = _make_infra_dir(self.tmpdir, 'dispatch-l1', pid=11111)
        _make_nested_dispatch_dir(d1, 'coding', '20260327-130100', pid=22222)

        dispatch = _make_dispatch_state(d1)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        with patch('projects.POC.orchestrator.withdraw._kill_pid') as mock_kill:
            _run(withdraw_session(session))
            killed = [c.args[0] for c in mock_kill.call_args_list]
            self.assertIn(22222, killed, 'L2 nested dispatch PID not killed')

    def test_kills_three_level_hierarchy(self):
        """Full 3-level cascade: session → L1 dispatch → L2 nested → L3 nested."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        d1 = _make_infra_dir(self.tmpdir, 'dispatch-l1', pid=11111)
        l2_dir = _make_nested_dispatch_dir(d1, 'coding', '20260327-130100', pid=22222)
        _make_nested_dispatch_dir(l2_dir, 'writing', '20260327-130200', pid=33333)

        dispatch = _make_dispatch_state(d1)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        with patch('projects.POC.orchestrator.withdraw._kill_pid') as mock_kill:
            _run(withdraw_session(session))
            killed = [c.args[0] for c in mock_kill.call_args_list]
            self.assertIn(99999, killed, 'Session PID not killed')
            self.assertIn(11111, killed, 'L1 PID not killed')
            self.assertIn(22222, killed, 'L2 PID not killed')
            self.assertIn(33333, killed, 'L3 PID not killed')

    def test_kills_multiple_teams_at_same_level(self):
        """Multiple team dispatches at the same level must all be killed."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        d1 = _make_infra_dir(self.tmpdir, 'dispatch-l1', pid=11111)
        _make_nested_dispatch_dir(d1, 'coding', '20260327-130100', pid=22222)
        _make_nested_dispatch_dir(d1, 'writing', '20260327-130200', pid=33333)
        _make_nested_dispatch_dir(d1, 'research', '20260327-130300', pid=44444)

        dispatch = _make_dispatch_state(d1)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        with patch('projects.POC.orchestrator.withdraw._kill_pid') as mock_kill:
            _run(withdraw_session(session))
            killed = [c.args[0] for c in mock_kill.call_args_list]
            self.assertIn(22222, killed, 'coding team PID not killed')
            self.assertIn(33333, killed, 'writing team PID not killed')
            self.assertIn(44444, killed, 'research team PID not killed')

    def test_ignores_non_dispatch_entries(self):
        """Files and non-timestamp dirs under team dirs must be ignored."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        d1 = _make_infra_dir(self.tmpdir, 'dispatch-l1', pid=11111)
        # Real dispatch
        _make_nested_dispatch_dir(d1, 'coding', '20260327-130100', pid=22222)
        # Non-dispatch: file in team dir
        coding_dir = os.path.join(d1, 'coding')
        with open(os.path.join(coding_dir, 'README.md'), 'w') as f:
            f.write('noise')
        # Non-dispatch: dir not starting with digit
        os.makedirs(os.path.join(coding_dir, 'metadata'))

        dispatch = _make_dispatch_state(d1)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        with patch('projects.POC.orchestrator.withdraw._kill_pid') as mock_kill:
            _run(withdraw_session(session))
            killed = [c.args[0] for c in mock_kill.call_args_list]
            # Should kill session, dispatch-l1, and the real nested dispatch
            self.assertEqual(len(killed), 3,
                             f'Expected 3 kills (session + L1 + L2), got {killed}')

    def test_sigkill_fallback(self):
        """Spec: "sends SIGTERM ... falling back to SIGKILL". If process survives
        SIGTERM, _kill_pid must send SIGKILL."""
        from projects.POC.orchestrator.withdraw import _kill_pid

        fake_pid = 55555
        my_pgid = os.getpgid(os.getpid())  # Capture before patching
        kill_signals = []

        def mock_getpgid(pid):
            if pid == os.getpid():
                return my_pgid
            return 99999  # Different process group

        def mock_killpg(pgid, sig):
            kill_signals.append(('killpg', pgid, sig))

        def mock_kill(pid, sig):
            kill_signals.append(('kill', pid, sig))
            if sig == 0:
                return  # "still alive"

        with patch('os.getpgid', side_effect=mock_getpgid), \
             patch('os.killpg', side_effect=mock_killpg), \
             patch('os.kill', side_effect=mock_kill):
            _kill_pid(fake_pid)

        # Should see SIGTERM via killpg, then kill(pid, 0) liveness check, then SIGKILL
        sigterm_sent = any(sig == signal.SIGTERM for _, _, sig in kill_signals)
        sigkill_sent = any(sig == signal.SIGKILL for _, _, sig in kill_signals)
        self.assertTrue(sigterm_sent, 'SIGTERM not sent')
        self.assertTrue(sigkill_sent, 'SIGKILL fallback not sent')


class TestStateCascade(unittest.TestCase):
    """Spec: "CfA state transitions to WITHDRAWN" at every level."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = _make_infra_dir(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_session_state_set_to_withdrawn(self):
        """Session .cfa-state.json must be WITHDRAWN."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        session = _make_session_state(self.infra_dir)
        _run(withdraw_session(session))

        cfa = _read_cfa_state(self.infra_dir)
        self.assertEqual(cfa['state'], 'WITHDRAWN')

    def test_l1_dispatch_state_set_to_withdrawn(self):
        """L1 dispatch .cfa-state.json must be WITHDRAWN."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        d1 = _make_infra_dir(self.tmpdir, 'dispatch-l1', pid=11111)
        dispatch = _make_dispatch_state(d1)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        _run(withdraw_session(session))

        cfa = _read_cfa_state(d1)
        self.assertEqual(cfa['state'], 'WITHDRAWN')

    def test_l2_nested_dispatch_state_set_to_withdrawn(self):
        """L2 nested dispatch .cfa-state.json must be WITHDRAWN."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        d1 = _make_infra_dir(self.tmpdir, 'dispatch-l1', pid=11111)
        l2_dir = _make_nested_dispatch_dir(d1, 'coding', '20260327-130100', pid=22222)

        dispatch = _make_dispatch_state(d1)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        _run(withdraw_session(session))

        cfa = _read_cfa_state(l2_dir)
        self.assertEqual(cfa['state'], 'WITHDRAWN')

    def test_history_entry_appended(self):
        """history[] must have a withdraw entry with actor='tui-withdraw'."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        session = _make_session_state(self.infra_dir)
        _run(withdraw_session(session))

        cfa = _read_cfa_state(self.infra_dir)
        last_entry = cfa['history'][-1]
        self.assertEqual(last_entry['state'], 'WITHDRAWN')
        self.assertEqual(last_entry['action'], 'withdraw')
        self.assertEqual(last_entry['actor'], 'tui-withdraw')
        self.assertIn('timestamp', last_entry)

    def test_sentinels_cleaned_at_nested_levels(self):
        """.running files must be removed at nested dispatch levels."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        d1 = _make_infra_dir(self.tmpdir, 'dispatch-l1', pid=11111)
        l2_dir = _make_nested_dispatch_dir(d1, 'coding', '20260327-130100', pid=22222)

        dispatch = _make_dispatch_state(d1)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        _run(withdraw_session(session))

        # Session sentinels cleaned
        self.assertFalse(os.path.exists(os.path.join(self.infra_dir, '.running')))
        # L1 dispatch sentinels cleaned
        self.assertFalse(os.path.exists(os.path.join(d1, '.running')))
        # L2 nested dispatch sentinels cleaned
        self.assertFalse(os.path.exists(os.path.join(l2_dir, '.running')))


class TestLearningSignal(unittest.TestCase):
    """Spec: "Both events are recorded as memory chunks" + session log."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir, self.project_dir, self.db_path = \
            _make_project_dir_with_proxy_db(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_log_event_emitted(self):
        """LOG event with withdrawal context must be emitted."""
        from projects.POC.orchestrator.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventType

        bus = _mock_bus()
        session = _make_session_state(self.infra_dir, task='build widget',
                                       cfa_phase='execution')
        _run(withdraw_session(session, event_bus=bus))

        log_evt = _find_event(bus, EventType.LOG)
        self.assertIsNotNone(log_evt, 'No LOG event emitted')
        msg = log_evt.data['message'].lower()
        self.assertIn('withdraw', msg)

    def test_log_event_includes_phase_and_task(self):
        """LOG event must name the phase and task for learning extraction."""
        from projects.POC.orchestrator.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventType

        bus = _mock_bus()
        session = _make_session_state(self.infra_dir, task='redesign navbar',
                                       cfa_phase='planning')
        _run(withdraw_session(session, event_bus=bus))

        log_evt = _find_event(bus, EventType.LOG)
        msg = log_evt.data['message']
        self.assertIn('planning', msg, 'Phase not in LOG message')
        self.assertIn('redesign navbar', msg, 'Task not in LOG message')

    def test_memory_chunk_stored(self):
        """A 'withdrawal' chunk must be stored in proxy_memory.db."""
        from projects.POC.orchestrator.withdraw import withdraw_session
        from projects.POC.orchestrator.proxy_memory import open_proxy_db

        session = _make_session_state(self.infra_dir, task='build widget',
                                       cfa_state='TASK_IN_PROGRESS')
        _run(withdraw_session(session))

        conn = open_proxy_db(self.db_path)
        try:
            rows = conn.execute(
                "SELECT type, state, outcome, task_type, content "
                "FROM proxy_chunks WHERE type='withdrawal'"
            ).fetchall()
            self.assertEqual(len(rows), 1, 'Expected exactly one withdrawal chunk')
            chunk_type, state, outcome, task_type, content = rows[0]
            self.assertEqual(chunk_type, 'withdrawal')
            self.assertEqual(state, 'TASK_IN_PROGRESS')
            self.assertEqual(outcome, 'withdrawn')
            self.assertEqual(task_type, 'test-project')
            self.assertIn('build widget', content)
            self.assertIn('execution', content)
            self.assertIn('TASK_IN_PROGRESS', content)
        finally:
            conn.close()

    def test_memory_chunk_with_different_phase(self):
        """Memory chunk content must reflect the actual phase at withdrawal."""
        from projects.POC.orchestrator.withdraw import withdraw_session
        from projects.POC.orchestrator.proxy_memory import open_proxy_db

        session = _make_session_state(self.infra_dir, task='write docs',
                                       cfa_phase='intent', cfa_state='PROPOSAL')
        _run(withdraw_session(session))

        conn = open_proxy_db(self.db_path)
        try:
            row = conn.execute(
                "SELECT state, content FROM proxy_chunks WHERE type='withdrawal'"
            ).fetchone()
            self.assertEqual(row[0], 'PROPOSAL')
            self.assertIn('intent', row[1])
        finally:
            conn.close()

    def test_no_crash_when_db_missing(self):
        """Withdrawal must succeed gracefully when proxy DB doesn't exist."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        os.unlink(self.db_path)
        session = _make_session_state(self.infra_dir)
        result = _run(withdraw_session(session))
        self.assertTrue(result, 'Withdrawal should succeed without proxy DB')


class TestGuardRails(unittest.TestCase):
    """Terminal sessions are no-ops; recursion is depth-bounded."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_noop_on_completed_work(self):
        """Withdrawing a COMPLETED_WORK session must return False and change nothing."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        infra = _make_infra_dir(self.tmpdir, cfa_state='COMPLETED_WORK')
        session = _make_session_state(infra, cfa_state='COMPLETED_WORK')
        result = _run(withdraw_session(session))
        self.assertFalse(result)
        cfa = _read_cfa_state(infra)
        self.assertEqual(cfa['state'], 'COMPLETED_WORK')

    def test_noop_on_already_withdrawn(self):
        """Withdrawing an already-WITHDRAWN session must return False."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        infra = _make_infra_dir(self.tmpdir, cfa_state='WITHDRAWN')
        session = _make_session_state(infra, cfa_state='WITHDRAWN')
        result = _run(withdraw_session(session))
        self.assertFalse(result)

    def test_depth_bounded_recursion(self):
        """_kill_nested_dispatches must stop at depth 10 to prevent runaway traversal."""
        from projects.POC.orchestrator.withdraw import _kill_nested_dispatches

        # Build a chain 12 levels deep — only 11 should be visited (0..10)
        base = os.path.join(self.tmpdir, 'deep')
        os.makedirs(base)
        current = base
        pids_written = []
        for i in range(12):
            current = _make_nested_dispatch_dir(current, 'coding', f'2026032{i:1d}-130000',
                                                 pid=10000 + i)
            pids_written.append(10000 + i)

        killed = []
        with patch('projects.POC.orchestrator.withdraw._kill_pid', side_effect=lambda pid: killed.append(pid)):
            _kill_nested_dispatches(base)

        # Depth 0 through 10 = 11 levels, but the 12th (depth=11) should be skipped
        self.assertIn(10000, killed, 'Depth 0 not killed')
        self.assertIn(10010, killed, 'Depth 10 not killed')
        self.assertNotIn(10011, killed, 'Depth 11 should be skipped (beyond bound)')


if __name__ == '__main__':
    unittest.main()
