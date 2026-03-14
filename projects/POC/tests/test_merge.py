"""Tests for merge.py and the ApprovalGate elapsed-time guard in actors.py.

Covers:
  - _is_excluded() filter logic
  - MergeConflictEscalation exception attributes
  - ApprovalGate._proxy_decide() elapsed-time guard (Issue #122)
  - Integration: squash_merge with real git repos reproducing #123 scenario
  - Integration: infrastructure files excluded from merge
  - Integration: -X theirs conflict resolution
  - Integration: post-merge verification catches missing/truncated files
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
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

from projects.POC.orchestrator.merge import (
    _is_excluded, MergeConflictEscalation, squash_merge, commit_deliverables,
    _verify_merge,
)
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

    def test_work_summary_excluded(self):
        """Work summary is an infrastructure artifact, not a deliverable."""
        self.assertTrue(_is_excluded('.work-summary.md'))


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


# ── Integration test helpers ──────────────────────────────────────────────────

def _git(cwd, *args):
    """Run a git command synchronously, raise on failure."""
    result = subprocess.run(
        ['git'] + list(args),
        cwd=cwd,
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f'git {" ".join(args)} failed in {cwd}: {result.stderr}'
        )
    return result.stdout.strip()


def _make_repo(path):
    """Initialize a bare-minimum git repo with one commit on 'main' branch."""
    os.makedirs(path, exist_ok=True)
    _git(path, 'init', '-b', 'main')
    _git(path, 'config', 'user.email', 'test@test.com')
    _git(path, 'config', 'user.name', 'Test')
    # Initial commit so we have a HEAD
    with open(os.path.join(path, 'README.md'), 'w') as f:
        f.write('# Test repo\n')
    _git(path, 'add', 'README.md')
    _git(path, 'commit', '-m', 'initial commit')


def _make_source_worktree(repo_root, branch_name='session-branch'):
    """Create a worktree branching from the repo, simulating a session worktree."""
    worktree_path = os.path.join(
        os.path.dirname(repo_root), f'worktree-{branch_name}',
    )
    _git(repo_root, 'worktree', 'add', '-b', branch_name, worktree_path)
    _git(worktree_path, 'config', 'user.email', 'test@test.com')
    _git(worktree_path, 'config', 'user.name', 'Test')
    return worktree_path


# ── Integration tests: reproduce #123 scenario ──────────────────────────────

class TestSquashMergeIntegration(unittest.TestCase):
    """Integration tests that create real git repos and run squash_merge.

    These reproduce the exact scenario from issue #123: a source worktree
    with agent-produced source files plus infrastructure junk in the target.
    """

    def setUp(self):
        """Create a temporary directory for each test's git repos."""
        self.test_dir = tempfile.mkdtemp(prefix='merge-integration-')

    def tearDown(self):
        """Clean up temporary directories."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_repos(self):
        """Set up target repo + source worktree with initial commit."""
        target = os.path.join(self.test_dir, 'target-repo')
        _make_repo(target)
        source = _make_source_worktree(target, 'session-branch')
        return target, source

    # ── Test: #123 reproduction — infrastructure files must NOT land ──────

    def test_infrastructure_files_excluded_from_merge(self):
        """Reproduce #123: source has real code, target has .DS_Store etc.

        The merge must land the source code files and NOT include the
        infrastructure files that exist in the target directory.
        """
        target, source = self._make_repos()

        # Agent produces real source code in the source worktree
        src_dir = os.path.join(source, 'src', 'entities')
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, 'Snake.js'), 'w') as f:
            f.write('// Snake entity\n' * 124)  # 124 lines like in #123
        with open(os.path.join(src_dir, 'Crocodile.js'), 'w') as f:
            f.write('// Crocodile entity\n' * 117)
        scenes_dir = os.path.join(source, 'src', 'scenes')
        os.makedirs(scenes_dir, exist_ok=True)
        with open(os.path.join(scenes_dir, 'GameScene.js'), 'w') as f:
            f.write('// Game scene - the core logic\n' * 533)
        with open(os.path.join(source, 'PLAN.md'), 'w') as f:
            f.write('# Plan\nImplement frogger features\n')
        with open(os.path.join(source, 'INTENT.md'), 'w') as f:
            f.write('# Intent\nAdd new game entities\n')

        # Infrastructure junk in the TARGET (this is what #123 picked up)
        with open(os.path.join(target, '.DS_Store'), 'wb') as f:
            f.write(b'\x00\x00\x00\x01Bud1')
        with open(os.path.join(target, '.memory.db'), 'wb') as f:
            f.write(b'SQLite format 3\x00')
        with open(os.path.join(target, '.proxy-confidence.json'), 'w') as f:
            f.write('{"entries": {}}')
        with open(os.path.join(target, 'worktrees.json'), 'w') as f:
            f.write('{"worktrees": []}')

        # Run the merge
        asyncio.run(squash_merge(
            source=source,
            target=target,
            message='Session test: frogger entities',
        ))

        # VERIFY: source code files MUST exist in target
        self.assertTrue(
            os.path.exists(os.path.join(target, 'src', 'entities', 'Snake.js')),
            'Snake.js missing from target after merge',
        )
        self.assertTrue(
            os.path.exists(os.path.join(target, 'src', 'entities', 'Crocodile.js')),
            'Crocodile.js missing from target after merge',
        )
        self.assertTrue(
            os.path.exists(os.path.join(target, 'src', 'scenes', 'GameScene.js')),
            'GameScene.js missing from target after merge',
        )
        self.assertTrue(
            os.path.exists(os.path.join(target, 'PLAN.md')),
            'PLAN.md missing from target after merge',
        )
        self.assertTrue(
            os.path.exists(os.path.join(target, 'INTENT.md')),
            'INTENT.md missing from target after merge',
        )

        # VERIFY: source code content is correct (not truncated)
        with open(os.path.join(target, 'src', 'entities', 'Snake.js')) as f:
            snake_lines = f.readlines()
        self.assertEqual(len(snake_lines), 124,
                         f'Snake.js should have 124 lines, got {len(snake_lines)}')

        with open(os.path.join(target, 'src', 'scenes', 'GameScene.js')) as f:
            scene_lines = f.readlines()
        self.assertEqual(len(scene_lines), 533,
                         f'GameScene.js should have 533 lines, got {len(scene_lines)}')

        # VERIFY: infrastructure files are NOT in the git history
        committed_files = _git(target, 'diff', '--name-only', 'HEAD~1', 'HEAD')
        committed_list = committed_files.strip().splitlines()
        for junk in ['.DS_Store', '.memory.db', '.proxy-confidence.json', 'worktrees.json']:
            self.assertNotIn(junk, committed_list,
                             f'{junk} should NOT be in the merge commit')

    # ── Test: all source files land (no files dropped) ───────────────────

    def test_all_source_files_land_on_target(self):
        """Verify that ALL files from the source worktree are present in
        the target after merge — not just a subset.

        Issue #123 showed only 4 of 15 files landing. This test creates
        15 files (matching the issue) and verifies all 15 are present.
        """
        target, source = self._make_repos()

        # Create the exact file set from issue #123
        files = {
            'INTENT.md': '# Intent\n' * 50,
            'PLAN.md': '# Plan\n' * 30,
            'src/art/ui.js': '// UI art\n' * 25,
            'src/config/levels.js': '// Level config\n' * 175,
            'src/entities/Crocodile.js': '// Crocodile\n' * 117,
            'src/entities/HomeCell.js': '// HomeCell\n' * 53,
            'src/entities/LadyFrog.js': '// LadyFrog\n' * 90,
            'src/entities/Otter.js': '// Otter\n' * 128,
            'src/entities/PinkToad.js': '// PinkToad\n' * 98,
            'src/entities/Snake.js': '// Snake\n' * 124,
            'src/scenes/GameOverScene.js': '// GameOver\n' * 9,
            'src/scenes/GameScene.js': '// GameScene\n' * 533,
            'src/systems/CollisionSystem.js': '// Collision\n' * 273,
            'src/systems/LaneSystem.js': '// Lane\n' * 3,
            'style.css': 'body { margin: 0; }\n' * 24,
        }

        for relpath, content in files.items():
            full = os.path.join(source, relpath)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w') as f:
                f.write(content)

        asyncio.run(squash_merge(
            source=source,
            target=target,
            message='Session test: full frogger implementation',
        ))

        # Every single file must be present in target
        for relpath, content in files.items():
            full = os.path.join(target, relpath)
            self.assertTrue(
                os.path.exists(full),
                f'{relpath} missing from target after merge',
            )
            with open(full) as f:
                actual = f.read()
            self.assertEqual(
                actual, content,
                f'{relpath} content differs — expected {len(content)} chars, '
                f'got {len(actual)} chars',
            )

    # ── Test: merge with conflicts uses -X theirs ────────────────────────

    def test_merge_with_conflicts_resolves_with_x_theirs(self):
        """When target has diverged and both sides edit the same file,
        the merge should resolve by taking the source (session) version.
        """
        target, source = self._make_repos()

        # Both branches start with the same file (from initial commit base).
        # Create the file on main first, then cherry-pick to session branch.
        with open(os.path.join(target, 'shared.js'), 'w') as f:
            f.write('// original version\nconst x = 1;\n')
        _git(target, 'add', 'shared.js')
        _git(target, 'commit', '-m', 'add shared.js on main')
        base_sha = _git(target, 'rev-parse', 'HEAD')

        # Cherry-pick the base commit into the source branch
        _git(source, 'cherry-pick', base_sha)

        # Now diverge: edit differently in source
        with open(os.path.join(source, 'shared.js'), 'w') as f:
            f.write('// session version - the completed work\nconst x = 42;\n')
        _git(source, 'add', 'shared.js')
        _git(source, 'commit', '-m', 'edit shared.js in session')

        # And diverge on target too
        with open(os.path.join(target, 'shared.js'), 'w') as f:
            f.write('// target version - should be overwritten\nconst x = 999;\n')
        _git(target, 'add', 'shared.js')
        _git(target, 'commit', '-m', 'edit shared.js on main again')

        asyncio.run(squash_merge(
            source=source,
            target=target,
            message='Merge with conflict',
        ))

        # Source (session) version should win
        with open(os.path.join(target, 'shared.js')) as f:
            content = f.read()
        self.assertIn('session version', content,
                      'Source version should win on conflict')
        self.assertNotIn('target version', content,
                         'Target version should be overwritten')

    # ── Test: commit_deliverables excludes infrastructure ────────────────

    def test_commit_deliverables_excludes_infrastructure(self):
        """commit_deliverables() should NOT stage .DS_Store, .memory.db, etc."""
        target, source = self._make_repos()

        # Create both real files and infrastructure junk in source
        with open(os.path.join(source, 'app.js'), 'w') as f:
            f.write('console.log("hello");\n')
        with open(os.path.join(source, '.DS_Store'), 'wb') as f:
            f.write(b'\x00\x00\x00\x01Bud1')
        with open(os.path.join(source, '.memory.db'), 'wb') as f:
            f.write(b'SQLite format 3\x00')

        sha = asyncio.run(commit_deliverables(source, 'test commit'))
        self.assertIsNotNone(sha, 'Should have committed something')

        # Check what was committed
        committed = _git(source, 'diff', '--name-only', 'HEAD~1', 'HEAD')
        committed_list = committed.strip().splitlines()
        self.assertIn('app.js', committed_list)
        self.assertNotIn('.DS_Store', committed_list,
                         '.DS_Store should not be committed')
        self.assertNotIn('.memory.db', committed_list,
                         '.memory.db should not be committed')

    # ── Test: post-merge verification detects missing files ──────────────

    def test_verify_merge_detects_missing_files(self):
        """_verify_merge should log errors when source files are missing
        from target after a merge.
        """
        target, source = self._make_repos()

        # Source has a tracked file
        with open(os.path.join(source, 'important.js'), 'w') as f:
            f.write('// important code\n' * 100)
        _git(source, 'add', 'important.js')
        _git(source, 'commit', '-m', 'add important.js')

        # Target does NOT have important.js (simulating a failed merge)
        # We call _verify_merge directly
        with self.assertLogs('orchestrator.merge', level='ERROR') as cm:
            asyncio.run(_verify_merge(source, target))

        # Should have logged an error about the missing file
        error_messages = ' '.join(cm.output)
        self.assertIn('important.js', error_messages)
        self.assertIn('missing', error_messages.lower())

    # ── Test: post-merge verification detects truncated files ────────────

    def test_verify_merge_detects_truncated_files(self):
        """_verify_merge should warn when files are significantly smaller
        in target than in source (truncated during merge).
        """
        target, source = self._make_repos()

        # Source has a large file
        with open(os.path.join(source, 'GameScene.js'), 'w') as f:
            f.write('// game scene\n' * 533)
        _git(source, 'add', 'GameScene.js')
        _git(source, 'commit', '-m', 'add GameScene')

        # Target has a truncated version (< 50% of source size)
        with open(os.path.join(target, 'GameScene.js'), 'w') as f:
            f.write('// game scene\n' * 35)  # 35 lines vs 533 = ~6.5%
        _git(target, 'add', 'GameScene.js')
        _git(target, 'commit', '-m', 'add truncated GameScene')

        with self.assertLogs('orchestrator.merge', level='ERROR') as cm:
            asyncio.run(_verify_merge(source, target))

        error_messages = ' '.join(cm.output)
        self.assertIn('GameScene.js', error_messages)
        self.assertIn('truncated', error_messages.lower())

    # ── Test: conflict callback with escalation ──────────────────────────

    def test_conflict_callback_escalation_raises(self):
        """When conflict_callback returns 'escalate', squash_merge should
        raise MergeConflictEscalation.
        """
        target, source = self._make_repos()

        # Create a shared base: add config.js on main, cherry-pick to session
        with open(os.path.join(target, 'config.js'), 'w') as f:
            f.write('// original config\n')
        _git(target, 'add', 'config.js')
        _git(target, 'commit', '-m', 'add config on main')
        base_sha = _git(target, 'rev-parse', 'HEAD')
        _git(source, 'cherry-pick', base_sha)

        # Diverge: different edits on both sides
        with open(os.path.join(source, 'config.js'), 'w') as f:
            f.write('// source version\n')
        _git(source, 'add', 'config.js')
        _git(source, 'commit', '-m', 'edit config in session')

        with open(os.path.join(target, 'config.js'), 'w') as f:
            f.write('// diverged target version\n')
        _git(target, 'add', 'config.js')
        _git(target, 'commit', '-m', 'diverge config on main')

        async def escalate_callback(conflicted, src, tgt):
            return 'escalate'

        with self.assertRaises(MergeConflictEscalation) as ctx:
            asyncio.run(squash_merge(
                source=source,
                target=target,
                message='should escalate',
                conflict_callback=escalate_callback,
            ))

        self.assertIn('config.js', ctx.exception.conflicted_files)


if __name__ == '__main__':
    unittest.main()
