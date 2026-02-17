import unittest
from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from teaparty_app.models import Agent, Conversation, Message, User, Workgroup, new_id
from teaparty_app.services.prompt_builder import (
    build_system_prompt,
    build_user_message,
    build_workgroup_files_context,
)


def _make_agent(
    *,
    agent_id: str = "a1",
    name: str = "TestAgent",
    role: str = "Assistant",
    personality: str = "Helpful and concise",
    backstory: str = "",
) -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        role=role,
        personality=personality,
        backstory=backstory,
        tool_names=[],
    )


def _make_conversation(
    *,
    conversation_id: str = "conv-1",
    name: str = "general",
    description: str = "",
    kind: str = "job",
) -> Conversation:
    return Conversation(
        id=conversation_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        description=description,
        kind=kind,
    )


def _make_workgroup(*, workgroup_id: str = "wg-1", files: list | None = None) -> Workgroup:
    return Workgroup(
        id=workgroup_id,
        name="Test WG",
        owner_id="user-1",
        files=files or [],
    )


class BuildSystemPromptTests(unittest.TestCase):
    """Test system prompt construction."""

    def test_includes_agent_identity(self) -> None:
        agent = _make_agent(
            name="Alice",
            role="Code Reviewer",
            personality="Detail-oriented and thorough",
            backstory="Senior engineer with 10 years experience",
        )
        conversation = _make_conversation(kind="job")

        prompt = build_system_prompt(agent, conversation)

        self.assertIn("You are Alice", prompt)
        self.assertIn("Role: Code Reviewer", prompt)
        self.assertIn("Personality: Detail-oriented and thorough", prompt)
        self.assertIn("Backstory: Senior engineer with 10 years experience", prompt)

    def test_includes_conversation_context(self) -> None:
        agent = _make_agent(name="Bob")
        conversation = _make_conversation(
            kind="job",
            name="API Design",
            description="Discussing REST API patterns",
        )

        prompt = build_system_prompt(agent, conversation)

        self.assertIn("job discussion", prompt)
        self.assertIn("Job: API Design", prompt)
        self.assertIn("Description: Discussing REST API patterns", prompt)

    def test_direct_conversation_label(self) -> None:
        agent = _make_agent(name="Charlie")
        conversation = _make_conversation(kind="direct", name="general")

        prompt = build_system_prompt(agent, conversation)

        self.assertIn("direct conversation", prompt)
        self.assertNotIn("Job: general", prompt)

    def test_engagement_conversation_label(self) -> None:
        agent = _make_agent(name="Dave")
        conversation = _make_conversation(kind="engagement")

        prompt = build_system_prompt(agent, conversation)

        self.assertIn("engagement conversation", prompt)

    def test_includes_workgroup_files_context(self) -> None:
        agent = _make_agent(name="Frank")
        conversation = _make_conversation(kind="job")
        files_context = "Reference files:\n\n--- README.md ---\nProject overview"

        prompt = build_system_prompt(agent, conversation, workgroup_files_context=files_context)

        self.assertIn("Reference files", prompt)
        self.assertIn("README.md", prompt)

    def test_includes_guidelines(self) -> None:
        agent = _make_agent(name="Grace")
        conversation = _make_conversation(kind="job")

        prompt = build_system_prompt(agent, conversation)

        self.assertIn("Guidelines:", prompt)
        self.assertIn("Respond as this character", prompt)
        self.assertIn("Do not prefix your response with your name", prompt)

    def test_minimal_agent_without_optional_fields(self) -> None:
        agent = _make_agent(name="Henry", role="", personality="", backstory="")
        conversation = _make_conversation(kind="job")

        prompt = build_system_prompt(agent, conversation)

        self.assertIn("You are Henry", prompt)
        self.assertNotIn("Role:", prompt)
        self.assertNotIn("Personality:", prompt)
        self.assertNotIn("Backstory:", prompt)


