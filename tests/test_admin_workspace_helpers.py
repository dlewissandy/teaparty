import unittest

from teaparty_app.services.admin_workspace import (
    _is_confirmed_word,
    _normalize_file_content,
    _normalize_list_jobs_status,
    _normalize_job_selector,
    _parse_add_agent_payload,
    _parse_add_job_payload,
    _parse_file_payload,
    _parse_temperature,
    direct_conversation_key,
    direct_conversation_key_user_agent,
)


class AdminWorkspaceHelperTests(unittest.TestCase):
    def test_direct_conversation_keys(self) -> None:
        self.assertEqual(direct_conversation_key("user-b", "user-a"), "dm:user-a:user-b")
        self.assertEqual(direct_conversation_key_user_agent("user-1", "agent-9"), "dma:user-1:agent-9")

    def test_normalize_list_jobs_status(self) -> None:
        self.assertEqual(_normalize_list_jobs_status(None), ("open", None))
        self.assertEqual(_normalize_list_jobs_status("all"), ("both", None))
        status_value, error = _normalize_list_jobs_status("invalid")
        self.assertIsNone(status_value)
        self.assertEqual(error, "Status must be one of: open, archived, both.")

    def test_parse_add_agent_payload_with_explicit_options(self) -> None:
        name, parsed = _parse_add_agent_payload(
            'named "@Mia" role="Product Strategist" personality="Warm and clear" model=gpt-4.1-mini temperature=0.4'
        )
        self.assertEqual(name, "Mia")
        self.assertEqual(parsed["role"], "Product Strategist")
        self.assertEqual(parsed["personality"], "Warm and clear")
        self.assertEqual(parsed["model"], "gpt-4.1-mini")
        self.assertEqual(parsed["temperature"], "0.4")

    def test_parse_add_agent_payload_uses_narrative_and_inline_hints(self) -> None:
        name, parsed = _parse_add_agent_payload("Alex: pragmatic release manager")
        self.assertEqual(name, "Alex")
        self.assertEqual(parsed["personality"], "pragmatic release manager")
        self.assertEqual(parsed["role"], "")

        hinted_name, hinted = _parse_add_agent_payload("Lena use model gpt-5-nano at temperature 0.2")
        self.assertEqual(hinted_name, "Lena")
        self.assertEqual(hinted["model"], "gpt-5-nano")
        self.assertEqual(hinted["temperature"], "0.2")
        self.assertEqual(hinted["personality"], "Professional and concise")

    def test_parse_temperature(self) -> None:
        self.assertEqual(_parse_temperature(None), (0.7, None))
        self.assertEqual(_parse_temperature("1.2345"), (1.234, None))
        self.assertEqual(_parse_temperature(0.0), (0.0, None))
        self.assertEqual(_parse_temperature("oops"), (0.7, "Temperature must be a number between 0.0 and 2.0."))
        self.assertEqual(_parse_temperature(3.0), (0.7, "Temperature must be between 0.0 and 2.0."))

    def test_parse_add_job_payload(self) -> None:
        self.assertEqual(_parse_add_job_payload('Roadmap description="Q2 priorities"'), ("Roadmap", "Q2 priorities"))
        self.assertEqual(_parse_add_job_payload("Backlog"), ("Backlog", ""))

    def test_file_content_and_file_payload_parsing(self) -> None:
        content, error = _normalize_file_content(123)  # type: ignore[arg-type]
        self.assertEqual(content, "123")
        self.assertIsNone(error)

        too_long, too_long_error = _normalize_file_content("x" * 200001)
        self.assertEqual(too_long, "")
        self.assertEqual(too_long_error, "File content must be 200000 characters or fewer.")

        path, parsed_content, has_content = _parse_file_payload('notes.md content="hello world"')
        self.assertEqual(path, "notes.md")
        self.assertEqual(parsed_content, "hello world")
        self.assertTrue(has_content)

        path_only, empty_content, has_content_flag = _parse_file_payload('"notes.md"')
        self.assertEqual(path_only, "notes.md")
        self.assertEqual(empty_content, "")
        self.assertFalse(has_content_flag)

    def test_job_selector_and_confirmation_words(self) -> None:
        self.assertEqual(_normalize_job_selector("#general"), "general")
        self.assertEqual(_normalize_job_selector('"#team-planning"'), "team-planning")
        self.assertTrue(_is_confirmed_word("YES"))
        self.assertTrue(_is_confirmed_word("confirm"))
        self.assertFalse(_is_confirmed_word("no"))

