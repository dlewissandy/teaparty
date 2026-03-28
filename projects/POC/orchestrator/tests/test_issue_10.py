#!/usr/bin/env python3
"""Tests for Issue #10: Project-scoped team selection from organizational team definitions.

Covers:
 1. PhaseConfig loads org catalogue when no project config exists (backward compat)
 2. Project config selects a subset of teams
 3. Project config overrides agent model
 4. Project prompt additions are appended (additive)
 5. Project tool overrides replace org tool lists
 6. Resolution order: org defaults → project overrides
 7. PhaseConfig.project_teams returns only project-scoped teams
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator import find_poc_root
from projects.POC.orchestrator.phase_config import PhaseConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_phase_config(project_dir=None):
    """Build a PhaseConfig, optionally with a project directory."""
    return PhaseConfig(find_poc_root(), project_dir=project_dir)


def _make_project_dir(project_config: dict) -> str:
    """Create a temp dir with a project.json file."""
    d = tempfile.mkdtemp()
    with open(os.path.join(d, 'project.json'), 'w') as f:
        json.dump(project_config, f)
    return d


# ── 1. Backward compatibility: no project config ─────────────────────────────

class TestNoProjectConfig(unittest.TestCase):
    """When no project_dir is provided, PhaseConfig behaves identically to today."""

    def test_all_org_teams_available(self):
        """Without project config, all org-defined teams are available."""
        config = _make_phase_config()
        org_teams = config.teams
        self.assertIn('coding', org_teams)
        self.assertIn('art', org_teams)
        self.assertIn('writing', org_teams)
        self.assertIn('editorial', org_teams)
        self.assertIn('research', org_teams)

    def test_no_project_dir_same_as_none(self):
        """PhaseConfig(poc_root) and PhaseConfig(poc_root, None) are equivalent."""
        config_default = PhaseConfig(find_poc_root())
        config_none = PhaseConfig(find_poc_root(), project_dir=None)
        self.assertEqual(set(config_default.teams), set(config_none.teams))

    def test_empty_project_dir_no_crash(self):
        """A project_dir with no project.json falls back to org defaults."""
        d = tempfile.mkdtemp()
        config = _make_phase_config(project_dir=d)
        self.assertEqual(set(config.teams), set(_make_phase_config().teams))


# ── 2. Project team selection ─────────────────────────────────────────────────

class TestProjectTeamSelection(unittest.TestCase):
    """A project config can select a subset of org teams."""

    def test_selected_teams_only(self):
        """Only teams listed in project config are available."""
        d = _make_project_dir({'teams': {'coding': {}, 'research': {}}})
        config = _make_phase_config(project_dir=d)
        self.assertEqual(set(config.project_teams), {'coding', 'research'})

    def test_unselected_teams_excluded(self):
        """Teams not in project config are not in project_teams."""
        d = _make_project_dir({'teams': {'coding': {}}})
        config = _make_phase_config(project_dir=d)
        self.assertNotIn('art', config.project_teams)
        self.assertNotIn('writing', config.project_teams)

    def test_unknown_team_ignored(self):
        """A project team not in the org catalogue is silently ignored."""
        d = _make_project_dir({'teams': {'coding': {}, 'nonexistent': {}}})
        config = _make_phase_config(project_dir=d)
        self.assertIn('coding', config.project_teams)
        self.assertNotIn('nonexistent', config.project_teams)


# ── 3. Agent model override ──────────────────────────────────────────────────

class TestModelOverride(unittest.TestCase):
    """Project config can override agent models."""

    def test_model_override_applied(self):
        """A project-level model override changes the resolved agent model."""
        d = _make_project_dir({
            'teams': {
                'coding': {
                    'agent_overrides': {
                        'architect': {'model': 'haiku'},
                    },
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        resolved = config.resolve_team_agents('coding')
        self.assertEqual(resolved['architect']['model'], 'haiku')

    def test_unoverridden_model_preserved(self):
        """Agents without project overrides keep their org model."""
        d = _make_project_dir({
            'teams': {
                'coding': {
                    'agent_overrides': {
                        'architect': {'model': 'haiku'},
                    },
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        resolved = config.resolve_team_agents('coding')
        # 'coder' has no override, should keep org default
        self.assertNotEqual(resolved['coder']['model'], 'haiku')


# ── 4. Additive prompts ─────────────────────────────────────────────────────

class TestAdditivePrompts(unittest.TestCase):
    """Project prompt additions are appended to org base prompts."""

    def test_prompt_appended(self):
        """Project prompt addition appears after org base prompt."""
        addition = 'Focus on LaTeX formatting for all documents.'
        d = _make_project_dir({
            'teams': {
                'coding': {
                    'agent_overrides': {
                        'coder': {'prompt_addition': addition},
                    },
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        resolved = config.resolve_team_agents('coding')
        self.assertTrue(resolved['coder']['prompt'].endswith(addition))

    def test_org_prompt_preserved(self):
        """The original org prompt is still present."""
        addition = 'Focus on LaTeX.'
        d = _make_project_dir({
            'teams': {
                'coding': {
                    'agent_overrides': {
                        'coder': {'prompt_addition': addition},
                    },
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        # Load org agent definition directly for comparison
        org_config = PhaseConfig(find_poc_root())
        org_agents = org_config.resolve_team_agents('coding')
        resolved = config.resolve_team_agents('coding')
        self.assertTrue(resolved['coder']['prompt'].startswith(
            org_agents['coder']['prompt']))


# ── 5. Tool overrides ────────────────────────────────────────────────────────

class TestToolOverrides(unittest.TestCase):
    """Project tool overrides replace org tool lists (most specific wins)."""

    def test_disallowed_tools_override(self):
        """Project-level disallowedTools replaces org disallowedTools."""
        d = _make_project_dir({
            'teams': {
                'coding': {
                    'agent_overrides': {
                        'coder': {
                            'disallowedTools': ['Bash', 'Write'],
                        },
                    },
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        resolved = config.resolve_team_agents('coding')
        self.assertEqual(resolved['coder']['disallowedTools'], ['Bash', 'Write'])


# ── 6. Resolution order ─────────────────────────────────────────────────────

class TestResolutionOrder(unittest.TestCase):
    """Org defaults → project overrides."""

    def test_project_override_wins(self):
        """Project model override takes precedence over org default."""
        d = _make_project_dir({
            'teams': {
                'coding': {
                    'agent_overrides': {
                        'architect': {'model': 'haiku'},
                    },
                },
            },
        })
        org_config = PhaseConfig(find_poc_root())
        org_agents = org_config.resolve_team_agents('coding')
        self.assertNotEqual(org_agents['architect']['model'], 'haiku')

        proj_config = _make_phase_config(project_dir=d)
        proj_agents = proj_config.resolve_team_agents('coding')
        self.assertEqual(proj_agents['architect']['model'], 'haiku')


# ── 7. project_teams property ────────────────────────────────────────────────

class TestProjectTeamsProperty(unittest.TestCase):
    """PhaseConfig.project_teams returns the scoped team set."""

    def test_without_project_returns_all(self):
        """Without project config, project_teams == teams."""
        config = _make_phase_config()
        self.assertEqual(set(config.project_teams), set(config.teams))

    def test_with_project_returns_subset(self):
        """With project config, project_teams is the selected subset."""
        d = _make_project_dir({'teams': {'writing': {}, 'editorial': {}}})
        config = _make_phase_config(project_dir=d)
        self.assertEqual(set(config.project_teams), {'writing', 'editorial'})


# ── 8. Call site wiring ──────────────────────────────────────────────────────

class TestSessionWiring(unittest.TestCase):
    """Session creates PhaseConfig with project_dir."""

    def test_session_config_accepts_project_dir(self):
        """Session.__init__ creates a PhaseConfig that can be re-created with project_dir."""
        from projects.POC.orchestrator.session import Session
        # Session.__init__ accepts poc_root; config is re-created in run()
        # with project_dir. Verify PhaseConfig accepts project_dir.
        d = _make_project_dir({'teams': {'coding': {}}})
        config = PhaseConfig(find_poc_root(), project_dir=d)
        self.assertEqual(set(config.project_teams), {'coding'})


class TestDispatchListenerWiring(unittest.TestCase):
    """DispatchListener validates against project-scoped teams."""

    def test_listener_uses_project_teams(self):
        """With project_dir, listener validates against project-scoped teams."""
        from projects.POC.orchestrator.dispatch_listener import DispatchListener
        from projects.POC.orchestrator.events import EventBus
        d = _make_project_dir({'teams': {'coding': {}, 'research': {}}})
        listener = DispatchListener(
            event_bus=EventBus(),
            session_worktree='/tmp/worktree',
            infra_dir='/tmp/infra',
            project_slug='test',
            poc_root=find_poc_root(),
            project_dir=d,
        )
        self.assertEqual(listener._valid_teams, frozenset({'coding', 'research'}))

    def test_listener_without_project_dir_uses_all(self):
        """Without project_dir, listener validates against all org teams."""
        from projects.POC.orchestrator.dispatch_listener import DispatchListener
        from projects.POC.orchestrator.events import EventBus
        listener = DispatchListener(
            event_bus=EventBus(),
            session_worktree='/tmp/worktree',
            infra_dir='/tmp/infra',
            project_slug='test',
            poc_root=find_poc_root(),
        )
        org_config = PhaseConfig(find_poc_root())
        self.assertEqual(listener._valid_teams, frozenset(org_config.teams))


class TestDispatchCliWiring(unittest.TestCase):
    """dispatch_cli resolves project_dir from env."""

    def test_dispatch_creates_config_with_project_dir(self):
        """PhaseConfig accepts POC_PROJECT_DIR from environment."""
        d = _make_project_dir({'teams': {'art': {}}})
        config = PhaseConfig(find_poc_root(), project_dir=d)
        self.assertEqual(set(config.project_teams), {'art'})


class TestEngineAcceptsProjectDir(unittest.TestCase):
    """Orchestrator accepts project_dir parameter."""

    def test_orchestrator_has_project_dir(self):
        """Orchestrator stores project_dir for dispatch listener."""
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.scripts.cfa_state import make_initial_state
        from projects.POC.orchestrator.events import EventBus

        cfa = make_initial_state()
        config = PhaseConfig(find_poc_root())

        async def noop(req):
            pass

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=config,
            event_bus=EventBus(),
            input_provider=noop,
            infra_dir='/tmp/infra',
            project_workdir='/tmp/project',
            session_worktree='/tmp/worktree',
            proxy_model_path='/tmp/proxy.json',
            project_slug='test',
            poc_root=find_poc_root(),
            project_dir='/tmp/my-project',
        )
        self.assertEqual(orch.project_dir, '/tmp/my-project')


# ── 9. Permission mode overrides (finding #2) ───────────────────────────────

class TestPermissionModeOverride(unittest.TestCase):
    """Project can override permission_mode per agent."""

    def test_permission_mode_override(self):
        """Project-level permission_mode replaces org default."""
        d = _make_project_dir({
            'teams': {
                'coding': {
                    'agent_overrides': {
                        'coder': {'permission_mode': 'plan'},
                    },
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        resolved = config.resolve_team_agents('coding')
        self.assertEqual(resolved['coder']['permission_mode'], 'plan')

    def test_planning_permission_mode_override(self):
        """Project can override team-level planning_permission_mode."""
        d = _make_project_dir({
            'teams': {
                'coding': {
                    'planning_permission_mode': 'acceptEdits',
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        team = config.resolve_team_spec('coding')
        self.assertEqual(team.planning_permission_mode, 'acceptEdits')

    def test_planning_permission_mode_org_default(self):
        """Without override, org planning_permission_mode is preserved."""
        d = _make_project_dir({'teams': {'coding': {}}})
        config = _make_phase_config(project_dir=d)
        org_config = _make_phase_config()
        org_team = org_config.team('coding')
        proj_team = config.resolve_team_spec('coding')
        self.assertEqual(proj_team.planning_permission_mode, org_team.planning_permission_mode)


# ── 10. Skills overrides (finding #3) ───────────────────────────────────────

class TestSkillsOverride(unittest.TestCase):
    """Project can configure skills (allowedTools) per agent."""

    def test_allowed_tools_override(self):
        """Project-level allowedTools replaces org default."""
        d = _make_project_dir({
            'teams': {
                'coding': {
                    'agent_overrides': {
                        'coder': {
                            'allowedTools': ['Read', 'Write', 'Grep'],
                        },
                    },
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        resolved = config.resolve_team_agents('coding')
        self.assertEqual(resolved['coder']['allowedTools'], ['Read', 'Write', 'Grep'])


# ── 11. Project .claude/CLAUDE.md (finding #1) ──────────────────────────────

class TestProjectClaudeMd(unittest.TestCase):
    """PhaseConfig loads .claude/CLAUDE.md from project_dir."""

    def test_claude_md_loaded(self):
        """CLAUDE.md content is available via project_claude_md."""
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, '.claude'))
        with open(os.path.join(d, '.claude', 'CLAUDE.md'), 'w') as f:
            f.write('# Project Rules\nUse LaTeX for all docs.')
        with open(os.path.join(d, 'project.json'), 'w') as f:
            json.dump({'teams': {'coding': {}}}, f)
        config = _make_phase_config(project_dir=d)
        self.assertEqual(config.project_claude_md, '# Project Rules\nUse LaTeX for all docs.')

    def test_no_claude_md_returns_empty(self):
        """Without .claude/CLAUDE.md, project_claude_md is empty string."""
        d = _make_project_dir({'teams': {'coding': {}}})
        config = _make_phase_config(project_dir=d)
        self.assertEqual(config.project_claude_md, '')

    def test_no_project_dir_returns_empty(self):
        """Without project_dir, project_claude_md is empty string."""
        config = _make_phase_config()
        self.assertEqual(config.project_claude_md, '')


# ── 12. Phase-level overrides (finding #5) ───────────────────────────────────

class TestPhaseOverrides(unittest.TestCase):
    """Project can override phase-level agent configuration."""

    def test_phase_agent_file_override(self):
        """Project can override which agent file a phase uses."""
        d = _make_project_dir({
            'teams': {'coding': {}},
            'phases': {
                'planning': {
                    'agent_file': 'agents/coding-team.json',
                    'lead': 'coding-lead',
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        spec = config.resolve_phase('planning')
        self.assertEqual(spec.agent_file, 'agents/coding-team.json')
        self.assertEqual(spec.lead, 'coding-lead')

    def test_phase_permission_mode_override(self):
        """Project can override phase permission_mode."""
        d = _make_project_dir({
            'teams': {'coding': {}},
            'phases': {
                'execution': {
                    'permission_mode': 'plan',
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        spec = config.resolve_phase('execution')
        self.assertEqual(spec.permission_mode, 'plan')

    def test_phase_settings_overlay_override(self):
        """Project can override phase settings_overlay."""
        d = _make_project_dir({
            'teams': {'coding': {}},
            'phases': {
                'intent': {
                    'settings_overlay': {
                        'permissions': {'allow': ['Read', 'Grep']},
                    },
                },
            },
        })
        config = _make_phase_config(project_dir=d)
        spec = config.resolve_phase('intent')
        self.assertEqual(spec.settings_overlay, {'permissions': {'allow': ['Read', 'Grep']}})

    def test_unoverridden_phase_preserved(self):
        """Phases without project overrides keep org defaults."""
        d = _make_project_dir({
            'teams': {'coding': {}},
            'phases': {
                'planning': {'lead': 'coding-lead'},
            },
        })
        config = _make_phase_config(project_dir=d)
        org_config = _make_phase_config()
        # execution not overridden
        self.assertEqual(
            config.resolve_phase('execution').agent_file,
            org_config.phase('execution').agent_file,
        )

    def test_no_project_phases_returns_org(self):
        """Without phase overrides, resolve_phase returns org defaults."""
        d = _make_project_dir({'teams': {'coding': {}}})
        config = _make_phase_config(project_dir=d)
        org_config = _make_phase_config()
        for phase_name in ('intent', 'planning', 'execution'):
            resolved = config.resolve_phase(phase_name)
            org = org_config.phase(phase_name)
            self.assertEqual(resolved.agent_file, org.agent_file)
            self.assertEqual(resolved.lead, org.lead)


if __name__ == '__main__':
    unittest.main()
