import unittest

from teaparty_app.models import Workgroup
from teaparty_app.services.tools import (
    _is_ambiguous_add_path,
    _normalize_trigger_for_matching,
    _normalize_workgroup_files,
    _parse_file_payload,
    available_tools,
    run_tool,
)


class ToolHelperTests(unittest.TestCase):
    def test_normalize_trigger_for_matching_strips_polite_prefix_suffix(self) -> None:
        message = "Please could you add file notes.md please"
        self.assertEqual(_normalize_trigger_for_matching(message), "add file notes.md")

    def test_parse_file_payload_extracts_path_and_content(self) -> None:
        path, content, has_content = _parse_file_payload("named 'notes.md' with content \"Hello there\"")
        self.assertEqual(path, "notes.md")
        self.assertEqual(content, "Hello there")
        self.assertTrue(has_content)

    def test_parse_file_payload_without_content(self) -> None:
        path, content, has_content = _parse_file_payload("called project/notes.md")
        self.assertEqual(path, "project/notes.md")
        self.assertEqual(content, "")
        self.assertFalse(has_content)

    def test_is_ambiguous_add_path_detects_non_path_phrases(self) -> None:
        self.assertTrue(_is_ambiguous_add_path("markdown file"))
        self.assertTrue(_is_ambiguous_add_path(""))
        self.assertFalse(_is_ambiguous_add_path("docs/markdown-file.md"))

    def test_normalize_workgroup_files_deduplicates_and_enforces_limits(self) -> None:
        workgroup = Workgroup(
            id="wg-1",
            name="Core",
            owner_id="user-1",
            files=[
                {"id": "1", "path": "docs/notes.md", "content": "hello"},
                {"id": "2", "path": "docs/notes.md", "content": "duplicate path"},
                {"path": "x" * 513, "content": "too long path"},
                {"path": "too-big.txt", "content": "x" * 200001},
                "https://example.com/spec",
            ],
        )
        normalized = _normalize_workgroup_files(workgroup)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["path"], "docs/notes.md")
        self.assertEqual(normalized[0]["content"], "hello")
        self.assertEqual(normalized[1]["path"], "https://example.com/spec")
        self.assertEqual(normalized[1]["content"], "")
        self.assertTrue(normalized[1]["id"])

    def test_available_tools_returns_sorted_tool_names(self) -> None:
        tools = available_tools()
        self.assertEqual(tools, sorted(tools))
        self.assertIn("add_file", tools)
        self.assertIn("summarize_topic", tools)

    def test_run_tool_returns_error_for_unknown_tool(self) -> None:
        result = run_tool("missing_tool", None, None, None, None)  # type: ignore[arg-type]
        self.assertEqual(result, "Tool 'missing_tool' is not available.")

