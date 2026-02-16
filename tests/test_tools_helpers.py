import unittest

from teaparty_app.models import Conversation, Workgroup
from teaparty_app.services.tools import (
    _files_for_conversation,
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
        self.assertIn("summarize_job", tools)

    def test_available_tools_includes_web_search(self) -> None:
        tools = available_tools()
        self.assertIn("web_search", tools)

    def test_available_tools_includes_workflow_tools(self) -> None:
        tools = available_tools()
        self.assertIn("list_workflows", tools)
        self.assertIn("get_workflow_state", tools)
        self.assertIn("advance_workflow", tools)

    def test_run_tool_returns_server_side_message_for_web_search(self) -> None:
        result = run_tool("web_search", None, None, None, None)  # type: ignore[arg-type]
        self.assertIn("server-side tool", result)

    def test_run_tool_returns_error_for_unknown_tool(self) -> None:
        result = run_tool("missing_tool", None, None, None, None)  # type: ignore[arg-type]
        self.assertEqual(result, "Tool 'missing_tool' is not available.")

    def test_normalize_preserves_topic_id(self) -> None:
        workgroup = Workgroup(
            id="wg-1",
            name="Core",
            owner_id="user-1",
            files=[
                {"id": "1", "path": "shared.md", "content": "shared"},
                {"id": "2", "path": "topic.md", "content": "scoped", "topic_id": "conv-1"},
                {"id": "3", "path": "empty-tid.md", "content": "no tid"},
            ],
        )
        normalized = _normalize_workgroup_files(workgroup)
        self.assertEqual(len(normalized), 3)
        self.assertEqual(normalized[0]["topic_id"], "")
        self.assertEqual(normalized[1]["topic_id"], "conv-1")
        self.assertEqual(normalized[2]["topic_id"], "")

    def test_files_for_job_sees_shared_and_own(self) -> None:
        workgroup = Workgroup(
            id="wg-1",
            name="Core",
            owner_id="user-1",
            files=[
                {"id": "1", "path": "shared.md", "content": "shared"},
                {"id": "2", "path": "topic-a.md", "content": "a", "topic_id": "conv-a"},
                {"id": "3", "path": "topic-b.md", "content": "b", "topic_id": "conv-b"},
            ],
        )
        conv = Conversation(id="conv-a", workgroup_id="wg-1", kind="job", created_by_user_id="u1")
        result = _files_for_conversation(workgroup, conv)
        paths = [f["path"] for f in result]
        self.assertIn("shared.md", paths)
        self.assertIn("topic-a.md", paths)
        self.assertNotIn("topic-b.md", paths)

    def test_files_for_admin_sees_all(self) -> None:
        workgroup = Workgroup(
            id="wg-1",
            name="Core",
            owner_id="user-1",
            files=[
                {"id": "1", "path": "shared.md", "content": "shared"},
                {"id": "2", "path": "topic-a.md", "content": "a", "topic_id": "conv-a"},
                {"id": "3", "path": "topic-b.md", "content": "b", "topic_id": "conv-b"},
            ],
        )
        conv = Conversation(id="admin-conv", workgroup_id="wg-1", kind="admin", created_by_user_id="u1")
        result = _files_for_conversation(workgroup, conv)
        paths = [f["path"] for f in result]
        self.assertEqual(len(paths), 3)
        self.assertIn("shared.md", paths)
        self.assertIn("topic-a.md", paths)
        self.assertIn("topic-b.md", paths)

    def test_files_for_direct_sees_shared_only(self) -> None:
        workgroup = Workgroup(
            id="wg-1",
            name="Core",
            owner_id="user-1",
            files=[
                {"id": "1", "path": "shared.md", "content": "shared"},
                {"id": "2", "path": "topic-a.md", "content": "a", "topic_id": "conv-a"},
            ],
        )
        conv = Conversation(id="dm-conv", workgroup_id="wg-1", kind="direct", created_by_user_id="u1")
        result = _files_for_conversation(workgroup, conv)
        paths = [f["path"] for f in result]
        self.assertEqual(len(paths), 1)
        self.assertIn("shared.md", paths)
        self.assertNotIn("topic-a.md", paths)

