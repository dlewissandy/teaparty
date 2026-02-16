import unittest
from unittest.mock import patch

from teaparty_app.models import Agent, Conversation, Membership, Message, Workgroup
from teaparty_app.services.claude_code import (
    _build_system_prompt,
    _tool_create_file,
    _tool_edit_file,
    _tool_list_files,
    _tool_read_file,
    _dispatch_tool,
    claude_code,
)
from teaparty_app.services.tools import available_tools, run_tool


def _admin_conv() -> Conversation:
    return Conversation(id="admin-c", workgroup_id="wg-1", kind="admin", created_by_user_id="u1")


class ClaudeCodeToolListFilesTests(unittest.TestCase):
    def test_list_files_empty(self) -> None:
        wg = Workgroup(id="wg-1", name="Test", owner_id="u1", files=[])
        self.assertEqual(_tool_list_files(wg, _admin_conv()), "No files in this workgroup.")

    def test_list_files_returns_sorted_paths(self) -> None:
        wg = Workgroup(
            id="wg-1", name="Test", owner_id="u1",
            files=[
                {"id": "1", "path": "src/main.py", "content": "code"},
                {"id": "2", "path": "README.md", "content": "readme"},
            ],
        )
        result = _tool_list_files(wg, _admin_conv())
        self.assertEqual(result, "README.md\nsrc/main.py")


class ClaudeCodeToolReadFileTests(unittest.TestCase):
    def test_read_existing_file(self) -> None:
        wg = Workgroup(
            id="wg-1", name="Test", owner_id="u1",
            files=[{"id": "1", "path": "notes.md", "content": "hello world"}],
        )
        self.assertEqual(_tool_read_file(wg, _admin_conv(), "notes.md"), "hello world")

    def test_read_empty_file(self) -> None:
        wg = Workgroup(
            id="wg-1", name="Test", owner_id="u1",
            files=[{"id": "1", "path": "empty.txt", "content": ""}],
        )
        self.assertEqual(_tool_read_file(wg, _admin_conv(), "empty.txt"), "(empty file)")

    def test_read_missing_file(self) -> None:
        wg = Workgroup(id="wg-1", name="Test", owner_id="u1", files=[])
        result = _tool_read_file(wg, _admin_conv(), "nope.txt")
        self.assertIn("not found", result)


class ClaudeCodeToolCreateFileTests(unittest.TestCase):
    def test_create_file_success(self) -> None:
        wg = Workgroup(id="wg-1", name="Test", owner_id="u1", files=[])
        session = _FakeSession()
        result = _tool_create_file(session, wg, _admin_conv(), "wg-1", "agent-1", "new.py", "print('hi')")
        self.assertIn("Created", result)
        self.assertEqual(len(wg.files), 1)
        self.assertEqual(wg.files[0]["path"], "new.py")
        self.assertEqual(wg.files[0]["content"], "print('hi')")

    def test_create_file_duplicate(self) -> None:
        wg = Workgroup(
            id="wg-1", name="Test", owner_id="u1",
            files=[{"id": "1", "path": "existing.py", "content": "code"}],
        )
        session = _FakeSession()
        result = _tool_create_file(session, wg, _admin_conv(), "wg-1", "agent-1", "existing.py", "new code")
        self.assertIn("already exists", result)

    def test_create_file_path_too_long(self) -> None:
        wg = Workgroup(id="wg-1", name="Test", owner_id="u1", files=[])
        session = _FakeSession()
        result = _tool_create_file(session, wg, _admin_conv(), "wg-1", "agent-1", "x" * 513, "content")
        self.assertIn("512 characters", result)

    def test_create_file_content_too_large(self) -> None:
        wg = Workgroup(id="wg-1", name="Test", owner_id="u1", files=[])
        session = _FakeSession()
        result = _tool_create_file(session, wg, _admin_conv(), "wg-1", "agent-1", "big.txt", "x" * 200_001)
        self.assertIn("200000 characters", result)


class ClaudeCodeToolEditFileTests(unittest.TestCase):
    def test_edit_file_success(self) -> None:
        wg = Workgroup(
            id="wg-1", name="Test", owner_id="u1",
            files=[{"id": "1", "path": "app.py", "content": "old"}],
        )
        session = _FakeSession()
        result = _tool_edit_file(session, wg, _admin_conv(), "wg-1", "agent-1", "app.py", "new code")
        self.assertIn("Updated", result)
        self.assertEqual(wg.files[0]["content"], "new code")

    def test_edit_file_not_found(self) -> None:
        wg = Workgroup(id="wg-1", name="Test", owner_id="u1", files=[])
        session = _FakeSession()
        result = _tool_edit_file(session, wg, _admin_conv(), "wg-1", "agent-1", "missing.py", "code")
        self.assertIn("not found", result)


