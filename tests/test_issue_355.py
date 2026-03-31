"""Tests for Issue #355: MCP messaging tools inject consolidated context at process boundaries.

Acceptance criteria:
1. send_handler posts composite message: ## Task section = agent's message;
   ## Context section = caller's scratch file contents
2. Context is truncated at the budget cap; oldest lines are dropped first
3. reply_handler posts message unchanged — no context injection
4. Escalation tool (ask_question_handler with scratch_path) builds same composite
5. Specification-based tests verify composite structure for send_handler and escalation tool
6. Specification-based tests verify reply_handler does not modify the message
"""
import asyncio
import os
import shutil
import tempfile
import unittest

from pathlib import Path


def _run(coro):
    return asyncio.run(coro)


def _make_tmpdir() -> str:
    return tempfile.mkdtemp()


def _make_scratch_file(tmpdir: str, lines: list[str]) -> str:
    """Write a scratch.md file with the given lines; return its path."""
    context_dir = os.path.join(tmpdir, '.context')
    os.makedirs(context_dir, exist_ok=True)
    path = os.path.join(context_dir, 'scratch.md')
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return path


def _make_captured_post():
    """Return (post_fn, captured) where captured records each call."""
    captured = {}

    async def post_fn(member, composite, context_id=''):
        captured['member'] = member
        captured['composite'] = composite
        captured['context_id'] = context_id
        return 'ok'

    return post_fn, captured


def _make_captured_reply():
    """Return (reply_fn, captured) where captured records each call."""
    captured = {}

    async def reply_fn(message):
        captured['message'] = message
        return 'ok'

    return reply_fn, captured


def _make_captured_proxy():
    """Return (proxy_fn, captured) where captured records each call."""
    captured = {}

    async def proxy_fn(question, context=''):
        captured['question'] = question
        captured['context'] = context
        return {'confident': True, 'answer': 'proxy answer', 'prediction': 'proxy answer'}

    return proxy_fn, captured


# ── AC1: send_handler builds composite Task + Context envelope ────────────────

