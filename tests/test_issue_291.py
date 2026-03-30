"""Tests for issue #291: Implement the Configuration Team.

Acceptance criteria:
1. .claude/agents/configuration-lead.md exists — model: sonnet, tools include
   Read/Glob/Grep/Bash/AskTeam, role description explains routing and coordination
2. .claude/agents/project-specialist.md exists — model: sonnet, write-capable tools,
   skills: [create-project, edit-project, remove-project]
3. .claude/agents/workgroup-specialist.md exists — model: sonnet, write-capable tools,
   skills: [create-workgroup, edit-workgroup, remove-workgroup]
4. .claude/agents/agent-specialist.md exists — model: opus, write-capable tools,
   skills: [create-agent, edit-agent, remove-agent]
5. .claude/agents/skills-specialist.md exists — model: opus, write-capable tools,
   skills: [create-skill, edit-skill, remove-skill, optimize-skill]
6. .claude/agents/systems-engineer.md exists — model: sonnet, write-capable tools,
   skills: [create-hook, edit-hook, remove-hook, create-scheduled-task,
            edit-scheduled-task, remove-scheduled-task]
7. All 19 SOP skills exist as .claude/skills/{name}/SKILL.md
8. Each skill SKILL.md has required frontmatter fields
9. optimize-skill is structurally distinct from edit-skill (own supporting files)
10. OM agent definition updated with explicit triage rules for config requests
"""
import unittest
import yaml
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_AGENTS_DIR = _REPO_ROOT / '.claude/agents'
_SKILLS_DIR = _REPO_ROOT / '.claude/skills'

_ALL_SKILLS = [
    'create-project', 'edit-project', 'remove-project',
    'create-workgroup', 'edit-workgroup', 'remove-workgroup',
    'create-agent', 'edit-agent', 'remove-agent',
    'create-skill', 'edit-skill', 'remove-skill', 'optimize-skill',
    'create-hook', 'edit-hook', 'remove-hook',
    'create-scheduled-task', 'edit-scheduled-task', 'remove-scheduled-task',
]

_SPECIALIST_SKILLS = {
    'project-specialist': ['create-project', 'edit-project', 'remove-project'],
    'workgroup-specialist': ['create-workgroup', 'edit-workgroup', 'remove-workgroup'],
    'agent-specialist': ['create-agent', 'edit-agent', 'remove-agent'],
    'skills-specialist': ['create-skill', 'edit-skill', 'remove-skill', 'optimize-skill'],
    'systems-engineer': [
        'create-hook', 'edit-hook', 'remove-hook',
        'create-scheduled-task', 'edit-scheduled-task', 'remove-scheduled-task',
    ],
}

_SPECIALIST_MODELS = {
    'configuration-lead': 'sonnet',
    'project-specialist': 'sonnet',
    'workgroup-specialist': 'sonnet',
    'agent-specialist': 'opus',
    'skills-specialist': 'opus',
    'systems-engineer': 'sonnet',
}

_WRITE_CAPABLE_SPECIALISTS = [
    'project-specialist', 'workgroup-specialist', 'agent-specialist',
    'skills-specialist', 'systems-engineer',
]


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


def _parse_skill_frontmatter(path):
    """Return parsed YAML frontmatter from a SKILL.md file."""
    return _parse_frontmatter(path)


# ── Criterion 1–6: Agent definitions exist ────────────────────────────────────

class TestConfigurationTeamAgentsExist(unittest.TestCase):
    """All six configuration team agent definitions must exist."""

    def _agent_path(self, name):
        return _AGENTS_DIR / f'{name}.md'

    def test_configuration_lead_exists(self):
        """configuration-lead.md must exist in .claude/agents/."""
        self.assertTrue(
            self._agent_path('configuration-lead').exists(),
            '.claude/agents/configuration-lead.md does not exist — '
            'the Configuration Lead is the team lead that routes requests',
        )

    def test_project_specialist_exists(self):
        """project-specialist.md must exist in .claude/agents/."""
        self.assertTrue(
            self._agent_path('project-specialist').exists(),
            '.claude/agents/project-specialist.md does not exist',
        )

    def test_workgroup_specialist_exists(self):
        """workgroup-specialist.md must exist in .claude/agents/."""
        self.assertTrue(
            self._agent_path('workgroup-specialist').exists(),
            '.claude/agents/workgroup-specialist.md does not exist',
        )

    def test_agent_specialist_exists(self):
        """agent-specialist.md must exist in .claude/agents/."""
        self.assertTrue(
            self._agent_path('agent-specialist').exists(),
            '.claude/agents/agent-specialist.md does not exist',
        )

    def test_skills_specialist_exists(self):
        """skills-specialist.md must exist in .claude/agents/."""
        self.assertTrue(
            self._agent_path('skills-specialist').exists(),
            '.claude/agents/skills-specialist.md does not exist',
        )

    def test_systems_engineer_exists(self):
        """systems-engineer.md must exist in .claude/agents/."""
        self.assertTrue(
            self._agent_path('systems-engineer').exists(),
            '.claude/agents/systems-engineer.md does not exist',
        )


