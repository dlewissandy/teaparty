"""Tests for issue #370: Dashboard — file browser for pinning artifacts.

Acceptance criteria:
1. Artifacts panel (workgroup) has a Browse button alongside + New
2. Artifacts panel (project) has a Browse button alongside existing buttons
3. Clicking Browse opens a file tree navigator via /api/fs/list
4. Files and directories are both selectable
5. Label is editable after selection (input field in the modal)
6. Workgroup selection saved via PATCH /api/workgroups/{name} artifacts
7. Project selection saved via PATCH /api/artifacts/{project}/pins
8. New PATCH /api/artifacts/{project}/pins endpoint writes artifact_pins to project YAML
"""
import asyncio
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _get_config_html() -> str:
    path = _REPO_ROOT / 'bridge' / 'static' / 'config.html'
    return path.read_text()


def _extract_render_workgroup_body(source: str) -> str:
    m = re.search(
        r'async function renderWorkgroup\(.*?\)(.*?)(?=\nvar urlParams|\nasync function |\nfunction )',
        source, re.DOTALL
    )
    if m is None:
        raise AssertionError('renderWorkgroup() not found in config.html')
    return m.group(1)


def _extract_render_project_body(source: str) -> str:
    m = re.search(
        r'async function renderProject\(.*?\)(.*?)(?=\nasync function |\nvar _currentWgName)',
        source, re.DOTALL
    )
    if m is None:
        raise AssertionError('renderProject() not found in config.html')
    return m.group(1)


