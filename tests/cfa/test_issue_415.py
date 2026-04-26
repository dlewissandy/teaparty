"""Tests for issue #415 — SqliteMessageBus connections leaked on all session exit paths.

Specification-based tests covering:
  AC1: Session.run() closes self._message_bus on normal completion.
  AC2: Session.run() closes self._message_bus on dry_run early exit.
  AC3: Session.run() closes self._message_bus when the orchestrator raises.
  AC4: Session.resume_from_disk() closes message_bus on normal completion.
  AC5: Session.resume_from_disk() closes message_bus when the orchestrator raises.

Dimensions covered:
  - Method: Session.run() vs Session.resume_from_disk()
  - Exit path: normal completion / dry_run (run() only) / exception
"""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from teaparty.cfa.engine import OrchestratorResult
from teaparty.cfa.session import Session
from teaparty.cfa.statemachine.cfa_state import CfaState
from teaparty.messaging.bus import EventBus
from teaparty.messaging.conversations import SqliteMessageBus


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_tmp(tc: unittest.TestCase) -> str:
    tmp = tempfile.mkdtemp(prefix='teaparty-415-test-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return tmp


class _CloseTrackingBus(SqliteMessageBus):
    """SqliteMessageBus subclass that counts close() calls.

    Used to verify that the session lifecycle calls close() exactly once
    on the message bus, regardless of the exit path.
    """
    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.close_call_count = 0

    def close(self) -> None:
        self.close_call_count += 1
        super().close()


def _make_tracking_bus_factory(tc: unittest.TestCase, db_dir: str):
    """Return a (factory, buses_list) pair.

    The factory creates _CloseTrackingBus instances rooted at db_dir.
    All created buses are appended to buses_list for inspection.
    """
    buses: list[_CloseTrackingBus] = []

    def factory(path: str) -> _CloseTrackingBus:
        bus = _CloseTrackingBus(path)
        buses.append(bus)
        return bus

    return factory, buses


def _make_mock_state_writer():
    """Return a mock StateWriter with async start/stop."""
    sw = MagicMock()
    sw.start = AsyncMock()
    sw.stop = AsyncMock()
    return sw


def _make_fake_job_info(infra_dir: str, worktree_path: str) -> dict:
    """Return a fake job dict matching what create_job() returns."""
    return {
        'job_id': 'job-test-001',
        'job_dir': infra_dir,
        'worktree_path': worktree_path,
        'branch_name': 'job-test-001--test-task',
    }


def _make_session(
    tc: unittest.TestCase,
    poc_root: str,
    projects_dir: str,
    dry_run: bool = False,
) -> Session:
    """Build a minimal Session for testing."""
    return Session(
        task='Test task',
        poc_root=poc_root,
        projects_dir=projects_dir,
        project_override='test-project',
        session_id='test-001',
        dry_run=dry_run,
        skip_learnings=True,
        skip_learning_retrieval=True,
        event_bus=EventBus(),
    )


def _patch_session_infrastructure(
    infra_dir: str,
    worktree_path: str,
    bus_factory,
    orchestrator_run_side_effect=None,
):
    """Return a list of context managers that patch all heavy Session.run() dependencies."""
    mock_state_writer = _make_mock_state_writer()

    fake_result = OrchestratorResult(terminal_state='WITHDRAWN', backtrack_count=0)

    mock_orch = MagicMock()
    if orchestrator_run_side_effect is not None:
        mock_orch.run = AsyncMock(side_effect=orchestrator_run_side_effect)
    else:
        mock_orch.run = AsyncMock(return_value=fake_result)

    patches = [
        patch('teaparty.cfa.session.SqliteMessageBus', side_effect=bus_factory),
        patch('teaparty.cfa.session.create_job',
              new=AsyncMock(return_value=_make_fake_job_info(infra_dir, worktree_path))),
        patch('teaparty.cfa.session.StateWriter', return_value=mock_state_writer),
        patch('teaparty.cfa.session.save_state'),
        patch('teaparty.cfa.session.Orchestrator', return_value=mock_orch),
        patch('teaparty.cfa.session.commit_deliverables', new=AsyncMock()),
        patch('teaparty.cfa.session.squash_merge', new=AsyncMock()),
        patch('teaparty.cfa.session.extract_learnings', new=AsyncMock()),
        patch('teaparty.cfa.session.release_worktree', new=AsyncMock()),
    ]
    return patches


# ── Layer 1: Session.run() bus lifecycle ─────────────────────────────────────

class TestSessionRunBusLifecycle(unittest.TestCase):
    """Session.run() must close the message bus on all exit paths."""

    def setUp(self):
        self.tmp = _make_tmp(self)
        self.poc_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        )))
        self.projects_dir = os.path.join(self.tmp, 'projects')
        self.infra_dir = os.path.join(self.tmp, 'infra')
        self.worktree = os.path.join(self.tmp, 'worktree')
        os.makedirs(self.infra_dir, exist_ok=True)
        os.makedirs(self.worktree, exist_ok=True)

    def _run_session(self, dry_run: bool = False, orchestrator_raise=None) -> list:
        """Run a session and return the list of tracking buses created."""
        factory, buses = _make_tracking_bus_factory(self, self.infra_dir)
        session = _make_session(
            self, self.poc_root, self.projects_dir, dry_run=dry_run,
        )

        patches = _patch_session_infrastructure(
            self.infra_dir,
            self.worktree,
            factory,
            orchestrator_run_side_effect=orchestrator_raise,
        )

        ctx_managers = []
        try:
            for p in patches:
                ctx_managers.append(p.__enter__())
            try:
                _run(session.run())
            except Exception:
                pass  # Exception path — bus must still be closed
        finally:
            for p, _ in zip(patches, ctx_managers):
                p.__exit__(None, None, None)

        return buses

    def test_run_closes_message_bus_on_normal_completion(self):
        """Session.run() must close the message bus exactly once on normal completion.

        AC1: Without this fix, the bus connection is leaked — WAL stays open across
        multiple sessions in the bridge server.
        """
        buses = self._run_session(dry_run=False)

        # The session must have created exactly one bus connection
        self.assertEqual(
            len(buses), 1,
            f'Session.run() must open exactly 1 message bus, opened {len(buses)}',
        )
        primary_bus = buses[0]

        self.assertEqual(
            primary_bus.close_call_count, 1,
            f'Session.run() must call close() exactly once on the message bus after normal '
            f'completion; close_call_count={primary_bus.close_call_count}. '
            f'Without the fix, close() is never called and the SQLite WAL stays open.',
        )

    def test_run_closes_message_bus_on_dry_run_exit(self):
        """Session.run() must close the message bus when dry_run exits early.

        AC2: The dry_run path returns before running the orchestrator. Without a
        try/finally wrapping the bus creation, the early return leaks the connection.
        """
        buses = self._run_session(dry_run=True)

        self.assertEqual(
            len(buses), 1,
            f'Session.run(dry_run=True) must open exactly 1 message bus, opened {len(buses)}',
        )
        primary_bus = buses[0]

        self.assertEqual(
            primary_bus.close_call_count, 1,
            f'Session.run() must call close() exactly once on the message bus after dry_run '
            f'exit; close_call_count={primary_bus.close_call_count}. '
            f'The early return path must not bypass the finally block.',
        )

    def test_run_closes_message_bus_when_orchestrator_raises(self):
        """Session.run() must close the message bus when the orchestrator raises an exception.

        AC3: When orchestrator.run() raises, the method exits via exception. Without a
        try/finally, the bus is leaked regardless of the exception type.
        """
        buses = self._run_session(
            dry_run=False,
            orchestrator_raise=RuntimeError('orchestrator failed'),
        )

        self.assertEqual(
            len(buses), 1,
            f'Session.run() must open exactly 1 message bus, opened {len(buses)}',
        )
        primary_bus = buses[0]

        self.assertEqual(
            primary_bus.close_call_count, 1,
            f'Session.run() must call close() exactly once on the message bus after the '
            f'orchestrator raises; close_call_count={primary_bus.close_call_count}. '
            f'Exceptions must not bypass the bus cleanup.',
        )

    def test_run_bus_is_closed_not_just_opened(self):
        """Verify the bus is both opened AND closed — not just opened (negative space).

        This guards against a broken fix where close_call_count never increments
        because close() is patched out or never reached.
        """
        buses = self._run_session(dry_run=False)
        self.assertGreater(
            len(buses), 0,
            'Session.run() must open at least one message bus; no buses were created',
        )
        for i, bus in enumerate(buses):
            self.assertGreater(
                bus.close_call_count, 0,
                f'Bus #{i} was opened but never closed — '
                f'close_call_count={bus.close_call_count}',
            )


