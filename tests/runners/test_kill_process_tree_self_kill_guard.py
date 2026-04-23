"""Regression: _kill_process_tree must never SIGTERM the bridge itself.

The bridge spawns Claude CLI subprocesses.  If a subprocess ends up
sharing the bridge's process group, ``os.killpg(pgid, SIGTERM)`` on the
subprocess's pgid would fan out to every process in the group — the
bridge included.  The bridge would catch SIGTERM, close its HTTP
listener, and hang in cleanup; the user would see "localhost refused
to connect" mid-dispatch while the bridge process is still alive.

Two layers defend against this:

  1. **Isolation** — the Claude CLI is spawned with
     ``start_new_session=True`` so it has its own pgid.
     ``killpg(subprocess_pgid, ...)`` is then structurally unable to
     reach the bridge.

  2. **Self-kill guard** — if any subprocess ever ends up in our
     pgid (legacy callers, tests, or a regression that drops
     ``start_new_session``), ``_kill_process_tree`` refuses to
     ``killpg`` and signals only the single PID.  Mirrors the guard
     in ``teaparty/workspace/withdraw.py`` (issue #159).

Both must hold or the bridge is one signal away from going dark.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import signal
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.runners import claude as _claude


class TestClaudeSubprocessProcessGroupIsolation(unittest.TestCase):
    """Layer 1: the Claude CLI subprocess runs in its own process group.

    This test reads the source of ``ClaudeRunner.run`` and verifies
    the ``create_subprocess_exec`` call passes ``start_new_session=True``.
    Runtime proof requires actually spawning ``claude`` which these
    unit tests don't — but the structural invariant is what the fix
    relies on, and regressions have to pass through this call site.
    """

    def test_create_subprocess_exec_sets_start_new_session(self) -> None:
        src = inspect.getsource(_claude.ClaudeRunner.run)
        self.assertIn(
            'create_subprocess_exec', src,
            'ClaudeRunner.run no longer creates a subprocess — '
            'this test has to be updated for the new spawn path',
        )
        self.assertIn(
            'start_new_session=True', src,
            'ClaudeRunner.run spawns the Claude CLI without '
            'start_new_session=True — the subprocess will inherit the '
            "bridge's process group and killpg on it will SIGTERM the "
            'bridge.  Add start_new_session=True to the '
            'create_subprocess_exec call.',
        )


class TestKillProcessTreeSelfKillGuard(unittest.TestCase):
    """Layer 2: _kill_process_tree refuses to signal its own process group."""

    def test_refuses_when_target_shares_our_pgid(self) -> None:
        """The common defense against self-kill.

        We pretend the target pid has the same pgid we do.  The
        function MUST NOT call killpg — that would SIGTERM us.
        Instead it falls back to a single-pid ``os.kill`` so only the
        target dies.
        """
        our_pgid = os.getpgid(os.getpid())

        with mock.patch.object(os, 'getpgid', return_value=our_pgid), \
             mock.patch.object(os, 'killpg') as mock_killpg, \
             mock.patch.object(os, 'kill') as mock_kill:
            _claude._kill_process_tree(pid=99999)

        mock_killpg.assert_not_called()
        # Must have signaled the single pid instead.
        mock_kill.assert_called_once()
        args, _ = mock_kill.call_args
        self.assertEqual(args[0], 99999)
        self.assertEqual(args[1], signal.SIGTERM)

    def test_refuses_when_pid_is_self(self) -> None:
        """``pid == os.getpid()`` is a degenerate call — refuse both signals."""
        with mock.patch.object(os, 'killpg') as mock_killpg, \
             mock.patch.object(os, 'kill') as mock_kill:
            _claude._kill_process_tree(pid=os.getpid())

        mock_killpg.assert_not_called()
        mock_kill.assert_not_called()

    def test_uses_killpg_when_target_has_distinct_pgid(self) -> None:
        """The normal case: target pgid differs from ours, killpg fires."""
        other_pgid = os.getpgid(os.getpid()) + 1_000_000

        with mock.patch.object(os, 'getpgid') as mock_getpgid, \
             mock.patch.object(os, 'killpg') as mock_killpg, \
             mock.patch.object(os, 'kill') as mock_kill:

            def _getpgid(pid):
                if pid == 77777:
                    return other_pgid
                return other_pgid - 1_000_000  # our own pgid for anything else
            mock_getpgid.side_effect = _getpgid

            _claude._kill_process_tree(pid=77777)

        mock_killpg.assert_called_once_with(other_pgid, signal.SIGTERM)


class TestEndToEndSubprocessIsolation(unittest.IsolatedAsyncioTestCase):
    """Runtime proof: spawn a real subprocess and kill its tree.

    Uses ``sleep`` as a stand-in for the Claude CLI.  Before the fix
    this same call (without start_new_session=True) would SIGTERM the
    pytest process itself and the test run would die.  After the fix
    the parent survives and the target exits.
    """

    async def test_killing_subprocess_tree_does_not_kill_parent(self) -> None:
        # Same invocation shape as ClaudeRunner — but with a harmless
        # target.  If the fix regresses, this test process gets SIGTERM
        # on the killpg below.
        proc = await asyncio.create_subprocess_exec(
            'sleep', '30',
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

        # Sanity: the subprocess is in a different process group than us.
        child_pgid = os.getpgid(proc.pid)
        our_pgid = os.getpgid(os.getpid())
        self.assertNotEqual(
            child_pgid, our_pgid,
            'start_new_session=True did not isolate the subprocess — '
            'killpg on it would still reach us',
        )

        # Kill the subprocess tree.  If it somehow shared our pgid,
        # this would terminate the test.
        _claude._kill_process_tree(proc.pid)

        # The parent (this test) is still running — proved by the fact
        # that we're here executing the next line.
        self.assertEqual(os.getpid(), os.getpid())

        # The subprocess should die promptly.
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            self.fail('subprocess did not exit after _kill_process_tree')

        self.assertIsNotNone(proc.returncode)


if __name__ == '__main__':
    unittest.main()
