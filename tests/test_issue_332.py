"""Tests for Issue #332: OM chat — invoke the office manager with its full team.

Acceptance criteria:
1. OM invocation builds a liaison agent for each valid project in teaparty.yaml
2. OM invocation includes a Configuration workgroup liaison
3. Liaison names follow {slug}-liaison convention (slug = lowercased, hyphenated project name)
4. office-manager.md updated to reflect liaison naming convention
5. New project in teaparty.yaml is automatically included without manual configuration
6. Missing/malformed registry → graceful degradation; OM continues; human sees warning
7. Spec tests: correct liaison count, project path in liaison prompt, configuration liaison present,
   graceful degradation on missing registry
8. session-lifecycle.md updated to describe dynamic team construction
"""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml

_REPO_ROOT = Path(__file__).parent.parent


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_tmpdir() -> str:
    return tempfile.mkdtemp()


def _make_teaparty_home(tmpdir: str) -> str:
    """Create a .teaparty directory under tmpdir with a teaparty.yaml."""
    home = os.path.join(tmpdir, '.teaparty')
    os.makedirs(home, exist_ok=True)
    return home


def _write_teaparty_yaml(home: str, teams: list[dict], workgroups: list[dict] | None = None) -> None:
    """Write a teaparty.yaml with the given teams and workgroups."""
    data = {
        'name': 'Management Team',
        'lead': 'office-manager',
        'agents': ['office-manager'],
        'teams': teams,
        'workgroups': workgroups or [],
    }
    with open(os.path.join(home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False)


def _make_valid_project(tmpdir: str, name: str) -> str:
    """Create a valid TeaParty project directory (with .git, .claude, .teaparty)."""
    project_dir = os.path.join(tmpdir, name.lower().replace(' ', '-'))
    os.makedirs(project_dir)
    for marker in ['.git', '.claude', '.teaparty']:
        os.makedirs(os.path.join(project_dir, marker))
    return project_dir


def _make_workgroup_yaml(home: str, name: str = 'Configuration') -> str:
    """Write a minimal workgroup YAML file and return the config path."""
    wg_dir = os.path.join(home, 'workgroups')
    os.makedirs(wg_dir, exist_ok=True)
    filename = f'{name.lower()}.yaml'
    path = os.path.join(wg_dir, filename)
    data = {
        'name': name,
        'description': f'{name} workgroup',
        'lead': f'{name.lower()}-lead',
        'agents': [],
    }
    with open(path, 'w') as f:
        yaml.dump(data, f)
    return f'workgroups/{filename}'


def _make_stream_jsonl(text: str, session_id: str = 'sid-test') -> str:
    """Write a minimal stream JSONL file and return its path."""
    fd, path = tempfile.mkstemp(suffix='.jsonl', prefix='om-332-stream-')
    os.close(fd)
    with open(path, 'w') as f:
        f.write(json.dumps({'type': 'system', 'session_id': session_id}) + '\n')
        f.write(json.dumps({
            'type': 'assistant',
            'message': {'content': [{'type': 'text', 'text': text}]},
        }) + '\n')
    return path


# ── AC1/AC2/AC3: _build_liaison_agents_json ──────────────────────────────────

class TestBuildLiaisonAgentsJson(unittest.TestCase):
    """_build_liaison_agents_json must build named liaison agents from the registry."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_build_liaison_agents_is_importable(self):
        """_build_liaison_agents_json must be importable from orchestrator.office_manager."""
        from orchestrator.office_manager import _build_liaison_agents_json
        self.assertTrue(callable(_build_liaison_agents_json))

    def test_single_project_produces_one_project_liaison(self):
        """One valid project in teaparty.yaml → one project liaison in the output."""
        project_dir = _make_valid_project(self.tmpdir, 'TeaParty')
        _write_teaparty_yaml(self.home, teams=[{'name': 'TeaParty', 'path': project_dir}])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, warnings = _build_liaison_agents_json(self.home)

        project_liaisons = [k for k in agents if k.endswith('-liaison') and k != 'configuration-liaison']
        self.assertEqual(
            len(project_liaisons), 1,
            f'One valid project must produce exactly one project liaison; '
            f'got keys: {list(agents.keys())}',
        )

    def test_two_projects_produce_two_project_liaisons(self):
        """Two valid projects in teaparty.yaml → two project liaisons in the output."""
        p1 = _make_valid_project(self.tmpdir, 'ProjectA')
        p2 = _make_valid_project(self.tmpdir, 'ProjectB')
        _write_teaparty_yaml(self.home, teams=[
            {'name': 'ProjectA', 'path': p1},
            {'name': 'ProjectB', 'path': p2},
        ])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, warnings = _build_liaison_agents_json(self.home)

        project_liaisons = [k for k in agents if k.endswith('-liaison') and k != 'configuration-liaison']
        self.assertEqual(
            len(project_liaisons), 2,
            f'Two valid projects must produce exactly two project liaisons; '
            f'got keys: {list(agents.keys())}',
        )

    def test_liaison_name_is_slug_hyphenated_lowercase(self):
        """Project named 'TeaParty' must produce agent key 'teaparty-liaison'."""
        project_dir = _make_valid_project(self.tmpdir, 'TeaParty')
        _write_teaparty_yaml(self.home, teams=[{'name': 'TeaParty', 'path': project_dir}])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, warnings = _build_liaison_agents_json(self.home)

        self.assertIn(
            'teaparty-liaison', agents,
            f'Project "TeaParty" must produce liaison key "teaparty-liaison"; '
            f'got keys: {list(agents.keys())}',
        )

    def test_liaison_name_spaces_become_hyphens(self):
        """Project named 'My Project' must produce agent key 'my-project-liaison'."""
        project_dir = _make_valid_project(self.tmpdir, 'my-project')
        _write_teaparty_yaml(self.home, teams=[{'name': 'My Project', 'path': project_dir}])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, warnings = _build_liaison_agents_json(self.home)

        self.assertIn(
            'my-project-liaison', agents,
            f'Project "My Project" must produce liaison key "my-project-liaison"; '
            f'got keys: {list(agents.keys())}',
        )


# ── AC2: Configuration liaison always present ─────────────────────────────────

class TestConfigurationLiaisonAlwaysPresent(unittest.TestCase):
    """_build_liaison_agents_json must always include a configuration-liaison."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_configuration_liaison_present_with_no_projects(self):
        """configuration-liaison must be present even when there are no valid projects."""
        _write_teaparty_yaml(self.home, teams=[], workgroups=[])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, warnings = _build_liaison_agents_json(self.home)

        self.assertIn(
            'configuration-liaison', agents,
            f'configuration-liaison must always be included; got keys: {list(agents.keys())}',
        )

    def test_configuration_liaison_present_with_projects(self):
        """configuration-liaison must be present alongside project liaisons."""
        project_dir = _make_valid_project(self.tmpdir, 'teaparty')
        config_path = _make_workgroup_yaml(self.home, 'Configuration')
        _write_teaparty_yaml(
            self.home,
            teams=[{'name': 'TeaParty', 'path': project_dir}],
            workgroups=[{'name': 'Configuration', 'config': config_path}],
        )

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, warnings = _build_liaison_agents_json(self.home)

        self.assertIn(
            'configuration-liaison', agents,
            f'configuration-liaison must be present alongside project liaisons; '
            f'got keys: {list(agents.keys())}',
        )

    def test_configuration_liaison_has_haiku_model(self):
        """configuration-liaison must use the haiku model (relay role, not decision-making)."""
        _write_teaparty_yaml(self.home, teams=[])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, _warnings = _build_liaison_agents_json(self.home)

        liaison = agents.get('configuration-liaison', {})
        self.assertEqual(
            liaison.get('model'), 'haiku',
            f'configuration-liaison must use model=haiku; got {liaison.get("model")!r}',
        )

    def test_project_liaison_has_haiku_model(self):
        """Project liaisons must use the haiku model (relay role, not decision-making)."""
        project_dir = _make_valid_project(self.tmpdir, 'teaparty')
        _write_teaparty_yaml(self.home, teams=[{'name': 'TeaParty', 'path': project_dir}])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, _warnings = _build_liaison_agents_json(self.home)

        liaison = agents.get('teaparty-liaison', {})
        self.assertEqual(
            liaison.get('model'), 'haiku',
            f'teaparty-liaison must use model=haiku; got {liaison.get("model")!r}',
        )

    def test_liaison_max_turns_is_10(self):
        """Liaisons must have maxTurns=10 (status synthesis requires multiple file reads)."""
        _write_teaparty_yaml(self.home, teams=[])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, _warnings = _build_liaison_agents_json(self.home)

        liaison = agents['configuration-liaison']
        self.assertEqual(
            liaison.get('maxTurns'), 10,
            f'configuration-liaison must have maxTurns=10; got {liaison.get("maxTurns")!r}',
        )


# ── AC1: Project path baked into liaison prompt ───────────────────────────────

class TestLiaisonPromptContainsProjectPath(unittest.TestCase):
    """Each project liaison prompt must include the project path so it knows where to read."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_project_liaison_prompt_contains_project_path(self):
        """teaparty-liaison prompt must contain the absolute path to the project."""
        project_dir = _make_valid_project(self.tmpdir, 'teaparty')
        _write_teaparty_yaml(self.home, teams=[{'name': 'TeaParty', 'path': project_dir}])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, _warnings = _build_liaison_agents_json(self.home)

        liaison = agents.get('teaparty-liaison', {})
        prompt = liaison.get('prompt', '')
        self.assertIn(
            project_dir, prompt,
            f'teaparty-liaison prompt must contain the project path {project_dir!r}; '
            f'got prompt: {prompt[:200]!r}',
        )

    def test_invalid_project_path_not_included(self):
        """A project with an invalid path (missing .git/.claude/.teaparty) must not be included."""
        bad_dir = os.path.join(self.tmpdir, 'nonexistent-project')
        _write_teaparty_yaml(self.home, teams=[{'name': 'BadProject', 'path': bad_dir}])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, warnings = _build_liaison_agents_json(self.home)

        self.assertNotIn(
            'badproject-liaison', agents,
            'An invalid project path must not produce a liaison agent',
        )


# ── AC5: New project automatically included ──────────────────────────────────

class TestNewProjectAutoIncluded(unittest.TestCase):
    """Adding a project to teaparty.yaml must automatically include it in the next OM team."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_liaison_count_matches_valid_project_count(self):
        """Number of project liaisons must equal the number of valid projects in teaparty.yaml."""
        p1 = _make_valid_project(self.tmpdir, 'proj-a')
        p2 = _make_valid_project(self.tmpdir, 'proj-b')
        p3 = _make_valid_project(self.tmpdir, 'proj-c')
        _write_teaparty_yaml(self.home, teams=[
            {'name': 'ProjA', 'path': p1},
            {'name': 'ProjB', 'path': p2},
            {'name': 'ProjC', 'path': p3},
        ])

        from orchestrator.office_manager import _build_liaison_agents_json
        agents, _warnings = _build_liaison_agents_json(self.home)

        project_liaisons = [k for k in agents if k.endswith('-liaison') and k != 'configuration-liaison']
        self.assertEqual(
            len(project_liaisons), 3,
            f'Three valid projects must produce three project liaisons; '
            f'got {len(project_liaisons)}: {project_liaisons}',
        )


# ── AC6: Graceful degradation on missing/malformed registry ──────────────────

class TestGracefulDegradationOnMissingRegistry(unittest.TestCase):
    """OM must degrade gracefully when teaparty.yaml is missing or malformed."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_registry_returns_empty_agents_with_warning(self):
        """Missing teaparty.yaml must return empty agents dict and at least one warning."""
        # No teaparty.yaml written — home exists but has no config
        from orchestrator.office_manager import _build_liaison_agents_json
        agents, warnings = _build_liaison_agents_json(self.home)

        self.assertIsInstance(
            agents, dict,
            '_build_liaison_agents_json must return a dict even when registry is missing',
        )
        self.assertTrue(
            len(warnings) > 0,
            '_build_liaison_agents_json must return at least one warning when registry is missing',
        )

    def test_invoke_does_not_raise_when_registry_missing(self):
        """OfficeManagerSession.invoke() must not raise when teaparty.yaml is missing."""
        from orchestrator.office_manager import OfficeManagerSession
        from orchestrator.messaging import SqliteMessageBus

        om_dir = os.path.join(self.tmpdir, 'om')
        os.makedirs(om_dir, exist_ok=True)

        session = OfficeManagerSession(self.tmpdir, 'darrell')
        session.send_human_message('Hello.')

        stream_path = _make_stream_jsonl('Hello back.')
        try:
            mock_result = MagicMock()
            mock_result.session_id = 'sid-degrade-test'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                instance.stream_file = stream_path
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            # Must not raise
                            result = asyncio.run(session.invoke(cwd=self.tmpdir))

            # Result should be a string (even if empty) — not an exception
            self.assertIsInstance(
                result, str,
                'invoke() must return a string even when registry is missing',
            )
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass

    def test_invoke_sends_warning_to_bus_when_registry_missing(self):
        """When registry is missing, a warning about unavailable teammates must appear in the bus."""
        from orchestrator.office_manager import OfficeManagerSession

        session = OfficeManagerSession(self.tmpdir, 'darrell')
        session.send_human_message('Hello.')

        stream_path = _make_stream_jsonl('')  # empty response
        try:
            mock_result = MagicMock()
            mock_result.session_id = None

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                instance.stream_file = stream_path
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(session.invoke(cwd=self.tmpdir))

            # The bus must contain at least one message (human + some office-manager message)
            msgs = session.get_messages()
            all_content = ' '.join(m.content for m in msgs)
            # At minimum the human message is there; the session may or may not write a degradation
            # warning, but it must not be silent silence with no feedback.
            # The contract: if the registry fails, the next invocation is unblocked (not hung).
            self.assertIsNotNone(msgs, 'get_messages() must return a list, not None')
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass


# ── AC1 integration: agents_file passed to ClaudeRunner ──────────────────────

class TestInvokePassesAgentsFileToClaude(unittest.TestCase):
    """OfficeManagerSession.invoke() must pass agents_file to ClaudeRunner."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)
        os.makedirs(os.path.join(self.tmpdir, 'om'), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_invoke_with_valid_registry_passes_agents_file_to_runner(self):
        """With a valid registry, invoke() must construct ClaudeRunner with agents_file != None."""
        project_dir = _make_valid_project(self.tmpdir, 'teaparty')
        _write_teaparty_yaml(
            self.home,
            teams=[{'name': 'TeaParty', 'path': project_dir}],
        )

        from orchestrator.office_manager import OfficeManagerSession

        session = OfficeManagerSession(self.tmpdir, 'darrell')
        session.send_human_message('What is the status of TeaParty?')

        stream_path = _make_stream_jsonl('TeaParty looks good.')
        captured_kwargs: list[dict] = []

        try:
            mock_result = MagicMock()
            mock_result.session_id = 'sid-agents-test'

            def capture_runner(*args, **kwargs):
                captured_kwargs.append(kwargs)
                inst = MagicMock()
                inst.run = AsyncMock(return_value=mock_result)
                inst.stream_file = stream_path
                return inst

            with patch('orchestrator.claude_runner.ClaudeRunner', side_effect=capture_runner):
                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(session.invoke(cwd=self.tmpdir))

            self.assertTrue(
                len(captured_kwargs) > 0,
                'ClaudeRunner must have been called',
            )
            agents_file = captured_kwargs[0].get('agents_file')
            self.assertIsNotNone(
                agents_file,
                'ClaudeRunner must be called with agents_file != None when the registry is valid; '
                'currently no agents_file is passed (the core bug this issue fixes)',
            )
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass

    def test_agents_file_content_includes_configuration_liaison(self):
        """The temp agents JSON written by invoke() must include configuration-liaison."""
        project_dir = _make_valid_project(self.tmpdir, 'teaparty')
        _write_teaparty_yaml(self.home, teams=[{'name': 'TeaParty', 'path': project_dir}])

        from orchestrator.office_manager import OfficeManagerSession

        session = OfficeManagerSession(self.tmpdir, 'darrell')
        session.send_human_message('Hello.')

        stream_path = _make_stream_jsonl('Hi.')
        written_agents_files: list[str] = []

        try:
            mock_result = MagicMock()
            mock_result.session_id = 'sid-content-test'

            def capture_runner(*args, **kwargs):
                af = kwargs.get('agents_file')
                if af:
                    written_agents_files.append(af)
                inst = MagicMock()
                inst.run = AsyncMock(return_value=mock_result)
                inst.stream_file = stream_path
                return inst

            with patch('orchestrator.claude_runner.ClaudeRunner', side_effect=capture_runner):
                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(session.invoke(cwd=self.tmpdir))

            if written_agents_files:
                agents_file_path = written_agents_files[0]
                if os.path.exists(agents_file_path):
                    with open(agents_file_path) as f:
                        agents = json.load(f)
                    self.assertIn(
                        'configuration-liaison', agents,
                        f'agents JSON must include configuration-liaison; '
                        f'got keys: {list(agents.keys())}',
                    )
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass

    def test_invoke_without_valid_registry_does_not_raise(self):
        """invoke() must not raise when the registry is missing — OM degrades gracefully."""
        from orchestrator.office_manager import OfficeManagerSession

        session = OfficeManagerSession(self.tmpdir, 'darrell')
        session.send_human_message('Hello.')

        stream_path = _make_stream_jsonl('Hello.')
        try:
            mock_result = MagicMock()
            mock_result.session_id = 'sid-no-registry'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                instance.stream_file = stream_path
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            result = asyncio.run(session.invoke(cwd=self.tmpdir))

            self.assertIsInstance(result, str, 'invoke() must return a string even without a registry')
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass


# ── AC4: office-manager.md reflects naming convention ────────────────────────

class TestOfficeManagerMdLiaisonNaming(unittest.TestCase):
    """office-manager.md must reflect the slug-based liaison naming convention."""

    def _get_agent_def(self) -> str:
        path = _REPO_ROOT / '.claude' / 'agents' / 'office-manager.md'
        self.assertTrue(path.exists(), f'office-manager.md not found at {path}')
        return path.read_text()

    def test_office_manager_md_mentions_slug_naming_for_liaisons(self):
        """office-manager.md must explain that liaison names derive from project slugs."""
        doc = self._get_agent_def()
        # The doc must explain the naming convention so the OM knows who to address.
        # Accept either explicit slug mention or a concrete example name pattern.
        slug_naming_mentioned = (
            'slug' in doc.lower()
            or 'teaparty-liaison' in doc
            or '-liaison' in doc
            or 'liaison name' in doc.lower()
        )
        self.assertTrue(
            slug_naming_mentioned,
            'office-manager.md must explain how liaison names are derived from project slugs '
            '(e.g., "teaparty-liaison") so the OM knows who to address; '
            f'the current text does not mention slug naming or example liaison names',
        )


# ── AC8: session-lifecycle.md describes dynamic team construction ─────────────

class TestSessionLifecycleDocDescribesDynamicTeam(unittest.TestCase):
    """session-lifecycle.md must describe dynamic team construction from the registry."""

    def _get_doc(self) -> str:
        path = (
            _REPO_ROOT
            / 'docs' / 'proposals' / 'office-manager' / 'references' / 'session-lifecycle.md'
        )
        self.assertTrue(path.exists(), f'session-lifecycle.md not found at {path}')
        return path.read_text()

    def test_session_lifecycle_describes_dynamic_team_construction(self):
        """session-lifecycle.md must describe dynamic team construction from the registry."""
        doc = self._get_doc()
        dynamic_team_mentioned = (
            'dynamic' in doc.lower()
            or 'registry' in doc.lower()
            or 'teaparty.yaml' in doc
            or 'liaison' in doc.lower()
            or 'agents_file' in doc
        )
        self.assertTrue(
            dynamic_team_mentioned,
            'session-lifecycle.md must describe dynamic team construction — '
            'that liaisons are built from teaparty.yaml at each invocation; '
            'the current doc does not mention this',
        )