def _make_teaparty_home(tmp: str, projects: list | None = None) -> str:
    tp_home = os.path.join(tmp, '.teaparty')
    os.makedirs(tp_home)
    data = {
        'name': 'Test Org',
        'description': 'test',
        'lead': 'office-manager',
        'humans': {'decider': 'tester'},
        'members': {'agents': [], 'projects': []},
        'projects': projects or [],
        'workgroups': [],
        'scheduled': [],
    }
    with open(os.path.join(tp_home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return tp_home


def _make_project_dir(tmp: str, slug: str, artifact_pins: list | None = None) -> str:
    """Create a project directory with .teaparty.local/project.yaml."""
    proj_dir = os.path.join(tmp, slug)
    tp_local = os.path.join(proj_dir, '.teaparty.local')
    os.makedirs(tp_local)
    data = {
        'name': slug,
        'description': 'Test project',
        'lead': 'auditor',
        'humans': {},
        'workgroups': [],
        'members': {'workgroups': []},
        'artifact_pins': artifact_pins or [],
    }
    with open(os.path.join(tp_local, 'project.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return proj_dir


def _make_bridge(teaparty_home: str, tmp: str):
    from bridge.server import TeaPartyBridge
    static_dir = os.path.join(tmp, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)


def _read_project_yaml(proj_dir: str) -> dict:
    path = os.path.join(proj_dir, '.teaparty.local', 'project.yaml')
    with open(path) as f:
        return yaml.safe_load(f)


# ── AC1: Browse button in workgroup Artifacts panel ───────────────────────────

class TestWorkgroupArtifactsPanelHasBrowseButton(unittest.TestCase):
    """renderWorkgroup() Artifacts panel must include a Browse button."""

    def test_workgroup_artifacts_sectioncard_has_browse_option(self):
        """renderWorkgroup() Artifacts sectionCard must include browseBtn or Browse button."""
        body = _extract_render_workgroup_body(_get_config_html())
        artifacts_section = re.search(
            r"sectionCard\('Artifacts'.*?\)",
            body, re.DOTALL
        )
        self.assertIsNotNone(artifacts_section, "Artifacts sectionCard not found in renderWorkgroup()")
        call = artifacts_section.group(0)
        self.assertTrue(
            'browseBtn' in call or 'Browse' in call,
            "renderWorkgroup() Artifacts sectionCard must include browseBtn or Browse button option; "
            f"got: {call!r}"
        )

    def test_workgroup_artifacts_browse_button_triggers_file_browser(self):
        """renderWorkgroup() Artifacts Browse button must call a file browser function."""
        body = _extract_render_workgroup_body(_get_config_html())
        # Browse must invoke a file browser function, not openChat or openChatWithSeed
        has_browse = (
            'openFileBrowser' in body
            or 'openArtifactBrowser' in body
            or 'browseArtifacts' in body
            or 'fileBrowser' in body
        )
        self.assertTrue(
            has_browse,
            "renderWorkgroup() must call a file browser function (e.g. openFileBrowser) "
            "for the Artifacts Browse button, not openChat/openChatWithSeed"
        )


# ── AC2: Browse button in project Artifacts/Pins panel ───────────────────────

class TestProjectArtifactsPanelHasBrowseButton(unittest.TestCase):
    """renderProject() Artifacts/Pins panel must include a Browse button."""

    def test_project_artifacts_sectioncard_has_browse_option(self):
        """renderProject() Artifacts sectionCard must include browseBtn or Browse button."""
        body = _extract_render_project_body(_get_config_html())
        artifacts_section = re.search(
            r"sectionCard\('Artifacts'.*?\)",
            body, re.DOTALL
        )
        self.assertIsNotNone(artifacts_section, "Artifacts sectionCard not found in renderProject()")
        call = artifacts_section.group(0)
        self.assertTrue(
            'browseBtn' in call or 'Browse' in call,
            "renderProject() Artifacts sectionCard must include browseBtn or Browse button option; "
            f"got: {call!r}"
        )

    def test_project_artifacts_browse_button_triggers_file_browser(self):
        """renderProject() Artifacts Browse button must call a file browser function."""
        body = _extract_render_project_body(_get_config_html())
        has_browse = (
            'openFileBrowser' in body
            or 'openArtifactBrowser' in body
            or 'browseArtifacts' in body
            or 'fileBrowser' in body
        )
        self.assertTrue(
            has_browse,
            "renderProject() must call a file browser function (e.g. openFileBrowser) "
            "for the Artifacts Browse button"
        )


# ── AC3: File browser uses /api/fs/list ──────────────────────────────────────

class TestFileBrowserUsesApiEndpoint(unittest.TestCase):
    """The file browser must use /api/fs/list to navigate the filesystem."""

    def test_config_html_has_file_browser_function(self):
        """config.html must define a file browser function (openFileBrowser or similar)."""
        source = _get_config_html()
        has_func = (
            'function openFileBrowser' in source
            or 'function openArtifactBrowser' in source
            or 'function browseArtifacts' in source
            or 'function fileBrowser' in source
        )
        self.assertTrue(
            has_func,
            "config.html must define a file browser function such as openFileBrowser() "
            "to handle artifact browsing"
        )

    def test_file_browser_calls_api_fs_list(self):
        """File browser must use /api/fs/list to list directory contents."""
        source = _get_config_html()
        self.assertIn(
            '/api/fs/list',
            source,
            "config.html must call /api/fs/list to navigate the filesystem in the file browser"
        )


# ── AC4: Files and directories are both selectable ───────────────────────────

class TestFileBrowserSelectsFilesAndDirs(unittest.TestCase):
    """File browser must allow selecting both files and directories."""

    def test_file_browser_handles_is_dir_property(self):
        """File browser must use is_dir in the browser function to distinguish files from dirs."""
        source = _get_config_html()
        m = re.search(
            r'function (?:openFileBrowser|openArtifactBrowser|browseArtifacts|fileBrowser)'
            r'.*?(?=\nfunction |\nasync function |\nvar urlParams)',
            source, re.DOTALL
        )
        if m is None:
            self.fail(
                "File browser function not found in config.html — cannot verify is_dir handling"
            )
        browser_body = m.group(0)
        self.assertIn(
            'is_dir',
            browser_body,
            "File browser function must use is_dir from /api/fs/list entries "
            "to handle both files and directories as selectable"
        )


# ── AC5: Label is editable after selection ───────────────────────────────────

class TestFileBrowserLabelEditable(unittest.TestCase):
    """File browser modal must include an editable label field."""

    def test_file_browser_has_label_input(self):
        """File browser modal must have a label input field for editing pin labels."""
        source = _get_config_html()
        # The label input must be present in the file browser section of config.html
        # Look for a label input near the file browser function
        m = re.search(
            r'function (?:openFileBrowser|openArtifactBrowser|browseArtifacts|fileBrowser)'
            r'.*?(?=\nfunction |\nasync function |\nvar urlParams)',
            source, re.DOTALL
        )
        if m is None:
            self.fail(
                "File browser function not found in config.html — cannot verify label input"
            )
        browser_body = m.group(0)
        has_label_input = (
            'label' in browser_body.lower()
            and ('input' in browser_body or 'contenteditable' in browser_body)
        )
        self.assertTrue(
            has_label_input,
            "File browser modal must include a label input field so users can edit the pin label "
            "before confirming. Found function but no label input."
        )


# ── AC6a: Workgroup selection saved via existing PATCH /api/workgroups/{name} ─

class TestFileBrowserSavesWorkgroupArtifact(unittest.TestCase):
    """File browser must save workgroup artifacts via PATCH /api/workgroups/{name}."""

    def test_file_browser_patches_workgroups_endpoint_for_workgroup_context(self):
        """File browser confirmation must PATCH /api/workgroups/ with artifacts for workgroup context."""
        source = _get_config_html()
        m = re.search(
            r'function (?:openFileBrowser|openArtifactBrowser|browseArtifacts|fileBrowser)'
            r'.*?(?=\nfunction |\nasync function |\nvar urlParams)',
            source, re.DOTALL
        )
        if m is None:
            self.fail("File browser function not found in config.html")
        browser_body = m.group(0)
        self.assertIn(
            '/api/workgroups/',
            browser_body,
            "File browser must PATCH /api/workgroups/{name} to save workgroup artifacts"
        )


# ── AC7: New PATCH /api/artifacts/{project}/pins endpoint ─────────────────────

class TestPatchProjectArtifactPinsEndpointExists(unittest.TestCase):
    """PATCH /api/artifacts/{project}/pins must be registered in the bridge server."""

    def test_patch_artifact_pins_route_registered(self):
        """bridge/server.py must register PATCH /api/artifacts/{project}/pins."""
        source = (_REPO_ROOT / 'bridge' / 'server.py').read_text()
        self.assertIn(
            "add_patch('/api/artifacts/",
            source,
            "bridge/server.py must register app.router.add_patch('/api/artifacts/...') "
            "for the PATCH /api/artifacts/{project}/pins endpoint"
        )


# ── AC8: PATCH /api/artifacts/{project}/pins writes artifact_pins to project YAML ─

class TestPatchArtifactPinsWritesYaml(unittest.TestCase):
    """PATCH /api/artifacts/{project}/pins must write artifact_pins to project YAML."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.slug = 'myproject'
        self.proj_dir = _make_project_dir(
            self.tmp, self.slug,
            artifact_pins=[{'path': 'old/path.md', 'label': 'Old'}],
        )
        tp_home = _make_teaparty_home(
            self.tmp,
            projects=[{'name': self.slug, 'path': self.proj_dir}],
        )
        self.bridge = _make_bridge(tp_home, self.tmp)
        self.bridge._project_path_cache = {self.slug: self.proj_dir}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self, slug: str, body: dict) -> tuple[int, dict]:
        from unittest.mock import AsyncMock, MagicMock
        bridge = self.bridge

        async def _call():
            request = MagicMock()
            request.match_info = {'project': slug}
            request.json = AsyncMock(return_value=body)
            response = await bridge._handle_artifact_pins_patch(request)
            return response.status, json.loads(response.body)

        return _run_async(_call())

    def test_patch_adds_new_pin_to_project_yaml(self):
        """PATCH /api/artifacts/{project}/pins with new list writes artifact_pins to YAML."""
        new_pins = [{'path': 'docs/design.md', 'label': 'Design'}]
        self._patch(self.slug, {'artifact_pins': new_pins})
        data = _read_project_yaml(self.proj_dir)
        self.assertEqual(
            data.get('artifact_pins'),
            new_pins,
            "PATCH must write artifact_pins list to project YAML"
        )

    def test_patch_replaces_existing_artifact_pins(self):
        """PATCH /api/artifacts/{project}/pins replaces existing artifact_pins (not appends)."""
        new_pins = [{'path': 'README.md', 'label': 'Readme'}]
        self._patch(self.slug, {'artifact_pins': new_pins})
        data = _read_project_yaml(self.proj_dir)
        paths = [p.get('path') for p in data.get('artifact_pins', [])]
        self.assertNotIn(
            'old/path.md',
            paths,
            "PATCH must replace existing artifact_pins, not append"
        )

    def test_patch_empty_list_clears_artifact_pins(self):
        """PATCH /api/artifacts/{project}/pins with empty list clears all pins."""
        self._patch(self.slug, {'artifact_pins': []})
        data = _read_project_yaml(self.proj_dir)
        self.assertEqual(
            data.get('artifact_pins', []),
            [],
            "PATCH with empty list must clear artifact_pins"
        )

    def test_patch_returns_200_on_success(self):
        """PATCH /api/artifacts/{project}/pins returns HTTP 200 on success."""
        status, _ = self._patch(self.slug, {'artifact_pins': []})
        self.assertEqual(status, 200, f"PATCH must return 200; got {status}")

    def test_patch_invalid_body_returns_400(self):
        """PATCH /api/artifacts/{project}/pins with non-list artifact_pins returns 400."""
        status, body = self._patch(self.slug, {'artifact_pins': 'not-a-list'})
        self.assertEqual(status, 400, f"PATCH with non-list artifact_pins must return 400; got {status}")

    def test_patch_unknown_project_returns_404(self):
        """PATCH /api/artifacts/{project}/pins with unknown project returns 404."""
        status, body = self._patch('no-such-project', {'artifact_pins': []})
        self.assertEqual(status, 404, f"PATCH with unknown project must return 404; got {status}")


# ── AC8b: PATCH /api/artifacts/{project}/pins saves label correctly ──────────

class TestPatchArtifactPinsSavesLabel(unittest.TestCase):
    """PATCH /api/artifacts/{project}/pins must preserve label from request body."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.slug = 'labeled-project'
        self.proj_dir = _make_project_dir(self.tmp, self.slug)
        tp_home = _make_teaparty_home(
            self.tmp,
            projects=[{'name': self.slug, 'path': self.proj_dir}],
        )
        self.bridge = _make_bridge(tp_home, self.tmp)
        self.bridge._project_path_cache = {self.slug: self.proj_dir}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self, body: dict) -> tuple[int, dict]:
        from unittest.mock import AsyncMock, MagicMock
        bridge = self.bridge

        async def _call():
            request = MagicMock()
            request.match_info = {'project': self.slug}
            request.json = AsyncMock(return_value=body)
            response = await bridge._handle_artifact_pins_patch(request)
            return response.status, json.loads(response.body)

        return _run_async(_call())

    def test_patch_preserves_label_in_yaml(self):
        """PATCH saves the label exactly as provided in the request body."""
        pins = [{'path': 'scripts/run.sh', 'label': 'Custom Label'}]
        self._patch({'artifact_pins': pins})
        data = _read_project_yaml(self.proj_dir)
        saved = data.get('artifact_pins', [])
        labels = [p.get('label') for p in saved]
        self.assertIn(
            'Custom Label',
            labels,
            "PATCH must preserve the label provided in the request body"
        )
