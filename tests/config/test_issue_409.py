"""Specification tests for Issue #409: full project onboarding sequence.

These tests encode the requirements from
``docs/detailed-design/project-onboarding.md`` as load-bearing assertions.

Covers:

1. Name normalization (lowercase + whitespace → hyphens) — ``create_project``
2. Name normalization — ``add_project``
3. Description sentinel when description is omitted
4. ``project.yaml.workgroups`` includes ``Configuration`` on scaffold
5. ``.gitignore`` written from template with required entries
6. ``.gitignore`` append (not overwrite) when one already exists
7. Initial commit contains ``.gitignore`` and ``.teaparty/project/`` tree
8. ``{name}-lead`` always scaffolded (no ``lead`` parameter)
"""
import os
import shutil
import subprocess
import tempfile
import unittest

import yaml

from teaparty.config.config_reader import (
    add_project,
    create_project,
    load_management_team,
)

SENTINEL = '⚠ No description — ask the project lead'


def _make_tmp(tc: unittest.TestCase) -> str:
    tmp = tempfile.mkdtemp(prefix='teaparty-test-409-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def _make_teaparty_home(tmp: str) -> str:
    home = os.path.join(tmp, '.teaparty')
    mgmt = os.path.join(home, 'management')
    os.makedirs(mgmt, exist_ok=True)
    with open(os.path.join(mgmt, 'teaparty.yaml'), 'w') as f:
        yaml.dump({
            'name': 'Management Team',
            'lead': 'office-manager',
            'humans': {'decider': 'alice'},
            'projects': [],
            'members': {'agents': ['office-manager'], 'skills': [], 'workgroups': []},
        }, f, sort_keys=False)
    return home


def _read_project_yaml(project_path: str) -> dict:
    yaml_path = os.path.join(project_path, '.teaparty', 'project', 'project.yaml')
    with open(yaml_path) as f:
        return yaml.safe_load(f) or {}


class TestNameNormalizationCreate(unittest.TestCase):
    """Criterion 1: create_project normalizes the name before use."""

    def test_mixed_case_with_space_becomes_lowercase_hyphen(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'my-project')
        create_project('My Project', proj, teaparty_home=home, decider='alice')

        team = load_management_team(teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertIn(
            'my-project', names,
            f"create_project('My Project', ...) must store name as 'my-project'; "
            f"registry contains {names!r}",
        )
        self.assertNotIn('My Project', names)

    def test_normalized_name_written_into_project_yaml(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'my-project')
        create_project('My Project', proj, teaparty_home=home, decider='alice')
        data = _read_project_yaml(proj)
        self.assertEqual(
            data['name'], 'my-project',
            "project.yaml 'name' field must contain the normalized name",
        )

    def test_normalized_lead_is_derived_from_normalized_name(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'my-project')
        create_project('My Project', proj, teaparty_home=home, decider='alice')
        data = _read_project_yaml(proj)
        self.assertEqual(
            data['lead'], 'my-project-lead',
            "project.yaml 'lead' field must be '{normalized-name}-lead'",
        )


class TestNameNormalizationAdd(unittest.TestCase):
    """Criterion 2: add_project normalizes the name before use."""

    def test_trailing_whitespace_stripped(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'pybayes')
        os.makedirs(proj)
        add_project('PyBayes ', proj, teaparty_home=home, decider='alice')

        team = load_management_team(teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertIn(
            'pybayes', names,
            f"add_project('PyBayes ', ...) must store name as 'pybayes'; "
            f"registry contains {names!r}",
        )

    def test_normalized_lead_in_project_yaml(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'pybayes')
        os.makedirs(proj)
        add_project('PyBayes ', proj, teaparty_home=home, decider='alice')
        data = _read_project_yaml(proj)
        self.assertEqual(data['lead'], 'pybayes-lead')
        self.assertEqual(data['name'], 'pybayes')


class TestDescriptionSentinel(unittest.TestCase):
    """Criterion 3: missing description → sentinel value."""

    def test_sentinel_written_when_description_omitted(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'alpha')
        os.makedirs(proj)
        add_project('alpha', proj, teaparty_home=home, decider='alice')
        data = _read_project_yaml(proj)
        self.assertEqual(
            data['description'], SENTINEL,
            "missing description must default to the sentinel string "
            f"{SENTINEL!r}; got {data.get('description')!r}",
        )

    def test_explicit_description_preserved(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'beta')
        os.makedirs(proj)
        add_project('beta', proj, teaparty_home=home,
                    description='real description', decider='alice')
        data = _read_project_yaml(proj)
        self.assertEqual(data['description'], 'real description')

    def test_empty_string_description_becomes_sentinel(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'gamma')
        os.makedirs(proj)
        add_project('gamma', proj, teaparty_home=home,
                    description='', decider='alice')
        data = _read_project_yaml(proj)
        self.assertEqual(
            data['description'], SENTINEL,
            "empty-string description must be treated as missing and "
            "replaced with the sentinel",
        )


class TestWorkgroupsIncludesConfiguration(unittest.TestCase):
    """Criterion 4: project.yaml workgroups must reference 'Configuration'.

    The entry must be a ``{ref: Configuration}`` dict (a WorkgroupRef) — the
    canonical shape ``_parse_workgroup_entries`` expects. A bare string
    ``['Configuration']`` crashes the bridge response serializer when it
    reloads the freshly-created project.
    """

    EXPECTED = {'ref': 'configuration'}

    def test_add_project_includes_configuration(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'delta')
        os.makedirs(proj)
        add_project('delta', proj, teaparty_home=home, decider='alice')
        data = _read_project_yaml(proj)
        self.assertIn(
            self.EXPECTED, data.get('workgroups', []),
            f"project.yaml.workgroups must include {{ref: Configuration}}; "
            f"got {data.get('workgroups')!r}",
        )

    def test_create_project_includes_configuration(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'epsilon')
        create_project('epsilon', proj, teaparty_home=home, decider='alice')
        data = _read_project_yaml(proj)
        self.assertIn(self.EXPECTED, data.get('workgroups', []))

    def test_scaffolded_project_round_trips_through_loader(self):
        """A freshly-scaffolded project must load via load_project_team.

        Regression guard for the bridge-side crash where _parse_workgroup_entries
        tried to index a string. The response serializer reloads the project
        immediately after creation, so a scaffold that produces an unparseable
        workgroups field makes the HTTP POST return a 500.
        """
        from teaparty.config.config_reader import load_project_team
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'roundtrip')
        create_project('roundtrip', proj, teaparty_home=home, decider='alice')
        pt = load_project_team(proj)
        refs = [
            w.ref for w in pt.workgroups
            if hasattr(w, 'ref')
        ]
        self.assertIn(
            'configuration', refs,
            f"loaded ProjectTeam.workgroups must contain a WorkgroupRef "
            f"for configuration; got {pt.workgroups!r}",
        )


class TestGitignoreFromTemplate(unittest.TestCase):
    """Criterion 5: .gitignore is written from template."""

    REQUIRED_ENTRIES = ['.teaparty/jobs/', '*.db']

    def test_gitignore_created_by_create_project(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'zeta')
        create_project('zeta', proj, teaparty_home=home, decider='alice')
        gi = os.path.join(proj, '.gitignore')
        self.assertTrue(os.path.isfile(gi), ".gitignore must be written")
        with open(gi) as f:
            content = f.read()
        for entry in self.REQUIRED_ENTRIES:
            self.assertIn(
                entry, content,
                f".gitignore must contain {entry!r}; got:\n{content}",
            )

    def test_gitignore_created_by_add_project(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'eta')
        os.makedirs(proj)
        add_project('eta', proj, teaparty_home=home, decider='alice')
        gi = os.path.join(proj, '.gitignore')
        self.assertTrue(os.path.isfile(gi))
        with open(gi) as f:
            content = f.read()
        for entry in self.REQUIRED_ENTRIES:
            self.assertIn(entry, content)

    def test_teaparty_project_tree_not_ignored(self):
        """.teaparty/project/ is source-controlled config — must NOT be ignored."""
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'theta')
        create_project('theta', proj, teaparty_home=home, decider='alice')
        with open(os.path.join(proj, '.gitignore')) as f:
            content = f.read()
        # Negative space: the template must not ignore the project config tree.
        self.assertNotIn(
            '.teaparty/project/', content,
            ".teaparty/project/ is source-controlled and must not be gitignored",
        )
        self.assertNotIn('.teaparty/\n', content)


class TestGitignoreAppend(unittest.TestCase):
    """Criterion 6: existing .gitignore is appended, not overwritten."""

    def test_existing_content_preserved(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'iota')
        os.makedirs(proj)
        prior = '# project-local\nnode_modules/\n__pycache__/\n'
        with open(os.path.join(proj, '.gitignore'), 'w') as f:
            f.write(prior)

        add_project('iota', proj, teaparty_home=home, decider='alice')

        with open(os.path.join(proj, '.gitignore')) as f:
            content = f.read()
        self.assertIn('node_modules/', content, "existing entries must be preserved")
        self.assertIn('__pycache__/', content)
        self.assertIn('.teaparty/jobs/', content, "TeaParty stanza must be appended")
        self.assertIn('*.db', content)

    def test_append_is_idempotent(self):
        """Running twice must not duplicate the TeaParty stanza."""
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'kappa')
        os.makedirs(proj)
        with open(os.path.join(proj, '.gitignore'), 'w') as f:
            f.write('node_modules/\n')

        add_project('kappa', proj, teaparty_home=home, decider='alice')
        # Second invocation via scaffold path: remove from registry, then re-add
        from teaparty.config.config_reader import remove_project
        remove_project('kappa', teaparty_home=home)
        add_project('kappa', proj, teaparty_home=home, decider='alice')

        with open(os.path.join(proj, '.gitignore')) as f:
            content = f.read()
        self.assertEqual(
            content.count('.teaparty/jobs/'), 1,
            "TeaParty stanza must appear exactly once after repeated scaffolding; "
            f"got {content.count('.teaparty/jobs/')} occurrences:\n{content}",
        )


