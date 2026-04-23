"""OM's ListProjects and the home page agree on the project list (#422).

Both paths must resolve projects through
``load_management_team(teaparty_home)`` reading
``{teaparty_home}/management/teaparty.yaml`` (plus the
gitignored ``external-projects.yaml`` it merges in).  Any other
file path is a regression.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import yaml


class TestProjectRegistryIsSingleSource(unittest.TestCase):
    """The OM sees exactly what the home page sees."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp422-registry-')
        self._tp = os.path.join(self._dir, '.teaparty')
        os.makedirs(os.path.join(self._tp, 'management'))
        # The canonical file.  Registers TeaParty + joke-book as projects
        # in the management team's catalog.
        with open(os.path.join(self._tp, 'management', 'teaparty.yaml'),
                  'w') as f:
            yaml.dump({
                'name': 'test-mgmt',
                'description': 'test',
                'lead': 'teaparty-lead',
                'projects': [
                    {'name': 'TeaParty', 'path': self._dir},
                    {'name': 'joke-book',
                     'path': '/absolute/path/to/joke-book'},
                ],
                'members': {
                    'agents': [], 'projects': [], 'skills': [],
                    'workgroups': [],
                },
                'workgroups': [],
            }, f)

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_list_projects_handler_returns_every_managed_project(self) -> None:
        from teaparty.mcp.tools.config_crud import list_projects_handler
        import json as _json
        result = _json.loads(list_projects_handler(teaparty_home=self._tp))
        self.assertTrue(result.get('success'), result)
        names = {p['name'] for p in result['projects']}
        self.assertIn('joke-book', names,
                      'OM ListProjects must return joke-book — the home '
                      'page reads the same file and shows it')
        self.assertIn('TeaParty', names)

    def test_a_stray_root_teaparty_yaml_is_ignored(self) -> None:
        """A leftover ``{teaparty_home}/teaparty.yaml`` (the wrong path)
        must never shadow the real management/teaparty.yaml.  #422 removed
        that wrong-path read; this test pins that it stays gone.
        """
        # Plant a misleading root file that ONLY lists TeaParty.
        with open(os.path.join(self._tp, 'teaparty.yaml'), 'w') as f:
            yaml.dump({
                'projects': [{'name': 'TeaParty', 'path': self._dir}],
            }, f)

        from teaparty.mcp.tools.config_crud import list_projects_handler
        import json as _json
        result = _json.loads(list_projects_handler(teaparty_home=self._tp))
        names = {p['name'] for p in result['projects']}
        self.assertIn(
            'joke-book', names,
            'A stray root teaparty.yaml must not shadow the real '
            'management config.  If this assertion fails, something '
            'reintroduced the two-sources-of-truth bug.',
        )

    def test_external_projects_yaml_shows_up_in_list(self) -> None:
        """The machine-local external-projects.yaml is merged in."""
        with open(os.path.join(
                self._tp, 'management', 'external-projects.yaml'), 'w') as f:
            yaml.dump([
                {'name': 'local-only', 'path': '/tmp/local-only'},
            ], f)

        from teaparty.mcp.tools.config_crud import list_projects_handler
        import json as _json
        result = _json.loads(list_projects_handler(teaparty_home=self._tp))
        names = {p['name'] for p in result['projects']}
        self.assertIn('local-only', names,
                      'external-projects.yaml entries must appear in '
                      'ListProjects — same merge the home page sees')

    def test_list_projects_matches_home_page_discover(self) -> None:
        """Both code paths produce identical project name sets."""
        from teaparty.config.config_reader import (
            load_management_team, discover_projects,
        )
        from teaparty.mcp.tools.config_crud import list_projects_handler
        import json as _json

        team = load_management_team(teaparty_home=self._tp)
        home_page_names = {p['name'] for p in discover_projects(team)}

        om_result = _json.loads(list_projects_handler(teaparty_home=self._tp))
        om_names = {p['name'] for p in om_result['projects']}

        self.assertEqual(
            home_page_names, om_names,
            'Home page (discover_projects) and OM (ListProjects) MUST '
            'return the same project name set — they read the same file',
        )


if __name__ == '__main__':
    unittest.main()
