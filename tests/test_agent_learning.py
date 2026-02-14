"""Tests for the agent learning service."""

import json
import unittest
from unittest.mock import MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine

from teaparty_app.models import (
    Agent,
    AgentLearningEvent,
    AgentMemory,
    Conversation,
    Message,
    User,
    Workgroup,
    new_id,
)
from teaparty_app.services.agent_learning import (
    apply_short_term_learning,
    get_agent_memory_context,
    is_learning_eligible,
    synthesize_long_term_memories,
)


def _make_conversation(
    *,
    kind: str = "topic",
    topic: str = "general",
    workgroup_id: str = "wg-1",
) -> Conversation:
    return Conversation(
        id=new_id(),
        workgroup_id=workgroup_id,
        created_by_user_id="user-1",
        kind=kind,
        topic=topic,
        name=topic,
    )


def _make_agent(*, agent_id: str = "", workgroup_id: str = "wg-1", name: str = "Alice") -> Agent:
    return Agent(
        id=agent_id or new_id(),
        workgroup_id=workgroup_id,
        created_by_user_id="user-1",
        name=name,
        personality="Professional and concise",
        learning_state={},
        sentiment_state={},
        learned_preferences={},
        tool_names=[],
    )


def _make_message(
    *,
    conversation_id: str,
    sender_type: str = "user",
    sender_user_id: str | None = "user-1",
    sender_agent_id: str | None = None,
    content: str = "Hello",
) -> Message:
    return Message(
        id=new_id(),
        conversation_id=conversation_id,
        sender_type=sender_type,
        sender_user_id=sender_user_id,
        sender_agent_id=sender_agent_id,
        content=content,
        requires_response=False,
    )


# ---------------------------------------------------------------------------
# Pure unit tests (no DB)
# ---------------------------------------------------------------------------


class TestIsLearningEligible(unittest.TestCase):
    def test_topic_conversation_is_eligible(self) -> None:
        conv = _make_conversation(kind="topic", topic="general")
        self.assertTrue(is_learning_eligible(conv))

    def test_direct_conversation_is_eligible(self) -> None:
        conv = _make_conversation(kind="direct", topic="dm:user-1:user-2")
        self.assertTrue(is_learning_eligible(conv))

    def test_task_conversation_is_not_eligible(self) -> None:
        conv = _make_conversation(kind="topic", topic="task:abc-123")
        self.assertFalse(is_learning_eligible(conv))

    def test_task_mirror_is_not_eligible(self) -> None:
        conv = _make_conversation(kind="topic", topic="task-mirror:abc-123")
        self.assertFalse(is_learning_eligible(conv))

    def test_activity_is_not_eligible(self) -> None:
        conv = _make_conversation(kind="activity", topic="activity")
        self.assertFalse(is_learning_eligible(conv))

    def test_admin_is_not_eligible(self) -> None:
        conv = _make_conversation(kind="admin", topic="admin")
        self.assertFalse(is_learning_eligible(conv))


# ---------------------------------------------------------------------------
# DB-backed tests
# ---------------------------------------------------------------------------


def _create_test_engine():
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    return engine