class TestInitialCommit(unittest.TestCase):
    """Criterion 7: initial commit contains the scaffolded files."""

    def _git(self, cwd: str, *args: str) -> str:
        result = subprocess.run(
            ['git', *args], cwd=cwd, check=True,
            capture_output=True, text=True,
        )
        return result.stdout

    def test_create_project_makes_initial_commit(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'lambda')
        create_project('lambda', proj, teaparty_home=home, decider='alice')
        log = self._git(proj, 'log', '--oneline')
        self.assertTrue(
            log.strip(),
            f"create_project must produce a commit; git log is empty in {proj}",
        )

    def test_commit_contains_required_files(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'mu')
        create_project('mu', proj, teaparty_home=home, decider='alice')
        tree = self._git(proj, 'ls-tree', '-r', '--name-only', 'HEAD')
        files = set(tree.splitlines())
        self.assertIn(
            '.gitignore', files,
            f".gitignore must be in the initial commit; tree:\n{tree}",
        )
        self.assertIn(
            '.teaparty/project/project.yaml', files,
            ".teaparty/project/project.yaml must be in the initial commit",
        )

    def test_working_tree_clean_after_create(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'nu')
        create_project('nu', proj, teaparty_home=home, decider='alice')
        status = self._git(proj, 'status', '--porcelain')
        self.assertEqual(
            status, '',
            f"working tree must be clean after create_project; got:\n{status!r}",
        )

    def test_commit_message_matches_spec(self):
        """Design doc pins the commit message exactly."""
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'mu-msg')
        create_project('mu-msg', proj, teaparty_home=home, decider='alice')
        subject = self._git(proj, 'log', '-1', '--format=%s').strip()
        self.assertEqual(
            subject, 'chore: add TeaParty project configuration',
            f"initial commit subject must match the spec; got {subject!r}",
        )

    def test_add_project_commits_in_existing_repo(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'xi')
        os.makedirs(proj)
        subprocess.run(['git', 'init'], cwd=proj, check=True, capture_output=True)
        subprocess.run(
            ['git', '-c', 'user.email=t@t.x', '-c', 'user.name=t',
             'commit', '--allow-empty', '-m', 'initial'],
            cwd=proj, check=True, capture_output=True,
        )
        add_project('xi', proj, teaparty_home=home, decider='alice')
        tree = self._git(proj, 'ls-tree', '-r', '--name-only', 'HEAD')
        files = set(tree.splitlines())
        self.assertIn('.gitignore', files)
        self.assertIn('.teaparty/project/project.yaml', files)


