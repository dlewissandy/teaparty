"""Tests for the agent todo system: tools, materialization, and signal evaluation."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from teaparty_app.models import Agent, AgentTodoItem, Conversation, Message, Workgroup, utc_now, new_id
from teaparty_app.services.agent_tools import (
    _tool_create_todo,
    _tool_list_todos,
    _tool_update_todo,
    _materialize_todo_file,
    _cascade_todo_completed,
    evaluate_message_match_todos,
    evaluate_file_changed_todos,
    evaluate_job_resolved_todos,
    dispatch_agent_tool,
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


class _MockSession:
    """Minimal mock session that stores added objects and supports exec queries."""

    def __init__(self) -> None:
        self._objects: list = []
        self._todos: list[AgentTodoItem] = []

    def add(self, obj: object) -> None:
        self._objects.append(obj)
        if isinstance(obj, AgentTodoItem) and obj not in self._todos:
            self._todos.append(obj)

    def flush(self) -> None:
        pass

    def get(self, model_class, obj_id):
        if model_class is Workgroup:
            return None
        if model_class is AgentTodoItem:
            for t in self._todos:
                if t.id == obj_id:
                    return t
        return None

    def exec(self, query):
        return _MockResult([])


class _MockResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class TestCreateTodo(unittest.TestCase):
    def test_creates_basic_todo(self) -> None:
        session = _MockSession()
        agent = _make_agent()
        conversation = _make_conversation()

        result = _tool_create_todo(session, agent, conversation, {"title": "Write tests"})
        self.assertIn("Created todo", result)
        self.assertIn("Write tests", result)
        # Should have added a todo object
        todos = [o for o in session._objects if isinstance(o, AgentTodoItem)]
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].title, "Write tests")
        self.assertEqual(todos[0].priority, "medium")
        self.assertEqual(todos[0].trigger_type, "manual")
        self.assertEqual(todos[0].agent_id, "a1")
        self.assertEqual(todos[0].workgroup_id, "wg-1")
        self.assertEqual(todos[0].conversation_id, "conv-1")

    def test_rejects_empty_title(self) -> None:
        session = _MockSession()
        result = _tool_create_todo(session, _make_agent(), _make_conversation(), {"title": ""})
        self.assertIn("Error", result)

    def test_rejects_long_title(self) -> None:
        session = _MockSession()
        result = _tool_create_todo(session, _make_agent(), _make_conversation(), {"title": "x" * 201})
        self.assertIn("Error", result)

    def test_rejects_long_description(self) -> None:
        session = _MockSession()
        result = _tool_create_todo(
            session, _make_agent(), _make_conversation(),
            {"title": "ok", "description": "x" * 2001},
        )
        self.assertIn("Error", result)

    def test_rejects_invalid_priority(self) -> None:
        session = _MockSession()
        result = _tool_create_todo(
            session, _make_agent(), _make_conversation(),
            {"title": "ok", "priority": "critical"},
        )
        self.assertIn("Error", result)

    def test_rejects_invalid_trigger_type(self) -> None:
        session = _MockSession()
        result = _tool_create_todo(
            session, _make_agent(), _make_conversation(),
            {"title": "ok", "trigger_type": "magic"},
        )
        self.assertIn("Error", result)

    def test_time_trigger_requires_due_at(self) -> None:
        session = _MockSession()
        result = _tool_create_todo(
            session, _make_agent(), _make_conversation(),
            {"title": "ok", "trigger_type": "time"},
        )
        self.assertIn("Error", result)
        self.assertIn("due_at", result)

    def test_time_trigger_with_due_at(self) -> None:
        session = _MockSession()
        result = _tool_create_todo(
            session, _make_agent(), _make_conversation(),
            {"title": "Check status", "trigger_type": "time", "due_at": "2025-02-01T12:00:00Z"},
        )
        self.assertIn("Created todo", result)
        self.assertIn("trigger=time", result)
        todos = [o for o in session._objects if isinstance(o, AgentTodoItem)]
        self.assertEqual(todos[0].trigger_type, "time")
        self.assertIsNotNone(todos[0].due_at)

    def test_job_stall_defaults_stall_minutes(self) -> None:
        session = _MockSession()
        result = _tool_create_todo(
            session, _make_agent(), _make_conversation(),
            {"title": "Nudge", "trigger_type": "job_stall"},
        )
        self.assertIn("Created todo", result)
        todos = [o for o in session._objects if isinstance(o, AgentTodoItem)]
        self.assertEqual(todos[0].trigger_config.get("stall_minutes"), 30)

    def test_invalid_due_at_format(self) -> None:
        session = _MockSession()
        result = _tool_create_todo(
            session, _make_agent(), _make_conversation(),
            {"title": "ok", "trigger_type": "time", "due_at": "not-a-date"},
        )
        self.assertIn("Error", result)
        self.assertIn("ISO 8601", result)


class TestListTodos(unittest.TestCase):
    def test_empty_list(self) -> None:
        session = _MockSession()
        result = _tool_list_todos(session, _make_agent(), {})
        self.assertIn("No", result)

    def test_rejects_invalid_status(self) -> None:
        session = _MockSession()
        result = _tool_list_todos(session, _make_agent(), {"status": "exploded"})
        self.assertIn("Error", result)


class TestUpdateTodo(unittest.TestCase):
    def test_missing_todo_id(self) -> None:
        session = _MockSession()
        result = _tool_update_todo(session, _make_agent(), _make_conversation(), {})
        self.assertIn("Error", result)
        self.assertIn("todo_id", result)

    def test_not_found(self) -> None:
        session = _MockSession()
        result = _tool_update_todo(
            session, _make_agent(), _make_conversation(),
            {"todo_id": "nonexistent"},
        )
        self.assertIn("Error", result)
        self.assertIn("not found", result)

    def test_wrong_agent(self) -> None:
        session = _MockSession()
        todo = _make_todo(todo_id="t1", agent_id="other-agent")
        session._todos.append(todo)
        agent = _make_agent(agent_id="a1")
        result = _tool_update_todo(
            session, agent, _make_conversation(),
            {"todo_id": "t1", "status": "done"},
        )
        self.assertIn("Error", result)
        self.assertIn("your own", result)

    def test_mark_done(self) -> None:
        session = _MockSession()
        todo = _make_todo(todo_id="t1", agent_id="a1")
        session._todos.append(todo)

        result = _tool_update_todo(
            session, _make_agent(), _make_conversation(),
            {"todo_id": "t1", "status": "done"},
        )
        self.assertIn("Updated", result)
        self.assertIn("status=done", result)
        self.assertEqual(todo.status, "done")
        self.assertIsNotNone(todo.completed_at)

    def test_change_priority(self) -> None:
        session = _MockSession()
        todo = _make_todo(todo_id="t1", agent_id="a1")
        session._todos.append(todo)

        result = _tool_update_todo(
            session, _make_agent(), _make_conversation(),
            {"todo_id": "t1", "priority": "urgent"},
        )
        self.assertIn("Updated", result)
        self.assertIn("priority=urgent", result)
        self.assertEqual(todo.priority, "urgent")

    def test_no_changes(self) -> None:
        session = _MockSession()
        todo = _make_todo(todo_id="t1", agent_id="a1", title="Test todo")
        session._todos.append(todo)

        result = _tool_update_todo(
            session, _make_agent(), _make_conversation(),
            {"todo_id": "t1"},
        )
        self.assertIn("No changes", result)

    def test_invalid_status(self) -> None:
        session = _MockSession()
        todo = _make_todo(todo_id="t1", agent_id="a1")
        session._todos.append(todo)

        result = _tool_update_todo(
            session, _make_agent(), _make_conversation(),
            {"todo_id": "t1", "status": "exploded"},
        )
        self.assertIn("Error", result)


class TestCascadeTodoCompleted(unittest.TestCase):
    def test_cascade_marks_dependent(self) -> None:
        completed = _make_todo(todo_id="t1", status="done")
        dependent = _make_todo(
            todo_id="t2",
            trigger_type="todo_completed",
            trigger_config={"todo_id": "t1"},
        )

        session = MagicMock()
        session.exec.return_value.all.return_value = [dependent]

        _cascade_todo_completed(session, completed)
        self.assertIsNotNone(dependent.triggered_at)

    def test_cascade_ignores_wrong_ref(self) -> None:
        completed = _make_todo(todo_id="t1", status="done")
        unrelated = _make_todo(
            todo_id="t3",
            trigger_type="todo_completed",
            trigger_config={"todo_id": "other"},
        )

        session = MagicMock()
        session.exec.return_value.all.return_value = [unrelated]

        _cascade_todo_completed(session, completed)
        self.assertIsNone(unrelated.triggered_at)


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
        self.assertIn("# Todos — Alice", todo_file["content"])
        self.assertIn("Do something", todo_file["content"])
        self.assertIn("[HIGH]", todo_file["content"])
        self.assertIn("Old task", todo_file["content"])

    def test_updates_existing_todo_file(self) -> None:
        agent = _make_agent(name="Bob")
        existing_file = {
            "id": "f-existing",
            "path": "_todos/Bob.md",
            "content": "# Todos — Bob\nold content",
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
        self.assertIn("# Todos — Bob", todo_files[0]["content"])


class TestDispatchTodoTools(unittest.TestCase):
    """Test dispatch_agent_tool routes to todo tools correctly."""

    def test_dispatch_create_todo(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup()
        session.get.return_value = workgroup
        session.exec.return_value.all.return_value = []
        agent = _make_agent(tool_names=["create_todo"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "create_todo", {"title": "Test task"},
        )
        self.assertIn("Created todo", result)

    def test_dispatch_list_todos(self) -> None:
        session = MagicMock()
        session.exec.return_value.all.return_value = []
        agent = _make_agent(tool_names=["list_todos"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "list_todos", {},
        )
        self.assertIn("No", result)

    def test_dispatch_update_todo_missing_id(self) -> None:
        session = MagicMock()
        agent = _make_agent(tool_names=["update_todo"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "update_todo", {},
        )
        self.assertIn("Error", result)


# TestBuildTodoContext deleted - _build_todo_context was removed from agent_runtime