class TestAgentModels(unittest.TestCase):
    """Each agent must use the model specified in the design."""

    def _make_frontmatter(self, name):
        return _parse_frontmatter(_AGENTS_DIR / f'{name}.md')

    def test_configuration_lead_uses_sonnet(self):
        """Configuration Lead must use sonnet — routes requests, no heavy lifting."""
        fm = self._make_frontmatter('configuration-lead')
        self.assertIn(
            'sonnet', fm.get('model', ''),
            f'configuration-lead.md must specify a sonnet model, got: {fm.get("model")}',
        )

    def test_agent_specialist_uses_opus(self):
        """Agent Specialist must use opus — prompt engineering requires careful reasoning."""
        fm = self._make_frontmatter('agent-specialist')
        self.assertIn(
            'opus', fm.get('model', ''),
            f'agent-specialist.md must specify an opus model, got: {fm.get("model")}',
        )

    def test_skills_specialist_uses_opus(self):
        """Skills Specialist must use opus — skill design requires careful prompt engineering."""
        fm = self._make_frontmatter('skills-specialist')
        self.assertIn(
            'opus', fm.get('model', ''),
            f'skills-specialist.md must specify an opus model, got: {fm.get("model")}',
        )

    def test_project_specialist_uses_sonnet(self):
        """Project Specialist must use sonnet — routine config work."""
        fm = self._make_frontmatter('project-specialist')
        self.assertIn(
            'sonnet', fm.get('model', ''),
            f'project-specialist.md must specify a sonnet model, got: {fm.get("model")}',
        )

    def test_workgroup_specialist_uses_sonnet(self):
        """Workgroup Specialist must use sonnet."""
        fm = self._make_frontmatter('workgroup-specialist')
        self.assertIn(
            'sonnet', fm.get('model', ''),
            f'workgroup-specialist.md must specify a sonnet model, got: {fm.get("model")}',
        )

    def test_systems_engineer_uses_sonnet(self):
        """Systems Engineer must use sonnet."""
        fm = self._make_frontmatter('systems-engineer')
        self.assertIn(
            'sonnet', fm.get('model', ''),
            f'systems-engineer.md must specify a sonnet model, got: {fm.get("model")}',
        )


class TestSpecialistSkillAllowlists(unittest.TestCase):
    """Each specialist's skills: field must declare exactly the right CRUD skills."""

    def _make_frontmatter(self, name):
        return _parse_frontmatter(_AGENTS_DIR / f'{name}.md')

    def test_project_specialist_skills_allowlist(self):
        """project-specialist.md must declare create-project, edit-project, remove-project."""
        fm = self._make_frontmatter('project-specialist')
        skills = fm.get('skills', [])
        for s in ['create-project', 'edit-project', 'remove-project']:
            self.assertIn(
                s, skills,
                f'project-specialist.md skills: field must include {s!r}, got: {skills}',
            )

    def test_workgroup_specialist_skills_allowlist(self):
        """workgroup-specialist.md must declare create-workgroup, edit-workgroup, remove-workgroup."""
        fm = self._make_frontmatter('workgroup-specialist')
        skills = fm.get('skills', [])
        for s in ['create-workgroup', 'edit-workgroup', 'remove-workgroup']:
            self.assertIn(
                s, skills,
                f'workgroup-specialist.md skills: field must include {s!r}, got: {skills}',
            )

    def test_agent_specialist_skills_allowlist(self):
        """agent-specialist.md must declare create-agent, edit-agent, remove-agent."""
        fm = self._make_frontmatter('agent-specialist')
        skills = fm.get('skills', [])
        for s in ['create-agent', 'edit-agent', 'remove-agent']:
            self.assertIn(
                s, skills,
                f'agent-specialist.md skills: field must include {s!r}, got: {skills}',
            )

    def test_skills_specialist_skills_allowlist(self):
        """skills-specialist.md must declare all four skills including optimize-skill."""
        fm = self._make_frontmatter('skills-specialist')
        skills = fm.get('skills', [])
        for s in ['create-skill', 'edit-skill', 'remove-skill', 'optimize-skill']:
            self.assertIn(
                s, skills,
                f'skills-specialist.md skills: field must include {s!r}, got: {skills}',
            )

    def test_systems_engineer_skills_allowlist(self):
        """systems-engineer.md must declare full hook and scheduled-task CRUD."""
        fm = self._make_frontmatter('systems-engineer')
        skills = fm.get('skills', [])
        expected = [
            'create-hook', 'edit-hook', 'remove-hook',
            'create-scheduled-task', 'edit-scheduled-task', 'remove-scheduled-task',
        ]
        for s in expected:
            self.assertIn(
                s, skills,
                f'systems-engineer.md skills: field must include {s!r}, got: {skills}',
            )