class TestApplyShortTermLearning(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _create_test_engine()

    def test_skips_cross_group_conversations(self) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            agent = _make_agent(agent_id="agent-1")
            session.add(agent)
            conv = _make_conversation(kind="topic", topic="task:abc-123")
            session.add(conv)
            trigger = _make_message(conversation_id=conv.id, content="Tell me about the project")
            session.add(trigger)
            reply = _make_message(
                conversation_id=conv.id,
                sender_type="agent",
                sender_user_id=None,
                sender_agent_id=agent.id,
                content="The project is going well",
            )
            session.add(reply)
            session.commit()

            apply_short_term_learning(session, agent, conv, trigger, reply)
            session.commit()

            events = session.exec(
                AgentLearningEvent.__table__.select()
            ).all()
            self.assertEqual(len(events), 0)

    def test_creates_topic_expertise_event(self) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            agent = _make_agent(agent_id="agent-1")
            session.add(agent)
            conv = _make_conversation(kind="topic", topic="machine-learning")
            session.add(conv)
            trigger = _make_message(
                conversation_id=conv.id,
                content="What about neural network architectures?",
            )
            session.add(trigger)
            reply = _make_message(
                conversation_id=conv.id,
                sender_type="agent",
                sender_user_id=None,
                sender_agent_id=agent.id,
                content="Transformer architectures have revolutionized the field",
            )
            session.add(reply)
            session.commit()

            apply_short_term_learning(session, agent, conv, trigger, reply)
            session.commit()

            from sqlmodel import select

            events = session.exec(
                select(AgentLearningEvent).where(
                    AgentLearningEvent.agent_id == agent.id,
                    AgentLearningEvent.signal_type == "topic_expertise",
                )
            ).all()
            self.assertGreaterEqual(len(events), 1)
            value = events[0].value
            self.assertIn("domain_tokens", value)
            self.assertIn("machine-learning", value["topic"])

    def test_creates_collaboration_event_for_agent_trigger(self) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            agent_a = _make_agent(agent_id="agent-a", name="Alice")
            agent_b = _make_agent(agent_id="agent-b", name="Bob")
            session.add(agent_a)
            session.add(agent_b)
            conv = _make_conversation(kind="topic", topic="design")
            session.add(conv)
            trigger = _make_message(
                conversation_id=conv.id,
                sender_type="agent",
                sender_user_id=None,
                sender_agent_id=agent_a.id,
                content="We should use microservices for better scalability",
            )
            session.add(trigger)
            reply = _make_message(
                conversation_id=conv.id,
                sender_type="agent",
                sender_user_id=None,
                sender_agent_id=agent_b.id,
                content="I agree about scalability but monolith might be simpler initially",
            )
            session.add(reply)
            session.commit()

            apply_short_term_learning(session, agent_b, conv, trigger, reply)
            session.commit()

            from sqlmodel import select

            events = session.exec(
                select(AgentLearningEvent).where(
                    AgentLearningEvent.agent_id == agent_b.id,
                    AgentLearningEvent.signal_type == "collaboration",
                )
            ).all()
            self.assertEqual(len(events), 1)
            value = events[0].value
            self.assertIn("overlap_ratio", value)
            self.assertIn("is_complementary", value)
            self.assertEqual(value["trigger_agent_id"], agent_a.id)


class TestGetAgentMemoryContext(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _create_test_engine()

    def test_empty_with_no_memories(self) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            agent = _make_agent(agent_id="agent-1")
            session.add(agent)
            session.commit()

            result = get_agent_memory_context(session, agent)
            self.assertEqual(result, "")

    def test_formats_memories_correctly(self) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            agent = _make_agent(agent_id="agent-1")
            session.add(agent)
            conv = _make_conversation()
            session.add(conv)
            session.add(
                AgentMemory(
                    agent_id=agent.id,
                    conversation_id=conv.id,
                    memory_type="insight",
                    content="Users prefer concise answers",
                    confidence=0.9,
                )
            )
            session.add(
                AgentMemory(
                    agent_id=agent.id,
                    conversation_id=conv.id,
                    memory_type="correction",
                    content="API endpoints use snake_case",
                    confidence=0.8,
                )
            )
            session.commit()

            result = get_agent_memory_context(session, agent)
            self.assertIn("Long-term memories from past conversations:", result)
            self.assertIn("[insight] Users prefer concise answers", result)
            self.assertIn("[correction] API endpoints use snake_case", result)

    def test_respects_max_chars(self) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            agent = _make_agent(agent_id="agent-1")
            session.add(agent)
            conv = _make_conversation()
            session.add(conv)
            for i in range(20):
                session.add(
                    AgentMemory(
                        agent_id=agent.id,
                        conversation_id=conv.id,
                        memory_type="insight",
                        content=f"Memory number {i} with some padding text to make it longer " * 3,
                        confidence=0.9,
                    )
                )
            session.commit()

            result = get_agent_memory_context(session, agent, max_chars=200)
            # Should be truncated to stay within max_chars
            body = result.split("\n", 1)[1] if "\n" in result else result
            self.assertLessEqual(len(body), 250)  # Allow some slack for header


class TestSynthesizeLongTermMemories(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _create_test_engine()

    def test_skips_cross_group_conversation(self) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            conv = _make_conversation(kind="topic", topic="task:abc-123")
            session.add(conv)
            session.commit()

            result = synthesize_long_term_memories(session, conv)
            self.assertEqual(result, {})

    def test_skips_short_conversation(self) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            conv = _make_conversation(kind="topic", topic="short-topic")
            session.add(conv)
            # Only 2 messages
            session.add(_make_message(conversation_id=conv.id, content="Hello"))
            session.add(_make_message(conversation_id=conv.id, content="Hi"))
            session.commit()

            result = synthesize_long_term_memories(session, conv)
            self.assertEqual(result, {})

    @patch("teaparty_app.services.agent_learning._get_anthropic_client")
    def test_creates_memories_from_valid_llm_response(self, mock_client_factory: MagicMock) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            agent = _make_agent(agent_id="agent-1")
            session.add(agent)
            conv = _make_conversation(kind="topic", topic="architecture")
            session.add(conv)

            for i in range(5):
                sender_type = "user" if i % 2 == 0 else "agent"
                session.add(
                    _make_message(
                        conversation_id=conv.id,
                        sender_type=sender_type,
                        sender_user_id="user-1" if sender_type == "user" else None,
                        sender_agent_id=agent.id if sender_type == "agent" else None,
                        content=f"Message {i} about architecture decisions",
                    )
                )
            session.commit()

            llm_response_json = json.dumps({
                agent.id: [
                    {"type": "insight", "content": "Microservices preferred for this project", "source": "architecture discussion", "confidence": 0.85},
                    {"type": "domain_knowledge", "content": "Team uses event-driven patterns", "source": "architecture discussion", "confidence": 0.75},
                ]
            })

            mock_response = MagicMock()
            mock_response.content = [MagicMock(text=llm_response_json)]
            mock_response.usage.input_tokens = 100
            mock_response.usage.output_tokens = 50

            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_client_factory.return_value = mock_client

            result = synthesize_long_term_memories(session, conv)
            session.commit()

            self.assertIn(agent.id, result)
            self.assertEqual(result[agent.id], 2)

            from sqlmodel import select

            memories = session.exec(
                select(AgentMemory).where(AgentMemory.agent_id == agent.id)
            ).all()
            self.assertEqual(len(memories), 2)
            types = {m.memory_type for m in memories}
            self.assertIn("insight", types)
            self.assertIn("domain_knowledge", types)

    @patch("teaparty_app.services.agent_learning._get_anthropic_client")
    def test_handles_llm_failure_gracefully(self, mock_client_factory: MagicMock) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            agent = _make_agent(agent_id="agent-1")
            session.add(agent)
            conv = _make_conversation(kind="topic", topic="test-topic")
            session.add(conv)
            for i in range(4):
                sender_type = "user" if i % 2 == 0 else "agent"
                session.add(
                    _make_message(
                        conversation_id=conv.id,
                        sender_type=sender_type,
                        sender_user_id="user-1" if sender_type == "user" else None,
                        sender_agent_id=agent.id if sender_type == "agent" else None,
                        content=f"Message {i}",
                    )
                )
            session.commit()

            mock_client = MagicMock()
            mock_client.messages.create.side_effect = Exception("API error")
            mock_client_factory.return_value = mock_client

            result = synthesize_long_term_memories(session, conv)
            self.assertEqual(result, {})

    @patch("teaparty_app.services.agent_learning._get_anthropic_client")
    def test_enforces_five_per_agent_cap(self, mock_client_factory: MagicMock) -> None:
        with Session(self.engine) as session:
            wg = Workgroup(id="wg-1", name="Test WG", owner_id="user-1")
            session.add(wg)
            user = User(id="user-1", email="test@example.com")
            session.add(user)
            agent = _make_agent(agent_id="agent-1")
            session.add(agent)
            conv = _make_conversation(kind="topic", topic="big-topic")
            session.add(conv)
            for i in range(5):
                sender_type = "user" if i % 2 == 0 else "agent"
                session.add(
                    _make_message(
                        conversation_id=conv.id,
                        sender_type=sender_type,
                        sender_user_id="user-1" if sender_type == "user" else None,
                        sender_agent_id=agent.id if sender_type == "agent" else None,
                        content=f"Message {i}",
                    )
                )
            session.commit()

            # LLM returns 8 memories — should be capped at 5
            llm_response_json = json.dumps({
                agent.id: [
                    {"type": "insight", "content": f"Memory {i}", "source": "test", "confidence": 0.8}
                    for i in range(8)
                ]
            })

            mock_response = MagicMock()
            mock_response.content = [MagicMock(text=llm_response_json)]
            mock_response.usage.input_tokens = 100
            mock_response.usage.output_tokens = 50

            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_client_factory.return_value = mock_client

            result = synthesize_long_term_memories(session, conv)
            session.commit()

            self.assertEqual(result[agent.id], 5)

            from sqlmodel import select

            memories = session.exec(
                select(AgentMemory).where(AgentMemory.agent_id == agent.id)
            ).all()
            self.assertEqual(len(memories), 5)


if __name__ == "__main__":
    unittest.main()
