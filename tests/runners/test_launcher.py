"""Specification tests for the unified agent launcher (Issue #394).

Every agent in TeaParty must launch through a single function that reads
.teaparty/ config and produces the correct `claude -p` invocation.  These
tests encode the design doc requirements from
docs/detailed-design/unified-agent-launch.md.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

import yaml


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_teaparty_tree(root: str, scope: str = 'management') -> str:
    """Create a minimal .teaparty/{scope}/ tree with one agent and return teaparty_home."""
    tp = os.path.join(root, '.teaparty')
    scope_dir = os.path.join(tp, scope)
    agents_dir = os.path.join(scope_dir, 'agents', 'test-agent')
    skills_dir = os.path.join(scope_dir, 'skills', 'test-skill')
    os.makedirs(agents_dir)
    os.makedirs(skills_dir)

    # Agent definition with skills allowlist
    with open(os.path.join(agents_dir, 'agent.md'), 'w') as f:
        f.write('---\n')
        f.write('description: Test agent\n')
        f.write('tools: Read,Write,Grep\n')
        f.write('skills:\n')
        f.write('  - test-skill\n')
        f.write('---\n')
        f.write('You are a test agent.\n')

    # Agent-level settings override
    with open(os.path.join(agents_dir, 'settings.yaml'), 'w') as f:
        yaml.dump({'agent_override': True, 'permissions': {'allow': ['Read']}}, f)

    # Skill
    os.makedirs(os.path.join(skills_dir), exist_ok=True)
    with open(os.path.join(skills_dir, 'SKILL.md'), 'w') as f:
        f.write('# Test Skill\nDo the thing.\n')

    # Base settings
    with open(os.path.join(scope_dir, 'settings.yaml'), 'w') as f:
        yaml.dump({'base_setting': True}, f)

    return tp


def _make_workgroup(tp: str, scope: str, name: str, lead: str, members: list[str]) -> None:
    """Create a workgroup YAML file."""
    wg_dir = os.path.join(tp, scope, 'workgroups')
    os.makedirs(wg_dir, exist_ok=True)
    with open(os.path.join(wg_dir, f'{name}.yaml'), 'w') as f:
        yaml.dump({
            'name': name,
            'lead': lead,
            'members': {'agents': members},
        }, f)


class _TempDirMixin:
    """Mixin that creates a temp directory and cleans it up."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# ── 1. Single launch function exists ────────────────────────────────────────

class TestLaunchFunctionExists(unittest.TestCase):
    """The unified launcher must be importable as a single public function."""

    def test_launch_is_importable(self):
        """launch() must be importable from teaparty.runners.launcher."""
        from teaparty.runners.launcher import launch
        self.assertTrue(callable(launch))

    def test_launch_signature_accepts_agent_name_message_scope(self):
        """launch() must accept agent_name, message, and scope as parameters."""
        import inspect
        from teaparty.runners.launcher import launch
        sig = inspect.signature(launch)
        params = list(sig.parameters.keys())
        self.assertIn('agent_name', params)
        self.assertIn('message', params)
        self.assertIn('scope', params)


# ── 2. Production command via launch() ───────────────────────────────────────

