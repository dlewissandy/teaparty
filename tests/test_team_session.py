import json
import unittest
from unittest.mock import MagicMock

from teaparty_app.models import Agent, Workgroup
from teaparty_app.services.team_session import TeamEvent, TeamSession


def _make_agent(
    *,
    agent_id: str = "a1",
    name: str = "Implementer",
    model: str = "claude-sonnet-4-5",
    max_turns: int = 3,
) -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        role="Test agent",
        personality="Helpful",
        model=model,
        max_turns=max_turns,
        tool_names=[],
    )


def _make_workgroup(*, workgroup_id: str = "wg-1") -> Workgroup:
    return Workgroup(
        id=workgroup_id,
        name="Test Team",
        owner_id="user-1",
        files=[],
    )


class TeamEventParsingTests(unittest.TestCase):
    """Test parsing of stream-json events."""

    def setUp(self) -> None:
        self.session = TeamSession("conv-1")

    def test_parse_assistant_event(self) -> None:
        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Hello from the agent"}
                ]
            }
        }
        event = self.session._parse_event(raw)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "assistant")
        self.assertEqual(event.content, "Hello from the agent")

    def test_parse_text_delta_event(self) -> None:
        raw = {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "partial text"}
        }
        event = self.session._parse_event(raw)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "text_delta")
        self.assertEqual(event.content, "partial text")

    def test_parse_tool_use_event(self) -> None:
        raw = {
            "type": "tool_use",
            "name": "Read",
            "input": {"file_path": "/tmp/test.py"}
        }
        event = self.session._parse_event(raw)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "tool_use")
        self.assertEqual(event.tool_name, "Read")

    def test_parse_result_event(self) -> None:
        raw = {
            "type": "result",
            "result": "Task completed successfully",
            "session_id": "sess-abc",
        }
        event = self.session._parse_event(raw)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "result")
        self.assertEqual(event.content, "Task completed successfully")

    def test_parse_error_event(self) -> None:
        raw = {
            "type": "error",
            "error": {"message": "Something went wrong"}
        }
        event = self.session._parse_event(raw)
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "error")
        self.assertEqual(event.content, "Something went wrong")

    def test_parse_unknown_event_returns_none(self) -> None:
        raw = {"type": "unknown_type", "data": "stuff"}
        event = self.session._parse_event(raw)
        self.assertIsNone(event)

    def test_parse_assistant_multiple_text_blocks(self) -> None:
        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Part one"},
                    {"type": "text", "text": "Part two"},
                ]
            }
        }
        event = self.session._parse_event(raw)
        self.assertIsNotNone(event)
        self.assertIn("Part one", event.content)
        self.assertIn("Part two", event.content)

    def test_parse_assistant_empty_content(self) -> None:
        raw = {
            "type": "assistant",
            "message": {"content": []}
        }
        event = self.session._parse_event(raw)
        self.assertIsNone(event)


class TeamSessionAgentMappingTests(unittest.TestCase):
    """Test agent slug ↔ ID mapping."""

    def test_agent_id_lookup(self) -> None:
        session = TeamSession("conv-1")
        session._agent_slugs = {
            "implementer": "agent-123",
            "reviewer": "agent-456",
        }

        self.assertEqual(session.get_agent_id("implementer"), "agent-123")
        self.assertEqual(session.get_agent_id("reviewer"), "agent-456")
        self.assertIsNone(session.get_agent_id("unknown"))


class TeamSessionLifecycleTests(unittest.TestCase):
    """Test session start/stop lifecycle."""

    def test_stop_without_start(self) -> None:
        session = TeamSession("conv-1")
        # Should not raise
        session.stop()
        self.assertFalse(session.is_running)

    def test_stop_terminates_process(self) -> None:
        session = TeamSession("conv-1")
        session.is_running = True

        # Create a mock process
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = MagicMock()
        session.process = mock_proc

        session.stop()
        self.assertFalse(session.is_running)
        mock_proc.terminate.assert_called_once()
        self.assertIsNone(session.process)


class TeamRegistryTests(unittest.TestCase):
    """Test the session registry."""

    def test_get_session_returns_none_for_unknown(self) -> None:
        from teaparty_app.services.team_registry import get_session
        result = get_session("nonexistent-conv")
        self.assertIsNone(result)

    def test_active_session_count(self) -> None:
        from teaparty_app.services.team_registry import active_session_count
        # Should be 0 initially (or whatever state it's in)
        count = active_session_count()
        self.assertIsInstance(count, int)


if __name__ == "__main__":
    unittest.main()
