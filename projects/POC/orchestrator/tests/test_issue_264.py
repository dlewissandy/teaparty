"""Tests for issue #264: Chat window stream filtering with per-type toggle controls.

Verifies:
1. StreamFilter has correct default states (agent/human ON, rest OFF)
2. Event classification maps stream-json events to the correct filter category
3. should_show() respects current toggle state
4. Toggling categories changes filter behavior
5. Per-conversation filter state (separate instances track independently)
6. All 9 categories from the design spec are supported
7. Unknown/unclassifiable events are excluded by default
8. should_show_sender gates message-bus messages by sender
9. Stream event loading from JSONL files
10. Session ID extraction from conversation IDs
"""
import json
import os
import tempfile
import unittest

from projects.POC.tui.stream_filter import StreamFilter, StreamCategory, classify_event


def _make_text_event(text='Hello'):
    """Create a stream-json assistant text event."""
    return {
        'type': 'assistant',
        'message': {
            'content': [{'type': 'text', 'text': text}],
        },
    }


def _make_thinking_event(thinking='Let me think...'):
    """Create a stream-json thinking event."""
    return {
        'type': 'assistant',
        'message': {
            'content': [{'type': 'thinking', 'thinking': thinking}],
        },
    }


def _make_tool_use_event(name='Read', input_data=None):
    """Create a stream-json tool_use event."""
    return {
        'type': 'assistant',
        'message': {
            'content': [{'type': 'tool_use', 'name': name, 'input': input_data or {}}],
        },
    }


def _make_tool_result_event(output='file contents', is_error=False):
    """Create a stream-json tool_result event."""
    return {
        'type': 'tool_result',
        'output': output,
        'is_error': is_error,
    }


def _make_system_event(subtype='init'):
    """Create a stream-json system event."""
    return {'type': 'system', 'subtype': subtype}


def _make_result_event(result='Done', cost=0.05, duration=12.3):
    """Create a stream-json result event with cost/token data."""
    return {
        'type': 'result',
        'result': result,
        'total_cost_usd': cost,
        'duration_seconds': duration,
        'num_turns': 3,
    }


def _make_human_message():
    """Create a human message event (from message bus, not stream-json)."""
    return {'type': 'human', 'content': 'I approve'}


def _make_state_event(from_state='PLANNING', to_state='PLAN_ASSERT'):
    """Create a CfA state transition event."""
    return {
        'type': 'state',
        'from': from_state,
        'to': to_state,
    }


def _make_log_event(message='debug info'):
    """Create a diagnostic log event."""
    return {'type': 'log', 'message': message}


class TestStreamCategoryDefaults(unittest.TestCase):
    """StreamFilter has correct default states per the design spec."""

    def test_agent_on_by_default(self):
        f = StreamFilter()
        self.assertTrue(f.is_enabled(StreamCategory.AGENT))

    def test_human_on_by_default(self):
        f = StreamFilter()
        self.assertTrue(f.is_enabled(StreamCategory.HUMAN))

    def test_thinking_off_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.is_enabled(StreamCategory.THINKING))

    def test_tools_off_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.is_enabled(StreamCategory.TOOLS))

    def test_results_off_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.is_enabled(StreamCategory.RESULTS))

    def test_system_off_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.is_enabled(StreamCategory.SYSTEM))

    def test_state_off_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.is_enabled(StreamCategory.STATE))

    def test_cost_off_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.is_enabled(StreamCategory.COST))

    def test_log_off_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.is_enabled(StreamCategory.LOG))

    def test_all_nine_categories_exist(self):
        """Design spec defines exactly 9 categories."""
        self.assertEqual(len(StreamCategory), 9)


