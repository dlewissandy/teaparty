"""Tests for the agent todo system: materialization and signal evaluation."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from teaparty_app.models import Agent, AgentTodoItem, Conversation, Message, Workgroup, utc_now, new_id
from teaparty_app.services.todo_helpers import (
    _materialize_todo_file,
    evaluate_message_match_todos,
    evaluate_file_changed_todos,
    evaluate_job_resolved_todos,
)


def _make_agent(
    *,
    agent_id: str = "a1",
    name: str = "TestAgent",
    tool_names: list[str] | None = None,
) -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        tool_names=tool_names or [],
    )


def _make_conversation(
    *,
    conversation_id: str = "conv-1",
    workgroup_id: str = "wg-1",
    kind: str = "job",
) -> Conversation:
    return Conversation(
        id=conversation_id,
        workgroup_id=workgroup_id,
        created_by_user_id="user-1",
        kind=kind,
        topic="Test topic",
    )


def _make_message(
    *,
    message_id: str = "msg-1",
    conversation_id: str = "conv-1",
    content: str = "Hello",
) -> Message:
    return Message(
        id=message_id,
        conversation_id=conversation_id,
        sender_type="user",
        sender_user_id="user-1",
        content=content,
    )


def _make_workgroup(*, workgroup_id: str = "wg-1", files: list | None = None) -> Workgroup:
    return Workgroup(
        id=workgroup_id,
        name="Test WG",
        owner_id="user-1",
        files=files or [],
    )


def _make_todo(
    *,
    todo_id: str | None = None,
    agent_id: str = "a1",
    workgroup_id: str = "wg-1",
    conversation_id: str | None = "conv-1",
    title: str = "Test todo",
    status: str = "pending",
    priority: str = "medium",
    trigger_type: str = "manual",
    trigger_config: dict | None = None,
    due_at: datetime | None = None,
) -> AgentTodoItem:
    return AgentTodoItem(
        id=todo_id or new_id(),
        agent_id=agent_id,
        workgroup_id=workgroup_id,
        conversation_id=conversation_id,
        title=title,
        status=status,
        priority=priority,
        trigger_type=trigger_type,
        trigger_config=trigger_config or {},
        due_at=due_at,
    )


class TestEvaluateMessageMatchTodos(unittest.TestCase):
    def test_matches_keyword(self) -> None:
        conversation = _make_conversation()
        todo = _make_todo(
            trigger_type="message_match",
            trigger_config={"keywords": ["deployed", "shipped"]},
            conversation_id="conv-1",
        )

        session = MagicMock()
        session.get.return_value = conversation
        session.exec.return_value.all.return_value = [todo]

        message = _make_message(content="The feature has been deployed to production")
        evaluate_message_match_todos(session, message)

        self.assertIsNotNone(todo.triggered_at)

    def test_no_match(self) -> None:
        conversation = _make_conversation()
        todo = _make_todo(
            trigger_type="message_match",
            trigger_config={"keywords": ["deployed"]},
            conversation_id="conv-1",
        )

        session = MagicMock()
        session.get.return_value = conversation
        session.exec.return_value.all.return_value = [todo]

        message = _make_message(content="Just a normal message")
        evaluate_message_match_todos(session, message)

        self.assertIsNone(todo.triggered_at)

    def test_case_insensitive(self) -> None:
        conversation = _make_conversation()
        todo = _make_todo(
            trigger_type="message_match",
            trigger_config={"keywords": ["DEPLOYED"]},
            conversation_id="conv-1",
        )

        session = MagicMock()
        session.get.return_value = conversation
        session.exec.return_value.all.return_value = [todo]

        message = _make_message(content="Feature deployed successfully")
        evaluate_message_match_todos(session, message)

        self.assertIsNotNone(todo.triggered_at)

    def test_wrong_conversation_not_triggered(self) -> None:
        conversation = _make_conversation(conversation_id="conv-1")
        todo = _make_todo(
            trigger_type="message_match",
            trigger_config={"keywords": ["deployed"]},
            conversation_id="conv-other",
        )

        session = MagicMock()
        session.get.return_value = conversation
        session.exec.return_value.all.return_value = [todo]

        message = _make_message(content="deployed to prod", conversation_id="conv-1")
        evaluate_message_match_todos(session, message)

        self.assertIsNone(todo.triggered_at)


class TestEvaluateFileChangedTodos(unittest.TestCase):
    def test_matches_file_path(self) -> None:
        todo = _make_todo(
            trigger_type="file_changed",
            trigger_config={"file_path": "design.md"},
        )

        session = MagicMock()
        session.exec.return_value.all.return_value = [todo]

        evaluate_file_changed_todos(session, "wg-1", "design.md")
        self.assertIsNotNone(todo.triggered_at)

    def test_no_match_different_path(self) -> None:
        todo = _make_todo(
            trigger_type="file_changed",
            trigger_config={"file_path": "design.md"},
        )

        session = MagicMock()
        session.exec.return_value.all.return_value = [todo]

        evaluate_file_changed_todos(session, "wg-1", "readme.md")
        self.assertIsNone(todo.triggered_at)


class TestEvaluateJobResolvedTodos(unittest.TestCase):
    def test_marks_triggered(self) -> None:
        todo = _make_todo(
            trigger_type="job_resolved",
            conversation_id="conv-1",
        )

        session = MagicMock()
        session.exec.return_value.all.return_value = [todo]

        evaluate_job_resolved_todos(session, "conv-1")
        self.assertIsNotNone(todo.triggered_at)


class TestMaterializeTodoFile(unittest.TestCase):
    def test_creates_todo_file(self) -> None:
        agent = _make_agent(name="Alice")
        workgroup = _make_workgroup(files=[])

        pending_todo = _make_todo(title="Do something", priority="high", status="pending")
        done_todo = _make_todo(
            title="Old task", status="done",
            trigger_type="manual",
        )
        done_todo.completed_at = utc_now()

        session = MagicMock()
        session.get.return_value = workgroup
        session.exec.return_value.all.return_value = [pending_todo, done_todo]

        _materialize_todo_file(session, agent, "wg-1")

        # Check that workgroup.files was updated
        self.assertTrue(len(workgroup.files) > 0)
        todo_file = next(
            (f for f in workgroup.files if f["path"] == "_todos/Alice.md"),
            None,
        )
        self.assertIsNotNone(todo_file)
        self.assertIn("# Todos -- Alice", todo_file["content"])
        self.assertIn("Do something", todo_file["content"])
        self.assertIn("[HIGH]", todo_file["content"])
        self.assertIn("Old task", todo_file["content"])

    def test_updates_existing_todo_file(self) -> None:
        agent = _make_agent(name="Bob")
        existing_file = {
            "id": "f-existing",
            "path": "_todos/Bob.md",
            "content": "# Todos -- Bob\nold content",
            "topic_id": "",
        }
        workgroup = _make_workgroup(files=[existing_file])

        session = MagicMock()
        session.get.return_value = workgroup
        session.exec.return_value.all.return_value = []

        _materialize_todo_file(session, agent, "wg-1")

        # Should update in-place, not create a new file
        todo_files = [f for f in workgroup.files if f["path"] == "_todos/Bob.md"]
        self.assertEqual(len(todo_files), 1)
        self.assertIn("# Todos -- Bob", todo_files[0]["content"])
