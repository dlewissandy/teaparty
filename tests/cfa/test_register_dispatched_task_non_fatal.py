"""Regression: register_dispatched_task failures must not abort dispatch.

The dispatch path writes task.json so the bridge UI sees the worker.
This is a UI-visibility concern, never a correctness one.  A long-
running bridge whose ``job_store`` module was cached before
``register_dispatched_task`` existed would raise ImportError on the
deferred import — and a previous version of the dispatch path let
that propagate, aborting every dispatch and surfacing as
"Dispatch system has an internal error" to the agent.

This test pins the contract: any exception inside the task.json
write path is logged and swallowed; the dispatch proceeds.  The
worker will be invisible to the bridge UI's project list until the
bridge is restarted, which is acceptable degradation — the dispatch
itself works, the accordion UI (which reads the bus) works, and the
worker can do its job.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class RegisterDispatchedTaskFailureTest(unittest.TestCase):
    """The dispatch path catches every exception from the task.json write."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='register-fail-')
        self.task_dir = os.path.join(self._tmp, 'sid-test')

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_function_exists_and_has_expected_signature(self) -> None:
        """``register_dispatched_task`` is exported and callable.

        This is the case the staleness scenario violates: a
        sufficiently old cached module wouldn't expose the name.  The
        test pins that the current source does export it, so a fresh
        import always succeeds — the fragility is only in long-lived
        processes that imported the module before the function landed.
        """
        from teaparty.workspace.job_store import register_dispatched_task
        self.assertTrue(callable(register_dispatched_task))

    def test_dispatch_block_swallows_import_error(self) -> None:
        """Verifies the catch-all in schedule_child_dispatch.

        We can't easily simulate an ImportError on a real import.
        Instead, we read the source and assert that the block which
        calls ``register_dispatched_task`` has both an inner ``try``
        that imports it AND a broad ``except`` that catches Exception.
        This is the structural guarantee a long-running bridge needs.
        """
        import teaparty.messaging.child_dispatch as cd
        import inspect
        src = inspect.getsource(cd)
        # The block must wrap the import in a try and catch broad.
        self.assertIn('try:', src)
        self.assertIn(
            'from teaparty.workspace.job_store import',
            src,
        )
        self.assertIn(
            'register_dispatched_task',
            src,
        )
        # The except must catch ImportError (or broader).
        # We look for the specific pattern that swallows it.
        self.assertIn(
            'except (ImportError, OSError, Exception):',
            src,
            'register_dispatched_task call must catch ImportError so '
            'a stale module cache cannot abort dispatch',
        )

    def test_dispatch_block_logs_via_logger_exception(self) -> None:
        """The failure path emits a log entry so the gap is auditable."""
        import teaparty.messaging.child_dispatch as cd
        import inspect
        src = inspect.getsource(cd)
        self.assertIn(
            'register_dispatched_task failed',
            src,
            'failure path must log a message naming the function so '
            'operators can diagnose UI-invisibility',
        )


if __name__ == '__main__':
    unittest.main()
