import unittest
from unittest.mock import MagicMock, patch

from teaparty_app.models import Agent, Conversation, Workgroup
from teaparty_app.services.agent_tools import (
    AGENT_TOOL_SCHEMAS,
    auto_select_workflow,
    dispatch_agent_tool,
    _extract_workflow_title_and_trigger,
    _tool_list_workflows,
    _tool_get_workflow_state,
    _tool_advance_workflow,
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
        personality="Professional",
        role="Engineer",
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
):
    from teaparty_app.models import Message
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


SAMPLE_WORKFLOW_CONTENT = """\
# Code Review

A structured code review process.

## Trigger
When a user requests a code review or submits code for feedback.

## Steps

### 1. Acknowledge and Scope
- **Agent**: Reviewer
- **Action**: Read the submitted code.
"""

SAMPLE_STATE_CONTENT = """\
# Workflow State

- **Workflow**: workflows/code-review.md
- **Started**: 2024-01-15T10:30:00Z
- **Status**: in_progress
- **Current Step**: 2

## Step Log
- [x] 1. Acknowledge and Scope -- completed by Reviewer
- [ ] 2. Structural Analysis -- in_progress by Reviewer
"""


class TestListWorkflows(unittest.TestCase):
    def test_returns_workflows_with_titles_and_triggers(self) -> None:
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "workflows/code-review.md", "content": SAMPLE_WORKFLOW_CONTENT, "topic_id": ""},
        ])
        conversation = _make_conversation()
        result = _tool_list_workflows(workgroup, conversation)
        self.assertIn("Available workflows", result)
        self.assertIn("Code Review", result)
        self.assertIn("workflows/code-review.md", result)
        self.assertIn("code review", result.lower())

    def test_excludes_readme(self) -> None:
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "workflows/README.md", "content": "# Workflows\n", "topic_id": ""},
            {"id": "f2", "path": "workflows/code-review.md", "content": SAMPLE_WORKFLOW_CONTENT, "topic_id": ""},
        ])
        conversation = _make_conversation()
        result = _tool_list_workflows(workgroup, conversation)
        self.assertIn("Code Review", result)
        self.assertNotIn("README", result)

    def test_returns_message_when_no_workflows(self) -> None:
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "workflows/README.md", "content": "# Workflows\n", "topic_id": ""},
        ])
        conversation = _make_conversation()
        result = _tool_list_workflows(workgroup, conversation)
        self.assertIn("No workflows defined", result)

    def test_handles_empty_files(self) -> None:
        workgroup = _make_workgroup(files=[])
        conversation = _make_conversation()
        result = _tool_list_workflows(workgroup, conversation)
        self.assertIn("No workflows defined", result)

    def test_multiple_workflows(self) -> None:
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "workflows/code-review.md", "content": SAMPLE_WORKFLOW_CONTENT, "topic_id": ""},
            {"id": "f2", "path": "workflows/feature-build.md", "content": "# Feature Build\n\n## Trigger\nWhen building a feature.\n", "topic_id": ""},
        ])
        conversation = _make_conversation()
        result = _tool_list_workflows(workgroup, conversation)
        self.assertIn("Code Review", result)
        self.assertIn("Feature Build", result)


class TestGetWorkflowState(unittest.TestCase):
    def test_returns_state_when_present(self) -> None:
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "_workflow_state.md", "content": SAMPLE_STATE_CONTENT, "topic_id": "conv-1"},
        ])
        conversation = _make_conversation()
        result = _tool_get_workflow_state(workgroup, conversation)
        self.assertIn("Workflow State", result)
        self.assertIn("in_progress", result)

    def test_returns_no_active_workflow_when_absent(self) -> None:
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "README.md", "content": "hello", "topic_id": ""},
        ])
        conversation = _make_conversation()
        result = _tool_get_workflow_state(workgroup, conversation)
        self.assertEqual(result, "No active workflow.")

    def test_returns_empty_state_message(self) -> None:
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "_workflow_state.md", "content": "", "topic_id": "conv-1"},
        ])
        conversation = _make_conversation()
        result = _tool_get_workflow_state(workgroup, conversation)
        self.assertEqual(result, "(empty state file)")


