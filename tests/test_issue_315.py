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
    """workgroup-coding.yaml must NOT have a workgroup-level skills: field.
    Per the workgroup-model proposal, skills are selected per agent, not per workgroup."""

    def setUp(self):
        self.content = _WG_CODING_YAML.read_text()
        self.data = yaml.safe_load(self.content)

    def test_comment_clarifies_skills_is_not_access_control(self):
        """workgroup-coding.yaml must not have a top-level skills: field.
        Skills are per-agent in the new schema — no workgroup-level skills list."""
        self.assertNotIn(
            'skills',
            self.data,
            'workgroup-coding.yaml must not have a top-level skills: field '
            '(per workgroup-model proposal: skills are selected per agent)',
        )

    def test_comment_points_to_agent_definitions_for_per_agent_access(self):
        """workgroup-coding.yaml must use members.agents (new schema), not flat agents:."""
        members = self.data.get('members', {})
        self.assertIn(
            'agents',
            members,
            'workgroup-coding.yaml must have members.agents (new schema)',
        )


# ── Criterion 5: workgroup-configuration.yaml catalog vs allowlist + roster ───

class TestWorkgroupConfigurationYaml(unittest.TestCase):
    """workgroup-configuration.yaml must have the updated agent roster in members.agents
    and must NOT have a workgroup-level skills: field (new schema: skills are per-agent)."""

    def setUp(self):
        self.content = _WG_CONFIG_YAML.read_text()
        self.data = yaml.safe_load(self.content)

    def _member_agents(self):
        return self.data.get('members', {}).get('agents', [])

    def test_comment_clarifies_skills_is_not_access_control(self):
        """workgroup-configuration.yaml must not have a top-level skills: field.
        Per the workgroup-model proposal, skills are selected per agent."""
        self.assertNotIn(
            'skills',
            self.data,
            'workgroup-configuration.yaml must not have a top-level skills: field '
            '(per workgroup-model proposal: skills are selected per agent)',
        )

    def test_agent_roster_includes_project_specialist(self):
        """Configuration Team roster must include project-specialist in members.agents."""
        agents = self._member_agents()
        self.assertIn(
            'project-specialist', agents,
            f'workgroup-configuration.yaml members.agents must include project-specialist, got: {agents}',
        )

    def test_agent_roster_includes_workgroup_specialist(self):
        """Configuration Team roster must include workgroup-specialist in members.agents."""
        agents = self._member_agents()
        self.assertIn(
            'workgroup-specialist', agents,
            f'workgroup-configuration.yaml members.agents must include workgroup-specialist, got: {agents}',
        )

    def test_agent_roster_includes_agent_specialist(self):
        """Configuration Team roster must include agent-specialist in members.agents."""
        agents = self._member_agents()
        self.assertIn(
            'agent-specialist', agents,
            f'workgroup-configuration.yaml members.agents must include agent-specialist, got: {agents}',
        )

    def test_agent_roster_includes_skills_specialist(self):
        """Configuration Team roster must include skills-specialist in members.agents."""
        agents = self._member_agents()
        self.assertIn(
            'skills-specialist', agents,
            f'workgroup-configuration.yaml members.agents must include skills-specialist, got: {agents}',
        )

    def test_agent_roster_does_not_use_old_names(self):
        """Old agent names (skill-architect, agent-designer) must not appear in members.agents."""
        agents = self._member_agents()
        self.assertNotIn(
            'skill-architect', agents,
            'workgroup-configuration.yaml must use skills-specialist, not skill-architect',
        )
        self.assertNotIn(
            'agent-designer', agents,
            'workgroup-configuration.yaml must use agent-specialist, not agent-designer',
        )

    def test_skills_catalog_includes_full_crud_surface(self):
        """Per the workgroup-model proposal, skills are per-agent — no workgroup-level skills: field."""
        self.assertNotIn(
            'skills',
            self.data,
            'workgroup-configuration.yaml must not have a top-level skills: field '
            '(skills are per-agent, not per-workgroup)',
        )


# ── Criterion 6: .teaparty/workgroups/configuration.yaml live config ─────────

class TestLiveConfigurationWorkgroup(unittest.TestCase):
    """.teaparty/workgroups/configuration.yaml must reflect the current agent
    roster. Skills are per-agent in the new schema (workgroup-model proposal),
    not listed at the workgroup level."""

    def setUp(self):
        self.data = yaml.safe_load(_LIVE_CONFIG_YAML.read_text())

    def _member_agents(self):
        return self.data.get('members', {}).get('agents', [])

    def test_live_config_has_five_member_agents(self):
        """Configuration Team must have 5 member agents (lead is not listed in members)."""
        agents = self._member_agents()
        self.assertEqual(
            len(agents), 5,
            f'Expected 5 member agents (lead excluded per spec), got {len(agents)}: {agents}',
        )

    def test_live_config_includes_project_specialist(self):
        """Live config must include project-specialist."""
        self.assertIn('project-specialist', self._member_agents())

    def test_live_config_includes_workgroup_specialist(self):
        """Live config must include workgroup-specialist."""
        self.assertIn('workgroup-specialist', self._member_agents())

    def test_live_config_includes_agent_specialist(self):
        """Live config must include agent-specialist."""
        self.assertIn('agent-specialist', self._member_agents())

    def test_live_config_includes_skills_specialist(self):
        """Live config must include skills-specialist."""
        self.assertIn('skills-specialist', self._member_agents())

    def test_live_config_does_not_use_old_names(self):
        """Old agent names must not appear in the live config."""
        self.assertNotIn('skill-architect', self._member_agents())
        self.assertNotIn('agent-designer', self._member_agents())

    def test_live_config_has_no_workgroup_level_skills(self):
        """Skills are per-agent (workgroup-model proposal); workgroup YAML must not
        have a top-level skills: key."""
        self.assertNotIn(
            'skills', self.data,
            'configuration.yaml must not have a workgroup-level skills: — '
            'skills are selected per agent on the agent config screen',
        )


# ── Criterion: existing .claude/agents/ definitions ──────────────────────────

class TestExistingAgentDefinitionsAssessed(unittest.TestCase):
    """The issue requires updating any existing agent definitions that should have
    a skills allowlist. The management team agents (auditor, researcher, strategist,
    office-manager) do not auto-invoke skills — they are invoked BY skills, or they
    dispatch via tools (Send), not via the skills mechanism. Per the spec, omitting
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
        Send, not via skills. It does not auto-invoke CRUD skills like
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
                'configuration work routes to the Configuration Team via Send, not via skills.',
            )


if __name__ == '__main__':
    unittest.main()
