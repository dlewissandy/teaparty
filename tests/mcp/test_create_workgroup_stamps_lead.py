"""CreateWorkgroup must auto-stamp its lead from the unified template.

When a workgroup is created via the CreateWorkgroup MCP tool, the lead
agent ``{name}-lead`` is stamped with a canonical shape:

- frontmatter ``tools:`` is the unified 8-item workgroup-lead whitelist
  (Read/Glob/Grep/Write/Edit + Send/CloseConversation/AskQuestion)
- frontmatter ``skills:`` includes ``digest``
- the body carries the six-step coordination template (decompose /
  delegate / consolidate / mediate / reconcile / decide done / interface)
- no ``settings.yaml`` is written (settings.yaml is reserved for folder
  permissions; the tool whitelist lives in the frontmatter)

These tests lock that in so legacy drift can't reappear.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import yaml

from teaparty.config.config_reader import read_agent_frontmatter
from teaparty.mcp.tools.config_crud import (
    _WORKGROUP_LEAD_TOOLS,
    create_workgroup_handler,
)


_EXPECTED_TOOLS = {
    'Read', 'Glob', 'Grep', 'Write', 'Edit',
    'mcp__teaparty-config__Send',
    'mcp__teaparty-config__CloseConversation',
    'mcp__teaparty-config__AskQuestion',
}


class CreateWorkgroupStampsLeadTest(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='teaparty-wg-stamp-')
        os.makedirs(os.path.join(self._tmp, '.teaparty', 'management'))
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def _run(self, name: str, description: str = '') -> str:
        create_workgroup_handler(
            name=name,
            description=description,
            teaparty_home=os.path.join(self._tmp, '.teaparty'),
            project_root=self._tmp,
        )
        return os.path.join(
            self._tmp, '.teaparty', 'management', 'agents',
            f'{name}-lead', 'agent.md',
        )

    def test_unified_tool_list_is_the_lean_eight(self) -> None:
        """The tool constant used by the stamper matches the 8-item whitelist."""
        actual = {t.strip() for t in _WORKGROUP_LEAD_TOOLS.split(',')}
        self.assertEqual(
            actual, _EXPECTED_TOOLS,
            f'_WORKGROUP_LEAD_TOOLS drifted: {sorted(actual)} vs '
            f'expected {sorted(_EXPECTED_TOOLS)}',
        )

    def test_lead_agent_md_is_stamped(self) -> None:
        """After CreateWorkgroup, {name}-lead/agent.md exists."""
        lead_path = self._run('scratch')
        self.assertTrue(
            os.path.isfile(lead_path),
            f'lead agent.md not stamped at {lead_path}',
        )

    def test_lead_settings_yaml_has_unified_tools(self) -> None:
        """The stamped lead's settings.yaml permissions.allow matches the unified list.

        Tool assignments live in settings.yaml (the field Claude Code reads
        via ``--settings`` for MCP auto-approval), not in agent.md frontmatter.
        """
        import yaml as _yaml
        lead_path = self._run('scratch')
        settings_path = os.path.join(os.path.dirname(lead_path), 'settings.yaml')
        self.assertTrue(
            os.path.isfile(settings_path),
            f'stamped lead missing settings.yaml at {settings_path}',
        )
        with open(settings_path) as f:
            settings = _yaml.safe_load(f) or {}
        allow = (settings.get('permissions') or {}).get('allow') or []
        tools = set(allow)
        self.assertEqual(
            tools, _EXPECTED_TOOLS,
            f'stamped lead has settings.yaml allow {sorted(tools)}, '
            f'expected {sorted(_EXPECTED_TOOLS)}',
        )

    def test_lead_frontmatter_has_digest_skill(self) -> None:
        """The stamped lead's skills: includes digest."""
        lead_path = self._run('scratch')
        fm = read_agent_frontmatter(lead_path)
        skills = fm.get('skills') or []
        self.assertIn(
            'digest', skills,
            f'stamped lead skills {skills} missing digest',
        )

    def test_lead_body_uses_unified_template(self) -> None:
        """The lead's body contains the six-step coordination template markers."""
        lead_path = self._run('analytics',
                              'Statistical analysis and data visualization.')
        with open(lead_path) as f:
            content = f.read()
        for marker in (
            '**0. Strategic plan.**',
            '**1. Delegate.**',
            '**2. Consolidate.**',
            '**3. Mediate.**',
            '**4. Reconcile.**',
            '**5. Decide done.**',
            '**6. Interface externally.**',
        ):
            self.assertIn(
                marker, content,
                f'stamped lead body missing coordination step: {marker!r}',
            )

    def test_lead_body_embeds_workgroup_description(self) -> None:
        """The Team scope section carries the workgroup's description verbatim."""
        desc = 'Prose improvement — mechanics, fact-checking, style, and voice.'
        lead_path = self._run('editorial', desc)
        with open(lead_path) as f:
            content = f.read()
        self.assertIn(desc, content)
        self.assertIn('## Team scope', content)

    def test_settings_yaml_is_created(self) -> None:
        """settings.yaml IS stamped — it's the source of truth for tool permissions."""
        lead_path = self._run('scratch')
        settings_path = os.path.join(os.path.dirname(lead_path), 'settings.yaml')
        self.assertTrue(
            os.path.exists(settings_path),
            f'stamped lead missing settings.yaml at {settings_path} — '
            f'tool assignments live in settings.yaml permissions.allow',
        )

    def test_lead_frontmatter_has_no_tools(self) -> None:
        """Tools live in settings.yaml, not agent.md frontmatter."""
        lead_path = self._run('scratch')
        fm = read_agent_frontmatter(lead_path)
        self.assertNotIn(
            'tools', fm,
            f'stamped lead frontmatter still has tools: {fm.get("tools")!r} — '
            f'tools belong in settings.yaml permissions.allow',
        )

    def test_existing_lead_is_not_overwritten(self) -> None:
        """If {name}-lead/agent.md already exists, stamping is a no-op."""
        lead_path = self._run('scratch')
        with open(lead_path) as f:
            first_content = f.read()

        # Re-run CreateWorkgroup with different description — must not overwrite.
        create_workgroup_handler(
            name='scratch',
            description='Different description that should NOT land in the lead.',
            teaparty_home=os.path.join(self._tmp, '.teaparty'),
            project_root=self._tmp,
        )
        with open(lead_path) as f:
            second_content = f.read()
        self.assertEqual(
            first_content, second_content,
            'stamping overwrote an existing lead — user customizations lost',
        )

    def test_non_default_lead_is_not_stamped(self) -> None:
        """If the caller specifies a lead other than {name}-lead, don't stamp."""
        create_workgroup_handler(
            name='special',
            description='A workgroup led by someone else.',
            lead='office-manager',
            teaparty_home=os.path.join(self._tmp, '.teaparty'),
            project_root=self._tmp,
        )
        unexpected = os.path.join(
            self._tmp, '.teaparty', 'management', 'agents',
            'special-lead', 'agent.md',
        )
        self.assertFalse(
            os.path.exists(unexpected),
            f'stamping created {unexpected} even though the workgroup '
            f'specified a non-default lead',
        )

    def test_workgroup_yaml_still_created(self) -> None:
        """The workgroup YAML itself is still written as before."""
        self._run('scratch', 'A tiny team.')
        yaml_path = os.path.join(
            self._tmp, '.teaparty', 'management', 'workgroups', 'scratch.yaml',
        )
        self.assertTrue(os.path.isfile(yaml_path))
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['name'], 'scratch')
        self.assertEqual(data['description'], 'A tiny team.')
        self.assertEqual(data['lead'], 'scratch-lead')


if __name__ == '__main__':
    unittest.main()
