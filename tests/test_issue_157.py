#!/usr/bin/env python3
"""Tests for issue #157: TUI shows stale artifact after approval gate corrections.

After corrections at an approval gate, the agent edits the artifact in the
worktree but the infra_dir copy is never refreshed.  The TUI opens the stale
infra_dir copy.

Tests verify:
  1. _relocate_misplaced_artifact refreshes an existing infra_dir copy when the
     worktree version is newer (different content)
  2. _relocate_misplaced_artifact detects Edit tool calls, not just Write
  3. Refresh does not clobber infra_dir when the worktree copy does not exist
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.actors import _relocate_misplaced_artifact


def _make_stream(tmpdir, events):
    """Write a minimal stream JSONL with tool-use events."""
    path = os.path.join(tmpdir, '.plan-stream.jsonl')
    with open(path, 'w') as f:
        for tool_name, file_path in events:
            evt = {
                'type': 'assistant',
                'message': {
                    'content': [{
                        'type': 'tool_use',
                        'name': tool_name,
                        'input': {'file_path': file_path},
                    }],
                },
            }
            f.write(json.dumps(evt) + '\n')
    return path


# ── Refresh stale infra_dir copy ─────────────────────────────────────────


class TestRelocateRefreshesStaleArtifact(unittest.TestCase):
    """_relocate_misplaced_artifact must refresh infra_dir when worktree is newer."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        os.makedirs(self.infra_dir)
        os.makedirs(self.worktree)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_refreshes_when_worktree_has_newer_content(self):
        """After corrections, worktree PLAN.md is updated via Edit.
        The infra_dir copy must be refreshed."""
        # Initial state: both copies exist, infra_dir has stale content
        worktree_plan = os.path.join(self.worktree, 'PLAN.md')
        infra_plan = os.path.join(self.infra_dir, 'PLAN.md')

        Path(infra_plan).write_text('# Original plan\nOnly 3 passes.')
        Path(worktree_plan).write_text('# Updated plan\nSeven orthogonal passes.')

        # Stream shows an Edit to the worktree copy
        stream = _make_stream(self.infra_dir, [
            ('Write', worktree_plan),   # initial write
            ('Edit', worktree_plan),    # correction edit
        ])

        result = _relocate_misplaced_artifact(self.infra_dir, stream, 'PLAN.md')

        # The infra_dir copy must now match the worktree version
        actual = Path(infra_plan).read_text()
        self.assertIn('Seven orthogonal passes', actual,
                       "infra_dir PLAN.md must be refreshed from worktree after Edit")

    def test_does_not_clobber_when_worktree_copy_missing(self):
        """If the artifact only exists in infra_dir (no worktree copy),
        relocation must not delete or modify it."""
        infra_plan = os.path.join(self.infra_dir, 'PLAN.md')
        Path(infra_plan).write_text('# Good plan')

        stream = _make_stream(self.infra_dir, [])  # no tool calls

        _relocate_misplaced_artifact(self.infra_dir, stream, 'PLAN.md')

        actual = Path(infra_plan).read_text()
        self.assertEqual(actual, '# Good plan',
                         "infra_dir copy must not be modified when no worktree copy exists")


# ── Edit tool call detection ─────────────────────────────────────────────


class TestRelocateDetectsEditCalls(unittest.TestCase):
    """_relocate_misplaced_artifact must find artifacts modified via Edit."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        os.makedirs(self.infra_dir)
        os.makedirs(self.worktree)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_edit_only_stream_triggers_relocation(self):
        """When the artifact was only edited (never written from scratch),
        relocation must still find and copy it."""
        worktree_intent = os.path.join(self.worktree, 'INTENT.md')
        Path(worktree_intent).write_text('# Revised intent')

        # Stream has only Edit calls, no Write
        stream = _make_stream(self.infra_dir, [
            ('Edit', worktree_intent),
        ])

        result = _relocate_misplaced_artifact(self.infra_dir, stream, 'INTENT.md')

        infra_intent = os.path.join(self.infra_dir, 'INTENT.md')
        self.assertTrue(os.path.exists(infra_intent),
                        "Edit-only artifact must be copied to infra_dir")
        actual = Path(infra_intent).read_text()
        self.assertEqual(actual, '# Revised intent')


if __name__ == '__main__':
    unittest.main()
