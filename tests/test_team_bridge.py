import json
import queue
import unittest
from unittest.mock import MagicMock, patch, call

from teaparty_app.models import Conversation, Message
from teaparty_app.services.team_session import TeamEvent, TeamSession


def _make_conversation(*, conv_id: str = "conv-1", workgroup_id: str = "wg-1") -> Conversation:
    return Conversation(
        id=conv_id,
        workgroup_id=workgroup_id,
        created_by_user_id="user-1",
        kind="job",
        name="Test Job",
    )


def _make_trigger(*, conv_id: str = "conv-1") -> Message:
    return Message(
        id="msg-trigger",
        conversation_id=conv_id,
        sender_type="user",
        sender_user_id="user-1",
        content="Hello team",
    )


def _make_team_session(
    *,
    conv_id: str = "conv-1",
    slug_to_id: dict[str, str] | None = None,
) -> TeamSession:
    team = TeamSession(conv_id)
    team._agent_slugs = slug_to_id or {
        "lead-agent": "agent-lead",
        "researcher": "agent-researcher",
    }
    team.is_running = False  # events pre-loaded; no real process
    return team


class TestIncrementalEventProcessing(unittest.TestCase):
    """Test that process_team_events_sync posts messages incrementally."""

    def _run_bridge(self, events: list[TeamEvent], team: TeamSession | None = None):
        """Helper: load events into queue, run bridge, return created messages."""
        if team is None:
            team = _make_team_session()

        for ev in events:
            team.event_queue.put(ev)
        # Sentinel so the loop exits.
        team.event_queue.put(TeamEvent(kind="eof"))

        mock_session = MagicMock()
        mock_session.flush = MagicMock()

        conversation = _make_conversation()
        trigger = _make_trigger()

        with patch("teaparty_app.services.team_bridge.commit_with_retry"):
            with patch("teaparty_app.services.team_bridge._set_activity") as mock_set:
                with patch("teaparty_app.services.team_bridge._clear_activity") as mock_clear:
                    from teaparty_app.services.team_bridge import process_team_events_sync
                    created = process_team_events_sync(
                        mock_session, team, conversation, trigger,
                    )

        return created, mock_session, mock_set, mock_clear

    def test_assistant_text_posted_as_lead_message(self):
        events = [
            TeamEvent(
                kind="assistant",
                content="Lead thinking out loud",
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Lead thinking out loud"},
                        ]
                    },
                },
            ),
        ]
        created, mock_session, _, _ = self._run_bridge(events)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].content, "Lead thinking out loud")
        self.assertEqual(created[0].sender_agent_id, "agent-lead")

    def test_task_delegation_sets_subagent_activity(self):
        events = [
            TeamEvent(
                kind="assistant",
                content="",
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu-1",
                                "name": "Task",
                                "input": {"name": "researcher"},
                            },
                        ]
                    },
                },
            ),
        ]
        _, _, mock_set, _ = self._run_bridge(events)

        mock_set.assert_called_once_with(
            "conv-1", "agent-researcher", "researcher", "composing", "team",
        )

    def test_tool_result_posted_as_subagent_message(self):
        events = [
            # Lead delegates to researcher via Task
            TeamEvent(
                kind="assistant",
                content="",
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu-1",
                                "name": "Task",
                                "input": {"name": "researcher"},
                            },
                        ]
                    },
                },
            ),
            # Researcher responds
            TeamEvent(
                kind="tool_result",
                content="Research findings here",
                raw={
                    "type": "tool_result",
                    "tool_use_id": "tu-1",
                    "content": "Research findings here",
                },
            ),
        ]
        created, _, _, mock_clear = self._run_bridge(events)

        # Should have one message from the researcher.
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].content, "Research findings here")
        self.assertEqual(created[0].sender_agent_id, "agent-researcher")

        # Sub-agent activity should be cleared.
        mock_clear.assert_called_once_with("conv-1", "agent-researcher")

    def test_standalone_tool_use_tracks_task_delegation(self):
        """Standalone tool_use events (not inside assistant) also track Task."""
        events = [
            # Standalone tool_use for Task
            TeamEvent(
                kind="tool_use",
                tool_name="Task",
                content=json.dumps({"name": "researcher", "prompt": "Do research"}),
                raw={
                    "type": "tool_use",
                    "id": "tu-standalone",
                    "name": "Task",
                    "input": {"name": "researcher", "prompt": "Do research"},
                },
            ),
            # Researcher responds
            TeamEvent(
                kind="tool_result",
                content="Standalone research result",
                raw={
                    "type": "tool_result",
                    "tool_use_id": "tu-standalone",
                    "content": "Standalone research result",
                },
            ),
        ]
        created, _, mock_set, mock_clear = self._run_bridge(events)

        # Sub-agent activity was set then cleared.
        mock_set.assert_called_once_with(
            "conv-1", "agent-researcher", "researcher", "composing", "team",
        )
        mock_clear.assert_called_once_with("conv-1", "agent-researcher")

        # Message from researcher was stored.
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].sender_agent_id, "agent-researcher")
        self.assertEqual(created[0].content, "Standalone research result")

    def test_tool_use_only_assistant_still_tracks_task(self):
        """Assistant event with ONLY tool_use blocks (no text) still tracks Task."""
        events = [
            # Assistant with only a Task tool_use block, no text
            TeamEvent(
                kind="assistant",
                content="",  # no text
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu-2",
                                "name": "Task",
                                "input": {"name": "researcher"},
                            },
                        ]
                    },
                },
            ),
            # Researcher responds
            TeamEvent(
                kind="tool_result",
                content="Got it",
                raw={
                    "type": "tool_result",
                    "tool_use_id": "tu-2",
                    "content": "Got it",
                },
            ),
        ]
        created, _, mock_set, _ = self._run_bridge(events)

        # Activity was set for researcher.
        mock_set.assert_called_once()

        # Researcher message was posted.
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].sender_agent_id, "agent-researcher")

    def test_result_event_posted_as_lead_final(self):
        events = [
            TeamEvent(
                kind="result",
                content="Final summary from the lead",
                raw={"type": "result", "result": "Final summary from the lead"},
            ),
        ]
        created, _, _, _ = self._run_bridge(events)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].content, "Final summary from the lead")
        self.assertEqual(created[0].sender_agent_id, "agent-lead")

    def test_duplicate_content_not_posted_twice(self):
        """If result text matches already-posted lead text, skip it."""
        events = [
            TeamEvent(
                kind="assistant",
                content="Same text",
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "Same text"}]
                    },
                },
            ),
            TeamEvent(
                kind="result",
                content="Same text",
                raw={"type": "result", "result": "Same text"},
            ),
        ]
        created, _, _, _ = self._run_bridge(events)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].content, "Same text")

    def test_error_event_returns_system_message(self):
        events = [
            TeamEvent(kind="error", content="Something went wrong", raw={}),
        ]
        created, _, _, _ = self._run_bridge(events)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].sender_type, "system")
        self.assertIn("Something went wrong", created[0].content)

    def test_full_sequence_lead_delegate_respond(self):
        """End-to-end: lead text -> delegation -> sub-agent response -> result."""
        events = [
            # Lead says something and delegates
            TeamEvent(
                kind="assistant",
                content="",
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Let me delegate this."},
                            {
                                "type": "tool_use",
                                "id": "tu-1",
                                "name": "Task",
                                "input": {"name": "researcher"},
                            },
                        ]
                    },
                },
            ),
            # Researcher responds
            TeamEvent(
                kind="tool_result",
                content="Here are my findings.",
                raw={
                    "type": "tool_result",
                    "tool_use_id": "tu-1",
                    "content": "Here are my findings.",
                },
            ),
            # Lead wraps up
            TeamEvent(
                kind="result",
                content="Based on the research, here is the answer.",
                raw={
                    "type": "result",
                    "result": "Based on the research, here is the answer.",
                },
            ),
        ]
        created, _, mock_set, mock_clear = self._run_bridge(events)

        self.assertEqual(len(created), 3)

        # First: lead's delegation text
        self.assertEqual(created[0].sender_agent_id, "agent-lead")
        self.assertEqual(created[0].content, "Let me delegate this.")

        # Second: researcher's response
        self.assertEqual(created[1].sender_agent_id, "agent-researcher")
        self.assertEqual(created[1].content, "Here are my findings.")

        # Third: lead's final summary
        self.assertEqual(created[2].sender_agent_id, "agent-lead")
        self.assertIn("Based on the research", created[2].content)

        # Activity was set for researcher, then cleared.
        mock_set.assert_called_once_with(
            "conv-1", "agent-researcher", "researcher", "composing", "team",
        )
        mock_clear.assert_called_once_with("conv-1", "agent-researcher")

    def test_intermediate_subagent_assistant_suppressed(self):
        """Sub-agent assistant events during Task execution are suppressed.

        Without this, the sub-agent's text leaks in as a lead message,
        then the tool_result (with correct attribution) is deduplicated
        away — sub-agent response appears under the lead's name or vanishes.
        """
        events = [
            # Lead delegates to researcher
            TeamEvent(
                kind="assistant",
                content="",
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Delegating to researcher."},
                            {
                                "type": "tool_use",
                                "id": "tu-1",
                                "name": "Task",
                                "input": {"name": "researcher"},
                            },
                        ]
                    },
                },
            ),
            # Sub-agent's intermediate assistant event leaks into stream
            TeamEvent(
                kind="assistant",
                content="Research findings from sub-agent",
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Research findings from sub-agent"},
                        ]
                    },
                },
            ),
            # The actual tool_result with correct attribution
            TeamEvent(
                kind="tool_result",
                content="Research findings from sub-agent",
                raw={
                    "type": "tool_result",
                    "tool_use_id": "tu-1",
                    "content": "Research findings from sub-agent",
                },
            ),
        ]
        created, _, _, _ = self._run_bridge(events)

        # Lead's delegation text + researcher's response (from tool_result).
        # The intermediate assistant event must NOT appear as a lead message.
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].sender_agent_id, "agent-lead")
        self.assertEqual(created[0].content, "Delegating to researcher.")
        self.assertEqual(created[1].sender_agent_id, "agent-researcher")
        self.assertEqual(created[1].content, "Research findings from sub-agent")

    def test_lead_text_after_delegation_resolves_posted(self):
        """After all pending tasks resolve, lead text is posted again."""
        events = [
            # Lead delegates
            TeamEvent(
                kind="assistant",
                content="",
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu-1",
                                "name": "Task",
                                "input": {"name": "researcher"},
                            },
                        ]
                    },
                },
            ),
            # Researcher responds — pending_tasks empties
            TeamEvent(
                kind="tool_result",
                content="Done.",
                raw={
                    "type": "tool_result",
                    "tool_use_id": "tu-1",
                    "content": "Done.",
                },
            ),
            # Lead speaks again (pending_tasks is now empty)
            TeamEvent(
                kind="assistant",
                content="Great, wrapping up.",
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Great, wrapping up."},
                        ]
                    },
                },
            ),
        ]
        created, _, _, _ = self._run_bridge(events)

        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].sender_agent_id, "agent-researcher")
        self.assertEqual(created[0].content, "Done.")
        # Lead text posted because pending_tasks is empty after tool_result.
        self.assertEqual(created[1].sender_agent_id, "agent-lead")
        self.assertEqual(created[1].content, "Great, wrapping up.")

    def test_non_task_tool_result_ignored(self):
        """tool_result events that don't match a pending Task are skipped."""
        events = [
            TeamEvent(
                kind="tool_result",
                content="Some Read result",
                raw={
                    "type": "tool_result",
                    "tool_use_id": "tu-unknown",
                    "content": "Some Read result",
                },
            ),
        ]
        created, _, _, _ = self._run_bridge(events)
        self.assertEqual(len(created), 0)

    def test_non_task_tool_use_ignored(self):
        """Standalone tool_use events for non-Task tools are ignored."""
        events = [
            TeamEvent(
                kind="tool_use",
                tool_name="Read",
                content=json.dumps({"file_path": "/tmp/foo"}),
                raw={
                    "type": "tool_use",
                    "id": "tu-read",
                    "name": "Read",
                    "input": {"file_path": "/tmp/foo"},
                },
            ),
        ]
        created, _, mock_set, _ = self._run_bridge(events)
        self.assertEqual(len(created), 0)
        mock_set.assert_not_called()


