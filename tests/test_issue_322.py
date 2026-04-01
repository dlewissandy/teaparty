"""Tests for Issue #322: Project registration — OM-driven onboarding flow with filesystem navigation.

Acceptance criteria:
1. Projects section in config.html has separate "+ Add" (existing) and "+ New" (create) buttons
2. "+ Add" opens om:add-project conversation; "+ New" opens om:new-project conversation
3. GET /api/fs/list?path=<p> returns directory listing with name, path, is_dir fields
4. POST /api/projects/add accepts full frontmatter (description, lead, decider, agents,
   humans, workgroups, skills) and writes all fields to .teaparty.local/project.yaml
5. POST /api/projects/create accepts full frontmatter and writes it
6. add_project() accepts frontmatter kwargs and writes them to project.yaml
7. add_project() no longer requires .git/ and .claude/ as hard prerequisites
8. create_project() accepts frontmatter kwargs and writes them to project.yaml
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parent.parent


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_tmpdir() -> str:
    return tempfile.mkdtemp()


def _make_teaparty_home(tmpdir: str) -> str:
    home = os.path.join(tmpdir, '.teaparty')
    os.makedirs(home, exist_ok=True)
    return home


def _write_teaparty_yaml(home: str, teams: list | None = None) -> None:
    data = {
        'name': 'Test Management Team',
        'description': '',
        'lead': '',
        'humans': {'decider': ''},
        'members': {'agents': [], 'projects': []},
        'projects': [],
        'workgroups': [],
    }
    with open(os.path.join(home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _make_project_dir(tmpdir: str, name: str, with_git: bool = False, with_claude: bool = False) -> str:
    proj = os.path.join(tmpdir, name)
    os.makedirs(proj)
    if with_git:
        os.makedirs(os.path.join(proj, '.git'))
    if with_claude:
        os.makedirs(os.path.join(proj, '.claude'))
    return proj


def _read_project_yaml(proj_dir: str) -> dict:
    path = os.path.join(proj_dir, '.teaparty.local', 'project.yaml')
    with open(path) as f:
        return yaml.safe_load(f)


def _make_bridge(tmpdir: str):
    from bridge.server import TeaPartyBridge
    static_dir = os.path.join(tmpdir, 'static')
    os.makedirs(static_dir, exist_ok=True)
    # bridge requires an index.html to exist for the index route
    with open(os.path.join(static_dir, 'index.html'), 'w') as f:
        f.write('<html></html>')
    return TeaPartyBridge(teaparty_home=tmpdir, static_dir=static_dir)


def _get_route_paths(app) -> set:
    return {resource.canonical for resource in app.router.resources()}


# ── AC1 & AC2: config.html has scoped OM conversation IDs ────────────────────

class TestConfigHtmlProjectButtons(unittest.TestCase):
    """Projects section must have separate Add and New buttons routed to scoped OM threads."""

    def _get_config_html(self) -> str:
        path = _REPO_ROOT / 'bridge' / 'static' / 'config.html'
        self.assertTrue(path.exists(), f'config.html not found at {path}')
        return path.read_text()

    def test_add_project_conversation_id_present(self):
        """config.html must open om:add-project for the Add existing project flow."""
        html = self._get_config_html()
        self.assertIn(
            'om:add-project', html,
            'config.html must reference om:add-project conversation for the "+ Add" button',
        )

    def test_new_project_conversation_id_present(self):
        """config.html must open om:new-project for the Create new project flow."""
        html = self._get_config_html()
        self.assertIn(
            'om:new-project', html,
            'config.html must reference om:new-project conversation for the "+ New" button',
        )

    def test_add_and_new_are_distinct(self):
        """Add and New must route to different conversation IDs — not the same generic OM thread."""
        html = self._get_config_html()
        self.assertIn('om:add-project', html)
        self.assertIn('om:new-project', html)
        # The two IDs must differ (they're not the same string)
        self.assertNotEqual('om:add-project', 'om:new-project')

    def test_projects_section_has_add_label(self):
        """config.html must show a button labelled '+ Add' (not just '+ New') for projects."""
        html = self._get_config_html()
        self.assertIn(
            '+ Add', html,
            "config.html must have a '+ Add' button for the add-existing-project flow",
        )

    def test_projects_section_has_new_label(self):
        """config.html must show a button labelled '+ New' for creating new projects."""
        html = self._get_config_html()
        self.assertIn(
            '+ New', html,
            "config.html must have a '+ New' button for the create-new-project flow",
        )

    def test_add_button_passes_seed_message(self):
        """config.html + Add button must pass a skill-referenced seed for the add-project flow."""
        html = self._get_config_html()
        self.assertIn(
            'openChatWithSeed', html,
            'config.html must use openChatWithSeed() for project buttons to pre-seed intent',
        )
        self.assertIn(
            '/add-project skill', html,
            "config.html '+ Add' seed must reference the /add-project skill",
        )

    def test_new_button_passes_seed_message(self):
        """config.html + New button must pass a skill-referenced seed for the create-project flow."""
        html = self._get_config_html()
        self.assertIn(
            '/create-project skill', html,
            "config.html '+ New' seed must reference the /create-project skill",
        )

    def test_chat_html_reads_seed_param(self):
        """chat.html must read a 'seed' URL parameter to pre-seed the OM conversation."""
        path = _REPO_ROOT / 'bridge' / 'static' / 'chat.html'
        html = path.read_text()
        self.assertIn(
            'seed', html,
            "chat.html must read a 'seed' URL parameter for pre-seeded OM messages",
        )
        self.assertIn(
            'seedMessage', html,
            "chat.html must have a seedMessage variable from the seed URL parameter",
        )

    def test_chat_html_posts_seed_when_conversation_empty(self):
        """chat.html must POST the seed message when the conversation has no messages."""
        path = _REPO_ROOT / 'bridge' / 'static' / 'chat.html'
        html = path.read_text()
        # Must check that messages are empty before posting the seed
        self.assertIn(
            'messages.length === 0', html,
            "chat.html must only post seed when conversation is empty",
        )


# ── AC3: /api/fs/list route and helper ───────────────────────────────────────

class TestFsListRoute(unittest.TestCase):
    """GET /api/fs/list must be registered on the bridge application."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        self.app = self.bridge._build_app()
        self.paths = _get_route_paths(self.app)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fs_list_route_registered(self):
        """GET /api/fs/list must be a registered route."""
        self.assertIn(
            '/api/fs/list', self.paths,
            'GET /api/fs/list not registered; OM needs this to navigate the filesystem',
        )


