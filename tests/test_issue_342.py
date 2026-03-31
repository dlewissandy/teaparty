"""Tests for Issue #342: Project buttons — OM must dialog before calling AddProject/CreateProject.

Acceptance criteria:
1. "+ Add" seed changed to 'Please run the /add-project skill.'
2. "+ New" seed changed to 'Please run the /create-project skill.'
3. .claude/skills/add-project/ created with SKILL.md + phase files: discover, dialog, register, exit
4. .claude/skills/create-project/ refactored to phase-based: dialog, scaffold, exit
5. OM office-manager.md frontmatter includes skills: [add-project, create-project]
6. OM routing table does not fast-path project registration when invoked via skill
7. docs/proposals/dashboard-ui/references/creating-things.md updated to reflect skill-referenced seeds
8. Skill phase files reference WithdrawSession and collect required fields before calling MCP tools
"""
import os
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_SKILLS_DIR = _REPO_ROOT / '.claude' / 'skills'
_AGENTS_DIR = _REPO_ROOT / '.claude' / 'agents'
_CONFIG_HTML = _REPO_ROOT / 'bridge' / 'static' / 'config.html'
_OM_AGENT = _AGENTS_DIR / 'office-manager.md'
_CREATING_THINGS_DOC = _REPO_ROOT / 'docs' / 'proposals' / 'dashboard-ui' / 'references' / 'creating-things.md'


# ── AC1 & AC2: Seed messages carry explicit skill references ─────────────────

class TestSeedMessages(unittest.TestCase):
    """config.html button seeds must reference skills explicitly, not vague English."""

    def _config_html_source(self) -> str:
        return _CONFIG_HTML.read_text()

    def test_add_button_seed_references_add_project_skill(self):
        """'+ Add' button seed must be 'Please run the /add-project skill.'"""
        src = self._config_html_source()
        self.assertIn(
            'Please run the /add-project skill.',
            src,
            '"+ Add" button seed must explicitly reference the /add-project skill, '
            'not a vague English string',
        )

    def test_new_button_seed_references_create_project_skill(self):
        """'+ New' button seed must be 'Please run the /create-project skill.'"""
        src = self._config_html_source()
        self.assertIn(
            'Please run the /create-project skill.',
            src,
            '"+ New" button seed must explicitly reference the /create-project skill, '
            'not a vague English string',
        )

    def test_add_button_no_longer_uses_vague_seed(self):
        """'+ Add' button must not use the old vague seed."""
        src = self._config_html_source()
        self.assertNotIn(
            'I would like to add an existing project to TeaParty.',
            src,
            '"+ Add" button must not use the old vague seed; it must use the skill reference',
        )

    def test_new_button_no_longer_uses_vague_seed(self):
        """'+ New' button must not use the old vague seed."""
        src = self._config_html_source()
        self.assertNotIn(
            'I would like to create a new project.',
            src,
            '"+ New" button must not use the old vague seed; it must use the skill reference',
        )


# ── AC3: add-project skill structure ─────────────────────────────────────────

class TestAddProjectSkillExists(unittest.TestCase):
    """add-project skill must exist with SKILL.md entry point."""

    def _skill_dir(self) -> Path:
        return _SKILLS_DIR / 'add-project'

    def test_add_project_skill_directory_exists(self):
        """add-project skill directory must exist at .claude/skills/add-project/."""
        self.assertTrue(
            self._skill_dir().exists(),
            'add-project skill directory must exist at .claude/skills/add-project/',
        )

    def test_add_project_skill_md_exists(self):
        """add-project/SKILL.md must exist."""
        skill_md = self._skill_dir() / 'SKILL.md'
        self.assertTrue(
            skill_md.exists(),
            'add-project/SKILL.md must exist as the skill entry point',
        )

    def test_add_project_skill_has_name_frontmatter(self):
        """add-project/SKILL.md must have name: add-project in frontmatter."""
        skill_md = self._skill_dir() / 'SKILL.md'
        content = skill_md.read_text()
        self.assertIn(
            'name: add-project',
            content,
            'add-project/SKILL.md must declare name: add-project in frontmatter',
        )


