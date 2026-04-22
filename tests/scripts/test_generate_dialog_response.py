#!/usr/bin/env python3
"""Tests for generate_dialog_response.py."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
import teaparty.scripts.generate_dialog_response as mod


class TestReadFileContent(unittest.TestCase):

    def test_reads_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("Hello world" * 100)
            f.flush()
            content = mod.read_file_content(f.name)
        self.assertTrue(content.startswith("Hello world"))
        os.unlink(f.name)

    def test_truncates_at_max(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("x" * 10000)
            f.flush()
            content = mod.read_file_content(f.name, max_chars=500)
        self.assertLessEqual(len(content), 500)
        os.unlink(f.name)

    def test_missing_file_returns_empty(self):
        self.assertEqual(mod.read_file_content("/nonexistent/path.md"), "")


class TestReadExecStream(unittest.TestCase):

    def test_reads_tail_of_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            f.write("line1\n" * 1000)
            f.flush()
            content = mod.read_exec_stream(f.name, max_chars=100)
        self.assertLessEqual(len(content), 200)  # allow some slack
        os.unlink(f.name)

    def test_missing_file_returns_empty(self):
        self.assertEqual(mod.read_exec_stream("/nonexistent/stream.jsonl"), "")



class TestBuildContext(unittest.TestCase):

    def test_no_artifact(self):
        ctx = mod.build_context("PLAN_ASSERT")
        self.assertIn("no artifact", ctx["artifact_content"])

    def test_with_artifact_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("# My Plan\nStep 1: do stuff")
            f.flush()
            ctx = mod.build_context("PLAN_ASSERT", artifact_path=f.name)
        self.assertIn("My Plan", ctx["artifact_content"])
        os.unlink(f.name)

    def test_exec_stream_only_for_execute(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            f.write("some exec data\n")
            f.flush()
            ctx_exec = mod.build_context("EXECUTE", exec_stream_path=f.name)
            ctx_plan = mod.build_context("PLAN", exec_stream_path=f.name)
        self.assertIn("EXECUTION LOG", ctx_exec["extra_context"])
        self.assertEqual(ctx_plan["extra_context"], "")
        os.unlink(f.name)

    def test_dialog_history_included(self):
        ctx = mod.build_context("WORK_ASSERT",
                                dialog_history="HUMAN: hi\nAGENT: hello")
        self.assertIn("PRIOR DIALOG", ctx["dialog_history_block"])

    def test_dialog_history_empty(self):
        ctx = mod.build_context("WORK_ASSERT", dialog_history="")
        self.assertEqual(ctx["dialog_history_block"], "")

    def test_task_default(self):
        ctx = mod.build_context("PLAN_ASSERT")
        self.assertIn("no task", ctx["task"])

    def test_task_provided(self):
        ctx = mod.build_context("PLAN_ASSERT", task="Build a widget")
        self.assertEqual(ctx["task"], "Build a widget")


class TestGenerate(unittest.TestCase):

    def _mock_llm(self, stdout, returncode=0):
        mock = MagicMock()
        mock.returncode = returncode
        mock.stdout = stdout
        return mock

    def test_generates_response(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm(
                       "Yes, I tested it with the sample data.")):
            result = mod.generate("WORK_ASSERT", "Have you tested it?")
        self.assertEqual(result, "Yes, I tested it with the sample data.")

    def test_empty_question_returns_fallback(self):
        result = mod.generate("WORK_ASSERT", "")
        self.assertEqual(result, mod.FALLBACK_RESPONSE)

    def test_whitespace_question_returns_fallback(self):
        result = mod.generate("WORK_ASSERT", "   ")
        self.assertEqual(result, mod.FALLBACK_RESPONSE)

    def test_timeout_returns_fallback(self):
        with patch('subprocess.run',
                   side_effect=subprocess.TimeoutExpired("claude", 30)):
            result = mod.generate("WORK_ASSERT", "What happened?")
        self.assertEqual(result, mod.FALLBACK_RESPONSE)

    def test_not_found_returns_fallback(self):
        with patch('subprocess.run', side_effect=FileNotFoundError()):
            result = mod.generate("WORK_ASSERT", "What happened?")
        self.assertEqual(result, mod.FALLBACK_RESPONSE)

    def test_nonzero_exit_returns_fallback(self):
        with patch('subprocess.run', return_value=self._mock_llm("", 1)):
            result = mod.generate("WORK_ASSERT", "What happened?")
        self.assertEqual(result, mod.FALLBACK_RESPONSE)

    def test_empty_output_returns_fallback(self):
        with patch('subprocess.run', return_value=self._mock_llm("  ")):
            result = mod.generate("WORK_ASSERT", "What happened?")
        self.assertEqual(result, mod.FALLBACK_RESPONSE)

    def test_output_not_truncated(self):
        """Issue #182: Agent output must never be truncated."""
        long_response = "First sentence. " + "More text. " * 100
        with patch('subprocess.run',
                   return_value=self._mock_llm(long_response)):
            result = mod.generate("WORK_ASSERT", "Tell me everything")
        self.assertEqual(result, long_response.strip())

    def test_prompt_includes_state_and_question(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("response")) as mock_run:
            mod.generate("PLAN_ASSERT", "What's the approach?")
        call_args = mock_run.call_args
        prompt = call_args.kwargs.get('input', call_args[1].get('input', ''))
        self.assertIn("PLAN_ASSERT", prompt)
        self.assertIn("What's the approach?", prompt)

    def test_dialog_history_in_prompt(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("response")) as mock_run:
            mod.generate("WORK_ASSERT", "And then?",
                         dialog_history="HUMAN: hi\nAGENT: hello")
        call_args = mock_run.call_args
        prompt = call_args.kwargs.get('input', call_args[1].get('input', ''))
        self.assertIn("PRIOR DIALOG", prompt)
        self.assertIn("HUMAN: hi", prompt)

    def test_artifact_content_in_prompt(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md',
                                         delete=False) as f:
            f.write("# Plan Content Here")
            f.flush()
            with patch('subprocess.run',
                       return_value=self._mock_llm("response")) as mock_run:
                mod.generate("PLAN_ASSERT", "What is this?",
                             artifact_path=f.name)
        call_args = mock_run.call_args
        prompt = call_args.kwargs.get('input', call_args[1].get('input', ''))
        self.assertIn("Plan Content Here", prompt)
        os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
