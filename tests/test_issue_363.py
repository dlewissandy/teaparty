"""Tests for issue #363: Project Lead — define agent and update project configs.

Acceptance criteria:
1. teaparty-lead.md exists in .claude/agents/
2. Project Lead has appropriate description, model, and dispatch capabilities
3. .teaparty.local/project.yaml uses lead: teaparty-lead (not office-manager)
4. The OM no longer serves as project lead for any project
5. Specification tests cover OM -> project-lead dispatch routing
"""
import os
import sys
import unittest
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config_reader import load_management_team, load_project_team

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENTS_DIR = os.path.join(_REPO_ROOT, '.claude', 'agents')
_TEAPARTY_HOME = os.path.join(_REPO_ROOT, '.teaparty')
_PROJECT_YAML = os.path.join(_REPO_ROOT, '.teaparty.local', 'project.yaml')
_TEAPARTY_LEAD_AGENT = os.path.join(_AGENTS_DIR, 'teaparty-lead.md')


def _parse_frontmatter(path: str) -> dict:
    """Extract YAML frontmatter between --- delimiters."""
    with open(path) as f:
        content = f.read()
    if not content.startswith('---'):
        return {}
    end = content.index('---', 3)
    return yaml.safe_load(content[3:end])


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ── Criterion 1: teaparty-lead.md exists ─────────────────────────────────────

class TestTeapartyLeadAgentFileExists(unittest.TestCase):
    """teaparty-lead.md must exist in .claude/agents/."""

    def test_agent_file_exists(self):
        self.assertTrue(
            os.path.isfile(_TEAPARTY_LEAD_AGENT),
            f"teaparty-lead.md must exist at {_TEAPARTY_LEAD_AGENT}",
        )


# ── Criterion 2: Agent has appropriate frontmatter ───────────────────────────

class TestTeapartyLeadFrontmatter(unittest.TestCase):
    """teaparty-lead.md must have the required frontmatter fields."""

    def setUp(self):
        if not os.path.isfile(_TEAPARTY_LEAD_AGENT):
            self.skipTest('teaparty-lead.md does not exist yet')
        self.fm = _parse_frontmatter(_TEAPARTY_LEAD_AGENT)

    def test_has_name_field(self):
        self.assertIn('name', self.fm, "teaparty-lead.md must have a 'name:' field")

    def test_name_is_teaparty_lead(self):
        self.assertEqual(
            self.fm.get('name'), 'teaparty-lead',
            "Agent name must be 'teaparty-lead'",
        )

    def test_has_description_field(self):
        self.assertIn('description', self.fm,
            "teaparty-lead.md must have a 'description:' field")

    def test_description_is_not_empty(self):
        self.assertTrue(
            self.fm.get('description', '').strip(),
            "description: must not be empty",
        )

    def test_has_model_field(self):
        self.assertIn('model', self.fm, "teaparty-lead.md must have a 'model:' field")

    def test_model_is_valid(self):
        valid_models = {'opus', 'sonnet', 'haiku'}
        self.assertIn(
            self.fm.get('model'), valid_models,
            f"model: must be one of {valid_models}",
        )

    def test_description_mentions_project_lead_role(self):
        """Description must signal the project lead role so the OM routes correctly."""
        desc = self.fm.get('description', '').lower()
        self.assertTrue(
            'project' in desc and ('lead' in desc or 'coordinator' in desc),
            "description must mention the project lead / coordinator role",
        )


# ── Criterion 3: project.yaml uses teaparty-lead ─────────────────────────────

class TestProjectYamlLeadIsTeapartyLead(unittest.TestCase):
    """project.yaml must have lead: teaparty-lead, not office-manager."""

    def setUp(self):
        self.data = _load_yaml(_PROJECT_YAML)

    def test_lead_field_exists(self):
        self.assertIn('lead', self.data, "project.yaml must have a 'lead:' field")

    def test_lead_is_teaparty_lead(self):
        self.assertEqual(
            self.data.get('lead'), 'teaparty-lead',
            "project.yaml lead: must be 'teaparty-lead'",
        )

    def test_lead_is_not_office_manager(self):
        self.assertNotEqual(
            self.data.get('lead'), 'office-manager',
            "project.yaml lead: must not be 'office-manager' — the OM is management lead, "
            "not project lead",
        )


