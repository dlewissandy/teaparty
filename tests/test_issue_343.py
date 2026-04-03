"""Tests for Issue #343: Artifact viewer — nested folder navigation and per-project pinned paths.

Acceptance criteria:
1. artifact_pins field supported in project.yaml and ProjectTeam dataclass
2. PinArtifact MCP tool adds or updates a pin entry in the project's artifact_pins
3. UnpinArtifact MCP tool removes a pin entry by path
4. GET /api/artifacts/{project}/pins returns the pins list with absolute paths and is_dir flags
5. Artifact viewer navigator shows a Pinned section above Documentation sections
6. File pins open the file directly on click
7. Folder pins render as collapsible nodes; expanding calls /api/fs/list and shows children
8. Nested subdirectories are themselves collapsible (lazy, no depth limit)
9. Pinned section survives refresh() — pins come from config, not session state
10. Project config page shows current pins with a "+ Pin" button that seeds an OM conversation
11. A skill phase calling PinArtifact causes the pinned path to appear in the viewer on next load
12. Specification-based tests cover artifact_pins parse/scaffold round-trip and the endpoint
"""
import asyncio
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import yaml

_REPO_ROOT = Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tmpdir() -> str:
    return tempfile.mkdtemp()


def _run(coro):
    return asyncio.run(coro)


