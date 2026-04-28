"""Regression: close_conversation finds dispatched sessions under tasks_dir.

When a CfA job dispatches a worker, the worker's session lives at
``{job_infra_dir}/tasks/<sid>/`` (per the layout change in commit
b45dbe84).  ``close_conversation`` previously hard-coded the
catalog-keyed path
``{teaparty_home}/<scope>/sessions/<sid>/``, so calling it on a new-
layout session loaded an empty metadata dict, skipped the merge, and
silently dropped the worker's branch.

This test pins the contract: ``close_conversation`` accepts a
``tasks_dir`` parameter; ``_close_recursive`` checks both locations
(tasks_dir first, legacy as fallback) so chat-tier and pre-layout-
change sessions still close cleanly.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.workspace.close_conversation import _close_recursive


class FakeBus:
    """Minimal bus stub: no children, no real bus state."""

    def children_of(self, parent_id: str):
        return []

    def update_conversation_state(self, *args, **kwargs):
        pass


class CloseRecursiveFindsSessionTest(unittest.TestCase):
    """``_close_recursive`` locates the session in either layout."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='close-tasks-dir-')
        self.teaparty_home = os.path.join(self._tmp, '.teaparty')
        self.legacy_dir = os.path.join(
            self.teaparty_home, 'management', 'sessions',
        )
        self.tasks_dir = os.path.join(
            self._tmp, 'project-repo', '.teaparty', 'jobs',
            'job-test', 'tasks',
        )
        os.makedirs(self.legacy_dir)
        os.makedirs(self.tasks_dir)
        self.bus = FakeBus()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_session(self, base_dir: str, sid: str, *, with_worktree: bool = False) -> str:
        path = os.path.join(base_dir, sid)
        os.makedirs(path)
        meta = {
            'agent_name': 'research-lead',
            'session_id': sid,
            'scope': 'management',
            # No worktree path — keeps the merge call inert; the test
            # only verifies the lookup path, not the git operations.
            'worktree_path': '',
            'worktree_branch': '',
        }
        with open(os.path.join(path, 'metadata.json'), 'w') as fh:
            json.dump(meta, fh)
        return path

    def test_finds_session_under_tasks_dir(self) -> None:
        """When tasks_dir is set and the session lives there, it loads."""
        path = self._write_session(self.tasks_dir, 'sid-new')
        result = asyncio.run(_close_recursive(
            self.legacy_dir, 'sid-new', self.bus, tasks_dir=self.tasks_dir,
        ))
        # No worktree → status is 'ok' (plain teardown), and the session
        # dir is rmtree'd.
        self.assertEqual(result['status'], 'ok')
        self.assertFalse(
            os.path.exists(path),
            f'Session dir at {path} should be removed on close',
        )

    def test_finds_session_in_legacy_layout_as_fallback(self) -> None:
        """Sessions created before the layout change still close.

        ``tasks_dir`` is set (the CfA engine always sets it after the
        fix), but the on-disk session is at the legacy catalog-keyed
        path — close_recursive must still find and clean it up.
        """
        path = self._write_session(self.legacy_dir, 'sid-legacy')
        result = asyncio.run(_close_recursive(
            self.legacy_dir, 'sid-legacy', self.bus, tasks_dir=self.tasks_dir,
        ))
        self.assertEqual(result['status'], 'ok')
        self.assertFalse(os.path.exists(path))

    def test_returns_ok_when_neither_layout_has_session(self) -> None:
        """Missing-session is a clean no-op (matches prior behavior)."""
        result = asyncio.run(_close_recursive(
            self.legacy_dir, 'nonexistent', self.bus, tasks_dir=self.tasks_dir,
        ))
        # The function returns 'ok' (not 'noop') because empty meta
        # passes through the merge guard and reaches the rmtree at the
        # end.  Either way, no error.
        self.assertEqual(result['status'], 'ok')

    def test_chat_tier_close_without_tasks_dir_uses_legacy(self) -> None:
        """When tasks_dir is empty (chat tier), only legacy is checked."""
        path = self._write_session(self.legacy_dir, 'sid-chat')
        result = asyncio.run(_close_recursive(
            self.legacy_dir, 'sid-chat', self.bus, tasks_dir='',
        ))
        self.assertEqual(result['status'], 'ok')
        self.assertFalse(os.path.exists(path))


if __name__ == '__main__':
    unittest.main()
