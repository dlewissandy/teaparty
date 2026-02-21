import unittest

from teaparty_app.models import Agent, Conversation, Workgroup
from teaparty_app.services.agent_definition import (
    build_agent_json,
    build_worktree_settings_json,
    slugify,
)


def _make_agent(
    *,
    agent_id: str = "a1",
    name: str = "Implementer",
    role: str = "Implementation lead",
    personality: str = "Practical and concise",
    backstory: str = "",
    model: str = "sonnet",
    max_turns: int = 3,
    is_lead: bool = False,
) -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        role=role,
        personality=personality,
        backstory=backstory,
        model=model,
        max_turns=max_turns,
        tool_names=[],
        is_lead=is_lead,
    )


def _make_conversation(
    *,
    conversation_id: str = "conv-1",
    name: str = "Feature Build",
    description: str = "Building the auth module",
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
        name="Coding Team",
        owner_id="user-1",
        files=files or [],
    )


class SlugifyTests(unittest.TestCase):
    """Test the slugify helper."""

    def test_simple_name(self) -> None:
        self.assertEqual(slugify("Implementer"), "implementer")

    def test_name_with_spaces(self) -> None:
        self.assertEqual(slugify("Code Reviewer"), "code-reviewer")

    def test_name_with_special_chars(self) -> None:
        self.assertEqual(slugify("Agent #1 (Main)"), "agent-1-main")

    def test_empty_string(self) -> None:
        self.assertEqual(slugify(""), "agent")

    def test_unicode_name(self) -> None:
        result = slugify("Agent-Über")
        self.assertTrue(result)
        self.assertNotIn(" ", result)


class BuildAgentJsonTests(unittest.TestCase):
    """Test agent JSON generation for --agents flag."""

    def test_basic_agent_json(self) -> None:
        agent = _make_agent()
        conversation = _make_conversation()

        result = build_agent_json(agent, conversation)

        self.assertEqual(result["description"], "Implementation lead")
        self.assertEqual(result["model"], "sonnet")
        self.assertEqual(result["maxTurns"], 3)
        self.assertIn("You are Implementer", result["prompt"])
        self.assertIn("Role: Implementation lead", result["prompt"])
        self.assertIn("Personality: Practical and concise", result["prompt"])

    def test_model_alias_mapping(self) -> None:
        agent = _make_agent(model="sonnet")
        conversation = _make_conversation()
        result = build_agent_json(agent, conversation)
        self.assertEqual(result["model"], "sonnet")

        agent2 = _make_agent(model="haiku")
        result2 = build_agent_json(agent2, conversation)
        self.assertEqual(result2["model"], "haiku")

        agent3 = _make_agent(model="opus")
        result3 = build_agent_json(agent3, conversation)
        self.assertEqual(result3["model"], "opus")

    def test_unknown_model_passes_through(self) -> None:
        agent = _make_agent(model="custom-model-v1")
        conversation = _make_conversation()
        result = build_agent_json(agent, conversation)
        self.assertEqual(result["model"], "custom-model-v1")

    def test_max_turns_from_agent(self) -> None:
        agent = _make_agent(max_turns=20)
        conversation = _make_conversation()
        result = build_agent_json(agent, conversation)
        self.assertEqual(result["maxTurns"], 20)

    def test_max_turns_defaults_to_3(self) -> None:
        agent = _make_agent()
        agent.max_turns = 0  # Edge case
        conversation = _make_conversation()
        result = build_agent_json(agent, conversation)
        self.assertEqual(result["maxTurns"], 3)

    def test_conversation_context_in_prompt(self) -> None:
        agent = _make_agent()
        conversation = _make_conversation(
            name="Auth Module",
            description="Implementing OAuth2",
            kind="job",
        )
        result = build_agent_json(agent, conversation)
        self.assertIn("job discussion", result["prompt"])
        self.assertIn("Job: Auth Module", result["prompt"])
        self.assertIn("Description: Implementing OAuth2", result["prompt"])

    def test_files_context_in_prompt(self) -> None:
        agent = _make_agent()
        conversation = _make_conversation()
        result = build_agent_json(
            agent, conversation,
            files_context="Reference files:\n--- README.md ---\nProject overview",
        )
        self.assertIn("Reference files:", result["prompt"])
        self.assertIn("README.md", result["prompt"])

    def test_description_fallback_chain(self) -> None:
        # Uses description first
        agent = _make_agent(role="Code Reviewer")
        agent.description = "Reviews code quality"
        conversation = _make_conversation()
        result = build_agent_json(agent, conversation)
        self.assertEqual(result["description"], "Reviews code quality")

        # Falls back to role
        agent2 = _make_agent(role="Architect")
        agent2.description = ""
        result2 = build_agent_json(agent2, conversation)
        self.assertEqual(result2["description"], "Architect")

        # Falls back to name
        agent3 = _make_agent(name="Bob", role="")
        agent3.description = ""
        result3 = build_agent_json(agent3, conversation)
        self.assertEqual(result3["description"], "Bob")

    def test_guidelines_always_present(self) -> None:
        agent = _make_agent()
        conversation = _make_conversation()
        result = build_agent_json(agent, conversation)
        self.assertIn("Guidelines:", result["prompt"])
        self.assertIn("Be direct and substantive", result["prompt"])

    def test_workflows_not_injected_into_prompt(self) -> None:
        """Workflows are just files — not injected into agent prompts."""
        agent = _make_agent(name="Reviewer")
        conversation = _make_conversation()
        workgroup = _make_workgroup(files=[
            {
                "path": "workflows/code-review.md",
                "content": "# Code Review\n\n## Steps\n### 1. Analyze\n- **Agent**: Reviewer",
            },
        ])
        result = build_agent_json(agent, conversation, workgroup=workgroup)
        self.assertNotIn("Active Workflow", result["prompt"])
        self.assertNotIn("Available Workflows", result["prompt"])
        self.assertNotIn("Code Review", result["prompt"])


class BuildWorktreeSettingsJsonTests(unittest.TestCase):
    """Test hook settings generation."""

    def test_generates_valid_json(self) -> None:
        import json
        result = build_worktree_settings_json("/tmp/test-worktree")
        parsed = json.loads(result)
        self.assertIn("hooks", parsed)
        self.assertIn("PreToolUse", parsed["hooks"])

    def test_includes_worktree_path_in_hook_command(self) -> None:
        result = build_worktree_settings_json("/tmp/my-worktree")
        self.assertIn("/tmp/my-worktree", result)

    def test_matches_file_tools(self) -> None:
        import json
        result = build_worktree_settings_json("/tmp/test")
        parsed = json.loads(result)
        matcher = parsed["hooks"]["PreToolUse"][0]["matcher"]
        self.assertIn("Edit", matcher)
        self.assertIn("Write", matcher)
        self.assertIn("Read", matcher)
        self.assertIn("Glob", matcher)
        self.assertIn("Grep", matcher)


if __name__ == "__main__":
    unittest.main()
