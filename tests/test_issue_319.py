#!/usr/bin/env python3
"""Tests for Issue #319: Fix teaparty_home — repo-local config, correct path passing, bridge/static/.

Acceptance criteria:
1. bridge/__main__.py accepts --teaparty-home CLI arg; no hardcoded ~/.teaparty
2. teaparty.sh passes --teaparty-home explicitly
3. load_project_team() reads from .teaparty.local/project.yaml by default
4. _scaffold_project_yaml() creates .teaparty.local/project.yaml
5. bridge/static/ exists at repo root and is served by bridge/__main__.py
6. .teaparty/teaparty.yaml has TeaParty in teams:, darrell in humans:,
   lead: office-manager, and Configuration workgroup
7. .teaparty.local/project.yaml exists at repo root
8. resolve_workgroups uses .teaparty.local/workgroups/ for project-level overrides
"""
import inspect
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_REPO_ROOT = Path(__file__).parent.parent


# ── 1. bridge/__main__.py accepts --teaparty-home ─────────────────────────────

class TestBridgeMainTeapartyHome(unittest.TestCase):
    """bridge/__main__.py must accept --teaparty-home CLI arg, not hardcode ~/.teaparty."""

    def _get_main_source(self) -> str:
        path = _REPO_ROOT / 'bridge' / '__main__.py'
        self.assertTrue(path.exists(), f'bridge/__main__.py not found at {path}')
        return path.read_text()

    def test_no_hardcoded_home_teaparty(self):
        """bridge/__main__.py must not hardcode ~/.teaparty as teaparty_home."""
        source = self._get_main_source()
        self.assertNotIn(
            "~/.teaparty",
            source,
            'bridge/__main__.py must not hardcode ~/.teaparty; '
            'teaparty_home must come from --teaparty-home CLI arg',
        )

    def test_teaparty_home_cli_arg_defined(self):
        """bridge/__main__.py must define --teaparty-home argument."""
        source = self._get_main_source()
        self.assertIn(
            '--teaparty-home',
            source,
            'bridge/__main__.py must define --teaparty-home CLI argument',
        )

    def test_teaparty_home_passed_to_bridge(self):
        """bridge/__main__.py must pass teaparty_home from args to TeaPartyBridge."""
        source = self._get_main_source()
        # The arg value (args.teaparty_home) must be passed to TeaPartyBridge
        self.assertIn(
            'args.teaparty_home',
            source,
            'bridge/__main__.py must pass args.teaparty_home to TeaPartyBridge',
        )

    def test_default_points_to_repo_local_teaparty(self):
        """Default teaparty_home must be repo-local .teaparty/, not user home."""
        source = self._get_main_source()
        # Must use project_root-based default, not expanduser('~/.teaparty')
        self.assertNotIn(
            "expanduser('~/.teaparty')",
            source,
            'bridge/__main__.py must not use expanduser for ~/.teaparty default',
        )
        self.assertNotIn(
            'expanduser("~/.teaparty")',
            source,
            'bridge/__main__.py must not use expanduser for ~/.teaparty default',
        )


# ── 2. teaparty.sh passes --teaparty-home explicitly ─────────────────────────

class TestTeapartyShPassesHome(unittest.TestCase):
    """teaparty.sh must pass --teaparty-home explicitly to the python command."""

    def _get_script_source(self) -> str:
        path = _REPO_ROOT / 'teaparty.sh'
        self.assertTrue(path.exists(), f'teaparty.sh not found at {path}')
        return path.read_text()

    def test_teaparty_home_passed_in_script(self):
        """teaparty.sh must pass --teaparty-home to python -m bridge."""
        source = self._get_script_source()
        self.assertIn(
            '--teaparty-home',
            source,
            'teaparty.sh must pass --teaparty-home to the bridge command',
        )

    def test_teaparty_home_is_repo_local(self):
        """teaparty.sh must derive teaparty_home from the script's own directory."""
        source = self._get_script_source()
        # Must reference BASH_SOURCE[0] or dirname for repo-relative path
        self.assertIn(
            'BASH_SOURCE',
            source,
            'teaparty.sh must use BASH_SOURCE to derive the repo-local .teaparty/ path',
        )