# ── Criterion 4: OM not serving as project lead for any project ───────────────

class TestOMNotProjectLeadForAnyProject(unittest.TestCase):
    """The Office Manager must not be the lead in any project.yaml."""

    def test_teaparty_project_lead_is_not_om(self):
        data = _load_yaml(_PROJECT_YAML)
        self.assertNotEqual(
            data.get('lead'), 'office-manager',
            "TeaParty project.yaml lead: must not be 'office-manager'",
        )

    def test_om_agent_is_not_project_lead_in_config_reader(self):
        """load_project_team() must return a lead other than 'office-manager'."""
        team = load_project_team(_REPO_ROOT)
        self.assertNotEqual(
            team.lead, 'office-manager',
            "ProjectTeam.lead must not be 'office-manager' — OM is management lead only",
        )


# ── Criterion 5: OM → project-lead dispatch routing ─────────────────────────

class TestOMDispatchRoutingToProjectLead(unittest.TestCase):
    """Verify OM → Project Lead dispatch chain is structurally correct."""

    def setUp(self):
        self.mgmt = load_management_team(teaparty_home=_TEAPARTY_HOME)
        self.project = load_project_team(_REPO_ROOT)

    def test_teaparty_in_om_members_projects(self):
        """TeaParty must be in the OM's dispatch roster so it can route work to it."""
        self.assertIn(
            'TeaParty', self.mgmt.members_projects,
            "TeaParty must be in teaparty.yaml members.projects for OM dispatch",
        )

    def test_project_lead_is_set_on_project_team(self):
        """ProjectTeam.lead must be a non-empty string (the project lead agent name)."""
        self.assertTrue(
            self.project.lead and self.project.lead.strip(),
            "ProjectTeam.lead must be set to the project lead agent name",
        )

    def test_project_lead_agent_file_exists_for_om_dispatch_targets(self):
        """For every project the OM dispatches to, the project lead agent file must exist.

        The OM routes work to projects. Each project has a lead. That lead must
        be a real agent (file on disk) — otherwise the dispatch chain is broken.
        """
        registered = {p['name']: p for p in self.mgmt.projects}
        for project_name in self.mgmt.members_projects:
            self.assertIn(project_name, registered,
                f"OM dispatch target '{project_name}' is not in registered projects")
            project_entry = registered[project_name]
            config_rel = project_entry.get('config', '')
            project_path = project_entry['path']
            if config_rel:
                config_abs = os.path.join(project_path, config_rel)
            else:
                config_abs = os.path.join(project_path, '.teaparty.local', 'project.yaml')
            if not os.path.exists(config_abs):
                continue  # skip projects not on this machine
            project_data = _load_yaml(config_abs)
            lead = project_data.get('lead', '')
            self.assertTrue(lead, f"Project '{project_name}' project.yaml must have a lead:")
            self.assertNotEqual(
                lead, 'office-manager',
                f"Project '{project_name}' lead must not be 'office-manager'",
            )
            agent_file = os.path.join(_AGENTS_DIR, f'{lead}.md')
            self.assertTrue(
                os.path.isfile(agent_file),
                f"Project '{project_name}' lead agent '{lead}' must have a file at {agent_file}",
            )

    def test_project_lead_name_matches_agent_file(self):
        """The lead name in project.yaml must correspond to an agent file in .claude/agents/."""
        lead = self.project.lead
        agent_file = os.path.join(_AGENTS_DIR, f'{lead}.md')
        self.assertTrue(
            os.path.isfile(agent_file),
            f"Project lead '{lead}' must have an agent file at {agent_file}",
        )

    def test_om_lead_is_office_manager(self):
        """The management team lead must still be 'office-manager' (unchanged)."""
        self.assertEqual(
            self.mgmt.lead, 'office-manager',
            "Management team lead must be 'office-manager'",
        )

    def test_dispatch_chain_om_to_project_lead_is_not_identity(self):
        """OM lead must be different from the project lead — they are separate roles."""
        self.assertNotEqual(
            self.mgmt.lead, self.project.lead,
            "OM lead and project lead must be different agents — distinct roles in the hierarchy",
        )
