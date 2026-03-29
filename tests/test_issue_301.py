"""Tests for issue #301: chat page — wire mockup to live bridge API.

Acceptance criteria:
1. chat.html loads job conversation messages via GET /api/conversations/{id}
2. chat.html discovers task sub-conversations via GET /api/conversations?type=task
3. chat.html subscribes to WebSocket for real-time message updates
4. chat.html appends messages from WebSocket 'message' events without full reload
5. chat.html updates sidebar escalation dots from 'input_requested' WS events
6. chat.html sends human messages via POST /api/conversations/{id}
7. chat.html shows/hides Review button based on GET /api/cfa/{session_id} phase
8. chat.html Withdraw button POSTs to /api/withdraw/{session_id}
9. chat.html participant sidebar loads conversations via GET /api/conversations?type={type}
10. chat.html message filters (agent/human/thinking/tools/system) work on live data
11. chat.html does NOT use mockData.conversations as its data source
"""
import os
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHAT_HTML = os.path.join(_REPO_ROOT, 'docs', 'proposals', 'ui-redesign', 'mockup', 'chat.html')


def _read_chat():
    with open(_CHAT_HTML) as f:
        return f.read()


# ── No hardcoded data ─────────────────────────────────────────────────────────

class TestChatHtmlNoMockData(unittest.TestCase):
    """chat.html must not use mockData.conversations as its conversation source."""

    def setUp(self):
        self.content = _read_chat()

    def test_does_not_read_conversations_from_mockdata(self):
        self.assertNotIn('mockData.conversations[', self.content,
                         'chat.html must not use mockData.conversations — replace with '
                         'GET /api/conversations/{id}')

    def test_does_not_use_mock_data_for_task_sidebar(self):
        # The old code called findTask() which iterated mockData.status.projects
        self.assertNotIn('mockData.status.projects', self.content,
                         'chat.html must not read task data from mockData.status — '
                         'discover tasks from GET /api/conversations?type=task')

    def test_mockSend_replaced_with_api_send(self):
        # The old mockSend() never called the API. It must be replaced or renamed.
        self.assertNotIn('function mockSend(', self.content,
                         'mockSend() must be replaced with a function that POSTs to '
                         'POST /api/conversations/{id}')


# ── GET /api/conversations/{id} ───────────────────────────────────────────────

class TestChatHtmlLoadsConversationFromApi(unittest.TestCase):
    """chat.html must fetch job/participant messages from /api/conversations/{id}."""

    def setUp(self):
        self.content = _read_chat()

    def test_fetches_conversation_messages(self):
        self.assertIn('/api/conversations/', self.content,
                      'chat.html must call GET /api/conversations/{id} to load messages')

    def test_uses_fetch_for_api_calls(self):
        self.assertIn('fetch(', self.content,
                      'chat.html must use fetch() for bridge API calls')


# ── GET /api/conversations?type=task ─────────────────────────────────────────

class TestChatHtmlLoadsTaskConversations(unittest.TestCase):
    """Job chat sidebar must discover task sub-conversations from the bridge."""

    def setUp(self):
        self.content = _read_chat()

    def test_fetches_task_conversations_by_type(self):
        self.assertIn('type=task', self.content,
                      'chat.html must call GET /api/conversations?type=task to discover '
                      'task sub-conversations for the job chat sidebar')


# ── WebSocket real-time updates ───────────────────────────────────────────────

class TestChatHtmlWebSocket(unittest.TestCase):
    """chat.html must use WebSocket for real-time message delivery."""

    def setUp(self):
        self.content = _read_chat()

    def test_opens_websocket_connection(self):
        self.assertIn('WebSocket', self.content,
                      'chat.html must open a WebSocket connection for real-time updates')

    def test_handles_message_events(self):
        # Must handle 'message' events from the WebSocket (variable name may differ)
        self.assertIn("'message'", self.content,
                      "chat.html must handle WebSocket 'message' events to append new messages")
        # Must have a dedicated WS message handler function
        self.assertIn('onWsMessage', self.content,
                      "chat.html must have a dedicated onWsMessage handler for incoming messages")

    def test_handles_input_requested_events(self):
        self.assertIn("'input_requested'", self.content,
                      "chat.html must handle 'input_requested' WS events to update "
                      "sidebar escalation dots")

    def test_websocket_connects_to_ws_endpoint(self):
        self.assertIn('/ws', self.content,
                      'chat.html must connect WebSocket to the /ws endpoint')


# ── POST /api/conversations/{id} ─────────────────────────────────────────────

