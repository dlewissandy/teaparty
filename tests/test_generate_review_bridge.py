#!/usr/bin/env python3
"""Tests for generate_review_bridge.py."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import scripts.generate_review_bridge as mod


class TestStateConfig(unittest.TestCase):
    """STATE_CONFIG covers all documented CfA review states."""

    def test_all_six_states_present(self):
        expected = {"INTENT_ASSERT", "PLAN_ASSERT", "WORK_ASSERT",
                    "INTENT_ESCALATE", "PLANNING_ESCALATE", "TASK_ESCALATE"}
        self.assertEqual(set(mod.STATE_CONFIG.keys()), expected)

    def test_each_config_has_template_and_noun(self):
        for state, cfg in mod.STATE_CONFIG.items():
            self.assertIn("template", cfg, f"{state} missing template")
            self.assertIn("noun", cfg, f"{state} missing noun")
            self.assertIn(cfg["template"], mod.TEMPLATES,
                          f"{state} template '{cfg['template']}' not in TEMPLATES")


class TestReadFileContent(unittest.TestCase):

    def test_reads_small_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("Hello world")
            path = f.name
        try:
            content = mod.read_file_content(path)
            self.assertEqual(content, "Hello world")
        finally:
            os.unlink(path)

    def test_truncates_large_file(self):
        big = "x" * (mod.MAX_FILE_CHARS + 500)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(big)
            path = f.name
        try:
            content = mod.read_file_content(path)
            self.assertEqual(len(content),
                             mod.MAX_FILE_CHARS + len("\n[... truncated ...]"))
            self.assertTrue(content.endswith("[... truncated ...]"))
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self):
        content = mod.read_file_content("/nonexistent/path/file.md")
        self.assertEqual(content, "")

    def test_empty_file_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            path = f.name
        try:
            content = mod.read_file_content(path)
            self.assertEqual(content, "")
        finally:
            os.unlink(path)


class TestFallbackBridge(unittest.TestCase):

    def test_known_state_with_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("line1\nline2\nline3\n")
            path = f.name
        try:
            result = mod.fallback_bridge(path, "INTENT_ASSERT")
            self.assertIn("intent document", result)
            self.assertIn(path, result)
            self.assertIn("line1", result)
        finally:
            os.unlink(path)

    def test_truncates_to_max_lines(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            for i in range(20):
                f.write(f"line {i}\n")
            path = f.name
        try:
            result = mod.fallback_bridge(path, "PLAN_ASSERT")
            # Output: question line, "Review plan at: path", up to MAX_FALLBACK_LINES, "..."
            lines = result.split('\n')
            # Skip question + path header lines; count only file content lines
            content_lines = [l for l in lines[2:] if l != '...']
            self.assertLessEqual(len(content_lines), mod.MAX_FALLBACK_LINES)
        finally:
            os.unlink(path)

    def test_missing_file_returns_path_only(self):
        result = mod.fallback_bridge("/no/such/file.md", "TASK_ESCALATE")
        self.assertIn("/no/such/file.md", result)
        self.assertNotIn("\n", result)  # No preview lines

    def test_unknown_state_uses_document_noun(self):
        result = mod.fallback_bridge("/tmp/x.md", "UNKNOWN_STATE")
        self.assertIn("document", result)



class TestGenerate(unittest.TestCase):

    def _make_file(self, content="# Intent\nBuild a widget"):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_assert_state_produces_bridge_with_path(self):
        path = self._make_file()
        try:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = f"I've drafted the intent document and saved it to {path}. The core objective is building a widget."
            with patch('subprocess.run', return_value=mock_result):
                result = mod.generate(path, "INTENT_ASSERT", "Build a widget")
            self.assertIn(path, result)
            self.assertIn("intent", result.lower())
        finally:
            os.unlink(path)

    def test_escalate_state_produces_bridge_referencing_blocker(self):
        path = self._make_file("## Question\nWhat database should we use?")
        try:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = f"I need your help before I can proceed. I've written my questions to {path} -- the main blocker is the database choice."
            with patch('subprocess.run', return_value=mock_result):
                result = mod.generate(path, "INTENT_ESCALATE", "Build a widget")
            self.assertIn(path, result)
        finally:
            os.unlink(path)

    def test_plan_assert_produces_plan_summary(self):
        path = self._make_file("# Plan\n1. Setup DB\n2. Build API\n3. Deploy")
        try:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = f"I've drafted a plan and saved it to {path}. The approach covers database setup, API implementation, and deployment."
            with patch('subprocess.run', return_value=mock_result):
                result = mod.generate(path, "PLAN_ASSERT", "Build a service")
            self.assertIn(path, result)
        finally:
            os.unlink(path)

    def test_unknown_state_falls_back_to_assert(self):
        path = self._make_file()
        try:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = f"I've prepared a document at {path}."
            with patch('subprocess.run', return_value=mock_result):
                result = mod.generate(path, "WEIRD_STATE", "test")
            self.assertIn(path, result)
        finally:
            os.unlink(path)

    def test_llm_timeout_returns_fallback(self):
        path = self._make_file()
        try:
            with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("claude", 30)):
                result = mod.generate(path, "INTENT_ASSERT", "test")
            self.assertIn("intent document", result)
            self.assertIn(path, result)
        finally:
            os.unlink(path)

    def test_llm_not_found_returns_fallback(self):
        path = self._make_file()
        try:
            with patch('subprocess.run', side_effect=FileNotFoundError()):
                result = mod.generate(path, "PLAN_ASSERT", "test")
            self.assertIn("plan", result)
            self.assertIn(path, result)
        finally:
            os.unlink(path)

    def test_llm_nonzero_exit_returns_fallback(self):
        path = self._make_file()
        try:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            with patch('subprocess.run', return_value=mock_result):
                result = mod.generate(path, "INTENT_ASSERT", "test")
            self.assertIn("intent document", result)
        finally:
            os.unlink(path)

    def test_llm_empty_output_returns_fallback(self):
        path = self._make_file()
        try:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "   "
            with patch('subprocess.run', return_value=mock_result):
                result = mod.generate(path, "INTENT_ASSERT", "test")
            self.assertIn("intent document", result)
        finally:
            os.unlink(path)

    def test_oversized_llm_output_not_truncated(self):
        """Issue #182: Agent output must never be truncated."""
        path = self._make_file()
        try:
            long_output = "Sentence one. " * 100  # Way over 800 chars
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = long_output
            with patch('subprocess.run', return_value=mock_result):
                result = mod.generate(path, "INTENT_ASSERT", "test")
            self.assertEqual(result, long_output.strip())
        finally:
            os.unlink(path)

    def test_empty_file_returns_fallback(self):
        path = self._make_file("")
        try:
            result = mod.generate(path, "INTENT_ASSERT", "test")
            self.assertIn("intent document", result)
        finally:
            os.unlink(path)

    def test_missing_file_returns_fallback(self):
        result = mod.generate("/nonexistent/file.md", "INTENT_ASSERT", "test")
        self.assertIn("intent document", result)
        self.assertIn("/nonexistent/file.md", result)


if __name__ == "__main__":
    unittest.main()
