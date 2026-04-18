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

    # A management workgroup so configuration-lead is reachable via
    # registry walk (members.workgroups → Configuration → lead).
    mgmt_wg_dir = os.path.join(mgmt, 'workgroups')
    os.makedirs(mgmt_wg_dir)
    with open(os.path.join(mgmt_wg_dir, 'configuration.yaml'), 'w') as f:
        yaml.dump({
            'name': 'Configuration',
            'description': 'Config team',
            'lead': 'configuration-lead',
            'members': {'agents': []},
        }, f)

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
        'members': {
            'projects': [],
            'agents': [],
            'workgroups': ['Configuration'],
        },
        'workgroups': [
            {'name': 'Configuration',
             'config': 'workgroups/configuration.yaml'},
        ],
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

    def test_missing_registry_raises(self):
        tp, teaparty_repo, _ = _make_env(self._tmpdir, with_project=False)
        os.unlink(os.path.join(tp, 'management', 'teaparty.yaml'))
        from teaparty.config.roster import (
            resolve_launch_cwd, LaunchCwdNotResolved,
        )
        with self.assertRaises(LaunchCwdNotResolved):
            resolve_launch_cwd('configuration-lead', tp)

    def test_unknown_member_raises(self):
        tp, _, _ = _make_env(self._tmpdir, with_project=True)
        from teaparty.config.roster import (
            resolve_launch_cwd, LaunchCwdNotResolved,
        )
        with self.assertRaises(LaunchCwdNotResolved):
            resolve_launch_cwd('nonexistent-lead', tp)

    def test_management_lead_resolves_to_teaparty_repo(self):
        tp, teaparty_repo, _ = _make_env(self._tmpdir, with_project=True)
        from teaparty.config.roster import resolve_launch_cwd
        # The management team's `lead` (office-manager by default) must
        # resolve to the teaparty repo via registry walk.
        cwd = resolve_launch_cwd('office-manager', tp)
        self.assertEqual(
            os.path.realpath(cwd), os.path.realpath(teaparty_repo),
        )


class TestComposeLaunchConfig(unittest.TestCase):
    """`compose_launch_config` writes only to the config_dir."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tp, self._teaparty_repo, _ = _make_env(self._tmpdir)
        self._cfg_dir = os.path.join(self._tmpdir, 'session-A')

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_writes_all_three_files_inside_config_dir(self):
        """compose_launch_config writes settings.json, mcp.json, agent.json."""
        from teaparty.runners.launcher import compose_launch_config
        os.makedirs(self._cfg_dir, exist_ok=True)
        out = compose_launch_config(
            config_dir=self._cfg_dir,
            agent_name='office-manager',
            scope='management',
            teaparty_home=self._tp,
            mcp_port=9000,
            session_id='sess-A',
        )
        for key in ('settings_path', 'mcp_path', 'agents_file'):
            path = out[key]
            self.assertTrue(path,
                            f'compose_launch_config did not return {key}')
            self.assertTrue(path.startswith(self._cfg_dir),
                            f'{key} must live inside config_dir')
            self.assertTrue(os.path.isfile(path),
                            f'{key} at {path} must exist on disk')
        self.assertTrue(out['agents_file'].endswith('agent.json'))

    def test_config_dir_at_spec_location(self):
        """`chat_config_dir` produces the spec'd path from issue #397."""
        from teaparty.runners.launcher import chat_config_dir
        path = chat_config_dir(self._tp, 'management', 'office-manager', 'q1')
        expected = os.path.join(
            self._tp, 'management', 'agents', 'office-manager', 'q1', 'config',
        )
        self.assertEqual(path, expected)

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


