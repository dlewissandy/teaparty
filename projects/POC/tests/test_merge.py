"""Unit tests for merge.py and the ApprovalGate elapsed-time guard in actors.py.

Covers:
  - _is_excluded() filter logic
  - MergeConflictEscalation exception attributes
  - ApprovalGate._proxy_decide() elapsed-time guard (Issue #122)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on the path so POC imports resolve.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from projects.POC.orchestrator.merge import _is_excluded, MergeConflictEscalation
from projects.POC.orchestrator.actors import ApprovalGate, MIN_EXECUTION_SECONDS
from projects.POC.scripts.approval_gate import make_model, record_outcome, save_model

# NOTE: _proxy_decide uses `import time` inline, so `time` is not a module-level
# attribute of actors.  We patch `time.monotonic` at the stdlib level instead.


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _dummy_input(request):
    """Stub InputProvider — should never be called in unit tests."""
    raise AssertionError("_dummy_input should not be called in unit tests")


def _make_warm_proxy_model(state: str, task_type: str) -> str:
    """Create a proxy model file with enough approvals to reach auto-approve confidence.

    Records well above COLD_START_THRESHOLD approvals so the model is not in
    cold-start and has a high EMA approval rate.  Returns the path to the file.
    """
    model = make_model()
    for _ in range(10):
        model = record_outcome(model, state, task_type, 'approve')
    path = tempfile.mktemp(suffix='.json')
    save_model(model, path)
    return path


# ── Tests: _is_excluded() ─────────────────────────────────────────────────────

class TestIsExcluded(unittest.TestCase):
    """Test the _is_excluded() filter used to avoid committing infrastructure files."""

    # --- Files that SHOULD be excluded ---

    def test_ds_store_excluded(self):
        self.assertTrue(_is_excluded('.DS_Store'))

    def test_memory_db_excluded(self):
        self.assertTrue(_is_excluded('.memory.db'))

    def test_memory_db_shm_excluded(self):
        self.assertTrue(_is_excluded('.memory.db-shm'))

    def test_memory_db_wal_excluded(self):
        self.assertTrue(_is_excluded('.memory.db-wal'))

    def test_proxy_confidence_json_excluded(self):
        self.assertTrue(_is_excluded('.proxy-confidence.json'))

    def test_escalation_md_excluded(self):
        self.assertTrue(_is_excluded('ESCALATION.md'))

    def test_observations_md_excluded(self):
        self.assertTrue(_is_excluded('OBSERVATIONS.md'))

    def test_worktrees_json_excluded(self):
        self.assertTrue(_is_excluded('worktrees.json'))

    def test_nested_ds_store_excluded(self):
        """Basename extraction must work for nested paths."""
        self.assertTrue(_is_excluded('subdir/.DS_Store'))

    def test_hidden_db_file_excluded(self):
        """Hidden files ending in .db should be excluded."""
        self.assertTrue(_is_excluded('.something.db'))

    def test_hidden_db_shm_file_excluded(self):
        self.assertTrue(_is_excluded('.something.db-shm'))

    def test_hidden_db_wal_file_excluded(self):
        self.assertTrue(_is_excluded('.something.db-wal'))

    def test_hidden_json_file_excluded(self):
        """Hidden files ending in .json should be excluded."""
        self.assertTrue(_is_excluded('.state.json'))

    def test_hidden_lock_file_excluded(self):
        """Hidden files ending in .lock should be excluded."""
        self.assertTrue(_is_excluded('.session.lock'))

    def test_nested_hidden_db_excluded(self):
        """Nested hidden .db file should be excluded via basename check."""
        self.assertTrue(_is_excluded('infra/.runtime.db'))

    # --- Files that should NOT be excluded ---

    def test_source_python_file_not_excluded(self):
        self.assertFalse(_is_excluded('src/main.py'))

    def test_nested_js_file_not_excluded(self):
        self.assertFalse(_is_excluded('src/entities/Snake.js'))

    def test_plan_md_not_excluded(self):
        self.assertFalse(_is_excluded('PLAN.md'))

    def test_intent_md_not_excluded(self):
        self.assertFalse(_is_excluded('INTENT.md'))

    def test_gitignore_not_excluded(self):
        """.gitignore is explicitly exempted from the hidden-file rule."""
        self.assertFalse(_is_excluded('.gitignore'))

    def test_gitattributes_not_excluded(self):
        """.gitattributes is explicitly exempted from the hidden-file rule."""
        self.assertFalse(_is_excluded('.gitattributes'))

    def test_readme_not_excluded(self):
        self.assertFalse(_is_excluded('README.md'))

    def test_nested_gitignore_not_excluded(self):
        self.assertFalse(_is_excluded('subdir/.gitignore'))

    def test_worktrees_json_in_subdir_excluded(self):
        """worktrees.json nested under a subdirectory is still excluded by basename."""
        self.assertTrue(_is_excluded('deep/nested/worktrees.json'))


# ── Tests: MergeConflictEscalation ───────────────────────────────────────────

class TestMergeConflictEscalation(unittest.TestCase):
    """Test that MergeConflictEscalation carries the correct data."""

    def test_attributes_are_set(self):
        exc = MergeConflictEscalation(['file1.py', 'file2.py'], '/src', '/target')
        self.assertEqual(exc.conflicted_files, ['file1.py', 'file2.py'])
        self.assertEqual(exc.source, '/src')
        self.assertEqual(exc.target, '/target')

    def test_is_exception(self):
        exc = MergeConflictEscalation(['a.py'], '/s', '/t')
        self.assertIsInstance(exc, Exception)

    def test_message_includes_file_count(self):
        exc = MergeConflictEscalation(['a.py', 'b.py', 'c.py'], '/s', '/t')
        self.assertIn('3', str(exc))

    def test_message_includes_first_file(self):
        exc = MergeConflictEscalation(['conflict.py'], '/s', '/t')
        self.assertIn('conflict.py', str(exc))

    def test_empty_conflicted_files(self):
        exc = MergeConflictEscalation([], '/s', '/t')
        self.assertEqual(exc.conflicted_files, [])
        self.assertIn('0', str(exc))

    def test_many_files_truncated_in_message(self):
        """The message should only include the first 5 files per the implementation."""
        files = [f'file{i}.py' for i in range(10)]
        exc = MergeConflictEscalation(files, '/s', '/t')
        # All 10 files are in conflicted_files, but message only shows first 5
        self.assertEqual(len(exc.conflicted_files), 10)
        msg = str(exc)
        self.assertIn('file0.py', msg)
        self.assertNotIn('file9.py', msg)


# ── Tests: ApprovalGate elapsed-time guard ───────────────────────────────────

class TestElapsedTimeGuard(unittest.TestCase):
    """Test the MIN_EXECUTION_SECONDS guard in ApprovalGate._proxy_decide().

    The guard fires when:
      - state is TASK_ASSERT or WORK_ASSERT
      - phase_start_time > 0
      - time.monotonic() - phase_start_time < MIN_EXECUTION_SECONDS

    When the guard fires it returns 'escalate' immediately without consulting
    the proxy model.
    """

    def _make_gate(self, proxy_model_path: str) -> ApprovalGate:
        return ApprovalGate(
            proxy_model_path=proxy_model_path,
            input_provider=_dummy_input,
            poc_root='/tmp',
        )

    def test_elapsed_time_guard_escalates_short_execution(self):
        """Phase elapsed 30s < MIN_EXECUTION_SECONDS → guard must return 'escalate'."""
        gate = self._make_gate('/tmp/nonexistent-proxy.json')
        # Set phase_start_time to 30 seconds ago using real monotonic clock
        phase_start = time.monotonic() - 30.0

        result = gate._proxy_decide(
            state='TASK_ASSERT',
            project_slug='test-project',
            artifact_path='',
            team='',
            phase_start_time=phase_start,
        )

        self.assertEqual(result, 'escalate')

    def test_elapsed_time_guard_escalates_short_execution_work_assert(self):
        """Same guard applies to WORK_ASSERT state."""
        gate = self._make_gate('/tmp/nonexistent-proxy.json')
        phase_start = time.monotonic() - 60.0  # 60 seconds — still under 120s minimum

        result = gate._proxy_decide(
            state='WORK_ASSERT',
            project_slug='test-project',
            artifact_path='',
            team='',
            phase_start_time=phase_start,
        )

        self.assertEqual(result, 'escalate')

    def test_elapsed_time_guard_allows_long_execution(self):
        """Phase elapsed 300s >= MIN_EXECUTION_SECONDS → time guard must NOT fire.

        The proxy model with enough approvals should be able to auto-approve.
        We mock random.random to suppress the exploration-rate escalation so
        the test is deterministic.
        """
        state = 'TASK_ASSERT'
        task_type = 'test-project'
        proxy_path = _make_warm_proxy_model(state, task_type)

        try:
            gate = self._make_gate(proxy_path)
            # Set start 300 seconds ago — well above MIN_EXECUTION_SECONDS
            phase_start = time.monotonic() - 300.0

            with patch('projects.POC.scripts.approval_gate.random') as mock_random:
                # Suppress exploration so the model can auto-approve
                mock_random.random.return_value = 1.0  # > EXPLORE_RATE (0.15)
                result = gate._proxy_decide(
                    state=state,
                    project_slug=task_type,
                    artifact_path='',
                    team='',
                    phase_start_time=phase_start,
                )

            # Time guard did not fire; warm model should auto-approve
            self.assertEqual(result, 'auto-approve')
        finally:
            if os.path.exists(proxy_path):
                os.unlink(proxy_path)

    def test_elapsed_time_guard_skips_non_execution_states(self):
        """PLAN_ASSERT with short elapsed time → guard must NOT fire.

        The guard only covers TASK_ASSERT and WORK_ASSERT.  A warm model for
        PLAN_ASSERT should auto-approve when the time guard doesn't fire.
        If the guard incorrectly fired for PLAN_ASSERT, the result would be
        'escalate' regardless of model warmth, so we use a warm model to
        detect whether the guard fired.
        """
        state = 'PLAN_ASSERT'
        task_type = 'non-execution-test'
        proxy_path = _make_warm_proxy_model(state, task_type)

        try:
            gate = self._make_gate(proxy_path)
            # A very recent start — would trigger the guard if PLAN_ASSERT were covered
            phase_start = time.monotonic() - 5.0

            with patch('projects.POC.scripts.approval_gate.random') as mock_random:
                mock_random.random.return_value = 1.0  # suppress exploration
                result = gate._proxy_decide(
                    state=state,
                    project_slug=task_type,
                    artifact_path='',
                    team='',
                    phase_start_time=phase_start,
                )

            # Warm model + no time guard = auto-approve
            # If guard had fired it would have returned 'escalate'
            self.assertEqual(result, 'auto-approve')
        finally:
            if os.path.exists(proxy_path):
                os.unlink(proxy_path)

    def test_elapsed_time_guard_skips_zero_phase_start_time(self):
        """phase_start_time=0 → guard must NOT fire (0 is the sentinel for 'not set').

        A warm model with phase_start_time=0 should be able to auto-approve for
        TASK_ASSERT because the guard condition `phase_start_time > 0` is False.
        """
        state = 'TASK_ASSERT'
        task_type = 'zero-start-test'
        proxy_path = _make_warm_proxy_model(state, task_type)

        try:
            gate = self._make_gate(proxy_path)

            with patch('projects.POC.scripts.approval_gate.random') as mock_random:
                mock_random.random.return_value = 1.0  # suppress exploration
                result = gate._proxy_decide(
                    state=state,
                    project_slug=task_type,
                    artifact_path='',
                    team='',
                    phase_start_time=0.0,  # sentinel — guard must be skipped
                )

            # Guard skipped because phase_start_time == 0; warm model auto-approves
            self.assertEqual(result, 'auto-approve')
        finally:
            if os.path.exists(proxy_path):
                os.unlink(proxy_path)

    def test_min_execution_seconds_constant(self):
        """MIN_EXECUTION_SECONDS should be 120 as documented in Issue #122."""
        self.assertEqual(MIN_EXECUTION_SECONDS, 120)

    def test_elapsed_time_guard_boundary_exactly_at_minimum(self):
        """Phase elapsed exactly MIN_EXECUTION_SECONDS → guard should NOT fire.

        The guard condition is `elapsed < MIN_EXECUTION_SECONDS`, so at exactly
        the boundary the phase is considered long enough.  We patch time.monotonic
        at the stdlib level to get a deterministic boundary value.
        """
        state = 'TASK_ASSERT'
        task_type = 'boundary-project'
        proxy_path = _make_warm_proxy_model(state, task_type)

        try:
            gate = self._make_gate(proxy_path)
            fake_now = 7000.0
            # Elapsed == exactly MIN_EXECUTION_SECONDS
            phase_start = fake_now - MIN_EXECUTION_SECONDS

            with patch('time.monotonic', return_value=fake_now), \
                 patch('projects.POC.scripts.approval_gate.random') as mock_random:
                mock_random.random.return_value = 1.0  # suppress exploration
                result = gate._proxy_decide(
                    state=state,
                    project_slug=task_type,
                    artifact_path='',
                    team='',
                    phase_start_time=phase_start,
                )

            # Boundary: elapsed == MIN_EXECUTION_SECONDS → guard does not fire → auto-approve
            self.assertEqual(result, 'auto-approve')
        finally:
            if os.path.exists(proxy_path):
                os.unlink(proxy_path)


if __name__ == '__main__':
    unittest.main()
