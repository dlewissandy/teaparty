"""Tests for issue #282: broadcast-all WebSocket + optimistic UI race conditions.

Acceptance criteria:
1. MessageRelay broadcasts 'id' in message events (enables correlation ID filtering)
2. chat.html sends via POST /api/conversations/{id} (not just optimistic UI)
3. chat.html stores returned message IDs and filters WebSocket echoes of those IDs
4. index.html fetchAll() merges escalation state — never clears WS-established entries
5. index.html render() shows badge from escalationConvMap regardless of REST needs_input
6. bridge-api.md documents the correlation ID scheme and scale assumption
"""
import asyncio
import os
import re
import unittest

_WORKTREE = os.path.join(os.path.dirname(__file__), '..', '.worktrees', 'issue-282')
_CHAT_HTML = os.path.join(_WORKTREE, 'docs', 'proposals', 'ui-redesign', 'mockup', 'chat.html')
_INDEX_HTML = os.path.join(_WORKTREE, 'docs', 'proposals', 'ui-redesign', 'mockup', 'index.html')
_BRIDGE_API = os.path.join(_WORKTREE, 'docs', 'proposals', 'ui-redesign', 'references', 'bridge-api.md')


# ── Fake helpers (same pattern as test_issue_297.py) ─────────────────────────

class _FakeMsg:
    def __init__(self, sender, content, timestamp=1.0, msg_id='msg-abc'):
        self.sender = sender
        self.content = content
        self.timestamp = timestamp
        self.id = msg_id
        self.conversation = 'conv-1'


class _FakeConv:
    def __init__(self, cid):
        self.id = cid


class _FakeBus:
    def __init__(self, conv_ids=None, messages=None, awaiting=None):
        self._conv_ids = conv_ids or []
        self._messages = messages or {}
        self._awaiting = awaiting or []

    def conversations(self):
        return list(self._conv_ids)

    def receive(self, cid, since_timestamp=0.0):
        return [m for m in self._messages.get(cid, []) if m.timestamp > since_timestamp]

    def conversations_awaiting_input(self):
        return self._awaiting


# ── AC 1: message events must include 'id' field ─────────────────────────────

class TestMessageEventIncludesId(unittest.TestCase):
    """MessageRelay must broadcast an 'id' field in message events.

    This is the server-side half of the correlation ID scheme: without the
    message ID in the event payload, the chat page cannot tell which WebSocket
    messages echo ones it just sent.
    """

    def test_message_event_has_id_field(self):
        """message events must include an 'id' field equal to msg.id."""
        from projects.POC.bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:poc:job-001:t1'
        msg = _FakeMsg('orchestrator', 'Test content', timestamp=1.0, msg_id='abc123')
        bus = _FakeBus(conv_ids=[cid], messages={cid: [msg]})
        relay = MessageRelay({'session-1': bus}, broadcast)

        asyncio.run(relay.poll_once())

        msg_events = [e for e in events if e['type'] == 'message']
        self.assertEqual(len(msg_events), 1, 'Expected exactly one message event')
        self.assertIn('id', msg_events[0],
                      "message event must include 'id' field for correlation filtering")

    def test_message_event_id_matches_msg_id(self):
        """The 'id' in the message event must be the message's actual DB id."""
        from projects.POC.bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:poc:job-001:t1'
        msg = _FakeMsg('human', 'Hello', timestamp=2.0, msg_id='deadbeef')
        bus = _FakeBus(conv_ids=[cid], messages={cid: [msg]})
        relay = MessageRelay({'session-1': bus}, broadcast)

        asyncio.run(relay.poll_once())

        msg_events = [e for e in events if e['type'] == 'message']
        self.assertEqual(len(msg_events), 1)
        self.assertEqual(msg_events[0]['id'], 'deadbeef',
                         "event['id'] must equal msg.id, not a derived value")

    def test_multiple_messages_each_have_distinct_ids(self):
        """Each message event must carry that specific message's id."""
        from projects.POC.bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'job:poc:job-001'
        msgs = [
            _FakeMsg('orchestrator', 'First', timestamp=1.0, msg_id='id-1'),
            _FakeMsg('human', 'Second', timestamp=2.0, msg_id='id-2'),
        ]
        bus = _FakeBus(conv_ids=[cid], messages={cid: msgs})
        relay = MessageRelay({'session-1': bus}, broadcast)

        asyncio.run(relay.poll_once())

        msg_events = [e for e in events if e['type'] == 'message']
        emitted_ids = [e['id'] for e in msg_events]
        self.assertIn('id-1', emitted_ids)
        self.assertIn('id-2', emitted_ids)
        self.assertEqual(len(set(emitted_ids)), 2, 'Each message must carry its own unique id')


# ── AC 2 & 3: chat.html must POST and filter echoes ──────────────────────────

