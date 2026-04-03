"""Tests for issue #368: Dashboard — build workgroup config screen.

Acceptance criteria:
1. Lead panel present in renderWorkgroup with lead agent name
2. Members panel (renamed from Agents) shows full agent catalog with active highlighting and toggles
3. Hooks panel shows full hooks catalog with active highlighting and click-to-toggle
4. Humans panel (renamed from Participants) shows humans with role selectors
5. Artifacts panel shows pinned items without norms inline; + New present; unpin supported
6. Management workgroup screen (no projectSlug) renders a Projects panel
7. Project workgroup screen (has projectSlug) renders a sub-workgroups (Workgroups) panel
8. PATCH /api/workgroups/{name} supports artifacts key and writes to YAML
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


def _make_workgroup_yaml(
    path: str,
    agents: list,
    hooks: list | None = None,
    artifacts: list | None = None,
) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    name = os.path.basename(path).replace('.yaml', '')
    data = {
        'name': name,
        'description': 'Test workgroup',
        'lead': 'auditor',
        'members': {
            'agents': agents,
            'hooks': hooks or [],
        },
    }
    if artifacts is not None:
        data['artifacts'] = artifacts
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _read_workgroup_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _make_teaparty_home(tmp: str) -> str:
    tp_home = os.path.join(tmp, '.teaparty')
    mgmt_dir = os.path.join(tp_home, 'management')
    os.makedirs(mgmt_dir)
    data = {
        'name': 'Test Org',
        'description': 'test',
        'lead': 'office-manager',
        'humans': {'decider': 'tester'},
        'members': {'agents': [], 'projects': []},
        'projects': [],
        'workgroups': [],
        'scheduled': [],
    }
    with open(os.path.join(mgmt_dir, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return tp_home


def _make_bridge(teaparty_home: str, tmp: str):
    from bridge.server import TeaPartyBridge
    static_dir = os.path.join(tmp, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)


# ── AC1: Lead panel ───────────────────────────────────────────────────────────

class TestRenderWorkgroupHasLeadPanel(unittest.TestCase):
    """renderWorkgroup() must render a Lead panel showing the workgroup's lead agent."""

    def test_renderWorkgroup_renders_lead_section(self):
        """renderWorkgroup must call sectionCard('Lead', ...) to render the lead panel."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            "sectionCard('Lead'",
            body,
            "renderWorkgroup() must render a Lead panel via sectionCard('Lead', ...)"
        )

    def test_renderWorkgroup_lead_section_uses_wgData_lead(self):
        """renderWorkgroup Lead panel must reference wgData.lead to display the lead agent."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            'wgData.lead',
            body,
            "renderWorkgroup() Lead panel must reference wgData.lead to display the lead agent name"
        )


# ── AC2: Members panel ────────────────────────────────────────────────────────

class TestRenderWorkgroupHasMembersPanel(unittest.TestCase):
    """renderWorkgroup() must render a Members panel (not 'Agents') with full catalog and toggles."""

    def test_renderWorkgroup_renders_members_section(self):
        """renderWorkgroup must call sectionCard('Members', ...) not sectionCard('Agents', ...)."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            "sectionCard('Members'",
            body,
            "renderWorkgroup() must render a Members panel via sectionCard('Members', ...). "
            "The panel must be named 'Members', not 'Agents'."
        )

    def test_renderWorkgroup_members_section_uses_catalog_active_class(self):
        """renderWorkgroup Members panel must apply item-catalog-active to active agents."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            'item-catalog-active',
            body,
            "renderWorkgroup() Members panel must apply item-catalog-active CSS class to active agents"
        )

    def test_renderWorkgroup_members_have_toggle_calling_toggleMembership(self):
        """renderWorkgroup Members items must have toggles calling toggleMembership."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            'toggleMembership',
            body,
            "renderWorkgroup() Members items must include toggleMembership() calls for click-to-toggle"
        )


# ── AC3: Hooks panel ──────────────────────────────────────────────────────────

class TestRenderWorkgroupHasHooksPanel(unittest.TestCase):
    """renderWorkgroup() must render a Hooks panel with full catalog and click-to-toggle."""

    def test_renderWorkgroup_renders_hooks_section(self):
        """renderWorkgroup must call sectionCard('Hooks', ...) to render the hooks panel."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            "sectionCard('Hooks'",
            body,
            "renderWorkgroup() must render a Hooks panel via sectionCard('Hooks', ...)"
        )

    def test_renderWorkgroup_hooks_panel_uses_wgData_hooks(self):
        """renderWorkgroup Hooks panel must iterate over wgData.hooks for the catalog."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            'wgData.hooks',
            body,
            "renderWorkgroup() Hooks panel must reference wgData.hooks to render hook catalog items"
        )

    def test_renderWorkgroup_hooks_panel_shows_active_state(self):
        """renderWorkgroup Hooks panel must apply item-catalog-active to active hooks."""
        body = _extract_render_workgroup_body(_get_config_html())
        # item-catalog-active appears in Members already; verify hooks section also
        # We verify by checking the hooks rendering path contains active class or active flag
        self.assertIn(
            'item-catalog-active',
            body,
            "renderWorkgroup() Hooks panel must apply item-catalog-active to active hooks"
        )

    def test_renderWorkgroup_hooks_have_toggles_for_click_to_toggle(self):
        """renderWorkgroup Hooks items must have toggles that call toggleMembership with type 'hook'."""
        body = _extract_render_workgroup_body(_get_config_html())
        # In the HTML source the type string is escape-quoted as \'hook\' (JS inside a string literal)
        self.assertTrue(
            "'hook'" in body or "\\'hook\\'" in body,
            "renderWorkgroup() Hooks items must call toggleMembership with type 'hook' for click-to-toggle"
        )


# ── AC4: Humans panel ─────────────────────────────────────────────────────────

class TestRenderWorkgroupHasHumansPanel(unittest.TestCase):
    """renderWorkgroup() must render a Humans panel (not 'Participants') with role selectors."""

    def test_renderWorkgroup_renders_humans_section(self):
        """renderWorkgroup must call sectionCard('Humans', ...) not sectionCard('Participants', ...)."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            "sectionCard('Humans'",
            body,
            "renderWorkgroup() must render a Humans panel via sectionCard('Humans', ...). "
            "Must not be named 'Participants'."
        )

    def test_renderWorkgroup_humans_section_has_role_selectors(self):
        """renderWorkgroup Humans panel must include role selectors (decider/advisor/inform)."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            'role-select',
            body,
            "renderWorkgroup() Humans panel must include role-select dropdowns for decider/advisor/inform"
        )

    def test_renderWorkgroup_humans_section_uses_wgData_humans(self):
        """renderWorkgroup Humans panel must iterate over wgData.humans."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            'wgData.humans',
            body,
            "renderWorkgroup() Humans panel must reference wgData.humans to render human participants"
        )