class TestEventClassification(unittest.TestCase):
    """classify_event maps stream-json events to the correct category."""

    def test_assistant_text_is_agent(self):
        self.assertEqual(classify_event(_make_text_event()), StreamCategory.AGENT)

    def test_thinking_is_thinking(self):
        self.assertEqual(classify_event(_make_thinking_event()), StreamCategory.THINKING)

    def test_tool_use_is_tools(self):
        self.assertEqual(classify_event(_make_tool_use_event()), StreamCategory.TOOLS)

    def test_tool_result_is_results(self):
        self.assertEqual(classify_event(_make_tool_result_event()), StreamCategory.RESULTS)

    def test_system_init_is_system(self):
        self.assertEqual(classify_event(_make_system_event('init')), StreamCategory.SYSTEM)

    def test_result_with_cost_is_cost(self):
        self.assertEqual(classify_event(_make_result_event()), StreamCategory.COST)

    def test_human_message_is_human(self):
        self.assertEqual(classify_event(_make_human_message()), StreamCategory.HUMAN)

    def test_state_transition_is_state(self):
        self.assertEqual(classify_event(_make_state_event()), StreamCategory.STATE)

    def test_log_event_is_log(self):
        self.assertEqual(classify_event(_make_log_event()), StreamCategory.LOG)

    def test_unknown_event_returns_none(self):
        self.assertIsNone(classify_event({'type': 'unknown_mystery'}))


class TestShouldShow(unittest.TestCase):
    """should_show() respects toggle state."""

    def test_agent_text_shown_by_default(self):
        f = StreamFilter()
        self.assertTrue(f.should_show(_make_text_event()))

    def test_human_shown_by_default(self):
        f = StreamFilter()
        self.assertTrue(f.should_show(_make_human_message()))

    def test_thinking_hidden_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.should_show(_make_thinking_event()))

    def test_tools_hidden_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.should_show(_make_tool_use_event()))

    def test_results_hidden_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.should_show(_make_tool_result_event()))

    def test_system_hidden_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.should_show(_make_system_event()))

    def test_state_hidden_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.should_show(_make_state_event()))

    def test_cost_hidden_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.should_show(_make_result_event()))

    def test_log_hidden_by_default(self):
        f = StreamFilter()
        self.assertFalse(f.should_show(_make_log_event()))

    def test_unknown_event_hidden(self):
        f = StreamFilter()
        self.assertFalse(f.should_show({'type': 'unknown'}))


class TestToggling(unittest.TestCase):
    """Toggling categories changes filter behavior."""

    def test_enable_thinking_shows_thinking(self):
        f = StreamFilter()
        f.enable(StreamCategory.THINKING)
        self.assertTrue(f.should_show(_make_thinking_event()))

    def test_disable_agent_hides_agent(self):
        f = StreamFilter()
        f.disable(StreamCategory.AGENT)
        self.assertFalse(f.should_show(_make_text_event()))

    def test_toggle_flips_state(self):
        f = StreamFilter()
        f.toggle(StreamCategory.TOOLS)
        self.assertTrue(f.is_enabled(StreamCategory.TOOLS))
        f.toggle(StreamCategory.TOOLS)
        self.assertFalse(f.is_enabled(StreamCategory.TOOLS))

    def test_enable_all_shows_everything(self):
        f = StreamFilter()
        for cat in StreamCategory:
            f.enable(cat)
        self.assertTrue(f.should_show(_make_thinking_event()))
        self.assertTrue(f.should_show(_make_tool_use_event()))
        self.assertTrue(f.should_show(_make_tool_result_event()))
        self.assertTrue(f.should_show(_make_system_event()))
        self.assertTrue(f.should_show(_make_state_event()))
        self.assertTrue(f.should_show(_make_result_event()))
        self.assertTrue(f.should_show(_make_log_event()))


class TestPerConversationFilterState(unittest.TestCase):
    """Separate StreamFilter instances track independently."""

    def test_independent_instances(self):
        f1 = StreamFilter()
        f2 = StreamFilter()
        f1.enable(StreamCategory.THINKING)
        self.assertTrue(f1.is_enabled(StreamCategory.THINKING))
        self.assertFalse(f2.is_enabled(StreamCategory.THINKING))

    def test_enabled_categories_returns_set(self):
        f = StreamFilter()
        enabled = f.enabled_categories()
        self.assertEqual(enabled, {StreamCategory.AGENT, StreamCategory.HUMAN})

    def test_enabled_categories_after_toggle(self):
        f = StreamFilter()
        f.enable(StreamCategory.TOOLS)
        enabled = f.enabled_categories()
        self.assertEqual(enabled, {StreamCategory.AGENT, StreamCategory.HUMAN, StreamCategory.TOOLS})