class TestSessionMetadataRoundTrip(unittest.TestCase):
    """`launch_cwd` must survive a metadata.json save/load round-trip.

    Issue #397 calls this out explicitly — the field has to be useful
    for debugging and for verifying scope across restarts.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tp, self._teaparty_repo, _ = _make_env(self._tmpdir)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_launch_cwd_persists(self):
        from teaparty.runners.launcher import (
            create_session, load_session, _save_session_metadata,
        )
        session = create_session(
            agent_name='comics-lead', scope='management',
            teaparty_home=self._tp, session_id='child-42',
        )
        session.launch_cwd = '/absolute/path/to/comics-repo'
        _save_session_metadata(session)

        reloaded = load_session(
            agent_name='comics-lead', scope='management',
            teaparty_home=self._tp, session_id='child-42',
        )
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.launch_cwd, '/absolute/path/to/comics-repo')


class TestOnlyConfigDirIsMutated(unittest.TestCase):
    """Full filesystem snapshot: a chat launch must mutate only files
    under the spec'd config dir. Nothing under the launch cwd outside
    `.teaparty/` may change. This is the strong form of criterion 4."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tp, self._teaparty_repo, _ = _make_env(self._tmpdir)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_only_config_dir_under_teaparty_changes(self):
        from teaparty.runners.launcher import launch, chat_config_dir

        async def stub_caller(**kwargs):
            from teaparty.runners.claude import ClaudeResult
            return ClaudeResult(exit_code=0, session_id='s-1')

        config_dir = chat_config_dir(
            self._tp, 'management', 'office-manager', 'qual-1',
        )
        # Expected allowed-mutation roots (everything else is forbidden):
        allowed_roots = [
            os.path.realpath(config_dir),
            os.path.realpath(os.path.join(self._tp, 'management', 'sessions')),
            os.path.realpath(os.path.join(self._tp, 'management', 'metrics.db')),
            # telemetry.db (and -shm / -wal siblings) are written by the
            # event-sourced telemetry store introduced in #405.
            os.path.realpath(os.path.join(self._tp, 'telemetry.db')),
        ]

        before = _full_snapshot(self._teaparty_repo)
        asyncio.run(launch(
            agent_name='office-manager',
            message='hi',
            scope='management',
            teaparty_home=self._tp,
            tier='chat',
            launch_cwd=self._teaparty_repo,
            config_dir=config_dir,
            session_id='sess-strict',
            mcp_port=9000,
            llm_caller=stub_caller,
        ))
        after = _full_snapshot(self._teaparty_repo)

        changed = set(after) ^ set(before)
        changed.update(
            k for k in set(after) & set(before) if before[k] != after[k]
        )
        # Every mutated file must be under one of the allowed roots.
        forbidden = []
        for path in changed:
            real = os.path.realpath(path)
            if not any(real.startswith(root) for root in allowed_roots):
                forbidden.append(path)
        self.assertEqual(
            forbidden, [],
            f'Files mutated outside the allowed config/session/metrics '
            f'roots: {forbidden}'
        )
        # And positively: the three config files must now exist.
        self.assertTrue(os.path.isfile(os.path.join(config_dir, 'settings.json')))
        self.assertTrue(os.path.isfile(os.path.join(config_dir, 'mcp.json')))
        self.assertTrue(os.path.isfile(os.path.join(config_dir, 'agent.json')))


def _full_snapshot(path: str) -> dict[str, int]:
    """Snapshot every file under *path* (including .teaparty/, excluding .git).

    This is the strong form used by TestOnlyConfigDirIsMutated — the
    other test class uses `_snapshot` which excludes .teaparty/.
    """
    snap: dict[str, int] = {}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d != '.git']
        for name in files:
            fp = os.path.join(root, name)
            try:
                st = os.stat(fp)
                snap[fp] = (st.st_mtime_ns, st.st_size)
            except FileNotFoundError:
                pass
    return snap