class TestChatHtmlSendsMessages(unittest.TestCase):
    """chat.html must POST human messages to the bridge API."""

    def setUp(self):
        self.content = _read_chat()

    def test_posts_to_conversations_endpoint(self):
        self.assertIn("POST", self.content,
                      "chat.html must POST to /api/conversations/{id} to send human messages")

    def test_posts_content_field(self):
        # The POST body must include {"content": ...}, not just mention the word 'content'
        self.assertIn("content:", self.content,
                      "chat.html must include a 'content' key in the POST body JSON "
                      "(field name required by bridge API)")
        # Verify it's a POST with JSON body, not just a fetch GET
        self.assertIn("method: 'POST'", self.content,
                      "chat.html must use method: 'POST' for sending messages")


# ── Review button from GET /api/cfa/{session_id} ─────────────────────────────

class TestChatHtmlReviewButton(unittest.TestCase):
    """Review button visibility must be driven by CfA phase from the bridge."""

    def setUp(self):
        self.content = _read_chat()

    def test_fetches_cfa_state(self):
        self.assertIn('/api/cfa/', self.content,
                      'chat.html must call GET /api/cfa/{session_id} to determine '
                      'whether the Review button should be shown')

    def test_review_button_at_gate_phases(self):
        # The button should only appear at assertion phases
        self.assertIn('INTENT_ASSERT', self.content,
                      'chat.html must show Review button at INTENT_ASSERT phase')
        self.assertIn('PLAN_ASSERT', self.content,
                      'chat.html must show Review button at PLAN_ASSERT phase')
        self.assertIn('WORK_ASSERT', self.content,
                      'chat.html must show Review button at WORK_ASSERT phase')

    def test_does_not_use_mockdata_for_review_button(self):
        # Old code called getGateReviewButton() using mockData.status.projects
        self.assertNotIn('function getGateReviewButton(', self.content,
                         'chat.html must not use getGateReviewButton() with mockData — '
                         'gate state must come from GET /api/cfa/{session_id}')


# ── POST /api/withdraw/{session_id} ──────────────────────────────────────────

class TestChatHtmlWithdraw(unittest.TestCase):
    """Withdraw button must POST to the bridge withdraw endpoint."""

    def setUp(self):
        self.content = _read_chat()

    def test_withdraw_posts_to_api(self):
        self.assertIn('/api/withdraw/', self.content,
                      'chat.html must POST to /api/withdraw/{session_id} for the '
                      'Withdraw button — not just append a local system message')

    def test_withdraw_extracts_session_id_from_conv_id(self):
        # session_id is the last segment of job:{project}:{session_id}
        # The page must parse this from the conv query param
        self.assertIn('session_id', self.content,
                      'chat.html must extract the session_id from the conv ID '
                      'to construct the /api/withdraw/ path')


# ── Participant chat sidebar ──────────────────────────────────────────────────

class TestChatHtmlParticipantSidebar(unittest.TestCase):
    """Participant chat sidebar must load conversations from the bridge."""

    def setUp(self):
        self.content = _read_chat()

    def test_fetches_conversations_by_type_for_participant_sidebar(self):
        # Participant chat sidebar lists past sessions: fetched via ?type= param
        self.assertIn('/api/conversations?type=', self.content,
                      'chat.html must call GET /api/conversations?type={type} to populate '
                      'the participant chat sidebar with historical sessions')

    def test_infers_conv_type_from_prefix(self):
        # The page must map the 'om:' prefix to the office_manager API type
        self.assertIn("'office_manager'", self.content,
                      "chat.html must map the 'om:' conv ID prefix to 'office_manager' "
                      "for the ?type= query parameter")


# ── Message filters ───────────────────────────────────────────────────────────

class TestChatHtmlMessageFilters(unittest.TestCase):
    """Message filter buttons must apply to the live API message stream."""

    def setUp(self):
        self.content = _read_chat()

    def test_filter_buttons_present(self):
        # All five filter names must appear in the source (either as static HTML or
        # inside a string literal used to build the filter row dynamically).
        for f in ('agent', 'human', 'thinking', 'tools', 'system'):
            self.assertIn(f"'{f}'", self.content,
                          f'chat.html must include a filter for "{f}" messages')

    def test_filter_applied_before_render(self):
        # The filter buttons must gate what gets rendered using message sender/type checks
        self.assertIn('filter-btn', self.content,
                      'chat.html must use filter-btn class for message filter buttons')
        # After the fix, rendering must consult filter state before displaying messages
        self.assertIn('classList.contains', self.content,
                      'chat.html must check filter button state (classList.contains) '
                      'before rendering each message')


# ── Bridge unreachable error ──────────────────────────────────────────────────

class TestChatHtmlBridgeError(unittest.TestCase):
    """chat.html must show an error when the bridge is unreachable."""

    def setUp(self):
        self.content = _read_chat()

    def test_shows_error_when_bridge_unreachable(self):
        self.assertIn('Bridge not reachable', self.content,
                      'chat.html must show "Bridge not reachable" error when API calls fail, '
                      'same as index.html')


if __name__ == '__main__':
    unittest.main()
