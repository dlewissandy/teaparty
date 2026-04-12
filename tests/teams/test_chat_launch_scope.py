"""Specification tests for chat-tier launch scope (issue #397).

These tests encode the contract from issue #397:

1. Chat-tier launches create NO git worktrees — `spawn_fn` does not
   call `git worktree add`, and `_invoke_inner` does not call
   `ensure_agent_worktree`.
2. Office Manager and management leads launch with cwd = teaparty
   repo root.
3. Project leads launch with cwd = <project repo root> resolved from
   teaparty.yaml.
4. Launching never mutates `{launch_cwd}/.claude/`, `{launch_cwd}/.mcp.json`,
   or `{launch_cwd}/CLAUDE.md`.
5. Per-launch config files are written to the session directory and
   are the only filesystem mutation a chat launch performs.
6. Two concurrent launches of the same agent under different qualifiers
   use different config dirs and do not conflict.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml


def _init_repo(path: str) -> None:
    subprocess.run(['git', 'init', '-q'], cwd=path, check=True)
    subprocess.run(['git', 'config', 'user.email', 't@x'], cwd=path, check=True)
    subprocess.run(['git', 'config', 'user.name', 't'], cwd=path, check=True)
    with open(os.path.join(path, 'README.md'), 'w') as f:
        f.write('x\n')
    subprocess.run(['git', 'add', 'README.md'], cwd=path, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', 'init'], cwd=path, check=True)


def _make_env(root: str, *, with_project: bool = False) -> tuple[str, str, str]:
    """Create a teaparty repo + optional sibling project repo, return paths."""
    teaparty_repo = os.path.join(root, 'teaparty-root')
    os.makedirs(teaparty_repo)
    _init_repo(teaparty_repo)

    tp = os.path.join(teaparty_repo, '.teaparty')
    mgmt = os.path.join(tp, 'management')
    agents_dir = os.path.join(mgmt, 'agents')
    os.makedirs(agents_dir)

    # Minimal management agents: office-manager and comics-lead
    for name in ('office-manager', 'comics-lead', 'configuration-lead'):
        d = os.path.join(agents_dir, name)
        os.makedirs(d)
        with open(os.path.join(d, 'agent.md'), 'w') as f:
            f.write(f'---\ndescription: {name}\n---\n\nYou are {name}.\n')

    with open(os.path.join(mgmt, 'settings.yaml'), 'w') as f:
        yaml.dump({'base_setting': True}, f)

    project_repo = ''
    if with_project:
        project_repo = os.path.join(root, 'comics-root')
        os.makedirs(project_repo)
        _init_repo(project_repo)
        project_tp = os.path.join(project_repo, '.teaparty', 'project')
        os.makedirs(project_tp)
        with open(os.path.join(project_tp, 'project.yaml'), 'w') as f:
            yaml.dump({
                'name': 'comics',
                'lead': 'comics-lead',
                'description': 'comic-book project',
                'members': {'workgroups': []},
                'workgroups': [],
            }, f)

    # teaparty.yaml at both places (legacy and management/) — the
    # loader reads management/teaparty.yaml.
    mgmt_yaml = {
        'name': 'Management',
        'description': 'mgmt',
        'lead': 'office-manager',
        'projects': [],
        'members': {'projects': [], 'agents': [], 'workgroups': []},
        'workgroups': [],
    }
    if with_project:
        mgmt_yaml['projects'] = [{
            'name': 'comics',
            'path': project_repo,
            'config': '.teaparty/project/project.yaml',
        }]
        mgmt_yaml['members']['projects'] = ['comics']
    with open(os.path.join(mgmt, 'teaparty.yaml'), 'w') as f:
        yaml.dump(mgmt_yaml, f)

    return tp, teaparty_repo, project_repo


class TestResolveLaunchCwd(unittest.TestCase):
    """`resolve_launch_cwd` returns the right repo for each agent role."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_project_lead_resolves_to_project_repo(self):
        tp, teaparty_repo, project_repo = _make_env(
            self._tmpdir, with_project=True,
        )
        from teaparty.config.roster import resolve_launch_cwd
        cwd = resolve_launch_cwd('comics-lead', tp)
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(project_repo))

    def test_management_agent_falls_back_to_teaparty_repo(self):
        tp, teaparty_repo, _ = _make_env(self._tmpdir, with_project=True)
        from teaparty.config.roster import resolve_launch_cwd
        cwd = resolve_launch_cwd('configuration-lead', tp)
        self.assertEqual(
            os.path.realpath(cwd), os.path.realpath(teaparty_repo),
        )

    def test_missing_registry_does_not_raise(self):
        tp, teaparty_repo, _ = _make_env(self._tmpdir, with_project=False)
        # Delete management/teaparty.yaml entirely
        os.unlink(os.path.join(tp, 'management', 'teaparty.yaml'))
        from teaparty.config.roster import resolve_launch_cwd
        cwd = resolve_launch_cwd('configuration-lead', tp)
        self.assertEqual(
            os.path.realpath(cwd), os.path.realpath(teaparty_repo),
        )

    def test_fallback_used_when_not_a_project_lead(self):
        tp, teaparty_repo, project_repo = _make_env(
            self._tmpdir, with_project=True,
        )
        from teaparty.config.roster import resolve_launch_cwd
        # A workgroup agent dispatched under comics-lead inherits
        # comics-lead's cwd via the fallback parameter.
        cwd = resolve_launch_cwd(
            'coding-lead', tp, fallback=project_repo,
        )
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(project_repo))


