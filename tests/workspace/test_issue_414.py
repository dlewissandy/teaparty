"""Issue #414: _verify_merge must raise on missing or truncated files.

Spec:
  SC1: _verify_merge raises MergeVerificationError when a tracked source
       file is absent from the target after merge.
  SC2: _verify_merge raises MergeVerificationError when a tracked source
       file is present in target but >50% smaller (truncated).
  SC3: _verify_merge passes silently when all source files are present
       and not significantly truncated.
  SC4: _verify_merge writes an entry to {target}/.teaparty/logs/merge-verification.log
       when verification fails (missing files case).
  SC5: _verify_merge writes an entry to {target}/.teaparty/logs/merge-verification.log
       when verification fails (truncated files case).
  SC6: squash_merge propagates MergeVerificationError when _verify_merge
       detects data loss after a successful git merge.
  SC7: Session.run() publishes EventType.FAILURE when squash_merge raises
       MergeVerificationError so the human is informed of the data loss.
  SC8: Session.run() returns MERGE_VERIFICATION_FAILED (not COMPLETED_WORK)
       when squash_merge raises MergeVerificationError.
  SC9: Session.run() skips extract_learnings when verification fails —
       learnings extracted from incomplete deliverables would be corrupt.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from teaparty.workspace.merge import (
    MergeVerificationError,
    _verify_merge,
    squash_merge,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_git_repo(path: str) -> str:
    """Init a git repo with an initial commit. Returns repo root."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(['git', 'init', path], check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'],
                   cwd=path, check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'],
                   cwd=path, check=True, capture_output=True)
    dummy = os.path.join(path, '.gitkeep')
    with open(dummy, 'w') as f:
        f.write('')
    subprocess.run(['git', 'add', '.gitkeep'], cwd=path, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=path,
                   check=True, capture_output=True)
    return path


def _make_worktree_pair(tmpdir: str) -> tuple[str, str]:
    """Create a source repo (with committed files) and a bare target repo."""
    source = _make_git_repo(os.path.join(tmpdir, 'source'))
    target = _make_git_repo(os.path.join(tmpdir, 'target'))
    return source, target


class TestVerifyMergeRaisesOnMissingFiles(unittest.TestCase):
    """SC1: raises MergeVerificationError when a tracked source file is missing from target."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.source, self.target = _make_worktree_pair(self._tmpdir)
        # Add a tracked file to source and commit it
        fpath = os.path.join(self.source, 'output.md')
        with open(fpath, 'w') as f:
            f.write('# Result\n' * 100)
        subprocess.run(['git', 'add', 'output.md'], cwd=self.source,
                       check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'add output'],
                       cwd=self.source, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_raises_when_source_file_absent_from_target(self):
        """_verify_merge raises MergeVerificationError when source file not in target."""
        with self.assertRaises(MergeVerificationError) as ctx:
            _run(_verify_merge(self.source, self.target))
        err = ctx.exception
        self.assertIn('output.md', err.missing)
        self.assertEqual(err.source, self.source)
        self.assertEqual(err.target, self.target)

    def test_error_message_names_the_missing_file(self):
        """Error message includes the name of the missing file."""
        with self.assertRaises(MergeVerificationError) as ctx:
            _run(_verify_merge(self.source, self.target))
        self.assertIn('output.md', str(ctx.exception))


class TestVerifyMergeRaisesOnTruncatedFiles(unittest.TestCase):
    """SC2: raises MergeVerificationError when a target file is >50% smaller than source."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.source, self.target = _make_worktree_pair(self._tmpdir)
        # Add a substantial file to source
        fpath = os.path.join(self.source, 'report.md')
        with open(fpath, 'w') as f:
            f.write('data\n' * 200)  # ~1000 bytes
        subprocess.run(['git', 'add', 'report.md'], cwd=self.source,
                       check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'add report'],
                       cwd=self.source, check=True, capture_output=True)
        # Put a truncated version in target (10% of source size)
        dst = os.path.join(self.target, 'report.md')
        with open(dst, 'w') as f:
            f.write('data\n' * 10)  # ~50 bytes — well under 50%

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_raises_when_target_file_is_truncated(self):
        """_verify_merge raises MergeVerificationError when target file is >50% smaller."""
        with self.assertRaises(MergeVerificationError) as ctx:
            _run(_verify_merge(self.source, self.target))
        err = ctx.exception
        truncated_paths = [f for f, _, _ in err.truncated]
        self.assertIn('report.md', truncated_paths)

    def test_truncated_entry_carries_size_info(self):
        """MergeVerificationError.truncated carries (path, src_size, dst_size)."""
        with self.assertRaises(MergeVerificationError) as ctx:
            _run(_verify_merge(self.source, self.target))
        err = ctx.exception
        path, src_size, dst_size = err.truncated[0]
        self.assertGreater(src_size, dst_size)


