"""Tests for issue #374: Config reader — merge management and project catalogs.

Acceptance criteria:
1. Config reader returns a merged catalog per project (management + project-level entries)
2. Project-specific agents appear in catalog panels alongside management agents
3. Project-specific skills appear in the agent config screen skill picker
4. Project-level entry takes precedence over management-level entry with the same name
5. Tests cover merge behavior, precedence, and empty project catalog case
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config_reader import (
    MergedCatalog,
    merge_catalog,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_agents_dir(claude_dir: str, names: list[str]) -> None:
    """Create .md agent files in {claude_dir}/agents/."""
    agents_dir = os.path.join(claude_dir, 'agents')
    os.makedirs(agents_dir, exist_ok=True)
    for name in names:
        with open(os.path.join(agents_dir, f'{name}.md'), 'w') as f:
            f.write(f'# {name}\n')


def _make_skills_dir(claude_dir: str, names: list[str]) -> None:
    """Create skill directories in {claude_dir}/skills/."""
    skills_dir = os.path.join(claude_dir, 'skills')
    os.makedirs(skills_dir, exist_ok=True)
    for name in names:
        skill_dir = os.path.join(skills_dir, name)
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, 'SKILL.md'), 'w') as f:
            f.write(f'# {name}\n')


def _make_settings_json(claude_dir: str, hooks: list[dict]) -> None:
    """Create settings.json with hooks in the given .claude/ directory.

    Each hook dict has: event, matcher, type, command.
    These are written in the settings.json format used by Claude Code.
    """
    os.makedirs(claude_dir, exist_ok=True)
    settings: dict = {'hooks': {}}
    for h in hooks:
        event = h['event']
        matcher = h.get('matcher', '')
        if event not in settings['hooks']:
            settings['hooks'][event] = []
        # Find or create a matcher group
        group = next(
            (g for g in settings['hooks'][event] if g.get('matcher') == matcher),
            None,
        )
        if group is None:
            group = {'matcher': matcher, 'hooks': []}
            settings['hooks'][event].append(group)
        group['hooks'].append({'type': h.get('type', 'command'), 'command': h.get('command', '')})
    path = os.path.join(claude_dir, 'settings.json')
    with open(path, 'w') as f:
        json.dump(settings, f)


# ── AC1/5: merge_catalog with no project dir returns management entries only ──

class TestMergeCatalogManagementOnly(unittest.TestCase):
    """merge_catalog with no project dir returns only management-level entries."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._mgmt_claude = os.path.join(self._tmpdir, '.claude')
        _make_agents_dir(self._mgmt_claude, ['auditor', 'researcher'])
        _make_skills_dir(self._mgmt_claude, ['commit', 'fix-issue'])
        _make_settings_json(self._mgmt_claude, [
            {'event': 'PostToolUse', 'matcher': '', 'type': 'command', 'command': 'echo done'},
        ])

    def test_returns_merged_catalog_type(self):
        """merge_catalog returns a MergedCatalog instance."""
        result = merge_catalog(self._mgmt_claude)
        self.assertIsInstance(result, MergedCatalog)

    def test_management_agents_present(self):
        """All management agents appear in merged catalog when no project dir given."""
        result = merge_catalog(self._mgmt_claude)
        self.assertIn('auditor', result.agents)
        self.assertIn('researcher', result.agents)

    def test_management_skills_present(self):
        """All management skills appear in merged catalog when no project dir given."""
        result = merge_catalog(self._mgmt_claude)
        self.assertIn('commit', result.skills)
        self.assertIn('fix-issue', result.skills)

    def test_management_hooks_present(self):
        """Management hooks appear in merged catalog when no project dir given."""
        result = merge_catalog(self._mgmt_claude)
        events = [h['event'] for h in result.hooks]
        self.assertIn('PostToolUse', events)

    def test_project_agents_set_empty_without_project_dir(self):
        """project_agents is empty when no project dir given."""
        result = merge_catalog(self._mgmt_claude)
        self.assertEqual(result.project_agents, set())

    def test_project_skills_set_empty_without_project_dir(self):
        """project_skills is empty when no project dir given."""
        result = merge_catalog(self._mgmt_claude)
        self.assertEqual(result.project_skills, set())


# ── AC5: empty project catalog falls back to management entries ───────────────

