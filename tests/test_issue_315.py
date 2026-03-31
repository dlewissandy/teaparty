"""Tests for issue #315: Agent definitions: add skills allowlist field.

Acceptance criteria:
1. docs/proposals/configuration-team/examples/agent-definition.yaml includes skills:
   as a first-class frontmatter field (parseable YAML key, not just a comment).
2. The skills: field is a list type.
3. docs/proposals/configuration-team/proposal.md documents the enforcement model
   for the skills: allowlist, resolving "to be decided" on the default.
4. docs/proposals/team-configuration/examples/workgroup-coding.yaml has a comment
   that distinguishes workgroup-level skills: (catalog/dispatch) from the
   agent-level skills: allowlist.
5. docs/proposals/team-configuration/examples/workgroup-configuration.yaml has
   the same catalog-vs-allowlist distinction and the updated agent roster.
6. .teaparty/workgroups/configuration.yaml reflects the current Configuration Team
   roster (Project Specialist, Workgroup Specialist, Agent Specialist, Skills
   Specialist, Systems Engineer) and lists all skills in the catalog.
"""
import unittest
import yaml
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

_AGENT_DEF_YAML = _REPO_ROOT / 'docs/proposals/configuration-team/examples/agent-definition.yaml'
_PROPOSAL_MD = _REPO_ROOT / 'docs/proposals/configuration-team/proposal.md'
_WG_CODING_YAML = _REPO_ROOT / 'docs/proposals/team-configuration/examples/workgroup-coding.yaml'
_WG_CONFIG_YAML = _REPO_ROOT / 'docs/proposals/team-configuration/examples/workgroup-configuration.yaml'
_LIVE_CONFIG_YAML = _REPO_ROOT / '.teaparty/workgroups/configuration.yaml'


def _parse_frontmatter(path):
    """Return parsed YAML from the --- delimited frontmatter block of a file."""
    content = path.read_text()
    lines = content.split('\n')
    if not lines or lines[0].strip() != '---':
        return {}
    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == '---':
            end = i
            break
    if end is None:
        return {}
    return yaml.safe_load('\n'.join(lines[1:end])) or {}


# ── Criterion 1 & 2: skills: field in agent-definition.yaml ──────────────────

class TestAgentDefinitionSkillsField(unittest.TestCase):
    """agent-definition.yaml must declare skills: as a YAML key, not a comment."""

    def setUp(self):
        self.frontmatter = _parse_frontmatter(_AGENT_DEF_YAML)

    def test_skills_key_present_in_frontmatter(self):
        """skills: must be a parseable YAML key in the agent-definition.yaml frontmatter."""
        self.assertIn(
            'skills', self.frontmatter,
            'agent-definition.yaml must have skills: as a first-class frontmatter field — '
            'not only as a YAML comment. The field should be parseable by yaml.safe_load().',
        )

    def test_skills_value_is_list(self):
        """skills: value must be a list (may be empty or populated)."""
        skills = self.frontmatter.get('skills')
        self.assertIsInstance(
            skills, list,
            f'skills: must be a YAML list, got {type(skills).__name__}: {skills!r}',
        )


# ── Criterion 3: enforcement model in proposal.md ────────────────────────────

