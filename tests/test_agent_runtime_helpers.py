import unittest
from unittest.mock import MagicMock, patch

from teaparty_app.config import settings
from teaparty_app.models import Agent, AgentLearningEvent, Conversation, Message, Workgroup
from teaparty_app.services.agent_runtime import (
    _extract_json_object,
    _is_resumable_conversation,
    infer_requires_response,
    run_agent_auto_responses,
)


def _make_agent(
    *,
    agent_id: str,
    name: str,
    tool_names: list[str] | None = None,
    personality: str = "Professional and concise",
    role: str = "",
    backstory: str = "",
    verbosity: float = 0.5,
    learning_state: dict[str, float] | None = None,
    response_threshold: float = 0.55,
) -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        personality=personality,
        role=role,
        backstory=backstory,
        tool_names=tool_names or [],
        verbosity=verbosity,
        learning_state=learning_state or {},
        response_threshold=response_threshold,
    )


def _make_conversation(*, conversation_id: str = "conv-1", topic: str = "Test topic", kind: str = "job") -> Conversation:
    return Conversation(
        id=conversation_id,
        workgroup_id="wg-1",
        topic=topic,
        kind=kind,
    )


def _make_message(*, message_id: str = "msg-1", content: str = "Hello", sender_type: str = "user", sender_agent_id: str | None = None) -> Message:
    return Message(
        id=message_id,
        conversation_id="conv-1",
        sender_type=sender_type,
        content=content,
        sender_agent_id=sender_agent_id,
    )


class IsResumableConversationTests(unittest.TestCase):
    def test_task_conversation_is_resumable(self) -> None:
        conv = _make_conversation(kind="task")
        self.assertTrue(_is_resumable_conversation(conv))

    def test_direct_dma_conversation_is_resumable(self) -> None:
        conv = _make_conversation(kind="direct", topic="dma:agent-1")
        self.assertTrue(_is_resumable_conversation(conv))

    def test_job_conversation_is_not_resumable(self) -> None:
        conv = _make_conversation(kind="job")
        self.assertFalse(_is_resumable_conversation(conv))

    def test_direct_user_dm_is_not_resumable(self) -> None:
        conv = _make_conversation(kind="direct", topic="dm:user1:user2")
        self.assertFalse(_is_resumable_conversation(conv))

    def test_admin_conversation_is_not_resumable(self) -> None:
        conv = _make_conversation(kind="admin")
        self.assertFalse(_is_resumable_conversation(conv))

    def test_engagement_conversation_is_not_resumable(self) -> None:
        conv = _make_conversation(kind="engagement")
        self.assertFalse(_is_resumable_conversation(conv))


class AgentRuntimeHelperTests(unittest.TestCase):
    def test_infer_requires_response_detects_question_like_content(self) -> None:
        self.assertTrue(infer_requires_response("Can you summarize this thread"))
        self.assertTrue(infer_requires_response("Status update?"))
        self.assertFalse(infer_requires_response("Posted the update in the doc."))

    def test_extract_json_object_handles_fenced_and_embedded_json(self) -> None:
        self.assertEqual(_extract_json_object("```json\n{\"a\":1}\n```"), {"a": 1})
        self.assertEqual(_extract_json_object("prefix {\"b\":2} suffix"), {"b": 2})
        self.assertIsNone(_extract_json_object("not json"))