class TestChatHtmlSendViaPost(unittest.TestCase):
    """chat.html must send messages via POST /api/conversations/{id}.

    The optimistic-only mockSend() is insufficient: it never calls the bridge,
    so messages are never persisted and no correlation ID is available.
    """

    def setUp(self):
        with open(_CHAT_HTML) as f:
            self._src = f.read()

    def test_post_to_conversations_endpoint(self):
        """chat.html must call POST /api/conversations/ to persist messages."""
        self.assertIn('/api/conversations/', self._src,
                      "chat.html must POST to /api/conversations/{id} to send messages")

    def test_fetch_post_method(self):
        """The send call must use method: 'POST'."""
        self.assertIn("method: 'POST'", self._src,
                      "chat.html must use fetch with method: 'POST' to send messages")

    def test_sent_id_tracking(self):
        """chat.html must track sent message IDs to filter echoes."""
        # The page must maintain a set/collection of sent message IDs
        # (e.g., sentIds, _sentIds, sentMessageIds, etc.)
        has_tracking = (
            'sentIds' in self._src
            or 'sentMessageIds' in self._src
            or '_sent' in self._src
            or 'pendingIds' in self._src
        )
        self.assertTrue(has_tracking,
                        "chat.html must track sent message IDs (e.g., sentIds set) to filter WS echoes")

    def test_echo_filtering_on_message_event(self):
        """chat.html must skip message events whose id is in the sent set."""
        # Look for code that checks an id against the sent set before appending
        has_filter = (
            'sentIds.has(' in self._src
            or 'sentIds.delete(' in self._src
            or 'has(event.id)' in self._src
            or 'has(msg.id)' in self._src
        )
        self.assertTrue(has_filter,
                        "chat.html must filter WebSocket message events whose 'id' was already sent")


# ── AC 4: index.html fetchAll() must not clear WS-established badges ──────────

class TestIndexHtmlStickyBadge(unittest.TestCase):
    """index.html fetchAll() must not wipe escalationConvMap on reload.

    Resetting escalationConvMap = {} discards escalation state established by
    WebSocket input_requested events, causing badges to disappear prematurely
    when the page fetches fresh data.
    """

    def setUp(self):
        with open(_INDEX_HTML) as f:
            self._src = f.read()

    def test_fetchall_does_not_reset_escalation_map(self):
        """fetchAll() must not execute 'escalationConvMap = {}' unconditionally."""
        # The bug is exactly this assignment without a condition
        self.assertNotIn(
            'escalationConvMap = {}',
            self._src,
            "fetchAll() must not reset escalationConvMap — doing so clears WS-established badges"
        )

    def test_render_uses_escalation_map_for_badge(self):
        """render() must check escalationConvMap, not just s.needs_input, for badges."""
        # The render function must consult the sticky map, not only REST state
        self.assertIn(
            'escalationConvMap',
            self._src,
            "render() must use escalationConvMap as source of truth for badge visibility"
        )
        # Verify that the render function uses escalationConvMap within the project render loop
        # (not just from the onInputRequested / onMessage handlers)
        render_fn_match = re.search(
            r'function render\(\)(.*?)^}',
            self._src,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_fn_match, 'render() function must exist')
        render_body = render_fn_match.group(1)
        self.assertIn('escalationConvMap', render_body,
                      "render() must reference escalationConvMap to preserve sticky badge state")


# ── AC 5: render() must show badge from map even when needs_input=false ───────

class TestIndexHtmlBadgeFromMap(unittest.TestCase):
    """render() must show escalation badge when escalationConvMap has an entry.

    The REST data may show needs_input=false if the bridge re-fetches after a
    race. The sticky map ensures the badge remains until the human responds.
    """

    def setUp(self):
        with open(_INDEX_HTML) as f:
            self._src = f.read()

    def test_badge_condition_includes_map_lookup(self):
        """The badge condition must check escalationConvMap[s.session_id] or equivalent."""
        # Look for a condition that combines needs_input with escalationConvMap
        has_combined = (
            ('needs_input' in self._src and 'escalationConvMap' in self._src)
        )
        self.assertTrue(has_combined,
                        "render() must use both needs_input and escalationConvMap for badge logic")
        # Verify the OR pattern: badge visible if needs_input OR map has entry
        has_or_pattern = (
            'needs_input || ' in self._src
            or '|| pageState.escalationConvMap' in self._src
            or 'escalationConvMap[s.session_id]' in self._src
        )
        self.assertTrue(has_or_pattern,
                        "render() badge must be visible when escalationConvMap has entry, not only when needs_input is true")


# ── AC 6: bridge-api.md must document the scheme and scale assumption ─────────

class TestBridgeApiDocumentation(unittest.TestCase):
    """bridge-api.md must document the correlation ID scheme and scale assumption."""

    def setUp(self):
        with open(_BRIDGE_API) as f:
            self._src = f.read()

    def test_correlation_id_documented(self):
        """bridge-api.md must describe the correlation ID approach."""
        has_correlation = (
            'correlation' in self._src.lower()
            or 'correlation id' in self._src.lower()
            or 'sent ids' in self._src.lower()
            or 'echo' in self._src.lower()
        )
        self.assertTrue(has_correlation,
                        "bridge-api.md must document the correlation ID / echo-filtering scheme")

    def test_scale_assumption_documented(self):
        """bridge-api.md must acknowledge the single-user / broadcast-all scale assumption."""
        has_scale = (
            'single user' in self._src.lower()
            or 'broadcast-all' in self._src.lower()
            or 'scale assumption' in self._src.lower()
            or 'handful' in self._src.lower()
        )
        self.assertTrue(has_scale,
                        "bridge-api.md must acknowledge the scale assumption that makes broadcast-all defensible")


if __name__ == '__main__':
    unittest.main()
