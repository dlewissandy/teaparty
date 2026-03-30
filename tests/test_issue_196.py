#!/usr/bin/env python3
"""Tests for Issue #196 — Project-scoped and team-scoped skills.

Covers:
 1. SkillMatch includes a scope field.
 2. lookup_skill with skills_dirs searches multiple directories.
 3. Team-scoped skill overrides project-scoped skill of the same name.
 4. When no team skill matches, project skill is returned.
 5. Scores from all scopes are compared; best score wins (different names).
 6. Skill override is name-based: same name at narrower scope shadows broader.
 7. Engine._try_skill_lookup builds scoped skill dirs when team_override is set.
 8. Engine._try_skill_lookup uses project-only when no team context.
 9. procedural_learning.crystallize_skills writes to team dir when team_name given.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.skill_lookup import SkillMatch, lookup_skill


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_skill_content(
    name: str = 'test-skill',
    description: str = 'A test skill',
    category: str = 'testing',
    body: str = '## Steps\n\n1. Do the thing\n2. Verify the thing',
) -> str:
    return (
        f'---\n'
        f'name: {name}\n'
        f'description: {description}\n'
        f'category: {category}\n'
        f'---\n\n'
        f'{body}'
    )


def _write_skill(directory: str, filename: str, content: str) -> str:
    """Write a skill file and return its path."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    with open(path, 'w') as f:
        f.write(content)
    return path


def _run(coro):
    return asyncio.run(coro)


# ── Tests: SkillMatch scope field ─────────────────────────────────────────────

class TestSkillMatchScope(unittest.TestCase):
    """SkillMatch includes a scope field indicating which scope produced it."""

    def test_skill_match_has_scope_field(self):
        """SkillMatch dataclass has a scope field."""
        m = SkillMatch(
            name='test', path='/tmp/test.md', description='desc',
            score=0.5, template='body', scope='team',
        )
        self.assertEqual(m.scope, 'team')

    def test_skill_match_scope_defaults_to_project(self):
        """When scope is not specified, SkillMatch defaults to 'project'."""
        m = SkillMatch(
            name='test', path='/tmp/test.md', description='desc',
            score=0.5, template='body',
        )
        self.assertEqual(m.scope, 'project')


# ── Tests: Scoped skill lookup ────────────────────────────────────────────────