class TestSendHandlerCompositeStructure(unittest.TestCase):
    """send_handler must build a ## Task / ## Context composite before posting."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_composite_contains_task_section_with_agent_message(self):
        """Composite message must start with ## Task containing the agent's message."""
        from orchestrator.mcp_server import send_handler

        scratch_path = _make_scratch_file(self.tmpdir, ['# State', 'decision: use approach A'])
        post_fn, captured = _make_captured_post()

        _run(send_handler(
            member='coding-specialist',
            message='Implement the login flow',
            scratch_path=scratch_path,
            post_fn=post_fn,
        ))

        composite = captured['composite']
        self.assertIn('## Task\n', composite)
        self.assertIn('Implement the login flow', composite)
        task_section = composite[composite.index('## Task\n'):]
        self.assertTrue(
            task_section.startswith('## Task\nImplement the login flow'),
            f'Task section must open with the agent message, got: {task_section[:80]}',
        )

    def test_composite_contains_context_section_with_scratch_contents(self):
        """Composite message must include ## Context containing scratch file contents."""
        from orchestrator.mcp_server import send_handler

        scratch_path = _make_scratch_file(
            self.tmpdir, ['# Current State', 'Decided to use SQLite for persistence.'],
        )
        post_fn, captured = _make_captured_post()

        _run(send_handler(
            member='coding-specialist',
            message='Write the migration script',
            scratch_path=scratch_path,
            post_fn=post_fn,
        ))

        composite = captured['composite']
        self.assertIn('## Context\n', composite)
        self.assertIn('Decided to use SQLite for persistence.', composite)

    def test_task_section_precedes_context_section(self):
        """## Task must appear before ## Context in the composite."""
        from orchestrator.mcp_server import send_handler

        scratch_path = _make_scratch_file(self.tmpdir, ['scratch contents'])
        post_fn, captured = _make_captured_post()

        _run(send_handler(
            member='qa-reviewer',
            message='Review the migration script',
            scratch_path=scratch_path,
            post_fn=post_fn,
        ))

        composite = captured['composite']
        task_pos = composite.index('## Task')
        context_pos = composite.index('## Context')
        self.assertLess(
            task_pos, context_pos,
            '## Task must appear before ## Context in the composite message',
        )

    def test_post_fn_receives_composite_not_raw_message(self):
        """The post_fn must receive the composite, not the raw agent message."""
        from orchestrator.mcp_server import send_handler

        scratch_path = _make_scratch_file(self.tmpdir, ['state: researching'])
        post_fn, captured = _make_captured_post()

        _run(send_handler(
            member='research-agent',
            message='Find relevant papers',
            scratch_path=scratch_path,
            post_fn=post_fn,
        ))

        composite = captured['composite']
        # Must not be just the raw message
        self.assertNotEqual(composite, 'Find relevant papers')
        # Must have both sections
        self.assertIn('## Task', composite)
        self.assertIn('## Context', composite)

    def test_composite_context_empty_when_scratch_file_missing(self):
        """When the scratch file does not exist, ## Context section is present but empty."""
        from orchestrator.mcp_server import send_handler

        nonexistent = os.path.join(self.tmpdir, '.context', 'scratch.md')
        post_fn, captured = _make_captured_post()

        _run(send_handler(
            member='coding-specialist',
            message='Start the task',
            scratch_path=nonexistent,
            post_fn=post_fn,
        ))

        composite = captured['composite']
        self.assertIn('## Task\n', composite)
        self.assertIn('## Context\n', composite)
        # Context section should be empty (nothing after ## Context)
        context_start = composite.index('## Context\n') + len('## Context\n')
        context_body = composite[context_start:].strip()
        self.assertEqual(context_body, '', f'Context section must be empty, got: {context_body!r}')

    def test_post_fn_receives_member_unchanged(self):
        """The member name must be passed to post_fn unchanged."""
        from orchestrator.mcp_server import send_handler

        scratch_path = _make_scratch_file(self.tmpdir, ['state: planning'])
        post_fn, captured = _make_captured_post()

        _run(send_handler(
            member='doc-writer',
            message='Write the API docs',
            scratch_path=scratch_path,
            post_fn=post_fn,
        ))

        self.assertEqual(captured['member'], 'doc-writer')

    def test_context_id_passed_to_post_fn(self):
        """The context_id must be passed through to post_fn."""
        from orchestrator.mcp_server import send_handler

        scratch_path = _make_scratch_file(self.tmpdir, ['state: in progress'])
        post_fn, captured = _make_captured_post()

        _run(send_handler(
            member='coding-specialist',
            message='Continue the task',
            context_id='ctx-abc123',
            scratch_path=scratch_path,
            post_fn=post_fn,
        ))

        self.assertEqual(captured['context_id'], 'ctx-abc123')


# ── AC2: context truncated at budget cap, oldest lines dropped first ──────────

