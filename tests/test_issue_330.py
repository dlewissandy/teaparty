"""Tests for issue #330: Config screen file-backed items open in Artifacts viewer on click.

Acceptance criteria:
1. _serialize_management_team agent entries include 'file' with absolute path to .claude/agents/{name}.md
2. _serialize_project_team agent entries include 'file' — local/generated from project_dir, shared from teaparty_home
3. _serialize_management_team skill entries include 'file' with absolute path to .claude/skills/{name}/SKILL.md
4. _serialize_project_team skill entries include 'file' — local from project_dir, shared from teaparty_home, missing as None
5. _serialize_management_team hook entries include 'file' — handler script if command is a file, else teaparty.yaml
6. _serialize_project_team hook entries include 'file' — handler script if command is a file, else project.yaml
7. _serialize_management_team scheduled task entries include 'file' pointing to skill's SKILL.md
8. _serialize_project_team scheduled task entries include 'file' pointing to skill's SKILL.md (source-aware)
"""
import os
import tempfile
import unittest
import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_bridge(teaparty_home: str) -> object:
    from bridge.server import TeaPartyBridge
    static_dir = os.path.join(teaparty_home, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)


def _make_management_team(teaparty_home: str, agents=None, hooks=None, scheduled=None):
    from orchestrator.config_reader import load_management_team
    data = {
        'name': 'Management Team',
        'description': 'Test org',
        'lead': 'office-manager',
        'decider': 'darrell',
        'agents': agents or ['office-manager', 'auditor'],
        'humans': [{'name': 'darrell', 'role': 'decider'}],
        'skills': ['sprint-plan'],
        'hooks': hooks or [{'event': 'PreToolUse', 'matcher': 'Bash', 'type': 'command'}],
        'scheduled': scheduled or [{'name': 'nightly', 'schedule': '0 2 * * *', 'skill': 'audit', 'enabled': True}],
        'workgroups': [],
        'teams': [],
    }
    with open(os.path.join(teaparty_home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f)
    return load_management_team(teaparty_home=teaparty_home)


def _make_project_team(project_dir: str, agents=None, hooks=None, scheduled=None,
                       skills=None):
    from orchestrator.config_reader import load_project_team
    tp_local = os.path.join(project_dir, '.teaparty.local')
    os.makedirs(tp_local, exist_ok=True)
    data = {
        'name': 'Test Project',
        'description': 'A test project',
        'lead': 'project-lead',
        'decider': 'darrell',
        'agents': agents or ['project-lead', 'reviewer'],
        'humans': [{'name': 'Alice', 'role': 'advisor'}],
        'skills': skills or ['fix-issue'],
        'hooks': hooks or [{'event': 'Stop', 'type': 'agent'}],
        'scheduled': scheduled or [{'name': 'health', 'schedule': '*/30 * * * *', 'skill': 'audit', 'enabled': True}],
        'workgroups': [],
    }
    with open(os.path.join(tp_local, 'project.yaml'), 'w') as f:
        yaml.dump(data, f)
    return load_project_team(project_dir)


def _make_skill(skills_dir: str, name: str) -> None:
    skill_path = os.path.join(skills_dir, name)
    os.makedirs(skill_path, exist_ok=True)
    with open(os.path.join(skill_path, 'SKILL.md'), 'w') as f:
        f.write(f'# {name}\n')


def _make_agent_file(agents_dir: str, name: str) -> None:
    os.makedirs(agents_dir, exist_ok=True)
    with open(os.path.join(agents_dir, f'{name}.md'), 'w') as f:
        f.write(f'# {name}\n')


# ── Criterion 1: Management team agents have 'file' ──────────────────────────

class TestManagementTeamAgentsHaveFilePath(unittest.TestCase):
    """_serialize_management_team must include 'file' for each agent entry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(self.tmp)
        self.team = _make_management_team(self.tmp, agents=['office-manager', 'auditor'])

    def test_agent_entries_are_dicts_not_strings(self):
        """After #330, agents must be objects with 'name' and 'file', not plain strings."""
        result = self.bridge._serialize_management_team(
            self.team, discovered_skills=[], teaparty_home=self.tmp
        )
        agents = result['agents']
        self.assertTrue(len(agents) > 0)
        for a in agents:
            self.assertIsInstance(a, dict, 'Agent entry must be a dict with name and file')

    def test_agent_entry_has_name_field(self):
        """Each agent entry must have a 'name' key."""
        result = self.bridge._serialize_management_team(
            self.team, discovered_skills=[], teaparty_home=self.tmp
        )
        for a in result['agents']:
            self.assertIn('name', a)

    def test_agent_entry_has_file_field(self):
        """Each agent entry must have a 'file' key."""
        result = self.bridge._serialize_management_team(
            self.team, discovered_skills=[], teaparty_home=self.tmp
        )
        for a in result['agents']:
            self.assertIn('file', a, f'Agent entry missing "file": {a}')

    def test_agent_file_points_to_agents_md(self):
        """Agent 'file' must be absolute path to .claude/agents/{name}.md in teaparty_home."""
        result = self.bridge._serialize_management_team(
            self.team, discovered_skills=[], teaparty_home=self.tmp
        )
        for a in result['agents']:
            expected = os.path.join(self.tmp, '.claude', 'agents', f'{a["name"]}.md')
            self.assertEqual(a['file'], expected,
                f'Agent {a["name"]} file path mismatch')

    def test_agent_file_is_absolute_path(self):
        """Agent file path must be absolute."""
        result = self.bridge._serialize_management_team(
            self.team, discovered_skills=[], teaparty_home=self.tmp
        )
        for a in result['agents']:
            self.assertTrue(os.path.isabs(a['file']),
                f'Agent file path must be absolute: {a["file"]}')


# ── Criterion 2: Project team agents have 'file' ─────────────────────────────

class TestProjectTeamAgentsHaveFilePath(unittest.TestCase):
    """_serialize_project_team must include 'file' for each agent entry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(self.tmp)
        self.project_dir = os.path.join(self.tmp, 'my-project')
        os.makedirs(self.project_dir)
        # Org has auditor; project has project-lead (local) and auditor (shared)
        self.org_agents = ['auditor']
        self.team = _make_project_team(
            self.project_dir,
            agents=['project-lead', 'auditor'],
        )

    def test_project_agent_entries_are_dicts_with_file(self):
        """All project agent entries must include 'file'."""
        result = self.bridge._serialize_project_team(
            self.team,
            org_agents=self.org_agents,
            local_skills=[],
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        for a in result['agents']:
            self.assertIn('file', a, f'Agent entry missing "file": {a}')

    def test_local_agent_file_resolves_from_project_dir(self):
        """A local (non-org) agent's 'file' resolves under project_dir/.claude/agents/."""
        result = self.bridge._serialize_project_team(
            self.team,
            org_agents=['auditor'],  # project-lead is local
            local_skills=[],
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        agent = next(a for a in result['agents'] if a['name'] == 'project-lead')
        expected = os.path.join(self.project_dir, '.claude', 'agents', 'project-lead.md')
        self.assertEqual(agent['file'], expected)

    def test_shared_agent_file_resolves_from_teaparty_home(self):
        """A shared (org) agent's 'file' resolves under teaparty_home/.claude/agents/."""
        result = self.bridge._serialize_project_team(
            self.team,
            org_agents=['auditor'],  # auditor is shared
            local_skills=[],
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        agent = next(a for a in result['agents'] if a['name'] == 'auditor')
        expected = os.path.join(self.tmp, '.claude', 'agents', 'auditor.md')
        self.assertEqual(agent['file'], expected)

    def test_generated_lead_agent_file_resolves_from_project_dir(self):
        """The generated project lead agent's 'file' resolves under project_dir."""
        result = self.bridge._serialize_project_team(
            self.team,
            org_agents=['auditor'],
            local_skills=[],
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        lead_agent = next(a for a in result['agents'] if a['name'] == self.team.lead)
        expected = os.path.join(self.project_dir, '.claude', 'agents', f'{self.team.lead}.md')
        self.assertEqual(lead_agent['file'], expected)


# ── Criterion 3: Management team skills have 'file' ──────────────────────────

class TestManagementTeamSkillsHaveFilePath(unittest.TestCase):
    """_serialize_management_team must include 'file' for each skill entry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(self.tmp)
        self.team = _make_management_team(self.tmp)
        # Create a real skill on disk
        org_skills_dir = os.path.join(self.tmp, '.claude', 'skills')
        _make_skill(org_skills_dir, 'audit')
        _make_skill(org_skills_dir, 'sprint-plan')

    def test_skill_entries_are_dicts_not_strings(self):
        """Skill entries must be dicts with 'name' and 'file', not plain strings."""
        org_skills_dir = os.path.join(self.tmp, '.claude', 'skills')
        from orchestrator.config_reader import discover_skills
        discovered = discover_skills(org_skills_dir)
        result = self.bridge._serialize_management_team(
            self.team, discovered_skills=discovered, teaparty_home=self.tmp
        )
        for s in result['skills']:
            self.assertIsInstance(s, dict, f'Skill entry must be a dict: {s}')

    def test_skill_entry_has_file_field(self):
        """Each skill entry must have a 'file' key."""
        org_skills_dir = os.path.join(self.tmp, '.claude', 'skills')
        from orchestrator.config_reader import discover_skills
        discovered = discover_skills(org_skills_dir)
        result = self.bridge._serialize_management_team(
            self.team, discovered_skills=discovered, teaparty_home=self.tmp
        )
        for s in result['skills']:
            self.assertIn('file', s, f'Skill entry missing "file": {s}')

    def test_skill_file_points_to_skill_md(self):
        """Skill 'file' must be absolute path to .claude/skills/{name}/SKILL.md."""
        org_skills_dir = os.path.join(self.tmp, '.claude', 'skills')
        from orchestrator.config_reader import discover_skills
        discovered = discover_skills(org_skills_dir)
        result = self.bridge._serialize_management_team(
            self.team, discovered_skills=discovered, teaparty_home=self.tmp
        )
        for s in result['skills']:
            expected = os.path.join(self.tmp, '.claude', 'skills', s['name'], 'SKILL.md')
            self.assertEqual(s['file'], expected,
                f'Skill {s["name"]} file path mismatch')


# ── Criterion 4: Project team skills have 'file' ─────────────────────────────

class TestProjectTeamSkillsHaveFilePath(unittest.TestCase):
    """_serialize_project_team must include 'file' for each skill entry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(self.tmp)
        self.project_dir = os.path.join(self.tmp, 'my-project')
        os.makedirs(self.project_dir)
        # Create local skill
        local_skills_dir = os.path.join(self.project_dir, '.claude', 'skills')
        _make_skill(local_skills_dir, 'local-skill')
        # Create org skill
        org_skills_dir = os.path.join(self.tmp, '.claude', 'skills')
        _make_skill(org_skills_dir, 'audit')
        self.team = _make_project_team(self.project_dir, skills=['audit'])

    def test_local_skill_file_resolves_from_project_dir(self):
        """A local skill's 'file' resolves under project_dir/.claude/skills/{name}/SKILL.md."""
        result = self.bridge._serialize_project_team(
            self.team,
            org_agents=[],
            local_skills=['local-skill'],
            registered_org_skills=['audit'],
            org_catalog_skills=['audit'],
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        skill = next(s for s in result['skills'] if s['name'] == 'local-skill')
        expected = os.path.join(self.project_dir, '.claude', 'skills', 'local-skill', 'SKILL.md')
        self.assertEqual(skill['file'], expected)

    def test_shared_skill_file_resolves_from_teaparty_home(self):
        """A shared (org) skill's 'file' resolves under teaparty_home/.claude/skills/{name}/SKILL.md."""
        result = self.bridge._serialize_project_team(
            self.team,
            org_agents=[],
            local_skills=['local-skill'],
            registered_org_skills=['audit'],
            org_catalog_skills=['audit'],
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        skill = next(s for s in result['skills'] if s['name'] == 'audit')
        expected = os.path.join(self.tmp, '.claude', 'skills', 'audit', 'SKILL.md')
        self.assertEqual(skill['file'], expected)

    def test_missing_skill_has_null_file(self):
        """A skill declared in project.yaml but not in org catalog has file=None."""
        result = self.bridge._serialize_project_team(
            self.team,
            org_agents=[],
            local_skills=[],
            registered_org_skills=['nonexistent-skill'],
            org_catalog_skills=[],  # not in catalog
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        skill = next((s for s in result['skills'] if s['name'] == 'nonexistent-skill'), None)
        self.assertIsNotNone(skill, 'Missing skill must still appear in result')
        self.assertIsNone(skill['file'], 'Missing skill file must be None')


# ── Criterion 5: Management team hooks have 'file' ───────────────────────────

class TestManagementTeamHooksHaveFilePath(unittest.TestCase):
    """_serialize_management_team must include 'file' for each hook entry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(self.tmp)

    def test_hook_without_command_falls_back_to_teaparty_yaml(self):
        """A hook with no command field gets file = teaparty.yaml."""
        hooks = [{'event': 'PreToolUse', 'matcher': 'Bash', 'type': 'command'}]
        team = _make_management_team(self.tmp, hooks=hooks)
        result = self.bridge._serialize_management_team(
            team, discovered_skills=[], teaparty_home=self.tmp
        )
        h = result['hooks'][0]
        self.assertIn('file', h, 'Hook entry must have a "file" key')
        expected = os.path.join(self.tmp, 'teaparty.yaml')
        self.assertEqual(h['file'], expected)

    def test_hook_with_nonfile_command_falls_back_to_teaparty_yaml(self):
        """A hook whose command is a shell string (not a file) gets file = teaparty.yaml."""
        hooks = [{'event': 'PreToolUse', 'matcher': 'Bash', 'type': 'command',
                  'command': 'echo hello'}]
        team = _make_management_team(self.tmp, hooks=hooks)
        result = self.bridge._serialize_management_team(
            team, discovered_skills=[], teaparty_home=self.tmp
        )
        h = result['hooks'][0]
        expected = os.path.join(self.tmp, 'teaparty.yaml')
        self.assertEqual(h['file'], expected)

    def test_hook_with_script_file_command_resolves_to_script(self):
        """A hook whose command is a path to an existing file gets file = that absolute path."""
        # Create a script file
        script = os.path.join(self.tmp, 'my-hook.sh')
        with open(script, 'w') as f:
            f.write('#!/bin/sh\n')
        hooks = [{'event': 'PreToolUse', 'matcher': 'Bash', 'type': 'command',
                  'command': script}]
        team = _make_management_team(self.tmp, hooks=hooks)
        result = self.bridge._serialize_management_team(
            team, discovered_skills=[], teaparty_home=self.tmp
        )
        h = result['hooks'][0]
        self.assertEqual(h['file'], script)


# ── Criterion 6: Project team hooks have 'file' ──────────────────────────────

class TestProjectTeamHooksHaveFilePath(unittest.TestCase):
    """_serialize_project_team must include 'file' for each hook entry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(self.tmp)
        self.project_dir = os.path.join(self.tmp, 'my-project')
        os.makedirs(self.project_dir)

    def test_hook_without_command_falls_back_to_project_yaml(self):
        """A project hook with no command field gets file = project.yaml path."""
        hooks = [{'event': 'Stop', 'type': 'agent'}]
        team = _make_project_team(self.project_dir, hooks=hooks)
        result = self.bridge._serialize_project_team(
            team,
            org_agents=[],
            local_skills=[],
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        h = result['hooks'][0]
        self.assertIn('file', h, 'Hook entry must have a "file" key')
        expected = os.path.join(self.project_dir, '.teaparty.local', 'project.yaml')
        self.assertEqual(h['file'], expected)

    def test_hook_with_script_file_command_resolves_to_script(self):
        """A project hook whose command is a file path resolves to that file."""
        script = os.path.join(self.project_dir, 'hook.sh')
        with open(script, 'w') as f:
            f.write('#!/bin/sh\n')
        hooks = [{'event': 'Stop', 'type': 'command', 'command': script}]
        team = _make_project_team(self.project_dir, hooks=hooks)
        result = self.bridge._serialize_project_team(
            team,
            org_agents=[],
            local_skills=[],
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        h = result['hooks'][0]
        self.assertEqual(h['file'], script)


# ── Criterion 7: Management team scheduled tasks have 'file' ─────────────────

class TestManagementTeamScheduledTasksHaveFilePath(unittest.TestCase):
    """_serialize_management_team must include 'file' for each scheduled task."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(self.tmp)
        org_skills_dir = os.path.join(self.tmp, '.claude', 'skills')
        _make_skill(org_skills_dir, 'audit')

    def test_scheduled_task_has_file_field(self):
        """Each scheduled task entry must have a 'file' key."""
        scheduled = [{'name': 'nightly', 'schedule': '0 2 * * *', 'skill': 'audit', 'enabled': True}]
        team = _make_management_team(self.tmp, scheduled=scheduled)
        result = self.bridge._serialize_management_team(
            team, discovered_skills=[], teaparty_home=self.tmp
        )
        task = result['scheduled'][0]
        self.assertIn('file', task, 'Scheduled task entry must have a "file" key')

    def test_scheduled_task_file_points_to_skill_md(self):
        """Scheduled task 'file' must point to the skill's SKILL.md in teaparty_home."""
        scheduled = [{'name': 'nightly', 'schedule': '0 2 * * *', 'skill': 'audit', 'enabled': True}]
        team = _make_management_team(self.tmp, scheduled=scheduled)
        result = self.bridge._serialize_management_team(
            team, discovered_skills=[], teaparty_home=self.tmp
        )
        task = result['scheduled'][0]
        expected = os.path.join(self.tmp, '.claude', 'skills', 'audit', 'SKILL.md')
        self.assertEqual(task['file'], expected)

    def test_scheduled_task_with_unknown_skill_has_none_file(self):
        """A scheduled task whose skill doesn't exist in org catalog has file=None."""
        scheduled = [{'name': 'unknown', 'schedule': '0 2 * * *', 'skill': 'nonexistent', 'enabled': True}]
        team = _make_management_team(self.tmp, scheduled=scheduled)
        result = self.bridge._serialize_management_team(
            team, discovered_skills=[], teaparty_home=self.tmp
        )
        task = result['scheduled'][0]
        self.assertIsNone(task['file'],
            'Scheduled task with unknown skill must have file=None')


# ── Criterion 8: Project team scheduled tasks have 'file' ────────────────────

class TestProjectTeamScheduledTasksHaveFilePath(unittest.TestCase):
    """_serialize_project_team must include 'file' for each scheduled task."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(self.tmp)
        self.project_dir = os.path.join(self.tmp, 'my-project')
        os.makedirs(self.project_dir)
        org_skills_dir = os.path.join(self.tmp, '.claude', 'skills')
        _make_skill(org_skills_dir, 'audit')

    def test_project_scheduled_task_file_resolves_from_org_catalog(self):
        """Project scheduled task that invokes an org skill resolves to org skill SKILL.md."""
        scheduled = [{'name': 'health', 'schedule': '*/30 * * * *', 'skill': 'audit', 'enabled': True}]
        team = _make_project_team(self.project_dir, scheduled=scheduled)
        result = self.bridge._serialize_project_team(
            team,
            org_agents=[],
            local_skills=[],
            registered_org_skills=['audit'],
            org_catalog_skills=['audit'],
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        task = result['scheduled'][0]
        self.assertIn('file', task)
        expected = os.path.join(self.tmp, '.claude', 'skills', 'audit', 'SKILL.md')
        self.assertEqual(task['file'], expected)

    def test_project_scheduled_task_file_resolves_from_local_skills_first(self):
        """Project scheduled task invoking a local skill resolves to project skill SKILL.md."""
        local_skills_dir = os.path.join(self.project_dir, '.claude', 'skills')
        _make_skill(local_skills_dir, 'local-audit')
        scheduled = [{'name': 'local', 'schedule': '0 * * * *', 'skill': 'local-audit', 'enabled': True}]
        team = _make_project_team(self.project_dir, scheduled=scheduled)
        result = self.bridge._serialize_project_team(
            team,
            org_agents=[],
            local_skills=['local-audit'],
            teaparty_home=self.tmp,
            project_dir=self.project_dir,
        )
        task = result['scheduled'][0]
        expected = os.path.join(self.project_dir, '.claude', 'skills', 'local-audit', 'SKILL.md')
        self.assertEqual(task['file'], expected)
