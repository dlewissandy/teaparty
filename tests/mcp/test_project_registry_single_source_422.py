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


class TestAddProjectMakesItDispatchable(unittest.TestCase):
    """After ``add_project``, OM's Send must route to the new project's lead.

    The bug this pins: ``members_projects`` and ``projects`` used to be
    two separate lists.  ``add_project`` only wrote to the catalog, not
    the members roster.  ``resolve_launch_placement`` walked the
    roster, so a freshly registered project was visible on the home
    page (catalog) but not dispatchable from OM (roster).  #422
    collapsed the two into one: registering a project IS adding it to
    the roster.  This test proves registration makes the lead
    dispatchable in the same flow.
    """

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp422-dispatchable-')
        self._tp = os.path.join(self._dir, '.teaparty')
        os.makedirs(os.path.join(self._tp, 'management'))
        # Management team with a human decider — required by add_project's
        # decider resolution path.
        with open(os.path.join(self._tp, 'management', 'teaparty.yaml'),
                  'w') as f:
            yaml.dump({
                'name': 'test-mgmt',
                'description': 'test',
                'lead': 'office-manager',
                'humans': [
                    {'name': 'operator', 'role': 'decider',
                     'email': 'op@example.com'},
                ],
                'projects': [],
                'members': {},
                'workgroups': [],
            }, f)

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_add_project_then_resolve_launch_placement_succeeds(self) -> None:
        """The full registration-to-dispatch flow works end to end."""
        from teaparty.config.config_reader import add_project
        from teaparty.config.roster import resolve_launch_placement

        project_dir = os.path.join(self._dir, 'widgets')
        os.makedirs(project_dir)

        add_project(
            name='widgets',
            path=project_dir,
            teaparty_home=self._tp,
        )

        # The project lead must resolve — this was the broken path.
        # Before #422 this raised LaunchCwdNotResolved because
        # add_project didn't touch members.projects, so
        # resolve_launch_placement couldn't find 'widgets-lead'.
        launch_cwd, scope = resolve_launch_placement(
            'widgets-lead', self._tp,
        )

        self.assertEqual(
            scope, 'project',
            "widgets-lead must resolve to 'project' scope — it lives "
            'in the widgets project directory',
        )
        self.assertEqual(
            os.path.realpath(launch_cwd), os.path.realpath(project_dir),
            'widgets-lead must launch in the widgets project directory',
        )

    def test_added_project_appears_in_om_roster(self) -> None:
        """The OM's derived roster must include the new project lead."""
        from teaparty.config.config_reader import add_project
        from teaparty.config.roster import derive_roster

        project_dir = os.path.join(self._dir, 'gadgets')
        os.makedirs(project_dir)

        add_project(
            name='gadgets',
            path=project_dir,
            teaparty_home=self._tp,
        )

        roster = derive_roster(teaparty_home=self._tp)
        member_names = {m.name for m in roster.members}
        self.assertIn(
            'gadgets-lead', member_names,
            'Freshly registered projects must appear in the OM '
            'roster — that is what makes them dispatchable from chat',
        )

    def test_members_projects_is_derived_from_catalog(self) -> None:
        """``team.members_projects`` is the catalog's name list, nothing more.

        If anyone tries to reintroduce a separate on-disk list, this
        test fails.  The property is the contract: catalog is truth.
        """
        from teaparty.config.config_reader import (
            add_project, load_management_team,
        )

        project_dir = os.path.join(self._dir, 'sprockets')
        os.makedirs(project_dir)

        add_project(
            name='sprockets',
            path=project_dir,
            teaparty_home=self._tp,
        )

        team = load_management_team(teaparty_home=self._tp)
        catalog_names = [p['name'] for p in team.projects]
        self.assertEqual(
            sorted(team.members_projects), sorted(catalog_names),
            'members_projects must equal the catalog name list — '
            'any divergence is the two-source bug coming back',
        )
        self.assertIn('sprockets', team.members_projects)


if __name__ == '__main__':
    unittest.main()