class TestScopedSkillLookup(unittest.TestCase):
    """lookup_skill with skills_dirs searches multiple scope-ordered directories."""

    def test_skills_dirs_returns_match_with_scope(self):
        """A match from skills_dirs includes the scope that produced it."""
        with tempfile.TemporaryDirectory() as td:
            project_skills = os.path.join(td, 'project', 'skills')
            _write_skill(project_skills, 'research.md', _make_skill_content(
                name='research',
                description='Write a research paper with literature survey',
                category='writing',
            ))

            result = lookup_skill(
                task='Write a research paper on distributed systems',
                intent='Research and write a paper surveying consensus algorithms',
                skills_dirs=[('project', project_skills)],
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.scope, 'project')

    def test_team_skill_overrides_project_skill_same_name(self):
        """A team skill with the same name as a project skill wins."""
        with tempfile.TemporaryDirectory() as td:
            project_skills = os.path.join(td, 'project', 'skills')
            team_skills = os.path.join(td, 'team', 'skills')

            _write_skill(project_skills, 'deploy.md', _make_skill_content(
                name='deploy',
                description='Deploy service to production environment',
                category='infrastructure',
                body='## Project deploy steps',
            ))
            _write_skill(team_skills, 'deploy.md', _make_skill_content(
                name='deploy',
                description='Deploy service to production environment',
                category='infrastructure',
                body='## Team-specific deploy steps',
            ))

            result = lookup_skill(
                task='Deploy the service to production',
                intent='Deploy the microservice to production environment',
                skills_dirs=[('team', team_skills), ('project', project_skills)],
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.scope, 'team')
            self.assertIn('Team-specific', result.template)

    def test_project_skill_returned_when_no_team_skill(self):
        """When team dir has no matching skill, project skill is returned."""
        with tempfile.TemporaryDirectory() as td:
            project_skills = os.path.join(td, 'project', 'skills')
            team_skills = os.path.join(td, 'team', 'skills')
            os.makedirs(team_skills)  # empty team dir

            _write_skill(project_skills, 'deploy.md', _make_skill_content(
                name='deploy',
                description='Deploy service to production environment',
                category='infrastructure',
                body='## Project deploy steps',
            ))

            result = lookup_skill(
                task='Deploy the service to production',
                intent='Deploy the microservice to production environment',
                skills_dirs=[('team', team_skills), ('project', project_skills)],
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.scope, 'project')

    def test_best_score_wins_across_scopes_different_names(self):
        """When skills have different names, the best score wins regardless of scope."""
        with tempfile.TemporaryDirectory() as td:
            project_skills = os.path.join(td, 'project', 'skills')
            team_skills = os.path.join(td, 'team', 'skills')

            # Project skill is a better match for the task
            _write_skill(project_skills, 'api-endpoint.md', _make_skill_content(
                name='api-endpoint',
                description='Build a REST API endpoint with tests and documentation',
                category='coding',
                body='## API steps',
            ))
            # Team skill is unrelated
            _write_skill(team_skills, 'logo-design.md', _make_skill_content(
                name='logo-design',
                description='Design a logo with brand guidelines',
                category='design',
                body='## Logo steps',
            ))

            result = lookup_skill(
                task='Build a new REST API endpoint for user profiles',
                intent='Create a /users endpoint with CRUD operations and tests',
                skills_dirs=[('team', team_skills), ('project', project_skills)],
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.name, 'api-endpoint')
            self.assertEqual(result.scope, 'project')

    def test_name_override_applies_before_scoring(self):
        """Same-name override happens before scoring — the broader skill is eliminated."""
        with tempfile.TemporaryDirectory() as td:
            project_skills = os.path.join(td, 'project', 'skills')
            team_skills = os.path.join(td, 'team', 'skills')

            # Project has a rich description that would score well
            _write_skill(project_skills, 'deploy.md', _make_skill_content(
                name='deploy',
                description='Deploy the production microservice with full rollback support',
                category='infrastructure deployment production',
                body='## Rich project deploy',
            ))
            # Team overrides with a minimal description
            _write_skill(team_skills, 'deploy.md', _make_skill_content(
                name='deploy',
                description='Quick deploy',
                category='ops',
                body='## Quick team deploy',
            ))

            result = lookup_skill(
                task='Deploy the production microservice',
                intent='Deploy the microservice to production environment',
                skills_dirs=[('team', team_skills), ('project', project_skills)],
                threshold=0.05,  # Low threshold — testing override, not scoring
            )
            # Team version wins even with a weaker description
            self.assertIsNotNone(result)
            self.assertEqual(result.scope, 'team')
            self.assertIn('Quick team deploy', result.template)

    def test_nonexistent_scope_dir_is_skipped(self):
        """A scope dir that doesn't exist is silently skipped."""
        with tempfile.TemporaryDirectory() as td:
            project_skills = os.path.join(td, 'project', 'skills')
            _write_skill(project_skills, 'research.md', _make_skill_content(
                name='research',
                description='Write a research paper with literature survey',
                category='writing',
            ))

            result = lookup_skill(
                task='Write a research paper on distributed systems',
                intent='Research and write a paper surveying consensus algorithms',
                skills_dirs=[
                    ('team', '/nonexistent/team/skills'),
                    ('project', project_skills),
                ],
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.scope, 'project')

    def test_backward_compat_single_skills_dir(self):
        """The old skills_dir parameter still works for single-scope lookup."""
        with tempfile.TemporaryDirectory() as td:
            skills_dir = os.path.join(td, 'skills')
            _write_skill(skills_dir, 'research.md', _make_skill_content(
                name='research',
                description='Write a research paper with literature survey',
                category='writing',
            ))

            result = lookup_skill(
                task='Write a research paper on distributed systems',
                intent='Research and write a paper surveying consensus algorithms',
                skills_dir=skills_dir,
            )
            self.assertIsNotNone(result)
            # Default scope for single-dir lookup
            self.assertEqual(result.scope, 'project')


# ── Tests: Engine integration ─────────────────────────────────────────────────

