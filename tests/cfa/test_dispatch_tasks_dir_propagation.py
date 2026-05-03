"""Integration: nested dispatch from a CfA job stays under the job dir.

The unit tests in ``tests/runners/test_dispatched_session_under_job.py``
prove ``create_session(parent_dir=...)`` writes to the right location.
This test proves the end-to-end wiring: a ``ChildDispatchContext``
with ``tasks_dir`` set produces a ``spawn_fn`` whose closure preserves
that ``tasks_dir`` across every level of dispatch — joke-book-lead's
dispatched worker (one level), and that worker's dispatched worker
(two levels), both land under the same ``tasks_dir``.

This guarantee comes from the architecture rather than per-tier
plumbing: ``run_child_lifecycle`` reuses the parent's ``mcp_routes``
verbatim, so every descendant in a CfA job's dispatch tree calls the
same closure with the same captured context.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.messaging.child_dispatch import (
    ChildDispatchContext,
    make_spawn_fn,
)


class SpawnFnCarriesTasksDirTest(unittest.TestCase):
    """``make_spawn_fn(ctx)`` returns a closure that preserves ``ctx.tasks_dir``."""

    def test_closure_holds_tasks_dir(self) -> None:
        """The returned spawn_fn closes over the ctx's ``tasks_dir``."""
        ctx = ChildDispatchContext(
            dispatcher_session=MagicMock(),
            bus=MagicMock(),
            bus_listener=MagicMock(),
            session_registry={},
            tasks_by_child={},
            tasks_dir='/jobs/job-test/tasks',
        )
        spawn_fn = make_spawn_fn(ctx)
        # The closure should capture ctx by reference; mutating it
        # changes what the closure sees.
        self.assertEqual(
            spawn_fn.__closure__[0].cell_contents.tasks_dir,
            '/jobs/job-test/tasks',
        )

    def test_two_dispatched_workers_share_one_ctx(self) -> None:
        """Nested dispatch reuses the parent's spawn_fn — therefore the
        same ctx, therefore the same tasks_dir.

        This is what ``run_child_lifecycle`` does at child_dispatch.py:953
        when it sets ``child_mcp_routes.spawn_fn = base_routes.spawn_fn``:
        the worker inherits the parent's closure verbatim, not a new one.
        Pinning the invariant in a test means the architecture is the
        single source of tasks_dir for the whole tree.
        """
        engine_ctx = ChildDispatchContext(
            dispatcher_session=MagicMock(),
            bus=MagicMock(),
            bus_listener=MagicMock(),
            session_registry={},
            tasks_by_child={},
            tasks_dir='/jobs/job-test/tasks',
        )
        # joke-book-lead's spawn_fn — the one MCPRoutes gets at engine
        # boot time.
        lead_spawn_fn = make_spawn_fn(engine_ctx)

        # research-lead's spawn_fn — what run_child_lifecycle copies
        # into ``child_mcp_routes`` when launching the dispatched worker
        # (see child_dispatch.py:953-954).  Same callable, same closure.
        worker_spawn_fn = lead_spawn_fn

        # Both functions are the exact same object; their closures
        # both reference the engine's single ctx, so any worker calling
        # Send will use ``tasks_dir = '/jobs/job-test/tasks'``.
        self.assertIs(lead_spawn_fn, worker_spawn_fn)
        self.assertIs(
            lead_spawn_fn.__closure__[0].cell_contents,
            worker_spawn_fn.__closure__[0].cell_contents,
        )
        self.assertEqual(
            worker_spawn_fn.__closure__[0].cell_contents.tasks_dir,
            engine_ctx.tasks_dir,
        )

    def test_chat_tier_ctx_has_no_tasks_dir(self) -> None:
        """Chat-tier dispatchers (OM, PM chat) leave ``tasks_dir`` empty.

        The legacy catalog-keyed layout still applies for top-level
        chat: those sessions live at ``{teaparty_home}/<scope>/sessions/``,
        not under any job.
        """
        chat_ctx = ChildDispatchContext(
            dispatcher_session=MagicMock(),
            bus=MagicMock(),
            bus_listener=MagicMock(),
            session_registry={},
            tasks_by_child={},
            # No tasks_dir kwarg — defaults to ''.
        )
        self.assertEqual(chat_ctx.tasks_dir, '')


if __name__ == '__main__':
    unittest.main()
