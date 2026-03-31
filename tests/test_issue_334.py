"""Tests for Issue #334: Message bus — all stream event types must be written with typed senders.

Acceptance criteria:
1. Every thinking block is written to the bus as sender='thinking'
2. Every tool_use block is written as sender='tool_use'; content encodes tool name and input
3. Every tool_result event is written as sender='tool_result'
4. System events are written as sender='system'
5. Agent text response is unchanged — written with the agent's role sender
6. Message ordering in the bus preserves stream ordering within a turn
7. Stream filter toggles (thinking, tools, results, system) match the corresponding senders
8. Stream file is still deleted after all events are written
9. No events are silently dropped — unknown block types are written to the bus
10. Specification-based tests cover: correct sender per event type, correct event count,
    correct ordering, filter predicate routing for each sender
11. Tests are in tests/ using unittest.TestCase with _make_*() helpers
"""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tmpdir() -> str:
    return tempfile.mkdtemp()


def _make_om_session(tmpdir: str, user_id: str = 'darrell'):
    from orchestrator.messaging import SqliteMessageBus
    from orchestrator.office_manager import OfficeManagerSession, om_bus_path
    path = om_bus_path(tmpdir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return OfficeManagerSession(tmpdir, user_id)


def _write_stream_jsonl(path: str, events: list) -> None:
    """Write a stream JSONL file with the given event dicts."""
    with open(path, 'w') as f:
        for ev in events:
            f.write(json.dumps(ev) + '\n')


def _make_stream_path(events: list) -> str:
    """Create a temp stream JSONL file and return its path."""
    fd, path = tempfile.mkstemp(suffix='.jsonl', prefix='om-test-334-')
    os.close(fd)
    _write_stream_jsonl(path, events)
    return path


def _make_assistant_event(*blocks: dict) -> dict:
    """Build an assistant stream event with the given content blocks."""
    return {
        'type': 'assistant',
        'message': {'content': list(blocks)},
    }


def _make_thinking_block(text: str) -> dict:
    return {'type': 'thinking', 'thinking': text}


def _make_text_block(text: str) -> dict:
    return {'type': 'text', 'text': text}


def _make_tool_use_block(name: str, input_dict: dict, tool_id: str = 'tu_1') -> dict:
    return {'type': 'tool_use', 'id': tool_id, 'name': name, 'input': input_dict}


def _make_tool_result_event(tool_use_id: str, content) -> dict:
    return {'type': 'tool_result', 'tool_use_id': tool_use_id, 'content': content}


def _make_system_event(session_id: str = 'sid-test', **kwargs) -> dict:
    ev = {'type': 'system', 'session_id': session_id}
    ev.update(kwargs)
    return ev


# ── AC1: thinking block → sender='thinking' ───────────────────────────────────

class TestThinkingBlockSender(unittest.TestCase):
    """_iter_stream_events must yield sender='thinking' for thinking content blocks."""

    def test_thinking_block_yields_thinking_sender(self):
        """A thinking block in an assistant event must produce sender='thinking'."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(_make_thinking_block('I should analyze this carefully.')),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        senders = [s for s, _ in events]
        self.assertIn(
            'thinking', senders,
            '_iter_stream_events must yield sender="thinking" for thinking blocks; '
            f'got senders: {senders}',
        )

    def test_thinking_block_content_is_the_thinking_text(self):
        """The content for a thinking event must be the thinking text, not wrapped JSON."""
        from orchestrator.office_manager import _iter_stream_events

        thinking_text = 'Let me reason step by step about this.'
        path = _make_stream_path([
            _make_assistant_event(_make_thinking_block(thinking_text)),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        thinking_events = [(s, c) for s, c in events if s == 'thinking']
        self.assertTrue(len(thinking_events) > 0, 'Must have at least one thinking event')
        _, content = thinking_events[0]
        self.assertEqual(
            content, thinking_text,
            f'Thinking event content must be the raw thinking text; got: {content!r}',
        )

    def test_multiple_thinking_blocks_each_yield_thinking_sender(self):
        """Multiple thinking blocks in one turn must each yield a separate thinking event."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(
                _make_thinking_block('First thought.'),
                _make_thinking_block('Second thought.'),
            ),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        thinking_events = [(s, c) for s, c in events if s == 'thinking']
        self.assertEqual(
            len(thinking_events), 2,
            f'Two thinking blocks must yield two thinking events; got {len(thinking_events)}',
        )


# ── AC2: tool_use block → sender='tool_use', content encodes name+input ──────

