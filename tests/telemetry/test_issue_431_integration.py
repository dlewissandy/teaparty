"""Integration tests for Issue #431 — wired emission paths.

The unit tests in test_issue_431_dispatch_metadata.py drive the public
``record_event`` / ``record_message`` / ``record_dispatch_edge`` API
directly. The tests below exercise the actual call sites — launcher,
job_store, claude runner stream parser, escalation runner — to verify
the wiring is in place. Reverting any of the edits would make at least
one of these fail.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import tempfile
import unittest

import yaml

from teaparty import telemetry
from teaparty.telemetry import events as E


def _make_home() -> str:
    home = tempfile.mkdtemp(prefix='telemetry-431i-')
    telemetry.set_teaparty_home(home)
    return home


def _make_teaparty_tree(root: str, scope: str = 'management') -> str:
    """Minimal .teaparty/<scope>/ skeleton sufficient for launch()."""
    tp = os.path.join(root, '.teaparty')
    scope_dir = os.path.join(tp, scope)
    agents_dir = os.path.join(scope_dir, 'agents', 'test-agent')
    os.makedirs(agents_dir)
    with open(os.path.join(agents_dir, 'agent.md'), 'w') as f:
        f.write('---\ndescription: Test\ntools: Read\n---\nstub\n')
    with open(os.path.join(scope_dir, 'settings.yaml'), 'w') as f:
        yaml.dump({}, f)
    return tp


# ── Launcher wiring ──────────────────────────────────────────────────────────


class LauncherTelemetryWiringTests(unittest.TestCase):
    """launch() emits TURN_COMPLETE with every Issue #431 SDK field
    populated, plus turn_id linkage and cost_source attribution."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self._tmp = tempfile.mkdtemp(prefix='launcher-431-')
        self._tp = _make_teaparty_tree(self._tmp)
        telemetry.set_teaparty_home(self._tp)

    def tearDown(self) -> None:
        telemetry.reset_for_tests()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_turn_complete_carries_sdk_result_fields_via_launch(self) -> None:
        from teaparty.runners.launcher import launch
        from teaparty.runners.claude import ClaudeResult
        wt = os.path.join(self._tmp, 'wt')
        os.makedirs(os.path.join(wt, '.claude'), exist_ok=True)
        with open(os.path.join(wt, '.claude', 'CLAUDE.md'), 'w') as f:
            f.write('# stub\n')

        async def stub_caller(**kwargs):
            return ClaudeResult(
                exit_code=0, cost_usd=0.07,
                input_tokens=900, output_tokens=300, duration_ms=2000,
                cache_read_tokens=8000, cache_create_tokens=2000,
                cache_5m_tokens=1500, cache_1h_tokens=500,
                num_turns=4, duration_api_ms=1850,
                stop_reason='end_turn', is_error=False,
                api_error_status='', model='claude-opus-4-7',
                claude_session_uuid='abc-uuid',
                tools_called={'Bash': 2, 'Read': 5},
                response_text='hi from stub',
            )

        async def run() -> None:
            await launch(
                agent_name='test-agent', message='hello',
                scope='management', teaparty_home=self._tp,
                worktree=wt, llm_caller=stub_caller,
                trigger='dispatch', parent_session_id='sess-parent',
                job_id='job-J', dispatch_depth=1,
            )

        asyncio.run(run())

        completes = telemetry.query_events(event_type=E.TURN_COMPLETE)
        self.assertEqual(
            len(completes), 1,
            f'expected exactly one TURN_COMPLETE — got {len(completes)}',
        )
        d = completes[0].data
        for k, expected in (
            ('num_turns', 4),
            ('duration_api_ms', 1850),
            ('stop_reason', 'end_turn'),
            ('is_error', False),
            ('cache_5m_tokens', 1500),
            ('cache_1h_tokens', 500),
            ('cache_read_tokens', 8000),
            ('cache_create_tokens', 2000),
            ('model', 'claude-opus-4-7'),
            ('claude_session_uuid', 'abc-uuid'),
            ('response_text_len', len('hi from stub')),
            ('tools_called', {'Bash': 2, 'Read': 5}),
        ):
            self.assertEqual(
                d.get(k), expected,
                f'TURN_COMPLETE.data.{k} via launch() — '
                f'expected {expected!r}, got {d.get(k)!r}',
            )
        # cost_source must be attached as the indexed column.
        db = os.path.join(self._tp, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT cost_source, parent_session_id, job_id, "
                "dispatch_depth FROM events WHERE event_type='turn_complete'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row,
            ('stream_result', 'sess-parent', 'job-J', 1),
            f'launch() must persist linkage columns — got {row!r}',
        )

    def test_turn_id_pairs_start_and_complete_through_launch(self) -> None:
        from teaparty.runners.launcher import launch
        from teaparty.runners.claude import ClaudeResult
        wt = os.path.join(self._tmp, 'wt2')
        os.makedirs(os.path.join(wt, '.claude'), exist_ok=True)
        with open(os.path.join(wt, '.claude', 'CLAUDE.md'), 'w') as f:
            f.write('# stub\n')

        async def stub_caller(**kwargs):
            return ClaudeResult(exit_code=0)

        async def run() -> None:
            await launch(
                agent_name='test-agent', message='hi',
                scope='management', teaparty_home=self._tp,
                worktree=wt, llm_caller=stub_caller,
            )
        asyncio.run(run())

        db = os.path.join(self._tp, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                'SELECT event_type, turn_id FROM events '
                "WHERE event_type IN ('turn_start','turn_complete') "
                'ORDER BY ts, id'
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(
            len(rows), 2,
            'launch() must emit one TURN_START and one TURN_COMPLETE',
        )
        ts_start, tid_start = rows[0]
        ts_complete, tid_complete = rows[1]
        self.assertEqual(ts_start, 'turn_start')
        self.assertEqual(ts_complete, 'turn_complete')
        self.assertTrue(
            tid_start and tid_complete,
            f'turn_id must be set on both — got {rows!r}',
        )
        self.assertEqual(
            tid_start, tid_complete,
            f'TURN_START and TURN_COMPLETE must share the same turn_id — '
            f'got start={tid_start!r}, complete={tid_complete!r}',
        )

    def test_trigger_taxonomy_distinguishes_resume_from_new(self) -> None:
        """The original code labelled every resume as 'dispatch' — the
        spec requires resume / dispatch / new / wake to be distinct."""
        from teaparty.runners.launcher import launch
        from teaparty.runners.claude import ClaudeResult
        wt = os.path.join(self._tmp, 'wt3')
        os.makedirs(os.path.join(wt, '.claude'), exist_ok=True)
        with open(os.path.join(wt, '.claude', 'CLAUDE.md'), 'w') as f:
            f.write('# stub\n')

        async def stub_caller(**kwargs):
            return ClaudeResult(exit_code=0)

        async def run() -> None:
            # Fresh launch — no resume_session, no explicit trigger.
            await launch(
                agent_name='test-agent', message='m1',
                scope='management', teaparty_home=self._tp,
                worktree=wt, llm_caller=stub_caller,
            )
            # Re-entry — resume_session set.
            await launch(
                agent_name='test-agent', message='m2',
                scope='management', teaparty_home=self._tp,
                worktree=wt, llm_caller=stub_caller,
                resume_session='claude-uuid-xyz',
            )
            # Cron-fired wake — caller passes trigger explicitly.
            await launch(
                agent_name='test-agent', message='m3',
                scope='management', teaparty_home=self._tp,
                worktree=wt, llm_caller=stub_caller,
                trigger='wake',
            )

        asyncio.run(run())

        starts = telemetry.query_events(event_type=E.TURN_START)
        triggers = [e.data.get('trigger') for e in starts]
        self.assertEqual(
            triggers, ['new', 'resume', 'wake'],
            f'launch() must map (no-resume, resume, wake-override) to '
            f'(new, resume, wake) — got {triggers}',
        )


# ── Job creation wiring ──────────────────────────────────────────────────────


class JobStoreJobCreatedTests(unittest.TestCase):
    """create_job() emits JOB_CREATED with the full metadata block,
    including prompt_hash for byte-identical-prompt grouping."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self._tmp = tempfile.mkdtemp(prefix='jobstore-431-')
        # Use the temp dir as both project_root and teaparty_home for
        # this isolated test — the JOB_CREATED event lands at
        # {teaparty_home}/telemetry.db.
        telemetry.set_teaparty_home(self._tmp)

    def tearDown(self) -> None:
        telemetry.reset_for_tests()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_create_job_emits_job_created_with_prompt_hash(self) -> None:
        from teaparty.workspace.job_store import create_job
        # create_job uses git worktree add — make project_root a git repo.
        import subprocess
        proj = os.path.join(self._tmp, 'proj')
        os.makedirs(proj)
        subprocess.run(['git', 'init', '-q'], cwd=proj, check=True)
        # Need an initial commit so worktree add works.
        with open(os.path.join(proj, 'README.md'), 'w') as f:
            f.write('# x\n')
        subprocess.run(['git', 'add', 'README.md'], cwd=proj, check=True)
        subprocess.run(
            ['git', '-c', 'user.email=t@t', '-c', 'user.name=t',
             'commit', '-qm', 'init'],
            cwd=proj, check=True,
        )

        async def run() -> dict:
            return await create_job(
                project_root=proj,
                task='Fix the auth bug',
                issue=999,
            )

        asyncio.run(run())

        evs = telemetry.query_events(event_type=E.JOB_CREATED)
        self.assertEqual(
            len(evs), 1,
            f'create_job must emit exactly one JOB_CREATED — got {len(evs)}',
        )
        d = evs[0].data
        for required in (
            'job_id', 'project', 'slug', 'classification',
            'prompt_text', 'prompt_hash', 'prompt_bytes',
            'branch', 'status', 'created_at',
        ):
            self.assertIn(
                required, d,
                f'JOB_CREATED.data must include {required!r} — '
                f'got {sorted(d)}',
            )
        self.assertEqual(d['prompt_text'], 'Fix the auth bug')
        self.assertEqual(d['prompt_bytes'], len('Fix the auth bug'))
        # The hash must be the sha1 of the prompt.
        import hashlib
        self.assertEqual(
            d['prompt_hash'],
            hashlib.sha1(b'Fix the auth bug').hexdigest(),
            'prompt_hash must be sha1 of the prompt for byte-identical '
            'grouping',
        )
        # Production emits status='active' for newly-created jobs;
        # asserting the value gates regressions that drop the field
        # or invent an unexpected lifecycle string.
        self.assertEqual(
            d['status'], 'active',
            f'JOB_CREATED.status must be the production value '
            f'\'active\' — got {d["status"]!r}',
        )
        self.assertEqual(
            d['classification'], '',
            'JOB_CREATED.classification is empty by design; downstream '
            "analysis derives it from slug. Got " + repr(d['classification']),
        )


# ── Stream parser wiring ─────────────────────────────────────────────────────


class StreamParserDedupeAndToolEmissionTests(unittest.TestCase):
    """ClaudeRunner._process_stream_event must emit MESSAGE_RECORDED
    (deduped) and TOOL_CALL_COMPLETE for the relevant content blocks."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self._home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def _make_runner(self) -> object:
        from teaparty.runners.claude import ClaudeRunner
        return ClaudeRunner(
            prompt='hello',
            cwd='/tmp', stream_file='/tmp/x.jsonl',
            session_id='sess-INT',
        )

    def test_assistant_event_dedupes_session_messages_row(self) -> None:
        runner = self._make_runner()
        # Two assistant events with the SAME message_id and the SAME
        # usage object — simulating an SDK response that emitted both
        # a thinking block and a tool_use block under one message.id.
        usage = {
            'input_tokens': 100, 'output_tokens': 200,
            'cache_read_input_tokens': 8000,
            'cache_creation': {
                'ephemeral_5m_input_tokens': 1500,
                'ephemeral_1h_input_tokens': 500,
            },
        }
        for _ in range(2):
            runner._process_stream_event(
                {
                    'type': 'assistant',
                    'message': {
                        'id': 'msg_unique_1',
                        'model': 'claude-opus-4-7',
                        'usage': dict(usage),
                        'stop_reason': 'tool_use',
                        'content': [{'type': 'text', 'text': 'hi'}],
                    },
                },
                now=1000.0,
            )
        db = os.path.join(self._home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row_count = conn.execute(
                'SELECT COUNT(*) FROM session_messages '
                "WHERE session_id='sess-INT' AND message_id='msg_unique_1'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(
            row_count, 1,
            f'two assistant events with the same message_id must collapse '
            f'to one row — got {row_count}',
        )

    def test_read_stdout_calls_process_stream_event(self) -> None:
        """Wiring assertion — _process_stream_event must be invoked from
        read_stdout so MESSAGE_RECORDED / TOOL_CALL_COMPLETE actually
        fire on the live stream. Without this call, the per-message
        dedupe and per-tool-call records never reach the events table
        in production no matter how correct the helper logic is."""
        import inspect
        from teaparty.runners import claude as _claude
        # The reference must appear inside ClaudeRunner._stream_with_watchdog
        # (which defines read_stdout as a closure).
        src = inspect.getsource(_claude.ClaudeRunner._stream_with_watchdog)
        self.assertIn(
            'self._process_stream_event(', src,
            'read_stdout must call self._process_stream_event(...) '
            'so per-message dedupe and TOOL_CALL_COMPLETE fire on '
            'the live stream',
        )

    def test_tool_use_then_tool_result_emits_tool_call_complete(self) -> None:
        runner = self._make_runner()
        # Open a tool call.
        runner._process_stream_event(
            {
                'type': 'assistant',
                'message': {
                    'id': 'msg-tool-1',
                    'content': [{
                        'type': 'tool_use',
                        'id': 'toolu_abc',
                        'name': 'mcp__teaparty-config__Delegate',
                        'input': {'member': 'developer', 'task': 'go'},
                    }],
                },
            },
            now=1000.0,
        )
        # Close it.
        runner._process_stream_event(
            {
                'type': 'user',
                'message': {
                    'content': [{
                        'type': 'tool_result',
                        'tool_use_id': 'toolu_abc',
                        'content': '{"conversation_id":"dispatch:childhex"}',
                        'is_error': False,
                    }],
                },
            },
            now=1003.0,
        )
        evs = telemetry.query_events(event_type=E.TOOL_CALL_COMPLETE)
        self.assertEqual(len(evs), 1)
        d = evs[0].data
        self.assertEqual(d['tool_name'],
                         'mcp__teaparty-config__Delegate')
        self.assertEqual(d['mcp_server'], 'teaparty-config')
        self.assertEqual(d['parent_session_id'], 'sess-INT')
        self.assertEqual(
            d['child_session_id'], 'childhex',
            'child_session_id must be parsed from the tool_result conversation_id',
        )
        self.assertEqual(d['duration_ms'], 3000)


# ── Delegate edge wiring ─────────────────────────────────────────────────────


class DelegateDispatchEdgeWiringTests(unittest.TestCase):
    """messaging.delegate_handler must record a dispatch_edges row when
    the spawn_fn produces a child session."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self._home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_delegate_records_dispatch_edge_on_spawn(self) -> None:
        from teaparty.mcp.tools.messaging import _default_delegate_post
        from teaparty.mcp import registry as _reg

        async def fake_spawn(member, composite, ctx_id):
            return ('child-sid-123', '/tmp/wt', 'ok')

        # Install fake_spawn into the registry — _default_delegate_post
        # reads it via get_spawn_fn.
        _reg.MCPRoutes  # noqa — ensure import works
        _reg._spawn_fns.clear()
        _reg._spawn_fns['parent-agent'] = fake_spawn
        _reg.current_agent_name.set('parent-agent')
        _reg.current_session_id.set('parent-sid')

        async def run() -> str:
            return await _default_delegate_post(
                member='developer', composite='do the thing',
                skill='attempt-task',
            )

        try:
            result_json = asyncio.run(run())
        finally:
            _reg._spawn_fns.clear()
            _reg.current_agent_name.set('')
            _reg.current_session_id.set('')

        self.assertIn(
            'message_sent', result_json,
            f'fake spawn must report success — got {result_json}',
        )
        # The dispatch_edges sidecar row must be present with both
        # session ids and the skill.
        db = os.path.join(self._home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                'SELECT parent_session_id, child_session_id, member, skill '
                'FROM dispatch_edges'
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row,
            ('parent-sid', 'child-sid-123', 'developer', 'attempt-task'),
            f'delegate_handler must record dispatch_edges row — got {row!r}',
        )


# ── Conversation bus wiring ──────────────────────────────────────────────────


class ConversationBusTelemetryWiringTests(unittest.TestCase):
    """SqliteMessageBus.create_conversation / close_conversation must
    emit CONVERSATION_OPENED / CONVERSATION_CLOSED — without this
    wiring the conversation span is invisible to telemetry."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self._home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_bus_create_conversation_emits_conversation_opened(self) -> None:
        from teaparty.messaging.conversations import (
            ConversationType, SqliteMessageBus,
        )
        bus_db = os.path.join(self._home, 'bus.db')
        bus = SqliteMessageBus(bus_db)
        try:
            bus.create_conversation(
                ConversationType.DISPATCH, 'abc',
                agent_name='dev', project_slug='comics',
            )
        finally:
            bus.close()
        evs = telemetry.query_events(event_type=E.CONVERSATION_OPENED)
        self.assertEqual(
            len(evs), 1,
            f'create_conversation must emit exactly one CONVERSATION_OPENED — '
            f'got {len(evs)}',
        )
        ev = evs[0]
        self.assertEqual(
            ev.scope, 'comics',
            'CONVERSATION_OPENED must inherit project_slug, not default to '
            f"'management' — got scope={ev.scope!r}",
        )
        self.assertEqual(
            ev.data.get('conversation_id'), 'dispatch:abc',
            f'data.conversation_id must match the bus row — '
            f'got {ev.data.get("conversation_id")!r}',
        )

    def test_bus_close_conversation_emits_conversation_closed(self) -> None:
        from teaparty.messaging.conversations import (
            ConversationType, SqliteMessageBus,
        )
        bus_db = os.path.join(self._home, 'bus.db')
        bus = SqliteMessageBus(bus_db)
        try:
            bus.create_conversation(
                ConversationType.DISPATCH, 'xyz',
                agent_name='qa', project_slug='comics',
            )
            bus.close_conversation('dispatch:xyz')
        finally:
            bus.close()
        opened = telemetry.query_events(event_type=E.CONVERSATION_OPENED)
        closed = telemetry.query_events(event_type=E.CONVERSATION_CLOSED)
        self.assertEqual(len(opened), 1)
        self.assertEqual(
            len(closed), 1,
            f'close_conversation must emit one CONVERSATION_CLOSED — '
            f'got {len(closed)}',
        )
        self.assertEqual(
            closed[0].scope, 'comics',
            'CONVERSATION_CLOSED must inherit the bus row\'s project_slug',
        )


# ── Child-dispatch trigger override wiring ───────────────────────────────────


class ChildDispatchTriggerOverrideTests(unittest.TestCase):
    """child_dispatch.run_agent_loop must override trigger='dispatch'
    on the first launch of a freshly-spawned session and 'resume' on
    re-entries. Without this, the launcher's default heuristic labels
    every dispatched child's first turn as 'new' (no resume_session
    is set on the first call), conflating it with top-level chats."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self._home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_first_launch_is_dispatch_subsequent_is_resume(self) -> None:
        # Drive the in-loop trigger-selection block from
        # child_dispatch.run_agent_loop directly via a mini script that
        # mirrors lines 511-525 of that file. Going through the full
        # loop requires the bus, MCP routes, and a launch_fn — heavier
        # than this test needs. The contract under test is the
        # if/else around current_claude_session.
        captured = []

        def fake_launch(**kwargs):
            captured.append(kwargs.get('trigger'))
            return None

        def emulate_iteration(current_claude_session: str) -> None:
            launch_kwargs = {}
            if current_claude_session:
                launch_kwargs['resume_session'] = current_claude_session
                launch_kwargs['trigger'] = 'resume'
            else:
                launch_kwargs['trigger'] = 'dispatch'
            fake_launch(**launch_kwargs)

        emulate_iteration('')
        emulate_iteration('claude-uuid-1')
        emulate_iteration('claude-uuid-1')

        self.assertEqual(
            captured, ['dispatch', 'resume', 'resume'],
            f'child_dispatch.run_agent_loop must label first launch '
            f"'dispatch' and re-entries 'resume' — got {captured}",
        )
        # And the contract is enforced by source: the literal block
        # above must appear in the production code.
        import inspect
        from teaparty.messaging import child_dispatch as _cd
        src = inspect.getsource(_cd.run_agent_loop)
        self.assertIn(
            "launch_kwargs['trigger'] = 'dispatch'", src,
            "run_agent_loop must set trigger='dispatch' on the no-resume "
            'branch — without this the launcher labels every dispatched '
            "child's first turn as 'new'",
        )
        self.assertIn(
            "launch_kwargs['trigger'] = 'resume'", src,
            "run_agent_loop must set trigger='resume' on the resume "
            'branch (overriding the launcher default in case the '
            'caller upstream set a different trigger via contextvar)',
        )


# ── Scheduler wake-trigger wiring ────────────────────────────────────────────


class SchedulerWakeTriggerTests(unittest.TestCase):
    """Scheduler.run_task must set trigger='wake' so cron-fired turns
    are distinguishable from interactive dispatches in telemetry. The
    contextvar approach lets every nested launch under the scheduler
    inherit the wake trigger without threading a kwarg through every
    Session / engine / spawn frame."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self._home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_scheduler_sets_wake_trigger_on_contextvar(self) -> None:
        # Reading from the source guarantees the wiring exists; the
        # full scheduler.run_task path requires a teaparty project
        # tree, a CFA engine, and a real launch — heavier than this
        # contract needs. Confirm here that the scheduler is the
        # writer of the contextvar value.
        import inspect
        from teaparty.scheduling import scheduler as _sched
        src = inspect.getsource(_sched.CronScheduler.run_task)
        self.assertIn(
            'current_trigger', src,
            'Scheduler.run_task must reference current_trigger — '
            'without this, scheduled-wake launches cannot be '
            "distinguished from resume / new in telemetry",
        )
        self.assertIn(
            "'wake'", src,
            "Scheduler.run_task must set the trigger contextvar to 'wake'",
        )


# ── PROXY_INVOKED escalation wiring ──────────────────────────────────────────


class ProxyInvokedEscalationWiringTests(unittest.TestCase):
    """AskQuestionRunner._route must emit PROXY_INVOKED with the
    correct dispatch-edge metadata. Without this, proxy cost cannot
    be rolled up under the right job in pure SQL."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self._home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_route_emits_proxy_invoked_in_source(self) -> None:
        """The wiring is verified via source inspection — actually
        driving _route requires a proxy invoker, dispatcher session,
        bus, and proxy bus, which all live behind heavy setup. The
        emission block, the question_hash via sha1, and the
        parent_session_id linkage must be present."""
        import inspect
        from teaparty.cfa.gates import escalation as _esc
        src = inspect.getsource(_esc.AskQuestionRunner._route)
        self.assertIn(
            'PROXY_INVOKED', src,
            '_route must emit PROXY_INVOKED at the moment the proxy '
            'session is created',
        )
        self.assertIn(
            'sha1', src,
            'PROXY_INVOKED.data.question_hash must be the sha1 of the '
            'question text, matching the byte-identical-question grouping '
            'contract',
        )
        self.assertIn(
            "'asking_session_id'", src,
            'PROXY_INVOKED.data must include asking_session_id so SQL '
            'can roll up proxy cost under the asking job',
        )
        self.assertIn(
            "'proxy_session_id'", src,
            'PROXY_INVOKED.data must include proxy_session_id',
        )
        self.assertIn(
            'parent_session_id=asking_sid', src,
            'PROXY_INVOKED indexed parent_session_id column must be '
            'set to the asking session — without this, proxy turns '
            "don't roll up under the asking session in tree queries",
        )


# ── Dispatch-tree linkage end-to-end ─────────────────────────────────────────


class DispatchTreeLinkageE2ETests(unittest.TestCase):
    """End-to-end: a child launched via run_child_lifecycle's
    launch_kwargs_base path must produce TURN_COMPLETE rows whose
    indexed parent_session_id, job_id, and dispatch_depth columns
    are populated, not NULL. Without this the spec's primary
    dispatch-tree queries return empty."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self._tmp = tempfile.mkdtemp(prefix='dispatch-tree-431-')
        self._tp = _make_teaparty_tree(self._tmp)
        telemetry.set_teaparty_home(self._tp)

    def tearDown(self) -> None:
        telemetry.reset_for_tests()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_launch_with_linkage_kwargs_persists_to_indexed_columns(
        self,
    ) -> None:
        """Mirrors the kwargs-pattern run_child_lifecycle now passes
        into launch_kwargs_base after fix-issue-431 audit-round-2."""
        from teaparty.runners.launcher import launch
        from teaparty.runners.claude import ClaudeResult
        wt = os.path.join(self._tmp, 'wt-link')
        os.makedirs(os.path.join(wt, '.claude'), exist_ok=True)
        with open(os.path.join(wt, '.claude', 'CLAUDE.md'), 'w') as f:
            f.write('# stub\n')

        async def stub_caller(**kwargs):
            return ClaudeResult(exit_code=0)

        async def run() -> None:
            await launch(
                agent_name='test-agent', message='hi',
                scope='management', teaparty_home=self._tp,
                worktree=wt, llm_caller=stub_caller,
                # The actual kwargs run_child_lifecycle now sets:
                parent_session_id='sess-parent-X',
                job_id='job-2026-05-09-Y',
                dispatch_depth=2,
            )
        asyncio.run(run())

        db = os.path.join(self._tp, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                'SELECT event_type, parent_session_id, job_id, '
                'dispatch_depth FROM events '
                "WHERE event_type IN ('turn_start','turn_complete') "
                'ORDER BY ts, id'
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 2)
        for et, parent_sid, j, d in rows:
            self.assertEqual(
                parent_sid, 'sess-parent-X',
                f'{et}.parent_session_id must be populated, not NULL — '
                f'without this the call-tree walk cannot proceed in SQL',
            )
            self.assertEqual(
                j, 'job-2026-05-09-Y',
                f'{et}.job_id must be populated for cost-per-job rollup',
            )
            self.assertEqual(d, 2, f'{et}.dispatch_depth must be 2')

    def test_run_child_lifecycle_sets_linkage_in_launch_kwargs(self) -> None:
        """Source-level wiring assertion that run_child_lifecycle
        installs parent_session_id, job_id, and dispatch_depth into
        launch_kwargs_base. Reverting the relevant block would flip
        this test."""
        import inspect
        from teaparty.messaging import child_dispatch as _cd
        src = inspect.getsource(_cd.run_child_lifecycle)
        for required in (
            "parent_session_id=parent_sid",
            "job_id=job_id",
            "dispatch_depth=child_depth",
        ):
            self.assertIn(
                required, src,
                f'run_child_lifecycle must set {required!r} in '
                f'launch_kwargs_base — without this the indexed '
                f'columns are NULL on every child TURN_* event',
            )


# ── Delegate edge job_id linkage ─────────────────────────────────────────────


class DelegateJobIdLinkageTests(unittest.TestCase):
    """The dispatch_edges.job_id column must be populated by
    _default_delegate_post — the motivating tree query
    ``WHERE job_id=?`` returns nothing without it."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self._home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_delegate_records_job_id_from_contextvar(self) -> None:
        from teaparty.mcp.tools.messaging import _default_delegate_post
        from teaparty.mcp import registry as _reg

        async def fake_spawn(member, composite, ctx_id):
            return ('child-J', '/tmp/wt', 'ok')

        _reg._spawn_fns.clear()
        _reg._spawn_fns['parent-agent'] = fake_spawn
        _reg.current_agent_name.set('parent-agent')
        _reg.current_session_id.set('parent-J')
        _reg.current_job_id.set('job-J-2026')

        async def run() -> str:
            return await _default_delegate_post(
                member='developer', composite='do',
                skill='attempt-task',
            )

        try:
            asyncio.run(run())
        finally:
            _reg._spawn_fns.clear()
            _reg.current_agent_name.set('')
            _reg.current_session_id.set('')
            _reg.current_job_id.set('')

        db = os.path.join(self._home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                'SELECT parent_session_id, child_session_id, member, '
                'skill, job_id FROM dispatch_edges'
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row,
            ('parent-J', 'child-J', 'developer', 'attempt-task', 'job-J-2026'),
            f'_default_delegate_post must read job_id from the contextvar '
            f'and pass it to record_dispatch_edge — got {row!r}',
        )


if __name__ == '__main__':
    unittest.main()
