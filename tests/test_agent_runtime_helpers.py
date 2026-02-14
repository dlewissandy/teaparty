import unittest

from teaparty_app.models import Agent
from teaparty_app.services.agent_runtime import (
    _build_chain_selector_guidance,
    _extract_file_tool_command,
    _extract_json_object,
    _extract_web_search_reply,
    _is_valid_file_tool_command,
    _model_supports_temperature,
    _normalize_agent_reply_text,
    _role_identity_bonus,
    _runtime_model_candidates,
    _select_tool,
    _topic_relevance_bonus,
    _trim_to_sentences,
    _trim_to_words,
    infer_requires_response,
)


def _make_agent(
    *,
    agent_id: str,
    name: str,
    tool_names: list[str] | None = None,
    personality: str = "Professional and concise",
    role: str = "",
    backstory: str = "",
    verbosity: float = 0.5,
    learning_state: dict[str, float] | None = None,
) -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        personality=personality,
        role=role,
        backstory=backstory,
        tool_names=tool_names or [],
        verbosity=verbosity,
        learning_state=learning_state or {},
    )


class AgentRuntimeHelperTests(unittest.TestCase):
    def test_infer_requires_response_detects_question_like_content(self) -> None:
        self.assertTrue(infer_requires_response("Can you summarize this thread"))
        self.assertTrue(infer_requires_response("Status update?"))
        self.assertFalse(infer_requires_response("Posted the update in the doc."))

    def test_select_tool_uses_pattern_and_file_path_fallback(self) -> None:
        list_agent = _make_agent(agent_id="a1", name="Alex", tool_names=["list_files"])
        self.assertEqual(_select_tool(list_agent, "Could you list files for this workgroup?"), "list_files")

        edit_agent = _make_agent(agent_id="a2", name="Alex", tool_names=["edit_file"])
        self.assertEqual(_select_tool(edit_agent, "Please update docs/plan.md with the latest milestones"), "edit_file")

        no_tool_agent = _make_agent(agent_id="a3", name="Alex", tool_names=["summarize_topic"])
        self.assertIsNone(_select_tool(no_tool_agent, "Please update docs/plan.md with the latest milestones"))

    def test_validate_file_tool_commands(self) -> None:
        self.assertTrue(_is_valid_file_tool_command("add_file", "add file notes.md content=hello"))
        self.assertFalse(_is_valid_file_tool_command("add_file", "add file notes.md"))
        self.assertFalse(_is_valid_file_tool_command("unknown", "anything"))

    def test_extract_file_tool_command_from_json_and_plain_text(self) -> None:
        self.assertEqual(
            _extract_file_tool_command('{"command":"rename file a.txt to b.txt"}'),
            "rename file a.txt to b.txt",
        )
        self.assertEqual(_extract_file_tool_command("list files\nthen share results"), "list files")

    def test_extract_json_object_handles_fenced_and_embedded_json(self) -> None:
        self.assertEqual(_extract_json_object("```json\n{\"a\":1}\n```"), {"a": 1})
        self.assertEqual(_extract_json_object("prefix {\"b\":2} suffix"), {"b": 2})
        self.assertIsNone(_extract_json_object("not json"))

    def test_runtime_model_candidates_are_ordered_and_unique(self) -> None:
        candidates = _runtime_model_candidates("custom-model")
        self.assertEqual(candidates[0], "custom-model")
        self.assertIn("claude-haiku-4-5", candidates)
        self.assertEqual(len(candidates), len(set(candidates)))

    def test_model_supports_temperature(self) -> None:
        self.assertTrue(_model_supports_temperature("claude-sonnet-4-5"))
        self.assertTrue(_model_supports_temperature("claude-haiku-4-5"))
        self.assertTrue(_model_supports_temperature(""))

    def test_build_chain_selector_guidance_empty_at_step_zero(self) -> None:
        agents = [_make_agent(agent_id="a1", name="Alice"), _make_agent(agent_id="a2", name="Bob")]
        self.assertEqual(_build_chain_selector_guidance(0, [], agents), "")

    def test_build_chain_selector_guidance_includes_context_at_step_one(self) -> None:
        agents = [_make_agent(agent_id="a1", name="Alice"), _make_agent(agent_id="a2", name="Bob")]
        guidance = _build_chain_selector_guidance(1, ["a1"], agents)
        self.assertIn("Step 2", guidance)
        self.assertIn("Alice", guidance)
        self.assertNotIn("WARNING", guidance)

    def test_build_chain_selector_guidance_warns_on_long_chain(self) -> None:
        agents = [_make_agent(agent_id="a1", name="Alice"), _make_agent(agent_id="a2", name="Bob")]
        guidance = _build_chain_selector_guidance(3, ["a1", "a2", "a1"], agents)
        self.assertIn("WARNING", guidance)
        self.assertIn("spoken multiple times", guidance)

    def test_trim_helpers(self) -> None:
        self.assertEqual(_trim_to_words("one two three four", 3), "one two three...")
        self.assertEqual(_trim_to_words("one two", 5), "one two")
        self.assertEqual(_trim_to_sentences("A. B. C.", 2), "A. B.")
        self.assertEqual(_trim_to_sentences("One sentence only.", 2), "One sentence only.")

    def test_normalize_agent_reply_text_flattens_markdown_and_applies_verbosity(self) -> None:
        markdown_agent = _make_agent(agent_id="a1", name="Alex", verbosity=0.6)
        normalized = _normalize_agent_reply_text(markdown_agent, "### Update\n- Item one\n- Item two")
        self.assertEqual(normalized, "Update Item one Item two")

        brief_agent = _make_agent(agent_id="a2", name="Alex", verbosity=0.1)
        brief = _normalize_agent_reply_text(brief_agent, "Alex: First sentence. Second sentence. Third sentence.")
        self.assertEqual(brief, "First sentence. Second sentence.")

        fenced = _normalize_agent_reply_text(markdown_agent, "```text\nhello world\n```")
        self.assertEqual(fenced, "hello world")

    def test_relevance_and_role_identity_bonuses(self) -> None:
        agent = _make_agent(
            agent_id="a1",
            name="Finance Bot",
            role="Budget and forecasting specialist",
            backstory="Helps teams with planning and finance strategy.",
        )
        self.assertGreater(_topic_relevance_bonus(agent, "Can we review the budget forecast for Q2?"), 0.0)
        self.assertEqual(_topic_relevance_bonus(agent, "Need help with CSS gradients"), 0.0)
        self.assertEqual(_role_identity_bonus(agent, "Who can help with this?"), 0.22)
        self.assertEqual(_role_identity_bonus(agent, "Please draft a budget memo"), 0.0)

    def test_select_tool_skips_web_search(self) -> None:
        agent = _make_agent(agent_id="a1", name="Researcher", tool_names=["web_search", "summarize_topic"])
        self.assertIsNone(_select_tool(agent, "search the web for latest AI news"))
        self.assertEqual(_select_tool(agent, "give me a summary"), "summarize_topic")

    def test_extract_web_search_reply_text_only(self) -> None:
        class FakeBlock:
            def __init__(self, text: str, citations=None):
                self.text = text
                self.citations = citations

        class FakeResponse:
            def __init__(self, content):
                self.content = content

        response = FakeResponse([FakeBlock("Hello world")])
        result = _extract_web_search_reply(response)
        self.assertEqual(result, "Hello world")

    def test_extract_web_search_reply_multiple_blocks_with_citations(self) -> None:
        class FakeCitation:
            def __init__(self, title: str, url: str):
                self.title = title
                self.url = url

        class FakeBlock:
            def __init__(self, text: str, citations=None):
                self.text = text
                self.citations = citations

        class FakeToolUseBlock:
            pass

        class FakeResponse:
            def __init__(self, content):
                self.content = content

        blocks = [
            FakeBlock("Part one.", [FakeCitation("Source A", "https://a.com")]),
            FakeToolUseBlock(),
            FakeBlock("Part two.", [
                FakeCitation("Source B", "https://b.com"),
                FakeCitation("Source A dup", "https://a.com"),
            ]),
        ]
        response = FakeResponse(blocks)
        result = _extract_web_search_reply(response)
        self.assertIn("Part one.", result)
        self.assertIn("Part two.", result)
        self.assertIn("Sources:", result)
        self.assertIn("https://a.com", result)
        self.assertIn("https://b.com", result)
        self.assertEqual(result.count("https://a.com"), 1)

