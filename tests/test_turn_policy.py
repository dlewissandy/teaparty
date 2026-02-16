import unittest

from teaparty_app.models import Agent, Conversation, Message, Workgroup, new_id
from teaparty_app.services.turn_policy import (
    TurnDirective,
    determine_next_turns,
    parse_workflow_state,
    advance_workflow_state,
    _parse_workflow_steps,
)


def _make_agent(*, agent_id: str = "a1", name: str = "TestAgent") -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        personality="Professional",
        role="Assistant",
        tool_names=[],
    )


def _make_conversation(
    *,
    conversation_id: str = "conv-1",
    kind: str = "topic",
    name: str = "Test",
) -> Conversation:
    return Conversation(
        id=conversation_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        kind=kind,
    )


def _make_message(
    *,
    message_id: str = "msg-1",
    content: str = "Hello",
    sender_type: str = "user",
) -> Message:
    return Message(
        id=message_id,
        conversation_id="conv-1",
        sender_type=sender_type,
        content=content,
    )


def _make_workgroup(*, workgroup_id: str = "wg-1", files: list | None = None) -> Workgroup:
    return Workgroup(
        id=workgroup_id,
        name="Test WG",
        owner_id="user-1",
        files=files or [],
    )


# Sample workflow from dialectic template
DIALECTIC_WORKFLOW = """\
# Structured Debate

A formal dialectic process.

## Steps

### 1. Frame the Question
- **Agent**: Synthesist
- **Action**: State the question or topic clearly

### 2. Opening Argument
- **Agent**: Proponent
- **Action**: Present initial position

### 3. Counter-Argument
- **Agent**: Opponent
- **Action**: Challenge the position

### 4. Clarifying Questions
- **Agent**: Neophyte
- **Action**: Ask questions for understanding

### 5. Rebuttal Exchange
- **Agent**: Proponent, Opponent
- **Loop**: Until no new substantive points or 3 iterations max
- **Action**: Address each other's arguments

### 6. Synthesis
- **Agent**: Synthesist
- **Action**: Integrate perspectives

### 7. Final Assessment
- **Agent**: Synthesist
- **Completes**: Workflow done.
- **Action**: Provide final assessment
"""