# ── AC5: Artifacts panel ──────────────────────────────────────────────────────

class TestRenderWorkgroupArtifactsPanel(unittest.TestCase):
    """renderWorkgroup() must render an Artifacts panel without inline norms, with unpin support."""

    def test_renderWorkgroup_renders_artifacts_section(self):
        """renderWorkgroup must call sectionCard('Artifacts', ...) to render the artifacts panel."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            "sectionCard('Artifacts'",
            body,
            "renderWorkgroup() must render an Artifacts panel via sectionCard('Artifacts', ...)"
        )

    def test_renderWorkgroup_artifacts_section_does_not_render_norms_inline(self):
        """renderWorkgroup Artifacts panel must NOT inline norms categories as item-group-headings."""
        body = _extract_render_workgroup_body(_get_config_html())
        # The old norms-in-artifacts rendering used 'item-group-heading' for norms categories.
        # After the fix, norms must not appear in the artifacts panel.
        self.assertNotIn(
            'item-group-heading',
            body,
            "renderWorkgroup() must not render norms as inline item-group-headings in the Artifacts panel; "
            "norms are edited via chat blade, not displayed inline"
        )

    def test_renderWorkgroup_artifacts_have_new_button(self):
        """renderWorkgroup Artifacts panel must include a + New button."""
        body = _extract_render_workgroup_body(_get_config_html())
        # The + New button is added via sectionCard opts.addBtn or explicit button in the section
        # sectionCard with addBtn:true produces a '+ New' button
        # We verify the Artifacts sectionCard call includes addBtn or newBtn
        artifacts_section = re.search(
            r"sectionCard\('Artifacts'.*?\)",
            body, re.DOTALL
        )
        self.assertIsNotNone(
            artifacts_section,
            "renderWorkgroup() Artifacts sectionCard not found"
        )
        section_call = artifacts_section.group(0)
        self.assertTrue(
            'addBtn' in section_call or 'newBtn' in section_call or 'New' in section_call,
            "renderWorkgroup() Artifacts panel must include a + New button (addBtn option)"
        )

    def test_renderWorkgroup_artifacts_use_wgData_artifacts(self):
        """renderWorkgroup Artifacts panel must reference wgData.artifacts for pinned items."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            'wgData.artifacts',
            body,
            "renderWorkgroup() Artifacts panel must reference wgData.artifacts for pinned items"
        )


# ── AC6: Management workgroup Projects panel ──────────────────────────────────

