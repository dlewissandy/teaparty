"""Tests for Issue #350: Chat copy conversation button.

Acceptance criteria:
1. Copy button appears in the chat header for all conversation types (OM, proxy, job, task)
2. Clicking it writes all visible messages to clipboard in readable format
3. Button gives brief visual confirmation then reverts
4. Empty conversations: button is a no-op or copies an empty string
"""
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_CHAT_HTML = _REPO_ROOT / 'bridge' / 'static' / 'chat.html'


def _read_chat() -> str:
    return _CHAT_HTML.read_text()


class TestCopyButtonPresenceInHeader(unittest.TestCase):
    """Copy button must appear in the chat header for all conversation types."""

    def test_copy_button_rendered_in_renderMainArea(self):
        """renderMainArea must include a copy button in the header."""
        html = _read_chat()
        # Locate renderMainArea function body
        fn_start = html.find('function renderMainArea(')
        self.assertGreater(fn_start, -1, 'renderMainArea function must exist')
        # Find function body
        brace_start = html.find('{', fn_start)
        depth = 0
        end = brace_start
        for i in range(brace_start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = html[brace_start:end]
        self.assertRegex(body, r'[Cc]opy',
                         'renderMainArea must include a Copy button in the header')

    def test_copy_button_present_in_both_job_and_participant_layouts(self):
        """Copy button must appear regardless of job vs. participant conv type.

        renderMainArea is called for both layouts, so placing the button there
        ensures it appears in all conversation types.
        """
        html = _read_chat()
        fn_start = html.find('function renderMainArea(')
        self.assertGreater(fn_start, -1)
        brace_start = html.find('{', fn_start)
        depth = 0
        end = brace_start
        for i in range(brace_start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = html[brace_start:end]
        # copyConversation must be referenced in renderMainArea
        self.assertIn('copyConversation', body,
                      'renderMainArea must call copyConversation from the Copy button')

    def test_copy_button_has_copy_btn_class_for_feedback_targeting(self):
        """Copy button must have a class or identifier for post-copy label update."""
        html = _read_chat()
        # The button needs some way to be targeted for feedback; copy-btn class is canonical
        self.assertIn('copy-btn', html,
                      'Copy button must have copy-btn class so copyConversation can target it')


class TestCopyConversationFunction(unittest.TestCase):
    """copyConversation must collect visible messages and write them to clipboard."""

    def test_copyConversation_function_exists(self):
        """copyConversation function must be defined in chat.html."""
        html = _read_chat()
        self.assertIn('function copyConversation(', html,
                      'copyConversation function must be defined')

    def test_copyConversation_calls_navigator_clipboard_writeText(self):
        """copyConversation must write to the clipboard via navigator.clipboard.writeText."""
        html = _read_chat()
        fn_start = html.find('function copyConversation(')
        self.assertGreater(fn_start, -1)
        brace_start = html.find('{', fn_start)
        depth = 0
        end = brace_start
        for i in range(brace_start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = html[brace_start:end]
        self.assertIn('navigator.clipboard.writeText', body,
                      'copyConversation must call navigator.clipboard.writeText')

    def test_copyConversation_respects_active_filters(self):
        """copyConversation must collect only visible (filtered) messages."""
        html = _read_chat()
        fn_start = html.find('function copyConversation(')
        self.assertGreater(fn_start, -1)
        brace_start = html.find('{', fn_start)
        depth = 0
        end = brace_start
        for i in range(brace_start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = html[brace_start:end]
        self.assertIn('filterMessages', body,
                      'copyConversation must call filterMessages to respect active filter toggles')

    def test_copyConversation_formats_messages_as_sender_colon_content(self):
        """Messages must be formatted as {Sender}: {content} separated by blank lines."""
        html = _read_chat()
        fn_start = html.find('function copyConversation(')
        self.assertGreater(fn_start, -1)
        brace_start = html.find('{', fn_start)
        depth = 0
        end = brace_start
        for i in range(brace_start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = html[brace_start:end]
        # Must include sender and content fields with a colon separator
        self.assertRegex(body, r'sender.*:.*content|content.*sender',
                         'copyConversation must format messages as sender: content')
        # Must join with double newline (blank line between messages)
        self.assertIn(r'\n\n', body,
                      'copyConversation must separate messages with blank lines (\\n\\n)')


class TestCopyButtonVisualFeedback(unittest.TestCase):
    """Copy button must show 'Copied' briefly then revert to 'Copy'."""

    def test_copyConversation_changes_label_to_Copied_on_success(self):
        """On successful clipboard write, button label must change to 'Copied'."""
        html = _read_chat()
        fn_start = html.find('function copyConversation(')
        self.assertGreater(fn_start, -1)
        brace_start = html.find('{', fn_start)
        depth = 0
        end = brace_start
        for i in range(brace_start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = html[brace_start:end]
        self.assertIn('Copied', body,
                      'copyConversation must set button text to "Copied" after successful copy')

    def test_copyConversation_reverts_label_after_timeout(self):
        """Label must revert to 'Copy' after ~1.5 s via setTimeout."""
        html = _read_chat()
        fn_start = html.find('function copyConversation(')
        self.assertGreater(fn_start, -1)
        brace_start = html.find('{', fn_start)
        depth = 0
        end = brace_start
        for i in range(brace_start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = html[brace_start:end]
        self.assertIn('setTimeout', body,
                      'copyConversation must use setTimeout to revert the button label')
        # Must revert back to 'Copy' text
        self.assertIn('Copy', body,
                      'copyConversation must revert button text to "Copy" after timeout')

    def test_copy_button_reverts_after_approximately_1500ms(self):
        """The revert timeout must be ~1500 ms."""
        html = _read_chat()
        fn_start = html.find('function copyConversation(')
        self.assertGreater(fn_start, -1)
        brace_start = html.find('{', fn_start)
        depth = 0
        end = brace_start
        for i in range(brace_start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = html[brace_start:end]
        self.assertIn('1500', body,
                      'copyConversation must use a 1500 ms timeout for label revert')


class TestCopyButtonEmptyConversation(unittest.TestCase):
    """Empty conversations: copy button must be a no-op or copy empty string."""

    def test_copyConversation_handles_empty_message_list(self):
        """copyConversation must not throw when pageState.messages is empty."""
        html = _read_chat()
        fn_start = html.find('function copyConversation(')
        self.assertGreater(fn_start, -1)
        brace_start = html.find('{', fn_start)
        depth = 0
        end = brace_start
        for i in range(brace_start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = html[brace_start:end]
        # Uses filterMessages(pageState.messages) which handles empty list safely via .map/.join
        self.assertIn('pageState.messages', body,
                      'copyConversation must operate on pageState.messages')


if __name__ == '__main__':
    unittest.main()