class DetermineNextTurnsTests(unittest.TestCase):
    """Test determine_next_turns function."""

    def test_direct_conversation_single_agent_always_responds(self) -> None:
        conversation = _make_conversation(kind="direct")
        agent = _make_agent(agent_id="a1", name="Helper")
        trigger = _make_message()

        directive = determine_next_turns(conversation, trigger, [agent], None)

        self.assertEqual(directive.agent_ids, ["a1"])
        self.assertTrue(directive.pause_after)
        self.assertEqual(directive.workflow_step_label, "")

    def test_topic_conversation_without_workflow_all_agents_respond(self) -> None:
        conversation = _make_conversation(kind="topic")
        agents = [
            _make_agent(agent_id="a1", name="Alice"),
            _make_agent(agent_id="a2", name="Bob"),
            _make_agent(agent_id="a3", name="Charlie"),
        ]
        trigger = _make_message()

        directive = determine_next_turns(conversation, trigger, agents, None)

        self.assertEqual(directive.agent_ids, ["a1", "a2", "a3"])
        self.assertTrue(directive.pause_after)
        self.assertEqual(directive.workflow_step_label, "")

    def test_empty_agents_list_returns_empty_directive(self) -> None:
        conversation = _make_conversation(kind="topic")
        trigger = _make_message()

        directive = determine_next_turns(conversation, trigger, [], None)

        self.assertEqual(directive.agent_ids, [])
        self.assertTrue(directive.pause_after)

    def test_single_agent_in_topic_conversation_returns_that_agent(self) -> None:
        conversation = _make_conversation(kind="topic")
        agent = _make_agent(agent_id="a1", name="Solo")
        trigger = _make_message()

        directive = determine_next_turns(conversation, trigger, [agent], None)

        self.assertEqual(directive.agent_ids, ["a1"])
        self.assertTrue(directive.pause_after)

    def test_with_active_workflow_uses_step_driven_selection(self) -> None:
        conversation = _make_conversation(kind="topic")
        agents = [
            _make_agent(agent_id="a1", name="Synthesist"),
            _make_agent(agent_id="a2", name="Proponent"),
            _make_agent(agent_id="a3", name="Opponent"),
        ]
        trigger = _make_message()

        workflow_state = {
            "status": "active",
            "current_step": {
                "number": 2,
                "label": "Opening Argument",
                "agents": ["Proponent"],
                "pause_after": True,
            },
        }

        directive = determine_next_turns(conversation, trigger, agents, workflow_state)

        self.assertEqual(directive.agent_ids, ["a2"])  # Proponent
        self.assertTrue(directive.pause_after)
        self.assertEqual(directive.workflow_step_label, "Opening Argument")

    def test_workflow_step_with_multiple_agents(self) -> None:
        conversation = _make_conversation(kind="topic")
        agents = [
            _make_agent(agent_id="a1", name="Proponent"),
            _make_agent(agent_id="a2", name="Opponent"),
        ]
        trigger = _make_message()

        workflow_state = {
            "status": "active",
            "current_step": {
                "number": 5,
                "label": "Rebuttal Exchange",
                "agents": ["Proponent", "Opponent"],
                "pause_after": False,
            },
        }

        directive = determine_next_turns(conversation, trigger, agents, workflow_state)

        self.assertEqual(directive.agent_ids, ["a1", "a2"])
        self.assertFalse(directive.pause_after)

    def test_workflow_step_with_unknown_agent_name_falls_back(self) -> None:
        conversation = _make_conversation(kind="topic")
        agents = [
            _make_agent(agent_id="a1", name="Alice"),
            _make_agent(agent_id="a2", name="Bob"),
        ]
        trigger = _make_message()

        workflow_state = {
            "status": "active",
            "current_step": {
                "number": 1,
                "label": "Opening",
                "agents": ["UnknownAgent"],
                "pause_after": True,
            },
        }

        directive = determine_next_turns(conversation, trigger, agents, workflow_state)

        # Should fallback to first agent
        self.assertEqual(directive.agent_ids, ["a1"])

    def test_completed_workflow_does_not_trigger_step_driven_selection(self) -> None:
        conversation = _make_conversation(kind="topic")
        agents = [
            _make_agent(agent_id="a1", name="Alice"),
            _make_agent(agent_id="a2", name="Bob"),
        ]
        trigger = _make_message()

        workflow_state = {"status": "completed", "current_step": {}}

        directive = determine_next_turns(conversation, trigger, agents, workflow_state)

        # Should fallback to default behavior (all agents)
        self.assertEqual(directive.agent_ids, ["a1", "a2"])