class TestProposalDocumentsEnforcement(unittest.TestCase):
    """proposal.md must document the skills: enforcement model and resolve
    the 'to be decided' question about the default behavior when the field
    is omitted."""

    def setUp(self):
        self.content = _PROPOSAL_MD.read_text()

    def test_proposal_documents_skills_allowlist_semantics(self):
        """proposal.md must describe skills: as an allowlist — not a suggestion."""
        self.assertIn(
            'allowlist', self.content,
            'proposal.md must describe the skills: field as an allowlist',
        )

    def test_proposal_documents_skill_ownership_model(self):
        """proposal.md must state that skills are registered to agents (not vice versa)."""
        self.assertIn(
            'registered to agents', self.content,
            'proposal.md must state that skills are registered to agents, '
            'not the other way around',
        )

    def test_proposal_maps_each_specialist_to_its_crud_skills(self):
        """proposal.md must list each specialist and the skills it owns."""
        expected_specialists = [
            'Project Specialist',
            'Workgroup Specialist',
            'Agent Specialist',
            'Skills Specialist',
            'Systems Engineer',
        ]
        for specialist in expected_specialists:
            self.assertIn(
                specialist, self.content,
                f'proposal.md must reference {specialist!r} and its skill assignments',
            )

    def test_proposal_documents_enforcement_model(self):
        """proposal.md must state how the skills: field is enforced.

        The issue explicitly asks to document whether enforcement is Claude Code
        native, TeaParty dispatch layer, or convention with explicit contract.
        """
        # Must explain enforcement mechanism
        has_enforcement = (
            'dispatch' in self.content.lower() and
            ('enforc' in self.content.lower() or 'convention' in self.content.lower())
        )
        self.assertTrue(
            has_enforcement,
            'proposal.md must document the enforcement model for skills: — '
            'whether it is Claude Code native, TeaParty dispatch layer, or convention. '
            'The issue explicitly requires this to be documented.',
        )

    def test_proposal_resolves_default_when_skills_field_is_omitted(self):
        """proposal.md must resolve the 'to be decided' question: what does omitting
        skills: mean? The issue leaves this open; the proposal must decide."""
        # Must state what happens when skills: is absent
        has_default = (
            'no skills' in self.content.lower() or
            'no `skills:` field' in self.content or
            'no skills: field' in self.content
        )
        self.assertTrue(
            has_default,
            'proposal.md must state what omitting the skills: field means — '
            'the issue leaves it as "to be decided" and the proposal must resolve it.',
        )

    def test_proposal_documents_human_participant_management_is_out_of_scope(self):
        """proposal.md must note human participant management is out of scope."""
        self.assertIn(
            'out of scope', self.content,
            'proposal.md must note that human participant management is out of scope',
        )


# ── Criterion 4: workgroup-coding.yaml catalog vs allowlist distinction ───────

class TestWorkgroupCodingYamlCatalogComment(unittest.TestCase):
    """workgroup-coding.yaml must have a comment distinguishing the workgroup-level
    skills: field (catalog for dispatch) from the agent-level skills: allowlist."""

    def setUp(self):
        self.content = _WG_CODING_YAML.read_text()

    def test_comment_clarifies_skills_is_not_access_control(self):
        """The skills: section must be preceded by a comment stating it is NOT an ACL."""
        # The comment must make clear this is catalog/dispatch context, not access control.
        # Check for either "NOT an access control" or "not an access control" phrasing.
        has_clarification = (
            'NOT an access control' in self.content
            or 'not an access control' in self.content
            or 'catalog' in self.content.lower()
        )
        self.assertTrue(
            has_clarification,
            'workgroup-coding.yaml must have a comment clarifying that the workgroup-level '
            'skills: is a catalog/dispatch list, not an access control list. '
            'Per-agent access is controlled by skills: in each agent definition.',
        )

    def test_comment_points_to_agent_definitions_for_per_agent_access(self):
        """The comment must point readers to per-agent agent definitions for access control."""
        has_pointer = (
            'agent' in self.content.lower() and
            ('definition' in self.content.lower() or 'allowlist' in self.content.lower())
        )
        self.assertTrue(
            has_pointer,
            'workgroup-coding.yaml comment must direct readers to agent definitions '
            'for per-agent skill access control',
        )


# ── Criterion 5: workgroup-configuration.yaml catalog vs allowlist + roster ───