class TestEngineScopedSkillLookup(unittest.TestCase):
    """Engine._try_skill_lookup builds scoped skill dirs from team context."""

    def _make_orchestrator(self, worktree, project_dir, infra_dir=None,
                           team_override=''):
        from orchestrator.engine import Orchestrator
        from orchestrator.events import EventBus
        from orchestrator.phase_config import PhaseConfig, PhaseSpec
        from scripts.cfa_state import CfaState

        if infra_dir is None:
            infra_dir = '/tmp/infra'

        cfg = MagicMock(spec=PhaseConfig)
        cfg.stall_timeout = 1800
        cfg.human_actor_states = frozenset()
        cfg.phase.return_value = PhaseSpec(
            name='planning', agent_file='agents/uber-team.json',
            lead='project-lead', permission_mode='acceptEdits',
            stream_file='.plan-stream.jsonl', artifact='PLAN.md',
            approval_state='PLAN_ASSERT', settings_overlay={},
        )

        orch = Orchestrator(
            cfa_state=CfaState(state='DRAFT', phase='planning', actor='agent',
                               history=[], backtrack_count=0),
            phase_config=cfg,
            event_bus=MagicMock(spec=EventBus, publish=AsyncMock()),
            input_provider=AsyncMock(),
            infra_dir=infra_dir,
            project_workdir=project_dir,
            session_worktree=worktree,
            proxy_model_path='/tmp/proxy.json',
            project_slug='test',
            poc_root='/tmp/poc',
            task='Deploy the service to production',
            session_id='test-session',
            team_override=team_override,
        )
        return orch

    def test_team_skill_found_via_engine(self):
        """Engine uses team skill dir when team_override is set."""
        with tempfile.TemporaryDirectory() as worktree, \
             tempfile.TemporaryDirectory() as project_dir, \
             tempfile.TemporaryDirectory() as infra_dir:

            with open(os.path.join(infra_dir, 'INTENT.md'), 'w') as f:
                f.write('Deploy the microservice to production environment')

            # Team skill
            team_skills = os.path.join(project_dir, 'teams', 'coding-team', 'skills')
            _write_skill(team_skills, 'deploy.md', _make_skill_content(
                name='deploy',
                description='Deploy service to production environment',
                category='infrastructure',
                body='## Team deploy steps',
            ))

            orch = self._make_orchestrator(
                worktree, project_dir, infra_dir=infra_dir,
                team_override='coding-team',
            )
            result = _run(orch._try_skill_lookup())

            self.assertTrue(result)
            plan_path = os.path.join(infra_dir, 'PLAN.md')
            self.assertTrue(os.path.exists(plan_path))
            with open(plan_path) as f:
                self.assertIn('Team deploy', f.read())

            # Scope is propagated to active skill and sidecar
            self.assertEqual(orch._active_skill['scope'], 'team')
            import json
            sidecar = os.path.join(infra_dir, '.active-skill.json')
            with open(sidecar) as f:
                sidecar_data = json.load(f)
            self.assertEqual(sidecar_data['scope'], 'team')

    def test_project_skill_used_when_no_team_override(self):
        """Without team_override, only project skills dir is searched."""
        with tempfile.TemporaryDirectory() as worktree, \
             tempfile.TemporaryDirectory() as project_dir, \
             tempfile.TemporaryDirectory() as infra_dir:

            with open(os.path.join(infra_dir, 'INTENT.md'), 'w') as f:
                f.write('Deploy the microservice to production environment')

            # Project skill only
            project_skills = os.path.join(project_dir, 'skills')
            _write_skill(project_skills, 'deploy.md', _make_skill_content(
                name='deploy',
                description='Deploy service to production environment',
                category='infrastructure',
                body='## Project deploy steps',
            ))

            orch = self._make_orchestrator(
                worktree, project_dir, infra_dir=infra_dir,
            )
            result = _run(orch._try_skill_lookup())

            self.assertTrue(result)
            plan_path = os.path.join(infra_dir, 'PLAN.md')
            with open(plan_path) as f:
                self.assertIn('Project deploy', f.read())

    def test_team_overrides_project_in_engine(self):
        """Engine prefers team skill over project skill of same name."""
        with tempfile.TemporaryDirectory() as worktree, \
             tempfile.TemporaryDirectory() as project_dir, \
             tempfile.TemporaryDirectory() as infra_dir:

            with open(os.path.join(infra_dir, 'INTENT.md'), 'w') as f:
                f.write('Deploy the microservice to production environment')

            # Project skill
            project_skills = os.path.join(project_dir, 'skills')
            _write_skill(project_skills, 'deploy.md', _make_skill_content(
                name='deploy',
                description='Deploy service to production environment',
                category='infrastructure',
                body='## Project deploy steps',
            ))
            # Team skill (same name, overrides)
            team_skills = os.path.join(project_dir, 'teams', 'coding-team', 'skills')
            _write_skill(team_skills, 'deploy.md', _make_skill_content(
                name='deploy',
                description='Deploy service to production environment',
                category='infrastructure',
                body='## Team-specific deploy steps',
            ))

            orch = self._make_orchestrator(
                worktree, project_dir, infra_dir=infra_dir,
                team_override='coding-team',
            )
            result = _run(orch._try_skill_lookup())

            self.assertTrue(result)
            plan_path = os.path.join(infra_dir, 'PLAN.md')
            with open(plan_path) as f:
                self.assertIn('Team-specific', f.read())


