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


# ── 2. Command composition from config ──────────────────────────────────────

class TestCommandComposition(_TempDirMixin, unittest.TestCase):
    """launch() must produce a claude -p command with the correct flags,
    derived entirely from .teaparty/ config."""

    def setUp(self):
        super().setUp()
        self._tp = _make_teaparty_tree(self._tmpdir)

    def test_always_present_flags(self):
        """Every launch must include --agent, --output-format stream-json,
        --verbose, --setting-sources user, --settings."""
        from teaparty.runners.launcher import build_launch_command
        cmd = build_launch_command(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        self.assertIn('claude', cmd)
        self.assertIn('-p', cmd)
        self.assertIn('--output-format', cmd)
        idx = cmd.index('--output-format')
        self.assertEqual(cmd[idx + 1], 'stream-json')
        self.assertIn('--verbose', cmd)
        self.assertIn('--setting-sources', cmd)
        idx = cmd.index('--setting-sources')
        self.assertEqual(cmd[idx + 1], 'user')
        self.assertIn('--agent', cmd)
        idx = cmd.index('--agent')
        self.assertEqual(cmd[idx + 1], 'test-agent')

    def test_settings_from_config_merge(self):
        """--settings must be derived from scope settings.yaml merged with
        agent settings.yaml (agent wins per-key)."""
        from teaparty.runners.launcher import build_launch_command
        cmd = build_launch_command(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        self.assertIn('--settings', cmd)
        idx = cmd.index('--settings')
        settings_path = cmd[idx + 1]
        # The settings file must exist (either temp file or path)
        # and contain the merged result
        with open(settings_path) as f:
            settings = json.load(f)
        self.assertTrue(settings.get('base_setting'), 'Base setting missing')
        self.assertTrue(settings.get('agent_override'), 'Agent override missing')

    def test_resume_session_flag(self):
        """--resume must be included when a session_id is provided."""
        from teaparty.runners.launcher import build_launch_command
        cmd = build_launch_command(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
            resume_session='abc-123',
        )
        self.assertIn('--resume', cmd)
        idx = cmd.index('--resume')
        self.assertEqual(cmd[idx + 1], 'abc-123')

    def test_no_resume_when_cold_start(self):
        """--resume must NOT be included when no session_id is provided."""
        from teaparty.runners.launcher import build_launch_command
        cmd = build_launch_command(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        self.assertNotIn('--resume', cmd)

    def test_mcp_config_when_agent_has_mcp(self):
        """--mcp-config must point to HTTP MCP server scoped to the agent."""
        from teaparty.runners.launcher import build_launch_command
        cmd = build_launch_command(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
            mcp_port=9000,
        )
        self.assertIn('--mcp-config', cmd)
        idx = cmd.index('--mcp-config')
        mcp_arg = cmd[idx + 1]
        # Must be a path to a file or JSON containing the HTTP URL
        if os.path.isfile(mcp_arg):
            with open(mcp_arg) as f:
                mcp_data = json.load(f)
        else:
            mcp_data = json.loads(mcp_arg)
        url = mcp_data['mcpServers']['teaparty-config']['url']
        self.assertIn('/mcp/management/test-agent', url)


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


# ── 6. Environment isolation ────────────────────────────────────────────────

class TestEnvironmentIsolation(unittest.TestCase):
    """Agents must not inherit orchestrator credentials or sensitive state."""

    def test_env_strips_to_allowlist(self):
        """build_launch_env must strip env to an allowlist, not inherit everything."""
        from teaparty.runners.launcher import build_launch_env
        os.environ['SUPER_SECRET_TOKEN'] = 'leaked'
        try:
            env = build_launch_env()
            self.assertNotIn('SUPER_SECRET_TOKEN', env)
            # But PATH must be present
            self.assertIn('PATH', env)
        finally:
            del os.environ['SUPER_SECRET_TOKEN']

    def test_agent_teams_env_var_removed(self):
        """CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS must never be passed to agents."""
        from teaparty.runners.launcher import build_launch_env
        os.environ['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'] = '1'
        try:
            env = build_launch_env()
            self.assertNotIn('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS', env)
        finally:
            del os.environ['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS']


# ── 7. All agents use stream-json ────────────────────────────────────────────

class TestAllAgentsStream(_TempDirMixin, unittest.TestCase):
    """Every agent must use --output-format stream-json. No json, no NDJSON stdin."""

    def setUp(self):
        super().setUp()
        self._tp = _make_teaparty_tree(self._tmpdir)

    def test_output_format_is_stream_json(self):
        """The command must use --output-format stream-json, not json."""
        from teaparty.runners.launcher import build_launch_command
        cmd = build_launch_command(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        idx = cmd.index('--output-format')
        self.assertEqual(cmd[idx + 1], 'stream-json',
                         'All agents must use stream-json, not json')

    def test_no_input_format_flag(self):
        """The command must NOT use --input-format (no persistent NDJSON stdin)."""
        from teaparty.runners.launcher import build_launch_command
        cmd = build_launch_command(
            agent_name='test-agent',
            scope='management',
            teaparty_home=self._tp,
        )
        self.assertNotIn('--input-format', cmd,
                         'No --input-format flag — agents are one-shot, not persistent')


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


if __name__ == '__main__':
    unittest.main()