class TestAdvanceWorkflow(unittest.TestCase):
    def test_creates_new_state_file(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        conversation = _make_conversation()
        result = _tool_advance_workflow(session, workgroup, conversation, "a1", SAMPLE_STATE_CONTENT)
        self.assertIn("Created", result)
        self.assertIn("_workflow_state.md", result)
        # Verify file was added to workgroup
        self.assertEqual(len(workgroup.files), 1)
        self.assertEqual(workgroup.files[0]["path"], "_workflow_state.md")
        self.assertEqual(workgroup.files[0]["content"], SAMPLE_STATE_CONTENT)
        self.assertEqual(workgroup.files[0]["topic_id"], "conv-1")

    def test_updates_existing_state_file(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "_workflow_state.md", "content": "old state", "topic_id": "conv-1"},
        ])
        conversation = _make_conversation()
        new_state = "# Updated State\n- **Status**: completed\n"
        result = _tool_advance_workflow(session, workgroup, conversation, "a1", new_state)
        self.assertIn("Updated", result)
        # Verify content was updated
        updated = [f for f in workgroup.files if f["path"] == "_workflow_state.md"]
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["content"], new_state)

    def test_rejects_empty_content(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        conversation = _make_conversation()
        result = _tool_advance_workflow(session, workgroup, conversation, "a1", "")
        self.assertIn("Error", result)
        self.assertIn("required", result)

    def test_rejects_whitespace_only_content(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        conversation = _make_conversation()
        result = _tool_advance_workflow(session, workgroup, conversation, "a1", "   \n  ")
        self.assertIn("Error", result)

    def test_job_scoped_for_job_conversations(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        conversation = _make_conversation(kind="job", conversation_id="topic-123")
        _tool_advance_workflow(session, workgroup, conversation, "a1", "state content")
        self.assertEqual(workgroup.files[0]["topic_id"], "topic-123")

    def test_not_job_scoped_for_admin_conversations(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        conversation = _make_conversation(kind="admin", conversation_id="admin-1")
        _tool_advance_workflow(session, workgroup, conversation, "a1", "state content")
        self.assertEqual(workgroup.files[0]["topic_id"], "")


class TestDispatchWorkflowTools(unittest.TestCase):
    def test_dispatch_list_workflows(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "workflows/code-review.md", "content": SAMPLE_WORKFLOW_CONTENT, "topic_id": ""},
        ])
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["list_workflows"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(session, agent, conversation, trigger, "list_workflows", {})
        self.assertIn("Code Review", result)

    def test_dispatch_get_workflow_state(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "_workflow_state.md", "content": SAMPLE_STATE_CONTENT, "topic_id": "conv-1"},
        ])
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["get_workflow_state"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(session, agent, conversation, trigger, "get_workflow_state", {})
        self.assertIn("Workflow State", result)

    def test_dispatch_advance_workflow(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        session.get.return_value = workgroup
        agent = _make_agent(tool_names=["advance_workflow"])
        conversation = _make_conversation()
        trigger = _make_message()

        result = dispatch_agent_tool(
            session, agent, conversation, trigger,
            "advance_workflow", {"state_content": SAMPLE_STATE_CONTENT},
        )
        self.assertIn("Created", result)


class TestWorkflowSchemas(unittest.TestCase):
    def test_list_workflows_schema_exists(self) -> None:
        schema = next((s for s in AGENT_TOOL_SCHEMAS if s["name"] == "list_workflows"), None)
        self.assertIsNotNone(schema)
        self.assertEqual(schema["input_schema"]["type"], "object")
        self.assertEqual(schema["input_schema"]["required"], [])

    def test_get_workflow_state_schema_exists(self) -> None:
        schema = next((s for s in AGENT_TOOL_SCHEMAS if s["name"] == "get_workflow_state"), None)
        self.assertIsNotNone(schema)
        self.assertEqual(schema["input_schema"]["type"], "object")
        self.assertEqual(schema["input_schema"]["required"], [])

    def test_advance_workflow_schema_exists(self) -> None:
        schema = next((s for s in AGENT_TOOL_SCHEMAS if s["name"] == "advance_workflow"), None)
        self.assertIsNotNone(schema)
        self.assertIn("state_content", schema["input_schema"]["properties"])
        self.assertIn("state_content", schema["input_schema"]["required"])


# TestBuildWorkflowContext and TestBuildWorkflowHint deleted - functions moved from agent_runtime


SAMPLE_FEATURE_BUILD_CONTENT = """\
# Feature Build

Build a new feature end to end.

## Trigger
When a user wants to build or implement a new feature.

## Steps

### 1. Scope
- **Agent**: Any
- **Action**: Define scope and requirements.
"""


class TestExtractWorkflowTitleAndTrigger(unittest.TestCase):
    def test_extracts_title_and_trigger(self) -> None:
        title, trigger = _extract_workflow_title_and_trigger(SAMPLE_WORKFLOW_CONTENT)
        self.assertEqual(title, "Code Review")
        self.assertIn("code review", trigger.lower())

    def test_empty_content(self) -> None:
        title, trigger = _extract_workflow_title_and_trigger("")
        self.assertEqual(title, "")
        self.assertEqual(trigger, "")

    def test_no_trigger_section(self) -> None:
        title, trigger = _extract_workflow_title_and_trigger("# My Workflow\n\nSome text.")
        self.assertEqual(title, "My Workflow")
        self.assertEqual(trigger, "")


class TestAutoSelectNoWorkflows(unittest.TestCase):
    def test_returns_none_no_state_created(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[])
        conversation = _make_conversation(topic="Design Review")
        result = auto_select_workflow(session, workgroup, conversation)
        self.assertIsNone(result)
        # No file should have been added
        self.assertEqual(workgroup.files, [])


class TestAutoSelectSingleWorkflow(unittest.TestCase):
    def test_auto_selects_the_one_workflow(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "workflows/code-review.md", "content": SAMPLE_WORKFLOW_CONTENT, "topic_id": ""},
        ])
        conversation = _make_conversation(topic="Review my PR")
        result = auto_select_workflow(session, workgroup, conversation)
        self.assertEqual(result, "workflows/code-review.md")
        # State file should be created
        state_files = [f for f in workgroup.files if f["path"] == "_workflow_state.md"]
        self.assertEqual(len(state_files), 1)
        self.assertIn("workflows/code-review.md", state_files[0]["content"])
        self.assertEqual(state_files[0]["topic_id"], conversation.id)


class TestAutoSelectMultipleWorkflowsLLMMatch(unittest.TestCase):
    @patch("teaparty_app.services.agent_tools._match_workflow_to_job")
    def test_returns_llm_matched_workflow(self, mock_match: MagicMock) -> None:
        mock_match.return_value = "workflows/feature-build.md"
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "workflows/code-review.md", "content": SAMPLE_WORKFLOW_CONTENT, "topic_id": ""},
            {"id": "f2", "path": "workflows/feature-build.md", "content": SAMPLE_FEATURE_BUILD_CONTENT, "topic_id": ""},
        ])
        conversation = _make_conversation(topic="Build a login page")
        result = auto_select_workflow(session, workgroup, conversation)
        self.assertEqual(result, "workflows/feature-build.md")
        mock_match.assert_called_once()
        state_files = [f for f in workgroup.files if f["path"] == "_workflow_state.md"]
        self.assertEqual(len(state_files), 1)
        self.assertIn("workflows/feature-build.md", state_files[0]["content"])