class TestWriteCapableSpecialistTools(unittest.TestCase):
    """Specialists that create/modify config files must have Write and Edit tools."""

    def _make_frontmatter(self, name):
        return _parse_frontmatter(_AGENTS_DIR / f'{name}.md')

    def _tools_list(self, name):
        fm = self._make_frontmatter(name)
        raw = fm.get('tools', '')
        if isinstance(raw, list):
            return raw
        return [t.strip() for t in str(raw).split(',')]

    def test_project_specialist_has_write_access(self):
        """Project Specialist must have Write and Edit tools."""
        tools = self._tools_list('project-specialist')
        self.assertIn('Write', tools, 'project-specialist.md must include Write in tools')
        self.assertIn('Edit', tools, 'project-specialist.md must include Edit in tools')

    def test_workgroup_specialist_has_write_access(self):
        """Workgroup Specialist must have Write and Edit tools."""
        tools = self._tools_list('workgroup-specialist')
        self.assertIn('Write', tools, 'workgroup-specialist.md must include Write in tools')
        self.assertIn('Edit', tools, 'workgroup-specialist.md must include Edit in tools')

    def test_agent_specialist_has_write_access(self):
        """Agent Specialist must have Write and Edit tools."""
        tools = self._tools_list('agent-specialist')
        self.assertIn('Write', tools, 'agent-specialist.md must include Write in tools')
        self.assertIn('Edit', tools, 'agent-specialist.md must include Edit in tools')

    def test_skills_specialist_has_write_access(self):
        """Skills Specialist must have Write and Edit tools."""
        tools = self._tools_list('skills-specialist')
        self.assertIn('Write', tools, 'skills-specialist.md must include Write in tools')
        self.assertIn('Edit', tools, 'skills-specialist.md must include Edit in tools')

    def test_systems_engineer_has_write_access(self):
        """Systems Engineer must have Write and Edit tools."""
        tools = self._tools_list('systems-engineer')
        self.assertIn('Write', tools, 'systems-engineer.md must include Write in tools')
        self.assertIn('Edit', tools, 'systems-engineer.md must include Edit in tools')


class TestConfigurationLeadTools(unittest.TestCase):
    """Configuration Lead must have AskTeam for routing (no Write — it doesn't create)."""

    def setUp(self):
        self.fm = _parse_frontmatter(_AGENTS_DIR / 'configuration-lead.md')

    def _tools_list(self):
        raw = self.fm.get('tools', '')
        if isinstance(raw, list):
            return raw
        return [t.strip() for t in str(raw).split(',')]

    def test_configuration_lead_has_ask_team(self):
        """Configuration Lead must have AskTeam for dispatching to specialists."""
        tools = self._tools_list()
        self.assertIn(
            'AskTeam', tools,
            'configuration-lead.md must include AskTeam in tools — '
            'it routes requests to specialists via AskTeam',
        )

    def test_configuration_lead_does_not_have_write(self):
        """Configuration Lead must not have Write — it coordinates, specialists write."""
        tools = self._tools_list()
        self.assertNotIn(
            'Write', tools,
            'configuration-lead.md must not have Write — '
            'the Lead routes and coordinates; specialists do the writing',
        )


# ── Criterion 7–8: SOP skills exist with proper structure ─────────────────────