class TestSendHandlerContextTruncation(unittest.TestCase):
    """Context section must be truncated to CONTEXT_BUDGET_LINES; oldest lines dropped first."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scratch_within_budget_included_in_full(self):
        """When scratch is within budget, all lines appear in Context section."""
        from orchestrator.mcp_server import send_handler, CONTEXT_BUDGET_LINES

        lines = [f'line {i}' for i in range(CONTEXT_BUDGET_LINES - 10)]
        scratch_path = _make_scratch_file(self.tmpdir, lines)
        post_fn, captured = _make_captured_post()

        _run(send_handler(
            member='specialist',
            message='do something',
            scratch_path=scratch_path,
            post_fn=post_fn,
        ))

        composite = captured['composite']
        for line in lines[:5]:
            self.assertIn(line, composite, f'{line!r} must be present when within budget')

    def test_scratch_over_budget_drops_oldest_lines(self):
        """When scratch exceeds budget, oldest (first) lines are dropped."""
        from orchestrator.mcp_server import send_handler, CONTEXT_BUDGET_LINES

        # Write budget + 10 lines; first 10 should be dropped
        lines = [f'line {i}' for i in range(CONTEXT_BUDGET_LINES + 10)]
        scratch_path = _make_scratch_file(self.tmpdir, lines)
        post_fn, captured = _make_captured_post()

        _run(send_handler(
            member='specialist',
            message='do something',
            scratch_path=scratch_path,
            post_fn=post_fn,
        ))

        composite = captured['composite']
        # Oldest lines should be gone
        for i in range(10):
            self.assertNotIn(f'line {i}\n', composite,
                             f'line {i} is oldest and must be dropped when over budget')
        # Newest lines should be present
        for i in range(CONTEXT_BUDGET_LINES + 10 - 5, CONTEXT_BUDGET_LINES + 10):
            self.assertIn(f'line {i}', composite,
                          f'line {i} is newest and must be present after truncation')

    def test_context_budget_lines_constant_is_200(self):
        """CONTEXT_BUDGET_LINES must be 200 per the design spec."""
        from orchestrator.mcp_server import CONTEXT_BUDGET_LINES
        self.assertEqual(CONTEXT_BUDGET_LINES, 200)


# ── AC3: reply_handler posts message unchanged ─────────────────────────────────

class TestReplyHandlerNoContextInjection(unittest.TestCase):
    """reply_handler must post the message unchanged — no Task/Context envelope."""

    def test_reply_posts_message_unchanged(self):
        """The reply_fn must receive the exact message the caller passed."""
        from orchestrator.mcp_server import reply_handler

        reply_fn, captured = _make_captured_reply()

        _run(reply_handler(
            message='Task complete. Results are in /output/report.md.',
            post_fn=reply_fn,
        ))

        self.assertEqual(
            captured['message'],
            'Task complete. Results are in /output/report.md.',
        )

    def test_reply_does_not_prepend_task_section(self):
        """reply_handler must not add ## Task to the message."""
        from orchestrator.mcp_server import reply_handler

        reply_fn, captured = _make_captured_reply()

        _run(reply_handler(message='Done.', post_fn=reply_fn))

        self.assertNotIn('## Task', captured['message'])

    def test_reply_does_not_inject_context_section(self):
        """reply_handler must not add ## Context to the message."""
        from orchestrator.mcp_server import reply_handler

        reply_fn, captured = _make_captured_reply()

        _run(reply_handler(message='Done.', post_fn=reply_fn))

        self.assertNotIn('## Context', captured['message'])

    def test_reply_requires_nonempty_message(self):
        """reply_handler must raise ValueError for empty message."""
        from orchestrator.mcp_server import reply_handler

        with self.assertRaises(ValueError):
            _run(reply_handler(message=''))


# ── AC4: ask_question_handler with scratch_path builds same composite ──────────