# ── Tests: Procedural learning team scope ─────────────────────────────────────

class TestProceduralLearningTeamScope(unittest.TestCase):
    """crystallize_skills writes to team dir when team_name is provided."""

    def _make_candidate(self, candidates_dir, filename, *, task='Write a paper',
                        category='writing', status='pending'):
        """Write a skill candidate file with frontmatter."""
        content = (
            f'---\n'
            f'task: {task}\n'
            f'category: {category}\n'
            f'status: {status}\n'
            f'session_id: test-session\n'
            f'timestamp: 2026-03-14T12:00:00\n'
            f'---\n\n'
            f'## Decomposition\n\n1. Survey\n2. Draft\n3. Edit\n'
        )
        os.makedirs(candidates_dir, exist_ok=True)
        path = os.path.join(candidates_dir, filename)
        with open(path, 'w') as f:
            f.write(content)
        return path

    def test_crystallize_to_team_dir(self):
        """When team_name is given, skills are written to teams/{name}/skills/."""
        from unittest.mock import patch
        from orchestrator.procedural_learning import crystallize_skills

        with tempfile.TemporaryDirectory() as project_dir:
            candidates_dir = os.path.join(project_dir, 'skill-candidates')
            for i in range(3):
                self._make_candidate(candidates_dir, f'candidate-{i}.md')

            fake_skill = (
                '---\n'
                'name: research-paper\n'
                'description: Write a research paper\n'
                'category: writing\n'
                '---\n\n'
                '## Steps\n1. Survey\n2. Draft\n3. Edit\n'
            )
            with patch(
                'orchestrator.procedural_learning._generalize_candidates',
                return_value=fake_skill,
            ):
                result = crystallize_skills(
                    project_dir=project_dir, team_name='coding-team',
                )

            self.assertEqual(result, 1)
            team_skills_dir = os.path.join(
                project_dir, 'teams', 'coding-team', 'skills',
            )
            self.assertTrue(os.path.isdir(team_skills_dir))
            skill_files = [f for f in os.listdir(team_skills_dir) if f.endswith('.md')]
            self.assertEqual(len(skill_files), 1)

            # Project-level skills/ should NOT exist
            project_skills_dir = os.path.join(project_dir, 'skills')
            self.assertFalse(os.path.exists(project_skills_dir))

    def test_crystallize_without_team_uses_project_dir(self):
        """Without team_name, skills are written to {project_dir}/skills/."""
        from unittest.mock import patch
        from orchestrator.procedural_learning import crystallize_skills

        with tempfile.TemporaryDirectory() as project_dir:
            candidates_dir = os.path.join(project_dir, 'skill-candidates')
            for i in range(3):
                self._make_candidate(candidates_dir, f'candidate-{i}.md')

            fake_skill = (
                '---\n'
                'name: research-paper\n'
                'description: Write a research paper\n'
                'category: writing\n'
                '---\n\n'
                '## Steps\n1. Survey\n2. Draft\n3. Edit\n'
            )
            with patch(
                'orchestrator.procedural_learning._generalize_candidates',
                return_value=fake_skill,
            ):
                result = crystallize_skills(project_dir=project_dir)

            self.assertEqual(result, 1)
            project_skills_dir = os.path.join(project_dir, 'skills')
            self.assertTrue(os.path.isdir(project_skills_dir))
            skill_files = [f for f in os.listdir(project_skills_dir) if f.endswith('.md')]
            self.assertEqual(len(skill_files), 1)

            # Team dir should NOT exist
            teams_dir = os.path.join(project_dir, 'teams')
            self.assertFalse(os.path.exists(teams_dir))


if __name__ == '__main__':
    unittest.main()
