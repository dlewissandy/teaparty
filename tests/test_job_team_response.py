import json
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

from teaparty_app.models import Agent, Conversation, Message, Workgroup
from teaparty_app.services.agent_runtime import _run_job_team_response
from teaparty_app.services.claude_runner import ClaudeResult


def _make_agent(*, agent_id: str, name: str, role: str = "", model: str = "sonnet") -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        role=role,
        model=model,
        tool_names=[],
    )


def _make_conversation(*, conversation_id: str = "conv-1", kind: str = "job") -> Conversation:
    return Conversation(
        id=conversation_id,
        workgroup_id="wg-1",
        kind=kind,
    )


def _make_trigger(*, message_id: str = "msg-1") -> Message:
    return Message(
        id=message_id,
        conversation_id="conv-1",
        sender_type="user",
        sender_user_id="user-1",
        content="What should we do?",
    )


def _make_result(*, text: str = "", events: list[dict] | None = None, is_error: bool = False, error: str | None = None) -> ClaudeResult:
    return ClaudeResult(
        text=text,
        events=events or [],
        is_error=is_error,
        error=error,
        model="sonnet",
        input_tokens=100,
        output_tokens=50,
        duration_ms=1000,
    )


class JobTeamResponseTests(unittest.TestCase):
    """Integration tests for _run_job_team_response."""

    def _setup_mocks(self):
        """Common mock setup for session and workgroup."""
        session = MagicMock()
        session.get.return_value = Workgroup(id="wg-1", name="Test", owner_user_id="user-1")
        return session

    @patch("teaparty_app.services.agent_runtime.commit_with_retry")
    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="User says: What should we do?")
    @patch("teaparty_app.services.agent_runtime.build_workgroup_files_context", return_value="")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_events_with_task_delegation_creates_attributed_messages(
        self, mock_run, mock_files, mock_user_msg, mock_usage, mock_commit
    ) -> None:
        """Verbose events with Task tool_use/result produce per-agent Messages."""
        mock_run.return_value = _make_result(
            text="Done",
            events=[
                {"type": "assistant", "message": {"content": [
                    {"type": "text", "text": "Delegating to the team."},
                    {"type": "tool_use", "id": "tu-1", "name": "Task", "input": {"name": "bob"}},
                ]}},
                {"type": "tool_result", "tool_use_id": "tu-1", "content": "Bob's analysis."},
                {"type": "result", "result": "Done", "usage": {}},
            ],
        )

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice", role="Lead")
        bob = _make_agent(agent_id="a2", name="Bob", role="Analyst")

        messages = _run_job_team_response(session, conv, trigger, [alice, bob])

        # Should have 2 messages: lead text + Bob's contribution.
        self.assertEqual(len(messages), 2)

        # First: lead text (attributed to Alice since agent_id is None -> lead fallback).
        self.assertEqual(messages[0].sender_agent_id, "a1")
        self.assertIn("Delegating", messages[0].content)

        # Second: Bob's contribution.
        self.assertEqual(messages[1].sender_agent_id, "a2")
        self.assertIn("Bob's analysis", messages[1].content)

    @patch("teaparty_app.services.agent_runtime.commit_with_retry")
    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="msg")
    @patch("teaparty_app.services.agent_runtime.build_workgroup_files_context", return_value="")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_text_fallback_when_no_task_events(
        self, mock_run, mock_files, mock_user_msg, mock_usage, mock_commit
    ) -> None:
        """When events have no Task tool_use, falls back to text-based unpacking."""
        mock_run.return_value = _make_result(
            text="**Alice**: My analysis.\n\n**Bob**: My review.",
            events=[
                {"type": "assistant", "message": {"content": [
                    {"type": "text", "text": "**Alice**: My analysis.\n\n**Bob**: My review."},
                ]}},
                {"type": "result", "result": "**Alice**: My analysis.\n\n**Bob**: My review.", "usage": {}},
            ],
        )

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice")
        bob = _make_agent(agent_id="a2", name="Bob")

        messages = _run_job_team_response(session, conv, trigger, [alice, bob])

        # Event parsing returns lead text (the full text). Text fallback should split it.
        # The exact count depends on parsing — at minimum we get messages.
        self.assertGreaterEqual(len(messages), 1)
        # All messages should be attributed to known agents.
        for msg in messages:
            self.assertIn(msg.sender_agent_id, ["a1", "a2"])

    @patch("teaparty_app.services.agent_runtime.commit_with_retry")
    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="msg")
    @patch("teaparty_app.services.agent_runtime.build_workgroup_files_context", return_value="")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_lead_attribution_fallback(
        self, mock_run, mock_files, mock_user_msg, mock_usage, mock_commit
    ) -> None:
        """When nothing parses, full text goes to lead agent."""
        mock_run.return_value = _make_result(
            text="A plain response with no structure.",
            events=[],
        )

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice")
        bob = _make_agent(agent_id="a2", name="Bob")

        messages = _run_job_team_response(session, conv, trigger, [alice, bob])

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].sender_agent_id, "a1")
        self.assertIn("plain response", messages[0].content)

    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="msg")
    @patch("teaparty_app.services.agent_runtime.build_workgroup_files_context", return_value="")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_error_result_creates_error_message(
        self, mock_run, mock_files, mock_user_msg, mock_usage
    ) -> None:
        """CLI error produces an error message attributed to lead."""
        mock_run.return_value = _make_result(
            is_error=True,
            error="CLI crashed",
        )

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice")

        messages = _run_job_team_response(session, conv, trigger, [alice])

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].sender_agent_id, "a1")
        self.assertIn("Agent error", messages[0].content)

    @patch("teaparty_app.services.agent_runtime.commit_with_retry")
    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="msg")
    @patch("teaparty_app.services.agent_runtime.build_workgroup_files_context", return_value="")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_single_agent_job_works(
        self, mock_run, mock_files, mock_user_msg, mock_usage, mock_commit
    ) -> None:
        """Single-agent jobs go through the team path and produce a message."""
        mock_run.return_value = _make_result(
            text="Solo agent response.",
            events=[],
        )

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice")

        messages = _run_job_team_response(session, conv, trigger, [alice])

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].sender_agent_id, "a1")
        self.assertEqual(messages[0].content, "Solo agent response.")


if __name__ == "__main__":
    unittest.main()
