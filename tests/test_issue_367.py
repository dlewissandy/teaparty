"""Tests for issue #367: Config screen — show full inherited catalog with active items highlighted.

Acceptance criteria:
1. Agents panel shows all agents in the inherited catalog; active agents highlighted
2. Skills panel shows all skills in the inherited catalog; active skills highlighted
3. Hooks panel shows all hooks in the inherited catalog; active hooks highlighted
4. Clicking an inactive item activates it; clicking an active item deactivates it
5. Changes written back to the YAML on disk
6. Management and project config screens both updated
"""
import json
import os
import tempfile
import unittest
import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────

CONFIG_HTML = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'bridge', 'static', 'config.html',
)
STYLES_CSS = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'bridge', 'static', 'styles.css',
)


def _read_config_html():
    with open(CONFIG_HTML) as f:
        return f.read()


def _read_styles_css():
    with open(STYLES_CSS) as f:
        return f.read()


def _make_bridge(tmpdir: str):
    from bridge.server import TeaPartyBridge
    teaparty_home = os.path.join(tmpdir, '.teaparty')
    os.makedirs(teaparty_home, exist_ok=True)
    static_dir = os.path.join(tmpdir, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)


def _make_management_yaml(teaparty_home: str, agents: list, skills: list | None = None):
    """Write teaparty.yaml with given active agents/skills list."""
    data = {
        'name': 'Management',
        'description': 'Test',
        'lead': 'office-manager',
        'humans': {'decider': 'darrell'},
        'members': {
            'agents': agents,
            'skills': skills or [],
        },
        'hooks': [],
        'scheduled': [],
        'workgroups': [],
    }
    os.makedirs(teaparty_home, exist_ok=True)
    with open(os.path.join(teaparty_home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _make_project_yaml(project_dir: str, agents: list, skills: list | None = None):
    """Write project.yaml with given active agents/skills list."""
    tp_local = os.path.join(project_dir, '.teaparty.local')
    os.makedirs(tp_local, exist_ok=True)
    data = {
        'name': 'Test Project',
        'description': 'A test project',
        'lead': 'project-lead',
        'humans': {'decider': 'darrell'},
        'members': {
            'agents': agents,
            'skills': skills or [],
        },
        'hooks': [],
        'scheduled': [],
        'workgroups': [],
    }
    with open(os.path.join(tp_local, 'project.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _make_agent_file(agents_dir: str, name: str):
    os.makedirs(agents_dir, exist_ok=True)
    with open(os.path.join(agents_dir, f'{name}.md'), 'w') as f:
        f.write(f'# {name}\n')


def _make_skill(skills_dir: str, name: str):
    skill_path = os.path.join(skills_dir, name)
    os.makedirs(skill_path, exist_ok=True)
    with open(os.path.join(skill_path, 'SKILL.md'), 'w') as f:
        f.write(f'# {name}\n')


def _read_project_yaml(project_dir: str) -> dict:
    path = os.path.join(project_dir, '.teaparty.local', 'project.yaml')
    with open(path) as f:
        return yaml.safe_load(f)


def _read_management_yaml(teaparty_home: str) -> dict:
    path = os.path.join(teaparty_home, 'teaparty.yaml')
    with open(path) as f:
        return yaml.safe_load(f)


# ── discover_agents ──────────────────────────────────────────────────────────

class TestDiscoverAgents(unittest.TestCase):
    """discover_agents must return all .md filenames (without extension) from agents_dir."""

    def test_returns_agent_names_from_md_files(self):
        """discover_agents returns names derived from .md files in the directory."""
        from orchestrator.config_reader import discover_agents
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = os.path.join(tmp, '.claude', 'agents')
            _make_agent_file(agents_dir, 'office-manager')
            _make_agent_file(agents_dir, 'auditor')
            result = discover_agents(agents_dir)
        self.assertIn('office-manager', result)
        self.assertIn('auditor', result)

    def test_returns_empty_list_for_missing_dir(self):
        """discover_agents returns [] when the agents directory does not exist."""
        from orchestrator.config_reader import discover_agents
        result = discover_agents('/nonexistent/path/.claude/agents')
        self.assertEqual(result, [])

    def test_ignores_non_md_files(self):
        """discover_agents ignores non-.md files in the directory."""
        from orchestrator.config_reader import discover_agents
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = os.path.join(tmp, '.claude', 'agents')
            os.makedirs(agents_dir, exist_ok=True)
            _make_agent_file(agents_dir, 'office-manager')
            with open(os.path.join(agents_dir, 'README.txt'), 'w') as f:
                f.write('ignored')
            result = discover_agents(agents_dir)
        self.assertEqual(result, ['office-manager'])

    def test_returns_sorted_names(self):
        """discover_agents returns names in sorted order."""
        from orchestrator.config_reader import discover_agents
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = os.path.join(tmp, '.claude', 'agents')
            _make_agent_file(agents_dir, 'zebra')
            _make_agent_file(agents_dir, 'alpha')
            _make_agent_file(agents_dir, 'mango')
            result = discover_agents(agents_dir)
        self.assertEqual(result, ['alpha', 'mango', 'zebra'])


# ── toggle_management_membership ────────────────────────────────────────────

class TestToggleManagementMembership(unittest.TestCase):
    """toggle_management_membership must add/remove items from teaparty.yaml."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        _make_management_yaml(self.teaparty_home, agents=['office-manager'], skills=['audit'])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_activate_agent_adds_to_yaml(self):
        """Activating an agent that is not in the list adds it to teaparty.yaml."""
        from orchestrator.config_reader import toggle_management_membership
        toggle_management_membership(self.teaparty_home, 'agent', 'auditor', True)
        data = _read_management_yaml(self.teaparty_home)
        self.assertIn('auditor', data['members']['agents'])

    def test_deactivate_agent_removes_from_yaml(self):
        """Deactivating an agent removes it from teaparty.yaml."""
        from orchestrator.config_reader import toggle_management_membership
        toggle_management_membership(self.teaparty_home, 'agent', 'office-manager', False)
        data = _read_management_yaml(self.teaparty_home)
        self.assertNotIn('office-manager', data['members']['agents'])

    def test_activate_already_active_agent_is_idempotent(self):
        """Activating an already-active agent does not duplicate it in the list."""
        from orchestrator.config_reader import toggle_management_membership
        toggle_management_membership(self.teaparty_home, 'agent', 'office-manager', True)
        data = _read_management_yaml(self.teaparty_home)
        self.assertEqual(data['members']['agents'].count('office-manager'), 1)

    def test_activate_skill_adds_to_yaml(self):
        """Activating a skill adds it to the skills list in teaparty.yaml."""
        from orchestrator.config_reader import toggle_management_membership
        toggle_management_membership(self.teaparty_home, 'skill', 'sprint-plan', True)
        data = _read_management_yaml(self.teaparty_home)
        self.assertIn('sprint-plan', data['members']['skills'])

    def test_deactivate_skill_removes_from_yaml(self):
        """Deactivating a skill removes it from teaparty.yaml."""
        from orchestrator.config_reader import toggle_management_membership
        toggle_management_membership(self.teaparty_home, 'skill', 'audit', False)
        data = _read_management_yaml(self.teaparty_home)
        self.assertNotIn('audit', data['members']['skills'])

    def test_other_fields_preserved_after_toggle(self):
        """toggle_management_membership preserves all other YAML fields."""
        from orchestrator.config_reader import toggle_management_membership
        toggle_management_membership(self.teaparty_home, 'agent', 'auditor', True)
        data = _read_management_yaml(self.teaparty_home)
        self.assertEqual(data['lead'], 'office-manager')
        self.assertEqual(data['humans']['decider'], 'darrell')

    def test_deactivate_hook_sets_active_false(self):
        """Deactivating a hook sets active=False on the hook entry in teaparty.yaml."""
        from orchestrator.config_reader import toggle_management_membership
        # Add a hook to the YAML first
        data = _read_management_yaml(self.teaparty_home)
        data['hooks'] = [{'event': 'PreToolUse', 'matcher': 'Bash', 'type': 'command', 'command': './hook.sh'}]
        import yaml as _yaml
        with open(os.path.join(self.teaparty_home, 'teaparty.yaml'), 'w') as f:
            _yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        toggle_management_membership(self.teaparty_home, 'hook', 'PreToolUse', False)
        data = _read_management_yaml(self.teaparty_home)
        hook = data['hooks'][0]
        self.assertFalse(hook.get('active', True))

    def test_reactivate_hook_sets_active_true(self):
        """Reactivating a deactivated hook sets active=True on the entry."""
        from orchestrator.config_reader import toggle_management_membership
        data = _read_management_yaml(self.teaparty_home)
        data['hooks'] = [{'event': 'PreToolUse', 'active': False, 'type': 'command', 'command': './hook.sh'}]
        import yaml as _yaml
        with open(os.path.join(self.teaparty_home, 'teaparty.yaml'), 'w') as f:
            _yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        toggle_management_membership(self.teaparty_home, 'hook', 'PreToolUse', True)
        data = _read_management_yaml(self.teaparty_home)
        self.assertTrue(data['hooks'][0].get('active', True))


# ── toggle_project_membership ────────────────────────────────────────────────

class TestToggleProjectMembership(unittest.TestCase):
    """toggle_project_membership must add/remove items from project.yaml."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.tmp, 'myproject')
        os.makedirs(self.project_dir)
        _make_project_yaml(self.project_dir, agents=['project-lead'], skills=['fix-issue'])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_activate_agent_adds_to_project_yaml(self):
        """Activating an agent adds it to project.yaml agents list."""
        from orchestrator.config_reader import toggle_project_membership
        toggle_project_membership(self.project_dir, 'agent', 'reviewer', True)
        data = _read_project_yaml(self.project_dir)
        self.assertIn('reviewer', data['members']['agents'])

    def test_deactivate_agent_removes_from_project_yaml(self):
        """Deactivating an agent removes it from project.yaml agents list."""
        from orchestrator.config_reader import toggle_project_membership
        toggle_project_membership(self.project_dir, 'agent', 'project-lead', False)
        data = _read_project_yaml(self.project_dir)
        self.assertNotIn('project-lead', data['members']['agents'])

    def test_activate_skill_adds_to_project_yaml(self):
        """Activating a skill adds it to project.yaml skills list."""
        from orchestrator.config_reader import toggle_project_membership
        toggle_project_membership(self.project_dir, 'skill', 'audit', True)
        data = _read_project_yaml(self.project_dir)
        self.assertIn('audit', data['members']['skills'])

    def test_deactivate_skill_removes_from_project_yaml(self):
        """Deactivating a skill removes it from project.yaml skills list."""
        from orchestrator.config_reader import toggle_project_membership
        toggle_project_membership(self.project_dir, 'skill', 'fix-issue', False)
        data = _read_project_yaml(self.project_dir)
        self.assertNotIn('fix-issue', data['members']['skills'])

    def test_other_fields_preserved_after_toggle(self):
        """toggle_project_membership preserves all other project YAML fields."""
        from orchestrator.config_reader import toggle_project_membership
        toggle_project_membership(self.project_dir, 'agent', 'reviewer', True)
        data = _read_project_yaml(self.project_dir)
        self.assertEqual(data['lead'], 'project-lead')
        self.assertEqual(data['humans']['decider'], 'darrell')


# ── _serialize_management_team: full catalog with active flag ────────────────

class TestManagementTeamFullAgentCatalog(unittest.TestCase):
    """_serialize_management_team must return all filesystem agents with active: bool."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        self.agents_dir = os.path.join(self.tmp, '.claude', 'agents')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_active_agent_has_active_true(self):
        """An agent listed in teaparty.yaml agents has active: True in the response."""
        from orchestrator.config_reader import load_management_team
        _make_management_yaml(self.teaparty_home, agents=['office-manager'])
        _make_agent_file(self.agents_dir, 'office-manager')
        team = load_management_team(teaparty_home=self.teaparty_home)
        bridge = _make_bridge(self.tmp)
        result = bridge._serialize_management_team(team)
        active_agent = next((a for a in result['agents'] if a['name'] == 'office-manager'), None)
        self.assertIsNotNone(active_agent, 'office-manager must be in agents list')
        self.assertTrue(active_agent['active'],
                        'office-manager is in teaparty.yaml, so active must be True')

    def test_inactive_agent_has_active_false(self):
        """An agent file that exists but is NOT in teaparty.yaml has active: False."""
        from orchestrator.config_reader import load_management_team
        _make_management_yaml(self.teaparty_home, agents=['office-manager'])
        _make_agent_file(self.agents_dir, 'office-manager')
        _make_agent_file(self.agents_dir, 'auditor')  # in filesystem, not in YAML
        team = load_management_team(teaparty_home=self.teaparty_home)
        bridge = _make_bridge(self.tmp)
        result = bridge._serialize_management_team(team)
        inactive_agent = next((a for a in result['agents'] if a['name'] == 'auditor'), None)
        self.assertIsNotNone(inactive_agent,
                             'auditor exists in .claude/agents/ — must appear in catalog')
        self.assertFalse(inactive_agent['active'],
                         'auditor is not in teaparty.yaml, so active must be False')

    def test_all_filesystem_agents_appear_in_catalog(self):
        """All agents found in .claude/agents/ appear in the response, not just active ones."""
        from orchestrator.config_reader import load_management_team
        _make_management_yaml(self.teaparty_home, agents=['office-manager'])
        _make_agent_file(self.agents_dir, 'office-manager')
        _make_agent_file(self.agents_dir, 'auditor')
        _make_agent_file(self.agents_dir, 'researcher')
        team = load_management_team(teaparty_home=self.teaparty_home)
        bridge = _make_bridge(self.tmp)
        result = bridge._serialize_management_team(team)
        names = {a['name'] for a in result['agents']}
        self.assertIn('office-manager', names)
        self.assertIn('auditor', names)
        self.assertIn('researcher', names)


class TestManagementTeamSkillCatalogWithActiveFlag(unittest.TestCase):
    """_serialize_management_team skills must include active: bool based on t.skills."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        self.skills_dir = os.path.join(self.tmp, '.claude', 'skills')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_active_skill_has_active_true(self):
        """A skill listed in teaparty.yaml skills has active: True."""
        from orchestrator.config_reader import load_management_team, discover_skills
        _make_management_yaml(self.teaparty_home, agents=[], skills=['audit'])
        _make_skill(self.skills_dir, 'audit')
        team = load_management_team(teaparty_home=self.teaparty_home)
        discovered = discover_skills(self.skills_dir)
        bridge = _make_bridge(self.tmp)
        result = bridge._serialize_management_team(team, discovered_skills=discovered)
        skill = next((s for s in result['skills'] if s['name'] == 'audit'), None)
        self.assertIsNotNone(skill, 'audit must appear in skills catalog')
        self.assertTrue(skill['active'], 'audit is in teaparty.yaml skills, so active must be True')

    def test_inactive_skill_has_active_false(self):
        """A discovered skill NOT in teaparty.yaml skills has active: False."""
        from orchestrator.config_reader import load_management_team, discover_skills
        _make_management_yaml(self.teaparty_home, agents=[], skills=['audit'])
        _make_skill(self.skills_dir, 'audit')
        _make_skill(self.skills_dir, 'sprint-plan')  # in filesystem, not in YAML
        team = load_management_team(teaparty_home=self.teaparty_home)
        discovered = discover_skills(self.skills_dir)
        bridge = _make_bridge(self.tmp)
        result = bridge._serialize_management_team(team, discovered_skills=discovered)
        skill = next((s for s in result['skills'] if s['name'] == 'sprint-plan'), None)
        self.assertIsNotNone(skill, 'sprint-plan exists on filesystem — must appear in catalog')
        self.assertFalse(skill['active'],
                         'sprint-plan is not in teaparty.yaml skills, so active must be False')


# ── _serialize_project_team: full catalog with active flag ───────────────────

class TestProjectTeamFullAgentCatalog(unittest.TestCase):
    """_serialize_project_team must return all catalog agents with active: bool."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        self.project_dir = os.path.join(self.tmp, 'myproject')
        os.makedirs(self.project_dir)
        self.org_agents_dir = os.path.join(self.tmp, '.claude', 'agents')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_active_org_agent_has_active_true(self):
        """An org agent listed in project.yaml agents has active: True."""
        from orchestrator.config_reader import load_project_team
        _make_management_yaml(self.teaparty_home, agents=['office-manager', 'auditor'])
        _make_project_yaml(self.project_dir, agents=['auditor'])
        _make_agent_file(self.org_agents_dir, 'office-manager')
        _make_agent_file(self.org_agents_dir, 'auditor')
        team = load_project_team(self.project_dir)
        bridge = _make_bridge(self.tmp)
        result = bridge._serialize_project_team(
            team,
            org_agents=['office-manager', 'auditor'],
            teaparty_home=self.teaparty_home,
            project_dir=self.project_dir,
        )
        agent = next((a for a in result['agents'] if a['name'] == 'auditor'), None)
        self.assertIsNotNone(agent, 'auditor must appear in agents catalog')
        self.assertTrue(agent['active'], 'auditor is in project.yaml, so active must be True')

    def test_inactive_org_agent_has_active_false(self):
        """An org agent NOT in project.yaml agents has active: False in the catalog."""
        from orchestrator.config_reader import load_project_team
        _make_management_yaml(self.teaparty_home, agents=['office-manager', 'auditor'])
        _make_project_yaml(self.project_dir, agents=['auditor'])
        _make_agent_file(self.org_agents_dir, 'office-manager')
        _make_agent_file(self.org_agents_dir, 'auditor')
        team = load_project_team(self.project_dir)
        bridge = _make_bridge(self.tmp)
        result = bridge._serialize_project_team(
            team,
            org_agents=['office-manager', 'auditor'],
            teaparty_home=self.teaparty_home,
            project_dir=self.project_dir,
        )
        agent = next((a for a in result['agents'] if a['name'] == 'office-manager'), None)
        self.assertIsNotNone(agent,
                             'office-manager is in .claude/agents/ — must appear in catalog')
        self.assertFalse(agent['active'],
                         'office-manager is not in project.yaml agents, so active must be False')

    def test_all_org_catalog_agents_present_regardless_of_project_active_list(self):
        """All org catalog agents appear in project team response, not just active ones."""
        from orchestrator.config_reader import load_project_team
        _make_management_yaml(self.teaparty_home, agents=['a', 'b', 'c'])
        _make_project_yaml(self.project_dir, agents=['b'])
        for name in ['a', 'b', 'c']:
            _make_agent_file(self.org_agents_dir, name)
        team = load_project_team(self.project_dir)
        bridge = _make_bridge(self.tmp)
        result = bridge._serialize_project_team(
            team,
            org_agents=['a', 'b', 'c'],
            teaparty_home=self.teaparty_home,
            project_dir=self.project_dir,
        )
        names = {ag['name'] for ag in result['agents']}
        self.assertIn('a', names)
        self.assertIn('b', names)
        self.assertIn('c', names)


class TestProjectTeamSkillCatalogWithActiveFlag(unittest.TestCase):
    """_serialize_project_team skills must include active: bool based on project skills list."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        self.project_dir = os.path.join(self.tmp, 'myproject')
        os.makedirs(self.project_dir)
        self.org_skills_dir = os.path.join(self.tmp, '.claude', 'skills')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_active_org_skill_has_active_true(self):
        """A skill in project.yaml skills has active: True."""
        from orchestrator.config_reader import load_project_team, discover_skills
        _make_management_yaml(self.teaparty_home, agents=[])
        _make_project_yaml(self.project_dir, agents=[], skills=['audit'])
        _make_skill(self.org_skills_dir, 'audit')
        _make_skill(self.org_skills_dir, 'sprint-plan')
        team = load_project_team(self.project_dir)
        bridge = _make_bridge(self.tmp)
        discovered = discover_skills(self.org_skills_dir)
        result = bridge._serialize_project_team(
            team,
            org_agents=[],
            registered_org_skills=['audit'],
            org_catalog_skills=discovered,
            teaparty_home=self.teaparty_home,
            project_dir=self.project_dir,
        )
        skill = next((s for s in result['skills'] if s['name'] == 'audit'), None)
        self.assertIsNotNone(skill, 'audit must appear in skills')
        self.assertTrue(skill['active'], 'audit is in project.yaml skills, so active must be True')

    def test_inactive_org_skill_has_active_false(self):
        """An org catalog skill NOT in project.yaml skills has active: False."""
        from orchestrator.config_reader import load_project_team, discover_skills
        _make_management_yaml(self.teaparty_home, agents=[])
        _make_project_yaml(self.project_dir, agents=[], skills=['audit'])
        _make_skill(self.org_skills_dir, 'audit')
        _make_skill(self.org_skills_dir, 'sprint-plan')
        team = load_project_team(self.project_dir)
        bridge = _make_bridge(self.tmp)
        discovered = discover_skills(self.org_skills_dir)
        result = bridge._serialize_project_team(
            team,
            org_agents=[],
            registered_org_skills=['audit'],
            org_catalog_skills=discovered,
            teaparty_home=self.teaparty_home,
            project_dir=self.project_dir,
        )
        skill = next((s for s in result['skills'] if s['name'] == 'sprint-plan'), None)
        self.assertIsNotNone(skill, 'sprint-plan is in org catalog — must appear in skills')
        self.assertFalse(skill['active'],
                         'sprint-plan is not in project.yaml skills, so active must be False')


# ── Toggle endpoint ──────────────────────────────────────────────────────────

class TestToggleManagementEndpoint(unittest.TestCase):
    """POST /api/config/management/toggle must add/remove membership and return 200."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        self.agents_dir = os.path.join(self.tmp, '.claude', 'agents')
        _make_management_yaml(self.teaparty_home, agents=['office-manager'])
        _make_agent_file(self.agents_dir, 'office-manager')
        _make_agent_file(self.agents_dir, 'auditor')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, body: dict) -> tuple[int, dict]:
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge(
            teaparty_home=self.teaparty_home,
            static_dir=os.path.join(self.tmp, 'static'),
        )

        async def _call():
            request = MagicMock()
            request.json = AsyncMock(return_value=body)
            response = await bridge._handle_config_management_toggle(request)
            return response.status, json.loads(response.body)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_call())
        finally:
            loop.close()

    def test_activate_agent_returns_200(self):
        """POST /api/config/management/toggle with active=True returns 200."""
        status, _ = self._run({'type': 'agent', 'name': 'auditor', 'active': True})
        self.assertEqual(status, 200)

    def test_activate_agent_writes_yaml(self):
        """POST /api/config/management/toggle with active=True writes to teaparty.yaml."""
        self._run({'type': 'agent', 'name': 'auditor', 'active': True})
        data = _read_management_yaml(self.teaparty_home)
        self.assertIn('auditor', data['members']['agents'])

    def test_deactivate_agent_writes_yaml(self):
        """POST /api/config/management/toggle with active=False removes from teaparty.yaml."""
        self._run({'type': 'agent', 'name': 'office-manager', 'active': False})
        data = _read_management_yaml(self.teaparty_home)
        self.assertNotIn('office-manager', data['members']['agents'])


class TestToggleProjectEndpoint(unittest.TestCase):
    """POST /api/config/{project}/toggle must add/remove membership and return 200."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        self.project_dir = os.path.join(self.tmp, 'myproject')
        os.makedirs(self.project_dir)
        _make_management_yaml(self.teaparty_home, agents=['office-manager', 'auditor'])
        _make_project_yaml(self.project_dir, agents=['auditor'])
        # Register project in management YAML
        data = _read_management_yaml(self.teaparty_home)
        data['projects'] = [{'name': 'myproject', 'path': self.project_dir}]
        with open(os.path.join(self.teaparty_home, 'teaparty.yaml'), 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        org_agents_dir = os.path.join(self.tmp, '.claude', 'agents')
        _make_agent_file(org_agents_dir, 'office-manager')
        _make_agent_file(org_agents_dir, 'auditor')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, slug: str, body: dict) -> tuple[int, dict]:
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge(
            teaparty_home=self.teaparty_home,
            static_dir=os.path.join(self.tmp, 'static'),
        )
        bridge._project_path_cache = {'myproject': self.project_dir}

        async def _call():
            request = MagicMock()
            request.match_info = {'project': slug}
            request.json = AsyncMock(return_value=body)
            response = await bridge._handle_config_project_toggle(request)
            return response.status, json.loads(response.body)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_call())
        finally:
            loop.close()

    def test_activate_agent_returns_200(self):
        """POST /api/config/{project}/toggle returns 200 when activating an agent."""
        status, _ = self._run('myproject', {'type': 'agent', 'name': 'office-manager', 'active': True})
        self.assertEqual(status, 200)

    def test_activate_agent_writes_project_yaml(self):
        """POST /api/config/{project}/toggle writes updated agents to project.yaml."""
        self._run('myproject', {'type': 'agent', 'name': 'office-manager', 'active': True})
        data = _read_project_yaml(self.project_dir)
        self.assertIn('office-manager', data['members']['agents'])

    def test_deactivate_agent_writes_project_yaml(self):
        """POST /api/config/{project}/toggle removes agent from project.yaml."""
        self._run('myproject', {'type': 'agent', 'name': 'auditor', 'active': False})
        data = _read_project_yaml(self.project_dir)
        self.assertNotIn('auditor', data['members']['agents'])


# ── Frontend: config.html toggleMembership and active/inactive rendering ─────

class TestConfigHtmlCatalogRendering(unittest.TestCase):
    """config.html must render all catalog items with active/inactive state and toggle handlers."""

    def setUp(self):
        self.content = _read_config_html()

    def test_toggle_membership_function_present(self):
        """config.html must define a toggleMembership function for click-to-toggle."""
        self.assertIn(
            'function toggleMembership',
            self.content,
            'config.html must define toggleMembership() for active/inactive item clicks',
        )

    def test_toggle_calls_toggle_endpoint(self):
        """toggleMembership must POST to the toggle API endpoint."""
        self.assertIn(
            '/toggle',
            self.content,
            'toggleMembership must call a /toggle API endpoint',
        )

    def test_agents_rendered_with_active_flag_in_render_project(self):
        """renderProject() must check a.active to determine item rendering state."""
        self.assertIn(
            'a.active',
            self.content,
            'renderProject() must use a.active to distinguish active from inactive agents',
        )

    def test_agents_rendered_with_active_flag_in_render_global(self):
        """renderGlobal() must check a.active to determine item rendering state."""
        # The a.active reference covers both renderGlobal and renderProject
        self.assertIn(
            'a.active',
            self.content,
            'renderGlobal() must use a.active to distinguish active from inactive agents',
        )

    def test_skills_rendered_with_active_flag(self):
        """Config screens must use s.active to render skill active/inactive state."""
        self.assertIn(
            's.active',
            self.content,
            'Config screens must use s.active to distinguish active from inactive skills',
        )

    def test_inactive_items_have_catalog_inactive_class(self):
        """Inactive catalog items must use item-catalog-inactive CSS class."""
        self.assertIn(
            'item-catalog-inactive',
            self.content,
            'Inactive catalog items must use item-catalog-inactive class',
        )

    def test_active_items_have_catalog_active_class(self):
        """Active catalog items must use item-catalog-active CSS class."""
        self.assertIn(
            'item-catalog-active',
            self.content,
            'Active catalog items must use item-catalog-active class',
        )

    def test_toggle_membership_called_on_inactive_item_click(self):
        """Clicking an inactive item must call toggleMembership with active=true."""
        self.assertIn(
            'toggleMembership',
            self.content,
            'Inactive item onclick must call toggleMembership to activate',
        )


# ── toggle_workgroup_membership ──────────────────────────────────────────────

def _make_workgroup_yaml(workgroup_yaml_path: str, agents: list, skills: list | None = None):
    os.makedirs(os.path.dirname(workgroup_yaml_path), exist_ok=True)
    data = {
        'name': os.path.basename(workgroup_yaml_path).replace('.yaml', ''),
        'description': 'Test workgroup',
        'lead': 'auditor',
        'members': {
            'agents': agents,
            'skills': skills or [],
        },
    }
    with open(workgroup_yaml_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _read_workgroup_yaml(workgroup_yaml_path: str) -> dict:
    with open(workgroup_yaml_path) as f:
        return yaml.safe_load(f)


class TestToggleWorkgroupMembership(unittest.TestCase):
    """toggle_workgroup_membership must add/remove agents and skills from workgroup YAML."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.yaml_path = os.path.join(self.tmp, 'backlog.yaml')
        _make_workgroup_yaml(self.yaml_path, agents=['auditor'], skills=['commit'])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_activate_agent_adds_to_agents(self):
        """toggle_workgroup_membership with active=True adds agent to workgroup YAML."""
        from orchestrator.config_reader import toggle_workgroup_membership
        toggle_workgroup_membership(self.yaml_path, 'agent', 'researcher', True)
        data = _read_workgroup_yaml(self.yaml_path)
        agent_names = [a['name'] if isinstance(a, dict) else a for a in data['members'].get('agents', [])]
        self.assertIn('researcher', agent_names)

    def test_deactivate_agent_removes_from_agents(self):
        """toggle_workgroup_membership with active=False removes agent from workgroup YAML."""
        from orchestrator.config_reader import toggle_workgroup_membership
        toggle_workgroup_membership(self.yaml_path, 'agent', 'auditor', False)
        data = _read_workgroup_yaml(self.yaml_path)
        agent_names = [a['name'] if isinstance(a, dict) else a for a in data['members'].get('agents', [])]
        self.assertNotIn('auditor', agent_names)

    def test_activate_skill_adds_to_skills(self):
        """toggle_workgroup_membership with active=True adds skill to workgroup YAML."""
        from orchestrator.config_reader import toggle_workgroup_membership
        toggle_workgroup_membership(self.yaml_path, 'skill', 'review-pr', True)
        data = _read_workgroup_yaml(self.yaml_path)
        self.assertIn('review-pr', data['members'].get('skills', []))

    def test_deactivate_skill_removes_from_skills(self):
        """toggle_workgroup_membership with active=False removes skill from workgroup YAML."""
        from orchestrator.config_reader import toggle_workgroup_membership
        toggle_workgroup_membership(self.yaml_path, 'skill', 'commit', False)
        data = _read_workgroup_yaml(self.yaml_path)
        self.assertNotIn('commit', data['members'].get('skills', []))


# ── _serialize_workgroup catalog expansion ────────────────────────────────────

class TestWorkgroupCatalogSerialization(unittest.TestCase):
    """_serialize_workgroup must emit full org catalog with active flags when detail=True."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_workgroup(self, agents: list):
        from orchestrator.config_reader import Workgroup
        return Workgroup(
            name='backlog',
            description='Test',
            lead='auditor',
            members_agents=agents,
        )

    def test_inactive_catalog_agents_appear_with_active_false(self):
        """Agents in org catalog but not in workgroup must appear with active=False."""
        bridge = _make_bridge(self.tmp)
        w = self._make_workgroup(agents=['auditor'])
        result = bridge._serialize_workgroup(
            w, detail=True,
            org_catalog_agents=['auditor', 'researcher'],
        )
        active_states = {a['name']: a['active'] for a in result['agents']}
        self.assertTrue(active_states['auditor'])
        self.assertFalse(active_states['researcher'])

    def test_active_workgroup_agents_have_active_true(self):
        """Agents in the workgroup must appear with active=True."""
        bridge = _make_bridge(self.tmp)
        w = self._make_workgroup(agents=['auditor', 'researcher'])
        result = bridge._serialize_workgroup(
            w, detail=True,
            org_catalog_agents=['auditor', 'researcher', 'strategist'],
        )
        active_states = {a['name']: a['active'] for a in result['agents']}
        self.assertTrue(active_states['auditor'])
        self.assertTrue(active_states['researcher'])
        self.assertFalse(active_states['strategist'])


# ── Workgroup toggle endpoint ─────────────────────────────────────────────────

class TestToggleWorkgroupEndpoint(unittest.TestCase):
    """POST /api/workgroups/{name}/toggle must add/remove membership and return 200."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        wg_dir = os.path.join(self.teaparty_home, 'workgroups')
        os.makedirs(wg_dir, exist_ok=True)
        self.wg_path = os.path.join(wg_dir, 'backlog.yaml')
        _make_workgroup_yaml(self.wg_path, agents=['auditor'], skills=['commit'])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, name: str, body: dict) -> tuple[int, dict]:
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge(
            teaparty_home=self.teaparty_home,
            static_dir=os.path.join(self.tmp, 'static'),
        )

        async def _call():
            request = MagicMock()
            request.match_info = {'name': name}
            request.rel_url.query.get = MagicMock(return_value=None)
            request.json = AsyncMock(return_value=body)
            response = await bridge._handle_workgroup_toggle(request)
            return response.status, json.loads(response.body)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_call())
        finally:
            loop.close()

    def test_activate_agent_returns_200(self):
        """POST /api/workgroups/{name}/toggle returns 200 when activating an agent."""
        status, _ = self._run('backlog', {'type': 'agent', 'name': 'researcher', 'active': True})
        self.assertEqual(status, 200)

    def test_activate_agent_writes_workgroup_yaml(self):
        """POST /api/workgroups/{name}/toggle writes updated agents to workgroup YAML."""
        self._run('backlog', {'type': 'agent', 'name': 'researcher', 'active': True})
        data = _read_workgroup_yaml(self.wg_path)
        agent_names = [a['name'] if isinstance(a, dict) else a for a in data['members'].get('agents', [])]
        self.assertIn('researcher', agent_names)

    def test_deactivate_agent_writes_workgroup_yaml(self):
        """POST /api/workgroups/{name}/toggle removes agent from workgroup YAML."""
        self._run('backlog', {'type': 'agent', 'name': 'auditor', 'active': False})
        data = _read_workgroup_yaml(self.wg_path)
        agent_names = [a['name'] if isinstance(a, dict) else a for a in data['members'].get('agents', [])]
        self.assertNotIn('auditor', agent_names)


# ── Local project skills active flag ─────────────────────────────────────────

class TestLocalProjectSkillsActiveFlag(unittest.TestCase):
    """Local project skills must reflect actual YAML membership, not always-active."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        self.project_dir = os.path.join(self.tmp, 'myproject')
        os.makedirs(self.project_dir)
        # Make management team with no skills
        _make_management_yaml(self.teaparty_home, agents=[])
        # Make project with only 'commit' registered in skills:
        _make_project_yaml(self.project_dir, agents=[], skills=['commit'])
        # Create two local skills on filesystem; only 'commit' is registered
        local_skills_dir = os.path.join(self.project_dir, '.claude', 'skills')
        _make_skill(local_skills_dir, 'commit')
        _make_skill(local_skills_dir, 'review-pr')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _get_skills(self):
        from orchestrator.config_reader import load_project_team, discover_skills
        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge(
            teaparty_home=self.teaparty_home,
            static_dir=os.path.join(self.tmp, 'static'),
        )
        team = load_project_team(self.project_dir)
        local_skills = discover_skills(os.path.join(self.project_dir, '.claude', 'skills'))
        import yaml as _yaml
        with open(os.path.join(self.project_dir, '.teaparty.local', 'project.yaml')) as _f:
            _proj_data = _yaml.safe_load(_f) or {}
        registered = _proj_data.get('members', {}).get('skills') or []
        result = bridge._serialize_project_team(
            team,
            org_agents=[],
            org_catalog_agents=[],
            local_skills=local_skills,
            registered_org_skills=registered,
            org_catalog_skills=[],
            teaparty_home=self.teaparty_home,
            project_dir=self.project_dir,
        )
        return {s['name']: s['active'] for s in result['skills']}

    def test_registered_local_skill_is_active(self):
        """A local skill that appears in project.yaml skills: must be active=True."""
        skill_states = self._get_skills()
        self.assertTrue(skill_states.get('commit'), 'commit is registered and must be active')

    def test_unregistered_local_skill_is_inactive(self):
        """A local skill NOT in project.yaml skills: must be active=False."""
        skill_states = self._get_skills()
        self.assertFalse(skill_states.get('review-pr'), 'review-pr is not registered and must be inactive')


# ── Hooks CSS highlighting ────────────────────────────────────────────────────

class TestHooksCatalogHighlighting(unittest.TestCase):
    """config.html must render hook items with item-catalog-active CSS class."""

    def setUp(self):
        self.content = _read_config_html()

    def test_hooks_rendered_with_catalog_active_in_render_global(self):
        """renderGlobal() hook items must use item-catalog-active CSS class."""
        # The class is applied to all shown hooks since they are all active
        self.assertIn(
            'item-catalog-active',
            self.content,
            'Hook items must use item-catalog-active to indicate they are active',
        )

    def test_render_workgroup_uses_active_flag_for_agents(self):
        """renderWorkgroup() must check a.active to render active/inactive agents."""
        self.assertIn(
            'a.active',
            self.content,
            'renderWorkgroup() must use a.active for catalog rendering',
        )

    def test_render_workgroup_uses_active_flag_for_skills(self):
        """renderWorkgroup() must check s.active to render active/inactive skills."""
        self.assertIn(
            's.active',
            self.content,
            'renderWorkgroup() must use s.active for catalog rendering',
        )

    def test_toggle_membership_handles_workgroup_scope(self):
        """toggleMembership must handle workgroup scope (wg: prefix)."""
        self.assertIn(
            "startsWith('wg:')",
            self.content,
            "toggleMembership must handle 'wg:' scope for workgroup toggle",
        )

    def test_hooks_rendered_with_active_flag(self):
        """Hook items must use h.active to determine active/inactive state."""
        self.assertIn(
            'h.active',
            self.content,
            'Hook items must check h.active for active/inactive rendering',
        )

    def test_yaml_hooks_have_toggle_handler(self):
        """YAML hooks (source === yaml) must have a toggle click handler."""
        self.assertIn(
            "h.source === 'yaml'",
            self.content,
            "YAML hooks must be identified by source === 'yaml' for toggle handler",
        )


class TestStylesCssCatalogClasses(unittest.TestCase):
    """styles.css must define item-catalog-active and item-catalog-inactive classes."""

    def setUp(self):
        self.content = _read_styles_css()

    def test_item_catalog_active_class_defined(self):
        """styles.css must define .item-catalog-active for highlighting active catalog items."""
        self.assertIn(
            '.item-catalog-active',
            self.content,
            'styles.css must define .item-catalog-active',
        )

    def test_item_catalog_inactive_class_defined(self):
        """styles.css must define .item-catalog-inactive for dimming inactive catalog items."""
        self.assertIn(
            '.item-catalog-inactive',
            self.content,
            'styles.css must define .item-catalog-inactive',
        )


if __name__ == '__main__':
    unittest.main()