class JobRoutingTests(unittest.TestCase):
    """Full routing matrix for run_agent_auto_responses:
    - Job + @mention -> single named agent (_run_single_agent_responses)
    - Job + no @-mention, multiple agents -> team mode (_run_job_team_response)
    - Job + no @-mention, single agent -> single-agent (_run_single_agent_responses)
    - Job + @each -> fan-out (_run_single_agent_responses)
    - Job + agent sender -> no response (prevents re-triggering loops)
    - Direct/engagement -> single agent (_run_single_agent_responses)"""

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_job_at_all_routes_to_team(self, mock_agents, mock_single, mock_team) -> None:
        """@all with multiple agents uses the team path (via default routing)."""
        mock_agents.return_value = [
            _make_agent(agent_id="a1", name="Alice"),
            _make_agent(agent_id="a2", name="Bob"),
        ]
        mock_team.return_value = []

        session = MagicMock()
        conv = _make_conversation(kind="job")
        conv.is_archived = False
        trigger = _make_message(content="@all what does everyone think?")

        run_agent_auto_responses(session, conv, trigger)

        mock_team.assert_called_once()
        mock_single.assert_not_called()

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_direct_conversation_routes_to_single(self, mock_agents, mock_single, mock_team) -> None:
        """Direct conversations always use single-agent responses, never the team path."""
        mock_agents.return_value = [_make_agent(agent_id="a1", name="Alice")]
        mock_single.return_value = []

        session = MagicMock()
        conv = _make_conversation(kind="direct")
        conv.is_archived = False
        trigger = _make_message()

        run_agent_auto_responses(session, conv, trigger)

        mock_single.assert_called_once()
        mock_team.assert_not_called()

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_job_at_all_multi_agent_routes_to_team(self, mock_agents, mock_single, mock_team) -> None:
        """@all with multiple agents uses the multi-agent team path — all
        agents included in a single claude invocation, not separate ones."""
        mock_agents.return_value = [
            _make_agent(agent_id="a1", name="Alice"),
            _make_agent(agent_id="a2", name="Bob"),
        ]
        mock_team.return_value = []

        session = MagicMock()
        conv = _make_conversation(kind="job")
        conv.is_archived = False
        trigger = _make_message(content="@all let's discuss this")

        run_agent_auto_responses(session, conv, trigger)

        mock_team.assert_called_once()
        mock_single.assert_not_called()

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_job_no_mention_multi_agent_routes_to_team(self, mock_agents, mock_single, mock_team) -> None:
        """Job messages without @mention default to team mode when multiple
        agents are present."""
        mock_agents.return_value = [
            _make_agent(agent_id="a1", name="Alice"),
            _make_agent(agent_id="a2", name="Bob"),
        ]
        mock_team.return_value = []

        session = MagicMock()
        conv = _make_conversation(kind="job")
        conv.is_archived = False
        trigger = _make_message(content="What's the status?")

        run_agent_auto_responses(session, conv, trigger)

        mock_team.assert_called_once()
        mock_single.assert_not_called()

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_job_no_mention_single_agent_routes_to_single(self, mock_agents, mock_single, mock_team) -> None:
        """Job messages with only one agent route to single-agent path."""
        mock_agents.return_value = [
            _make_agent(agent_id="a1", name="Alice"),
        ]
        mock_single.return_value = []

        session = MagicMock()
        conv = _make_conversation(kind="job")
        conv.is_archived = False
        trigger = _make_message(content="What's the status?")

        run_agent_auto_responses(session, conv, trigger)

        mock_single.assert_called_once()
        mock_team.assert_not_called()

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_job_at_mention_routes_to_named_agent(self, mock_agents, mock_single, mock_team) -> None:
        """@AgentName routes to that specific agent only, via the single-agent path."""
        mock_agents.return_value = [
            _make_agent(agent_id="a1", name="Alice"),
            _make_agent(agent_id="a2", name="Bob"),
        ]
        mock_single.return_value = []

        session = MagicMock()
        conv = _make_conversation(kind="job")
        conv.is_archived = False
        trigger = _make_message(content="@Bob can you review this?")

        run_agent_auto_responses(session, conv, trigger)

        mock_single.assert_called_once()
        passed_candidates = mock_single.call_args[0][3]
        self.assertEqual(len(passed_candidates), 1)
        self.assertEqual(passed_candidates[0].name, "Bob")
        mock_team.assert_not_called()

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_agent_sender_produces_no_response(self, mock_agents, mock_single, mock_team) -> None:
        """Agent messages in job conversations produce no response — only user
        messages trigger agent responses.  This prevents infinite loops."""
        mock_agents.return_value = [_make_agent(agent_id="a1", name="Alice")]

        session = MagicMock()
        conv = _make_conversation(kind="job")
        conv.is_archived = False
        trigger = _make_message(sender_type="agent", sender_agent_id="a1")

        result = run_agent_auto_responses(session, conv, trigger)

        self.assertEqual(result, [])
        mock_team.assert_not_called()
        mock_single.assert_not_called()