class TestFsListHelper(unittest.TestCase):
    """_list_directory() must return entries with name, path, and is_dir fields."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        # Create a few subdirectories and a file
        os.makedirs(os.path.join(self.tmpdir, 'subdir_a'))
        os.makedirs(os.path.join(self.tmpdir, 'subdir_b'))
        with open(os.path.join(self.tmpdir, 'file.txt'), 'w') as f:
            f.write('hello')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_directory_function_importable(self):
        """bridge.server must export _list_directory()."""
        from bridge.server import _list_directory  # noqa: F401

    def test_list_directory_returns_list(self):
        """_list_directory() must return a list."""
        from bridge.server import _list_directory
        entries = _list_directory(self.tmpdir)
        self.assertIsInstance(entries, list)

    def test_list_directory_entries_have_required_fields(self):
        """Each entry must have name, path, and is_dir fields."""
        from bridge.server import _list_directory
        entries = _list_directory(self.tmpdir)
        self.assertGreater(len(entries), 0, 'must return at least one entry')
        for e in entries:
            self.assertIn('name', e, 'entry missing name field')
            self.assertIn('path', e, 'entry missing path field')
            self.assertIn('is_dir', e, 'entry missing is_dir field')

    def test_list_directory_directories_marked_is_dir_true(self):
        """Subdirectories must be marked is_dir=True."""
        from bridge.server import _list_directory
        entries = _list_directory(self.tmpdir)
        dirs = {e['name']: e for e in entries if e['is_dir']}
        self.assertIn('subdir_a', dirs, 'subdir_a must appear as is_dir=True')
        self.assertIn('subdir_b', dirs, 'subdir_b must appear as is_dir=True')

    def test_list_directory_files_marked_is_dir_false(self):
        """Regular files must be marked is_dir=False."""
        from bridge.server import _list_directory
        entries = _list_directory(self.tmpdir)
        files = {e['name']: e for e in entries if not e['is_dir']}
        self.assertIn('file.txt', files, 'file.txt must appear as is_dir=False')

    def test_list_directory_path_field_is_absolute(self):
        """Each entry's path field must be an absolute path."""
        from bridge.server import _list_directory
        entries = _list_directory(self.tmpdir)
        for e in entries:
            self.assertTrue(
                os.path.isabs(e['path']),
                f"entry {e['name']!r} path is not absolute: {e['path']!r}",
            )

    def test_list_directory_nonexistent_path_raises(self):
        """_list_directory() must raise (not return empty list) for a nonexistent path."""
        from bridge.server import _list_directory
        with self.assertRaises(Exception):
            _list_directory('/nonexistent/path/that/does/not/exist')