class TestVerifyMergePassesSilently(unittest.TestCase):
    """SC3: no exception when all source files are present and not truncated."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.source, self.target = _make_worktree_pair(self._tmpdir)
        content = 'result\n' * 100
        fpath = os.path.join(self.source, 'result.md')
        with open(fpath, 'w') as f:
            f.write(content)
        subprocess.run(['git', 'add', 'result.md'], cwd=self.source,
                       check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'add result'],
                       cwd=self.source, check=True, capture_output=True)
        # Copy the same file into target (simulates a successful merge)
        dst = os.path.join(self.target, 'result.md')
        with open(dst, 'w') as f:
            f.write(content)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_no_exception_when_all_files_present(self):
        """_verify_merge returns normally when all source files exist in target."""
        _run(_verify_merge(self.source, self.target))  # must not raise


class TestVerifyMergeAuditLog(unittest.TestCase):
    """SC4 & SC5: _verify_merge writes to the audit log on failure."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.source, self.target = _make_worktree_pair(self._tmpdir)
        fpath = os.path.join(self.source, 'artifact.txt')
        with open(fpath, 'w') as f:
            f.write('important data\n' * 50)
        subprocess.run(['git', 'add', 'artifact.txt'], cwd=self.source,
                       check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'add artifact'],
                       cwd=self.source, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_audit_log_created_on_missing_file(self):
        """A merge-verification.log entry is written when files are missing."""
        audit_path = os.path.join(self.target, '.teaparty', 'logs', 'merge-verification.log')
        self.assertFalse(os.path.exists(audit_path))

        with self.assertRaises(MergeVerificationError):
            _run(_verify_merge(self.source, self.target))

        self.assertTrue(os.path.exists(audit_path))
        with open(audit_path) as f:
            entry = f.read()
        self.assertIn('FAIL', entry)
        self.assertIn('artifact.txt', entry)

    def test_audit_log_appends_on_repeated_failures(self):
        """Each failure appends a new line; old entries are preserved."""
        with self.assertRaises(MergeVerificationError):
            _run(_verify_merge(self.source, self.target))
        with self.assertRaises(MergeVerificationError):
            _run(_verify_merge(self.source, self.target))

        audit_path = os.path.join(self.target, '.teaparty', 'logs', 'merge-verification.log')
        with open(audit_path) as f:
            lines = [l for l in f.readlines() if l.strip()]
        self.assertEqual(len(lines), 2)


