"""Tests for issue #312: chat.html WS handler delivers messages for active conversation.

Acceptance criteria:
1. onWsMessage filters by activeConvId() — not the static top-level convId URL parameter.
2. sendMessage POSTs to activeConvId() — not the static top-level convId URL parameter.
3. activeConvId() returns 'task:{project}:{session}:{taskId}' when a task is selected
   in a job chat.
4. activeConvId() returns convId (the job-level ID) when no task is selected.
"""
import os
import re
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHAT_HTML = os.path.join(_REPO_ROOT, 'docs', 'proposals', 'ui-redesign', 'mockup', 'chat.html')


def _read_chat():
    with open(_CHAT_HTML) as f:
        return f.read()


def _extract_function_body(content, name):
    """Return the source of the named JS function (from 'function name' to its closing brace).

    Handles one level of nested braces. Returns '' if the function is not found.
    """
    start = content.find('function ' + name + '(')
    if start == -1:
        return ''
    # Find opening brace
    open_brace = content.find('{', start)
    if open_brace == -1:
        return ''
    depth = 0
    pos = open_brace
    while pos < len(content):
        if content[pos] == '{':
            depth += 1
        elif content[pos] == '}':
            depth -= 1
            if depth == 0:
                return content[start:pos + 1]
        pos += 1
    return ''


# ── onWsMessage: filter by activeConvId() ────────────────────────────────────

class TestWsMessageFilterUsesActiveConvId(unittest.TestCase):
    """onWsMessage must filter messages by the dynamically computed activeConvId().

    The bug was filtering by the static top-level convId URL parameter, which caused
    task sub-conversation messages to be dropped when a task was selected in the
    sidebar — because convId never changes (it's always the job-level ID).
    """

    def setUp(self):
        self.content = _read_chat()
        self.fn = _extract_function_body(self.content, 'onWsMessage')

    def test_onWsMessage_function_exists(self):
        self.assertNotEqual(self.fn, '',
                            'onWsMessage function must exist in chat.html')

    def test_onWsMessage_calls_activeConvId(self):
        self.assertIn('activeConvId()', self.fn,
                      'onWsMessage must filter by activeConvId() so that task '
                      'sub-conversation messages are delivered when a task is selected')

    def test_onWsMessage_does_not_filter_by_bare_convId(self):
        # The filter must NOT compare ev.conversation_id directly against the
        # static convId variable — that discards messages for task sub-conversations.
        # Note: 'convId' also appears inside activeConvId() itself, so we check the
        # specific broken pattern: comparing against the bare name without a call.
        self.assertNotIn('conversation_id === convId', self.fn,
                         'onWsMessage must not compare ev.conversation_id === convId '
                         '(static URL param) — use activeConvId() instead')
        self.assertNotIn('conversation_id !== convId', self.fn,
                         'onWsMessage must not compare ev.conversation_id !== convId '
                         '(static URL param) — use activeConvId() instead')


# ── sendMessage: POST to activeConvId() ──────────────────────────────────────

class TestSendMessageUsesActiveConvId(unittest.TestCase):
    """sendMessage must POST to the active conversation's ID, not the job-level convId.

    The bug: when a task was selected, sending still POSTed to the job-level convId.
    The fix: sendMessage must use activeConvId() for the POST endpoint.
    """

    def setUp(self):
        self.content = _read_chat()
        self.fn = _extract_function_body(self.content, 'sendMessage')

    def test_sendMessage_function_exists(self):
        self.assertNotEqual(self.fn, '',
                            'sendMessage function must exist in chat.html')

    def test_sendMessage_posts_to_activeConvId(self):
        self.assertIn('activeConvId()', self.fn,
                      'sendMessage must POST to /api/conversations/{activeConvId()} '
                      'so that messages reach the selected task conversation, not the '
                      'job-level conversation')

    def test_sendMessage_does_not_post_to_bare_convId(self):
        # Check for the specific broken pattern: concatenating convId (bare variable)
        # into the fetch URL instead of calling activeConvId().
        # We look for a POST fetch that uses convId rather than activeConvId().
        broken_pattern = re.search(
            r"fetch\([^)]*encodeURIComponent\(convId\)[^)]*\{",
            self.fn,
        )
        self.assertIsNone(
            broken_pattern,
            'sendMessage must not POST to encodeURIComponent(convId) — '
            'that sends to the job-level conversation even when a task is selected. '
            'Use activeConvId() instead.',
        )


# ── activeConvId(): returns task conv ID when task is selected ────────────────

class TestActiveConvIdBuildsTaskConvId(unittest.TestCase):
    """activeConvId() must return the task-scoped conversation ID when a task is selected.

    In a job chat the full conversation ID for a task is:
        task:{project}:{session_id}:{taskId}

    activeConvId() must construct this from the URL-parsed convProject, session_id,
    and selectedItem so that the WS filter and POST target are both correct.
    """

    def setUp(self):
        self.content = _read_chat()
        self.fn = _extract_function_body(self.content, 'activeConvId')

    def test_activeConvId_function_exists(self):
        self.assertNotEqual(self.fn, '',
                            'activeConvId function must exist in chat.html')

    def test_activeConvId_constructs_task_conv_id_from_selectedItem(self):
        # Must compose "task:{project}:{session}:{task}" from URL params + selectedItem
        self.assertIn("'task:'", self.fn,
                      "activeConvId must build a task conv ID prefixed with 'task:' "
                      "when a task is selected in a job chat")
        self.assertIn('selectedItem', self.fn,
                      'activeConvId must incorporate selectedItem into the task conv ID')

    def test_activeConvId_uses_convProject_and_session_id(self):
        self.assertIn('convProject', self.fn,
                      'activeConvId must include convProject when building the task conv ID')
        self.assertIn('session_id', self.fn,
                      'activeConvId must include session_id when building the task conv ID')


# ── activeConvId(): falls back to convId when no task is selected ─────────────

class TestActiveConvIdFallsBackToConvId(unittest.TestCase):
    """activeConvId() must return the job-level convId when no task is selected.

    When selectedItem is null (the user is viewing the job conversation itself),
    the WS filter and POST target must use the top-level convId.
    """

    def setUp(self):
        self.content = _read_chat()
        self.fn = _extract_function_body(self.content, 'activeConvId')

    def test_activeConvId_returns_convId_as_default(self):
        self.assertIn('return convId', self.fn,
                      'activeConvId must return the top-level convId when no item is '
                      'selected (job conversation view)')


if __name__ == '__main__':
    unittest.main()