class TestWorkgroupConfigurationYaml(unittest.TestCase):
    """workgroup-configuration.yaml must have the updated agent roster and
    the catalog-vs-allowlist distinction."""

    def setUp(self):
        self.content = _WG_CONFIG_YAML.read_text()
        self.data = yaml.safe_load(self.content)

    def test_comment_clarifies_skills_is_not_access_control(self):
        """The skills: section must be preceded by a comment that it is NOT an ACL."""
        has_clarification = (
            'NOT an access control' in self.content
            or 'not an access control' in self.content
            or 'catalog' in self.content.lower()
        )
        self.assertTrue(
            has_clarification,
            'workgroup-configuration.yaml must have a comment clarifying that the '
            'workgroup-level skills: is not an access control list',
        )

    def test_agent_roster_includes_project_specialist(self):
        """Configuration Team roster must include Project Specialist."""
        names = [a['name'] for a in self.data.get('agents', [])]
        self.assertIn(
            'Project Specialist', names,
            f'workgroup-configuration.yaml agents must include Project Specialist, got: {names}',
        )

    def test_agent_roster_includes_workgroup_specialist(self):
        """Configuration Team roster must include Workgroup Specialist."""
        names = [a['name'] for a in self.data.get('agents', [])]
        self.assertIn(
            'Workgroup Specialist', names,
            f'workgroup-configuration.yaml agents must include Workgroup Specialist, got: {names}',
        )

    def test_agent_roster_includes_agent_specialist(self):
        """Configuration Team roster must include Agent Specialist."""
        names = [a['name'] for a in self.data.get('agents', [])]
        self.assertIn(
            'Agent Specialist', names,
            f'workgroup-configuration.yaml agents must include Agent Specialist, got: {names}',
        )

    def test_agent_roster_includes_skills_specialist(self):
        """Configuration Team roster must include Skills Specialist."""
        names = [a['name'] for a in self.data.get('agents', [])]
        self.assertIn(
            'Skills Specialist', names,
            f'workgroup-configuration.yaml agents must include Skills Specialist, got: {names}',
        )

    def test_agent_roster_does_not_use_old_names(self):
        """Old agent names (Skill Architect, Agent Designer) must not appear."""
        names = [a['name'] for a in self.data.get('agents', [])]
        self.assertNotIn(
            'Skill Architect', names,
            'workgroup-configuration.yaml must use Skills Specialist, not Skill Architect',
        )
        self.assertNotIn(
            'Agent Designer', names,
            'workgroup-configuration.yaml must use Agent Specialist, not Agent Designer',
        )

    def test_skills_catalog_includes_full_crud_surface(self):
        """The workgroup-level skills catalog must list all CRUD skills for all domains."""
        skills = self.data.get('skills', [])
        expected = [
            'create-project', 'edit-project', 'remove-project',
            'create-workgroup', 'edit-workgroup', 'remove-workgroup',
            'create-agent', 'edit-agent', 'remove-agent',
            'create-skill', 'edit-skill', 'remove-skill', 'optimize-skill',
            'create-hook', 'edit-hook', 'remove-hook',
            'create-scheduled-task', 'edit-scheduled-task', 'remove-scheduled-task',
        ]
        for skill in expected:
            self.assertIn(
                skill, skills,
                f'workgroup-configuration.yaml skills catalog must include {skill!r}',
            )


# ── Criterion 6: .teaparty/workgroups/configuration.yaml live config ─────────

class TestLiveConfigurationWorkgroup(unittest.TestCase):
    """.teaparty/workgroups/configuration.yaml must reflect the current agent
    roster and the full skills catalog."""

    def setUp(self):
        self.data = yaml.safe_load(_LIVE_CONFIG_YAML.read_text())

    def test_live_config_has_six_agents(self):
        """Configuration Team must have 6 agents: lead + 5 specialists."""
        agents = self.data.get('agents', [])
        self.assertEqual(
            len(agents), 6,
            f'Expected 6 agents (lead + 5 specialists), got {len(agents)}: '
            f'{[a["name"] for a in agents]}',
        )

    def test_live_config_includes_project_specialist(self):
        """Live config must include Project Specialist."""
        names = [a['name'] for a in self.data.get('agents', [])]
        self.assertIn('Project Specialist', names)

    def test_live_config_includes_workgroup_specialist(self):
        """Live config must include Workgroup Specialist."""
        names = [a['name'] for a in self.data.get('agents', [])]
        self.assertIn('Workgroup Specialist', names)

    def test_live_config_includes_agent_specialist(self):
        """Live config must include Agent Specialist."""
        names = [a['name'] for a in self.data.get('agents', [])]
        self.assertIn('Agent Specialist', names)

    def test_live_config_includes_skills_specialist(self):
        """Live config must include Skills Specialist."""
        names = [a['name'] for a in self.data.get('agents', [])]
        self.assertIn('Skills Specialist', names)

    def test_live_config_does_not_use_old_names(self):
        """Old agent names must not appear in the live config."""
        names = [a['name'] for a in self.data.get('agents', [])]
        self.assertNotIn('Skill Architect', names)
        self.assertNotIn('Agent Designer', names)

    def test_live_config_skills_catalog_includes_optimize_skill(self):
        """optimize-skill must be in the live catalog (it is a distinct operation)."""
        skills = self.data.get('skills', [])
        self.assertIn(
            'optimize-skill', skills,
            'optimize-skill is a distinct operation from edit-skill and must be in the catalog',
        )

    def test_live_config_skills_catalog_includes_scheduled_task_ops(self):
        """The live catalog must include scheduled-task CRUD skills."""
        skills = self.data.get('skills', [])
        for skill in ('create-scheduled-task', 'edit-scheduled-task', 'remove-scheduled-task'):
            self.assertIn(skill, skills, f'live config must include {skill!r}')