class ParseWorkflowStepsTests(unittest.TestCase):
    """Test _parse_workflow_steps function."""

    def test_parses_dialectic_workflow_steps(self) -> None:
        steps = _parse_workflow_steps(DIALECTIC_WORKFLOW)

        self.assertEqual(len(steps), 7)

        # Step 1: Frame the Question
        self.assertEqual(steps[0]["number"], 1)
        self.assertEqual(steps[0]["label"], "Frame the Question")
        self.assertEqual(steps[0]["agents"], ["Synthesist"])
        self.assertFalse(steps[0]["has_loop"])

        # Step 2: Opening Argument
        self.assertEqual(steps[1]["number"], 2)
        self.assertEqual(steps[1]["label"], "Opening Argument")
        self.assertEqual(steps[1]["agents"], ["Proponent"])

        # Step 3: Counter-Argument
        self.assertEqual(steps[2]["number"], 3)
        self.assertEqual(steps[2]["label"], "Counter-Argument")
        self.assertEqual(steps[2]["agents"], ["Opponent"])

        # Step 4: Clarifying Questions
        self.assertEqual(steps[3]["number"], 4)
        self.assertEqual(steps[3]["label"], "Clarifying Questions")
        self.assertEqual(steps[3]["agents"], ["Neophyte"])

        # Step 5: Rebuttal Exchange (multiple agents, loop)
        self.assertEqual(steps[4]["number"], 5)
        self.assertEqual(steps[4]["label"], "Rebuttal Exchange")
        self.assertEqual(steps[4]["agents"], ["Proponent", "Opponent"])
        self.assertTrue(steps[4]["has_loop"])

        # Step 6: Synthesis
        self.assertEqual(steps[5]["number"], 6)
        self.assertEqual(steps[5]["label"], "Synthesis")
        self.assertEqual(steps[5]["agents"], ["Synthesist"])

        # Step 7: Final Assessment (completes workflow)
        self.assertEqual(steps[6]["number"], 7)
        self.assertEqual(steps[6]["label"], "Final Assessment")
        self.assertEqual(steps[6]["agents"], ["Synthesist"])
        self.assertTrue(steps[6]["pause_after"])

    def test_parses_agent_names_with_commas(self) -> None:
        content = """\
### 1. Discussion
- **Agent**: Alice, Bob, Charlie
"""
        steps = _parse_workflow_steps(content)

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["agents"], ["Alice", "Bob", "Charlie"])

    def test_parses_agent_names_with_and(self) -> None:
        content = """\
### 1. Collaboration
- **Agent**: Alice and Bob
"""
        steps = _parse_workflow_steps(content)

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["agents"], ["Alice", "Bob"])

    def test_handles_missing_agent_line(self) -> None:
        content = """\
### 1. Solo Step
- **Action**: Do something
"""
        steps = _parse_workflow_steps(content)

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["agents"], [])

    def test_handles_loop_marker(self) -> None:
        content = """\
### 1. Iteration
- **Agent**: Worker
- **Loop**: Continue until done
"""
        steps = _parse_workflow_steps(content)

        self.assertEqual(len(steps), 1)
        self.assertTrue(steps[0]["has_loop"])
        self.assertFalse(steps[0]["pause_after"])

    def test_empty_workflow_returns_empty_list(self) -> None:
        steps = _parse_workflow_steps("")
        self.assertEqual(steps, [])

    def test_workflow_without_steps_returns_empty_list(self) -> None:
        content = """\
# My Workflow

Just a description with no steps.
"""
        steps = _parse_workflow_steps(content)
        self.assertEqual(steps, [])


class ParseWorkflowStateTests(unittest.TestCase):
    """Test parse_workflow_state function."""

    def test_returns_none_when_no_workflow_state_file(self) -> None:
        workgroup = _make_workgroup(files=[])
        conversation = _make_conversation()

        result = parse_workflow_state(workgroup, conversation)

        self.assertIsNone(result)

    def test_returns_none_when_workflow_definition_missing(self) -> None:
        workgroup = _make_workgroup(
            files=[
                {
                    "path": "_workflow_state.md",
                    "content": """\
# Workflow State

- **Workflow**: workflows/debate.md
- **Status**: active
- **Current Step**: 2. Opening Argument
""",
                }
            ]
        )
        conversation = _make_conversation()

        result = parse_workflow_state(workgroup, conversation)

        # Should return None because workflow file doesn't exist
        self.assertIsNone(result)

    def test_parses_active_workflow_with_state_and_definition(self) -> None:
        workgroup = _make_workgroup(
            files=[
                {
                    "path": "_workflow_state.md",
                    "content": """\
# Workflow State

- **Workflow**: workflows/debate.md
- **Status**: active
- **Current Step**: 2. Opening Argument
""",
                },
                {"path": "workflows/debate.md", "content": DIALECTIC_WORKFLOW},
            ]
        )
        conversation = _make_conversation()

        result = parse_workflow_state(workgroup, conversation)

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["current_step_number"], 2)
        self.assertEqual(result["current_step"]["label"], "Opening Argument")
        self.assertEqual(result["current_step"]["agents"], ["Proponent"])
        self.assertEqual(len(result["steps"]), 7)
        self.assertEqual(result["workflow_path"], "workflows/debate.md")

    def test_parses_completed_workflow(self) -> None:
        workgroup = _make_workgroup(
            files=[
                {
                    "path": "_workflow_state.md",
                    "content": """\
# Workflow State

- **Workflow**: workflows/debate.md
- **Status**: completed
- **Current Step**: (done)
""",
                },
                {"path": "workflows/debate.md", "content": DIALECTIC_WORKFLOW},
            ]
        )
        conversation = _make_conversation()

        result = parse_workflow_state(workgroup, conversation)

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["current_step"], {})

    def test_filters_to_topic_scoped_workflow_state(self) -> None:
        conversation = _make_conversation(conversation_id="topic-123", kind="topic")
        workgroup = _make_workgroup(
            files=[
                {
                    "path": "_workflow_state.md",
                    "content": "# Workflow State\n- **Workflow**: workflows/debate.md\n- **Status**: active\n- **Current Step**: 1. Frame",
                    "topic_id": "topic-456",  # Different topic
                },
                {
                    "path": "_workflow_state.md",
                    "content": "# Workflow State\n- **Workflow**: workflows/debate.md\n- **Status**: active\n- **Current Step**: 3. Counter-Argument",
                    "topic_id": "topic-123",  # Matching topic
                },
                {"path": "workflows/debate.md", "content": DIALECTIC_WORKFLOW},
            ]
        )

        result = parse_workflow_state(workgroup, conversation)

        self.assertIsNotNone(result)
        self.assertEqual(result["current_step_number"], 3)

    def test_defaults_to_step_1_if_current_step_not_found(self) -> None:
        workgroup = _make_workgroup(
            files=[
                {
                    "path": "_workflow_state.md",
                    "content": """\
# Workflow State

- **Workflow**: workflows/debate.md
- **Status**: active
- **Current Step**: 99. NonExistent
""",
                },
                {"path": "workflows/debate.md", "content": DIALECTIC_WORKFLOW},
            ]
        )
        conversation = _make_conversation()

        result = parse_workflow_state(workgroup, conversation)

        self.assertIsNotNone(result)
        self.assertEqual(result["current_step"]["number"], 1)


