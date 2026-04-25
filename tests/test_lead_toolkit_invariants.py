"""Lead toolkit invariants — Send and ListTeamMembers travel together.

If an agent can ``Send`` to teammates, they must also be able to
``ListTeamMembers`` to know who their teammates are.  The two tools
are a paired primitive: one without the other is a usability bug.

Pinned here:
1. Every agent in ``.teaparty/**/settings.yaml`` whose ``permissions.allow``
   contains ``mcp__teaparty-config__Send`` ALSO contains
   ``mcp__teaparty-config__ListTeamMembers``.
2. Both scaffolding constants — ``_WORKGROUP_LEAD_TOOLS`` (workgroup-lead
   stamper) and ``PROJECT_LEAD_TOOLS`` (project-lead stamper) — include
   ``ListTeamMembers``.  Future leads created via these paths inherit
   the pair automatically.
3. UI tool/skill edits land in settings.yaml / agent.md and are read
   fresh by ``compose_launch_config`` at every launch — no caching.
"""
from __future__ import annotations

import os
import tempfile
import unittest

import yaml


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _canonical_agent_settings_paths() -> list[str]:
    """Walk every CANONICAL agent settings.yaml under .teaparty/.

    Canonical = ``.teaparty/{scope}/agents/<name>/settings.yaml``.  We
    skip per-launch / per-session generated config dirs (under
    ``agents/<name>/<qualifier>/`` or ``sessions/`` or ``worktree``)
    because those are output artifacts, not source-of-truth settings.
    """
    paths: list[str] = []
    for scope_root in (
        os.path.join(REPO_ROOT, '.teaparty', 'management', 'agents'),
        os.path.join(REPO_ROOT, '.teaparty', 'project', 'agents'),
    ):
        if not os.path.isdir(scope_root):
            continue
        for entry in sorted(os.listdir(scope_root)):
            agent_dir = os.path.join(scope_root, entry)
            settings = os.path.join(agent_dir, 'settings.yaml')
            if os.path.isfile(settings):
                paths.append(settings)
    return paths


def _allow_set(settings_path: str) -> set[str]:
    with open(settings_path) as f:
        data = yaml.safe_load(f) or {}
    return set((data.get('permissions') or {}).get('allow') or [])


class TestSendImpliesListTeamMembers(unittest.TestCase):
    """Any agent that can Send must also be able to ListTeamMembers."""

    def test_paired_in_every_settings_yaml(self) -> None:
        offenders: list[str] = []
        for path in _canonical_agent_settings_paths():
            allow = _allow_set(path)
            if 'mcp__teaparty-config__Send' in allow:
                if 'mcp__teaparty-config__ListTeamMembers' not in allow:
                    rel = os.path.relpath(path, REPO_ROOT)
                    offenders.append(rel)
        self.assertFalse(
            offenders,
            'These agents have Send but not ListTeamMembers — they '
            'can dispatch without being able to enumerate their team:\n'
            + '\n'.join(f'  {p}' for p in offenders),
        )


class TestScaffoldingIncludesListTeamMembers(unittest.TestCase):
    """New leads created via the stamper paths get the paired toolkit."""

    def test_workgroup_lead_scaffold_includes_listteammembers(self) -> None:
        from teaparty.mcp.tools.config_crud import _WORKGROUP_LEAD_TOOLS
        tools = {t.strip() for t in _WORKGROUP_LEAD_TOOLS.split(',')}
        self.assertIn(
            'mcp__teaparty-config__Send', tools,
            '_WORKGROUP_LEAD_TOOLS missing Send — the toolkit is broken'
        )
        self.assertIn(
            'mcp__teaparty-config__ListTeamMembers', tools,
            'Future workgroup leads must inherit ListTeamMembers '
            'automatically; the scaffold constant must include it',
        )

    def test_project_lead_scaffold_includes_listteammembers(self) -> None:
        from teaparty.config.config_reader import PROJECT_LEAD_TOOLS
        self.assertIn(
            'mcp__teaparty-config__Send', PROJECT_LEAD_TOOLS,
        )
        self.assertIn(
            'mcp__teaparty-config__ListTeamMembers', PROJECT_LEAD_TOOLS,
            'Future project leads must inherit ListTeamMembers '
            'automatically; PROJECT_LEAD_TOOLS must include it',
        )


class TestSettingsYamlIsReadFreshOnEveryLaunch(unittest.TestCase):
    """UI tool edits land in settings.yaml and are picked up at next launch.

    Pins the no-caching property: ``compose_launch_config`` reads
    ``settings.yaml`` from disk every call.  If a future change adds an
    in-memory cache between PATCH and launch, this test fails.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='lead-toolkit-')
        self._tp = os.path.join(self._tmp, '.teaparty')
        self._scope = 'management'
        self._agent = 'fake-lead'
        agent_dir = os.path.join(
            self._tp, self._scope, 'agents', self._agent,
        )
        os.makedirs(agent_dir)
        self._settings_path = os.path.join(agent_dir, 'settings.yaml')
        # Bare agent.md so the launcher's frontmatter read finds something.
        with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
            f.write('---\nname: fake-lead\n---\nplaceholder\n')

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_settings(self, allow: list[str]) -> None:
        with open(self._settings_path, 'w') as f:
            yaml.dump({'permissions': {'allow': allow}}, f)

    def _read_composed_allow(self, config_dir: str) -> set[str]:
        import json
        settings_json = os.path.join(config_dir, 'settings.json')
        with open(settings_json) as f:
            data = json.load(f)
        return set((data.get('permissions') or {}).get('allow') or [])

    def test_settings_yaml_change_takes_effect_immediately(self) -> None:
        """compose_launch_config writes a settings.json that mirrors
        the CURRENT settings.yaml — not a cached snapshot."""
        from teaparty.runners.launcher import compose_launch_config

        # Initial state: minimal toolkit.
        self._write_settings(['Read', 'mcp__teaparty-config__Send'])
        config_dir_a = os.path.join(self._tmp, 'launch-a')
        compose_launch_config(
            config_dir=config_dir_a,
            agent_name=self._agent,
            scope=self._scope,
            teaparty_home=self._tp,
        )
        allow_a = self._read_composed_allow(config_dir_a)
        self.assertNotIn(
            'mcp__teaparty-config__ListTeamMembers', allow_a,
            'precondition: initial settings.yaml does not have it',
        )

        # Simulate a UI PATCH that adds ListTeamMembers.
        self._write_settings([
            'Read', 'mcp__teaparty-config__Send',
            'mcp__teaparty-config__ListTeamMembers',
        ])

        # Next launch composes from disk — must see the new tool.
        config_dir_b = os.path.join(self._tmp, 'launch-b')
        compose_launch_config(
            config_dir=config_dir_b,
            agent_name=self._agent,
            scope=self._scope,
            teaparty_home=self._tp,
        )
        allow_b = self._read_composed_allow(config_dir_b)
        self.assertIn(
            'mcp__teaparty-config__ListTeamMembers', allow_b,
            'compose_launch_config must read settings.yaml fresh — '
            'a UI tool edit did not propagate to settings.json',
        )


if __name__ == '__main__':
    unittest.main()