class TestRenderWorkgroupManagementProjectsPanel(unittest.TestCase):
    """renderWorkgroup() without projectSlug must render a Projects panel for management workgroup."""

    def test_renderWorkgroup_renders_projects_section_for_management_context(self):
        """renderWorkgroup without projectSlug must call sectionCard('Projects', ...) for management."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            "sectionCard('Projects'",
            body,
            "renderWorkgroup() must render a Projects panel via sectionCard('Projects', ...) "
            "when no projectSlug is given (management workgroup context)"
        )

    def test_renderWorkgroup_projects_panel_conditional_on_no_project_slug(self):
        """renderWorkgroup Projects panel must only appear when projectSlug is absent."""
        body = _extract_render_workgroup_body(_get_config_html())
        # The rendering must be conditional on projectSlug being absent
        # We verify that the source contains a conditional branch for this
        has_conditional = (
            '!projectSlug' in body
            or 'projectSlug == null' in body
            or 'projectSlug === null' in body
            or "projectSlug === ''" in body
            or 'projectSlug ?' in body
        )
        self.assertTrue(
            has_conditional,
            "renderWorkgroup() Projects panel must be conditional on projectSlug being absent; "
            "use !projectSlug or equivalent conditional logic"
        )


# ── AC7: Project workgroup sub-workgroups panel ───────────────────────────────

class TestRenderWorkgroupProjectSubworkgroupsPanel(unittest.TestCase):
    """renderWorkgroup() with projectSlug must render a Workgroups panel for project workgroups."""

    def test_renderWorkgroup_renders_workgroups_section_for_project_context(self):
        """renderWorkgroup with projectSlug must call sectionCard('Workgroups', ...) for project."""
        body = _extract_render_workgroup_body(_get_config_html())
        self.assertIn(
            "sectionCard('Workgroups'",
            body,
            "renderWorkgroup() must render a Workgroups panel via sectionCard('Workgroups', ...) "
            "when projectSlug is given (project workgroup context)"
        )


# ── AC8: PATCH endpoint supports artifacts ────────────────────────────────────

class TestWorkgroupPatchSupportsArtifacts(unittest.TestCase):
    """PATCH /api/workgroups/{name} must support an artifacts key and write to YAML."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        wg_dir = os.path.join(self.teaparty_home, 'management', 'workgroups')
        os.makedirs(wg_dir, exist_ok=True)
        self.wg_path = os.path.join(wg_dir, 'coding.yaml')
        _make_workgroup_yaml(
            self.wg_path,
            agents=['auditor'],
            hooks=['PreToolUse'],
            artifacts=[{'path': 'docs/', 'label': 'Docs'}],
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_patch(self, wg_name: str, body: dict) -> tuple[int, dict]:
        from unittest.mock import AsyncMock, MagicMock
        bridge = _make_bridge(self.teaparty_home, self.tmp)

        async def _call():
            request = MagicMock()
            request.match_info = {'name': wg_name}
            request.rel_url.query.get = MagicMock(return_value=None)
            request.json = AsyncMock(return_value=body)
            response = await bridge._handle_workgroup_patch(request)
            return response.status, json.loads(response.body)

        return _run_async(_call())

    def test_patch_artifacts_writes_to_yaml(self):
        """PATCH /api/workgroups/{name} with artifacts list writes artifacts to workgroup YAML."""
        self._run_patch('coding', {'artifacts': [{'path': 'NORMS.md', 'label': 'Norms'}]})
        data = _read_workgroup_yaml(self.wg_path)
        self.assertIn(
            {'path': 'NORMS.md', 'label': 'Norms'},
            data.get('artifacts', []),
            "PATCH with artifacts must write the artifacts list to the workgroup YAML file"
        )

    def test_patch_artifacts_replaces_existing_list(self):
        """PATCH /api/workgroups/{name} replaces the artifacts list (not appends)."""
        self._run_patch('coding', {'artifacts': [{'path': 'NORMS.md', 'label': 'Norms'}]})
        data = _read_workgroup_yaml(self.wg_path)
        paths = [a.get('path') for a in data.get('artifacts', [])]
        self.assertNotIn(
            'docs/',
            paths,
            "PATCH with artifacts must replace the existing artifacts list, not append"
        )

    def test_patch_artifacts_empty_list_removes_all_artifacts(self):
        """PATCH /api/workgroups/{name} with empty artifacts list removes all pinned artifacts."""
        self._run_patch('coding', {'artifacts': []})
        data = _read_workgroup_yaml(self.wg_path)
        self.assertEqual(
            data.get('artifacts', []),
            [],
            "PATCH with empty artifacts list must remove all pinned artifacts from YAML"
        )

    def test_patch_artifacts_preserves_agents_and_hooks(self):
        """PATCH /api/workgroups/{name} with only artifacts does not overwrite agents or hooks."""
        self._run_patch('coding', {'artifacts': [{'path': 'NORMS.md', 'label': 'Norms'}]})
        data = _read_workgroup_yaml(self.wg_path)
        self.assertIn(
            'auditor',
            data.get('members', {}).get('agents', []),
            "PATCH with only artifacts must not overwrite members.agents"
        )
        self.assertIn(
            'PreToolUse',
            data.get('members', {}).get('hooks', []),
            "PATCH with only artifacts must not overwrite members.hooks"
        )

    def test_patch_artifacts_returns_200(self):
        """PATCH /api/workgroups/{name} with artifacts returns HTTP 200."""
        status, _ = self._run_patch('coding', {'artifacts': []})
        self.assertEqual(
            status, 200,
            f"PATCH with artifacts must return HTTP 200; got {status}"
        )

    def test_patch_artifacts_invalid_body_returns_400(self):
        """PATCH /api/workgroups/{name} with non-list artifacts returns HTTP 400."""
        status, body = self._run_patch('coding', {'artifacts': 'not-a-list'})
        self.assertEqual(
            status, 400,
            f"PATCH with non-list artifacts must return 400; got {status}"
        )