class AdvanceWorkflowStateTests(unittest.TestCase):
    """Test advance_workflow_state function."""

    def test_advances_to_next_step(self) -> None:
        workgroup = _make_workgroup()
        conversation = _make_conversation()

        workflow_state = {
            "status": "active",
            "current_step_number": 2,
            "workflow_path": "workflows/debate.md",
            "steps": [
                {"number": 1, "label": "Frame", "agents": ["A"]},
                {"number": 2, "label": "Opening", "agents": ["B"]},
                {"number": 3, "label": "Counter", "agents": ["C"]},
            ],
        }

        updated_state = advance_workflow_state(workgroup, conversation, workflow_state)

        self.assertIsNotNone(updated_state)
        self.assertIn("Current Step**: 3. Counter", updated_state)
        self.assertIn("Status**: active", updated_state)

    def test_completes_workflow_when_no_next_step(self) -> None:
        workgroup = _make_workgroup()
        conversation = _make_conversation()

        workflow_state = {
            "status": "active",
            "current_step_number": 3,
            "workflow_path": "workflows/debate.md",
            "steps": [
                {"number": 1, "label": "Frame", "agents": ["A"]},
                {"number": 2, "label": "Opening", "agents": ["B"]},
                {"number": 3, "label": "Final", "agents": ["C"]},
            ],
        }

        updated_state = advance_workflow_state(workgroup, conversation, workflow_state)

        self.assertIsNotNone(updated_state)
        self.assertIn("Status**: completed", updated_state)
        self.assertIn("Current Step**: (done)", updated_state)

    def test_preserves_workflow_path_in_updated_state(self) -> None:
        workgroup = _make_workgroup()
        conversation = _make_conversation()

        workflow_state = {
            "status": "active",
            "current_step_number": 1,
            "workflow_path": "workflows/custom-workflow.md",
            "steps": [
                {"number": 1, "label": "First", "agents": ["A"]},
                {"number": 2, "label": "Second", "agents": ["B"]},
            ],
        }

        updated_state = advance_workflow_state(workgroup, conversation, workflow_state)

        self.assertIn("workflows/custom-workflow.md", updated_state)


if __name__ == "__main__":
    unittest.main()
