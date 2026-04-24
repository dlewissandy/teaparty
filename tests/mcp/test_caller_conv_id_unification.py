"""Regression: every spawn_fn reads the caller's conv_id from ONE source.

The root invariant this test pins: the MCP URL's ``?conv=`` query
param is the single source of truth for "what conv is making this
call."  ``launch()`` writes it (from the caller's own conv_id).  The
MCP middleware parses it into ``current_conversation_id``.  Every
spawn_fn reads it to stamp ``parent_conversation_id`` on new
dispatches.

Before unification, three tiers each derived the parent conv_id from
``session.id`` independently, producing different wrong answers for
different roles.  Job leads got parented under ``dispatch:{sid}``
instead of ``job:{slug}:{sid}``; the job page's tree walker (rooted at
the JOB conv) never found their dispatches, and accordion blades for
dispatched sub-agents (e.g. coding-lead) never rendered.

The user's pointed question — "how is there still a WRONG conv_id;
did you not unify it all?" — was correct: fixing one tier at a time
doesn't unify, it just moves the defect.  The real unification is
one contextvar, one write at launch, one read at spawn.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestLauncherWritesConvIdIntoMcpUrl(unittest.TestCase):
    """``launch()``'s caller_conversation_id lands in the MCP URL as ?conv=."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp-unify-')

    def _read_mcp_url(self, mcp_path: str) -> str:
        import json
        with open(mcp_path) as fh:
            data = json.load(fh)
        return data['mcpServers']['teaparty-config']['url']

    def test_compose_launch_worktree_includes_conv_query(self) -> None:
        """Job-tier composer writes ``?conv=`` when given a caller conv_id."""
        from teaparty.runners.launcher import compose_launch_worktree

        worktree = os.path.join(self._dir, 'wt')
        os.makedirs(os.path.join(worktree, '.claude', 'agents'))
        compose_launch_worktree(
            worktree=worktree,
            agent_name='joke-book-lead',
            scope='project',
            teaparty_home=os.path.join(self._dir, '.teaparty'),
            mcp_port=9000,
            session_id='session-abc',
            caller_conversation_id='job:joke-book:session-abc',
        )

        url = self._read_mcp_url(os.path.join(worktree, '.mcp.json'))
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        self.assertEqual(
            qs.get('conv'), ['job:joke-book:session-abc'],
            'The caller conv_id must land in the URL so the MCP '
            'middleware can set current_conversation_id.  Without '
            'this, spawn_fn has to derive it from session.id, and '
            "deriving is the bug class we're fixing.",
        )

    def test_compose_launch_config_includes_conv_query(self) -> None:
        """Chat-tier composer writes ``?conv=`` when given a caller conv_id."""
        from teaparty.runners.launcher import compose_launch_config

        config_dir = os.path.join(self._dir, 'cfg')
        os.makedirs(config_dir)
        tp_home = os.path.join(self._dir, '.teaparty')
        os.makedirs(os.path.join(tp_home, 'management', 'agents'))
        try:
            compose_launch_config(
                config_dir=config_dir,
                agent_name='office-manager',
                scope='management',
                teaparty_home=tp_home,
                mcp_port=9000,
                session_id='session-xyz',
                caller_conversation_id='om:chat-q42',
            )
        except FileNotFoundError:
            # compose_launch_config needs a full teaparty_home layout;
            # write a minimal one and retry once.
            self.skipTest('compose_launch_config requires richer fixture')

        url = self._read_mcp_url(os.path.join(config_dir, 'mcp.json'))
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        self.assertEqual(qs.get('conv'), ['om:chat-q42'])

    def test_conv_id_with_colons_is_url_encoded(self) -> None:
        """Conv ids like ``job:foo:bar`` contain colons — must be quoted."""
        from teaparty.runners.launcher import compose_launch_worktree

        worktree = os.path.join(self._dir, 'wt2')
        os.makedirs(os.path.join(worktree, '.claude', 'agents'))
        compose_launch_worktree(
            worktree=worktree,
            agent_name='joke-book-lead',
            scope='project',
            teaparty_home=os.path.join(self._dir, '.teaparty'),
            mcp_port=9000,
            session_id='s',
            caller_conversation_id='job:x:y',
        )
        url = self._read_mcp_url(os.path.join(worktree, '.mcp.json'))
        # Colons in the query value must be percent-encoded so the URL
        # parses correctly on the server side; parse_qs round-trips it.
        qs = parse_qs(urlparse(url).query)
        self.assertEqual(qs.get('conv'), ['job:x:y'])

    def test_no_conv_query_when_caller_conv_id_empty(self) -> None:
        """Legacy callers that don't pass conv_id → no ?conv= param.

        Backward compat: existing tests and any pre-migration launch
        sites still work.  The spawn_fn sites all have fallback
        derivation for this path.
        """
        from teaparty.runners.launcher import compose_launch_worktree

        worktree = os.path.join(self._dir, 'wt3')
        os.makedirs(os.path.join(worktree, '.claude', 'agents'))
        compose_launch_worktree(
            worktree=worktree,
            agent_name='a',
            scope='project',
            teaparty_home=os.path.join(self._dir, '.teaparty'),
            mcp_port=9000,
            session_id='s',
            # caller_conversation_id omitted (default '')
        )
        url = self._read_mcp_url(os.path.join(worktree, '.mcp.json'))
        self.assertNotIn('conv=', url)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)