class TestEscalationToolCompositeConstruction(unittest.TestCase):
    """ask_question_handler with scratch_path must build ## Task / ## Context composite."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_escalation_proxy_receives_composite_with_task_section(self):
        """When scratch_path is given, proxy receives composite with ## Task section."""
        from orchestrator.mcp_server import ask_question_handler

        scratch_path = _make_scratch_file(self.tmpdir, ['# State', 'working on auth flow'])
        proxy_fn, captured = _make_captured_proxy()

        _run(ask_question_handler(
            question='Should I use JWT or session cookies?',
            scratch_path=scratch_path,
            proxy_fn=proxy_fn,
        ))

        question_sent = captured['question']
        self.assertIn('## Task\n', question_sent)
        self.assertIn('Should I use JWT or session cookies?', question_sent)

    def test_escalation_proxy_receives_context_section_with_scratch_contents(self):
        """When scratch_path is given, proxy receives ## Context with scratch contents."""
        from orchestrator.mcp_server import ask_question_handler

        scratch_path = _make_scratch_file(
            self.tmpdir, ['# State', 'Auth module in progress. Using FastAPI.'],
        )
        proxy_fn, captured = _make_captured_proxy()

        _run(ask_question_handler(
            question='Should I add rate limiting now or later?',
            scratch_path=scratch_path,
            proxy_fn=proxy_fn,
        ))

        question_sent = captured['question']
        self.assertIn('## Context\n', question_sent)
        self.assertIn('Auth module in progress. Using FastAPI.', question_sent)

    def test_escalation_task_precedes_context(self):
        """In the escalation composite, ## Task must precede ## Context."""
        from orchestrator.mcp_server import ask_question_handler

        scratch_path = _make_scratch_file(self.tmpdir, ['state: planning'])
        proxy_fn, captured = _make_captured_proxy()

        _run(ask_question_handler(
            question='Which approach should I take?',
            scratch_path=scratch_path,
            proxy_fn=proxy_fn,
        ))

        question_sent = captured['question']
        task_pos = question_sent.index('## Task')
        context_pos = question_sent.index('## Context')
        self.assertLess(task_pos, context_pos)

    def test_escalation_without_scratch_path_preserves_existing_behavior(self):
        """ask_question_handler without scratch_path must behave as before (no composite)."""
        from orchestrator.mcp_server import ask_question_handler

        proxy_fn, captured = _make_captured_proxy()

        _run(ask_question_handler(
            question='Simple question?',
            proxy_fn=proxy_fn,
        ))

        # No scratch_path → no composite wrapping; question passed as-is
        question_sent = captured['question']
        self.assertEqual(question_sent, 'Simple question?')

    def test_escalation_same_composite_structure_as_send_handler(self):
        """Escalation composite uses the same Task/Context structure as send_handler."""
        from orchestrator.mcp_server import ask_question_handler, send_handler

        lines = ['# State', 'decision: approach A is better']
        scratch_path = _make_scratch_file(self.tmpdir, lines)

        proxy_fn, esc_captured = _make_captured_proxy()
        post_fn, send_captured = _make_captured_post()

        _run(ask_question_handler(
            question='Which db should I use?',
            scratch_path=scratch_path,
            proxy_fn=proxy_fn,
        ))
        _run(send_handler(
            member='coding-specialist',
            message='Which db should I use?',
            scratch_path=scratch_path,
            post_fn=post_fn,
        ))

        esc_composite = esc_captured['question']
        send_composite = send_captured['composite']

        # Both must have Task and Context sections
        for composite, label in [(esc_composite, 'escalation'), (send_composite, 'send')]:
            self.assertIn('## Task\n', composite, f'{label} must have ## Task')
            self.assertIn('## Context\n', composite, f'{label} must have ## Context')
            self.assertIn('decision: approach A is better', composite,
                          f'{label} must have scratch contents in Context')


# ── AC5/6: send_handler and reply_handler importable and testable ─────────────

class TestHandlersExistAndAreCallable(unittest.TestCase):
    """send_handler and reply_handler must exist in orchestrator.mcp_server."""

    def test_send_handler_exists(self):
        from orchestrator.mcp_server import send_handler
        self.assertTrue(callable(send_handler))

    def test_reply_handler_exists(self):
        from orchestrator.mcp_server import reply_handler
        self.assertTrue(callable(reply_handler))

    def test_send_handler_is_async(self):
        import asyncio
        from orchestrator.mcp_server import send_handler

        async def noop(*a):
            return 'ok'

        coro = send_handler(
            member='m',
            message='msg',
            scratch_path='/nonexistent',
            post_fn=noop,
        )
        self.assertTrue(asyncio.iscoroutine(coro))
        coro.close()

    def test_reply_handler_is_async(self):
        import asyncio
        from orchestrator.mcp_server import reply_handler

        async def noop(m):
            return 'ok'

        coro = reply_handler(message='done', post_fn=noop)
        self.assertTrue(asyncio.iscoroutine(coro))
        coro.close()

    def test_context_budget_lines_constant_exported(self):
        from orchestrator.mcp_server import CONTEXT_BUDGET_LINES
        self.assertIsInstance(CONTEXT_BUDGET_LINES, int)
        self.assertGreater(CONTEXT_BUDGET_LINES, 0)

    def test_send_and_reply_tools_registered_in_server(self):
        """Send and Reply tools must be registered in create_server()."""
        import asyncio
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')
        from orchestrator.mcp_server import create_server
        server = create_server()
        tool_names = [t.name for t in asyncio.run(server.list_tools())]
        self.assertIn('Send', tool_names, 'Send tool must be registered in create_server()')
        self.assertIn('Reply', tool_names, 'Reply tool must be registered in create_server()')

    def test_send_handler_requires_nonempty_member(self):
        """send_handler must raise ValueError for empty member."""
        from orchestrator.mcp_server import send_handler
        with self.assertRaises(ValueError):
            _run(send_handler(member='', message='hello', post_fn=_make_captured_post()[0]))

    def test_send_handler_requires_nonempty_message(self):
        """send_handler must raise ValueError for empty message."""
        from orchestrator.mcp_server import send_handler
        with self.assertRaises(ValueError):
            _run(send_handler(member='specialist', message='', post_fn=_make_captured_post()[0]))