# ── 3. load_project_team reads from .teaparty.local/ by default ───────────────

class TestLoadProjectTeamLocalPath(unittest.TestCase):
    """load_project_team() must read from .teaparty.local/project.yaml by default."""

    def _make_project_dir(self, project_yaml: str) -> str:
        """Create a temp project dir with .teaparty.local/project.yaml."""
        proj = tempfile.mkdtemp()
        tp_local = os.path.join(proj, '.teaparty.local')
        os.makedirs(tp_local)
        os.makedirs(os.path.join(proj, '.git'))
        os.makedirs(os.path.join(proj, '.claude'))
        with open(os.path.join(tp_local, 'project.yaml'), 'w') as f:
            f.write(project_yaml)
        return proj

    def test_loads_from_teaparty_local(self):
        """load_project_team reads from .teaparty.local/project.yaml."""
        from orchestrator.config_reader import load_project_team
        yaml_text = 'name: My Project\nlead: lead\ndecider: boss\n'
        proj = self._make_project_dir(yaml_text)
        team = load_project_team(proj)
        self.assertEqual(team.name, 'My Project')

    def test_raises_when_only_old_path_exists(self):
        """load_project_team raises FileNotFoundError if only .teaparty/project.yaml exists."""
        from orchestrator.config_reader import load_project_team
        proj = tempfile.mkdtemp()
        # Put project.yaml in old location (.teaparty/) only
        old_tp = os.path.join(proj, '.teaparty')
        os.makedirs(old_tp)
        with open(os.path.join(old_tp, 'project.yaml'), 'w') as f:
            f.write('name: Old Project\nlead: lead\ndecider: boss\n')
        with self.assertRaises(FileNotFoundError):
            load_project_team(proj)

    def test_config_path_override_still_works(self):
        """Explicit config_path arg bypasses the default .teaparty.local/ path."""
        from orchestrator.config_reader import load_project_team
        proj = tempfile.mkdtemp()
        explicit = os.path.join(proj, 'custom', 'project.yaml')
        os.makedirs(os.path.dirname(explicit))
        with open(explicit, 'w') as f:
            f.write('name: Custom Project\nlead: lead\ndecider: boss\n')
        team = load_project_team(proj, config_path=explicit)
        self.assertEqual(team.name, 'Custom Project')

    def test_default_path_in_source_is_teaparty_local(self):
        """config_reader.py default path must reference .teaparty.local, not .teaparty."""
        import inspect
        from orchestrator import config_reader
        source = inspect.getsource(config_reader.load_project_team)
        self.assertIn(
            '.teaparty.local',
            source,
            'load_project_team default path must reference .teaparty.local',
        )
        self.assertNotIn(
            "'.teaparty', 'project.yaml'",
            source,
            'load_project_team must not use .teaparty/project.yaml as default',
        )


# ── 4. _scaffold_project_yaml creates .teaparty.local/ ───────────────────────