class ClaudeCodeDispatchTests(unittest.TestCase):
    def test_dispatch_list_files(self) -> None:
        wg = Workgroup(id="wg-1", name="Test", owner_id="u1", files=[])
        session = _FakeSession()
        result = _dispatch_tool("list_files", {}, session, wg, _admin_conv(), "wg-1", "a1")
        self.assertEqual(result, "No files in this workgroup.")

    def test_dispatch_unknown_tool(self) -> None:
        wg = Workgroup(id="wg-1", name="Test", owner_id="u1", files=[])
        session = _FakeSession()
        result = _dispatch_tool("nope", {}, session, wg, _admin_conv(), "wg-1", "a1")
        self.assertIn("unknown tool", result)


class ClaudeCodeAccessControlTests(unittest.TestCase):
    def test_rejects_agent_trigger(self) -> None:
        trigger = Message(
            conversation_id="c1", sender_type="agent",
            sender_agent_id="a1", content="write code",
        )
        result = claude_code(None, None, None, trigger)  # type: ignore[arg-type]
        self.assertIn("requires a direct user request", result)

    def test_rejects_non_owner(self) -> None:
        trigger = Message(
            conversation_id="c1", sender_type="user",
            sender_user_id="u1", content="write code",
        )
        conversation = Conversation(
            id="c1", workgroup_id="wg-1",
            created_by_user_id="u1", kind="direct", topic="coding",
        )
        membership = Membership(
            id="m1", workgroup_id="wg-1", user_id="u1", role="member",
        )
        session = _FakeSession(membership=membership)
        agent = Agent(
            id="a1", workgroup_id="wg-1", created_by_user_id="u1",
            name="Coder", tool_names=["claude_code"],
        )
        result = claude_code(session, agent, conversation, trigger)
        self.assertIn("Only the workgroup owner", result)

    def test_rejects_missing_api_key(self) -> None:
        trigger = Message(
            conversation_id="c1", sender_type="user",
            sender_user_id="u1", content="write code",
        )
        conversation = Conversation(
            id="c1", workgroup_id="wg-1",
            created_by_user_id="u1", kind="direct", topic="coding",
        )
        membership = Membership(
            id="m1", workgroup_id="wg-1", user_id="u1", role="owner",
        )
        workgroup = Workgroup(id="wg-1", name="Test", owner_id="u1", files=[])
        session = _FakeSession(membership=membership, workgroup=workgroup)
        agent = Agent(
            id="a1", workgroup_id="wg-1", created_by_user_id="u1",
            name="Coder", tool_names=["claude_code"],
        )
        with patch("teaparty_app.services.llm_client.llm_enabled", return_value=False):
            result = claude_code(session, agent, conversation, trigger)
        self.assertIn("no LLM provider configured", result)


class ClaudeCodeSystemPromptTests(unittest.TestCase):
    def test_system_prompt_contains_workgroup_name(self) -> None:
        agent = Agent(
            id="a1", workgroup_id="wg-1", created_by_user_id="u1",
            name="Coder", role="backend developer",
        )
        conversation = Conversation(
            id="c1", workgroup_id="wg-1",
            created_by_user_id="u1", topic="feature-x",
        )
        wg = Workgroup(id="wg-1", name="MyProject", owner_id="u1", files=[])
        prompt = _build_system_prompt(agent, conversation, wg)
        self.assertIn("MyProject", prompt)
        self.assertIn("Coder", prompt)
        self.assertIn("backend developer", prompt)
        self.assertIn("feature-x", prompt)


class ClaudeCodeRegistrationTests(unittest.TestCase):
    def test_available_tools_includes_claude_code(self) -> None:
        tools = available_tools()
        self.assertIn("claude_code", tools)


class _FakeSession:
    """Minimal session stub for unit tests that don't need a real database."""

    def __init__(
        self,
        *,
        membership: Membership | None = None,
        workgroup: Workgroup | None = None,
    ) -> None:
        self._membership = membership
        self._workgroup = workgroup
        self.added: list = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def exec(self, statement: object) -> "_FakeResult":
        return _FakeResult(self._membership)

    def get(self, model_class: type, pk: str) -> object | None:
        if model_class is Workgroup and self._workgroup:
            return self._workgroup
        return None


class _FakeResult:
    def __init__(self, value: object = None) -> None:
        self._value = value

    def first(self) -> object | None:
        return self._value

    def all(self) -> list:
        return [self._value] if self._value else []