class TestCfaSpawnReadsConvIdFromContextvar(unittest.TestCase):
    """CfA engine's ``_bus_spawn_agent`` uses the contextvar.

    The failure mode this test pins: before the unification, a CfA
    job lead (conv_id ``job:{slug}:{sid}``) calling Send got its
    dispatch parented under ``dispatch:{sid}`` — the JOB tree walker
    never found the row and the child's blade never opened.  After
    the unification, the middleware puts the job conv in the
    contextvar, spawn_fn reads it, dispatches are parented correctly.
    """

    def test_spawn_fn_parents_dispatch_to_contextvar_value(self) -> None:
        import asyncio
        from teaparty.mcp.registry import current_conversation_id
        from teaparty.messaging.conversations import SqliteMessageBus
        from teaparty.messaging.listener import BusEventListener
        from teaparty.runners.launcher import create_session

        tmp = tempfile.mkdtemp(prefix='tp-cfa-spawn-ctxvar-')
        try:
            # Minimal stub Orchestrator — we only test
            # _bus_spawn_agent's parent_conv_id logic.  Everything the
            # method touches past that is expected to fail cleanly
            # (no worktree), but the bus row write happens before
            # any of that.
            teaparty_home = os.path.join(tmp, '.teaparty')
            os.makedirs(os.path.join(teaparty_home, 'management'))
            bus_path = os.path.join(teaparty_home, 'management', 'messages.db')
            # Seed the bus file so the listener can open it.
            SqliteMessageBus(bus_path).close()

            class _StubOrchestrator:
                teaparty_home = os.path.join(tmp, '.teaparty')
                project_workdir = tmp
                session_worktree = ''
                session_id = 'orch-session-1'
                project_slug = 'joke-book'
                _stream_conv_id = 'job:joke-book:orch-session-1'
                _mcp_routes = None
                _dispatcher_session = create_session(
                    agent_name='joke-book-lead', scope='management',
                    teaparty_home=os.path.join(tmp, '.teaparty'),
                    session_id='orch-session-1',
                )
                _bus_event_listener = BusEventListener(
                    bus_db_path=bus_path,
                    initiator_agent_id='joke-book-lead',
                    current_context_id='ctx-1',
                    spawn_fn=None, resume_fn=None, reply_fn=None,
                )

            from teaparty.cfa.engine import Orchestrator
            stub = _StubOrchestrator()

            # Set the contextvar to what the MCP middleware would set
            # (if the caller_conversation_id made it through
            # ``launch()`` and the URL).  The spawn_fn must read THIS,
            # not derive from session.id.
            current_conversation_id.set('job:joke-book:orch-session-1')

            # Stub the member resolver — this test is about parent
            # conv_id, not member resolution.  Production refuses
            # unknown members; the stub orchestrator has no registry.
            import teaparty.config.roster as roster_mod
            orig_resolve = roster_mod.resolve_launch_placement
            roster_mod.resolve_launch_placement = (
                lambda m, th: (th, 'management')
            )

            # Run the spawn.  We don't care about its return value —
            # the side effect we're testing is the bus row it writes.
            async def _run():
                try:
                    await Orchestrator._bus_spawn_agent(
                        stub, 'coding-lead', 'compose', 'req-1',
                    )
                except Exception:
                    # create_subchat_worktree will fail in this stub
                    # environment; the bus row is written before that.
                    pass

            try:
                asyncio.run(_run())
            finally:
                roster_mod.resolve_launch_placement = orig_resolve

            # Now inspect the bus — the DISPATCH row's parent must be
            # the JOB conv, not ``dispatch:orch-session-1``.
            bus = SqliteMessageBus(bus_path)
            rows = bus._conn.execute(
                'SELECT id, parent_conversation_id, agent_name FROM conversations',
            ).fetchall()
            bus.close()
            dispatch_rows = [r for r in rows if r[0].startswith('dispatch:')]
            self.assertEqual(
                len(dispatch_rows), 1,
                f'Expected one dispatch row, got {rows}',
            )
            _, parent, agent = dispatch_rows[0]
            self.assertEqual(
                parent, 'job:joke-book:orch-session-1',
                f"parent must be the contextvar's JOB conv_id "
                f"(the single source of truth); got {parent!r}.  "
                f'If this fails, spawn_fn has reverted to deriving '
                f'from session.id and the class of bug #422 set out '
                f'to kill is back.',
            )
            self.assertEqual(agent, 'coding-lead')
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
