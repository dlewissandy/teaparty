import unittest
from unittest.mock import MagicMock, patch

from teaparty_app.config import settings
from teaparty_app.models import Agent, AgentLearningEvent, Conversation, Message
from teaparty_app.services.agent_runtime import (
    _extract_file_tool_command,
    _extract_json_object,
    _extract_web_search_reply,
    _gather_agent_intents,
    _is_valid_file_tool_command,
    _model_supports_temperature,
    _normalize_agent_reply_text,
    _probe_agent_intent,
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
    response_threshold: float = 0.55,
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
        response_threshold=response_threshold,
    )


def _make_conversation(*, conversation_id: str = "conv-1", topic: str = "Test topic", kind: str = "topic") -> Conversation:
    return Conversation(
        id=conversation_id,
        workgroup_id="wg-1",
        topic=topic,
        kind=kind,
    )


def _make_message(*, message_id: str = "msg-1", content: str = "Hello", sender_type: str = "user", sender_agent_id: str | None = None) -> Message:
    return Message(
        id=message_id,
        conversation_id="conv-1",
        sender_type=sender_type,
        content=content,
        sender_agent_id=sender_agent_id,
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
        # With llm_default_model set (default is ollama/llama3.1), override takes priority
        candidates = _runtime_model_candidates("custom-model")
        self.assertEqual(candidates[0], settings.llm_default_model)
        self.assertEqual(len(candidates), 1)

    @patch.object(settings, "llm_default_model", "")
    def test_runtime_model_candidates_fallback_without_override(self) -> None:
        candidates = _runtime_model_candidates("custom-model")
        self.assertEqual(candidates[0], "custom-model")
        self.assertIn("claude-haiku-4-5", candidates)
        self.assertEqual(len(candidates), len(set(candidates)))

    def test_model_supports_temperature(self) -> None:
        self.assertTrue(_model_supports_temperature("claude-sonnet-4-5"))
        self.assertTrue(_model_supports_temperature("claude-haiku-4-5"))
        self.assertTrue(_model_supports_temperature(""))

    def test_trim_helpers(self) -> None:
        self.assertEqual(_trim_to_words("one two three four", 3), "one two three...")
        self.assertEqual(_trim_to_words("one two", 5), "one two")
        self.assertEqual(_trim_to_sentences("A. B. C.", 2), "A. B.")
        self.assertEqual(_trim_to_sentences("One sentence only.", 2), "One sentence only.")

    def test_normalize_agent_reply_text_preserves_markdown_and_strips_prefix(self) -> None:
        markdown_agent = _make_agent(agent_id="a1", name="Alex", verbosity=0.6)
        normalized = _normalize_agent_reply_text(markdown_agent, "### Update\n- Item one\n- Item two")
        self.assertEqual(normalized, "### Update\n- Item one\n- Item two")

        brief_agent = _make_agent(agent_id="a2", name="Alex", verbosity=0.1)
        brief = _normalize_agent_reply_text(brief_agent, "Alex: First sentence. Second sentence. Third sentence.")
        self.assertEqual(brief, "First sentence. Second sentence. Third sentence.")

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


class IntentProbeTests(unittest.TestCase):
    """Tests for _probe_agent_intent and _gather_agent_intents."""

    def _patch_targets(self):
        """Common patch targets for intent probe tests."""
        return {
            "create_message": patch("teaparty_app.services.llm_client.create_message"),
            "history": patch("teaparty_app.services.agent_runtime._selector_history_context", return_value="- user: hello"),
            "usage": patch("teaparty_app.services.agent_runtime.record_llm_usage"),
        }

    def test_probe_agent_intent_returns_none_on_api_failure(self) -> None:
        agent = _make_agent(agent_id="a1", name="Alice", role="Engineer")
        conversation = _make_conversation()
        trigger = _make_message(content="What do you think about this design?")

        patches = self._patch_targets()
        with patches["create_message"] as mock_create_message, patches["history"], patches["usage"]:
            mock_create_message.side_effect = Exception("API error")
            intent, urgency = _probe_agent_intent(
                session=MagicMock(),
                agent=agent,
                conversation=conversation,
                trigger=trigger,
                chain_step=0,
                chain_responded_ids=[],
                candidates=[agent],
            )
        self.assertIsNone(intent)
        self.assertEqual(urgency, 0.0)

    def test_probe_agent_intent_parses_valid_json(self) -> None:
        agent = _make_agent(agent_id="a1", name="Alice", role="Engineer")
        conversation = _make_conversation()
        trigger = _make_message(content="What do you think about this design?")

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text='{"intent": "I think we need more tests", "urgency": 0.75}')]
        fake_response.usage.input_tokens = 100
        fake_response.usage.output_tokens = 20

        patches = self._patch_targets()
        with patches["create_message"] as mock_create_message, patches["history"], patches["usage"]:
            mock_create_message.return_value = fake_response
            intent, urgency = _probe_agent_intent(
                session=MagicMock(),
                agent=agent,
                conversation=conversation,
                trigger=trigger,
                chain_step=0,
                chain_responded_ids=[],
                candidates=[agent],
            )
        self.assertEqual(intent, "I think we need more tests")
        self.assertEqual(urgency, 0.75)

    def test_probe_agent_intent_clamps_urgency_above_one(self) -> None:
        agent = _make_agent(agent_id="a1", name="Alice", role="Engineer")
        conversation = _make_conversation()
        trigger = _make_message(content="Critical issue!")

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text='{"intent": "This is critical", "urgency": 1.5}')]
        fake_response.usage.input_tokens = 100
        fake_response.usage.output_tokens = 20

        patches = self._patch_targets()
        with patches["create_message"] as mock_create_message, patches["history"], patches["usage"]:
            mock_create_message.return_value = fake_response
            intent, urgency = _probe_agent_intent(
                session=MagicMock(),
                agent=agent,
                conversation=conversation,
                trigger=trigger,
                chain_step=0,
                chain_responded_ids=[],
                candidates=[agent],
            )
        self.assertEqual(intent, "This is critical")
        self.assertEqual(urgency, 1.0)

    def test_probe_agent_intent_null_intent_returns_none(self) -> None:
        agent = _make_agent(agent_id="a1", name="Alice", role="Engineer")
        conversation = _make_conversation()
        trigger = _make_message(content="Sounds good to me")

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text='{"intent": null, "urgency": 0}')]
        fake_response.usage.input_tokens = 100
        fake_response.usage.output_tokens = 20

        patches = self._patch_targets()
        with patches["create_message"] as mock_create_message, patches["history"], patches["usage"]:
            mock_create_message.return_value = fake_response
            intent, urgency = _probe_agent_intent(
                session=MagicMock(),
                agent=agent,
                conversation=conversation,
                trigger=trigger,
                chain_step=0,
                chain_responded_ids=[],
                candidates=[agent],
            )
        self.assertIsNone(intent)
        self.assertEqual(urgency, 0.0)

    def test_gather_agent_intents_skips_blocked_agents(self) -> None:
        alice = _make_agent(agent_id="a1", name="Alice", role="Engineer")
        bob = _make_agent(agent_id="a2", name="Bob", role="Designer")
        conversation = _make_conversation()
        trigger = _make_message(content="What do you think?")

        fake_response = MagicMock()
        fake_response.content = [MagicMock(text='{"intent": "I have a point", "urgency": 0.7}')]
        fake_response.usage.input_tokens = 100
        fake_response.usage.output_tokens = 20

        mock_session = MagicMock()

        patches = self._patch_targets()
        with patches["create_message"] as mock_create_message, patches["history"], patches["usage"]:
            mock_create_message.return_value = fake_response
            results = _gather_agent_intents(
                session=mock_session,
                conversation=conversation,
                trigger=trigger,
                candidates=[alice, bob],
                blocked_agent_ids={"a1"},
            )

        # Only Bob should be probed (Alice is blocked).
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0].id, "a2")

    def test_gather_agent_intents_sorts_by_urgency_descending(self) -> None:
        alice = _make_agent(agent_id="a1", name="Alice", role="Engineer")
        bob = _make_agent(agent_id="a2", name="Bob", role="Designer")
        conversation = _make_conversation()
        trigger = _make_message(content="What do you think?")

        alice_response = MagicMock()
        alice_response.content = [MagicMock(text='{"intent": "Low priority point", "urgency": 0.3}')]
        alice_response.usage.input_tokens = 100
        alice_response.usage.output_tokens = 20

        bob_response = MagicMock()
        bob_response.content = [MagicMock(text='{"intent": "Critical disagreement", "urgency": 0.9}')]
        bob_response.usage.input_tokens = 100
        bob_response.usage.output_tokens = 20

        mock_session = MagicMock()

        patches = self._patch_targets()
        with patches["create_message"] as mock_create_message, patches["history"], patches["usage"]:
            mock_create_message.side_effect = [alice_response, bob_response]
            results = _gather_agent_intents(
                session=mock_session,
                conversation=conversation,
                trigger=trigger,
                candidates=[alice, bob],
                blocked_agent_ids=set(),
            )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0].id, "a2")  # Bob first (higher urgency)
        self.assertEqual(results[0][2], 0.9)
        self.assertEqual(results[1][0].id, "a1")  # Alice second
        self.assertEqual(results[1][2], 0.3)