# ── Layer 2: Session.resume_from_disk() bus lifecycle ─────────────────────────

def _write_minimal_resume_state(infra_dir: str, project_dir: str) -> None:
    """Write the minimal on-disk state that resume_from_disk() requires.

    Creates:
      - {infra_dir}/.cfa-state.json  — minimal CfA state
      - {infra_dir}/PROMPT.txt       — the task prompt
      - {infra_dir}/job.json         — job metadata
    """
    # .cfa-state.json
    cfa_state = {
        'state': 'PLAN',
        'phase': 'planning',
        'actor': 'agent',
        'history': [],
        'backtrack_count': 0,
        'task_id': 'test-resume-001',
    }
    with open(os.path.join(infra_dir, '.cfa-state.json'), 'w') as f:
        json.dump(cfa_state, f)

    # PROMPT.txt
    with open(os.path.join(infra_dir, 'PROMPT.txt'), 'w') as f:
        f.write('Resumed test task')

    # job.json
    job_state = {
        'job_id': 'job-test-resume-001',
        'slug': 'resumed-test-task',
        'status': 'running',
        'project_root': os.path.dirname(infra_dir),
    }
    with open(os.path.join(infra_dir, 'job.json'), 'w') as f:
        json.dump(job_state, f)


class TestResumeFromDiskBusLifecycle(unittest.TestCase):
    """Session.resume_from_disk() must close the message bus on all exit paths."""

    def setUp(self):
        self.tmp = _make_tmp(self)
        self.poc_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        )))
        # Set up a fake project directory with the infra_dir structure
        self.project_dir = os.path.join(self.tmp, 'projects', 'test-project')
        self.infra_dir = os.path.join(self.tmp, 'infra')
        self.worktree = os.path.join(self.tmp, 'worktree')
        os.makedirs(self.project_dir, exist_ok=True)
        os.makedirs(self.infra_dir, exist_ok=True)
        os.makedirs(self.worktree, exist_ok=True)
        _write_minimal_resume_state(self.infra_dir, self.project_dir)

    def _run_resume(self, orchestrator_raise=None) -> list:
        """Run resume_from_disk() and return the list of tracking buses created."""
        factory, buses = _make_tracking_bus_factory(self, self.infra_dir)

        mock_state_writer = _make_mock_state_writer()
        fake_cfa = CfaState(
            state='PLAN',
            
            history=[],
            backtrack_count=0,
        )
        fake_result = OrchestratorResult(terminal_state='WITHDRAWN', backtrack_count=0)
        mock_orch = MagicMock()
        if orchestrator_raise is not None:
            mock_orch.run = AsyncMock(side_effect=orchestrator_raise)
        else:
            mock_orch.run = AsyncMock(return_value=fake_result)

        patches = [
            patch('teaparty.cfa.session.SqliteMessageBus', side_effect=factory),
            patch('teaparty.cfa.session.load_state', return_value=fake_cfa),
            patch('teaparty.cfa.session.is_globally_terminal', return_value=False),
            # project_root_from_job_dir is imported locally inside resume_from_disk
            patch('teaparty.workspace.job_store.project_root_from_job_dir',
                  return_value=self.project_dir),
            patch('teaparty.cfa.session._resolve_worktree_path',
                  return_value=self.worktree),
            patch('teaparty.cfa.session.StateWriter', return_value=mock_state_writer),
            patch('teaparty.cfa.session.Orchestrator', return_value=mock_orch),
            patch('teaparty.cfa.session.commit_deliverables', new=AsyncMock()),
            patch('teaparty.cfa.session.squash_merge', new=AsyncMock()),
            patch('teaparty.cfa.session.extract_learnings', new=AsyncMock()),
            patch('teaparty.cfa.session.release_worktree', new=AsyncMock()),
            patch('teaparty.cfa.session._cleanup_stale_dispatch_sentinels',
                  return_value=0),
            patch('teaparty.cfa.session._extract_phase_session_ids',
                  return_value={}),
            patch('teaparty.cfa.session._reconstruct_last_actor_data',
                  return_value={}),
            patch('teaparty.cfa.session.Session._retrieve_memory_static',
                  return_value=''),
            patch('teaparty.cfa.session.Session._resolve_norms_static',
                  return_value=''),
        ]

        ctx_managers = []
        try:
            for p in patches:
                ctx_managers.append(p.__enter__())
            try:
                _run(Session.resume_from_disk(
                    self.infra_dir,
                    poc_root=self.poc_root,
                ))
            except Exception:
                pass  # Exception path — bus must still be closed
        finally:
            for p, _ in zip(patches, ctx_managers):
                p.__exit__(None, None, None)

        return buses

    def test_resume_closes_message_bus_on_normal_completion(self):
        """Session.resume_from_disk() must close the message bus exactly once on completion.

        AC4: Without the fix, the message_bus local variable in resume_from_disk()
        is never closed — every resumed session leaks a connection and a WAL segment.
        """
        buses = self._run_resume()

        self.assertEqual(
            len(buses), 1,
            f'resume_from_disk() must open exactly 1 message bus, opened {len(buses)}',
        )
        primary_bus = buses[0]

        self.assertEqual(
            primary_bus.close_call_count, 1,
            f'resume_from_disk() must call close() exactly once on normal completion; '
            f'close_call_count={primary_bus.close_call_count}. '
            f'Without the fix, close() is never called.',
        )

    def test_resume_closes_message_bus_when_orchestrator_raises(self):
        """Session.resume_from_disk() must close the message bus when orchestrator raises.

        AC5: The exception path in resume_from_disk() must not leak the bus.
        """
        buses = self._run_resume(
            orchestrator_raise=RuntimeError('resume orchestrator failed'),
        )

        self.assertEqual(
            len(buses), 1,
            f'resume_from_disk() must open exactly 1 message bus, opened {len(buses)}',
        )
        primary_bus = buses[0]

        self.assertEqual(
            primary_bus.close_call_count, 1,
            f'resume_from_disk() must call close() exactly once when orchestrator raises; '
            f'close_call_count={primary_bus.close_call_count}. '
            f'Exceptions in the orchestrator must not bypass bus cleanup.',
        )

    def test_resume_bus_is_not_closed_multiple_times(self):
        """close() must be called exactly once, not more (idempotency guard).

        Closing twice is wasteful; on some SQLite backends it raises. The fix
        must use a single try/finally, not double-close.
        """
        buses = self._run_resume()

        self.assertEqual(
            len(buses), 1,
            f'resume_from_disk() must open exactly 1 message bus',
        )
        self.assertEqual(
            buses[0].close_call_count, 1,
            f'close() must be called exactly 1 time, not {buses[0].close_call_count}; '
            f'double-close is incorrect.',
        )


if __name__ == '__main__':
    unittest.main()