class TestAssistantEventWithMixedContent(unittest.TestCase):
    """Assistant events with multiple content blocks classify correctly."""

    def test_assistant_with_only_thinking_classifies_as_thinking(self):
        event = {
            'type': 'assistant',
            'message': {
                'content': [{'type': 'thinking', 'thinking': 'hmm'}],
            },
        }
        self.assertEqual(classify_event(event), StreamCategory.THINKING)

    def test_assistant_with_only_tool_use_classifies_as_tools(self):
        event = {
            'type': 'assistant',
            'message': {
                'content': [{'type': 'tool_use', 'name': 'Write', 'input': {}}],
            },
        }
        self.assertEqual(classify_event(event), StreamCategory.TOOLS)

    def test_assistant_with_text_and_tool_classifies_as_agent(self):
        """When both text and tool_use are present, text (agent) wins."""
        event = {
            'type': 'assistant',
            'message': {
                'content': [
                    {'type': 'text', 'text': 'I will read the file'},
                    {'type': 'tool_use', 'name': 'Read', 'input': {}},
                ],
            },
        }
        self.assertEqual(classify_event(event), StreamCategory.AGENT)


class TestShouldShowSender(unittest.TestCase):
    """should_show_sender gates message-bus messages by sender."""

    def test_human_sender_shown_by_default(self):
        f = StreamFilter()
        self.assertTrue(f.should_show_sender('human'))

    def test_orchestrator_sender_shown_by_default(self):
        f = StreamFilter()
        self.assertTrue(f.should_show_sender('orchestrator'))

    def test_human_sender_hidden_when_disabled(self):
        f = StreamFilter()
        f.disable(StreamCategory.HUMAN)
        self.assertFalse(f.should_show_sender('human'))

    def test_orchestrator_sender_hidden_when_agent_disabled(self):
        f = StreamFilter()
        f.disable(StreamCategory.AGENT)
        self.assertFalse(f.should_show_sender('orchestrator'))

    def test_unknown_sender_maps_to_agent(self):
        f = StreamFilter()
        self.assertTrue(f.should_show_sender('proxy'))
        f.disable(StreamCategory.AGENT)
        self.assertFalse(f.should_show_sender('proxy'))

    def test_disable_agent_still_shows_human(self):
        """Disabling AGENT doesn't affect HUMAN — they're independent."""
        f = StreamFilter()
        f.disable(StreamCategory.AGENT)
        self.assertTrue(f.should_show_sender('human'))

    def test_disable_human_still_shows_agent(self):
        """Disabling HUMAN doesn't affect AGENT — they're independent."""
        f = StreamFilter()
        f.disable(StreamCategory.HUMAN)
        self.assertTrue(f.should_show_sender('orchestrator'))