class TestScaffoldProjectYaml(unittest.TestCase):
    """_scaffold_project_yaml must create .teaparty.local/project.yaml."""

    def test_scaffold_creates_teaparty_local(self):
        """add_project scaffolds .teaparty.local/project.yaml, not .teaparty/project.yaml."""
        from orchestrator.config_reader import add_project, load_management_team
        import yaml

        proj = tempfile.mkdtemp()
        os.makedirs(os.path.join(proj, '.git'))
        os.makedirs(os.path.join(proj, '.claude'))

        home = tempfile.mkdtemp()
        tp_dir = os.path.join(home, '.teaparty')
        os.makedirs(tp_dir)
        with open(os.path.join(tp_dir, 'teaparty.yaml'), 'w') as f:
            yaml.dump({'name': 'Org', 'lead': 'boss', 'decider': 'boss', 'teams': []}, f)

        add_project('TestProj', proj, teaparty_home=tp_dir)

        local_yaml = os.path.join(proj, '.teaparty.local', 'project.yaml')
        self.assertTrue(
            os.path.exists(local_yaml),
            f'.teaparty.local/project.yaml was not created at {local_yaml}',
        )

    def test_scaffold_does_not_create_old_path(self):
        """add_project must not create .teaparty/project.yaml."""
        from orchestrator.config_reader import add_project
        import yaml

        proj = tempfile.mkdtemp()
        os.makedirs(os.path.join(proj, '.git'))
        os.makedirs(os.path.join(proj, '.claude'))

        home = tempfile.mkdtemp()
        tp_dir = os.path.join(home, '.teaparty')
        os.makedirs(tp_dir)
        with open(os.path.join(tp_dir, 'teaparty.yaml'), 'w') as f:
            yaml.dump({'name': 'Org', 'lead': 'boss', 'decider': 'boss', 'teams': []}, f)

        add_project('TestProj', proj, teaparty_home=tp_dir)

        old_yaml = os.path.join(proj, '.teaparty', 'project.yaml')
        self.assertFalse(
            os.path.exists(old_yaml),
            '.teaparty/project.yaml must not be created; scaffold goes to .teaparty.local/',
        )

    def test_scaffold_not_overwritten_if_exists(self):
        """_scaffold_project_yaml must not overwrite existing .teaparty.local/project.yaml."""
        from orchestrator.config_reader import add_project
        import yaml

        proj = tempfile.mkdtemp()
        os.makedirs(os.path.join(proj, '.git'))
        os.makedirs(os.path.join(proj, '.claude'))
        # Pre-create with custom content
        local_dir = os.path.join(proj, '.teaparty.local')
        os.makedirs(local_dir)
        existing = os.path.join(local_dir, 'project.yaml')
        with open(existing, 'w') as f:
            f.write('name: PreExisting\nlead: x\ndecider: x\n')

        home = tempfile.mkdtemp()
        tp_dir = os.path.join(home, '.teaparty')
        os.makedirs(tp_dir)
        with open(os.path.join(tp_dir, 'teaparty.yaml'), 'w') as f:
            yaml.dump({'name': 'Org', 'lead': 'boss', 'decider': 'boss', 'teams': []}, f)

        add_project('TestProj', proj, teaparty_home=tp_dir)

        with open(existing) as f:
            content = f.read()
        self.assertIn('PreExisting', content)


# ── 5. bridge/static/ exists and is served ───────────────────────────────────

class TestBridgeStaticDir(unittest.TestCase):
    """bridge/static/ must exist at repo root and be referenced by bridge/__main__.py."""

    def test_bridge_static_dir_exists(self):
        """bridge/static/ must exist at repo root."""
        static_dir = _REPO_ROOT / 'bridge' / 'static'
        self.assertTrue(
            static_dir.is_dir(),
            f'bridge/static/ not found at {static_dir}',
        )

    def test_bridge_static_has_index_html(self):
        """bridge/static/index.html must exist."""
        index = _REPO_ROOT / 'bridge' / 'static' / 'index.html'
        self.assertTrue(
            index.exists(),
            f'bridge/static/index.html not found at {index}',
        )

    def test_bridge_main_references_bridge_static(self):
        """bridge/__main__.py static_dir must point to bridge/static/."""
        source = (_REPO_ROOT / 'bridge' / '__main__.py').read_text()
        self.assertIn(
            "bridge', 'static'",
            source,
            "bridge/__main__.py must reference bridge/static/ as static_dir",
        )


# ── 6. .teaparty/teaparty.yaml global config invariants ──────────────────────

