import unittest
from unittest.mock import MagicMock, patch

from teaparty_app.config import settings
from teaparty_app.models import Agent, AgentLearningEvent, Conversation, Message
from teaparty_app.services.agent_runtime import (
    _extract_json_object,
    infer_requires_response,
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


class AgentRuntimeHelperTests(unittest.TestCase):
    def test_infer_requires_response_detects_question_like_content(self) -> None:
        self.assertTrue(infer_requires_response("Can you summarize this thread"))
        self.assertTrue(infer_requires_response("Status update?"))
        self.assertFalse(infer_requires_response("Posted the update in the doc."))

    def test_extract_json_object_handles_fenced_and_embedded_json(self) -> None:
        self.assertEqual(_extract_json_object("```json\n{\"a\":1}\n```"), {"a": 1})
        self.assertEqual(_extract_json_object("prefix {\"b\":2} suffix"), {"b": 2})
        self.assertIsNone(_extract_json_object("not json"))