class TestAddProjectPhaseFiles(unittest.TestCase):
    """add-project skill must have all required phase files with proper structure."""

    def _skill_dir(self) -> Path:
        return _SKILLS_DIR / 'add-project'

    def _phase(self, name: str) -> str:
        path = self._skill_dir() / f'phase-{name}.md'
        self.assertTrue(
            path.exists(),
            f'add-project/phase-{name}.md must exist',
        )
        return path.read_text()

    def test_phase_discover_exists(self):
        """add-project must have a phase-discover.md."""
        self._phase('discover')

    def test_phase_dialog_exists(self):
        """add-project must have a phase-dialog.md."""
        self._phase('dialog')

    def test_phase_register_exists(self):
        """add-project must have a phase-register.md."""
        self._phase('register')

    def test_phase_exit_exists(self):
        """add-project must have a phase-exit.md."""
        self._phase('exit')

    def test_phase_discover_references_next_phase(self):
        """phase-discover.md must have a Next pointer to phase-dialog.md."""
        content = self._phase('discover')
        self.assertIn(
            'phase-dialog.md',
            content,
            'phase-discover.md must point to phase-dialog.md as the next phase',
        )

    def test_phase_dialog_references_next_phase(self):
        """phase-dialog.md must have a Next pointer to phase-register.md."""
        content = self._phase('dialog')
        self.assertIn(
            'phase-register.md',
            content,
            'phase-dialog.md must point to phase-register.md as the next phase',
        )

    def test_phase_register_references_next_phase(self):
        """phase-register.md must have a Next pointer to phase-exit.md."""
        content = self._phase('register')
        self.assertIn(
            'phase-exit.md',
            content,
            'phase-register.md must point to phase-exit.md as the next phase',
        )

    def test_phase_discover_mentions_withdraw_session(self):
        """phase-discover.md must reference WithdrawSession for the withdrawal path."""
        content = self._phase('discover')
        self.assertIn(
            'WithdrawSession',
            content,
            'phase-discover.md must reference WithdrawSession so the OM can terminate '
            'if the human withdraws',
        )

    def test_phase_dialog_mentions_withdraw_session(self):
        """phase-dialog.md must reference WithdrawSession for the withdrawal path."""
        content = self._phase('dialog')
        self.assertIn(
            'WithdrawSession',
            content,
            'phase-dialog.md must reference WithdrawSession so the OM can terminate '
            'if the human withdraws',
        )

    def test_phase_register_calls_add_project_tool(self):
        """phase-register.md must call AddProject, not CreateProject."""
        content = self._phase('register')
        self.assertIn(
            'AddProject',
            content,
            'phase-register.md must call AddProject (not CreateProject)',
        )
        self.assertNotIn(
            'CreateProject',
            content,
            'phase-register.md must call AddProject only; CreateProject belongs to create-project skill',
        )

    def test_phase_register_mentions_withdraw_session_on_failure(self):
        """phase-register.md must reference WithdrawSession for the failure/withdrawal path."""
        content = self._phase('register')
        self.assertIn(
            'WithdrawSession',
            content,
            'phase-register.md must reference WithdrawSession — if AddProject fails and '
            'the human withdraws, the skill must terminate cleanly',
        )

    def test_phase_discover_asks_for_path(self):
        """phase-discover.md must ask for or verify the project directory path."""
        content = self._phase('discover')
        # Must mention path collection — AddProject requires a path
        self.assertTrue(
            'path' in content.lower() or 'directory' in content.lower(),
            'phase-discover.md must address path/directory collection — '
            'AddProject requires an existing path',
        )


# ── AC4: create-project skill phase-based structure ──────────────────────────

