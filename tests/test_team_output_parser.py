import unittest

from teaparty_app.services.team_output_parser import parse_team_output, unpack_agent_text


class ParseTeamOutputTests(unittest.TestCase):
    """Test event-based parsing of verbose CLI output."""

    def _make_slug_to_id(self):
        return {
            "alice": "agent-1",
            "bob": "agent-2",
            "carol": "agent-3",
        }

    def test_task_tool_use_and_result_attributed_to_subagent(self) -> None:
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Let me delegate to the team."},
                {"type": "tool_use", "id": "tu-1", "name": "Task", "input": {"name": "bob", "prompt": "Do research"}},
            ]}},
            {"type": "tool_result", "tool_use_id": "tu-1", "content": "Bob's research findings here."},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "tu-2", "name": "Task", "input": {"name": "carol", "prompt": "Review"}},
            ]}},
            {"type": "tool_result", "tool_use_id": "tu-2", "content": "Carol's review notes."},
            {"type": "result", "result": "Done"},
        ]
        result = parse_team_output(events, self._make_slug_to_id(), ["Alice", "Bob", "Carol"])

        # Lead text + 2 sub-agent contributions.
        self.assertEqual(len(result), 3)

        # Lead text first.
        self.assertIsNone(result[0][0])
        self.assertIn("delegate", result[0][1])

        # Bob's contribution.
        self.assertEqual(result[1][0], "agent-2")
        self.assertIn("Bob's research", result[1][1])

        # Carol's contribution.
        self.assertEqual(result[2][0], "agent-3")
        self.assertIn("Carol's review", result[2][1])

    def test_subagent_type_field_used_for_attribution(self) -> None:
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "tu-1", "name": "Task", "input": {"subagent_type": "alice"}},
            ]}},
            {"type": "tool_result", "tool_use_id": "tu-1", "content": "Alice's work."},
        ]
        result = parse_team_output(events, self._make_slug_to_id(), ["Alice"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "agent-1")

    def test_no_task_events_returns_empty(self) -> None:
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Just a plain response."},
            ]}},
            {"type": "result", "result": "Done"},
        ]
        result = parse_team_output(events, self._make_slug_to_id(), ["Alice"])
        # Only lead text, no sub-agent attributions.
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0][0])
        self.assertIn("plain response", result[0][1])

    def test_empty_events_returns_empty(self) -> None:
        result = parse_team_output([], {}, [])
        self.assertEqual(result, [])

    def test_unmatched_subagent_returns_none_id(self) -> None:
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "tu-1", "name": "Task", "input": {"name": "unknown-agent"}},
            ]}},
            {"type": "tool_result", "tool_use_id": "tu-1", "content": "Mystery output."},
        ]
        result = parse_team_output(events, self._make_slug_to_id(), [])
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0][0])

    def test_tool_result_with_list_content(self) -> None:
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "tu-1", "name": "Task", "input": {"name": "bob"}},
            ]}},
            {"type": "tool_result", "tool_use_id": "tu-1", "content": [
                {"type": "text", "text": "Part one."},
                {"type": "text", "text": "Part two."},
            ]},
        ]
        result = parse_team_output(events, self._make_slug_to_id(), [])
        self.assertEqual(len(result), 1)
        self.assertIn("Part one", result[0][1])
        self.assertIn("Part two", result[0][1])

    def test_non_task_tool_use_ignored(self) -> None:
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "tu-1", "name": "Read", "input": {"path": "/foo"}},
            ]}},
            {"type": "tool_result", "tool_use_id": "tu-1", "content": "file contents"},
        ]
        result = parse_team_output(events, self._make_slug_to_id(), [])
        self.assertEqual(result, [])


class UnpackAgentTextTests(unittest.TestCase):
    """Test text-based agent attribution."""

    def test_bold_name_prefix(self) -> None:
        text = "**Alice**: First point.\n\n**Bob**: Second point."
        result = unpack_agent_text(text, ["Alice", "Bob"])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], "Alice")
        self.assertIn("First point", result[0][1])
        self.assertEqual(result[1][0], "Bob")
        self.assertIn("Second point", result[1][1])

    def test_bracket_name_prefix(self) -> None:
        text = "[Alice]: Her thoughts.\n[Bob]: His thoughts."
        result = unpack_agent_text(text, ["Alice", "Bob"])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], "Alice")
        self.assertEqual(result[1][0], "Bob")

    def test_plain_name_prefix(self) -> None:
        text = "Alice: Analysis here.\nBob: Response here."
        result = unpack_agent_text(text, ["Alice", "Bob"])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], "Alice")
        self.assertEqual(result[1][0], "Bob")

    def test_no_agent_prefixes_returns_full_text(self) -> None:
        text = "Just a plain response with no agent names."
        result = unpack_agent_text(text, ["Alice", "Bob"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "")
        self.assertEqual(result[0][1], text)

    def test_empty_text(self) -> None:
        result = unpack_agent_text("", ["Alice"])
        self.assertEqual(result, [])

    def test_empty_agent_names(self) -> None:
        result = unpack_agent_text("Some text", [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "")

    def test_case_insensitive_matching(self) -> None:
        text = "**alice**: lowercase name."
        result = unpack_agent_text(text, ["Alice"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "Alice")

    def test_text_before_first_agent_preserved(self) -> None:
        text = "Introduction paragraph.\n\n**Alice**: Her section."
        result = unpack_agent_text(text, ["Alice"])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], "")
        self.assertIn("Introduction", result[0][1])
        self.assertEqual(result[1][0], "Alice")

    def test_single_agent(self) -> None:
        text = "**Alice**: Only agent response."
        result = unpack_agent_text(text, ["Alice"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "Alice")


if __name__ == "__main__":
    unittest.main()
