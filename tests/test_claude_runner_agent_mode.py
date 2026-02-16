import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from teaparty_app.services.claude_runner import ClaudeResult, run_claude


class RunClaudeAgentModeTests(unittest.IsolatedAsyncioTestCase):
    """Test the agent-based invocation mode of run_claude."""

    async def test_agent_mode_command_construction(self) -> None:
        """When agent_name + agents_json provided, use --agent/--agents instead of --system-prompt/--model."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b'{"result": "Agent response", "usage": {}}', b"")
        )

        agents_json = json.dumps({
            "implementer": {
                "description": "Implementation lead",
                "prompt": "You are Implementer.",
                "model": "sonnet",
                "maxTurns": 3,
            }
        })

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            result = await run_claude(
                user_message="Build the auth module",
                agent_name="implementer",
                agents_json=agents_json,
                max_turns=3,
            )

            cmd = mock_exec.call_args[0]
            self.assertIn("--agent", cmd)
            self.assertIn("implementer", cmd)
            self.assertIn("--agents", cmd)
            # Should NOT have --system-prompt or --model
            self.assertNotIn("--system-prompt", cmd)
            self.assertNotIn("--model", cmd)
            # Should have --permission-mode
            self.assertIn("--permission-mode", cmd)
            self.assertIn("bypassPermissions", cmd)

    async def test_legacy_mode_still_works(self) -> None:
        """Without agent_name, should use --system-prompt and --model as before."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b'{"result": "OK", "usage": {}}', b"")
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            await run_claude(
                system_prompt="You are helpful",
                user_message="Hello",
                model="sonnet",
            )

            cmd = mock_exec.call_args[0]
            self.assertIn("--system-prompt", cmd)
            self.assertIn("--model", cmd)
            self.assertIn("sonnet", cmd)
            self.assertNotIn("--agent", cmd)
            self.assertNotIn("--agents", cmd)

    async def test_settings_json_passed_through(self) -> None:
        """Test that --settings flag is passed when settings_json provided."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b'{"result": "OK", "usage": {}}', b"")
        )

        settings = json.dumps({"hooks": {"PreToolUse": []}})

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            await run_claude(
                system_prompt="Test",
                user_message="Test",
                settings_json=settings,
            )

            cmd = mock_exec.call_args[0]
            self.assertIn("--settings", cmd)
            idx = cmd.index("--settings")
            self.assertEqual(cmd[idx + 1], settings)

    async def test_permission_mode_default(self) -> None:
        """Test that permission_mode defaults to bypassPermissions."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b'{"result": "OK", "usage": {}}', b"")
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            await run_claude(
                system_prompt="Test",
                user_message="Test",
            )

            cmd = mock_exec.call_args[0]
            self.assertIn("--permission-mode", cmd)
            idx = cmd.index("--permission-mode")
            self.assertEqual(cmd[idx + 1], "bypassPermissions")

    async def test_agent_mode_no_settings_means_no_flag(self) -> None:
        """Without settings_json, no --settings flag."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b'{"result": "OK", "usage": {}}', b"")
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_process

            await run_claude(
                user_message="Test",
                agent_name="test-agent",
                agents_json='{"test-agent": {}}',
            )

            cmd = mock_exec.call_args[0]
            self.assertNotIn("--settings", cmd)


if __name__ == "__main__":
    unittest.main()
