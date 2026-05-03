#!/usr/bin/env python3
"""Tests for the surviving surface in ``cfa/actors.py``.

After the engine unification onto ``run_agent_loop`` (#422), the
actor wrappers and outcome interpreter that used to live here were
deleted.  What remains are launch-prep helpers + post-launch
artifact-relocation utilities the engine still imports directly.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.cfa.actors import _relocate_plan_file


# ── Plan relocation from ~/.claude/plans/ ────────────────────────────────────

class TestRelocatePlanFile(unittest.TestCase):
    """_relocate_plan_file copies newest plan from ~/.claude/plans/ to target."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fake_plans_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.fake_plans_dir, ignore_errors=True)

    def test_relocates_newest_plan_after_start_time(self):
        """Plan file created after start_time is copied to target."""
        import time
        start = time.time() - 1  # 1 second ago

        target = os.path.join(self.tmpdir, 'PLAN.md')

        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)
            new_plan = plans_dir / 'test-plan.md'
            new_plan.write_text('# My Plan\n\n## Steps\n1. First\n2. Second')

            result = _relocate_plan_file(target, start)

        self.assertTrue(result)
        self.assertTrue(os.path.exists(target))
        self.assertIn('My Plan', Path(target).read_text())

    def test_ignores_plans_before_start_time(self):
        """Plan files older than start_time are not relocated."""
        import time

        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)
            old_plan = plans_dir / 'old-plan.md'
            old_plan.write_text('# Old Plan')
            os.utime(str(old_plan), (time.time() - 3600, time.time() - 3600))

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, time.time() - 1)

        self.assertFalse(result)
        self.assertFalse(os.path.exists(target))

    def test_picks_newest_when_multiple_candidates(self):
        """When multiple plans are new, the newest (highest mtime) wins."""
        import time
        start = time.time() - 2

        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)

            older = plans_dir / 'older-plan.md'
            older.write_text('# Older')
            os.utime(str(older), (time.time() - 1, time.time() - 1))

            newer = plans_dir / 'newer-plan.md'
            newer.write_text('# Newer')

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, start)

        self.assertTrue(result)
        self.assertIn('Newer', Path(target).read_text())

    def test_no_plans_dir_returns_false(self):
        """If ~/.claude/plans/ doesn't exist, return False gracefully."""
        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'empty-home'

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, 0)

        self.assertFalse(result)

    def test_empty_plans_dir_returns_false(self):
        """If ~/.claude/plans/ exists but is empty, return False."""
        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, 0)

        self.assertFalse(result)

    def test_non_md_files_ignored(self):
        """Non-.md files in plans dir are skipped."""
        import time

        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)
            (plans_dir / 'notes.txt').write_text('not a plan')
            (plans_dir / 'data.json').write_text('{}')

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, time.time() - 10)

        self.assertFalse(result)


# ── Misplaced-artifact relocation ────────────────────────────────────────────

class TestRelocateMisplacedArtifact(unittest.TestCase):
    """Artifacts written anywhere must be moved to the worktree via stream parsing."""

    def setUp(self):
        self.worktree = tempfile.mkdtemp()
        self.stream_dir = tempfile.mkdtemp()
        self.stream_file = os.path.join(self.stream_dir, '.intent-stream.jsonl')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.worktree, ignore_errors=True)
        shutil.rmtree(self.stream_dir, ignore_errors=True)

    def _write_stream_with_write_call(self, file_path: str) -> None:
        """Write a JSONL line representing a Write tool call to file_path."""
        import json as _json
        line = {
            'message': {
                'content': [
                    {'name': 'Write', 'input': {'file_path': file_path}},
                ],
            },
        }
        with open(self.stream_file, 'w') as f:
            f.write(_json.dumps(line) + '\n')

    def test_relocates_artifact_found_via_stream(self):
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        wrong_dir = tempfile.mkdtemp()
        misplaced = os.path.join(wrong_dir, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nObjective: build a thing')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'INTENT.md')))
        self.assertFalse(os.path.exists(misplaced))
        import shutil
        shutil.rmtree(wrong_dir, ignore_errors=True)

    def test_relocates_from_repo_root(self):
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        wrong_dir = tempfile.mkdtemp()
        misplaced = os.path.join(wrong_dir, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nObjective: x')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'INTENT.md')))
        import shutil
        shutil.rmtree(wrong_dir, ignore_errors=True)

    def test_relocates_from_project_dir(self):
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        project_dir = tempfile.mkdtemp()
        misplaced = os.path.join(project_dir, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nFrom project')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'INTENT.md')))
        import shutil
        shutil.rmtree(project_dir, ignore_errors=True)

    def test_no_op_when_artifact_already_in_worktree(self):
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        artifact_path = os.path.join(self.worktree, 'INTENT.md')
        Path(artifact_path).write_text('# Already here')
        self._write_stream_with_write_call(artifact_path)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertFalse(result)
        self.assertTrue(os.path.exists(artifact_path))

    def test_no_op_when_no_write_in_stream(self):
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        with open(self.stream_file, 'w') as f:
            f.write('{"message": {"content": []}}\n')

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertFalse(result)

    def test_no_op_when_stream_file_missing(self):
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        result = _relocate_misplaced_artifact(
            self.worktree, '/nonexistent/stream.jsonl', 'INTENT.md',
        )

        self.assertFalse(result)

    def test_works_for_plan_artifact(self):
        """Relocation works for PLAN.md too."""
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        wrong_dir = tempfile.mkdtemp()
        misplaced = os.path.join(wrong_dir, 'PLAN.md')
        Path(misplaced).write_text('# Plan\nStep 1')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'PLAN.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'PLAN.md')))
        import shutil
        shutil.rmtree(wrong_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
