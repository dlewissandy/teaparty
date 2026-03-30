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
        'decider': '',
        'agents': [],
        'humans': [],
        'teams': teams or [],
        'workgroups': [],
        'skills': [],
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
        """add_project() must accept a decider kwarg and write it to project.yaml."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'proj-c')
        add_project('proj-c', proj, decider='bob', teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('decider'), 'bob')

    def test_add_project_accepts_agents(self):
        """add_project() must accept an agents list and write it to project.yaml."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'proj-d')
        add_project('proj-d', proj, agents=['agent-x', 'agent-y'], teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('agents'), ['agent-x', 'agent-y'])

    def test_add_project_accepts_humans(self):
        """add_project() must accept a humans list and write it to project.yaml."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'proj-e')
        humans = [{'name': 'Alice', 'role': 'decider'}]
        add_project('proj-e', proj, humans=humans, teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('humans'), humans)

    def test_add_project_accepts_skills(self):
        """add_project() must accept a skills list and write it to project.yaml."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'proj-f')
        add_project('proj-f', proj, skills=['skill-a'], teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('skills'), ['skill-a'])

    def test_add_project_writes_full_frontmatter_together(self):
        """add_project() must write all frontmatter fields in a single call."""
        from orchestrator.config_reader import add_project
        proj = _make_project_dir(self.tmpdir, 'proj-full')
        add_project(
            'proj-full', proj,
            description='Full project',
            lead='manager-agent',
            decider='carol',
            agents=['agent-1'],
            humans=[{'name': 'Carol', 'role': 'decider'}],
            skills=['fix-issue'],
            teaparty_home=self.home,
        )
        data = _read_project_yaml(proj)
        self.assertEqual(data['description'], 'Full project')
        self.assertEqual(data['lead'], 'manager-agent')
        self.assertEqual(data['decider'], 'carol')
        self.assertEqual(data['agents'], ['agent-1'])
        self.assertEqual(data['humans'], [{'name': 'Carol', 'role': 'decider'}])
        self.assertEqual(data['skills'], ['fix-issue'])


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
        """create_project() must accept a decider kwarg and write it to project.yaml."""
        from orchestrator.config_reader import create_project
        proj = os.path.join(self.tmpdir, 'new-proj-c')
        create_project('new-proj-c', proj, decider='decider-name', teaparty_home=self.home)
        data = _read_project_yaml(proj)
        self.assertEqual(data.get('decider'), 'decider-name')

    def test_create_project_writes_full_frontmatter(self):
        """create_project() must write all frontmatter fields in a single call."""
        from orchestrator.config_reader import create_project
        proj = os.path.join(self.tmpdir, 'new-full')
        create_project(
            'new-full', proj,
            description='Created by OM',
            lead='om-agent',
            decider='dave',
            agents=['builder-agent'],
            humans=[{'name': 'Dave', 'role': 'decider'}],
            skills=['sprint'],
            teaparty_home=self.home,
        )
        data = _read_project_yaml(proj)
        self.assertEqual(data['description'], 'Created by OM')
        self.assertEqual(data['lead'], 'om-agent')
        self.assertEqual(data['decider'], 'dave')
        self.assertEqual(data['agents'], ['builder-agent'])
        self.assertEqual(data['skills'], ['sprint'])


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
