"""Regression: dispatched workers nest at arbitrary depth.

Project lead → art lead → svg artist must produce a filesystem tree
where each worker lives under its dispatcher, not flat under the
job.  Without per-dispatch derivation of ``tasks_dir``, every level
would land at ``{job_dir}/tasks/<sid>/`` regardless of depth, and
the bridge UI's recursive ``_scan_tasks`` would render the dispatch
tree as if it were one level deep.

This test pins the layout invariant: at any depth N, the worker's
session_path is ``{dispatcher_session.path}/tasks/<sid>/``.

Also pins the bus-based session_path lookup in ``_close_recursive``:
when the bus stores the worktree_path, the close walker reads it
verbatim and derives session_path as its parent — works regardless
of how deep the dispatch tree goes.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.messaging.child_dispatch import (
    ChildDispatchContext,
    _resolve_effective_tasks_dir,
)
from teaparty.workspace.close_conversation import _close_recursive


@dataclass
class FakeSession:
    """Minimal Session-shaped object for the registry."""
    id: str
    path: str


def _make_ctx(tasks_dir: str, registry: dict) -> ChildDispatchContext:
    return ChildDispatchContext(
        dispatcher_session=MagicMock(),
        bus=MagicMock(),
        bus_listener=MagicMock(),
        session_registry=registry,
        tasks_by_child={},
        tasks_dir=tasks_dir,
    )


class EffectiveTasksDirByDepthTest(unittest.TestCase):
    """``_resolve_effective_tasks_dir`` derives the right dir at every depth."""

    def setUp(self) -> None:
        self.job_tasks = '/jobs/job-test/tasks'

    def test_top_level_uses_job_tasks_dir(self) -> None:
        """Project-lead's dispatch (no caller_sid in registry) → job tasks/."""
        ctx = _make_ctx(self.job_tasks, registry={})
        # Top level: caller is the engine's dispatcher_session (not in registry).
        result = _resolve_effective_tasks_dir(ctx, caller_sid='')
        self.assertEqual(result, self.job_tasks)

    def test_one_level_deep_nests_under_dispatcher(self) -> None:
        """art-lead dispatched from project-lead → {job}/tasks/<art>/tasks/."""
        art_lead = FakeSession(
            id='sid-art', path=os.path.join(self.job_tasks, 'sid-art'),
        )
        ctx = _make_ctx(self.job_tasks, registry={'sid-art': art_lead})
        # Now art-lead is dispatching (caller_sid = its sid).
        result = _resolve_effective_tasks_dir(ctx, caller_sid='sid-art')
        self.assertEqual(
            result,
            os.path.join(self.job_tasks, 'sid-art', 'tasks'),
        )

    def test_two_levels_deep_nests_under_grandparent(self) -> None:
        """svg-artist from art-lead from project-lead lands inside art-lead.

        The path matches the dispatch tree's depth: each level adds
        one ``tasks/<sid>/`` segment.
        """
        art_lead = FakeSession(
            id='sid-art', path=os.path.join(self.job_tasks, 'sid-art'),
        )
        ctx = _make_ctx(self.job_tasks, registry={'sid-art': art_lead})
        # svg-artist is being dispatched FROM art-lead.
        result = _resolve_effective_tasks_dir(ctx, caller_sid='sid-art')
        # The svg-artist session would then be created at
        # ``{result}/<sid_svg>/`` = ``{job}/tasks/sid-art/tasks/<sid_svg>/``.
        self.assertEqual(
            result,
            os.path.join(self.job_tasks, 'sid-art', 'tasks'),
        )

    def test_three_levels_deep_nests_under_two_dispatchers(self) -> None:
        """Arbitrary depth: each dispatched level adds one tasks/ segment."""
        art_lead = FakeSession(
            id='sid-art',
            path=os.path.join(self.job_tasks, 'sid-art'),
        )
        # svg-artist was dispatched from art-lead and registered at
        # {job}/tasks/sid-art/tasks/sid-svg.
        svg_artist = FakeSession(
            id='sid-svg',
            path=os.path.join(self.job_tasks, 'sid-art', 'tasks', 'sid-svg'),
        )
        ctx = _make_ctx(
            self.job_tasks,
            registry={'sid-art': art_lead, 'sid-svg': svg_artist},
        )
        # svg-artist is now dispatching its own worker.
        result = _resolve_effective_tasks_dir(ctx, caller_sid='sid-svg')
        self.assertEqual(
            result,
            os.path.join(
                self.job_tasks, 'sid-art', 'tasks', 'sid-svg', 'tasks',
            ),
        )

    def test_chat_tier_returns_empty(self) -> None:
        """Chat-tier ctx (no tasks_dir) keeps the legacy catalog layout."""
        ctx = _make_ctx(tasks_dir='', registry={})
        self.assertEqual(_resolve_effective_tasks_dir(ctx, caller_sid=''), '')

    def test_unknown_caller_falls_back_to_top_level(self) -> None:
        """A caller_sid not in registry → treat as top-level."""
        ctx = _make_ctx(self.job_tasks, registry={})
        result = _resolve_effective_tasks_dir(ctx, caller_sid='nobody')
        self.assertEqual(result, self.job_tasks)


class CloseRecursiveReadsBusWorktreePathTest(unittest.TestCase):
    """``_close_recursive`` finds nested sessions via the bus, not by guessing."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='close-depth-')
        # Build a 3-deep hierarchy:
        #   {tmp}/job/tasks/<art>/tasks/<svg>/
        self.job_tasks = os.path.join(self._tmp, 'job', 'tasks')
        self.art_path = os.path.join(self.job_tasks, 'sid-art')
        self.svg_path = os.path.join(
            self.art_path, 'tasks', 'sid-svg',
        )
        os.makedirs(self.svg_path)
        # Write a metadata.json so _close_recursive's existence check passes.
        with open(os.path.join(self.svg_path, 'metadata.json'), 'w') as f:
            json.dump({'agent_name': 'svg-artist', 'worktree_path': ''}, f)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_finds_nested_session_via_bus_worktree_path(self) -> None:
        """Bus stores worktree_path; close walker derives session_path from it.

        The legacy fallback would look at ``{tasks_dir}/<sid>/`` —
        which for the deeply-nested svg-artist gives the wrong path.
        Bus-based lookup is the only one that works at arbitrary depth.
        """
        bus = MagicMock()
        # Conv stores the actual worktree path from arbitrary depth.
        bus_conv = MagicMock()
        bus_conv.worktree_path = os.path.join(self.svg_path, 'worktree')
        bus.get_conversation.return_value = bus_conv
        bus.children_of.return_value = []

        # legacy_sessions_dir is set but doesn't contain svg-artist;
        # tasks_dir is set to the JOB's tasks/ but svg-artist lives nested.
        # Without the bus-based lookup, the close path would fail.
        result = asyncio.run(_close_recursive(
            os.path.join(self._tmp, 'legacy', 'sessions'),
            'sid-svg',
            bus,
            tasks_dir=self.job_tasks,
        ))
        self.assertEqual(result['status'], 'ok')
        # The session_path was rmtreed — confirm the lookup found it.
        self.assertFalse(
            os.path.exists(self.svg_path),
            f'session at depth 2 should be cleaned up: {self.svg_path}',
        )


if __name__ == '__main__':
    unittest.main()