class TestToolUseBlockSender(unittest.TestCase):
    """_iter_stream_events must yield sender='tool_use' for tool_use content blocks."""

    def test_tool_use_block_yields_tool_use_sender(self):
        """A tool_use block must produce sender='tool_use'."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(
                _make_tool_use_block('Read', {'file_path': '/tmp/foo.txt'})
            ),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        senders = [s for s, _ in events]
        self.assertIn(
            'tool_use', senders,
            f'_iter_stream_events must yield sender="tool_use" for tool_use blocks; got: {senders}',
        )

    def test_tool_use_content_encodes_tool_name(self):
        """The tool_use event content must include the tool name."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(
                _make_tool_use_block('Bash', {'command': 'ls -la'})
            ),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        tool_events = [(s, c) for s, c in events if s == 'tool_use']
        self.assertTrue(len(tool_events) > 0, 'Must have a tool_use event')
        _, content = tool_events[0]
        parsed = json.loads(content)
        self.assertEqual(
            parsed.get('name'), 'Bash',
            f'tool_use content must include the tool name; got: {parsed}',
        )

    def test_tool_use_content_encodes_tool_input(self):
        """The tool_use event content must include the tool input."""
        from orchestrator.office_manager import _iter_stream_events

        tool_input = {'command': 'git status', 'timeout': 30}
        path = _make_stream_path([
            _make_assistant_event(
                _make_tool_use_block('Bash', tool_input)
            ),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        tool_events = [(s, c) for s, c in events if s == 'tool_use']
        self.assertTrue(len(tool_events) > 0, 'Must have a tool_use event')
        _, content = tool_events[0]
        parsed = json.loads(content)
        self.assertEqual(
            parsed.get('input'), tool_input,
            f'tool_use content must include the tool input; got: {parsed}',
        )


# ── AC3: tool_result event → sender='tool_result' ────────────────────────────

class TestToolResultEventSender(unittest.TestCase):
    """_iter_stream_events must yield sender='tool_result' for tool_result events."""

    def test_tool_result_event_yields_tool_result_sender(self):
        """A tool_result top-level event must produce sender='tool_result'."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_tool_result_event('tu_1', 'file contents here'),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        senders = [s for s, _ in events]
        self.assertIn(
            'tool_result', senders,
            f'_iter_stream_events must yield sender="tool_result" for tool_result events; got: {senders}',
        )

    def test_tool_result_string_content_preserved(self):
        """String tool_result content must be preserved as-is in the bus message."""
        from orchestrator.office_manager import _iter_stream_events

        result_text = 'total 42\ndrwxr-xr-x  8 user  staff   256 Mar 30 10:00 .'
        path = _make_stream_path([
            _make_tool_result_event('tu_1', result_text),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        result_events = [(s, c) for s, c in events if s == 'tool_result']
        self.assertTrue(len(result_events) > 0, 'Must have a tool_result event')
        _, content = result_events[0]
        self.assertEqual(
            content, result_text,
            f'String tool_result content must be preserved; got: {content!r}',
        )


# ── AC4: system event → sender='system' ──────────────────────────────────────

class TestSystemEventSender(unittest.TestCase):
    """_iter_stream_events must yield sender='system' for system events."""

    def test_system_event_yields_system_sender(self):
        """A system event must produce sender='system'."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_system_event('sid-001'),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        senders = [s for s, _ in events]
        self.assertIn(
            'system', senders,
            f'_iter_stream_events must yield sender="system" for system events; got: {senders}',
        )

    def test_system_event_content_is_json_serialized(self):
        """System event content must be JSON-serializable (not a Python repr)."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_system_event('sid-001', subtype='init'),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        system_events = [(s, c) for s, c in events if s == 'system']
        self.assertTrue(len(system_events) > 0, 'Must have a system event')
        _, content = system_events[0]
        try:
            parsed = json.loads(content)
        except (ValueError, json.JSONDecodeError):
            self.fail(f'System event content must be valid JSON; got: {content!r}')
        self.assertEqual(
            parsed.get('type'), 'system',
            f'System event content must include the event type; got: {parsed}',
        )


# ── AC5: text block → agent role sender, unchanged ───────────────────────────

class TestTextBlockSender(unittest.TestCase):
    """Text blocks must yield the agent_role sender, unchanged from previous behavior."""

    def test_text_block_yields_agent_role_sender(self):
        """A text block must produce sender=agent_role ('office-manager')."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(_make_text_block('Here is my response.')),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        senders = [s for s, _ in events]
        self.assertIn(
            'office-manager', senders,
            f'Text block must yield the agent_role sender; got: {senders}',
        )

    def test_text_block_content_is_the_text(self):
        """The content for a text event must be the text string."""
        from orchestrator.office_manager import _iter_stream_events

        response_text = 'I have analyzed your request and here is my finding.'
        path = _make_stream_path([
            _make_assistant_event(_make_text_block(response_text)),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        text_events = [(s, c) for s, c in events if s == 'office-manager']
        self.assertTrue(len(text_events) > 0, 'Must have a text event with agent role sender')
        _, content = text_events[0]
        self.assertEqual(
            content, response_text,
            f'Text event content must be the text; got: {content!r}',
        )

    def test_custom_agent_role_is_used_as_text_sender(self):
        """_iter_stream_events must use the provided agent_role, not a hardcoded string."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(_make_text_block('Custom agent response.')),
        ])
        try:
            events = list(_iter_stream_events(path, 'proxy-review'))
        finally:
            os.unlink(path)

        senders = [s for s, _ in events]
        self.assertIn(
            'proxy-review', senders,
            f'Text block sender must use the provided agent_role; got: {senders}',
        )
        self.assertNotIn(
            'office-manager', senders,
            'Text block sender must not be hardcoded to "office-manager"',
        )


# ── AC6: Message ordering preserves stream ordering ──────────────────────────

class TestMessageOrdering(unittest.TestCase):
    """Events yielded by _iter_stream_events must preserve stream order within a turn."""

    def test_thinking_then_text_preserves_order(self):
        """thinking block before text block must yield thinking event before text event."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(
                _make_thinking_block('Let me think.'),
                _make_text_block('Here is the answer.'),
            ),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        senders = [s for s, _ in events]
        thinking_idx = next((i for i, s in enumerate(senders) if s == 'thinking'), -1)
        text_idx = next((i for i, s in enumerate(senders) if s == 'office-manager'), -1)
        self.assertGreater(
            thinking_idx, -1, 'Must have a thinking event',
        )
        self.assertGreater(
            text_idx, -1, 'Must have a text event',
        )
        self.assertLess(
            thinking_idx, text_idx,
            f'thinking event (pos {thinking_idx}) must come before text event (pos {text_idx})',
        )

    def test_tool_use_then_tool_result_preserves_order(self):
        """tool_use block before tool_result event must yield tool_use before tool_result."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(
                _make_tool_use_block('Read', {'file_path': '/foo.txt'}),
            ),
            _make_tool_result_event('tu_1', 'file content'),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        senders = [s for s, _ in events]
        tool_use_idx = next((i for i, s in enumerate(senders) if s == 'tool_use'), -1)
        tool_result_idx = next((i for i, s in enumerate(senders) if s == 'tool_result'), -1)
        self.assertGreater(tool_use_idx, -1, 'Must have a tool_use event')
        self.assertGreater(tool_result_idx, -1, 'Must have a tool_result event')
        self.assertLess(
            tool_use_idx, tool_result_idx,
            f'tool_use (pos {tool_use_idx}) must come before tool_result (pos {tool_result_idx})',
        )

    def test_full_turn_order_system_thinking_tool_use_tool_result_text(self):
        """A full realistic turn must preserve stream event ordering end-to-end."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_system_event('sid-1'),
            _make_assistant_event(
                _make_thinking_block('I need to read the file first.'),
                _make_tool_use_block('Read', {'file_path': '/foo.txt'}),
            ),
            _make_tool_result_event('tu_1', 'file content here'),
            _make_assistant_event(
                _make_text_block('Based on the file, here is my answer.'),
            ),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        senders = [s for s, _ in events]
        expected_order = ['system', 'thinking', 'tool_use', 'tool_result', 'office-manager']
        for i in range(len(expected_order) - 1):
            a, b = expected_order[i], expected_order[i + 1]
            idx_a = next((j for j, s in enumerate(senders) if s == a), -1)
            idx_b = next((j for j, s in enumerate(senders) if s == b), -1)
            self.assertGreater(idx_a, -1, f'Expected event with sender={a!r} in stream')
            self.assertGreater(idx_b, -1, f'Expected event with sender={b!r} in stream')
            self.assertLess(
                idx_a, idx_b,
                f'"{a}" (pos {idx_a}) must come before "{b}" (pos {idx_b}); '
                f'full order: {senders}',
            )


# ── AC7: Filter predicate routing ────────────────────────────────────────────

class TestFilterPredicateRouting(unittest.TestCase):
    """Senders produced by _iter_stream_events must match chat.html filter predicates.

    chat.html predicates (updated for typed senders):
      'agent':    s !== 'human' && s !== 'system' && s !== 'thinking' && s.indexOf('tool') < 0
      'thinking': s === 'thinking' || s.indexOf('thinking') >= 0
      'tools':    s === 'tool_use' || (s.indexOf('tool') >= 0 && s !== 'tool_result')
      'results':  s === 'tool_result'
      'system':   s === 'system'
    """

    def _thinking_predicate(self, sender: str) -> bool:
        return sender == 'thinking' or 'thinking' in sender

    def _tools_predicate(self, sender: str) -> bool:
        return sender == 'tool_use' or ('tool' in sender and sender != 'tool_result')

    def _results_predicate(self, sender: str) -> bool:
        return sender == 'tool_result'

    def _system_predicate(self, sender: str) -> bool:
        return sender == 'system'

    def _agent_predicate(self, sender: str) -> bool:
        return (sender != 'human' and sender != 'system'
                and sender != 'thinking' and 'tool' not in sender)

    def test_thinking_sender_matches_thinking_filter(self):
        """sender='thinking' must match the thinking filter predicate."""
        self.assertTrue(
            self._thinking_predicate('thinking'),
            'sender="thinking" must match the thinking filter',
        )

    def test_tool_use_sender_matches_tools_filter(self):
        """sender='tool_use' must match the tools filter predicate."""
        self.assertTrue(
            self._tools_predicate('tool_use'),
            'sender="tool_use" must match the tools filter',
        )

    def test_tool_result_sender_matches_results_filter(self):
        """sender='tool_result' must match the results filter predicate (not tools)."""
        self.assertTrue(
            self._results_predicate('tool_result'),
            'sender="tool_result" must match the results filter',
        )
        self.assertFalse(
            self._tools_predicate('tool_result'),
            'sender="tool_result" must NOT match the tools filter (tools and results are separate)',
        )

    def test_system_sender_matches_system_filter(self):
        """sender='system' must match the system filter predicate."""
        self.assertTrue(
            self._system_predicate('system'),
            'sender="system" must match the system filter',
        )

    def test_office_manager_sender_matches_agent_filter(self):
        """sender='office-manager' must match the agent filter and not tool/thinking filters."""
        self.assertTrue(
            self._agent_predicate('office-manager'),
            'sender="office-manager" must match the agent filter',
        )
        self.assertFalse(
            self._thinking_predicate('office-manager'),
            'sender="office-manager" must not match the thinking filter',
        )
        self.assertFalse(
            self._tools_predicate('office-manager'),
            'sender="office-manager" must not match the tools filter',
        )
        self.assertFalse(
            self._results_predicate('office-manager'),
            'sender="office-manager" must not match the results filter',
        )
        self.assertFalse(
            self._system_predicate('office-manager'),
            'sender="office-manager" must not match the system filter',
        )

    def test_agent_filter_does_not_match_thinking_sender(self):
        """sender='thinking' must NOT match the agent filter — thinking is only visible when explicitly enabled."""
        self.assertFalse(
            self._agent_predicate('thinking'),
            'sender="thinking" must not match the agent filter; '
            'thinking is hidden by default and should only appear when the thinking toggle is ON',
        )

    def test_agent_filter_does_not_match_tool_use_sender(self):
        """sender='tool_use' must NOT match the agent filter — tools are only visible when explicitly enabled."""
        self.assertFalse(
            self._agent_predicate('tool_use'),
            'sender="tool_use" must not match the agent filter; '
            'tool activity is hidden by default per chat-windows.md spec',
        )

    def test_agent_filter_does_not_match_tool_result_sender(self):
        """sender='tool_result' must NOT match the agent filter — results are only visible when explicitly enabled."""
        self.assertFalse(
            self._agent_predicate('tool_result'),
            'sender="tool_result" must not match the agent filter; '
            'tool results are hidden by default per chat-windows.md spec',
        )

    def test_iter_stream_events_thinking_sender_routes_to_thinking_filter(self):
        """The thinking sender from _iter_stream_events must match chat.html thinking predicate."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(_make_thinking_block('some thought')),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        thinking_events = [(s, c) for s, c in events if self._thinking_predicate(s)]
        self.assertTrue(
            len(thinking_events) > 0,
            'At least one event from a thinking block must match the thinking filter predicate',
        )

    def test_iter_stream_events_tool_use_sender_routes_to_tools_filter(self):
        """The tool_use sender from _iter_stream_events must match chat.html tools predicate."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(_make_tool_use_block('Glob', {'pattern': '*.py'})),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        tool_events = [(s, c) for s, c in events if self._tools_predicate(s)]
        self.assertTrue(
            len(tool_events) > 0,
            'At least one event from a tool_use block must match the tools filter predicate',
        )

    def test_iter_stream_events_tool_result_sender_routes_to_results_filter(self):
        """The tool_result sender must match the chat.html results filter predicate (not tools)."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_tool_result_event('tu_1', 'result here'),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        result_events = [(s, c) for s, c in events if self._results_predicate(s)]
        self.assertTrue(
            len(result_events) > 0,
            'At least one event from a tool_result event must match the results filter predicate',
        )
        # tool_result must NOT appear in the tools filter (they are separate)
        tool_events = [(s, c) for s, c in events if self._tools_predicate(s)]
        self.assertEqual(
            len(tool_events), 0,
            'tool_result sender must not match the tools filter; '
            'tools and results are separate filters per chat-windows.md',
        )


# ── AC8: Stream file still deleted after all events written ───────────────────

class TestStreamFileCleanup(unittest.TestCase):
    """Stream file must still be deleted in invoke()'s finally block after all events are written."""

    def test_stream_file_deleted_after_invoke_completes(self):
        """After invoke() returns, the temp stream file must no longer exist."""
        from orchestrator.office_manager import OfficeManagerSession

        tmpdir = _make_tmpdir()
        try:
            session = _make_om_session(tmpdir)
            session.send_human_message('Hello.')

            stream_path = _make_stream_path([
                _make_system_event('sid-del-test'),
                _make_assistant_event(
                    _make_thinking_block('thinking'),
                    _make_text_block('hello back'),
                ),
            ])
            # Confirm the file exists before invoke
            self.assertTrue(os.path.exists(stream_path), 'Stream file must exist before invoke')

            mock_result = MagicMock()
            mock_result.session_id = 'sid-del-test'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        asyncio.run(session.invoke(cwd=tmpdir))

            self.assertFalse(
                os.path.exists(stream_path),
                'Stream file must be deleted after invoke() completes (cleanup in finally block)',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            if os.path.exists(stream_path):
                os.unlink(stream_path)


# ── AC9: Unknown block types are not silently dropped ─────────────────────────

class TestUnknownBlockTypeNotDropped(unittest.TestCase):
    """Unknown block types must be written to the bus, not silently discarded."""

    def test_unknown_block_type_yields_at_least_one_event(self):
        """An assistant event with an unrecognized block type must still produce an event."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(
                {'type': 'redacted', 'data': 'some future block type'},
            ),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        self.assertTrue(
            len(events) > 0,
            'Unknown block type must not be silently dropped — at least one event must be yielded',
        )

    def test_unknown_block_type_sender_is_not_empty(self):
        """The sender for an unknown block type event must be a non-empty string."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_assistant_event(
                {'type': 'future_block', 'content': 'something new'},
            ),
        ])
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        self.assertTrue(len(events) > 0, 'Must have at least one event for unknown block')
        for sender, _ in events:
            self.assertIsInstance(sender, str, 'Sender must be a string')
            self.assertGreater(len(sender), 0, 'Sender must not be empty')


# ── AC10 (integration): invoke() writes all event types to the bus ────────────

class TestInvokeWritesAllEventTypesToBus(unittest.TestCase):
    """invoke() must write every event type to the message bus, not just agent text."""

    def _run_invoke_with_stream(self, tmpdir: str, stream_events: list) -> list:
        """Run invoke() with a synthetic stream and return all bus messages."""
        from orchestrator.office_manager import OfficeManagerSession

        session = OfficeManagerSession(tmpdir, 'darrell')
        session.send_human_message('Please help.')

        stream_path = _make_stream_path(stream_events)
        mock_result = MagicMock()
        mock_result.session_id = 'sid-invoke-test'

        try:
            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(session.invoke(cwd=tmpdir))

            return session.get_messages()
        finally:
            if os.path.exists(stream_path):
                os.unlink(stream_path)

    def test_invoke_writes_thinking_event_to_bus(self):
        """invoke() must write thinking blocks to the bus as sender='thinking'."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_invoke_with_stream(tmpdir, [
                _make_assistant_event(
                    _make_thinking_block('I am thinking.'),
                    _make_text_block('My response.'),
                ),
            ])
            thinking_msgs = [m for m in msgs if m.sender == 'thinking']
            self.assertTrue(
                len(thinking_msgs) > 0,
                'invoke() must write thinking blocks to the bus as sender="thinking"; '
                f'bus senders: {[m.sender for m in msgs]}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invoke_writes_tool_use_event_to_bus(self):
        """invoke() must write tool_use blocks to the bus as sender='tool_use'."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_invoke_with_stream(tmpdir, [
                _make_assistant_event(
                    _make_tool_use_block('Read', {'file_path': '/foo.txt'}),
                ),
                _make_tool_result_event('tu_1', 'content'),
                _make_assistant_event(_make_text_block('Done.')),
            ])
            tool_use_msgs = [m for m in msgs if m.sender == 'tool_use']
            self.assertTrue(
                len(tool_use_msgs) > 0,
                'invoke() must write tool_use blocks to the bus as sender="tool_use"; '
                f'bus senders: {[m.sender for m in msgs]}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invoke_writes_tool_result_event_to_bus(self):
        """invoke() must write tool_result events to the bus as sender='tool_result'."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_invoke_with_stream(tmpdir, [
                _make_assistant_event(
                    _make_tool_use_block('Read', {'file_path': '/foo.txt'}),
                ),
                _make_tool_result_event('tu_1', 'file contents here'),
                _make_assistant_event(_make_text_block('Based on that.')),
            ])
            tool_result_msgs = [m for m in msgs if m.sender == 'tool_result']
            self.assertTrue(
                len(tool_result_msgs) > 0,
                'invoke() must write tool_result events to the bus as sender="tool_result"; '
                f'bus senders: {[m.sender for m in msgs]}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invoke_writes_system_event_to_bus(self):
        """invoke() must write system events to the bus as sender='system'."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_invoke_with_stream(tmpdir, [
                _make_system_event('sid-sys-test'),
                _make_assistant_event(_make_text_block('Response.')),
            ])
            system_msgs = [m for m in msgs if m.sender == 'system']
            self.assertTrue(
                len(system_msgs) > 0,
                'invoke() must write system events to the bus as sender="system"; '
                f'bus senders: {[m.sender for m in msgs]}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invoke_still_writes_agent_text_with_role_sender(self):
        """invoke() must still write the agent text response with the agent role sender."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_invoke_with_stream(tmpdir, [
                _make_assistant_event(_make_text_block('My final answer.')),
            ])
            agent_msgs = [m for m in msgs if m.sender == 'office-manager']
            self.assertTrue(
                len(agent_msgs) > 0,
                'invoke() must still write the agent text to the bus as sender="office-manager"; '
                f'bus senders: {[m.sender for m in msgs]}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invoke_bus_ordering_preserves_stream_order(self):
        """Bus messages from invoke() must appear in stream event order."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_invoke_with_stream(tmpdir, [
                _make_system_event('sid-order'),
                _make_assistant_event(
                    _make_thinking_block('think'),
                    _make_tool_use_block('Glob', {'pattern': '*.py'}),
                ),
                _make_tool_result_event('tu_1', 'results'),
                _make_assistant_event(_make_text_block('answer')),
            ])
            # Skip the human message at the front
            agent_msgs = [m for m in msgs if m.sender != 'human']
            senders = [m.sender for m in agent_msgs]

            expected = ['system', 'thinking', 'tool_use', 'tool_result', 'office-manager']
            for i in range(len(expected) - 1):
                a, b = expected[i], expected[i + 1]
                idx_a = next((j for j, s in enumerate(senders) if s == a), -1)
                idx_b = next((j for j, s in enumerate(senders) if s == b), -1)
                self.assertGreater(idx_a, -1, f'Expected "{a}" in bus messages; got: {senders}')
                self.assertGreater(idx_b, -1, f'Expected "{b}" in bus messages; got: {senders}')
                self.assertLess(
                    idx_a, idx_b,
                    f'"{a}" (pos {idx_a}) must come before "{b}" (pos {idx_b}) in bus; '
                    f'senders: {senders}',
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invoke_returns_agent_text_concatenated(self):
        """invoke() must still return the concatenated agent text (callers depend on this)."""
        tmpdir = _make_tmpdir()
        try:
            from orchestrator.office_manager import OfficeManagerSession

            session = OfficeManagerSession(tmpdir, 'darrell')
            session.send_human_message('What is the status?')

            stream_path = _make_stream_path([
                _make_assistant_event(_make_text_block('Status: all good.')),
            ])
            mock_result = MagicMock()
            mock_result.session_id = 'sid-ret-test'

            try:
                with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                    instance = MagicMock()
                    instance.run = AsyncMock(return_value=mock_result)
                    MockRunner.return_value = instance

                    with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                        with patch('os.close'):
                            with patch('os.unlink'):
                                result = asyncio.run(session.invoke(cwd=tmpdir))

                self.assertIn(
                    'Status: all good.', result,
                    f'invoke() must return the agent text; got: {result!r}',
                )
            finally:
                if os.path.exists(stream_path):
                    os.unlink(stream_path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Edge case: empty/malformed stream ─────────────────────────────────────────

class TestIterStreamEventsEdgeCases(unittest.TestCase):
    """_iter_stream_events must handle edge cases gracefully."""

    def test_empty_stream_yields_no_events(self):
        """An empty stream file must yield no events (not raise)."""
        from orchestrator.office_manager import _iter_stream_events

        fd, path = tempfile.mkstemp(suffix='.jsonl', prefix='om-empty-')
        os.close(fd)
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        self.assertEqual(events, [], 'Empty stream must yield no events')

    def test_missing_stream_file_yields_no_events(self):
        """A missing stream file must yield no events (not raise)."""
        from orchestrator.office_manager import _iter_stream_events

        events = list(_iter_stream_events('/tmp/nonexistent-om-334.jsonl', 'office-manager'))
        self.assertEqual(events, [], 'Missing stream file must yield no events')

    def test_malformed_json_lines_are_skipped(self):
        """Malformed JSON lines in the stream must be skipped without raising."""
        from orchestrator.office_manager import _iter_stream_events

        fd, path = tempfile.mkstemp(suffix='.jsonl', prefix='om-bad-')
        os.close(fd)
        with open(path, 'w') as f:
            f.write('not json\n')
            f.write(json.dumps(_make_assistant_event(_make_text_block('valid'))) + '\n')
            f.write('{incomplete\n')
        try:
            events = list(_iter_stream_events(path, 'office-manager'))
        finally:
            os.unlink(path)

        # Must produce an event for the valid line and not raise for the bad ones
        self.assertTrue(len(events) > 0, 'Valid events after malformed lines must still be yielded')


# ── build_context() excludes non-conversational events ────────────────────────

class TestBuildContextExcludesStreamTrace(unittest.TestCase):
    """build_context() must exclude thinking, tool_use, tool_result, and system messages.

    After invoke() writes typed stream events to the bus, build_context() would
    include them in the agent's fresh-session prompt unless explicitly filtered.
    The agent should see conversational history, not internal diagnostic events.
    """

    def _seed_conversation(self, session, events: list) -> None:
        """Write a list of (sender, content) events directly to the bus."""
        for sender, content in events:
            session._bus.send(session.conversation_id, sender, content)

    def test_build_context_excludes_thinking_messages(self):
        """build_context() must not include thinking messages in the context string."""
        tmpdir = _make_tmpdir()
        try:
            session = _make_om_session(tmpdir)
            self._seed_conversation(session, [
                ('human', 'What is the status?'),
                ('thinking', 'Let me reason about this.'),
                ('office-manager', 'Everything is fine.'),
            ])
            context = session.build_context()
            self.assertNotIn(
                'Let me reason about this.',
                context,
                'build_context() must not include thinking block content in the agent prompt',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_context_excludes_tool_use_messages(self):
        """build_context() must not include tool_use messages in the context string."""
        tmpdir = _make_tmpdir()
        try:
            session = _make_om_session(tmpdir)
            tool_json = json.dumps({'name': 'Bash', 'input': {'command': 'git log --oneline'}})
            self._seed_conversation(session, [
                ('human', 'What is the project status?'),
                ('tool_use', tool_json),
                ('office-manager', 'Done.'),
            ])
            context = session.build_context()
            self.assertNotIn(
                'git log --oneline',
                context,
                'build_context() must not include tool invocation content in the agent prompt',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_context_excludes_tool_result_messages(self):
        """build_context() must not include tool_result messages in the context string."""
        tmpdir = _make_tmpdir()
        try:
            session = _make_om_session(tmpdir)
            self._seed_conversation(session, [
                ('human', 'Show me the file.'),
                ('tool_result', 'file contents: line 1\nline 2'),
                ('office-manager', 'I read the file.'),
            ])
            context = session.build_context()
            self.assertNotIn(
                'file contents: line 1',
                context,
                'build_context() must not include tool_result content in the agent prompt',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_context_excludes_system_messages(self):
        """build_context() must not include system event messages in the context string."""
        tmpdir = _make_tmpdir()
        try:
            session = _make_om_session(tmpdir)
            system_json = json.dumps({'type': 'system', 'session_id': 'sid-001'})
            self._seed_conversation(session, [
                ('system', system_json),
                ('human', 'Hello.'),
                ('office-manager', 'Hi there.'),
            ])
            context = session.build_context()
            self.assertNotIn(
                'sid-001',
                context,
                'build_context() must not include system event content in the agent prompt',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_context_still_includes_human_and_agent_messages(self):
        """build_context() must still include human and office-manager messages."""
        tmpdir = _make_tmpdir()
        try:
            session = _make_om_session(tmpdir)
            self._seed_conversation(session, [
                ('human', 'What projects are active?'),
                ('thinking', 'Let me check the registry.'),
                ('tool_use', json.dumps({'name': 'Glob', 'input': {'pattern': '*.yaml'}})),
                ('tool_result', 'project-a.yaml\nproject-b.yaml'),
                ('office-manager', 'There are two active projects.'),
            ])
            context = session.build_context()
            self.assertIn(
                'What projects are active?', context,
                'build_context() must include human message content',
            )
            self.assertIn(
                'There are two active projects.', context,
                'build_context() must include office-manager message content',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_context_excludes_unknown_block_type_messages(self):
        """build_context() must not include unknown:<type> messages in the context string."""
        tmpdir = _make_tmpdir()
        try:
            session = _make_om_session(tmpdir)
            self._seed_conversation(session, [
                ('human', 'Proceed.'),
                ('unknown:future_block', json.dumps({'type': 'future_block', 'data': 'xyz'})),
                ('office-manager', 'Understood.'),
            ])
            context = session.build_context()
            self.assertNotIn(
                'future_block',
                context,
                'build_context() must not include unknown:<type> event content in the agent prompt',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Proxy path: invoke() writes typed events to bus ──────────────────────────

def _make_proxy_session(tmpdir: str, decider: str = 'alice'):
    from orchestrator.proxy_review import ProxyReviewSession, proxy_bus_path
    path = proxy_bus_path(tmpdir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return ProxyReviewSession(tmpdir, decider)


class TestProxyInvokeWritesAllEventTypesToBus(unittest.TestCase):
    """ProxyReviewSession.invoke() must write every stream event type to the bus."""

    def _run_proxy_invoke_with_stream(self, tmpdir: str, stream_events: list) -> list:
        """Run proxy invoke() with a synthetic stream and return all bus messages."""
        session = _make_proxy_session(tmpdir)
        session.send_human_message('Is the issue resolved?')

        stream_path = _make_stream_path(stream_events)
        mock_result = MagicMock()
        mock_result.session_id = 'sid-proxy-test'

        try:
            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            with patch('orchestrator.proxy_review._process_response_signals'):
                                asyncio.run(session.invoke(cwd=tmpdir))

            return session.get_messages()
        finally:
            if os.path.exists(stream_path):
                os.unlink(stream_path)

    def test_proxy_invoke_writes_thinking_to_bus(self):
        """proxy invoke() must write thinking blocks to the bus as sender='thinking'."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_proxy_invoke_with_stream(tmpdir, [
                _make_assistant_event(
                    _make_thinking_block('Let me reconsider this carefully.'),
                    _make_text_block('I think the issue is resolved.'),
                ),
            ])
            thinking_msgs = [m for m in msgs if m.sender == 'thinking']
            self.assertTrue(
                len(thinking_msgs) > 0,
                'proxy invoke() must write thinking blocks to the bus as sender="thinking"; '
                f'bus senders: {[m.sender for m in msgs]}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_proxy_invoke_writes_tool_use_to_bus(self):
        """proxy invoke() must write tool_use blocks to the bus as sender='tool_use'."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_proxy_invoke_with_stream(tmpdir, [
                _make_assistant_event(
                    _make_tool_use_block('Read', {'file_path': '/session.json'}),
                ),
                _make_tool_result_event('tu_1', 'session data'),
                _make_assistant_event(_make_text_block('Looks good.')),
            ])
            tool_use_msgs = [m for m in msgs if m.sender == 'tool_use']
            self.assertTrue(
                len(tool_use_msgs) > 0,
                'proxy invoke() must write tool_use blocks to the bus as sender="tool_use"; '
                f'bus senders: {[m.sender for m in msgs]}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_proxy_invoke_writes_tool_result_to_bus(self):
        """proxy invoke() must write tool_result events to the bus as sender='tool_result'."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_proxy_invoke_with_stream(tmpdir, [
                _make_assistant_event(
                    _make_tool_use_block('Read', {'file_path': '/x'}),
                ),
                _make_tool_result_event('tu_1', 'content read'),
                _make_assistant_event(_make_text_block('Read it.')),
            ])
            tool_result_msgs = [m for m in msgs if m.sender == 'tool_result']
            self.assertTrue(
                len(tool_result_msgs) > 0,
                'proxy invoke() must write tool_result events to the bus as sender="tool_result"; '
                f'bus senders: {[m.sender for m in msgs]}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_proxy_invoke_writes_system_to_bus(self):
        """proxy invoke() must write system events to the bus as sender='system'."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_proxy_invoke_with_stream(tmpdir, [
                _make_system_event('sid-proxy-sys'),
                _make_assistant_event(_make_text_block('Acknowledged.')),
            ])
            system_msgs = [m for m in msgs if m.sender == 'system']
            self.assertTrue(
                len(system_msgs) > 0,
                'proxy invoke() must write system events to the bus as sender="system"; '
                f'bus senders: {[m.sender for m in msgs]}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_proxy_invoke_writes_proxy_text_with_proxy_sender(self):
        """proxy invoke() must write agent text to the bus as sender='proxy'."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_proxy_invoke_with_stream(tmpdir, [
                _make_assistant_event(_make_text_block('My proxy response.')),
            ])
            proxy_msgs = [m for m in msgs if m.sender == 'proxy']
            self.assertTrue(
                len(proxy_msgs) > 0,
                'proxy invoke() must write agent text to the bus as sender="proxy"; '
                f'bus senders: {[m.sender for m in msgs]}',
            )
            self.assertIn(
                'My proxy response.',
                proxy_msgs[0].content,
                f'proxy sender message must contain the response text; got: {proxy_msgs[0].content!r}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_proxy_invoke_bus_ordering_preserved(self):
        """proxy invoke() bus messages must appear in stream event order."""
        tmpdir = _make_tmpdir()
        try:
            msgs = self._run_proxy_invoke_with_stream(tmpdir, [
                _make_system_event('sid-proxy-order'),
                _make_assistant_event(
                    _make_thinking_block('think'),
                    _make_tool_use_block('Glob', {'pattern': '*.md'}),
                ),
                _make_tool_result_event('tu_1', 'found docs'),
                _make_assistant_event(_make_text_block('Here is the review.')),
            ])
            agent_msgs = [m for m in msgs if m.sender != 'human']
            senders = [m.sender for m in agent_msgs]

            expected = ['system', 'thinking', 'tool_use', 'tool_result', 'proxy']
            for i in range(len(expected) - 1):
                a, b = expected[i], expected[i + 1]
                idx_a = next((j for j, s in enumerate(senders) if s == a), -1)
                idx_b = next((j for j, s in enumerate(senders) if s == b), -1)
                self.assertGreater(idx_a, -1, f'Expected "{a}" in proxy bus messages; got: {senders}')
                self.assertGreater(idx_b, -1, f'Expected "{b}" in proxy bus messages; got: {senders}')
                self.assertLess(
                    idx_a, idx_b,
                    f'"{a}" (pos {idx_a}) must come before "{b}" (pos {idx_b}) in proxy bus; '
                    f'senders: {senders}',
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Proxy path: dialog history builders exclude non-conversational events ─────

class TestProxyDialogHistoryExcludesStreamTrace(unittest.TestCase):
    """build_dialog_history(), build_context(), and fresh-session history in
    ProxyReviewSession must all exclude thinking/tool/system events from the
    proxy agent's prompt.
    """

    def _seed_proxy_bus(self, session, events: list) -> None:
        """Write (sender, content) pairs directly to the proxy bus."""
        for sender, content in events:
            session._bus.send(session.conversation_id, sender, content)

    def test_build_dialog_history_excludes_thinking(self):
        """build_dialog_history() must skip thinking messages."""
        from orchestrator.proxy_review import build_dialog_history
        from orchestrator.messaging import SqliteMessageBus
        from orchestrator.proxy_review import proxy_bus_path

        tmpdir = _make_tmpdir()
        try:
            session = _make_proxy_session(tmpdir)
            self._seed_proxy_bus(session, [
                ('human', 'Are you confident?'),
                ('thinking', 'Let me reconsider.'),
                ('proxy', 'Yes, I am confident.'),
            ])
            history = build_dialog_history(session._bus, session.conversation_id)
            self.assertNotIn(
                'Let me reconsider.',
                history,
                'build_dialog_history() must not include thinking content in dialog history',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_dialog_history_excludes_tool_use(self):
        """build_dialog_history() must skip tool_use messages."""
        from orchestrator.proxy_review import build_dialog_history

        tmpdir = _make_tmpdir()
        try:
            session = _make_proxy_session(tmpdir)
            tool_json = json.dumps({'name': 'Read', 'input': {'file_path': '/proxy-notes.md'}})
            self._seed_proxy_bus(session, [
                ('human', 'Check the session.'),
                ('tool_use', tool_json),
                ('tool_result', 'proxy notes content'),
                ('proxy', 'I reviewed the session.'),
            ])
            history = build_dialog_history(session._bus, session.conversation_id)
            self.assertNotIn(
                'proxy-notes.md',
                history,
                'build_dialog_history() must not include tool_use content in dialog history',
            )
            self.assertNotIn(
                'proxy notes content',
                history,
                'build_dialog_history() must not include tool_result content in dialog history',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_dialog_history_preserves_human_and_proxy_messages(self):
        """build_dialog_history() must include human and proxy messages."""
        from orchestrator.proxy_review import build_dialog_history

        tmpdir = _make_tmpdir()
        try:
            session = _make_proxy_session(tmpdir)
            self._seed_proxy_bus(session, [
                ('human', 'Does the fix look complete?'),
                ('thinking', 'Let me read the diff.'),
                ('proxy', 'Yes, it handles all cases.'),
            ])
            history = build_dialog_history(session._bus, session.conversation_id)
            self.assertIn(
                'Does the fix look complete?', history,
                'build_dialog_history() must include human message',
            )
            self.assertIn(
                'Yes, it handles all cases.', history,
                'build_dialog_history() must include proxy message',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_proxy_build_context_excludes_stream_trace(self):
        """ProxyReviewSession.build_context() must not include non-conversational events."""
        tmpdir = _make_tmpdir()
        try:
            session = _make_proxy_session(tmpdir)
            self._seed_proxy_bus(session, [
                ('human', 'What do you think?'),
                ('thinking', 'I should check the memory.'),
                ('tool_use', json.dumps({'name': 'Read', 'input': {'file_path': '/mem.db'}})),
                ('tool_result', 'memory database contents'),
                ('proxy', 'I reviewed the prior corrections.'),
            ])
            context = session.build_context()
            self.assertNotIn(
                'I should check the memory.',
                context,
                'build_context() must not include thinking content in proxy prompt',
            )
            self.assertNotIn(
                'memory database contents',
                context,
                'build_context() must not include tool_result content in proxy prompt',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