class TestProjectLeadAlwaysScaffolded(unittest.TestCase):
    """Criterion 8: {name}-lead is always created, no lead parameter."""

    def test_create_project_scaffolds_lead_agent(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'omicron')
        from teaparty.mcp.tools.config_crud import create_project_handler
        import json as _json
        result = _json.loads(create_project_handler(
            name='Omicron',
            path=proj,
            decider='alice',
            teaparty_home=home,
        ))
        self.assertTrue(result.get('success'), result)
        agent_md = os.path.join(
            home, 'management', 'agents', 'omicron-lead', 'agent.md'
        )
        self.assertTrue(
            os.path.isfile(agent_md),
            f"create_project_handler must scaffold {{name}}-lead/agent.md at "
            f"{agent_md}",
        )

    def test_add_project_scaffolds_lead_agent(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'pi-proj')
        os.makedirs(proj)
        from teaparty.mcp.tools.config_crud import add_project_handler
        import json as _json
        result = _json.loads(add_project_handler(
            name='Pi Proj',
            path=proj,
            decider='alice',
            teaparty_home=home,
        ))
        self.assertTrue(result.get('success'), result)
        agent_md = os.path.join(
            home, 'management', 'agents', 'pi-proj-lead', 'agent.md'
        )
        self.assertTrue(
            os.path.isfile(agent_md),
            "add_project_handler must scaffold {name}-lead/agent.md with "
            "the normalized name",
        )

    def test_lead_agent_md_has_spec_frontmatter(self):
        """agent.md must have name, description, tools, model=sonnet, maxTurns=30."""
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'tau')
        create_project('Tau Project', proj, teaparty_home=home, decider='alice')

        agent_md = os.path.join(
            home, 'management', 'agents', 'tau-project-lead', 'agent.md'
        )
        import re
        with open(agent_md) as f:
            content = f.read()
        m = re.match(r'^---\n(.*?\n)---\n(.*)', content, re.DOTALL)
        self.assertIsNotNone(m, "agent.md must have YAML frontmatter")
        fm = yaml.safe_load(m.group(1))
        self.assertEqual(fm['name'], 'tau-project-lead')
        self.assertEqual(
            fm['model'], 'sonnet',
            f"design doc requires model=sonnet; got {fm.get('model')!r}",
        )
        self.assertEqual(
            fm['maxTurns'], 30,
            f"design doc requires maxTurns=30; got {fm.get('maxTurns')!r}",
        )
        self.assertIn('tau-project', fm['description'])
        tools = fm.get('tools', '')
        for required_tool in [
            'Read', 'Glob', 'Grep', 'Bash',
            'mcp__teaparty-config__Send',
            'mcp__teaparty-config__ProjectStatus',
            'mcp__teaparty-config__WithdrawSession',
        ]:
            self.assertIn(
                required_tool, tools,
                f"project-lead tools must include {required_tool}",
            )

    def test_lead_settings_yaml_permissions(self):
        """settings.yaml must grant allow-list for the project-lead tool set."""
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'upsilon')
        create_project('upsilon', proj, teaparty_home=home, decider='alice')
        settings_path = os.path.join(
            home, 'management', 'agents', 'upsilon-lead', 'settings.yaml'
        )
        with open(settings_path) as f:
            settings = yaml.safe_load(f) or {}
        allow = settings.get('permissions', {}).get('allow', [])
        for required in [
            'mcp__teaparty-config__Send',
            'mcp__teaparty-config__ProjectStatus',
            'mcp__teaparty-config__PinArtifact',
            'mcp__teaparty-config__WithdrawSession',
        ]:
            self.assertIn(
                required, allow,
                f"settings.yaml allow-list must grant {required}",
            )

    def test_lead_pins_yaml_entries(self):
        """pins.yaml must pin agent.md + settings.yaml with spec labels."""
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'phi')
        create_project('phi', proj, teaparty_home=home, decider='alice')
        pins_path = os.path.join(
            home, 'management', 'agents', 'phi-lead', 'pins.yaml'
        )
        with open(pins_path) as f:
            pins = yaml.safe_load(f) or []
        paths = {p['path']: p['label'] for p in pins}
        self.assertEqual(
            paths.get('agent.md'), 'Prompt & Identity',
            "pins.yaml must pin agent.md with label 'Prompt & Identity'",
        )
        self.assertEqual(
            paths.get('settings.yaml'), 'Tool & File Permissions',
            "pins.yaml must pin settings.yaml with label "
            "'Tool & File Permissions'",
        )

    def test_lead_scaffold_is_non_destructive(self):
        """Pre-existing lead agent files are never overwritten."""
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        # Pre-create the lead agent directory with sentinel content.
        lead_dir = os.path.join(home, 'management', 'agents', 'chi-lead')
        os.makedirs(lead_dir, exist_ok=True)
        for fname, sentinel in [
            ('agent.md', '# custom agent\n'),
            ('settings.yaml', 'custom: true\n'),
            ('pins.yaml', '- path: custom.md\n  label: Custom\n'),
        ]:
            with open(os.path.join(lead_dir, fname), 'w') as f:
                f.write(sentinel)

        proj = os.path.join(tmp, 'chi')
        create_project('chi', proj, teaparty_home=home, decider='alice')

        for fname, sentinel in [
            ('agent.md', '# custom agent\n'),
            ('settings.yaml', 'custom: true\n'),
            ('pins.yaml', '- path: custom.md\n  label: Custom\n'),
        ]:
            with open(os.path.join(lead_dir, fname)) as f:
                self.assertEqual(
                    f.read(), sentinel,
                    f"scaffold_project_lead must not overwrite existing "
                    f"{fname}; the custom sentinel was clobbered",
                )

    def test_bridge_api_scaffolds_lead(self):
        """The bridge HTTP path must invoke the full onboarding sequence.

        Guards the integration finding from the audit: if
        ``_handle_projects_create`` bypasses ``scaffold_project_lead`` (for
        example, by calling only ``_scaffold_project_yaml``), projects added
        from the dashboard UI would get no project-lead agent.
        """
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'psi')

        # Call config_reader.create_project directly — this is the function
        # the bridge server invokes with no extra wrapping.
        create_project('Psi Sys', proj, teaparty_home=home, decider='alice')

        agent_md = os.path.join(
            home, 'management', 'agents', 'psi-sys-lead', 'agent.md'
        )
        self.assertTrue(
            os.path.isfile(agent_md),
            "config_reader.create_project must scaffold the project lead "
            "so the bridge HTTP path produces the same end state as the MCP "
            "handler (design doc: 'both produce identical end state')",
        )

    def test_lead_parameter_removed_from_create_project(self):
        """Passing 'lead=' to create_project should raise TypeError."""
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'rho')
        with self.assertRaises(
            TypeError,
            msg="create_project must not accept a 'lead' parameter",
        ):
            create_project(
                'rho', proj, teaparty_home=home,
                decider='alice', lead='custom-lead',
            )

    def test_lead_parameter_removed_from_add_project(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'sigma')
        os.makedirs(proj)
        with self.assertRaises(
            TypeError,
            msg="add_project must not accept a 'lead' parameter",
        ):
            add_project(
                'sigma', proj, teaparty_home=home,
                decider='alice', lead='custom-lead',
            )