class TestTeapartyYamlInvariants(unittest.TestCase):
    """The committed .teaparty/teaparty.yaml must satisfy the global invariants."""

    def _load_yaml(self):
        import yaml
        path = _REPO_ROOT / '.teaparty' / 'teaparty.yaml'
        self.assertTrue(path.exists(), f'.teaparty/teaparty.yaml not found at {path}')
        with open(path) as f:
            return yaml.safe_load(f)

    def test_lead_is_office_manager(self):
        """teaparty.yaml must have lead: office-manager."""
        data = self._load_yaml()
        self.assertEqual(
            data.get('lead'),
            'office-manager',
            'teaparty.yaml must have lead: office-manager',
        )

    def test_teaparty_registered_in_teams(self):
        """teaparty.yaml must register TeaParty itself in teams:."""
        data = self._load_yaml()
        teams = data.get('teams', [])
        self.assertTrue(
            any(t['name'] == 'TeaParty' for t in teams),
            f'teaparty.yaml must register TeaParty in teams:; found: {[t["name"] for t in teams]}',
        )

    def test_no_stale_projects_poc_in_teams(self):
        """teaparty.yaml must not contain stale projects/POC entry."""
        data = self._load_yaml()
        teams = data.get('teams', [])
        stale = [t for t in teams if 'projects/POC' in t.get('path', '') or t.get('name') == 'POC']
        self.assertEqual(
            stale,
            [],
            f'teaparty.yaml must not have stale projects/POC entry; found: {stale}',
        )

    def test_user_in_humans(self):
        """teaparty.yaml must include at least one human."""
        data = self._load_yaml()
        humans = data.get('humans', [])
        self.assertGreater(
            len(humans),
            0,
            'teaparty.yaml must include at least one human in humans:',
        )

    def test_configuration_workgroup_present(self):
        """teaparty.yaml must include the Configuration workgroup."""
        data = self._load_yaml()
        workgroups = data.get('workgroups', [])
        self.assertTrue(
            any(wg['name'] == 'Configuration' for wg in workgroups),
            'teaparty.yaml must include Configuration in workgroups:',
        )


# ── 7. .teaparty.local/project.yaml exists at repo root ──────────────────────

class TestTeapartyLocalExists(unittest.TestCase):
    """.teaparty.local/project.yaml must exist at repo root."""

    def test_teaparty_local_dir_exists(self):
        """.teaparty.local/ directory must exist at repo root."""
        local_dir = _REPO_ROOT / '.teaparty.local'
        self.assertTrue(
            local_dir.is_dir(),
            f'.teaparty.local/ not found at {local_dir}',
        )

    def test_project_yaml_exists(self):
        """.teaparty.local/project.yaml must exist."""
        project_yaml = _REPO_ROOT / '.teaparty.local' / 'project.yaml'
        self.assertTrue(
            project_yaml.exists(),
            f'.teaparty.local/project.yaml not found at {project_yaml}',
        )

    def test_project_yaml_loadable(self):
        """.teaparty.local/project.yaml must be loadable as a ProjectTeam."""
        from orchestrator.config_reader import load_project_team
        team = load_project_team(str(_REPO_ROOT))
        self.assertIsNotNone(team.name)


# ── 8. resolve_workgroups uses .teaparty.local/ for project-level overrides ──