class BuildUserMessageTests(unittest.TestCase):
    """Test user message construction from conversation history."""

    def setUp(self) -> None:
        # Create in-memory SQLite database
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()

    def test_formats_history_correctly(self) -> None:
        conversation = Conversation(
            id="conv-1",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            name="Test",
            kind="job",
        )
        self.session.add(conversation)

        user = User(id="user-1", email="alice@example.com", name="Alice")
        agent = Agent(
            id="agent-1",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            name="Bot",
            personality="Helpful",
            tool_names=[],
        )
        self.session.add(user)
        self.session.add(agent)

        msg1 = Message(
            id="msg-1",
            conversation_id="conv-1",
            sender_type="user",
            sender_user_id="user-1",
            content="Hello",
            created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
        msg2 = Message(
            id="msg-2",
            conversation_id="conv-1",
            sender_type="agent",
            sender_agent_id="agent-1",
            content="Hi there!",
            created_at=datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc),
        )
        trigger = Message(
            id="msg-3",
            conversation_id="conv-1",
            sender_type="user",
            sender_user_id="user-1",
            content="How are you?",
            created_at=datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc),
        )

        self.session.add(msg1)
        self.session.add(msg2)
        self.session.add(trigger)
        self.session.commit()

        user_message = build_user_message(self.session, conversation, trigger)

        self.assertIn("Conversation history", user_message)
        self.assertIn("user:Alice: Hello", user_message)
        self.assertIn("agent:Bot: Hi there!", user_message)
        self.assertIn("Latest message from user:Alice:", user_message)
        self.assertIn("How are you?", user_message)

    def test_respects_max_messages_limit(self) -> None:
        conversation = Conversation(
            id="conv-1",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            name="Test",
            kind="job",
        )
        self.session.add(conversation)

        user = User(id="user-1", email="alice@example.com", name="Alice")
        self.session.add(user)

        # Create 10 messages
        for i in range(10):
            msg = Message(
                id=f"msg-{i}",
                conversation_id="conv-1",
                sender_type="user",
                sender_user_id="user-1",
                content=f"Message {i}",
                created_at=datetime(2026, 1, 1, 12, i, tzinfo=timezone.utc),
            )
            self.session.add(msg)

        trigger = Message(
            id="msg-trigger",
            conversation_id="conv-1",
            sender_type="user",
            sender_user_id="user-1",
            content="Trigger message",
            created_at=datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc),
        )
        self.session.add(trigger)
        self.session.commit()

        # Limit to 5 messages (should only show last 5)
        user_message = build_user_message(
            self.session, conversation, trigger, max_messages=5
        )

        # Should include msg-6 through msg-9 (4 messages) + trigger
        self.assertNotIn("Message 0", user_message)
        self.assertNotIn("Message 5", user_message)
        self.assertIn("Message 6", user_message)
        self.assertIn("Message 9", user_message)

    def test_respects_max_chars_limit(self) -> None:
        conversation = Conversation(
            id="conv-1",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            name="Test",
            kind="job",
        )
        self.session.add(conversation)

        user = User(id="user-1", email="alice@example.com", name="Alice")
        self.session.add(user)

        # Create messages with long content
        for i in range(5):
            msg = Message(
                id=f"msg-{i}",
                conversation_id="conv-1",
                sender_type="user",
                sender_user_id="user-1",
                content="x" * 1000,  # 1000 chars each
                created_at=datetime(2026, 1, 1, 12, i, tzinfo=timezone.utc),
            )
            self.session.add(msg)

        trigger = Message(
            id="msg-trigger",
            conversation_id="conv-1",
            sender_type="user",
            sender_user_id="user-1",
            content="Short trigger",
            created_at=datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc),
        )
        self.session.add(trigger)
        self.session.commit()

        user_message = build_user_message(
            self.session, conversation, trigger, max_chars=2000
        )

        # Should truncate history due to char limit
        # Not all 5 messages should appear
        self.assertLess(len(user_message), 4000)

    def test_system_sender_type(self) -> None:
        conversation = Conversation(
            id="conv-1",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            name="Test",
            kind="job",
        )
        self.session.add(conversation)

        msg = Message(
            id="msg-1",
            conversation_id="conv-1",
            sender_type="system",
            content="Workflow started",
            created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
        trigger = Message(
            id="msg-trigger",
            conversation_id="conv-1",
            sender_type="user",
            sender_user_id="user-1",
            content="Hello",
            created_at=datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc),
        )
        self.session.add(msg)
        self.session.add(trigger)
        self.session.commit()

        user_message = build_user_message(self.session, conversation, trigger)

        self.assertIn("system: Workflow started", user_message)

    def test_empty_history(self) -> None:
        conversation = Conversation(
            id="conv-1",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            name="Test",
            kind="job",
        )
        self.session.add(conversation)

        trigger = Message(
            id="msg-trigger",
            conversation_id="conv-1",
            sender_type="user",
            sender_user_id="user-1",
            content="First message",
            created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
        self.session.add(trigger)
        self.session.commit()

        user_message = build_user_message(self.session, conversation, trigger)

        self.assertNotIn("Conversation history", user_message)
        self.assertIn("Latest message", user_message)
        self.assertIn("First message", user_message)


class BuildWorkgroupFilesContextTests(unittest.TestCase):
    """Test workgroup files context embedding."""

    def test_empty_files_returns_empty_string(self) -> None:
        workgroup = _make_workgroup(files=[])
        conversation = _make_conversation()

        context = build_workgroup_files_context(workgroup, conversation)

        self.assertEqual(context, "")

    def test_includes_shared_files(self) -> None:
        workgroup = _make_workgroup(
            files=[
                {"path": "README.md", "content": "Project overview"},
                {"path": "SETUP.md", "content": "Setup instructions"},
            ]
        )
        conversation = _make_conversation()

        context = build_workgroup_files_context(workgroup, conversation)

        self.assertIn("Reference files:", context)
        self.assertIn("--- README.md ---", context)
        self.assertIn("Project overview", context)
        self.assertIn("--- SETUP.md ---", context)
        self.assertIn("Setup instructions", context)

    def test_filters_to_job_scoped_files(self) -> None:
        conversation = _make_conversation(conversation_id="topic-123", kind="job")
        workgroup = _make_workgroup(
            files=[
                {
                    "path": "topic-notes.md",
                    "content": "Topic specific",
                    "topic_id": "topic-123",
                },
                {"path": "shared.md", "content": "Shared content"},
                {
                    "path": "other-topic.md",
                    "content": "Other topic",
                    "topic_id": "topic-456",
                },
            ]
        )

        context = build_workgroup_files_context(workgroup, conversation)

        self.assertIn("topic-notes.md", context)
        self.assertIn("Topic specific", context)
        self.assertIn("shared.md", context)
        self.assertIn("Shared content", context)
        self.assertNotIn("other-topic.md", context)
        self.assertNotIn("Other topic", context)

    def test_truncates_large_files(self) -> None:
        large_content = "x" * 5000
        workgroup = _make_workgroup(
            files=[{"path": "large.txt", "content": large_content}]
        )
        conversation = _make_conversation()

        context = build_workgroup_files_context(workgroup, conversation)

        self.assertIn("--- large.txt ---", context)
        self.assertIn("... (truncated)", context)
        # Should truncate to 3000 chars
        self.assertLess(context.count("x"), 3100)

    def test_skips_files_without_content(self) -> None:
        workgroup = _make_workgroup(
            files=[
                {"path": "empty.md", "content": ""},
                {"path": "has-content.md", "content": "Hello"},
            ]
        )
        conversation = _make_conversation()

        context = build_workgroup_files_context(workgroup, conversation)

        self.assertNotIn("empty.md", context)
        self.assertIn("has-content.md", context)
        self.assertIn("Hello", context)

    def test_direct_conversation_uses_shared_files_only(self) -> None:
        conversation = _make_conversation(kind="direct")
        workgroup = _make_workgroup(
            files=[
                {"path": "shared.md", "content": "Shared"},
                {"path": "topic.md", "content": "Topic", "topic_id": "topic-1"},
            ]
        )

        context = build_workgroup_files_context(workgroup, conversation)

        self.assertIn("shared.md", context)
        self.assertIn("Shared", context)
        # Job-scoped files should not be included since conversation isn't a job
        self.assertNotIn("topic.md", context)


if __name__ == "__main__":
    unittest.main()
