"""Issue #425: proxy memory store stays at the management tier.

The proxy is engaged from many places — AskQuestion in a project's job, a
participants-card click on the OM, a click on a project lead, and so on.
Whichever path engages it, the proxy's ``teaparty_home`` (where its
sessions, message bus, and ACT-R memory DB live) MUST be the management
home, not the caller's project home.

Without this, a project-tier engagement creates a per-project copy of the
proxy memory at ``<project>/.teaparty/proxy/.proxy-memory.db``.  That is
the fragmentation #425 forbids.

This test pins the invariant by exercising ``TeaPartyBridge._invoke_proxy``
with an explicit project-tier override and asserting the proxy's
AgentSession is created with ``teaparty_home`` = management.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import MethodType
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.bridge.server import TeaPartyBridge


class _MiniBridge:
    """Just enough of TeaPartyBridge's surface to drive _invoke_proxy."""

    def __init__(self, management_home: str):
        self.teaparty_home = management_home
        self._repo_root = os.path.dirname(management_home)
        self._agent_sessions: dict = {}
        self._agent_locks: dict = {}
        self._llm_backend = None
        self._paused_projects: set = set()
        self._broadcast_dispatch = lambda evt: None

        self._invoke_agent_calls: list[dict] = []

        async def fake_invoke_agent(**kwargs):
            self._invoke_agent_calls.append(kwargs)

        self._invoke_agent = fake_invoke_agent  # type: ignore[assignment]

    # The proxy invocation reaches into proxy/hooks.py for these.
    def _broadcast_dispatch_stub(self, evt: dict) -> None:
        pass


class ProxyTeapartyHomeIsManagementTest(unittest.TestCase):
    """The proxy AgentSession's teaparty_home must always be management,
    not whatever the caller passed in."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='proxy-mem-home-')
        self.management_home = os.path.join(self._tmp, 'management', '.teaparty')
        self.project_home = os.path.join(self._tmp, 'jokebook', '.teaparty')
        os.makedirs(self.management_home)
        os.makedirs(self.project_home)
        self.mini = _MiniBridge(self.management_home)
        # Bind real _invoke_proxy from TeaPartyBridge onto the mini.
        self.mini._invoke_proxy = MethodType(
            TeaPartyBridge._invoke_proxy, self.mini,
        )

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, qualifier: str, **kwargs):
        coro = self.mini._invoke_proxy(qualifier, **kwargs)
        asyncio.run(coro)

    def test_management_invocation_uses_management_home(self) -> None:
        # Bare-name qualifier (management-page click).  ``cwd`` is
        # required by ``_invoke_proxy``; pass a placeholder.
        self._run('primus', cwd=self.management_home)
        self.assertEqual(
            len(self.mini._invoke_agent_calls), 1,
            'expected exactly one _invoke_agent call',
        )
        call = self.mini._invoke_agent_calls[0]
        self.assertEqual(
            call.get('teaparty_home', ''), self.management_home,
            f"proxy launch must use management home "
            f"({self.management_home}); got {call.get('teaparty_home')!r}",
        )

    def test_project_caller_override_is_ignored(self) -> None:
        # A project-tier caller might pass its own teaparty_home; the
        # proxy must ignore it and stay at management (#425).
        self._run(
            'joke-book:primus',
            cwd='/tmp/some-job-worktree',
            teaparty_home=self.project_home,
            scope='project',
        )
        self.assertEqual(
            len(self.mini._invoke_agent_calls), 1,
            'expected exactly one _invoke_agent call',
        )
        call = self.mini._invoke_agent_calls[0]
        self.assertEqual(
            call.get('teaparty_home', ''), self.management_home,
            "proxy launched with project-tier teaparty_home override; "
            "memory would fragment under <project>/.teaparty/proxy/. "
            f"Expected {self.management_home}, got "
            f"{call.get('teaparty_home')!r}.  #425 invariant: memory "
            "lives at management regardless of caller.",
        )

    def test_management_home_used_even_when_scope_is_project(self) -> None:
        self._run(
            'joke-book:primus',
            cwd='/tmp/joke-book/worktree',
            teaparty_home=self.project_home,
            scope='project',
        )
        call = self.mini._invoke_agent_calls[0]
        # The scope can be 'project' (the conversation belongs to a project),
        # but the storage home for proxy state is still management.
        self.assertNotEqual(
            call.get('teaparty_home', ''), self.project_home,
            "proxy invoked with scope='project' must NOT inherit the "
            "project's teaparty_home — memory fragmentation (#425)",
        )


if __name__ == '__main__':
    unittest.main()
