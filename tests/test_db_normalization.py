import unittest

from teaparty_app.db import _normalize_workgroup_files_payload


class WorkgroupFileNormalizationTests(unittest.TestCase):
    def test_normalizes_json_string_payload_and_deduplicates_paths(self) -> None:
        raw = (
            '[{"path":"notes.md","content":"one"},'
            '{"path":"notes.md","content":"two"},'
            '{"id":"x","path":"todo.txt","content":123}]'
        )
        normalized = _normalize_workgroup_files_payload(raw)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["path"], "notes.md")
        self.assertEqual(normalized[0]["content"], "one")
        self.assertEqual(normalized[1]["path"], "todo.txt")
        self.assertEqual(normalized[1]["content"], "123")
        self.assertTrue(normalized[0]["id"])
        self.assertTrue(normalized[1]["id"])

    def test_truncates_long_path_and_content(self) -> None:
        payload = [{"path": "a" * 700, "content": "b" * 300000}]
        normalized = _normalize_workgroup_files_payload(payload)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(len(normalized[0]["path"]), 512)
        self.assertEqual(len(normalized[0]["content"]), 200000)

    def test_replaces_duplicate_ids(self) -> None:
        payload = [
            {"id": "dup", "path": "one.md", "content": "1"},
            {"id": "dup", "path": "two.md", "content": "2"},
        ]
        normalized = _normalize_workgroup_files_payload(payload)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["id"], "dup")
        self.assertNotEqual(normalized[1]["id"], "dup")
        self.assertNotEqual(normalized[0]["id"], normalized[1]["id"])

    def test_returns_empty_for_invalid_payload_types(self) -> None:
        self.assertEqual(_normalize_workgroup_files_payload({"path": "notes.md"}), [])
        self.assertEqual(_normalize_workgroup_files_payload("not-json"), [])

