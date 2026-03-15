#!/usr/bin/env python3
"""Tests for skill_lookup.py — dual-process routing for planning.

Covers:
 1. lookup_skill finds the best matching skill above threshold.
 2. lookup_skill returns None when no skills match above threshold.
 3. lookup_skill returns None when skills_dir does not exist.
 4. Skill frontmatter is parsed correctly into SkillMatch fields.
 5. Multiple skills: the highest-scoring one is returned.
 6. lookup_skill is fail-safe: malformed skill files are skipped.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.skill_lookup import SkillMatch, lookup_skill


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_skills_dir(skills: dict[str, str]) -> tempfile.TemporaryDirectory:
    """Create a temp directory with skill markdown files.

    Args:
        skills: mapping of filename → file content
    Returns:
        TemporaryDirectory (caller must manage lifetime)
    """
    td = tempfile.TemporaryDirectory()
    for name, content in skills.items():
        with open(os.path.join(td.name, name), 'w') as f:
            f.write(content)
    return td


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


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestLookupSkill(unittest.TestCase):
    """Skill lookup returns the best matching skill or None."""

    def test_returns_match_above_threshold(self):
        """A skill whose description overlaps the task is returned."""
        td = _make_skills_dir({
            'research-paper.md': _make_skill_content(
                name='research-paper',
                description='Write a research paper with literature survey and argument construction',
                category='writing',
                body='## Decomposition\n\n1. Survey\n2. Argue\n3. Draft',
            ),
        })
        with td:
            result = lookup_skill(
                task='Write a research paper on distributed systems',
                intent='Research and write a paper surveying distributed consensus algorithms',
                skills_dir=td.name,
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.name, 'research-paper')
            self.assertGreater(result.score, 0.0)
            self.assertIn('Survey', result.template)

    def test_returns_none_when_no_match(self):
        """A skill with unrelated description returns None."""
        td = _make_skills_dir({
            'database-migration.md': _make_skill_content(
                name='database-migration',
                description='Migrate database schema with rollback plan',
                category='infrastructure',
            ),
        })
        with td:
            result = lookup_skill(
                task='Design a logo for the company website',
                intent='Create a modern minimalist logo',
                skills_dir=td.name,
                threshold=0.3,
            )
            self.assertIsNone(result)

    def test_returns_none_when_dir_missing(self):
        """Returns None when skills_dir does not exist."""
        result = lookup_skill(
            task='anything',
            intent='anything',
            skills_dir='/nonexistent/skills',
        )
        self.assertIsNone(result)

    def test_returns_none_for_empty_dir(self):
        """Returns None when skills_dir exists but has no .md files."""
        td = _make_skills_dir({})
        with td:
            result = lookup_skill(
                task='Write a paper',
                intent='Research paper',
                skills_dir=td.name,
            )
            self.assertIsNone(result)

    def test_best_of_multiple_skills_returned(self):
        """When multiple skills exist, the highest-scoring one is returned."""
        td = _make_skills_dir({
            'api-endpoint.md': _make_skill_content(
                name='api-endpoint',
                description='Build a REST API endpoint with tests and documentation',
                category='coding',
                body='## Steps\n\n1. Schema\n2. Route\n3. Tests',
            ),
            'research-paper.md': _make_skill_content(
                name='research-paper',
                description='Write a research paper with literature survey',
                category='writing',
                body='## Steps\n\n1. Survey\n2. Draft',
            ),
        })
        with td:
            result = lookup_skill(
                task='Build a new REST API endpoint for user profiles',
                intent='Create a /users endpoint with CRUD operations and tests',
                skills_dir=td.name,
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.name, 'api-endpoint')

    def test_frontmatter_parsed_into_match_fields(self):
        """SkillMatch fields are populated from skill file frontmatter."""
        td = _make_skills_dir({
            'bug-fix.md': _make_skill_content(
                name='bug-fix',
                description='Systematic bug investigation and fix',
                category='debugging',
                body='## Workflow\n\n1. Reproduce\n2. Root cause\n3. Fix\n4. Test',
            ),
        })
        with td:
            result = lookup_skill(
                task='Fix the bug in the login flow',
                intent='Investigate and fix the authentication bug causing login failures',
                skills_dir=td.name,
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.name, 'bug-fix')
            self.assertEqual(result.description, 'Systematic bug investigation and fix')
            self.assertTrue(result.path.endswith('bug-fix.md'))
            self.assertIn('Reproduce', result.template)

    def test_malformed_skill_file_skipped(self):
        """A skill file with broken frontmatter is skipped, not an error."""
        td = _make_skills_dir({
            'good.md': _make_skill_content(
                name='good-skill',
                description='Fix bugs systematically with investigation and testing',
                category='debugging',
                body='## Good plan',
            ),
            'bad.md': '---\nthis is not valid: [yaml: {{{\n---\nSome body',
        })
        with td:
            # Should not raise — bad file is skipped, good file is found
            result = lookup_skill(
                task='Fix a bug with investigation and testing',
                intent='Systematically investigate and fix the bug',
                skills_dir=td.name,
            )
            # The good skill should still be findable
            self.assertIsNotNone(result)
            self.assertEqual(result.name, 'good-skill')

    def test_non_md_files_ignored(self):
        """Only .md files are considered as skills."""
        td = _make_skills_dir({
            'notes.txt': 'This is not a skill file',
            'config.json': '{"not": "a skill"}',
        })
        with td:
            result = lookup_skill(
                task='anything',
                intent='anything',
                skills_dir=td.name,
            )
            self.assertIsNone(result)


class TestSkillLookupIntegrationWithEngine(unittest.TestCase):
    """Engine routes between System 1 (skill) and System 2 (cold-start planning)."""

    def _make_orchestrator(self, worktree, project_dir, infra_dir=None):
        """Build an Orchestrator with mocked runners for routing tests."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.orchestrator.phase_config import PhaseConfig, PhaseSpec
        from projects.POC.scripts.cfa_state import CfaState

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
            task='Write a research paper on distributed systems',
            session_id='test-session',
        )
        return orch

    def test_skill_match_writes_plan_md(self):
        """When a skill matches, its template is written as PLAN.md in infra_dir."""
        with tempfile.TemporaryDirectory() as worktree, \
             tempfile.TemporaryDirectory() as project_dir, \
             tempfile.TemporaryDirectory() as infra_dir:
            # Write INTENT.md to infra_dir (Issue #147: artifacts live there)
            with open(os.path.join(infra_dir, 'INTENT.md'), 'w') as f:
                f.write('Research and write a paper surveying distributed consensus.')

            # Create skill library
            skills_dir = os.path.join(project_dir, 'skills')
            os.makedirs(skills_dir)
            with open(os.path.join(skills_dir, 'research-paper.md'), 'w') as f:
                f.write(_make_skill_content(
                    name='research-paper',
                    description='Write a research paper with literature survey and argument construction',
                    category='writing',
                    body='## Decomposition\n\n1. Survey\n2. Argue\n3. Draft',
                ))

            orch = self._make_orchestrator(worktree, project_dir, infra_dir=infra_dir)
            result = asyncio.run(orch._try_skill_lookup())

            self.assertTrue(result)
            plan_path = os.path.join(infra_dir, 'PLAN.md')
            self.assertTrue(os.path.exists(plan_path))
            with open(plan_path) as f:
                plan_content = f.read()
            self.assertIn('Survey', plan_content)
            self.assertIn('Argue', plan_content)

    def test_skill_match_advances_cfa_to_plan_assert(self):
        """When a skill matches, CfA state advances to PLAN_ASSERT."""
        with tempfile.TemporaryDirectory() as worktree, \
             tempfile.TemporaryDirectory() as project_dir:
            with open(os.path.join(worktree, 'INTENT.md'), 'w') as f:
                f.write('Research and write a paper surveying distributed consensus.')

            skills_dir = os.path.join(project_dir, 'skills')
            os.makedirs(skills_dir)
            with open(os.path.join(skills_dir, 'research-paper.md'), 'w') as f:
                f.write(_make_skill_content(
                    name='research-paper',
                    description='Write a research paper with literature survey and argument construction',
                    category='writing',
                    body='## Decomposition\n\n1. Survey\n2. Argue\n3. Draft',
                ))

            orch = self._make_orchestrator(worktree, project_dir)
            asyncio.run(orch._try_skill_lookup())

            self.assertEqual(orch.cfa.state, 'PLAN_ASSERT')

    def test_no_skill_match_returns_false_state_unchanged(self):
        """When no skill matches, returns False and CfA stays at DRAFT."""
        with tempfile.TemporaryDirectory() as worktree, \
             tempfile.TemporaryDirectory() as project_dir:
            with open(os.path.join(worktree, 'INTENT.md'), 'w') as f:
                f.write('Design a logo for the company.')

            # Empty skills dir
            os.makedirs(os.path.join(project_dir, 'skills'))

            orch = self._make_orchestrator(worktree, project_dir)
            result = asyncio.run(orch._try_skill_lookup())

            self.assertFalse(result)
            self.assertEqual(orch.cfa.state, 'DRAFT')
            # No PLAN.md written
            self.assertFalse(os.path.exists(os.path.join(worktree, 'PLAN.md')))

    def test_no_skills_dir_returns_false(self):
        """When skills/ doesn't exist, returns False silently."""
        with tempfile.TemporaryDirectory() as worktree, \
             tempfile.TemporaryDirectory() as project_dir:
            orch = self._make_orchestrator(worktree, project_dir)
            result = asyncio.run(orch._try_skill_lookup())

            self.assertFalse(result)
            self.assertEqual(orch.cfa.state, 'DRAFT')


if __name__ == '__main__':
    unittest.main()