# ── Flush-before-send: flush_fn called before scratch file is read ────────────

class TestSendHandlerFlushBeforeRead(unittest.TestCase):
    """send_handler must call flush_fn before reading the scratch file."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_flush_fn_is_called_before_scratch_is_read(self):
        """flush_fn must be called before send_handler reads the scratch file.

        State written by flush_fn must appear in the composite — not stale
        pre-existing content.  This is the freshness invariant: the composite
        reflects the full current turn, not the last compaction boundary.
        """
        from orchestrator.mcp_server import send_handler

        stale_path = os.path.join(self.tmpdir, '.context', 'scratch.md')
        os.makedirs(os.path.dirname(stale_path), exist_ok=True)
        with open(stale_path, 'w') as f:
            f.write('stale content\n')

        fresh_content = 'fresh content written by flush\n'

        async def flush_fn(path):
            with open(path, 'w') as f:
                f.write(fresh_content)

        post_fn, captured = _make_captured_post()

        _run(send_handler(
            member='specialist',
            message='do something',
            scratch_path=stale_path,
            flush_fn=flush_fn,
            post_fn=post_fn,
        ))

        composite = captured['composite']
        self.assertIn('fresh content written by flush', composite,
                      'Composite must contain content written by flush_fn, not stale pre-existing content')
        self.assertNotIn('stale content', composite,
                         'Composite must not contain stale content that predates the flush')

    def test_flush_fn_called_for_escalation_path(self):
        """ask_question_handler must also call flush_fn before reading the scratch file."""
        from orchestrator.mcp_server import ask_question_handler

        stale_path = os.path.join(self.tmpdir, '.context', 'scratch.md')
        os.makedirs(os.path.dirname(stale_path), exist_ok=True)
        with open(stale_path, 'w') as f:
            f.write('stale escalation context\n')

        fresh_content = 'fresh escalation context written by flush\n'

        async def flush_fn(path):
            with open(path, 'w') as f:
                f.write(fresh_content)

        proxy_fn, captured = _make_captured_proxy()

        _run(ask_question_handler(
            question='Which approach?',
            scratch_path=stale_path,
            flush_fn=flush_fn,
            proxy_fn=proxy_fn,
        ))

        question_sent = captured['question']
        self.assertIn('fresh escalation context written by flush', question_sent,
                      'Escalation composite must contain content written by flush_fn')
        self.assertNotIn('stale escalation context', question_sent,
                         'Escalation composite must not contain stale content')

    def test_flush_fn_receives_the_scratch_path(self):
        """flush_fn must be called with the resolved scratch path."""
        from orchestrator.mcp_server import send_handler

        scratch_path = _make_scratch_file(self.tmpdir, ['some content'])
        received_paths = []

        async def flush_fn(path):
            received_paths.append(path)

        post_fn, _ = _make_captured_post()

        _run(send_handler(
            member='specialist',
            message='do task',
            scratch_path=scratch_path,
            flush_fn=flush_fn,
            post_fn=post_fn,
        ))

        self.assertEqual(received_paths, [scratch_path],
                         'flush_fn must be called exactly once with the resolved scratch path')

    def test_send_handler_accepts_flush_fn_parameter(self):
        """send_handler must accept a flush_fn parameter."""
        from orchestrator.mcp_server import send_handler
        import inspect
        sig = inspect.signature(send_handler)
        self.assertIn('flush_fn', sig.parameters,
                      'send_handler must have a flush_fn keyword parameter')

    def test_ask_question_handler_accepts_flush_fn_parameter(self):
        """ask_question_handler must accept a flush_fn parameter."""
        from orchestrator.mcp_server import ask_question_handler
        import inspect
        sig = inspect.signature(ask_question_handler)
        self.assertIn('flush_fn', sig.parameters,
                      'ask_question_handler must have a flush_fn keyword parameter')


# ── SC3: Recipient agent's spawned conversation history contains the composite ──


class TestConversationHistoryInjection(unittest.TestCase):
    """SC3: inject_composite_into_history writes composite to JSONL session file.

    The composite assembled by send_handler must end up in the recipient's
    conversation history so --resume sees it as an incoming user message.
    inject_composite_into_history is the function that does this write.
    """

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _session_file(self, name: str = 'sess') -> str:
        return os.path.join(self.tmpdir, f'{name}.jsonl')

    def test_injected_entry_is_user_type_with_composite_content(self):
        """type=user and message.content equals the composite passed in."""
        from orchestrator.messaging import inject_composite_into_history
        import json

        session_file = self._session_file()
        composite = '## Task\ndo the thing\n\n## Context\njob state'
        inject_composite_into_history(session_file, composite, 'sess-1', '/work')

        with open(session_file) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['type'], 'user')
        self.assertEqual(entry['message']['role'], 'user')
        self.assertEqual(entry['message']['content'], composite)

    def test_injected_entry_structure_matches_jsonl_schema(self):
        """Entry has isSidechain=True, userType=external, sessionId, cwd, uuid, timestamp."""
        from orchestrator.messaging import inject_composite_into_history
        import json

        session_file = self._session_file()
        inject_composite_into_history(session_file, 'composite', 'sess-2', '/cwd')

        with open(session_file) as f:
            entry = json.loads(f.readline())
        self.assertTrue(entry['isSidechain'])
        self.assertEqual(entry['userType'], 'external')
        self.assertEqual(entry['sessionId'], 'sess-2')
        self.assertEqual(entry['cwd'], '/cwd')
        self.assertIn('uuid', entry)
        self.assertIn('timestamp', entry)

    def test_parent_uuid_is_none_for_empty_session_file(self):
        """parentUuid is null when the session file has no prior entries."""
        from orchestrator.messaging import inject_composite_into_history
        import json

        session_file = self._session_file()
        inject_composite_into_history(session_file, 'composite', 'sess-3', '/work')

        with open(session_file) as f:
            entry = json.loads(f.readline())
        self.assertIsNone(entry['parentUuid'])

    def test_parent_uuid_chains_to_prior_entry(self):
        """Second injection's parentUuid equals the first entry's uuid."""
        from orchestrator.messaging import inject_composite_into_history
        import json

        session_file = self._session_file()
        inject_composite_into_history(session_file, 'first', 'sess-4', '/work')
        inject_composite_into_history(session_file, 'second', 'sess-4', '/work')

        with open(session_file) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(entries), 2)
        self.assertIsNone(entries[0]['parentUuid'])
        self.assertEqual(entries[1]['parentUuid'], entries[0]['uuid'])

    def test_injected_composite_is_exactly_what_send_handler_produced(self):
        """The composite in the session file matches send_handler's output verbatim."""
        from orchestrator.messaging import inject_composite_into_history
        from orchestrator.mcp_server import send_handler
        import json

        scratch_path = _make_scratch_file(self.tmpdir, ['job: my-task', 'state: active'])
        post_fn, captured = _make_captured_post()

        _run(send_handler(
            'worker', 'do the thing', '',
            scratch_path=scratch_path,
            post_fn=post_fn,
        ))
        composite = captured['composite']

        session_file = self._session_file()
        inject_composite_into_history(session_file, composite, 'sess-5', '/work')

        with open(session_file) as f:
            entry = json.loads(f.readline())
        self.assertEqual(entry['message']['content'], composite)
        self.assertIn('## Task', entry['message']['content'])
        self.assertIn('## Context', entry['message']['content'])


if __name__ == '__main__':
    unittest.main()