class TestProductionCommand(_TempDirMixin, unittest.TestCase):
    """launch() must produce a claude -p subprocess with the correct flags,
    derived entirely from .teaparty/ config. Tests the ACTUAL production path
    by mocking create_subprocess_exec and inspecting the args it receives."""

    def setUp(self):
        super().setUp()
        self._tp = _make_teaparty_tree(self._tmpdir)
        self._worktree = os.path.join(self._tmpdir, 'worktree')
        os.makedirs(os.path.join(self._worktree, '.claude'), exist_ok=True)
        with open(os.path.join(self._worktree, '.claude', 'CLAUDE.md'), 'w') as f:
            f.write('# Repo\n')

    def _capture_subprocess_args(self):
        """Run launch() with a mocked subprocess, return the captured args."""
        import asyncio
        from unittest.mock import patch
        from tests.runners.test_dispatch_chain import _make_mock_process, _stream_json_events

        captured = {}

        async def mock_create(*args, **kwargs):
            captured['args'] = list(args)
            captured['env'] = kwargs.get('env', {})
            return await _make_mock_process(_stream_json_events('sess-1', 'ok'))

        async def run(resume='', mcp_port=0):
            from teaparty.runners.launcher import launch
            with patch('asyncio.create_subprocess_exec', side_effect=mock_create):
                await launch(
                    agent_name='test-agent',
                    message='hello',
                    scope='management',
                    teaparty_home=self._tp,
                    worktree=self._worktree,
                    resume_session=resume,
                    mcp_port=mcp_port,
                )
            return captured

        return run

    def test_always_present_flags(self):
        """Every launch must include --agent, --output-format stream-json,
        --verbose, --setting-sources user."""
        import asyncio
        run = self._capture_subprocess_args()
        captured = asyncio.run(run())
        cmd = captured['args']
        self.assertIn('claude', cmd)
        self.assertIn('-p', cmd)
        idx = cmd.index('--output-format')
        self.assertEqual(cmd[idx + 1], 'stream-json')
        self.assertIn('--verbose', cmd)
        idx = cmd.index('--setting-sources')
        self.assertEqual(cmd[idx + 1], 'user')
        idx = cmd.index('--agent')
        self.assertEqual(cmd[idx + 1], 'test-agent')

    def test_resume_flag_when_session_provided(self):
        """--resume must be included when a session_id is provided."""
        import asyncio
        run = self._capture_subprocess_args()
        captured = asyncio.run(run(resume='abc-123'))
        cmd = captured['args']
        idx = cmd.index('--resume')
        self.assertEqual(cmd[idx + 1], 'abc-123')

    def test_no_resume_when_cold_start(self):
        """--resume must NOT be included when no session_id is provided."""
        import asyncio
        run = self._capture_subprocess_args()
        captured = asyncio.run(run())
        cmd = captured['args']
        self.assertNotIn('--resume', cmd)

    def test_no_input_format_flag(self):
        """--input-format must NOT be present (no persistent NDJSON stdin)."""
        import asyncio
        run = self._capture_subprocess_args()
        captured = asyncio.run(run())
        cmd = captured['args']
        self.assertNotIn('--input-format', cmd)

    def test_env_strips_secrets(self):
        """Agent subprocess env must not inherit orchestrator secrets."""
        import asyncio
        os.environ['SUPER_SECRET_TOKEN'] = 'leaked'
        try:
            run = self._capture_subprocess_args()
            captured = asyncio.run(run())
            env = captured['env']
            self.assertNotIn('SUPER_SECRET_TOKEN', env)
            self.assertIn('PATH', env)
        finally:
            del os.environ['SUPER_SECRET_TOKEN']

    def test_agent_teams_env_var_removed(self):
        """CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS must never be in agent env."""
        import asyncio
        os.environ['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'] = '1'
        try:
            run = self._capture_subprocess_args()
            captured = asyncio.run(run())
            env = captured['env']
            self.assertNotIn('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS', env)
        finally:
            del os.environ['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS']

    def test_mcp_config_passed_via_cli_flag(self):
        """--mcp-config must point to the composed .mcp.json in the worktree.

        --setting-sources user prevents Claude Code from reading project-level
        .mcp.json automatically, so it must be passed explicitly."""
        import asyncio
        run = self._capture_subprocess_args()
        captured = asyncio.run(run(mcp_port=9000))
        cmd = captured['args']
        # .mcp.json should exist in worktree
        mcp_path = os.path.join(self._worktree, '.mcp.json')
        self.assertTrue(os.path.exists(mcp_path))
        with open(mcp_path) as f:
            mcp = json.load(f)
        self.assertIn('/mcp/management/test-agent',
                       mcp['mcpServers']['teaparty-config']['url'])
        # --mcp-config must be in the CLI args (--setting-sources user blocks
        # project-level discovery, so we must pass it explicitly)
        idx = cmd.index('--mcp-config')
        self.assertEqual(cmd[idx + 1], mcp_path)


# ── 3. Worktree composition ─────────────────────────────────────────────────