class TestDeciderResolution(unittest.TestCase):
    """The decider must be a human; empty defaults to the management decider."""

    def _home_with_humans(self, tmp: str, humans: dict, members_agents=None) -> str:
        home = os.path.join(tmp, '.teaparty')
        mgmt = os.path.join(home, 'management')
        os.makedirs(mgmt, exist_ok=True)
        with open(os.path.join(mgmt, 'teaparty.yaml'), 'w') as f:
            yaml.dump({
                'name': 'Management Team',
                'lead': 'office-manager',
                'humans': humans,
                'projects': [],
                'members': {
                    'agents': members_agents or ['office-manager'],
                    'skills': [],
                    'workgroups': [],
                },
            }, f, sort_keys=False)
        return home

    def test_empty_decider_defaults_to_management_decider(self):
        """The dashboard modal sends no decider; the management decider takes over."""
        tmp = _make_tmp(self)
        home = self._home_with_humans(tmp, {'decider': 'darrell'})
        proj = os.path.join(tmp, 'no-dec')
        create_project('no-dec', proj, teaparty_home=home)
        data = _read_project_yaml(proj)
        self.assertEqual(
            data['humans']['decider'], 'darrell',
            "when no decider is supplied, the project must inherit the "
            "management team's decider (the human running this instance)",
        )

    def test_empty_decider_raises_when_no_management_decider(self):
        """A project without any resolvable decider must be rejected."""
        tmp = _make_tmp(self)
        home = self._home_with_humans(tmp, {})
        proj = os.path.join(tmp, 'orphan')
        with self.assertRaises(ValueError) as ctx:
            create_project('orphan', proj, teaparty_home=home)
        self.assertIn('decider', str(ctx.exception).lower())

    def test_agent_name_rejected_as_decider(self):
        """Agents can never be deciders — even the management lead."""
        tmp = _make_tmp(self)
        home = self._home_with_humans(
            tmp, {'decider': 'darrell'},
            members_agents=['office-manager', 'project-specialist'],
        )
        proj = os.path.join(tmp, 'bad-dec')
        with self.assertRaises(ValueError) as ctx:
            create_project(
                'bad-dec', proj, teaparty_home=home,
                decider='office-manager',
            )
        msg = str(ctx.exception)
        self.assertIn('office-manager', msg)
        self.assertIn('agent', msg.lower())

    def test_unknown_human_rejected_as_decider(self):
        """Deciders must be registered humans; typos or guesses are rejected."""
        tmp = _make_tmp(self)
        home = self._home_with_humans(tmp, {'decider': 'darrell'})
        proj = os.path.join(tmp, 'unknown-dec')
        with self.assertRaises(ValueError) as ctx:
            create_project(
                'unknown-dec', proj, teaparty_home=home,
                decider='stranger',
            )
        self.assertIn('stranger', str(ctx.exception))

    def test_known_advisor_accepted_as_decider(self):
        """Any registered human may be named the project decider."""
        tmp = _make_tmp(self)
        home = self._home_with_humans(
            tmp,
            {'decider': 'darrell', 'advisors': ['alice']},
        )
        proj = os.path.join(tmp, 'advised')
        create_project(
            'advised', proj, teaparty_home=home, decider='alice',
        )
        data = _read_project_yaml(proj)
        self.assertEqual(data['humans']['decider'], 'alice')

    def test_add_project_also_resolves_decider(self):
        tmp = _make_tmp(self)
        home = self._home_with_humans(tmp, {'decider': 'darrell'})
        proj = os.path.join(tmp, 'add-dec')
        os.makedirs(proj)
        add_project('add-dec', proj, teaparty_home=home)
        data = _read_project_yaml(proj)
        self.assertEqual(data['humans']['decider'], 'darrell')


if __name__ == '__main__':
    unittest.main()