class TestResolveWorkgroupsLocalPath(unittest.TestCase):
    """resolve_workgroups must look in .teaparty.local/workgroups/ for project overrides."""

    def _make_local_project_dir(self, project_yaml: str, workgroup_files=None) -> str:
        proj = tempfile.mkdtemp()
        tp_local = os.path.join(proj, '.teaparty.local')
        os.makedirs(tp_local)
        os.makedirs(os.path.join(proj, '.git'))
        os.makedirs(os.path.join(proj, '.claude'))
        with open(os.path.join(tp_local, 'project.yaml'), 'w') as f:
            f.write(project_yaml)
        if workgroup_files:
            wg_dir = os.path.join(tp_local, 'workgroups')
            os.makedirs(wg_dir, exist_ok=True)
            for name, content in workgroup_files.items():
                with open(os.path.join(wg_dir, name), 'w') as f:
                    f.write(content)
        return proj

    def _make_teaparty_home(self, teaparty_yaml: str, workgroup_files=None) -> str:
        home = tempfile.mkdtemp()
        tp_dir = os.path.join(home, '.teaparty')
        os.makedirs(tp_dir)
        with open(os.path.join(tp_dir, 'teaparty.yaml'), 'w') as f:
            f.write(teaparty_yaml)
        if workgroup_files:
            wg_dir = os.path.join(tp_dir, 'workgroups')
            os.makedirs(wg_dir, exist_ok=True)
            for name, content in workgroup_files.items():
                with open(os.path.join(wg_dir, name), 'w') as f:
                    f.write(content)
        return os.path.join(home, '.teaparty')

    def test_project_override_in_teaparty_local_trumps_org(self):
        """Project-level workgroup in .teaparty.local/workgroups/ overrides org-level."""
        from orchestrator.config_reader import (
            load_project_team, resolve_workgroups, WorkgroupRef,
        )
        project_yaml = textwrap.dedent("""\
            name: My Project
            lead: lead
            decider: boss
            workgroups:
              - ref: coding
        """)
        override_yaml = 'name: Coding\ndescription: Project override.\nlead: override-lead\n'
        org_yaml = 'name: Coding\ndescription: Org version.\nlead: org-lead\n'

        proj = self._make_local_project_dir(
            project_yaml,
            workgroup_files={'coding.yaml': override_yaml},
        )
        tp_home = self._make_teaparty_home(
            'name: Org\nlead: boss\ndecider: boss\n',
            workgroup_files={'coding.yaml': org_yaml},
        )

        team = load_project_team(proj)
        resolved = resolve_workgroups(team.workgroups, project_dir=proj, teaparty_home=tp_home)
        self.assertEqual(resolved[0].description, 'Project override.')

    def test_project_override_not_found_in_old_teaparty_dir(self):
        """Project workgroup in .teaparty/workgroups/ (old path) is NOT used as override."""
        from orchestrator.config_reader import (
            load_project_team, resolve_workgroups,
        )
        project_yaml = textwrap.dedent("""\
            name: My Project
            lead: lead
            decider: boss
            workgroups:
              - ref: coding
        """)
        override_yaml = 'name: Coding\ndescription: Old path override.\nlead: old-lead\n'
        org_yaml = 'name: Coding\ndescription: Org version.\nlead: org-lead\n'

        proj = self._make_local_project_dir(project_yaml)
        # Put override in OLD .teaparty/workgroups/ path (not .teaparty.local/)
        old_tp = os.path.join(proj, '.teaparty', 'workgroups')
        os.makedirs(old_tp, exist_ok=True)
        with open(os.path.join(old_tp, 'coding.yaml'), 'w') as f:
            f.write(override_yaml)

        tp_home = self._make_teaparty_home(
            'name: Org\nlead: boss\ndecider: boss\n',
            workgroup_files={'coding.yaml': org_yaml},
        )

        team = load_project_team(proj)
        resolved = resolve_workgroups(team.workgroups, project_dir=proj, teaparty_home=tp_home)
        # Should fall through to org-level since .teaparty.local/workgroups/ has no override
        self.assertEqual(resolved[0].description, 'Org version.')


# ── Relative team path resolution ─────────────────────────────────────────────

class TestRelativeTeamPathResolution(unittest.TestCase):
    """teams: entries with relative paths must be resolved relative to teaparty_home parent."""

    def test_relative_team_path_resolved_to_repo_root(self):
        """A teams: entry with path '.' resolves to the repo root directory."""
        import yaml
        from orchestrator.config_reader import load_management_team, discover_projects

        # Create a fake repo structure
        repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(repo, '.git'))
        os.makedirs(os.path.join(repo, '.claude'))
        os.makedirs(os.path.join(repo, '.teaparty'))

        tp_dir = os.path.join(repo, '.teaparty')
        with open(os.path.join(tp_dir, 'teaparty.yaml'), 'w') as f:
            yaml.dump({
                'name': 'Org',
                'lead': 'boss',
                'decider': 'boss',
                'teams': [{'name': 'Self', 'path': '.'}],
            }, f)

        team = load_management_team(teaparty_home=tp_dir)
        projects = discover_projects(team)
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]['name'], 'Self')
        self.assertTrue(projects[0]['valid'])


if __name__ == '__main__':
    unittest.main()
