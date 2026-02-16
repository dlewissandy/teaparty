import json
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from teaparty_app.models import (
    Agent, Conversation, ConversationParticipant, Membership,
    Message, User, Workgroup, new_id,
)
from teaparty_app.services.agent_tools import (
    AGENT_TOOL_SCHEMAS,
    _ensure_agent_dm,
    _resolve_dm_recipient,
    _tool_send_direct_message,
    build_tool_schemas,
    dispatch_agent_tool,
)


def _make_agent(
    *,
    agent_id: str = "a1",
    name: str = "TestAgent",
    tool_names: list[str] | None = None,
    personality: str = "Professional and concise",
    role: str = "Engineer",
    description: str = "",
) -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        personality=personality,
        role=role,
        description=description,
        tool_names=tool_names or [],
    )


def _make_conversation(
    *,
    conversation_id: str = "conv-1",
    topic: str = "Test topic",
    kind: str = "job",
) -> Conversation:
    return Conversation(
        id=conversation_id,
        workgroup_id="wg-1",
        topic=topic,
        kind=kind,
    )


def _make_message(
    *,
    message_id: str = "msg-1",
    content: str = "Hello",
    sender_type: str = "user",
    sender_user_id: str | None = "user-1",
) -> Message:
    return Message(
        id=message_id,
        conversation_id="conv-1",
        sender_type=sender_type,
        sender_user_id=sender_user_id,
        content=content,
    )


def _make_workgroup(*, workgroup_id: str = "wg-1", files: list | None = None) -> Workgroup:
    return Workgroup(
        id=workgroup_id,
        name="Test WG",
        owner_id="user-1",
        files=files or [],
    )


class TestAgentToolSchemas(unittest.TestCase):
    def test_all_schemas_have_required_fields(self) -> None:
        for schema in AGENT_TOOL_SCHEMAS:
            self.assertIn("name", schema)
            self.assertIn("description", schema)
            self.assertIn("input_schema", schema)
            self.assertIn("type", schema["input_schema"])
            self.assertEqual(schema["input_schema"]["type"], "object")

    def test_schema_names_are_unique(self) -> None:
        names = [s["name"] for s in AGENT_TOOL_SCHEMAS]
        self.assertEqual(len(names), len(set(names)))

    def test_read_file_has_path_required(self) -> None:
        read_schema = next(s for s in AGENT_TOOL_SCHEMAS if s["name"] == "read_file")
        self.assertIn("path", read_schema["input_schema"]["properties"])
        self.assertIn("path", read_schema["input_schema"]["required"])

    def test_add_file_has_path_and_content_required(self) -> None:
        add_schema = next(s for s in AGENT_TOOL_SCHEMAS if s["name"] == "add_file")
        self.assertIn("path", add_schema["input_schema"]["required"])
        self.assertIn("content", add_schema["input_schema"]["required"])


# TestBuildToolSchemas and TestShouldUseSdk deleted - functions moved to admin_workspace


