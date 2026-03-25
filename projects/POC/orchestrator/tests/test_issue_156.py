#!/usr/bin/env python3
"""Tests for Issue #156: Harden agent sandboxing and proxy approval.

Covers the four quick-win mitigations from the issue:
 1. Proxy agent must NOT have Bash in its allowed tools
 2. _build_env() must use an allowlist, not inherit all of os.environ
 3. Execution phase must NOT include WebFetch or WebSearch
 4. Dispatch listener must reject unknown team names at the socket handler
"""
import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_runner(env_vars=None):
    """Build a minimal ClaudeRunner for testing _build_env."""
    from projects.POC.orchestrator.claude_runner import ClaudeRunner
    return ClaudeRunner(
        prompt='test',
        cwd='/tmp',
        stream_file='/tmp/stream.jsonl',
        env_vars=env_vars or {},
    )


def _make_phase_config():
    """Build a PhaseConfig from the real phase-config.json."""
    from projects.POC.orchestrator import find_poc_root
    from projects.POC.orchestrator.phase_config import PhaseConfig
    return PhaseConfig(find_poc_root())


def _make_dispatch_listener():
    """Build a minimal DispatchListener for testing."""
    from projects.POC.orchestrator.dispatch_listener import DispatchListener
    from projects.POC.orchestrator.events import EventBus
    return DispatchListener(
        event_bus=EventBus(),
        session_worktree='/tmp/worktree',
        infra_dir='/tmp/infra',
        project_slug='test',
    )


# ── Risk 2C: Proxy agent must not have Bash ──────────────────────────────────

class TestProxyNoBash(unittest.TestCase):
    """The proxy agent runs with bypassPermissions. Bash would give it
    unrestricted command execution — an escalation vector if compromised
    via indirect prompt injection."""

    def test_proxy_invocation_does_not_include_bash(self):
        """The --allowedTools passed to the proxy must not include Bash."""
        import projects.POC.orchestrator.proxy_agent as mod
        import inspect
        source = inspect.getsource(mod._invoke_claude_proxy)
        # The allowedTools string in _invoke_claude_proxy should not contain Bash
        self.assertNotIn("Bash", source,
                         "Proxy agent must not have Bash in --allowedTools. "
                         "The proxy needs Read/Glob/Grep to inspect artifacts, "
                         "not Bash to execute arbitrary commands.")


# ── Risk 8: Environment variable allowlist ────────────────────────────────────

class TestEnvVarAllowlist(unittest.TestCase):
    """_build_env() must use an allowlist — not start with dict(os.environ).
    Inheriting the full environment leaks API keys, tokens, and credentials
    into agent subprocesses."""

    def test_build_env_excludes_unknown_vars(self):
        """Env vars not on the allowlist must not appear in _build_env() output."""
        secret = 'SUPER_SECRET_TOKEN_FOR_TEST_156'
        with patch.dict(os.environ, {secret: 'leaked'}):
            runner = _make_runner()
            env = runner._build_env()
            self.assertNotIn(secret, env,
                             '_build_env() must not inherit arbitrary env vars. '
                             'Use an allowlist of required vars instead of '
                             'dict(os.environ).')

    def test_build_env_includes_path(self):
        """PATH must be in the env — the claude CLI needs it to find executables."""
        runner = _make_runner()
        env = runner._build_env()
        self.assertIn('PATH', env)

    def test_build_env_includes_home(self):
        """HOME must be in the env — needed for ~/.claude config."""
        runner = _make_runner()
        env = runner._build_env()
        self.assertIn('HOME', env)

    def test_build_env_includes_anthropic_api_key(self):
        """ANTHROPIC_API_KEY must be passed through if set."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-test'}):
            runner = _make_runner()
            env = runner._build_env()
            self.assertIn('ANTHROPIC_API_KEY', env)

    def test_build_env_includes_claude_vars(self):
        """CLAUDE_* vars set by _build_env itself must be present."""
        runner = _make_runner()
        env = runner._build_env()
        self.assertIn('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS', env)
        self.assertIn('CLAUDE_CODE_MAX_OUTPUT_TOKENS', env)

    def test_build_env_includes_caller_env_vars(self):
        """env_vars passed by the orchestrator must override/extend the env."""
        runner = _make_runner(env_vars={'POC_SESSION_DIR': '/tmp/infra'})
        env = runner._build_env()
        self.assertEqual(env['POC_SESSION_DIR'], '/tmp/infra')


# ── Risk 5C: No WebFetch/WebSearch in execution phase ─────────────────────────

class TestExecutionPhaseNoWebTools(unittest.TestCase):
    """Execution-phase agents should not have web access — web content
    should be gathered during planning, not during building."""

    def test_execution_phase_excludes_web_tools(self):
        """WebFetch and WebSearch must not appear in execution phase permissions."""
        config = _make_phase_config()
        exec_spec = config.phase('execution')
        allowed = exec_spec.settings_overlay.get('permissions', {}).get('allow', [])
        self.assertNotIn('WebFetch', allowed,
                         "WebFetch must not be in execution phase — "
                         "agents should research during planning, not execution.")
        self.assertNotIn('WebSearch', allowed,
                         "WebSearch must not be in execution phase — "
                         "agents should research during planning, not execution.")

    def test_intent_phase_retains_web_tools(self):
        """Intent phase should still have web tools for research."""
        config = _make_phase_config()
        intent_spec = config.phase('intent')
        allowed = intent_spec.settings_overlay.get('permissions', {}).get('allow', [])
        self.assertIn('WebFetch', allowed)
        self.assertIn('WebSearch', allowed)

    def test_planning_phase_retains_web_tools(self):
        """Planning phase should still have web tools for research."""
        config = _make_phase_config()
        plan_spec = config.phase('planning')
        allowed = plan_spec.settings_overlay.get('permissions', {}).get('allow', [])
        self.assertIn('WebFetch', allowed)
        self.assertIn('WebSearch', allowed)


# ── Risk 9: Team name validation at dispatch socket ───────────────────────────

class TestDispatchTeamValidation(unittest.TestCase):
    """The dispatch listener must reject unknown team names at the socket
    handler level, before any further processing."""

    def test_invalid_team_rejected(self):
        """A team name not in phase-config.json must be rejected."""
        listener = _make_dispatch_listener()
        result = asyncio.get_event_loop().run_until_complete(
            listener._handle_dispatch('evil-team', 'do bad things')
        )
        self.assertEqual(result['status'], 'failed')
        self.assertIn('team', result.get('reason', '').lower(),
                       "Rejection reason should mention the invalid team name.")

    def test_valid_teams_not_rejected(self):
        """Known team names from phase-config.json must not be rejected
        at the validation level (they may still fail for other reasons)."""
        config = _make_phase_config()
        listener = _make_dispatch_listener()
        # We only test that the team name validation passes —
        # the actual dispatch will fail because there's no real session.
        # We patch dispatch() to isolate the validation.
        for team_name in config.teams:
            with patch('projects.POC.orchestrator.dispatch_listener.dispatch',
                       return_value={'status': 'completed'}):
                result = asyncio.get_event_loop().run_until_complete(
                    listener._handle_dispatch(team_name, 'test task')
                )
                self.assertNotEqual(
                    result.get('reason', ''), f'unknown team: {team_name}',
                    f'Valid team {team_name!r} should not be rejected',
                )


if __name__ == '__main__':
    unittest.main()
