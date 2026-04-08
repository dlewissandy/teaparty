#!/usr/bin/env python3
"""Tests for generate_commit_message.py."""
import os
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import teaparty.scripts.generate_commit_message as mod


class TestBuildFallback(unittest.TestCase):

    def test_basic_fallback(self):
        result = mod.build_fallback("coding", "Add new feature")
        self.assertEqual(result, "coding: Add new feature")

    def test_long_task_truncated(self):
        long_task = "x" * 200
        result = mod.build_fallback("coding", long_task)
        self.assertLessEqual(len(result), len("coding: ") + 60)

    def test_empty_task_uses_dispatch(self):
        result = mod.build_fallback("art", "")
        self.assertEqual(result, "art: dispatch")

    def test_whitespace_task_uses_dispatch(self):
        result = mod.build_fallback("writing", "   ")
        self.assertEqual(result, "writing: dispatch")


class TestGenerate(unittest.TestCase):

    def _mock_llm(self, stdout, returncode=0):
        mock = MagicMock()
        mock.returncode = returncode
        mock.stdout = stdout
        return mock

    def test_generates_commit_message(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm(
                       "coding: add LLM commit generation\n\nAdds generate_commit_message.py")):
            result = mod.generate("Add LLM commit", "coding")
        self.assertIn("coding", result)

    def test_empty_task_still_calls_llm(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("task: dispatch\n\nNo task provided.")):
            result = mod.generate("", "task")
        self.assertIsNotNone(result)

    def test_timeout_returns_fallback(self):
        with patch('subprocess.run',
                   side_effect=subprocess.TimeoutExpired("claude", 30)):
            result = mod.generate("Build feature", "coding")
        self.assertEqual(result, mod.build_fallback("coding", "Build feature"))

    def test_not_found_returns_fallback(self):
        with patch('subprocess.run', side_effect=FileNotFoundError()):
            result = mod.generate("Build feature", "coding")
        self.assertEqual(result, mod.build_fallback("coding", "Build feature"))

    def test_nonzero_exit_returns_fallback(self):
        with patch('subprocess.run', return_value=self._mock_llm("", 1)):
            result = mod.generate("Build feature", "coding")
        self.assertEqual(result, mod.build_fallback("coding", "Build feature"))

    def test_empty_output_returns_fallback(self):
        with patch('subprocess.run', return_value=self._mock_llm("   ")):
            result = mod.generate("Build feature", "coding")
        self.assertEqual(result, mod.build_fallback("coding", "Build feature"))

    def test_dispatch_log_included_in_prompt(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("coding: squash")) as mock_run:
            mod.generate("Task", "coding", dispatch_log="- commit 1\n- commit 2")
        call_args = mock_run.call_args
        prompt = call_args.kwargs.get('input', call_args[1].get('input', ''))
        self.assertIn("commit 1", prompt)

    def test_files_included_in_prompt(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("coding: update")) as mock_run:
            mod.generate("Task", "coding", files="scripts/foo.py\nscripts/bar.py")
        call_args = mock_run.call_args
        prompt = call_args.kwargs.get('input', call_args[1].get('input', ''))
        self.assertIn("foo.py", prompt)

    def test_team_in_prompt(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("art: create diagram")) as mock_run:
            mod.generate("Create diagrams", "art")
        call_args = mock_run.call_args
        prompt = call_args.kwargs.get('input', call_args[1].get('input', ''))
        self.assertIn("art", prompt)


class TestBuildPrompt(unittest.TestCase):

    def test_basic_prompt(self):
        prompt = mod._build_prompt("Add feature", "coding")
        self.assertIn("coding", prompt)
        self.assertIn("Add feature", prompt)

    def test_dispatch_log_in_prompt(self):
        prompt = mod._build_prompt("Task", "coding", dispatch_log="- commit 1")
        self.assertIn("commit 1", prompt)

    def test_empty_team_defaults(self):
        prompt = mod._build_prompt("Task", "")
        self.assertIn("task", prompt)


class TestGenerateAsync(unittest.TestCase):

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_generates_message(self):
        """When claude CLI succeeds, returns its output."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b"coding: add feature\n\nAdded new feature.", b''))

        async def _test():
            with patch('asyncio.wait_for', side_effect=[
                mock_proc,   # first wait_for: process creation
                (b"coding: add feature\n\nAdded new feature.", b''),  # second: communicate
            ]):
                return await mod.generate_async("Build feature", "coding")

        result = self._run(_test())
        self.assertIn("coding: add feature", result)

    def test_fallback_on_missing_binary(self):
        """When claude binary is not found, returns fallback."""
        async def _test():
            with patch('asyncio.wait_for', side_effect=FileNotFoundError()):
                return await mod.generate_async("Build feature", "coding")

        result = self._run(_test())
        self.assertEqual(result, mod.build_fallback("coding", "Build feature"))

    def test_fallback_on_timeout(self):
        """When subprocess times out, returns fallback."""
        import asyncio as aio
        async def _test():
            with patch('asyncio.wait_for', side_effect=aio.TimeoutError()):
                return await mod.generate_async("Build feature", "coding")

        result = self._run(_test())
        self.assertEqual(result, mod.build_fallback("coding", "Build feature"))


if __name__ == "__main__":
    unittest.main()