class TestMergeCatalogEmptyProjectDir(unittest.TestCase):
    """Empty project .claude/ directory is equivalent to management-only."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._mgmt_claude = os.path.join(self._tmpdir, '.claude')
        _make_agents_dir(self._mgmt_claude, ['auditor'])
        _make_skills_dir(self._mgmt_claude, ['commit'])
        self._proj_claude = os.path.join(self._tmpdir, 'proj', '.claude')
        os.makedirs(self._proj_claude, exist_ok=True)
        # Project .claude/ has no agents/, skills/, or settings.json

    def test_management_agents_present_when_project_empty(self):
        """Management agents are present when project .claude/ is empty."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertIn('auditor', result.agents)

    def test_management_skills_present_when_project_empty(self):
        """Management skills are present when project .claude/ is empty."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertIn('commit', result.skills)

    def test_project_agents_set_empty_when_project_has_no_agents(self):
        """project_agents is empty when project .claude/agents/ has no files."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertEqual(result.project_agents, set())


# ── AC1: merge combines both management and project entries ───────────────────

class TestMergeCatalogCombinesEntries(unittest.TestCase):
    """merge_catalog includes both management and project entries when names differ."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._mgmt_claude = os.path.join(self._tmpdir, '.claude')
        _make_agents_dir(self._mgmt_claude, ['auditor', 'researcher'])
        _make_skills_dir(self._mgmt_claude, ['commit', 'audit'])
        _make_settings_json(self._mgmt_claude, [
            {'event': 'PostToolUse', 'matcher': '', 'command': 'echo post'},
        ])

        self._proj_claude = os.path.join(self._tmpdir, 'proj', '.claude')
        _make_agents_dir(self._proj_claude, ['domain-expert', 'tester'])
        _make_skills_dir(self._proj_claude, ['deploy', 'release'])
        _make_settings_json(self._proj_claude, [
            {'event': 'PreToolUse', 'matcher': '', 'command': 'echo pre'},
        ])

    def test_all_agents_in_merged_catalog(self):
        """Merged catalog contains agents from both management and project."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        for name in ['auditor', 'researcher', 'domain-expert', 'tester']:
            self.assertIn(name, result.agents)

    def test_all_skills_in_merged_catalog(self):
        """Merged catalog contains skills from both management and project."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        for name in ['commit', 'audit', 'deploy', 'release']:
            self.assertIn(name, result.skills)

    def test_all_hooks_in_merged_catalog(self):
        """Merged catalog contains hooks from both management and project."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        events = {h['event'] for h in result.hooks}
        self.assertIn('PostToolUse', events)
        self.assertIn('PreToolUse', events)

    def test_project_agents_set_identifies_project_entries(self):
        """project_agents set contains all agent names sourced from project."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertIn('domain-expert', result.project_agents)
        self.assertIn('tester', result.project_agents)
        self.assertNotIn('auditor', result.project_agents)
        self.assertNotIn('researcher', result.project_agents)

    def test_project_skills_set_identifies_project_entries(self):
        """project_skills set contains all skill names sourced from project."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertIn('deploy', result.project_skills)
        self.assertIn('release', result.project_skills)
        self.assertNotIn('commit', result.project_skills)
        self.assertNotIn('audit', result.project_skills)

    def test_no_duplicate_agents(self):
        """Each agent name appears at most once in the merged catalog."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertEqual(len(result.agents), len(set(result.agents)))

    def test_no_duplicate_skills(self):
        """Each skill name appears at most once in the merged catalog."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertEqual(len(result.skills), len(set(result.skills)))


# ── AC4: project-level entries take precedence on name collision ──────────────

