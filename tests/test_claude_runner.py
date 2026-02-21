import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from teaparty_app.services.claude_runner import (
    ClaudeResult,
    run_claude,
    _parse_json_output,
)


class ParseJsonOutputTests(unittest.TestCase):
    """Test NDJSON parsing of --output-format stream-json --verbose output.

    Each line of stdout is a separate JSON event.  The parser collects all
    events and extracts the result entry for the final ClaudeResult."""

    def test_parse_ndjson_with_result_event(self) -> None:
        """Standard stream-json output: multiple event lines, result at end."""
        lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "s1", "model": "sonnet"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}}),
            json.dumps({
                "type": "result", "subtype": "success",
                "result": "Hi there!",
                "is_error": False,
                "total_cost_usd": 0.02,
                "num_turns": 1,
                "session_id": "s1",
                "model": "sonnet",
                "usage": {"input_tokens": 40, "output_tokens": 10},
            }),
        ]
        raw = "\n".join(lines)
        result = _parse_json_output(raw, elapsed_ms=900)

        self.assertEqual(result.text, "Hi there!")
        self.assertEqual(result.cost_usd, 0.02)
        self.assertEqual(result.input_tokens, 40)
        self.assertEqual(result.output_tokens, 10)
        self.assertEqual(result.session_id, "s1")
        self.assertEqual(result.num_turns, 1)
        self.assertFalse(result.is_error)

    def test_events_preserved_from_ndjson(self) -> None:
        """All parsed events are available in result.events."""
        lines = [
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}}),
            json.dumps({"type": "result", "result": "Done", "usage": {}}),
        ]
        raw = "\n".join(lines)
        result = _parse_json_output(raw, elapsed_ms=100)

        self.assertEqual(len(result.events), 3)
        self.assertEqual(result.events[0]["type"], "system")
        self.assertEqual(result.events[1]["type"], "assistant")
        self.assertEqual(result.events[2]["type"], "result")

    def test_error_flag_in_result_event(self) -> None:
        raw = json.dumps({
            "type": "result",
            "result": "Error message here",
            "is_error": True,
            "usage": {},
        })
        result = _parse_json_output(raw, elapsed_ms=200)
        self.assertTrue(result.is_error)
        self.assertEqual(result.error, "Error message here")

    def test_non_json_falls_back_to_plain_text(self) -> None:
        raw = "This is not JSON, just plain text output"
        result = _parse_json_output(raw, elapsed_ms=1000)

        self.assertEqual(result.text, raw.strip())
        self.assertEqual(result.duration_ms, 1000)
        self.assertEqual(result.cost_usd, 0.0)
        self.assertEqual(result.input_tokens, 0)
        self.assertEqual(result.output_tokens, 0)
        self.assertFalse(result.is_error)

    def test_ndjson_without_result_entry(self) -> None:
        """NDJSON with events but no result entry returns empty text."""
        raw = json.dumps({"type": "system", "subtype": "init"})
        result = _parse_json_output(raw, elapsed_ms=100)
        self.assertEqual(result.text, "")
        self.assertFalse(result.is_error)
        self.assertEqual(len(result.events), 1)

    def test_cost_usd_field(self) -> None:
        raw = json.dumps({
            "type": "result",
            "result": "Test",
            "cost_usd": 0.05,
            "usage": {"input_tokens": 80, "output_tokens": 20},
        })
        result = _parse_json_output(raw, elapsed_ms=800)
        self.assertEqual(result.cost_usd, 0.05)

    def test_total_cost_usd_fallback(self) -> None:
        raw = json.dumps({
            "type": "result",
            "result": "Test",
            "total_cost_usd": 0.03,
            "usage": {"input_tokens": 80, "output_tokens": 20},
        })
        result = _parse_json_output(raw, elapsed_ms=800)
        self.assertEqual(result.cost_usd, 0.03)

    def test_missing_fields_default_to_zero(self) -> None:
        raw = json.dumps({"type": "result", "result": "Minimal response"})
        result = _parse_json_output(raw, elapsed_ms=500)

        self.assertEqual(result.text, "Minimal response")
        self.assertEqual(result.cost_usd, 0.0)
        self.assertEqual(result.input_tokens, 0)
        self.assertEqual(result.output_tokens, 0)

    def test_skips_malformed_lines(self) -> None:
        """Non-JSON lines in the output are silently skipped."""
        lines = [
            "some debug output",
            json.dumps({"type": "result", "result": "OK", "usage": {}}),
            "another stray line",
        ]
        raw = "\n".join(lines)
        result = _parse_json_output(raw, elapsed_ms=100)
        self.assertEqual(result.text, "OK")
        self.assertEqual(len(result.events), 1)