class TestLoadStreamEvents(unittest.TestCase):
    """_load_stream_events reads and parses JSONL files."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_jsonl(self, name, events):
        path = os.path.join(self._tmp, name)
        with open(path, 'w') as f:
            for ev in events:
                f.write(json.dumps(ev) + '\n')
        return path

    def test_loads_events_from_single_file(self):
        from projects.POC.tui.screens.chat import _load_stream_events
        path = self._write_jsonl('stream.jsonl', [
            {'type': 'system', 'subtype': 'init'},
            {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Hello'}]}},
        ])
        events = _load_stream_events([path])
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]['type'], 'system')
        self.assertEqual(events[1]['type'], 'assistant')

    def test_loads_events_from_multiple_files(self):
        from projects.POC.tui.screens.chat import _load_stream_events
        p1 = self._write_jsonl('a.jsonl', [{'type': 'system', 'subtype': 'init'}])
        p2 = self._write_jsonl('b.jsonl', [{'type': 'result', 'total_cost_usd': 0.01}])
        events = _load_stream_events([p1, p2])
        self.assertEqual(len(events), 2)

    def test_skips_invalid_json_lines(self):
        from projects.POC.tui.screens.chat import _load_stream_events
        path = os.path.join(self._tmp, 'bad.jsonl')
        with open(path, 'w') as f:
            f.write('{"type": "system"}\n')
            f.write('not json\n')
            f.write('{"type": "result"}\n')
        events = _load_stream_events([path])
        self.assertEqual(len(events), 2)

    def test_handles_missing_file(self):
        from projects.POC.tui.screens.chat import _load_stream_events
        events = _load_stream_events(['/nonexistent/path.jsonl'])
        self.assertEqual(events, [])

    def test_empty_file_returns_empty(self):
        from projects.POC.tui.screens.chat import _load_stream_events
        path = os.path.join(self._tmp, 'empty.jsonl')
        with open(path, 'w') as f:
            pass
        events = _load_stream_events([path])
        self.assertEqual(events, [])


class TestSessionIdFromConv(unittest.TestCase):
    """_session_id_from_conv extracts session IDs from conversation IDs."""

    def test_session_prefix(self):
        from projects.POC.tui.screens.chat import _session_id_from_conv
        self.assertEqual(_session_id_from_conv('session:20260327-143000'), '20260327-143000')

    def test_team_prefix(self):
        from projects.POC.tui.screens.chat import _session_id_from_conv
        self.assertEqual(_session_id_from_conv('team:writing-abc'), 'writing-abc')

    def test_job_prefix(self):
        from projects.POC.tui.screens.chat import _session_id_from_conv
        self.assertEqual(_session_id_from_conv('job:build-123'), 'build-123')

    def test_task_prefix(self):
        from projects.POC.tui.screens.chat import _session_id_from_conv
        self.assertEqual(_session_id_from_conv('task:fix-bug'), 'fix-bug')

    def test_om_prefix_returns_none(self):
        """Office manager conversations don't map to a session."""
        from projects.POC.tui.screens.chat import _session_id_from_conv
        self.assertIsNone(_session_id_from_conv('om:darrell'))

    def test_unknown_prefix_returns_none(self):
        from projects.POC.tui.screens.chat import _session_id_from_conv
        self.assertIsNone(_session_id_from_conv('proxy:review-1'))


class TestStreamFilterIntegration(unittest.TestCase):
    """End-to-end: stream events are filtered correctly by category."""

    def test_tool_events_hidden_by_default_shown_when_enabled(self):
        """Tool use events are hidden by default, shown when tools filter is enabled."""
        f = StreamFilter()
        tool_event = {
            'type': 'assistant',
            'message': {'content': [{'type': 'tool_use', 'name': 'Read', 'input': {}}]},
        }
        self.assertFalse(f.should_show(tool_event))
        f.enable(StreamCategory.TOOLS)
        self.assertTrue(f.should_show(tool_event))

    def test_thinking_events_hidden_by_default_shown_when_enabled(self):
        f = StreamFilter()
        think_event = {
            'type': 'assistant',
            'message': {'content': [{'type': 'thinking', 'thinking': 'analyzing...'}]},
        }
        self.assertFalse(f.should_show(think_event))
        f.enable(StreamCategory.THINKING)
        self.assertTrue(f.should_show(think_event))

    def test_cost_events_hidden_by_default_shown_when_enabled(self):
        f = StreamFilter()
        cost_event = {'type': 'result', 'total_cost_usd': 0.05, 'duration_seconds': 10}
        self.assertFalse(f.should_show(cost_event))
        f.enable(StreamCategory.COST)
        self.assertTrue(f.should_show(cost_event))

    def test_system_events_hidden_by_default_shown_when_enabled(self):
        f = StreamFilter()
        sys_event = {'type': 'system', 'subtype': 'init'}
        self.assertFalse(f.should_show(sys_event))
        f.enable(StreamCategory.SYSTEM)
        self.assertTrue(f.should_show(sys_event))

    def test_result_events_hidden_by_default_shown_when_enabled(self):
        f = StreamFilter()
        result_event = {'type': 'tool_result', 'output': 'file contents'}
        self.assertFalse(f.should_show(result_event))
        f.enable(StreamCategory.RESULTS)
        self.assertTrue(f.should_show(result_event))


if __name__ == '__main__':
    unittest.main()