class TestMergeCatalogAgentPrecedence(unittest.TestCase):
    """When project and management define an agent with the same name,
    project takes precedence — it appears in project_agents and only once."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._mgmt_claude = os.path.join(self._tmpdir, '.claude')
        _make_agents_dir(self._mgmt_claude, ['shared-agent', 'mgmt-only'])

        self._proj_claude = os.path.join(self._tmpdir, 'proj', '.claude')
        _make_agents_dir(self._proj_claude, ['shared-agent', 'proj-only'])

    def test_colliding_agent_appears_once(self):
        """An agent present in both sources appears exactly once in merged catalog."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertEqual(result.agents.count('shared-agent'), 1)

    def test_colliding_agent_in_project_agents_set(self):
        """A colliding agent is tagged as project-sourced (project takes precedence)."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertIn('shared-agent', result.project_agents)

    def test_management_only_agent_not_in_project_agents_set(self):
        """An agent only in management is not tagged as project-sourced."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertNotIn('mgmt-only', result.project_agents)

    def test_all_names_present_after_collision(self):
        """All unique agent names appear in the merged catalog despite collision."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertIn('shared-agent', result.agents)
        self.assertIn('mgmt-only', result.agents)
        self.assertIn('proj-only', result.agents)


class TestMergeCatalogSkillPrecedence(unittest.TestCase):
    """When project and management define a skill with the same name,
    project takes precedence."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._mgmt_claude = os.path.join(self._tmpdir, '.claude')
        _make_skills_dir(self._mgmt_claude, ['shared-skill', 'mgmt-only'])

        self._proj_claude = os.path.join(self._tmpdir, 'proj', '.claude')
        _make_skills_dir(self._proj_claude, ['shared-skill', 'proj-only'])

    def test_colliding_skill_appears_once(self):
        """A skill present in both sources appears exactly once in merged catalog."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertEqual(result.skills.count('shared-skill'), 1)

    def test_colliding_skill_in_project_skills_set(self):
        """A colliding skill is tagged as project-sourced (project takes precedence)."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertIn('shared-skill', result.project_skills)

    def test_management_only_skill_not_in_project_skills_set(self):
        """A skill only in management is not tagged as project-sourced."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertNotIn('mgmt-only', result.project_skills)


class TestMergeCatalogHookPrecedence(unittest.TestCase):
    """When project and management define a hook with the same (event, matcher),
    project takes precedence."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._mgmt_claude = os.path.join(self._tmpdir, '.claude')
        # Management defines PostToolUse and PostToolUse/Bash
        _make_settings_json(self._mgmt_claude, [
            {'event': 'PostToolUse', 'matcher': '', 'command': 'echo mgmt-post'},
            {'event': 'PreToolUse', 'matcher': 'Bash', 'command': 'echo mgmt-pre-bash'},
        ])

        self._proj_claude = os.path.join(self._tmpdir, 'proj', '.claude')
        # Project overrides PostToolUse (same event+matcher) and adds Stop
        _make_settings_json(self._proj_claude, [
            {'event': 'PostToolUse', 'matcher': '', 'command': 'echo proj-post'},
            {'event': 'Stop', 'matcher': '', 'command': 'echo proj-stop'},
        ])

    def test_colliding_hook_appears_once(self):
        """A hook with the same (event, matcher) appears exactly once in merged catalog."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        post_hooks = [h for h in result.hooks if h['event'] == 'PostToolUse' and h.get('matcher') == '']
        self.assertEqual(len(post_hooks), 1)

    def test_project_hook_wins_on_collision(self):
        """When event+matcher collides, the project's hook command is used."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        post_hook = next(
            h for h in result.hooks if h['event'] == 'PostToolUse' and h.get('matcher') == ''
        )
        self.assertEqual(post_hook['command'], 'echo proj-post')

    def test_non_colliding_management_hook_preserved(self):
        """A management hook with a unique (event, matcher) is still included."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        pre_bash = [
            h for h in result.hooks
            if h['event'] == 'PreToolUse' and h.get('matcher') == 'Bash'
        ]
        self.assertEqual(len(pre_bash), 1)

    def test_non_colliding_project_hook_added(self):
        """A project hook with a unique event is added to the merged catalog."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        stop_hooks = [h for h in result.hooks if h['event'] == 'Stop']
        self.assertEqual(len(stop_hooks), 1)


# ── AC2: bridge workgroup detail uses merged catalog ─────────────────────────

class TestBridgeWorkgroupDetailUsesProjectAgents(unittest.TestCase):
    """The workgroup detail endpoint must include project-level agents in its catalog."""

    def setUp(self):
        """Set up a temp repo structure with management and project .claude/ dirs."""
        self._tmpdir = tempfile.mkdtemp()

        # Management .claude/
        mgmt_claude = os.path.join(self._tmpdir, '.claude')
        _make_agents_dir(mgmt_claude, ['auditor', 'researcher'])
        _make_settings_json(mgmt_claude, [
            {'event': 'PostToolUse', 'matcher': '', 'command': 'echo mgmt'},
        ])

        # Project .claude/
        self._proj_dir = os.path.join(self._tmpdir, 'myproject')
        proj_claude = os.path.join(self._proj_dir, '.claude')
        _make_agents_dir(proj_claude, ['domain-expert'])
        _make_settings_json(proj_claude, [
            {'event': 'PreToolUse', 'matcher': '', 'command': 'echo proj'},
        ])

    def test_project_agent_in_merged_catalog_for_project_scope(self):
        """merge_catalog for project scope includes project-level agents."""
        catalog = merge_catalog(
            os.path.join(self._tmpdir, '.claude'),
            os.path.join(self._proj_dir, '.claude'),
        )
        self.assertIn('domain-expert', catalog.agents)
        self.assertIn('auditor', catalog.agents)

    def test_project_agent_tagged_as_project_sourced(self):
        """Project-level agents are identified in project_agents set."""
        catalog = merge_catalog(
            os.path.join(self._tmpdir, '.claude'),
            os.path.join(self._proj_dir, '.claude'),
        )
        self.assertIn('domain-expert', catalog.project_agents)
        self.assertNotIn('auditor', catalog.project_agents)