class TestSquashMergePropagatesVerificationError(unittest.TestCase):
    """SC6: squash_merge propagates MergeVerificationError from _verify_merge."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.source = _make_git_repo(os.path.join(self._tmpdir, 'source'))
        self.target = _make_git_repo(os.path.join(self._tmpdir, 'target'))

        # Add a file to source and commit it — this is the deliverable
        fpath = os.path.join(self.source, 'deliverable.md')
        with open(fpath, 'w') as f:
            f.write('Final answer\n' * 100)
        subprocess.run(['git', 'add', 'deliverable.md'], cwd=self.source,
                       check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'add deliverable'],
                       cwd=self.source, check=True, capture_output=True)

        # Make target share the same history so merge works, but do NOT copy the file
        # (simulate a merge that drops the file)
        source_head = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=self.source,
        ).decode().strip()
        # Push source branch to target via remote
        subprocess.run(
            ['git', 'remote', 'add', 'source', self.source],
            cwd=self.target, check=True, capture_output=True,
        )
        subprocess.run(
            ['git', 'fetch', 'source'],
            cwd=self.target, check=True, capture_output=True,
        )

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.source, capture_output=True)
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.target, capture_output=True)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_squash_merge_raises_when_file_lost_after_merge(self):
        """squash_merge raises MergeVerificationError if deliverables are missing post-merge."""
        # squash_merge will merge source into target; because target diverged from source
        # via file-copy fallback this should land the file — but we can test the error
        # path by patching _verify_merge directly.
        import unittest.mock as mock
        from teaparty.workspace import merge as merge_module

        err = MergeVerificationError(['deliverable.md'], [], self.source, self.target)
        with mock.patch.object(merge_module, '_verify_merge', side_effect=err):
            with self.assertRaises(MergeVerificationError):
                _run(squash_merge(
                    source=self.source,
                    target=self.target,
                    message='test merge',
                ))


class TestSessionMergeVerificationFailure(unittest.TestCase):
    """SC7-SC9: Session.run() handles MergeVerificationError from squash_merge.

    These tests verify the session-level contract: when the merge succeeds at
    the git level but _verify_merge finds data loss, the session must notify
    the human, return a failure terminal state, and skip learnings extraction.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='teaparty-414-session-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # poc_root must exist so Session.__init__ can find config
        self.poc_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        )))
        self.projects_dir = os.path.join(self.tmp, 'projects')
        self.infra_dir = os.path.join(self.tmp, 'infra')
        self.worktree = os.path.join(self.tmp, 'worktree')
        os.makedirs(self.infra_dir, exist_ok=True)
        os.makedirs(self.worktree, exist_ok=True)

    def _make_session(self):
        from teaparty.cfa.session import Session
        from teaparty.messaging.bus import EventBus
        return Session(
            task='Test task',
            poc_root=self.poc_root,
            projects_dir=self.projects_dir,
            project_override='test-project',
            session_id='test-414',
            dry_run=False,
            skip_learnings=False,
            skip_learning_retrieval=True,
            event_bus=EventBus(),
        )

    def _make_infrastructure_patches(self, squash_merge_side_effect=None):
        """Return patches that stand up a minimal runnable session."""
        from teaparty.cfa.engine import OrchestratorResult
        from teaparty.messaging.conversations import SqliteMessageBus

        completed_result = OrchestratorResult(terminal_state='COMPLETED_WORK', backtrack_count=0)
        mock_orch = MagicMock()
        mock_orch.run = AsyncMock(return_value=completed_result)

        mock_state_writer = MagicMock()
        mock_state_writer.start = AsyncMock()
        mock_state_writer.stop = AsyncMock()

        fake_job = {
            'job_id': 'job-test-414',
            'job_dir': self.infra_dir,
            'worktree_path': self.worktree,
            'branch_name': 'job-test-414--test-task',
        }

        smock = AsyncMock(side_effect=squash_merge_side_effect) if squash_merge_side_effect else AsyncMock()

        return [
            patch('teaparty.cfa.session.SqliteMessageBus', return_value=MagicMock(spec=SqliteMessageBus)),
            patch('teaparty.cfa.session.create_job', new=AsyncMock(return_value=fake_job)),
            patch('teaparty.cfa.session.StateWriter', return_value=mock_state_writer),
            patch('teaparty.cfa.session.save_state'),
            patch('teaparty.cfa.session.Orchestrator', return_value=mock_orch),
            patch('teaparty.cfa.session.commit_deliverables', new=AsyncMock()),
            patch('teaparty.cfa.session.squash_merge', new=smock),
            patch('teaparty.cfa.session.extract_learnings', new=AsyncMock()),
            patch('teaparty.cfa.session.release_worktree', new=AsyncMock()),
        ], smock

    def _run_with_verification_failure(self):
        """Run session with squash_merge raising MergeVerificationError.

        Returns (session_result, published_events, extract_learnings_mock).
        """
        from teaparty.cfa.session import Session
        from teaparty.messaging.bus import EventBus, EventType

        err = MergeVerificationError(
            ['deliverable.md'], [], '/src', '/tgt',
        )
        patches, squash_mock = self._make_infrastructure_patches(
            squash_merge_side_effect=err,
        )

        session = self._make_session()
        published: list = []

        async def _capture_publish(event):
            published.append(event)

        session.event_bus.publish = _capture_publish

        ctx = []
        for p in patches:
            ctx.append(p.__enter__())
        try:
            result = asyncio.run(session.run())
        finally:
            for p, _ in zip(patches, ctx):
                p.__exit__(None, None, None)

        extract_mock = ctx[7]  # extract_learnings patch mock (index 7)
        return result, published, extract_mock

    def test_failure_event_published_on_verification_error(self):
        """SC7: Session.run() publishes EventType.FAILURE when merge verification fails."""
        from teaparty.messaging.bus import EventType
        result, published, _ = self._run_with_verification_failure()

        failure_events = [e for e in published if e.type == EventType.FAILURE]
        self.assertGreater(
            len(failure_events), 0,
            'Expected at least one FAILURE event to be published',
        )
        # The failure reason must mention the data loss
        reason = failure_events[0].data.get('reason', '')
        self.assertIn('deliverable.md', reason)

    def test_terminal_state_is_merge_verification_failed(self):
        """SC8: Session.run() returns MERGE_VERIFICATION_FAILED, not COMPLETED_WORK."""
        result, _, _ = self._run_with_verification_failure()
        self.assertEqual(result.terminal_state, 'MERGE_VERIFICATION_FAILED')

    def test_learnings_not_extracted_on_verification_failure(self):
        """SC9: extract_learnings is NOT called when merge verification fails."""
        _, _, extract_mock = self._run_with_verification_failure()
        extract_mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