class TestCreateProjectSkillPhases(unittest.TestCase):
    """create-project skill must be phase-based with dialog before scaffold."""

    def _skill_dir(self) -> Path:
        return _SKILLS_DIR / 'create-project'

    def _phase(self, name: str) -> str:
        path = self._skill_dir() / f'phase-{name}.md'
        self.assertTrue(
            path.exists(),
            f'create-project/phase-{name}.md must exist',
        )
        return path.read_text()

    def test_phase_dialog_exists(self):
        """create-project must have a phase-dialog.md."""
        self._phase('dialog')

    def test_phase_scaffold_exists(self):
        """create-project must have a phase-scaffold.md."""
        self._phase('scaffold')

    def test_phase_exit_exists(self):
        """create-project must have a phase-exit.md."""
        self._phase('exit')

    def test_phase_dialog_references_phase_scaffold(self):
        """create-project phase-dialog.md must point to phase-scaffold.md."""
        content = self._phase('dialog')
        self.assertIn(
            'phase-scaffold.md',
            content,
            'create-project phase-dialog.md must point to phase-scaffold.md as the next phase',
        )

    def test_phase_scaffold_references_phase_exit(self):
        """create-project phase-scaffold.md must point to phase-exit.md."""
        content = self._phase('scaffold')
        self.assertIn(
            'phase-exit.md',
            content,
            'create-project phase-scaffold.md must point to phase-exit.md as the next phase',
        )

    def test_phase_scaffold_calls_create_project_tool(self):
        """create-project phase-scaffold.md must call CreateProject, not AddProject."""
        content = self._phase('scaffold')
        self.assertIn(
            'CreateProject',
            content,
            'phase-scaffold.md must call CreateProject',
        )
        self.assertNotIn(
            'AddProject',
            content,
            'phase-scaffold.md must call CreateProject only; AddProject belongs to add-project skill',
        )

    def test_phase_scaffold_mentions_withdraw_session_on_failure(self):
        """phase-scaffold.md must reference WithdrawSession for the failure/withdrawal path."""
        content = self._phase('scaffold')
        self.assertIn(
            'WithdrawSession',
            content,
            'phase-scaffold.md must reference WithdrawSession — if CreateProject fails and '
            'the human withdraws, the skill must terminate cleanly',
        )

    def test_phase_dialog_mentions_withdraw_session(self):
        """create-project phase-dialog.md must reference WithdrawSession."""
        content = self._phase('dialog')
        self.assertIn(
            'WithdrawSession',
            content,
            'phase-dialog.md must reference WithdrawSession so the OM can terminate '
            'if the human withdraws',
        )

    def test_skill_md_references_phase_dialog(self):
        """create-project SKILL.md must direct the agent to start at phase-dialog.md."""
        skill_md = (self._skill_dir() / 'SKILL.md').read_text()
        self.assertIn(
            'phase-dialog.md',
            skill_md,
            'create-project SKILL.md must reference phase-dialog.md as the entry point',
        )


# ── AC5: OM skills allowlist ──────────────────────────────────────────────────

class TestOMSkillsAllowlist(unittest.TestCase):
    """OM agent definition must include add-project and create-project in skills allowlist."""

    def _om_source(self) -> str:
        return _OM_AGENT.read_text()

    def test_om_frontmatter_includes_add_project_skill(self):
        """office-manager.md frontmatter must list add-project in skills."""
        content = self._om_source()
        # Find the frontmatter block (between --- delimiters)
        match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        self.assertIsNotNone(match, 'office-manager.md must have YAML frontmatter')
        frontmatter = match.group(1)
        self.assertIn(
            'add-project',
            frontmatter,
            'office-manager.md frontmatter must include add-project in skills allowlist',
        )

    def test_om_frontmatter_includes_create_project_skill(self):
        """office-manager.md frontmatter must list create-project in skills."""
        content = self._om_source()
        match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        self.assertIsNotNone(match, 'office-manager.md must have YAML frontmatter')
        frontmatter = match.group(1)
        self.assertIn(
            'create-project',
            frontmatter,
            'office-manager.md frontmatter must include create-project in skills allowlist',
        )

    def test_om_frontmatter_has_skills_key(self):
        """office-manager.md frontmatter must have a skills: key."""
        content = self._om_source()
        match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        self.assertIsNotNone(match, 'office-manager.md must have YAML frontmatter')
        frontmatter = match.group(1)
        self.assertIn(
            'skills:',
            frontmatter,
            'office-manager.md frontmatter must have a skills: key',
        )