class TestBridgeWorkgroupDetailAgentPrecedenceInMerge(unittest.TestCase):
    """When a project defines an agent with the same name as a management agent,
    the workgroup catalog must use the project's version (project takes precedence)."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

        mgmt_claude = os.path.join(self._tmpdir, '.claude')
        _make_agents_dir(mgmt_claude, ['shared-agent', 'mgmt-only'])

        self._proj_dir = os.path.join(self._tmpdir, 'proj')
        proj_claude = os.path.join(self._proj_dir, '.claude')
        _make_agents_dir(proj_claude, ['shared-agent', 'proj-only'])

    def test_merged_catalog_contains_shared_agent_once(self):
        """An agent with the same name in both sources appears exactly once."""
        catalog = merge_catalog(
            os.path.join(self._tmpdir, '.claude'),
            os.path.join(self._proj_dir, '.claude'),
        )
        self.assertEqual(catalog.agents.count('shared-agent'), 1)

    def test_shared_agent_source_is_project(self):
        """The shared agent is sourced from project, not management."""
        catalog = merge_catalog(
            os.path.join(self._tmpdir, '.claude'),
            os.path.join(self._proj_dir, '.claude'),
        )
        self.assertIn('shared-agent', catalog.project_agents)

    def test_management_only_agent_not_in_project_agents(self):
        """Management-only agents are not tagged as project-sourced."""
        catalog = merge_catalog(
            os.path.join(self._tmpdir, '.claude'),
            os.path.join(self._proj_dir, '.claude'),
        )
        self.assertNotIn('mgmt-only', catalog.project_agents)


# ── AC3: project-specific skills appear in skill catalog ─────────────────────

class TestMergeCatalogProjectSkillsVisible(unittest.TestCase):
    """Project-specific skills must appear in the merged skill catalog."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._mgmt_claude = os.path.join(self._tmpdir, '.claude')
        _make_skills_dir(self._mgmt_claude, ['commit', 'audit'])

        self._proj_claude = os.path.join(self._tmpdir, 'proj', '.claude')
        _make_skills_dir(self._proj_claude, ['deploy', 'release'])

    def test_project_skills_in_merged_catalog(self):
        """Project-specific skills appear alongside management skills in merged catalog."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertIn('deploy', result.skills)
        self.assertIn('release', result.skills)
        self.assertIn('commit', result.skills)
        self.assertIn('audit', result.skills)

    def test_project_skills_in_project_skills_set(self):
        """Project skills are tracked in project_skills for source tagging."""
        result = merge_catalog(self._mgmt_claude, self._proj_claude)
        self.assertIn('deploy', result.project_skills)
        self.assertIn('release', result.project_skills)


# ── AC4 edge: nonexistent project .claude/ treated like empty ─────────────────

class TestMergeCatalogNonexistentProjectDir(unittest.TestCase):
    """A project .claude/ path that does not exist on disk is treated as empty."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._mgmt_claude = os.path.join(self._tmpdir, '.claude')
        _make_agents_dir(self._mgmt_claude, ['auditor'])
        _make_skills_dir(self._mgmt_claude, ['commit'])

    def test_nonexistent_project_dir_treated_as_empty(self):
        """Passing a nonexistent project dir returns management-only catalog without error."""
        nonexistent = os.path.join(self._tmpdir, 'does-not-exist', '.claude')
        result = merge_catalog(self._mgmt_claude, nonexistent)
        self.assertIn('auditor', result.agents)
        self.assertIn('commit', result.skills)
        self.assertEqual(result.project_agents, set())
        self.assertEqual(result.project_skills, set())