class TestAutoSelectMultipleWorkflowsNoMatch(unittest.TestCase):
    @patch("teaparty_app.services.agent_tools._match_workflow_to_job")
    def test_returns_none_when_no_confident_match(self, mock_match: MagicMock) -> None:
        mock_match.return_value = None
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "workflows/code-review.md", "content": SAMPLE_WORKFLOW_CONTENT, "topic_id": ""},
            {"id": "f2", "path": "workflows/feature-build.md", "content": SAMPLE_FEATURE_BUILD_CONTENT, "topic_id": ""},
        ])
        conversation = _make_conversation(topic="Random chat")
        result = auto_select_workflow(session, workgroup, conversation)
        self.assertIsNone(result)
        # No state file should be created
        state_files = [f for f in workgroup.files if f["path"] == "_workflow_state.md"]
        self.assertEqual(len(state_files), 0)


class TestAutoSelectStateIsJobScoped(unittest.TestCase):
    def test_state_has_topic_id(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "workflows/code-review.md", "content": SAMPLE_WORKFLOW_CONTENT, "topic_id": ""},
        ])
        conversation = _make_conversation(conversation_id="topic-999", topic="Review PR")
        auto_select_workflow(session, workgroup, conversation)
        state_files = [f for f in workgroup.files if f["path"] == "_workflow_state.md"]
        self.assertEqual(len(state_files), 1)
        self.assertEqual(state_files[0]["topic_id"], "topic-999")


class TestAutoSelectSkipsReadme(unittest.TestCase):
    def test_readme_not_treated_as_workflow(self) -> None:
        session = MagicMock()
        workgroup = _make_workgroup(files=[
            {"id": "f1", "path": "workflows/README.md", "content": "# Workflows\n", "topic_id": ""},
        ])
        conversation = _make_conversation(topic="Some topic")
        result = auto_select_workflow(session, workgroup, conversation)
        self.assertIsNone(result)


class TestAutoSelectLLMErrorReturnsNone(unittest.TestCase):
    @patch("teaparty_app.services.llm_client.create_message")
    def test_llm_failure_returns_none(self, mock_create: MagicMock) -> None:
        mock_create.side_effect = Exception("API down")
        session = MagicMock()

        from teaparty_app.services.agent_tools import _match_workflow_to_job

        result = _match_workflow_to_job(
            session, "conv-1", "Something", "",
            [
                {"path": "workflows/code-review.md", "title": "Code Review", "trigger": "code review"},
                {"path": "workflows/feature-build.md", "title": "Feature Build", "trigger": "build a feature"},
            ],
        )
        self.assertIsNone(result)