def _make_teaparty_home(tmpdir: str, project_name: str, project_path: str) -> str:
    """Create .teaparty/ with a teaparty.yaml that registers a project."""
    tp_home = os.path.join(tmpdir, '.teaparty')
    mgmt_dir = os.path.join(tp_home, 'management')
    os.makedirs(mgmt_dir, exist_ok=True)
    data = {
        'name': 'Test Team',
        'description': 'test',
        'lead': 'office-manager',
        'humans': {'decider': 'darrell'},
        'members': {'agents': [], 'projects': [project_name]},
        'projects': [{'name': project_name, 'path': project_path, 'config': ''}],
        'workgroups': [],
        'scheduled': [],
    }
    with open(os.path.join(mgmt_dir, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return tp_home


def _make_project_yaml(project_dir: str, pins: list | None = None) -> str:
    """Create .teaparty/project/project.yaml with optional artifact_pins."""
    tp_local = os.path.join(project_dir, '.teaparty', 'project')
    os.makedirs(tp_local, exist_ok=True)
    path = os.path.join(tp_local, 'project.yaml')
    data = {
        'name': os.path.basename(project_dir),
        'description': '',
        'lead': '',
        'humans': {},
        'members': {'workgroups': []},
        'workgroups': [],
    }
    if pins is not None:
        data['artifact_pins'] = pins
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return path


def _make_bridge(teaparty_home: str):
    from bridge.server import TeaPartyBridge
    static_dir = os.path.join(teaparty_home, 'static')
    os.makedirs(static_dir, exist_ok=True)
    with open(os.path.join(static_dir, 'index.html'), 'w') as f:
        f.write('<html></html>')
    return TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)


def _mock_request(match_info: dict | None = None, query: dict | None = None) -> MagicMock:
    req = MagicMock()
    req.match_info = match_info or {}
    req.rel_url.query = query or {}
    return req


# ── AC1: artifact_pins in ProjectTeam dataclass ───────────────────────────────

class TestProjectTeamArtifactPinsField(unittest.TestCase):
    """ProjectTeam must have an artifact_pins field that parses from project.yaml."""

    def test_project_team_dataclass_has_artifact_pins_field(self):
        """ProjectTeam must have artifact_pins as a field."""
        from orchestrator.config_reader import ProjectTeam
        import dataclasses
        field_names = [f.name for f in dataclasses.fields(ProjectTeam)]
        self.assertIn('artifact_pins', field_names, 'ProjectTeam must have artifact_pins field')

    def test_artifact_pins_defaults_to_empty_list(self):
        """ProjectTeam artifact_pins must default to []."""
        from orchestrator.config_reader import ProjectTeam
        team = ProjectTeam(name='test')
        self.assertEqual(team.artifact_pins, [], 'artifact_pins must default to empty list')

    def test_load_project_team_parses_artifact_pins(self):
        """load_project_team must populate artifact_pins from project.yaml."""
        from orchestrator.config_reader import load_project_team
        tmpdir = _make_tmpdir()
        pins = [
            {'path': 'docs/', 'label': 'Documentation'},
            {'path': 'src/orchestrator/', 'label': 'Orchestrator'},
        ]
        project_yaml_path = _make_project_yaml(tmpdir, pins=pins)
        team = load_project_team(project_dir=tmpdir)
        self.assertEqual(len(team.artifact_pins), 2)
        self.assertEqual(team.artifact_pins[0]['path'], 'docs/')
        self.assertEqual(team.artifact_pins[0]['label'], 'Documentation')
        self.assertEqual(team.artifact_pins[1]['path'], 'src/orchestrator/')

    def test_load_project_team_missing_artifact_pins_defaults_to_empty_list(self):
        """load_project_team must return [] for artifact_pins when key is absent."""
        from orchestrator.config_reader import load_project_team
        tmpdir = _make_tmpdir()
        _make_project_yaml(tmpdir, pins=None)  # no artifact_pins key
        team = load_project_team(project_dir=tmpdir)
        self.assertEqual(team.artifact_pins, [], 'missing artifact_pins must default to []')

    def test_load_project_team_entry_without_label_is_accepted(self):
        """A pin entry with only path (no label) must be accepted."""
        from orchestrator.config_reader import load_project_team
        tmpdir = _make_tmpdir()
        pins = [{'path': 'tests/'}]
        _make_project_yaml(tmpdir, pins=pins)
        team = load_project_team(project_dir=tmpdir)
        self.assertEqual(len(team.artifact_pins), 1)
        self.assertEqual(team.artifact_pins[0]['path'], 'tests/')


# ── AC1: scaffold includes artifact_pins ─────────────────────────────────────

class TestScaffoldProjectYamlIncludesArtifactPins(unittest.TestCase):
    """_scaffold_project_yaml must write artifact_pins to the YAML file."""

    def test_scaffold_writes_artifact_pins_key(self):
        """_scaffold_project_yaml must include artifact_pins in the written YAML."""
        from orchestrator.config_reader import _scaffold_project_yaml
        tmpdir = _make_tmpdir()
        _scaffold_project_yaml(name='myproject', project_dir=tmpdir)
        project_yaml_path = os.path.join(tmpdir, '.teaparty', 'project', 'project.yaml')
        self.assertTrue(os.path.exists(project_yaml_path))
        with open(project_yaml_path) as f:
            data = yaml.safe_load(f)
        self.assertIn('artifact_pins', data, '_scaffold_project_yaml must write artifact_pins')
        self.assertEqual(data['artifact_pins'], [], 'scaffolded artifact_pins must be empty list')

    def test_scaffold_artifact_pins_round_trip(self):
        """Writing artifact_pins to project.yaml and loading it must round-trip correctly."""
        from orchestrator.config_reader import load_project_team
        tmpdir = _make_tmpdir()
        pins = [
            {'path': 'docs/', 'label': 'Docs'},
            {'path': 'tests/test_engine.py', 'label': 'Engine Tests'},
        ]
        _make_project_yaml(tmpdir, pins=pins)
        team = load_project_team(project_dir=tmpdir)
        self.assertEqual(len(team.artifact_pins), 2)
        self.assertEqual(team.artifact_pins[1]['path'], 'tests/test_engine.py')
        self.assertEqual(team.artifact_pins[1]['label'], 'Engine Tests')


# ── AC2: PinArtifact handler ──────────────────────────────────────────────────

class TestPinArtifactHandler(unittest.TestCase):
    """pin_artifact_handler must add or update a pin entry in the project's artifact_pins."""

    def test_pin_artifact_adds_new_entry(self):
        """pin_artifact_handler must append a new pin entry to artifact_pins."""
        from orchestrator.mcp_server import pin_artifact_handler
        tmpdir = _make_tmpdir()
        project_dir = os.path.join(tmpdir, 'myproject')
        os.makedirs(project_dir)
        tp_home = _make_teaparty_home(tmpdir, 'myproject', project_dir)
        _make_project_yaml(project_dir, pins=[])

        result = json.loads(pin_artifact_handler(
            project='myproject', path='docs/', label='Documentation',
            teaparty_home=tp_home,
        ))
        self.assertTrue(result.get('success'), f'Expected success, got: {result}')

        project_yaml_path = os.path.join(project_dir, '.teaparty', 'project', 'project.yaml')
        with open(project_yaml_path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(len(data['artifact_pins']), 1)
        self.assertEqual(data['artifact_pins'][0]['path'], 'docs/')
        self.assertEqual(data['artifact_pins'][0]['label'], 'Documentation')

    def test_pin_artifact_updates_existing_entry_with_same_path(self):
        """pin_artifact_handler must update the label for an existing path."""
        from orchestrator.mcp_server import pin_artifact_handler
        tmpdir = _make_tmpdir()
        project_dir = os.path.join(tmpdir, 'myproject')
        os.makedirs(project_dir)
        tp_home = _make_teaparty_home(tmpdir, 'myproject', project_dir)
        _make_project_yaml(project_dir, pins=[{'path': 'docs/', 'label': 'Old Label'}])

        pin_artifact_handler(
            project='myproject', path='docs/', label='New Label',
            teaparty_home=tp_home,
        )

        project_yaml_path = os.path.join(project_dir, '.teaparty', 'project', 'project.yaml')
        with open(project_yaml_path) as f:
            data = yaml.safe_load(f)
        # Must not have created a duplicate
        pins = [p for p in data['artifact_pins'] if p['path'] == 'docs/']
        self.assertEqual(len(pins), 1, 'pin_artifact_handler must not duplicate an existing path')
        self.assertEqual(pins[0]['label'], 'New Label', 'label must be updated')

    def test_pin_artifact_unknown_project_returns_error(self):
        """pin_artifact_handler must return an error dict for an unregistered project."""
        from orchestrator.mcp_server import pin_artifact_handler
        tmpdir = _make_tmpdir()
        tp_home = _make_teaparty_home(tmpdir, 'myproject', os.path.join(tmpdir, 'myproject'))

        result = json.loads(pin_artifact_handler(
            project='nonexistent', path='docs/', label='Docs',
            teaparty_home=tp_home,
        ))
        self.assertFalse(result.get('success'), 'Unknown project must return error')
        self.assertIn('error', result)


# ── AC3: UnpinArtifact handler ────────────────────────────────────────────────

class TestUnpinArtifactHandler(unittest.TestCase):
    """unpin_artifact_handler must remove a pin entry by path."""

    def test_unpin_artifact_removes_entry(self):
        """unpin_artifact_handler must remove the matching path from artifact_pins."""
        from orchestrator.mcp_server import unpin_artifact_handler
        tmpdir = _make_tmpdir()
        project_dir = os.path.join(tmpdir, 'myproject')
        os.makedirs(project_dir)
        tp_home = _make_teaparty_home(tmpdir, 'myproject', project_dir)
        _make_project_yaml(project_dir, pins=[
            {'path': 'docs/', 'label': 'Docs'},
            {'path': 'tests/', 'label': 'Tests'},
        ])

        result = json.loads(unpin_artifact_handler(
            project='myproject', path='docs/',
            teaparty_home=tp_home,
        ))
        self.assertTrue(result.get('success'), f'Expected success, got: {result}')

        project_yaml_path = os.path.join(project_dir, '.teaparty', 'project', 'project.yaml')
        with open(project_yaml_path) as f:
            data = yaml.safe_load(f)
        paths = [p['path'] for p in data['artifact_pins']]
        self.assertNotIn('docs/', paths, 'docs/ pin must be removed')
        self.assertIn('tests/', paths, 'tests/ pin must remain')

    def test_unpin_artifact_unknown_path_returns_error(self):
        """unpin_artifact_handler must return an error for a path not in artifact_pins."""
        from orchestrator.mcp_server import unpin_artifact_handler
        tmpdir = _make_tmpdir()
        project_dir = os.path.join(tmpdir, 'myproject')
        os.makedirs(project_dir)
        tp_home = _make_teaparty_home(tmpdir, 'myproject', project_dir)
        _make_project_yaml(project_dir, pins=[])

        result = json.loads(unpin_artifact_handler(
            project='myproject', path='nonexistent/',
            teaparty_home=tp_home,
        ))
        self.assertFalse(result.get('success'), 'Unpin of unknown path must return error')


# ── AC4: GET /api/artifacts/{project}/pins endpoint ──────────────────────────

class TestArtifactPinsEndpoint(unittest.TestCase):
    """GET /api/artifacts/{project}/pins must return pins with absolute paths and is_dir flags."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_pins_endpoint_returns_pins_list(self):
        """Endpoint must return a JSON list of pins with path, label, and is_dir."""
        tmpdir = _make_tmpdir()
        project_dir = os.path.join(tmpdir, 'myproject')
        os.makedirs(project_dir)
        tp_home = _make_teaparty_home(tmpdir, 'myproject', project_dir)
        # Create a real subdir and file for is_dir resolution
        docs_dir = os.path.join(project_dir, 'docs')
        os.makedirs(docs_dir)
        _make_project_yaml(project_dir, pins=[
            {'path': 'docs/', 'label': 'Documentation'},
        ])

        bridge = _make_bridge(tp_home)
        req = _mock_request(match_info={'project': 'myproject'})
        resp = self._run(bridge._handle_artifact_pins(req))

        self.assertEqual(resp.status, 200)
        pins = json.loads(resp.text)
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0]['label'], 'Documentation')
        self.assertTrue(pins[0]['is_dir'], 'docs/ must have is_dir=True')
        # Absolute path must point to the project dir
        self.assertTrue(os.path.isabs(pins[0]['path']), 'path must be absolute')

    def test_pins_endpoint_file_pin_has_is_dir_false(self):
        """A file pin must have is_dir=False."""
        tmpdir = _make_tmpdir()
        project_dir = os.path.join(tmpdir, 'myproject')
        os.makedirs(project_dir)
        tp_home = _make_teaparty_home(tmpdir, 'myproject', project_dir)
        # Create a real file
        test_file = os.path.join(project_dir, 'README.md')
        with open(test_file, 'w') as f:
            f.write('# Test')
        _make_project_yaml(project_dir, pins=[
            {'path': 'README.md', 'label': 'Readme'},
        ])

        bridge = _make_bridge(tp_home)
        req = _mock_request(match_info={'project': 'myproject'})
        resp = self._run(bridge._handle_artifact_pins(req))

        self.assertEqual(resp.status, 200)
        pins = json.loads(resp.text)
        self.assertEqual(len(pins), 1)
        self.assertFalse(pins[0]['is_dir'], 'README.md must have is_dir=False')

    def test_pins_endpoint_unknown_project_returns_404(self):
        """Endpoint must return 404 for a project not in the registry."""
        tmpdir = _make_tmpdir()
        tp_home = _make_teaparty_home(tmpdir, 'myproject', os.path.join(tmpdir, 'myproject'))
        bridge = _make_bridge(tp_home)
        req = _mock_request(match_info={'project': 'nonexistent'})
        resp = self._run(bridge._handle_artifact_pins(req))
        self.assertEqual(resp.status, 404)

    def test_pins_endpoint_empty_pins_returns_empty_list(self):
        """Endpoint must return [] when artifact_pins is empty."""
        tmpdir = _make_tmpdir()
        project_dir = os.path.join(tmpdir, 'myproject')
        os.makedirs(project_dir)
        tp_home = _make_teaparty_home(tmpdir, 'myproject', project_dir)
        _make_project_yaml(project_dir, pins=[])

        bridge = _make_bridge(tp_home)
        req = _mock_request(match_info={'project': 'myproject'})
        resp = self._run(bridge._handle_artifact_pins(req))

        self.assertEqual(resp.status, 200)
        pins = json.loads(resp.text)
        self.assertEqual(pins, [])

    def test_pins_endpoint_registered_in_router(self):
        """GET /api/artifacts/{project}/pins must be a registered route."""
        import inspect
        from bridge.server import TeaPartyBridge
        source = inspect.getsource(TeaPartyBridge._build_app)
        self.assertIn('/api/artifacts/{project}/pins', source,
                      "Route /api/artifacts/{project}/pins must be registered")

    def test_pins_endpoint_label_falls_back_to_last_path_component(self):
        """A pin without label must fall back to the last path component in the response."""
        tmpdir = _make_tmpdir()
        project_dir = os.path.join(tmpdir, 'myproject')
        os.makedirs(project_dir)
        tp_home = _make_teaparty_home(tmpdir, 'myproject', project_dir)
        docs_dir = os.path.join(project_dir, 'docs')
        os.makedirs(docs_dir)
        _make_project_yaml(project_dir, pins=[
            {'path': 'docs/'},  # no label
        ])

        bridge = _make_bridge(tp_home)
        req = _mock_request(match_info={'project': 'myproject'})
        resp = self._run(bridge._handle_artifact_pins(req))

        self.assertEqual(resp.status, 200)
        pins = json.loads(resp.text)
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0]['label'], 'docs',
                         'Missing label must fall back to last path component')


# ── AC5–9: Artifact viewer HTML structure ─────────────────────────────────────

class TestArtifactsHtmlPinnedSection(unittest.TestCase):
    """artifacts.html must fetch pins and render a Pinned section above Documentation."""

    def _read_html(self) -> str:
        return (_REPO_ROOT / 'bridge' / 'static' / 'artifacts.html').read_text()

    def test_artifacts_html_fetches_pins_endpoint(self):
        """artifacts.html must call /api/artifacts/{project}/pins on init."""
        html = self._read_html()
        self.assertIn('/api/artifacts/', html)
        self.assertIn('/pins', html,
                      "artifacts.html must fetch the /pins endpoint for the pinned section")

    def test_artifacts_html_has_pinned_section_before_documentation(self):
        """render() must output the Pinned section before Documentation sections."""
        html = self._read_html()
        # The pinned section heading must appear in the render function
        self.assertRegex(html, r'[Pp]inned',
                         "artifacts.html must render a Pinned section heading")

    def test_artifacts_html_folder_nodes_call_fs_list(self):
        """Folder pin expansion must call /api/fs/list."""
        html = self._read_html()
        self.assertIn('/api/fs/list', html,
                      "artifacts.html must call /api/fs/list for folder expansion")

    def test_artifacts_html_folder_nodes_are_collapsible(self):
        """Folder pins must support expand/collapse toggle."""
        html = self._read_html()
        # Must have some concept of expanded state
        self.assertRegex(html, r'expand|collapse|toggle',
                         "artifacts.html must support expand/collapse for folder nodes")

    def test_artifacts_html_refresh_re_fetches_pins(self):
        """refresh() must re-fetch the /pins endpoint, not rely on session state."""
        html = self._read_html()
        # Locate refresh() definition and verify /pins appears in the function
        refresh_pos = html.find('async function refresh()')
        self.assertGreater(refresh_pos, -1, 'refresh() function must be present')
        # Find the opening brace position
        start = html.find('{', refresh_pos)
        self.assertGreater(start, -1)
        # Walk forward tracking brace depth to find the function end
        depth = 0
        end = start
        for i in range(start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = html[start:end]
        self.assertIn('/pins', body,
                      "refresh() must re-fetch /pins endpoint so pinned section survives refresh")


# ── AC6: File pin behavior ────────────────────────────────────────────────────

class TestArtifactsHtmlFilePinBehavior(unittest.TestCase):
    """File pins must open the file on click (call loadFile)."""

    def _read_html(self) -> str:
        return (_REPO_ROOT / 'bridge' / 'static' / 'artifacts.html').read_text()

    def test_file_pin_renders_as_nav_item_that_calls_loadFile(self):
        """File pin nav items must call loadFile on click."""
        html = self._read_html()
        # The pin rendering code must call loadFile for file-type pins
        self.assertIn('loadFile', html,
                      "File pin must call loadFile on click")


# ── AC10: Config page Pins card ───────────────────────────────────────────────

class TestConfigHtmlPinsCard(unittest.TestCase):
    """config.html project view must show a Pins section with a '+ Pin' button."""

    def _read_html(self) -> str:
        return (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()

    def test_project_view_fetches_pins_endpoint(self):
        """renderProject must fetch /api/artifacts/{project}/pins."""
        html = self._read_html()
        self.assertIn('/pins', html,
                      "config.html renderProject must fetch the pins endpoint")

    def test_project_view_shows_pins_section_card(self):
        """renderProject must include a Pins section card."""
        html = self._read_html()
        self.assertRegex(html, r'[Pp]ins',
                         "config.html must render a Pins section in the project view")

    def test_project_view_pin_button_seeds_om_conversation(self):
        """+ Pin button must call openChatWithSeed to seed an OM conversation."""
        html = self._read_html()
        # The button must use openChatWithSeed with an om: conversation
        # and mention pinning
        self.assertRegex(html, r"openChatWithSeed.*[Pp]in",
                         "+ Pin button must seed an OM conversation about pinning")


# ── AC11: End-to-end: PinArtifact → pins endpoint ────────────────────────────

class TestPinArtifactEndToEnd(unittest.TestCase):
    """PinArtifact handler + pins endpoint: pinned path must appear in viewer on next load."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_pin_artifact_then_pins_endpoint_returns_pin(self):
        """Calling pin_artifact_handler, then the pins endpoint, must return the new pin."""
        from orchestrator.mcp_server import pin_artifact_handler
        tmpdir = _make_tmpdir()
        project_dir = os.path.join(tmpdir, 'myproject')
        os.makedirs(project_dir)
        tp_home = _make_teaparty_home(tmpdir, 'myproject', project_dir)
        docs_dir = os.path.join(project_dir, 'docs')
        os.makedirs(docs_dir)
        _make_project_yaml(project_dir, pins=[])

        # Step 1: PinArtifact
        result = json.loads(pin_artifact_handler(
            project='myproject', path='docs/', label='Documentation',
            teaparty_home=tp_home,
        ))
        self.assertTrue(result.get('success'))

        # Step 2: pins endpoint returns the new pin
        bridge = _make_bridge(tp_home)
        req = _mock_request(match_info={'project': 'myproject'})
        resp = self._run(bridge._handle_artifact_pins(req))

        self.assertEqual(resp.status, 200)
        pins = json.loads(resp.text)
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0]['label'], 'Documentation')
        self.assertTrue(pins[0]['is_dir'])


