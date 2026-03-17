#!/usr/bin/env python3
"""Tests for issue #174: TUI drilldown activity stream opacity.

Four improvements:
  1. Agent labels use role names from Task dispatch, not UUID fragments
  2. File operation noise is suppressed by default (show_progress=False)
  3. Text blocks are suppressed when a SendMessage follows in the same event
  4. show_progress toggle controls noise level

Tests verify the EventParser behavior, not Textual widgets.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.tui.event_parser import EventParser


def _make_assistant_event(blocks, session_id='abc-123', parent_tool_use_id=''):
    """Build a minimal assistant event with given content blocks."""
    ev = {
        'type': 'assistant',
        'session_id': session_id,
        'message': {'content': blocks},
    }
    if parent_tool_use_id:
        ev['parent_tool_use_id'] = parent_tool_use_id
    return ev


def _text_block(text):
    return {'type': 'text', 'text': text}


def _send_message_block(content, recipient='', msg_type='broadcast'):
    block = {
        'type': 'tool_use',
        'name': 'SendMessage',
        'id': 'tool-1',
        'input': {
            'type': msg_type,
            'content': content,
        },
    }
    if recipient:
        block['input']['recipient'] = recipient
    return block


def _write_block(path):
    return {
        'type': 'tool_use',
        'name': 'Write',
        'id': 'tool-2',
        'input': {'file_path': path, 'content': 'data'},
    }


def _read_block(path):
    return {
        'type': 'tool_use',
        'name': 'Read',
        'id': 'tool-3',
        'input': {'file_path': path},
    }


def _edit_block(path):
    return {
        'type': 'tool_use',
        'name': 'Edit',
        'id': 'tool-4',
        'input': {'file_path': path, 'old_string': 'a', 'new_string': 'b'},
    }


# ── Text block suppression when SendMessage follows ─────────────────────


class TestTextBlockSuppression(unittest.TestCase):
    """Text blocks should be suppressed when a SendMessage with similar
    content exists in the same event."""

    def test_text_block_suppressed_when_sendmessage_follows(self):
        """When an event has both a text block and a SendMessage with the
        same content, only the SendMessage should be displayed."""
        parser = EventParser(show_progress=True)
        event = _make_assistant_event([
            _text_block('I have completed the research phase.'),
            _send_message_block('I have completed the research phase.'),
        ])
        result = parser.format_event(event)
        text = result.plain if result else ''
        # Should show SendMessage (@all), not the raw text block
        self.assertIn('@all', text,
                      "SendMessage should be displayed, not the text block")

    def test_text_block_shown_when_no_sendmessage(self):
        """When an event has only a text block (no SendMessage), it should
        be displayed normally."""
        parser = EventParser(show_progress=True)
        event = _make_assistant_event([
            _text_block('Working on the plan...'),
        ])
        result = parser.format_event(event)
        text = result.plain if result else ''
        self.assertIn('Working on the plan', text,
                      "Text block should show when no SendMessage present")


# ── File operation noise filtering ───────────────────────────────────────


class TestFileOperationFiltering(unittest.TestCase):
    """File operations (Write, Edit, Read) should be suppressed by default."""

    def test_write_suppressed_by_default(self):
        """Write events should not appear when show_progress=False."""
        parser = EventParser(show_progress=False)
        event = _make_assistant_event([_write_block('/tmp/foo.txt')])
        result = parser.format_event(event)
        self.assertIsNone(result, "Write should be suppressed with show_progress=False")

    def test_read_suppressed_by_default(self):
        """Read events should not appear when show_progress=False."""
        parser = EventParser(show_progress=False)
        event = _make_assistant_event([_read_block('/tmp/foo.txt')])
        result = parser.format_event(event)
        self.assertIsNone(result, "Read should be suppressed with show_progress=False")

    def test_sendmessage_always_shown(self):
        """SendMessage should always be shown regardless of show_progress."""
        parser = EventParser(show_progress=False)
        event = _make_assistant_event([
            _send_message_block('Task complete', msg_type='broadcast'),
        ])
        result = parser.format_event(event)
        self.assertIsNotNone(result, "SendMessage must always be shown")

    def test_default_is_filtered(self):
        """The drilldown's default EventParser should suppress file ops.
        Currently show_progress=True — this test verifies the default
        changes to False."""
        # This tests the default constructor behavior
        parser = EventParser()
        # Default should be show_progress=False for cleaner output
        event = _make_assistant_event([_write_block('/tmp/foo.txt')])
        result = parser.format_event(event)
        self.assertIsNone(result,
                          "Default EventParser should suppress file operations")


if __name__ == '__main__':
    unittest.main()