class TestWorktreeComposition(_TempDirMixin, unittest.TestCase):
    """The launcher must compose the worktree .claude/ directory from
    .teaparty/ config: agent def, filtered skills, merged settings, MCP config.
    The repo CLAUDE.md must NOT be overwritten."""

    def setUp(self):
        super().setUp()
        self._tp = _make_teaparty_tree(self._tmpdir)
        self._worktree = os.path.join(self._tmpdir, 'worktree')
        os.makedirs(self._worktree)
        # Simulate repo CLAUDE.md in worktree
        claude_dir = os.path.join(self._worktree, '.claude')
        os.makedirs(claude_dir)
        with open(os.path.join(claude_dir, 'CLAUDE.md'), 'w') as f:
            f.write('# Repo CLAUDE.md\nThis is the repo-level instruction file.\n')

    def test_repo_claude_md_not_overwritten(self):
        """compose_claude_md must be deleted. The repo's CLAUDE.md must never
        be overwritten by the launcher."""
        from teaparty.runners.launcher import compose_launch_worktree
        compose_launch_worktree(
            worktree=self._worktree,
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        claude_md = os.path.join(self._worktree, '.claude', 'CLAUDE.md')
        with open(claude_md) as f:
            content = f.read()
        self.assertIn('Repo CLAUDE.md', content,
                       'Repo CLAUDE.md was overwritten by the launcher')

    def test_agent_definition_copied(self):
        """The agent definition must be copied into .claude/agents/{name}.md."""
        from teaparty.runners.launcher import compose_launch_worktree
        compose_launch_worktree(
            worktree=self._worktree,
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        agent_md = os.path.join(self._worktree, '.claude', 'agents', 'test-agent.md')
        self.assertTrue(os.path.exists(agent_md),
                        f'Agent definition not found at {agent_md}')
        with open(agent_md) as f:
            content = f.read()
        self.assertIn('Test agent', content)

    def test_skills_filtered_by_agent_allowlist(self):
        """Only skills named in the agent's skills: frontmatter must be included."""
        # Add a second skill NOT in the allowlist
        extra_skill = os.path.join(self._tp, 'management', 'skills', 'forbidden-skill')
        os.makedirs(extra_skill)
        with open(os.path.join(extra_skill, 'SKILL.md'), 'w') as f:
            f.write('# Forbidden\n')

        from teaparty.runners.launcher import compose_launch_worktree
        compose_launch_worktree(
            worktree=self._worktree,
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        skills_dir = os.path.join(self._worktree, '.claude', 'skills')
        if os.path.isdir(skills_dir):
            present = set(os.listdir(skills_dir))
        else:
            present = set()
        self.assertIn('test-skill', present)
        self.assertNotIn('forbidden-skill', present,
                         'Skill not in agent allowlist was included')

    def test_settings_json_is_merged(self):
        """settings.json must be the merge of scope + agent settings."""
        from teaparty.runners.launcher import compose_launch_worktree
        compose_launch_worktree(
            worktree=self._worktree,
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        settings_path = os.path.join(self._worktree, '.claude', 'settings.json')
        self.assertTrue(os.path.exists(settings_path))
        with open(settings_path) as f:
            settings = json.load(f)
        self.assertTrue(settings.get('base_setting'))
        self.assertTrue(settings.get('agent_override'))

    def test_mcp_json_points_to_http_server(self):
        """The worktree must contain .mcp.json pointing to the scoped HTTP endpoint."""
        from teaparty.runners.launcher import compose_launch_worktree
        compose_launch_worktree(
            worktree=self._worktree,
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
            mcp_port=9000,
        )
        mcp_path = os.path.join(self._worktree, '.mcp.json')
        self.assertTrue(os.path.exists(mcp_path))
        with open(mcp_path) as f:
            mcp = json.load(f)
        url = mcp['mcpServers']['teaparty-config']['url']
        self.assertIn('/mcp/management/test-agent', url)


# ── 4. Agent definition resolution ──────────────────────────────────────────

class TestAgentDefinitionResolution(_TempDirMixin, unittest.TestCase):
    """Agent definitions resolve project-first, fall back to management."""

    def setUp(self):
        super().setUp()
        self._tp = _make_teaparty_tree(self._tmpdir)
        # Also create a project-scope agent with the same name
        proj_agents = os.path.join(self._tp, 'project', 'agents', 'test-agent')
        os.makedirs(proj_agents)
        with open(os.path.join(proj_agents, 'agent.md'), 'w') as f:
            f.write('---\ndescription: Project override agent\n---\n')

    def test_project_scope_overrides_management(self):
        """When both scopes have an agent, project scope wins."""
        from teaparty.runners.launcher import resolve_agent_definition
        path = resolve_agent_definition('test-agent', 'project', self._tp)
        with open(path) as f:
            content = f.read()
        self.assertIn('Project override', content)

    def test_management_fallback_when_no_project_def(self):
        """When project scope lacks an agent, management scope is used."""
        from teaparty.runners.launcher import resolve_agent_definition
        path = resolve_agent_definition('test-agent', 'management', self._tp)
        with open(path) as f:
            content = f.read()
        self.assertIn('Test agent', content)


# ── 5. compose_claude_md is deleted ─────────────────────────────────────────

class TestComposeCLAUDEMdDeleted(unittest.TestCase):
    """compose_claude_md must no longer exist in agent_spawner.py."""

    def test_compose_claude_md_not_callable_from_launcher(self):
        """The launcher module must not export or use compose_claude_md."""
        from teaparty.runners import launcher
        self.assertFalse(
            hasattr(launcher, 'compose_claude_md'),
            'compose_claude_md should not exist in the launcher module',
        )




# ── 8. Directory structure: config vs runtime separation ─────────────────────

class TestDirectoryStructure(_TempDirMixin, unittest.TestCase):
    """Sessions must live in {scope}/sessions/, separate from config."""

    def setUp(self):
        super().setUp()
        self._tp = _make_teaparty_tree(self._tmpdir)

    def test_session_directory_created_under_scope(self):
        """create_session must place session data under {scope}/sessions/{session-id}/."""
        from teaparty.runners.launcher import create_session
        session = create_session(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        # Session path must be under .teaparty/management/sessions/
        self.assertIn(
            os.path.join(self._tp, 'management', 'sessions'),
            session.path,
        )

    def test_session_has_metadata_json(self):
        """Each session must have a metadata.json tracking state."""
        from teaparty.runners.launcher import create_session
        session = create_session(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        meta_path = os.path.join(session.path, 'metadata.json')
        self.assertTrue(os.path.exists(meta_path))
        with open(meta_path) as f:
            meta = json.load(f)
        self.assertEqual(meta['agent_name'], 'test-agent')

    def test_session_not_in_agent_config_dir(self):
        """Session state must NOT live in the agent config directory."""
        from teaparty.runners.launcher import create_session
        session = create_session(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        agent_config_dir = os.path.join(self._tp, 'management', 'agents', 'test-agent')
        self.assertFalse(
            session.path.startswith(agent_config_dir),
            'Session must not live in the agent config directory',
        )


# ── 9. Concurrency constraints ──────────────────────────────────────────────

class TestConcurrencyConstraints(_TempDirMixin, unittest.TestCase):
    """Per-agent conversation limit and system-wide ceiling."""

    def setUp(self):
        super().setUp()
        self._tp = _make_teaparty_tree(self._tmpdir)

    def test_conversation_map_tracks_open_slots(self):
        """metadata.json must maintain a conversation_map tracking open sessions."""
        from teaparty.runners.launcher import create_session, record_child_session
        session = create_session(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        record_child_session(session, request_id='req-1', child_session_id='child-1')
        meta_path = os.path.join(session.path, 'metadata.json')
        with open(meta_path) as f:
            meta = json.load(f)
        conv_map = meta.get('conversation_map', {})
        self.assertEqual(conv_map['req-1'], 'child-1')

    def test_per_agent_limit_of_three(self):
        """A fourth child session must not be allowed (per-agent limit of 3)."""
        from teaparty.runners.launcher import (
            create_session,
            record_child_session,
            check_slot_available,
        )
        session = create_session(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        for i in range(3):
            record_child_session(session, request_id=f'req-{i}', child_session_id=f'child-{i}')
        self.assertFalse(
            check_slot_available(session),
            'Fourth slot should not be available (per-agent limit of 3)',
        )


# ── 10. Session health detection ────────────────────────────────────────────

class TestSessionHealthDetection(unittest.TestCase):
    """The launcher must detect poisoned sessions and empty responses."""

    def test_poisoned_session_detected_from_system_events(self):
        """When system events show MCP 'failed', session is poisoned."""
        from teaparty.runners.launcher import detect_poisoned_session
        events = [
            {'type': 'system', 'subtype': 'init', 'session_id': 'abc',
             'mcp_servers': [{'name': 'teaparty-config', 'status': 'failed'}]},
        ]
        self.assertTrue(detect_poisoned_session(events))

    def test_healthy_session_not_flagged(self):
        """Normal system events must not trigger poisoned detection."""
        from teaparty.runners.launcher import detect_poisoned_session
        events = [
            {'type': 'system', 'subtype': 'init', 'session_id': 'abc',
             'mcp_servers': [{'name': 'teaparty-config', 'status': 'connected'}]},
        ]
        self.assertFalse(detect_poisoned_session(events))

    def test_empty_response_clears_session(self):
        """When no assistant text is produced, session ID must be cleared."""
        from teaparty.runners.launcher import should_clear_session
        self.assertTrue(should_clear_session(response_text='', session_id='abc'))
        self.assertFalse(should_clear_session(response_text='Hello', session_id='abc'))


# ── 11. Telemetry events (Issue #405) ───────────────────────────────────────

class TestTelemetry(_TempDirMixin, unittest.TestCase):
    """Per-turn telemetry must be written to the unified event store.

    Issue #405: the legacy per-scope metrics.db was replaced with a
    single event-sourced store at {teaparty_home}/telemetry.db. Every
    launch emits turn_start before the subprocess runs and turn_complete
    after it returns.
    """

    def setUp(self):
        super().setUp()
        self._tp = _make_teaparty_tree(self._tmpdir)
        from teaparty import telemetry
        telemetry.reset_for_tests()
        telemetry.set_teaparty_home(self._tp)

    def tearDown(self):
        from teaparty import telemetry
        telemetry.reset_for_tests()
        super().tearDown()

    def test_turn_complete_event_records_cost_tokens_duration(self):
        from teaparty import telemetry
        from teaparty.telemetry import events as E
        from teaparty.telemetry.record import record_event

        record_event(
            E.TURN_COMPLETE,
            scope='management',
            agent_name='test-agent',
            session_id='sess-abc',
            data={
                'cost_usd':      0.05,
                'input_tokens':  1000,
                'output_tokens': 500,
                'duration_ms':   3000,
                'exit_code':     0,
            },
        )

        rows = telemetry.query_events(
            event_type=E.TURN_COMPLETE, session='sess-abc',
        )
        self.assertEqual(len(rows), 1)
        ev = rows[0]
        self.assertEqual(ev.agent_name, 'test-agent')
        self.assertEqual(ev.scope, 'management')
        self.assertAlmostEqual(ev.data['cost_usd'], 0.05)
        self.assertEqual(ev.data['input_tokens'], 1000)
        self.assertEqual(ev.data['output_tokens'], 500)
        self.assertEqual(ev.data['duration_ms'], 3000)

    def test_turn_events_accumulate_in_single_telemetry_db(self):
        from teaparty import telemetry
        from teaparty.telemetry import events as E
        from teaparty.telemetry.record import record_event

        for i in range(3):
            record_event(
                E.TURN_COMPLETE,
                scope='management',
                agent_name='test-agent',
                session_id=f'sess-{i}',
                data={'cost_usd': 0.01 * (i + 1)},
            )

        self.assertEqual(telemetry.turn_count(), 3)
        self.assertAlmostEqual(telemetry.total_cost(), 0.06)

        # Legacy location must not exist.
        self.assertFalse(
            os.path.exists(os.path.join(self._tp, 'management', 'metrics.db')),
            'legacy metrics.db must not be created anywhere',
        )
        self.assertTrue(
            os.path.exists(os.path.join(self._tp, 'telemetry.db')),
            'unified telemetry.db must live at teaparty_home root',
        )

    def test_legacy_record_metrics_is_removed(self):
        """The legacy _record_metrics function must not exist."""
        from teaparty.runners import launcher
        self.assertFalse(
            hasattr(launcher, '_record_metrics'),
            'Issue #405: _record_metrics was replaced by record_event',
        )


if __name__ == '__main__':
    unittest.main()