class TestDispatchAgentTool(unittest.TestCase):
    def test_dispatch_list_files_empty(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["list_files"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(session, agent, conversation, trigger, "list_files", {})
        self.assertIn("No files", result)

    def test_dispatch_list_files_with_files(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "readme.md", "content": "hello", "topic_id": ""},
            {"id": "f2", "path": "notes.txt", "content": "world", "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["list_files"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(session, agent, conversation, trigger, "list_files", {})
        self.assertIn("notes.txt", result)
        self.assertIn("readme.md", result)

    def test_dispatch_read_file_found(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "config.yaml", "content": "key: value", "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent()
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(session, agent, conversation, trigger, "read_file", {"path": "config.yaml"})
        self.assertEqual(result, "key: value")

    def test_dispatch_read_file_not_found(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        session.get.return_value = workgroup
        agent = _make_agent()
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(session, agent, conversation, trigger, "read_file", {"path": "missing.txt"})
        self.assertIn("not found", result)

    def test_dispatch_add_file(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        session.get.return_value = workgroup
        agent = _make_agent()
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "add_file", {"path": "new.md", "content": "# Title"},
        )
        self.assertIn("Created", result)
        self.assertIn("new.md", result)

    def test_dispatch_add_file_already_exists(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "existing.md", "content": "old", "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent()
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "add_file", {"path": "existing.md", "content": "new"},
        )
        self.assertIn("already exists", result)

    def test_dispatch_edit_file(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "doc.md", "content": "old content", "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent()
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "edit_file", {"path": "doc.md", "content": "new content"},
        )
        self.assertIn("Updated", result)

    def test_dispatch_rename_file(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "old.md", "content": "data", "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent()
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "rename_file", {"source_path": "old.md", "dest_path": "new.md"},
        )
        self.assertIn("Renamed", result)

    def test_dispatch_delete_file(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "trash.md", "content": "", "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent()
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "delete_file", {"path": "trash.md"},
        )
        self.assertIn("Deleted", result)

    def test_dispatch_unknown_tool(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup()
        session.get.return_value = workgroup
        agent = _make_agent()
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(session, agent, conversation, trigger, "nonexistent", {})
        self.assertIn("unknown tool", result)

    def test_dispatch_suggest_next_step_blocked(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup()
        session.get.return_value = workgroup
        agent = _make_agent()
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "suggest_next_step", {"context": "we're blocked on API access"},
        )
        self.assertIn("blockers", result)

    def test_dispatch_suggest_next_step_decision(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup()
        session.get.return_value = workgroup
        agent = _make_agent()
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "suggest_next_step", {"context": "need a decision on the architecture"},
        )
        self.assertIn("options", result)


# TestBuildAgentReplyWithSdk deleted - function moved to admin_workspace


class TestSearchFiles(unittest.TestCase):
    def test_search_files_schema_has_query_required(self) -> None:
        schema = next(s for s in AGENT_TOOL_SCHEMAS if s["name"] == "search_files")
        self.assertIn("query", schema["input_schema"]["properties"])
        self.assertIn("query", schema["input_schema"]["required"])

    def test_dispatch_search_files_no_files(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["search_files"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "search_files", {"query": "deployment"},
        )
        self.assertIn("No files", result)

    def test_dispatch_search_files_few_files_skips_llm(self) -> None:
        """With ≤3 files, all are returned without an LLM call."""
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "readme.md", "content": "Welcome to the project", "topic_id": ""},
            {"id": "f2", "path": "config.yaml", "content": "key: value", "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["search_files"])
        conversation = _make_conversation()
        trigger = _make_message()

        with patch("teaparty_app.services.llm_client.create_message") as mock_create_message:
            result = dispatch_agent_tool(
                session, agent, conversation, trigger,
                "search_files", {"query": "config"},
            )
            mock_create_message.assert_not_called()

        self.assertIn("All files", result)
        self.assertIn("readme.md", result)
        self.assertIn("config.yaml", result)
        self.assertIn("Welcome to the project", result)

    def test_dispatch_search_files_llm_ranked(self) -> None:
        """With >3 files, LLM is called and results are returned ranked."""
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "readme.md", "content": "Welcome", "topic_id": ""},
            {"id": "f2", "path": "deploy.sh", "content": "#!/bin/bash\ndeploy to prod", "topic_id": ""},
            {"id": "f3", "path": "config.yaml", "content": "key: value", "topic_id": ""},
            {"id": "f4", "path": "notes.txt", "content": "meeting notes", "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["search_files"])
        conversation = _make_conversation()
        trigger = _make_message()

        llm_response_json = json.dumps([
            {"path": "deploy.sh", "excerpt": "deploy to prod", "relevance": "high"},
            {"path": "config.yaml", "excerpt": "key: value", "relevance": "medium"},
        ])

        mock_response = MagicMock()
        mock_response.usage.input_tokens = 200
        mock_response.usage.output_tokens = 50
        text_block = MagicMock()
        text_block.text = llm_response_json
        mock_response.content = [text_block]

        with (
            patch("teaparty_app.services.llm_client.create_message") as mock_create_message,
            patch("teaparty_app.services.llm_usage.record_llm_usage") as mock_usage,
        ):
            mock_create_message.return_value = mock_response
            result = dispatch_agent_tool(
                session, agent, conversation, trigger,
                "search_files", {"query": "deployment"},
            )

        self.assertIn("Search results", result)
        self.assertIn("deploy.sh", result)
        self.assertIn("[high]", result)
        self.assertIn("[medium]", result)
        mock_usage.assert_called_once()
        self.assertEqual(mock_usage.call_args.kwargs["purpose"], "file_search")

    def test_dispatch_search_files_llm_fallback(self) -> None:
        """When LLM fails, falls back to keyword matching."""
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "readme.md", "content": "Welcome", "topic_id": ""},
            {"id": "f2", "path": "deploy.sh", "content": "#!/bin/bash\ndeploy to prod", "topic_id": ""},
            {"id": "f3", "path": "config.yaml", "content": "key: value", "topic_id": ""},
            {"id": "f4", "path": "notes.txt", "content": "meeting notes about deployment", "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["search_files"])
        conversation = _make_conversation()
        trigger = _make_message()

        with patch("teaparty_app.services.llm_client.create_message") as mock_create_message:
            mock_create_message.side_effect = Exception("API error")
            result = dispatch_agent_tool(
                session, agent, conversation, trigger,
                "search_files", {"query": "deploy"},
            )

        self.assertIn("Search results", result)
        self.assertIn("deploy.sh", result)

    def test_dispatch_search_files_empty_query(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "readme.md", "content": "hello", "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["search_files"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "search_files", {"query": ""},
        )
        self.assertIn("Error", result)


class TestTodoToolSchemas(unittest.TestCase):
    def test_create_todo_schema_has_title_required(self) -> None:
        schema = next(s for s in AGENT_TOOL_SCHEMAS if s["name"] == "create_todo")
        self.assertIn("title", schema["input_schema"]["properties"])
        self.assertIn("title", schema["input_schema"]["required"])

    def test_list_todos_schema_exists(self) -> None:
        schema = next(s for s in AGENT_TOOL_SCHEMAS if s["name"] == "list_todos")
        self.assertIn("status", schema["input_schema"]["properties"])

    def test_update_todo_schema_has_todo_id_required(self) -> None:
        schema = next(s for s in AGENT_TOOL_SCHEMAS if s["name"] == "update_todo")
        self.assertIn("todo_id", schema["input_schema"]["required"])

    def test_todo_schemas_included_in_build(self) -> None:
        agent = _make_agent(tool_names=["create_todo", "list_todos", "update_todo"])
        session = MagicMock()
        schemas = build_tool_schemas(session, agent)
        names = {s["name"] for s in schemas}
        self.assertEqual(names, {"create_todo", "list_todos", "update_todo"})

    def test_dispatch_create_todo_missing_title(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup()
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["create_todo"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "create_todo", {},
        )
        self.assertIn("Error", result)
        self.assertIn("title", result)



# ---------------------------------------------------------------------------
# send_direct_message tests (real SQLite)
# ---------------------------------------------------------------------------


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


class TestSendDirectMessageSchema(unittest.TestCase):
    def test_schema_exists_with_required_fields(self) -> None:
        schema = next(s for s in AGENT_TOOL_SCHEMAS if s["name"] == "send_direct_message")
        self.assertIn("recipient_name", schema["input_schema"]["properties"])
        self.assertIn("message", schema["input_schema"]["properties"])
        self.assertEqual(
            sorted(schema["input_schema"]["required"]),
            ["message", "recipient_name"],
        )

    def test_included_in_build_tool_schemas(self) -> None:
        agent = _make_agent(tool_names=["send_direct_message"])
        session = MagicMock()
        schemas = build_tool_schemas(session, agent)
        names = {s["name"] for s in schemas}
        self.assertIn("send_direct_message", names)


class TestSendDirectMessage(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            # Create users
            self.user_alice = User(id="user-alice", email="alice@example.com", name="Alice")
            self.user_bob = User(id="user-bob", email="bob@example.com", name="Bob")
            self.user_carol = User(id="user-carol", email="carol@example.com", name="Carol McBob")
            session.add_all([self.user_alice, self.user_bob, self.user_carol])

            # Create workgroup
            self.workgroup = Workgroup(
                id="wg-1", name="Test WG", owner_id="user-alice", files=[],
            )
            session.add(self.workgroup)

            # Memberships
            session.add(Membership(workgroup_id="wg-1", user_id="user-alice", role="owner"))
            session.add(Membership(workgroup_id="wg-1", user_id="user-bob", role="member"))
            session.add(Membership(workgroup_id="wg-1", user_id="user-carol", role="member"))

            # Agent
            self.agent = Agent(
                id="agent-1", workgroup_id="wg-1", created_by_user_id="user-alice",
                name="Helper", tool_names=["send_direct_message"],
            )
            session.add(self.agent)

            # Topic conversation
            self.conversation = Conversation(
                id="conv-topic", workgroup_id="wg-1", created_by_user_id="user-alice",
                kind="job", topic="general", name="General",
            )
            session.add(self.conversation)
            session.commit()

    def test_successful_dm_send(self) -> None:
        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            result = _tool_send_direct_message(session, agent, conversation, "Alice", "Hey, quick question!")
            session.commit()

            self.assertEqual(result, "Sent DM to Alice.")

            # Verify DM conversation created
            dm_convos = session.exec(
                __import__("sqlmodel", fromlist=["select"]).select(Conversation).where(
                    Conversation.workgroup_id == "wg-1",
                    Conversation.kind == "direct",
                )
            ).all()
            self.assertEqual(len(dm_convos), 1)
            self.assertEqual(dm_convos[0].topic, "dma:user-alice:agent-1")

            # Verify participants
            from sqlmodel import select
            participants = session.exec(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == dm_convos[0].id,
                )
            ).all()
            self.assertEqual(len(participants), 2)
            user_ids = {p.user_id for p in participants if p.user_id}
            agent_ids = {p.agent_id for p in participants if p.agent_id}
            self.assertEqual(user_ids, {"user-alice"})
            self.assertEqual(agent_ids, {"agent-1"})

            # Verify message
            messages = session.exec(
                select(Message).where(Message.conversation_id == dm_convos[0].id)
            ).all()
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].sender_type, "agent")
            self.assertEqual(messages[0].sender_agent_id, "agent-1")
            self.assertEqual(messages[0].content, "Hey, quick question!")
            self.assertFalse(messages[0].requires_response)

    def test_dm_conversation_reused(self) -> None:
        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            _tool_send_direct_message(session, agent, conversation, "Bob", "First message")
            session.commit()

        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            _tool_send_direct_message(session, agent, conversation, "Bob", "Second message")
            session.commit()

        with Session(self.engine) as session:
            from sqlmodel import select
            dm_convos = session.exec(
                select(Conversation).where(
                    Conversation.workgroup_id == "wg-1",
                    Conversation.kind == "direct",
                )
            ).all()
            self.assertEqual(len(dm_convos), 1, "Should reuse same DM conversation")

            messages = session.exec(
                select(Message).where(Message.conversation_id == dm_convos[0].id)
            ).all()
            self.assertEqual(len(messages), 2)

    def test_recipient_not_found(self) -> None:
        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            result = _tool_send_direct_message(session, agent, conversation, "Zeke", "Hello")
            self.assertIn("Error", result)
            self.assertIn("No workgroup member matching", result)

    def test_ambiguous_recipient(self) -> None:
        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            # "bob" matches both "Bob" and "Carol McBob" by substring
            result = _tool_send_direct_message(session, agent, conversation, "bob", "Hello")
            # "bob" exact matches "Bob" (case-insensitive), so it should succeed
            self.assertEqual(result, "Sent DM to Bob.")

    def test_ambiguous_recipient_substring(self) -> None:
        """When substring matches multiple and no exact match, error with names."""
        with Session(self.engine) as session:
            # Add another user whose name also contains "car"
            session.add(User(id="user-carl", email="carl@example.com", name="Carl"))
            session.add(Membership(workgroup_id="wg-1", user_id="user-carl", role="member"))
            session.commit()

        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            result = _tool_send_direct_message(session, agent, conversation, "Car", "Hello")
            self.assertIn("Error", result)
            self.assertIn("Ambiguous", result)
            self.assertIn("Carol McBob", result)
            self.assertIn("Carl", result)

    def test_partial_name_match(self) -> None:
        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            result = _tool_send_direct_message(session, agent, conversation, "alic", "Hey!")
            self.assertEqual(result, "Sent DM to Alice.")

    def test_email_match(self) -> None:
        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            result = _tool_send_direct_message(session, agent, conversation, "bob@example.com", "Hey!")
            self.assertEqual(result, "Sent DM to Bob.")

    def test_empty_recipient(self) -> None:
        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            result = _tool_send_direct_message(session, agent, conversation, "", "Hello")
            self.assertIn("Error", result)
            self.assertIn("recipient_name is required", result)

    def test_empty_message(self) -> None:
        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            result = _tool_send_direct_message(session, agent, conversation, "Alice", "")
            self.assertIn("Error", result)
            self.assertIn("message is required", result)

    def test_message_too_long(self) -> None:
        with Session(self.engine) as session:
            agent = session.get(Agent, "agent-1")
            conversation = session.get(Conversation, "conv-topic")

            result = _tool_send_direct_message(session, agent, conversation, "Alice", "x" * 10_001)
            self.assertIn("Error", result)
            self.assertIn("10000", result)
