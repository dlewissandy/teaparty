"""Regression: ``list_team_members_handler`` returns membership, not catalog.

A management team config has two distinct lists:

* ``workgroups:`` (top level) — the **catalog** of workgroups whose
  YAML lives under ``management/workgroups/``.  Registered, knowable.
* ``members.workgroups:`` — the **membership**, the workgroups the
  team's lead is authorized to dispatch to.

These differ.  A workgroup can be in the catalog without being a
member.  The list-members tool must report membership; if it walks the
catalog it hands the agent a fictional roster and the agent then tries
to ``Send`` to non-members, which routing correctly refuses — surfacing
as "Routing refused" errors with no obvious cause.

This test pins the contract: only declared members appear in the
result, even when the catalog is larger.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import textwrap
import unittest

from teaparty.mcp.tools.config_crud import list_team_members_handler


class TestListTeamMembersFiltersByMembership(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='tp-list-members-')
        self._tp = os.path.join(self._tmp, '.teaparty')
        os.makedirs(os.path.join(self._tp, 'management', 'workgroups'))
        os.makedirs(os.path.join(self._tp, 'management', 'agents'))

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, relpath: str, content: str) -> None:
        path = os.path.join(self._tp, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(textwrap.dedent(content).lstrip())

    def test_only_member_workgroups_appear_in_result(self):
        """Catalog has 3 workgroups; only 1 is a declared member.  The
        result must contain exactly that one."""
        self._write('management/teaparty.yaml', '''
            name: Management Team
            description: Test
            lead: office-manager
            members:
              projects: []
              workgroups:
              - Configuration
            workgroups:
            - name: Configuration
              config: workgroups/configuration.yaml
            - name: Coding
              config: workgroups/coding.yaml
            - name: Research
              config: workgroups/research.yaml
        ''')
        for name in ('configuration', 'coding', 'research'):
            self._write(f'management/workgroups/{name}.yaml', f'''
                name: {name.capitalize()}
                description: {name} workgroup
                lead: {name}-lead
                members:
                  agents: []
            ''')

        result = json.loads(list_team_members_handler(teaparty_home=self._tp))
        self.assertTrue(result.get('success'))
        wg_leads = [m['name'] for m in result['members']
                    if m.get('role') == 'workgroup-lead']
        self.assertEqual(
            wg_leads, ['configuration-lead'],
            f'Only the workgroup declared in members.workgroups must '
            f'appear; got {wg_leads}.  Catalog ≠ membership.',
        )

    def test_catalog_only_workgroups_excluded(self):
        """A workgroup registered in the catalog but not in
        members.workgroups must NOT appear in the result."""
        self._write('management/teaparty.yaml', '''
            name: Management Team
            description: Test
            lead: office-manager
            members:
              projects: []
              workgroups: []
            workgroups:
            - name: Coding
              config: workgroups/coding.yaml
        ''')
        self._write('management/workgroups/coding.yaml', '''
            name: Coding
            description: implementation
            lead: coding-lead
            members:
              agents: []
        ''')

        result = json.loads(list_team_members_handler(teaparty_home=self._tp))
        self.assertTrue(result.get('success'))
        wg_leads = [m['name'] for m in result['members']
                    if m.get('role') == 'workgroup-lead']
        self.assertEqual(
            wg_leads, [],
            f'Workgroups in the catalog but not in members.workgroups '
            f'must not appear; got {wg_leads}.',
        )


if __name__ == '__main__':
    unittest.main()