class TestInboxEventProcessing(unittest.TestCase):
    """Test inbox event handling in the bridge."""

    def _run_bridge(self, events: list[TeamEvent], team: TeamSession | None = None):
        """Helper: load events into queue, run bridge, return created messages."""
        if team is None:
            team = _make_team_session()

        for ev in events:
            team.event_queue.put(ev)
        team.event_queue.put(TeamEvent(kind="eof"))

        mock_session = MagicMock()
        mock_session.flush = MagicMock()

        conversation = _make_conversation()
        trigger = _make_trigger()

        with patch("teaparty_app.services.team_bridge.commit_with_retry"):
            with patch("teaparty_app.services.team_bridge._set_activity"):
                with patch("teaparty_app.services.team_bridge._clear_activity"):
                    from teaparty_app.services.team_bridge import process_team_events_sync
                    created = process_team_events_sync(
                        mock_session, team, conversation, trigger,
                    )

        return created

    def test_inbox_event_creates_message_with_recipient_prefix(self):
        events = [
            TeamEvent(
                kind="inbox",
                agent_slug="researcher",
                content="Here are my findings",
                raw={
                    "from": "researcher",
                    "recipient": "lead-agent",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "summary": "Research findings",
                },
            ),
        ]
        created = self._run_bridge(events)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].content, "@lead-agent Here are my findings")
        self.assertEqual(created[0].sender_agent_id, "agent-researcher")

    def test_inbox_message_already_posted_via_stream_is_skipped(self):
        """If stream delivered the same text first, inbox duplicate is skipped."""
        events = [
            # Stream delivers lead text first
            TeamEvent(
                kind="assistant",
                content="Same content",
                raw={
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "Same content"}]
                    },
                },
            ),
            # Inbox delivers same raw text
            TeamEvent(
                kind="inbox",
                agent_slug="lead-agent",
                content="Same content",
                raw={
                    "from": "lead-agent",
                    "recipient": "researcher",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "summary": "Same",
                },
            ),
        ]
        created = self._run_bridge(events)

        # Only the stream version should appear
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].content, "Same content")

    def test_inbox_message_adds_text_to_posted_texts_for_dedup(self):
        """Inbox message prevents stream from duplicating it later."""
        events = [
            # Inbox delivers first
            TeamEvent(
                kind="inbox",
                agent_slug="researcher",
                content="Unique inbox content",
                raw={
                    "from": "researcher",
                    "recipient": "lead-agent",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "summary": "Research",
                },
            ),
            # Result tries to deliver same raw text
            TeamEvent(
                kind="result",
                content="Unique inbox content",
                raw={"type": "result", "result": "Unique inbox content"},
            ),
        ]
        created = self._run_bridge(events)

        # Only inbox version should appear (result deduped)
        self.assertEqual(len(created), 1)
        self.assertIn("@lead-agent", created[0].content)

    def test_inbox_without_recipient_omits_prefix(self):
        events = [
            TeamEvent(
                kind="inbox",
                agent_slug="researcher",
                content="Broadcast message",
                raw={
                    "from": "researcher",
                    "recipient": "",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "summary": "Broadcast",
                },
            ),
        ]
        created = self._run_bridge(events)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].content, "Broadcast message")

    def test_inbox_empty_content_skipped(self):
        events = [
            TeamEvent(
                kind="inbox",
                agent_slug="researcher",
                content="   ",
                raw={
                    "from": "researcher",
                    "recipient": "lead-agent",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "summary": "",
                },
            ),
        ]
        created = self._run_bridge(events)
        self.assertEqual(len(created), 0)


class TestParseEventAssistantWithToolUseOnly(unittest.TestCase):
    """Verify _parse_event emits assistant events even with no text blocks."""

    def test_assistant_with_only_tool_use_blocks_emits_event(self):
        session = TeamSession("conv-1")
        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu-1",
                        "name": "Task",
                        "input": {"name": "researcher"},
                    },
                ]
            },
        }
        event = session._parse_event(raw)
        self.assertIsNotNone(event, "assistant event with only tool_use blocks must not be dropped")
        self.assertEqual(event.kind, "assistant")
        self.assertEqual(event.content, "")  # no text, but event still exists
        # raw is preserved so bridge can extract tool_use blocks
        self.assertEqual(event.raw, raw)

    def test_assistant_with_text_and_tool_use_emits_event(self):
        session = TeamSession("conv-1")
        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "I'll delegate."},
                    {
                        "type": "tool_use",
                        "id": "tu-1",
                        "name": "Task",
                        "input": {"name": "researcher"},
                    },
                ]
            },
        }
        event = session._parse_event(raw)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "assistant")
        self.assertIn("I'll delegate.", event.content)


if __name__ == "__main__":
    unittest.main()