# ── Criterion: existing .claude/agents/ definitions ──────────────────────────

class TestExistingAgentDefinitionsAssessed(unittest.TestCase):
    """The issue requires updating any existing agent definitions that should have
    a skills allowlist. The management team agents (auditor, researcher, strategist,
    office-manager) do not auto-invoke skills — they are invoked BY skills, or they
    dispatch via tools (AskTeam), not via the skills mechanism. Per the spec, omitting
    skills: means no auto-invocable skills. These agents are correctly left without
    the field.

    These tests encode that decision explicitly so the audit trail shows it was made
    deliberately, not by omission.
    """

    _AGENTS_DIR = _REPO_ROOT / '.claude/agents'

    def _get_frontmatter(self, name):
        return _parse_frontmatter(self._AGENTS_DIR / f'{name}.md')

    def test_auditor_has_no_skills_field(self):
        """The auditor agent must not have a skills: field.

        The auditor is the target of audit-issue skill invocations — it does not
        itself invoke skills. Omitting skills: is the correct declaration that it
        has no auto-invocable skills.
        """
        fm = self._get_frontmatter('auditor')
        self.assertNotIn(
            'skills', fm,
            'auditor.md must not have a skills: field — it is invoked by skills, '
            'not an invoker of skills. Omitting skills: correctly declares no skill access.',
        )

    def test_researcher_has_no_skills_field(self):
        """The researcher agent must not have a skills: field.

        The researcher is a read-only specialist invoked via the research skill.
        It does not invoke skills itself.
        """
        fm = self._get_frontmatter('researcher')
        self.assertNotIn(
            'skills', fm,
            'researcher.md must not have a skills: field — it is a read-only specialist '
            'that does not auto-invoke skills.',
        )

    def test_strategist_has_no_skills_field(self):
        """The strategist agent must not have a skills: field.

        The strategist is a read-only specialist. It does not auto-invoke skills.
        """
        fm = self._get_frontmatter('strategist')
        self.assertNotIn(
            'skills', fm,
            'strategist.md must not have a skills: field — it is a read-only specialist '
            'that does not auto-invoke skills.',
        )

    def test_office_manager_does_not_have_crud_configuration_skills(self):
        """The office-manager agent must not have Configuration Team CRUD skills.

        The office manager dispatches configuration work to the Configuration Team via
        the AskTeam tool, not via skills. It does not auto-invoke CRUD skills like
        create-agent, edit-skill, create-hook, etc.

        It may have workflow dialog skills (add-project, create-project) for the
        dashboard onboarding flow — these are not CRUD configuration skills.
        """
        fm = self._get_frontmatter('office-manager')
        crud_skills = ['create-agent', 'edit-agent', 'create-skill', 'edit-skill',
                       'create-hook', 'create-workgroup', 'edit-workgroup']
        skills = fm.get('skills') or []
        for crud in crud_skills:
            self.assertNotIn(
                crud, skills,
                f'office-manager.md must not have Configuration Team CRUD skill {crud!r} — '
                'configuration work routes to the Configuration Team via AskTeam, not via skills.',
            )


if __name__ == '__main__':
    unittest.main()
