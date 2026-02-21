import unittest
from unittest.mock import MagicMock, patch

from teaparty_app.models import Agent, Conversation, Workgroup
from teaparty_app.services.workflow_helpers import (
    auto_select_workflow,
    _extract_workflow_title_and_trigger,
)


def _make_agent(
    *,
    agent_id: str = "a1",
    name: str = "TestAgent",
    tools: list[str] | None = None,
) -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        prompt="Engineer. Professional.",
        tools=tools or [],
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
    @patch("teaparty_app.services.workflow_helpers._match_workflow_to_job")
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
    @patch("teaparty_app.services.workflow_helpers._match_workflow_to_job")
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

        from teaparty_app.services.workflow_helpers import _match_workflow_to_job

        result = _match_workflow_to_job(
            session, "conv-1", "Something", "",
            [
                {"path": "workflows/code-review.md", "title": "Code Review", "trigger": "code review"},
                {"path": "workflows/feature-build.md", "title": "Feature Build", "trigger": "build a feature"},
            ],
        )
        self.assertIsNone(result)