# ── AC6: OM routing does not fast-path skill invocations ─────────────────────

class TestOMRoutingTableNoFastPath(unittest.TestCase):
    """OM routing table must not fast-path project work when skill invocation is in play."""

    def _om_source(self) -> str:
        return _OM_AGENT.read_text()

    def test_om_routing_table_has_skill_invocation_guidance(self):
        """office-manager.md must note that skill invocations bypass the fast-path."""
        content = self._om_source()
        # The routing table must mention that skill invocations should not be fast-pathed
        # to the Project Specialist — the skill IS the dialog
        self.assertTrue(
            'skill' in content and ('invocation' in content or 'add-project' in content),
            'office-manager.md must address skill invocation routing — '
            'project requests via /add-project or /create-project must not be fast-pathed '
            'to the Project Specialist',
        )

    def test_om_routing_table_addresses_project_skill_path(self):
        """OM body must instruct agent to run the skill, not route to Project Specialist."""
        content = self._om_source()
        # Look for guidance that distinguishes skill-invoked project work from direct requests
        self.assertTrue(
            'add-project' in content or 'create-project' in content,
            'office-manager.md body must mention add-project or create-project to guide '
            'the agent on how to handle button-initiated project requests',
        )


# ── AC7: creating-things.md updated ──────────────────────────────────────────

class TestCreatingThingsDocUpdated(unittest.TestCase):
    """creating-things.md must reflect skill-referenced seeds for Projects buttons."""

    def _doc_source(self) -> str:
        return _CREATING_THINGS_DOC.read_text()

    def test_creating_things_references_add_project_skill(self):
        """creating-things.md must reference the /add-project skill for the Add button."""
        content = self._doc_source()
        self.assertIn(
            'add-project',
            content,
            'creating-things.md must reference add-project skill for the Projects Add button',
        )

    def test_creating_things_references_create_project_skill(self):
        """creating-things.md must reference the /create-project skill for the New button."""
        content = self._doc_source()
        self.assertIn(
            'create-project',
            content,
            'creating-things.md must reference create-project skill for the Projects New button',
        )

    def test_creating_things_no_longer_uses_vague_add_seed(self):
        """creating-things.md must not document the old vague 'add an existing project' seed."""
        content = self._doc_source()
        self.assertNotIn(
            'I would like to add an existing project',
            content,
            'creating-things.md must be updated — old vague seed no longer applies',
        )


# ── AC8: Skill SKILL.md instructs OM to start the phase chain ────────────────

class TestSkillEntryPoints(unittest.TestCase):
    """SKILL.md files must instruct the agent to begin the phase chain."""

    def test_add_project_skill_md_references_phase_discover(self):
        """add-project SKILL.md must reference phase-discover.md as the first phase."""
        skill_md = (_SKILLS_DIR / 'add-project' / 'SKILL.md').read_text()
        self.assertIn(
            'phase-discover.md',
            skill_md,
            'add-project SKILL.md must reference phase-discover.md to start the dialog chain',
        )

    def test_add_project_skill_md_does_not_call_add_project_directly(self):
        """add-project SKILL.md must not call AddProject directly — phases do that."""
        skill_md = (_SKILLS_DIR / 'add-project' / 'SKILL.md').read_text()
        self.assertNotIn(
            'AddProject(',
            skill_md,
            'add-project SKILL.md must not call AddProject directly — '
            'phase-register.md is responsible for the tool call',
        )

    def test_create_project_skill_md_does_not_call_create_project_directly(self):
        """create-project SKILL.md must not call CreateProject directly — phases do that."""
        skill_md = (_SKILLS_DIR / 'create-project' / 'SKILL.md').read_text()
        self.assertNotIn(
            'CreateProject(',
            skill_md,
            'create-project SKILL.md must not call CreateProject directly — '
            'phase-scaffold.md is responsible for the tool call',
        )