class RunClaudeTests(unittest.IsolatedAsyncioTestCase):
    """Test the run_claude async function."""

    async def test_successful_invocation(self) -> None:
        """Test a successful claude -p subprocess call."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(
                json.dumps({"type": "result", "result": "Success", "cost_usd": 0.01, "usage": {"input_tokens": 50, "output_tokens": 30}}).encode(),
                b"",
            )
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            result = await run_claude(
                system_prompt="You are a helpful assistant.",
                user_message="Hello",
                model="sonnet",
                max_turns=3,
                timeout_seconds=120,
            )

            self.assertEqual(result.text, "Success")
            self.assertEqual(result.cost_usd, 0.01)
            self.assertEqual(result.input_tokens, 50)
            self.assertEqual(result.output_tokens, 30)
            self.assertFalse(result.is_error)

            # Verify command construction uses stream-json
            cmd = mock_exec.call_args[0]
            self.assertEqual(cmd[0], "claude")
            self.assertEqual(cmd[1], "-p")
            self.assertIn("--output-format", cmd)
            idx = cmd.index("--output-format")
            self.assertEqual(cmd[idx + 1], "stream-json")
            self.assertIn("--model", cmd)
            self.assertIn("sonnet", cmd)
            self.assertIn("--max-turns", cmd)
            self.assertIn("3", cmd)
            self.assertIn("--system-prompt", cmd)

    async def test_subprocess_timeout(self) -> None:
        """Test timeout handling."""
        mock_process = MagicMock()
        mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_process.kill = MagicMock()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            result = await run_claude(
                system_prompt="Test",
                user_message="Test message",
                timeout_seconds=5,
            )

            self.assertTrue(result.is_error)
            self.assertIn("Timed out after 5s", result.error)
            self.assertGreaterEqual(result.duration_ms, 0)
            mock_process.kill.assert_called_once()

    async def test_file_not_found(self) -> None:
        """Test handling when claude CLI is not on PATH."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = FileNotFoundError("claude not found")

            result = await run_claude(
                system_prompt="Test",
                user_message="Test",
            )

            self.assertTrue(result.is_error)
            self.assertEqual(result.error, "claude CLI not found on PATH")
            self.assertGreaterEqual(result.duration_ms, 0)

    async def test_non_zero_exit_code(self) -> None:
        """Test handling of subprocess error exits."""
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(
            return_value=(
                b"",
                b"Error: invalid arguments",
            )
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            result = await run_claude(
                system_prompt="Test",
                user_message="Test",
            )

            self.assertTrue(result.is_error)
            self.assertIn("invalid arguments", result.error)

    async def test_command_construction_with_allowed_tools(self) -> None:
        """Test that allowed_tools are passed correctly."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"type":"result","result":"OK"}', b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            await run_claude(
                system_prompt="Test",
                user_message="Test",
                allowed_tools=["Read", "Write", "Bash"],
            )

            cmd = mock_exec.call_args[0]
            self.assertIn("--allowedTools", cmd)
            idx = cmd.index("--allowedTools")
            self.assertEqual(cmd[idx + 1], "Read,Write,Bash")

    async def test_command_construction_with_disallowed_tools(self) -> None:
        """Test that disallowed_tools are passed correctly."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"type":"result","result":"OK"}', b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            await run_claude(
                system_prompt="Test",
                user_message="Test",
                disallowed_tools=["Bash"],
            )

            cmd = mock_exec.call_args[0]
            self.assertIn("--disallowedTools", cmd)
            idx = cmd.index("--disallowedTools")
            self.assertEqual(cmd[idx + 1], "Bash")

    async def test_command_construction_default_no_tools(self) -> None:
        """Test that without allowed or disallowed tools, non-agent mode defaults to no tools."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"type":"result","result":"OK"}', b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            await run_claude(
                system_prompt="Test",
                user_message="Test",
            )

            cmd = mock_exec.call_args[0]
            self.assertIn("--allowedTools", cmd)
            idx = cmd.index("--allowedTools")
            self.assertEqual(cmd[idx + 1], "")

    async def test_agent_mode_does_not_restrict_tools_by_default(self) -> None:
        """Agent mode should NOT add --allowedTools '' (needs Task tool for delegation)."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"type":"result","result":"OK"}', b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            await run_claude(
                user_message="Test",
                agent_name="lead",
                agents_json='{"lead": {"prompt": "test"}}',
            )

            cmd = mock_exec.call_args[0]
            self.assertNotIn("--allowedTools", cmd)
            self.assertNotIn("--disallowedTools", cmd)

    async def test_env_strips_nested_session_vars(self) -> None:
        """Test that CLAUDECODE and CLAUDE_CODE_ENTRYPOINT are stripped from env."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"type":"result","result":"OK"}', b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec, \
             patch.dict("os.environ", {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"}):
            mock_exec.return_value = mock_process

            await run_claude(
                system_prompt="Test",
                user_message="Test",
            )

            call_kwargs = mock_exec.call_args[1]
            env = call_kwargs["env"]
            self.assertNotIn("CLAUDECODE", env)
            self.assertNotIn("CLAUDE_CODE_ENTRYPOINT", env)

    async def test_resume_session_id_adds_flag(self) -> None:
        """Test that resume_session_id adds --resume <id> to the command."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"type":"result","result":"OK"}', b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            await run_claude(
                user_message="Follow-up message",
                agent_name="lead",
                agents_json='{"lead": {"prompt": "test"}}',
                resume_session_id="sess-abc-123",
            )

            cmd = mock_exec.call_args[0]
            self.assertIn("--resume", cmd)
            idx = cmd.index("--resume")
            self.assertEqual(cmd[idx + 1], "sess-abc-123")

    async def test_no_resume_flag_when_session_id_is_none(self) -> None:
        """Test that --resume is absent when resume_session_id is not set."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"type":"result","result":"OK"}', b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            await run_claude(
                user_message="Fresh message",
                agent_name="lead",
                agents_json='{"lead": {"prompt": "test"}}',
            )

            cmd = mock_exec.call_args[0]
            self.assertNotIn("--resume", cmd)

    async def test_user_message_passed_via_stdin(self) -> None:
        """Test that user_message is passed via stdin."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"type":"result","result":"OK"}', b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            user_msg = "Test message with special chars: ${}[]"
            await run_claude(
                system_prompt="Test",
                user_message=user_msg,
            )

            mock_process.communicate.assert_called_once_with(input=user_msg.encode())


if __name__ == "__main__":
    unittest.main()