class TestComposeLaunchConfig(unittest.TestCase):
    """`compose_launch_config` writes only to the config_dir."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tp, self._teaparty_repo, _ = _make_env(self._tmpdir)
        self._cfg_dir = os.path.join(self._tmpdir, 'session-A')

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_writes_settings_and_mcp_inside_config_dir(self):
        from teaparty.runners.launcher import compose_launch_config
        out = compose_launch_config(
            config_dir=self._cfg_dir,
            agent_name='office-manager',
            scope='management',
            teaparty_home=self._tp,
            mcp_port=9000,
            session_id='sess-A',
        )
        settings_path = out['settings_path']
        mcp_path = out['mcp_path']
        self.assertTrue(settings_path.startswith(self._cfg_dir))
        self.assertTrue(os.path.isfile(settings_path))
        self.assertTrue(mcp_path.startswith(self._cfg_dir))
        self.assertTrue(os.path.isfile(mcp_path))

    def test_does_not_write_into_launch_cwd(self):
        from teaparty.runners.launcher import compose_launch_config
        claude_dir = os.path.join(self._teaparty_repo, '.claude')
        # Snapshot of the real repo before composing
        before = _snapshot(self._teaparty_repo)
        compose_launch_config(
            config_dir=self._cfg_dir,
            agent_name='office-manager',
            scope='management',
            teaparty_home=self._tp,
            mcp_port=9000,
            session_id='sess-A',
        )
        after = _snapshot(self._teaparty_repo)
        self.assertEqual(before, after,
                         'compose_launch_config must not mutate the teaparty repo')
        self.assertFalse(os.path.isdir(os.path.join(claude_dir, 'agents')),
                         '.claude/agents/ must not be created in the real repo')
        self.assertFalse(os.path.isfile(os.path.join(self._teaparty_repo, '.mcp.json')),
                         '.mcp.json must not be written in the real repo')

    def test_returns_agents_json_for_inline_injection(self):
        from teaparty.runners.launcher import compose_launch_config
        out = compose_launch_config(
            config_dir=self._cfg_dir,
            agent_name='office-manager',
            scope='management',
            teaparty_home=self._tp,
            mcp_port=0,
        )
        agents_json = out['agents_json']
        self.assertTrue(agents_json)
        parsed = json.loads(agents_json)
        self.assertIn('office-manager', parsed)
        self.assertIn('prompt', parsed['office-manager'])
        self.assertIn('You are office-manager', parsed['office-manager']['prompt'])

    def test_parallel_qualifiers_do_not_conflict(self):
        from teaparty.runners.launcher import compose_launch_config
        cfg_a = os.path.join(self._tmpdir, 'sess-A')
        cfg_b = os.path.join(self._tmpdir, 'sess-B')
        out_a = compose_launch_config(
            config_dir=cfg_a, agent_name='office-manager',
            scope='management', teaparty_home=self._tp,
            mcp_port=9000, session_id='A',
        )
        out_b = compose_launch_config(
            config_dir=cfg_b, agent_name='office-manager',
            scope='management', teaparty_home=self._tp,
            mcp_port=9000, session_id='B',
        )
        self.assertNotEqual(out_a['settings_path'], out_b['settings_path'])
        self.assertNotEqual(out_a['mcp_path'], out_b['mcp_path'])
        # The two MCP URLs must have distinct session-scoped paths.
        with open(out_a['mcp_path']) as f:
            url_a = json.load(f)['mcpServers']['teaparty-config']['url']
        with open(out_b['mcp_path']) as f:
            url_b = json.load(f)['mcpServers']['teaparty-config']['url']
        self.assertIn('/A', url_a)
        self.assertIn('/B', url_b)
        self.assertNotEqual(url_a, url_b)


class TestChatLaunchDoesNotUseWorktree(unittest.TestCase):
    """`launch(tier='chat', ...)` must not call git worktree add."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tp, self._teaparty_repo, _ = _make_env(self._tmpdir)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_launch_chat_skips_worktree_subprocess(self):
        """Chat tier must not shell out to ``git worktree add``."""
        from teaparty.runners.launcher import launch

        original_run = subprocess.run
        seen_worktree_add = []

        def check_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if isinstance(cmd, list) and len(cmd) >= 3:
                if cmd[:3] == ['git', 'worktree', 'add']:
                    seen_worktree_add.append(cmd)
            return original_run(*args, **kwargs)

        async def stub_caller(**kwargs):
            from teaparty.runners.claude import ClaudeResult
            return ClaudeResult(exit_code=0, session_id='s-1')

        config_dir = os.path.join(self._tmpdir, 'sess-chat')
        with patch('subprocess.run', side_effect=check_run):
            asyncio.run(launch(
                agent_name='office-manager',
                message='hi',
                scope='management',
                teaparty_home=self._tp,
                tier='chat',
                launch_cwd=self._teaparty_repo,
                config_dir=config_dir,
                session_id='sess-chat',
                mcp_port=9000,
                llm_caller=stub_caller,
            ))
        self.assertEqual(seen_worktree_add, [],
                         'Chat-tier launch must not invoke git worktree add')

    def test_launch_chat_passes_real_cwd_to_caller(self):
        """The LLM caller must receive cwd = launch_cwd (the real repo)."""
        from teaparty.runners.launcher import launch

        captured = {}

        async def stub_caller(**kwargs):
            captured.update(kwargs)
            from teaparty.runners.claude import ClaudeResult
            return ClaudeResult(exit_code=0, session_id='s-1')

        config_dir = os.path.join(self._tmpdir, 'sess-chat')
        asyncio.run(launch(
            agent_name='office-manager',
            message='hi',
            scope='management',
            teaparty_home=self._tp,
            tier='chat',
            launch_cwd=self._teaparty_repo,
            config_dir=config_dir,
            session_id='sess-chat',
            mcp_port=9000,
            llm_caller=stub_caller,
        ))
        self.assertEqual(
            os.path.realpath(captured['cwd']),
            os.path.realpath(self._teaparty_repo),
        )
        self.assertTrue(captured.get('strict_mcp_config'))
        self.assertTrue(captured.get('settings_path'))
        self.assertTrue(captured.get('mcp_config_path'))
        # Settings path is inside the session dir, NOT inside the cwd.
        self.assertIn(config_dir, captured['settings_path'])
        self.assertNotIn(self._teaparty_repo, captured['settings_path'])

    def test_launch_chat_does_not_mutate_launch_cwd(self):
        """The teaparty repo's `.claude/` and `.mcp.json` must be untouched."""
        from teaparty.runners.launcher import launch

        async def stub_caller(**kwargs):
            from teaparty.runners.claude import ClaudeResult
            return ClaudeResult(exit_code=0, session_id='s-1')

        before = _snapshot(self._teaparty_repo)
        config_dir = os.path.join(self._tmpdir, 'sess-chat')
        asyncio.run(launch(
            agent_name='office-manager',
            message='hi',
            scope='management',
            teaparty_home=self._tp,
            tier='chat',
            launch_cwd=self._teaparty_repo,
            config_dir=config_dir,
            session_id='sess-chat',
            mcp_port=9000,
            llm_caller=stub_caller,
        ))
        after = _snapshot(self._teaparty_repo)
        self.assertEqual(before, after,
                         'Chat launch must not mutate the real repo')
        self.assertFalse(
            os.path.isfile(os.path.join(self._teaparty_repo, '.mcp.json')),
            '.mcp.json must not appear in the real repo',
        )


def _snapshot(path: str) -> dict[str, int]:
    """Snapshot every file under *path* except .git and .teaparty/.

    .teaparty/ is the TeaParty-managed area (config + session dirs +
    metrics.db). The prohibition is on mutating the real repo's working
    tree — .claude/, .mcp.json, CLAUDE.md, source files — not on
    TeaParty's own state under .teaparty/.
    """
    snap: dict[str, int] = {}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ('.git', '.teaparty')]
        for name in files:
            fp = os.path.join(root, name)
            try:
                snap[fp] = int(os.stat(fp).st_mtime_ns)
            except FileNotFoundError:
                pass
    return snap


if __name__ == '__main__':
    unittest.main()