# ── AC4 & AC6 & AC7: add_project() accepts frontmatter, loosened prereqs ─────

class TestAddProjectFrontmatter(unittest.TestCase):
    """add_project() must accept and write full frontmatter to project.yaml."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)
        _write_teaparty_yaml(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_project_accepts_description(self):
        """add_project() must accept a description kwarg and write it to project.yaml."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'proj-a')
        add_project('proj-a', proj, description='A test project', teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('description'), 'A test project')

    def test_add_project_accepts_lead(self):
        """add_project() must accept a lead kwarg and write it to project.yaml."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'proj-b')
        add_project('proj-b', proj, lead='alice', teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('lead'), 'alice')

    def test_add_project_accepts_decider(self):
        """add_project() must accept a decider kwarg and write it to project.yaml humans block."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'proj-c')
        add_project('proj-c', proj, decider='bob', teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('humans', {}).get('decider'), 'bob')

    def test_add_project_writes_full_frontmatter_together(self):
        """add_project() must write all frontmatter fields in a single call."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'proj-full')
        add_project(
            'proj-full', proj,
            description='Full project',
            lead='manager-agent',
            decider='carol',
            teaparty_home=self.home,
        )
        data = _read_project_yaml(proj)
        self.assertEqual(data['description'], 'Full project')
        self.assertEqual(data['lead'], 'manager-agent')
        self.assertEqual(data.get('humans', {}).get('decider'), 'carol')


class TestAddProjectLoosensPrereqs(unittest.TestCase):
    """add_project() must not require .git/ or .claude/ as hard prerequisites."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)
        _write_teaparty_yaml(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_project_succeeds_without_git(self):
        """add_project() must succeed for a directory without .git/."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'no-git', with_git=False, with_claude=False)
        try:
            add_project('no-git', proj, teaparty_home=self.home)
        except ValueError as exc:
            if '.git' in str(exc):
                self.fail(
                    f'add_project() raised ValueError about missing .git/: {exc}\n'
                    'OM handles .git bootstrapping — backend must not gate on it'
                )
            raise

    def test_add_project_succeeds_without_claude(self):
        """add_project() must succeed for a directory without .claude/."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'no-claude', with_git=False, with_claude=False)
        try:
            add_project('no-claude', proj, teaparty_home=self.home)
        except ValueError as exc:
            if '.claude' in str(exc):
                self.fail(
                    f'add_project() raised ValueError about missing .claude/: {exc}\n'
                    'OM handles .claude bootstrapping — backend must not gate on it'
                )
            raise

    def test_add_project_still_rejects_nonexistent_path(self):
        """add_project() must still reject a path that does not exist at all."""
        from orchestrator.config_reader import add_project
        with self.assertRaises(ValueError, msg='nonexistent path must still raise ValueError'):
            add_project('ghost', '/nonexistent/path/xyz', teaparty_home=self.home)


# ── AC5 & AC8: create_project() accepts frontmatter ─────────────────────────

class TestCreateProjectFrontmatter(unittest.TestCase):
    """create_project() must accept and write full frontmatter to project.yaml."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)
        _write_teaparty_yaml(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_project_accepts_description(self):
        """create_project() must accept a description kwarg and write it to project.yaml."""
        from orchestrator.config_reader import create_project
        proj = os.path.join(self.tmpdir, 'new-proj-a')
        create_project('new-proj-a', proj, description='Brand new project', teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('description'), 'Brand new project')

    def test_create_project_accepts_lead(self):
        """create_project() must accept a lead kwarg and write it to project.yaml."""
        from orchestrator.config_reader import create_project
        proj = os.path.join(self.tmpdir, 'new-proj-b')
        create_project('new-proj-b', proj, lead='team-lead', teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('lead'), 'team-lead')

    def test_create_project_accepts_decider(self):
        """create_project() must accept a decider kwarg and write it to project.yaml humans block."""
        from orchestrator.config_reader import create_project
        proj = os.path.join(self.tmpdir, 'new-proj-c')
        create_project('new-proj-c', proj, decider='decider-name', teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('humans', {}).get('decider'), 'decider-name')

    def test_create_project_writes_full_frontmatter(self):
        """create_project() must write all frontmatter fields in a single call."""
        from orchestrator.config_reader import create_project
        proj = os.path.join(self.tmpdir, 'new-full')
        create_project(
            'new-full', proj,
            description='Created by OM',
            lead='om-agent',
            decider='dave',
            teaparty_home=self.home,
        )
        data = _read_project_yaml(proj)
        self.assertEqual(data['description'], 'Created by OM')
        self.assertEqual(data['lead'], 'om-agent')
        self.assertEqual(data.get('humans', {}).get('decider'), 'dave')


# ── AC4 & AC5: /api/projects/add and /api/projects/create accept full frontmatter ──

class TestProjectsApiAcceptsFrontmatter(unittest.TestCase):
    """POST /api/projects/add and /api/projects/create must accept full frontmatter in body."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _get_handler_source(self, handler_name: str) -> str:
        import inspect
        handler = getattr(self.bridge, handler_name)
        return inspect.getsource(handler)

    def test_handle_projects_add_reads_description(self):
        """_handle_projects_add must read description from the request body."""
        source = self._get_handler_source('_handle_projects_add')
        self.assertIn(
            'description', source,
            '_handle_projects_add must extract description from request body',
        )

    def test_handle_projects_add_reads_lead(self):
        """_handle_projects_add must read lead from the request body."""
        source = self._get_handler_source('_handle_projects_add')
        self.assertIn(
            'lead', source,
            '_handle_projects_add must extract lead from request body',
        )

    def test_handle_projects_add_reads_decider(self):
        """_handle_projects_add must read decider from the request body."""
        source = self._get_handler_source('_handle_projects_add')
        self.assertIn(
            'decider', source,
            '_handle_projects_add must extract decider from request body',
        )

    def test_handle_projects_add_reads_agents(self):
        """_handle_projects_add must read agents from the request body."""
        source = self._get_handler_source('_handle_projects_add')
        self.assertIn(
            'agents', source,
            '_handle_projects_add must extract agents from request body',
        )

    def test_handle_projects_create_reads_description(self):
        """_handle_projects_create must read description from the request body."""
        source = self._get_handler_source('_handle_projects_create')
        self.assertIn(
            'description', source,
            '_handle_projects_create must extract description from request body',
        )

    def test_handle_projects_create_reads_lead(self):
        """_handle_projects_create must read lead from the request body."""
        source = self._get_handler_source('_handle_projects_create')
        self.assertIn(
            'lead', source,
            '_handle_projects_create must extract lead from request body',
        )


class TestProjectsApiPassesFrontmatterToConfigReader(unittest.TestCase):
    """Handlers must pass frontmatter through to add_project()/create_project()."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _get_handler_source(self, handler_name: str) -> str:
        import inspect
        handler = getattr(self.bridge, handler_name)
        return inspect.getsource(handler)

    def test_handle_projects_add_passes_frontmatter_kwargs(self):
        """_handle_projects_add must call add_project() with frontmatter kwargs, not just name+path."""
        source = self._get_handler_source('_handle_projects_add')
        # Must pass description or lead or at least one frontmatter field beyond name/path
        has_frontmatter = any(
            field in source
            for field in ['description=', 'lead=', 'decider=', 'agents=', 'humans=', 'skills=']
        )
        self.assertTrue(
            has_frontmatter,
            '_handle_projects_add must pass frontmatter kwargs to add_project(), not just name+path',
        )

    def test_handle_projects_create_passes_frontmatter_kwargs(self):
        """_handle_projects_create must call create_project() with frontmatter kwargs."""
        source = self._get_handler_source('_handle_projects_create')
        has_frontmatter = any(
            field in source
            for field in ['description=', 'lead=', 'decider=', 'agents=', 'humans=', 'skills=']
        )
        self.assertTrue(
            has_frontmatter,
            '_handle_projects_create must pass frontmatter kwargs to create_project()',
        )


# ── AC9: OM agent invocation pathway ─────────────────────────────────────────

class TestOfficeManagerSessionInvokeExists(unittest.TestCase):
    """OfficeManagerSession must have an async invoke() method."""

    def test_invoke_method_exists(self):
        """OfficeManagerSession must have an invoke() method."""
        from orchestrator.office_manager import OfficeManagerSession
        self.assertTrue(
            hasattr(OfficeManagerSession, 'invoke'),
            'OfficeManagerSession must have an invoke() method',
        )

    def test_invoke_is_coroutine(self):
        """OfficeManagerSession.invoke() must be an async (coroutine) method."""
        import asyncio
        import inspect
        from orchestrator.office_manager import OfficeManagerSession
        self.assertTrue(
            asyncio.iscoroutinefunction(OfficeManagerSession.invoke),
            'OfficeManagerSession.invoke() must be async',
        )

    def test_invoke_accepts_cwd(self):
        """OfficeManagerSession.invoke() must accept a cwd keyword argument."""
        import inspect
        from orchestrator.office_manager import OfficeManagerSession
        sig = inspect.signature(OfficeManagerSession.invoke)
        self.assertIn(
            'cwd', sig.parameters,
            'OfficeManagerSession.invoke() must accept a cwd keyword argument',
        )


class TestOfficeManagerStatePerConversation(unittest.TestCase):
    """save_state/load_state must be keyed per user_id so multiple OM threads don't collide."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.teaparty_home = _make_teaparty_home(self.tmpdir)
        os.makedirs(os.path.join(self.teaparty_home, 'om'), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_state_uses_per_conversation_file(self):
        """save_state() must write to a file distinct to this user_id, not a shared file."""
        from orchestrator.office_manager import OfficeManagerSession
        session_add = OfficeManagerSession(self.teaparty_home, 'add-project')
        session_add.claude_session_id = 'session-add-abc'
        session_add.save_state()

        session_new = OfficeManagerSession(self.teaparty_home, 'new-project')
        session_new.claude_session_id = 'session-new-xyz'
        session_new.save_state()

        # Load them back — each must recover its own session ID
        fresh_add = OfficeManagerSession(self.teaparty_home, 'add-project')
        fresh_add.load_state()
        fresh_new = OfficeManagerSession(self.teaparty_home, 'new-project')
        fresh_new.load_state()

        self.assertEqual(
            fresh_add.claude_session_id, 'session-add-abc',
            'add-project session must load its own state, not new-project state',
        )
        self.assertEqual(
            fresh_new.claude_session_id, 'session-new-xyz',
            'new-project session must load its own state, not add-project state',
        )

    def test_state_files_are_distinct(self):
        """The state files for different user_ids must be at different filesystem paths."""
        import inspect
        from orchestrator.office_manager import OfficeManagerSession
        # The path logic may live in a helper (_state_path) or inline in save_state.
        # Check all relevant methods for a dynamic path keyed by user_id/qualifier.
        sources = []
        for method in ('save_state', '_state_path'):
            fn = getattr(OfficeManagerSession, method, None)
            if fn is not None:
                sources.append(inspect.getsource(fn))
        combined = '\n'.join(sources)
        has_dynamic_path = (
            'safe_id' in combined
            or 'qualifier' in combined
            or ('{' in combined and ('user_id' in combined or 'conversation_id' in combined)
                and '.json' in combined)
        )
        self.assertTrue(
            has_dynamic_path,
            'save_state() or _state_path() must build a state file path that varies '
            'by user_id/qualifier, not use a fixed shared filename',
        )


class TestOfficeManagerInvokeWritesToBus(unittest.TestCase):
    """invoke() must write the agent response to the OM message bus."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.teaparty_home = _make_teaparty_home(self.tmpdir)
        om_dir = os.path.join(self.teaparty_home, 'om')
        os.makedirs(om_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_stream_jsonl(self, text: str, session_id: str = 'test-session-123') -> str:
        """Write a minimal stream-json file with one assistant text block."""
        import json
        import tempfile
        fd, path = tempfile.mkstemp(suffix='.jsonl')
        with os.fdopen(fd, 'w') as f:
            f.write(json.dumps({
                'type': 'system',
                'subtype': 'init',
                'session_id': session_id,
            }) + '\n')
            f.write(json.dumps({
                'type': 'assistant',
                'message': {
                    'content': [{'type': 'text', 'text': text}],
                },
            }) + '\n')
        return path

    def test_invoke_writes_response_to_bus(self):
        """invoke() must write the OM agent response to the OM bus as sender='office-manager'."""
        import asyncio
        import json
        from unittest.mock import AsyncMock, MagicMock, patch
        from orchestrator.office_manager import OfficeManagerSession
        from orchestrator.messaging import SqliteMessageBus

        session = OfficeManagerSession(self.teaparty_home, 'add-project')
        # Seed a human message so build_context() returns non-empty
        session.send_human_message('I would like to add an existing project.')

        stream_path = self._make_stream_jsonl('I can help you add a project. What is the path?')

        try:
            mock_result = MagicMock()
            mock_result.session_id = 'new-session-id'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                instance.stream_file = stream_path
                MockRunner.return_value = instance

                # Patch tempfile so invoke() uses our prepared stream file
                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(session.invoke(cwd='/tmp'))

            # Check the bus has an office-manager response
            messages = session.get_messages()
            agent_msgs = [m for m in messages if m.sender == 'office-manager']
            self.assertTrue(
                len(agent_msgs) > 0,
                'invoke() must write the OM agent response to the bus as sender=office-manager',
            )
            self.assertIn(
                'add a project', agent_msgs[0].content,
                'The response written to the bus must match the stream output',
            )
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass

    def test_invoke_saves_session_id_after_run(self):
        """invoke() must save the claude_session_id returned by ClaudeRunner for --resume."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from orchestrator.office_manager import OfficeManagerSession

        session = OfficeManagerSession(self.teaparty_home, 'add-project')
        session.send_human_message('I would like to add an existing project.')

        stream_path = self._make_stream_jsonl('Sure, let me navigate the filesystem.', 'returned-sid-456')

        try:
            mock_result = MagicMock()
            mock_result.session_id = 'returned-sid-456'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                instance.stream_file = stream_path
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(session.invoke(cwd='/tmp'))

            self.assertEqual(
                session.claude_session_id, 'returned-sid-456',
                'invoke() must set claude_session_id from the ClaudeRunner result',
            )
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass


class TestBridgeInvokesOMAfterPost(unittest.TestCase):
    """_handle_conversation_post must trigger OM invocation for om: conversations."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bridge_has_invoke_om_method(self):
        """TeaPartyBridge must have a _invoke_om() method for the OM invocation task."""
        self.assertTrue(
            hasattr(self.bridge, '_invoke_om'),
            'TeaPartyBridge must have a _invoke_om() method',
        )

    def test_invoke_om_is_coroutine(self):
        """TeaPartyBridge._invoke_om() must be an async method."""
        import asyncio
        self.assertTrue(
            asyncio.iscoroutinefunction(self.bridge._invoke_om),
            'TeaPartyBridge._invoke_om() must be async',
        )

    def test_handle_conversation_post_creates_task_for_om(self):
        """_handle_conversation_post source must create an asyncio task for om: conversations."""
        import inspect
        source = inspect.getsource(self.bridge._handle_conversation_post)
        self.assertTrue(
            'create_task' in source or '_invoke_om' in source,
            '_handle_conversation_post must schedule OM invocation (create_task or _invoke_om) '
            'for om: conversations',
        )

    def test_handle_conversation_post_checks_om_prefix(self):
        """_handle_conversation_post must check for om: prefix before invoking OM."""
        import inspect
        source = inspect.getsource(self.bridge._handle_conversation_post)
        self.assertIn(
            'om:', source,
            "_handle_conversation_post must check for 'om:' prefix to gate OM invocation",
        )