# ── AC2: MCP tool wrappers exist in create_server ─────────────────────────────

class TestMCPToolWrappersExist(unittest.TestCase):
    """PinArtifact and UnpinArtifact must be registered as MCP tools in create_server."""

    def test_pin_artifact_handler_importable(self):
        """pin_artifact_handler must be importable from orchestrator.mcp_server."""
        from orchestrator.mcp_server import pin_artifact_handler
        self.assertTrue(callable(pin_artifact_handler))

    def test_unpin_artifact_handler_importable(self):
        """unpin_artifact_handler must be importable from orchestrator.mcp_server."""
        from orchestrator.mcp_server import unpin_artifact_handler
        self.assertTrue(callable(unpin_artifact_handler))

    def test_create_server_registers_pin_artifact_tool(self):
        """create_server must register a PinArtifact tool."""
        import inspect
        from orchestrator.mcp_server import create_server
        source = inspect.getsource(create_server)
        self.assertIn('PinArtifact', source,
                      "create_server must register a PinArtifact MCP tool")

    def test_create_server_registers_unpin_artifact_tool(self):
        """create_server must register an UnpinArtifact tool."""
        import inspect
        from orchestrator.mcp_server import create_server
        source = inspect.getsource(create_server)
        self.assertIn('UnpinArtifact', source,
                      "create_server must register an UnpinArtifact MCP tool")


if __name__ == '__main__':
    unittest.main()