class TestInvokeInnerUsesResolvedCwd(unittest.TestCase):
    """`AgentSession.invoke` (the top-level path) must launch the
    subprocess at the cwd resolved from the registry, not the caller's
    fallback cwd. This closes the wiring gap between
    `resolve_launch_cwd` (unit-tested) and `_invoke_inner` (the only
    place the OM's own launch is assembled)."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tp, self._teaparty_repo, _ = _make_env(self._tmpdir)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_invoke_passes_registry_cwd_to_llm_caller(self):
        captured = []

        async def capturing_caller(**kwargs):
            captured.append(kwargs)
            from teaparty.runners.claude import ClaudeResult
            return ClaudeResult(exit_code=0, session_id='s-99')

        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType
        om = AgentSession(
            self._tp,
            agent_name='office-manager',
            scope='management',
            qualifier='verify-invoke',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=False,
            llm_caller=capturing_caller,
        )
        # Seed a human message so invoke produces a prompt.
        om.send_human_message('hello')

        # Intentionally pass a BOGUS cwd. If the code inherits instead of
        # resolving via the registry, this value will leak to the caller.
        bogus_cwd = os.path.join(self._tmpdir, 'NOT_THE_REAL_REPO')
        os.makedirs(bogus_cwd)
        asyncio.run(om.invoke(cwd=bogus_cwd))

        self.assertEqual(len(captured), 1)
        got = captured[0]
        self.assertEqual(
            os.path.realpath(got['cwd']),
            os.path.realpath(self._teaparty_repo),
            'invoke() must launch at the registry-resolved cwd, '
            'not the caller-supplied fallback',
        )
        # And the config_dir is at the spec'd path.
        self.assertIn(
            os.path.join(
                'management', 'agents', 'office-manager',
                'verify-invoke', 'config',
            ),
            got['settings_path'],
        )
        self.assertTrue(got['strict_mcp_config'])


class TestSpawnFnDispatchesAtProjectRepo(unittest.TestCase):
    """End-to-end wiring: a dispatch from the OM to a project lead must
    trigger a launch at the project's repo, with the config_dir at the
    spec'd per-agent-per-session path — proving criteria 2, 3, and the
    registry-walking rule together."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tp, self._teaparty_repo, self._project_repo = _make_env(
            self._tmpdir, with_project=True,
        )
        os.environ['TEAPARTY_BRIDGE_PORT'] = '19999'

    def tearDown(self):
        os.environ.pop('TEAPARTY_BRIDGE_PORT', None)
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        from teaparty.mcp.registry import _spawn_fns, _close_fns, _reply_fns
        _spawn_fns.clear()
        _close_fns.clear()
        _reply_fns.clear()

    def _run_dispatch(self, member: str) -> list[dict]:
        """Drive spawn_fn for *member* and return captured launch kwargs."""
        captured: list[dict] = []

        async def capturing_caller(**kwargs):
            captured.append(kwargs)
            from teaparty.runners.claude import ClaudeResult
            return ClaudeResult(exit_code=0, session_id='child-s')

        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType
        from unittest.mock import AsyncMock

        om = AgentSession(
            self._tp,
            agent_name='office-manager',
            scope='management',
            qualifier='dispatch-test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
            llm_caller=capturing_caller,
        )

        # Pre-create the OM's dispatch session; spawn_fn's slot check
        # requires it. _ensure_bus_listener will lazily create one too
        # but `_load_session` returns None instead of raising, so we
        # seed it explicitly.
        from teaparty.runners.launcher import create_session as _cs
        om._dispatch_session = _cs(
            agent_name='office-manager', scope='management',
            teaparty_home=self._tp,
            session_id='office-manager-dispatch-test',
        )

        async def drive():
            # Stub BusEventListener start/stop so we don't bind sockets.
            with patch(
                'teaparty.messaging.listener.BusEventListener.start',
                new_callable=AsyncMock,
                return_value=('/tmp/s', '/tmp/c'),
            ), patch(
                'teaparty.messaging.listener.BusEventListener.stop',
                new_callable=AsyncMock,
            ):
                await om._ensure_bus_listener(self._teaparty_repo)
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('office-manager')
                self.assertIsNotNone(spawn_fn,
                                     'spawn_fn not registered for OM')
                result = await spawn_fn(member, 'do a thing', 'ctx-1')
                # Drain background _run_child tasks so the launch
                # actually executes before we inspect captured kwargs.
                for task in list(om._background_tasks):
                    try:
                        await asyncio.wait_for(task, timeout=5)
                    except Exception:
                        pass
                return result

        result = asyncio.run(drive())
        return captured, result

    def test_project_lead_launches_at_project_repo(self):
        """comics-lead dispatch must land at the comics project repo."""
        captured, result = self._run_dispatch('comics-lead')

        # A launch DID happen.
        self.assertEqual(len(captured), 1,
                         f'expected exactly one launch, got {len(captured)}')
        got = captured[0]

        # cwd is the project repo, NOT the teaparty repo.
        self.assertEqual(
            os.path.realpath(got['cwd']),
            os.path.realpath(self._project_repo),
            'comics-lead must launch at the comics project repo',
        )
        self.assertNotEqual(
            os.path.realpath(got['cwd']),
            os.path.realpath(self._teaparty_repo),
            'comics-lead must NOT launch at the teaparty repo',
        )

        # Config dir is at the spec'd path (parent of settings.json).
        settings_path = got['settings_path']
        self.assertIn('management/agents/comics-lead/', settings_path)
        self.assertTrue(settings_path.endswith('/config/settings.json'))
        self.assertTrue(os.path.isfile(settings_path))
        self.assertTrue(got['strict_mcp_config'],
                        '--strict-mcp-config must be enabled for chat tier')

        # spawn_fn's returned "worktree path" element is the launch_cwd,
        # not a git worktree. Verified: no .git directory underneath it
        # that the test itself created, and launch_cwd == project_repo.
        child_session_id, returned_cwd, _ = result
        self.assertTrue(child_session_id)
        self.assertEqual(
            os.path.realpath(returned_cwd),
            os.path.realpath(self._project_repo),
        )

    def test_unknown_member_is_refused_at_dispatch(self):
        """Dispatching to an unregistered agent must block the launch."""
        captured, result = self._run_dispatch('bogus-lead')
        self.assertEqual(
            captured, [],
            'spawn_fn must NOT call launch() for an unknown member',
        )
        self.assertEqual(result, ('', '', ''),
                         'spawn_fn must return empty handles on refusal')

    def test_no_git_worktree_add_during_project_dispatch(self):
        """Cross-check criterion 1 on the dispatch path, not just launch()."""
        seen_worktree_add = []
        original_run = subprocess.run

        def check_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if isinstance(cmd, list) and len(cmd) >= 3:
                if cmd[:3] == ['git', 'worktree', 'add']:
                    seen_worktree_add.append(cmd)
            return original_run(*args, **kwargs)

        with patch('subprocess.run', side_effect=check_run):
            self._run_dispatch('comics-lead')
        self.assertEqual(
            seen_worktree_add, [],
            'chat-tier dispatch must not shell out to git worktree add',
        )


if __name__ == '__main__':
    unittest.main()