class TestAllSopSkillsExist(unittest.TestCase):
    """All 19 SOP skill directories and SKILL.md files must exist."""

    def _skill_path(self, name):
        return _SKILLS_DIR / name / 'SKILL.md'

    def test_create_project_skill_exists(self):
        p = self._skill_path('create-project')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_edit_project_skill_exists(self):
        p = self._skill_path('edit-project')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_remove_project_skill_exists(self):
        p = self._skill_path('remove-project')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_create_workgroup_skill_exists(self):
        p = self._skill_path('create-workgroup')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_edit_workgroup_skill_exists(self):
        p = self._skill_path('edit-workgroup')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_remove_workgroup_skill_exists(self):
        p = self._skill_path('remove-workgroup')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_create_agent_skill_exists(self):
        p = self._skill_path('create-agent')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_edit_agent_skill_exists(self):
        p = self._skill_path('edit-agent')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_remove_agent_skill_exists(self):
        p = self._skill_path('remove-agent')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_create_skill_skill_exists(self):
        p = self._skill_path('create-skill')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_edit_skill_skill_exists(self):
        p = self._skill_path('edit-skill')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_remove_skill_skill_exists(self):
        p = self._skill_path('remove-skill')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_optimize_skill_skill_exists(self):
        p = self._skill_path('optimize-skill')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_create_hook_skill_exists(self):
        p = self._skill_path('create-hook')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_edit_hook_skill_exists(self):
        p = self._skill_path('edit-hook')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_remove_hook_skill_exists(self):
        p = self._skill_path('remove-hook')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_create_scheduled_task_skill_exists(self):
        p = self._skill_path('create-scheduled-task')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_edit_scheduled_task_skill_exists(self):
        p = self._skill_path('edit-scheduled-task')
        self.assertTrue(p.exists(), f'{p} does not exist')

    def test_remove_scheduled_task_skill_exists(self):
        p = self._skill_path('remove-scheduled-task')
        self.assertTrue(p.exists(), f'{p} does not exist')


class TestSkillFrontmatter(unittest.TestCase):
    """Each SKILL.md must have required frontmatter: name, description."""

    def _make_frontmatter(self, skill_name):
        return _parse_frontmatter(_SKILLS_DIR / skill_name / 'SKILL.md')

    def _check_required_fields(self, skill_name):
        fm = self._make_frontmatter(skill_name)
        self.assertIn(
            'name', fm,
            f'{skill_name}/SKILL.md must have a name: frontmatter field',
        )
        self.assertIn(
            'description', fm,
            f'{skill_name}/SKILL.md must have a description: frontmatter field',
        )

    def test_all_skills_have_required_frontmatter(self):
        """Every SKILL.md must have name and description frontmatter fields."""
        for skill in _ALL_SKILLS:
            with self.subTest(skill=skill):
                self._check_required_fields(skill)


class TestSkillsUseProgressiveDisclosure(unittest.TestCase):
    """Each skill must have at least one supporting file — no monolithic SKILL.md.

    Progressive disclosure means the SKILL.md is the invocation entry point; domain
    knowledge (schemas, templates, checklists) lives in supporting files loaded on demand.
    A skill with only SKILL.md and no supporting files is a monolith — it has nowhere
    to defer content to.
    """

    def _skill_dir(self, name):
        return _SKILLS_DIR / name

    def _supporting_files(self, name):
        d = self._skill_dir(name)
        return [f for f in d.iterdir() if f.name != 'SKILL.md' and not f.name.startswith('.')]

    def test_create_project_has_supporting_files(self):
        files = self._supporting_files('create-project')
        self.assertTrue(files, 'create-project/ must have at least one supporting file')

    def test_create_workgroup_has_supporting_files(self):
        files = self._supporting_files('create-workgroup')
        self.assertTrue(files, 'create-workgroup/ must have at least one supporting file')

    def test_create_agent_has_supporting_files(self):
        files = self._supporting_files('create-agent')
        self.assertTrue(files, 'create-agent/ must have at least one supporting file')

    def test_create_skill_has_supporting_files(self):
        files = self._supporting_files('create-skill')
        self.assertTrue(files, 'create-skill/ must have at least one supporting file')

    def test_optimize_skill_has_supporting_files(self):
        """optimize-skill must have supporting files distinct from edit-skill.

        optimize-skill is a structural refactoring operation, not content editing.
        Its supporting files should reflect that (e.g., decomposition guide, analysis
        checklist) — not just be the same as edit-skill's files.
        """
        files = self._supporting_files('optimize-skill')
        self.assertTrue(
            files,
            'optimize-skill/ must have supporting files — '
            'it is a structural analysis operation, not just edit-skill with a different name',
        )

    def test_create_hook_has_supporting_files(self):
        files = self._supporting_files('create-hook')
        self.assertTrue(files, 'create-hook/ must have at least one supporting file')

    def test_create_scheduled_task_has_supporting_files(self):
        files = self._supporting_files('create-scheduled-task')
        self.assertTrue(files, 'create-scheduled-task/ must have at least one supporting file')


# ── Criterion 9: optimize-skill is structurally distinct from edit-skill ──────

class TestOptimizeSkillIsDistinct(unittest.TestCase):
    """optimize-skill must be structurally distinct from edit-skill.

    The proposal says: 'optimize-skill is structurally distinct from edit-skill —
    it is an analysis and refactoring operation (decompose monolithic SKILL.md,
    identify deferrable content, restructure for progressive disclosure), not a
    content edit.'
    """

    def _skill_content(self, name):
        return (_SKILLS_DIR / name / 'SKILL.md').read_text()

    def test_optimize_skill_mentions_analysis_or_refactoring(self):
        """optimize-skill SKILL.md must describe it as analysis/refactoring, not editing."""
        content = self._skill_content('optimize-skill')
        has_structural_framing = any(
            term in content.lower()
            for term in ['analys', 'refactor', 'decompos', 'restructur', 'progressive disclosure']
        )
        self.assertTrue(
            has_structural_framing,
            'optimize-skill/SKILL.md must frame the skill as structural analysis and '
            'refactoring (decompose, restructure, progressive disclosure) — '
            'not as a content editing operation',
        )

    def test_optimize_skill_supporting_files_differ_from_edit_skill(self):
        """optimize-skill must have different supporting files than edit-skill.

        If optimize-skill and edit-skill have identical supporting files, optimize-skill
        is not a distinct operation — it is edit-skill with a renamed entry point.
        """
        optimize_dir = _SKILLS_DIR / 'optimize-skill'
        edit_dir = _SKILLS_DIR / 'edit-skill'
        if not optimize_dir.exists() or not edit_dir.exists():
            self.skipTest('Both skills must exist for this comparison')
        optimize_files = {f.name for f in optimize_dir.iterdir() if f.name != 'SKILL.md'}
        edit_files = {f.name for f in edit_dir.iterdir() if f.name != 'SKILL.md'}
        # They must not be identical — optimize-skill has structurally distinct content
        self.assertNotEqual(
            optimize_files, edit_files,
            f'optimize-skill and edit-skill must have different supporting files. '
            f'optimize-skill: {sorted(optimize_files)}, edit-skill: {sorted(edit_files)}',
        )


# ── Criterion 10: OM routing updated with explicit triage rules ───────────────

class TestOfficeManagerRouting(unittest.TestCase):
    """The OM agent definition must have explicit routing rules for config requests.

    Per the proposal: simple single-artifact requests → direct to specialist.
    Complex multi-artifact requests → Configuration Lead.
    The current OM definition has only a brief mention with no triage detail.
    """

    def setUp(self):
        self.content = (_AGENTS_DIR / 'office-manager.md').read_text()

    def test_om_mentions_configuration_lead_routing(self):
        """OM must explicitly route multi-artifact requests to Configuration Lead."""
        self.assertIn(
            'Configuration Lead', self.content,
            'office-manager.md must explicitly mention routing multi-artifact requests '
            'to the Configuration Lead',
        )

    def test_om_mentions_direct_to_specialist_fast_path(self):
        """OM must mention fast-path: direct routing to specialist for simple requests."""
        has_fast_path = (
            'directly' in self.content.lower() or
            'fast path' in self.content.lower() or
            'direct to' in self.content.lower() or
            'specialist' in self.content.lower()
        )
        self.assertTrue(
            has_fast_path,
            'office-manager.md must describe the fast path: routing single-artifact requests '
            'directly to the specialist without going through the Configuration Lead',
        )

    def test_om_covers_artifact_type_routing_table(self):
        """OM must know which artifact types route to which specialist."""
        # The OM needs to know: skill → Skills Specialist, hook → Systems Engineer, etc.
        has_routing_table = any(
            term in self.content
            for term in ['Skills Specialist', 'Systems Engineer', 'Agent Specialist',
                         'skill.*specialist', 'agent.*specialist']
        )
        self.assertTrue(
            has_routing_table,
            'office-manager.md must describe which artifact types map to which specialist '
            '(skills → Skills Specialist, hooks → Systems Engineer, agents → Agent Specialist)',
        )


if __name__ == '__main__':
    unittest.main()
