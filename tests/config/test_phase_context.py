"""Tests for ``teaparty.config.phase_context`` — phase task context helpers.

The CfA engine's intent + planning phases benefit from project-aware
prose injected into their task prompts: norms framed as constraints,
the team roster, the skills catalog.  These three helpers turn config
into ready-to-inject strings; the engine concatenates them and stays
out of YAML schemas.

Cut 20 extracted these from engine.py (where they had no tests).  The
tests below pin the formatting contract so any future tweak to the
prose is intentional.
"""
from __future__ import annotations

import os
import tempfile
import textwrap
import unittest

from teaparty.config.phase_context import (
    intent_constraints_block,
    available_teams_block,
    list_available_skills,
)


def _write_skill(
    dirpath: str, filename: str, *,
    name: str = '', description: str = '', needs_review: bool = False,
) -> str:
    os.makedirs(dirpath, exist_ok=True)
    path = os.path.join(dirpath, filename)
    fm = []
    if name:
        fm.append(f'name: {name}')
    if description:
        fm.append(f'description: {description}')
    if needs_review:
        fm.append('needs_review: true')
    body = '\n'.join(fm)
    with open(path, 'w') as f:
        f.write(f'---\n{body}\n---\n# Skill\n')
    return path


# ── list_available_skills ──────────────────────────────────────────────────

class TestListAvailableSkills(unittest.TestCase):
    """Skill catalog formatting: name + description, dedup, exclusion."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_empty_when_no_skills_dir(self):
        out = list_available_skills(project_workdir=self._tmp)
        self.assertEqual(out, '')

    def test_lists_project_skills_with_descriptions(self):
        _write_skill(
            os.path.join(self._tmp, 'skills'), 'foo.md',
            name='foo', description='do the foo thing',
        )
        _write_skill(
            os.path.join(self._tmp, 'skills'), 'bar.md',
            name='bar', description='do the bar thing',
        )
        out = list_available_skills(project_workdir=self._tmp)
        # Sorted by filename → bar before foo.
        self.assertEqual(out, '- bar: do the bar thing\n- foo: do the foo thing')

    def test_excludes_skills_marked_needs_review(self):
        _write_skill(
            os.path.join(self._tmp, 'skills'), 'good.md',
            name='good', description='ready',
        )
        _write_skill(
            os.path.join(self._tmp, 'skills'), 'pending.md',
            name='pending', description='not safe',
            needs_review=True,
        )
        out = list_available_skills(project_workdir=self._tmp)
        self.assertIn('good', out)
        self.assertNotIn('pending', out)

    def test_team_skills_take_precedence_over_project_dups(self):
        """Same skill name in team + project: team-scoped wins (appears first)."""
        team_dir = os.path.join(
            self._tmp, 'teams', 'art', 'skills',
        )
        proj_dir = os.path.join(self._tmp, 'skills')
        _write_skill(
            team_dir, 'render.md',
            name='render', description='team-scoped render',
        )
        _write_skill(
            proj_dir, 'render.md',
            name='render', description='project-scoped render',
        )
        out = list_available_skills(
            project_workdir=self._tmp, team_override='art',
        )
        self.assertIn('team-scoped render', out)
        self.assertNotIn('project-scoped render', out)

    def test_filename_used_when_frontmatter_lacks_name(self):
        _write_skill(
            os.path.join(self._tmp, 'skills'), 'fallback.md',
            description='no name',
        )
        out = list_available_skills(project_workdir=self._tmp)
        self.assertIn('fallback', out)

    def test_unparseable_skill_is_skipped_not_fatal(self):
        skills_dir = os.path.join(self._tmp, 'skills')
        os.makedirs(skills_dir)
        # File with no frontmatter — _parse_frontmatter raises.
        with open(os.path.join(skills_dir, 'broken.md'), 'w') as f:
            f.write('not actually a skill\n')
        # Plus a real skill so the assertion has something to find.
        _write_skill(skills_dir, 'real.md', name='real', description='ok')
        out = list_available_skills(project_workdir=self._tmp)
        self.assertIn('real', out)


# ── available_teams_block ──────────────────────────────────────────────────

class TestAvailableTeamsBlock(unittest.TestCase):
    """Combined teams + skills block for the planning phase."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_empty_when_no_teams_and_no_skills(self):
        out = available_teams_block(
            project_teams=None, project_workdir=self._tmp,
        )
        self.assertEqual(out, '')

    def test_teams_only(self):
        out = available_teams_block(
            project_teams={'art': {}, 'writing': {}},
            project_workdir=self._tmp,
        )
        self.assertIn('--- Planning Constraints ---', out)
        self.assertIn('art, writing', out)
        self.assertIn('Only reference these teams', out)
        self.assertNotIn('Available skills', out)

    def test_skills_only(self):
        _write_skill(
            os.path.join(self._tmp, 'skills'), 'plan-pattern.md',
            name='plan-pattern', description='reusable plan',
        )
        out = available_teams_block(
            project_teams=None, project_workdir=self._tmp,
        )
        self.assertIn('Available skills', out)
        self.assertIn('plan-pattern', out)
        self.assertNotIn('Available teams', out)

    def test_both_in_order(self):
        """Teams come before skills when both are present."""
        _write_skill(
            os.path.join(self._tmp, 'skills'), 'foo.md',
            name='foo', description='thing',
        )
        out = available_teams_block(
            project_teams={'art': {}},
            project_workdir=self._tmp,
        )
        teams_idx = out.index('Available teams')
        skills_idx = out.index('Available skills')
        self.assertLess(teams_idx, skills_idx)

    def test_team_names_sorted(self):
        """Team names appear in lexical order — deterministic for prompts."""
        out = available_teams_block(
            project_teams={'zeta': {}, 'alpha': {}, 'mu': {}},
            project_workdir=self._tmp,
        )
        self.assertIn('alpha, mu, zeta', out)


# ── intent_constraints_block ───────────────────────────────────────────────

class TestIntentConstraintsBlock(unittest.TestCase):
    """Norm resolution + constraint framing for the intent phase."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        # Build a minimal teaparty_home with management/teaparty.yaml.
        self._tp = os.path.join(self._tmp, '.teaparty')
        os.makedirs(os.path.join(self._tp, 'management'))

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_management_yaml(self, norms: dict[str, list[str]]) -> None:
        import yaml
        config = {
            'name': 'TestOrg',
            'description': 'test',
            'norms': norms,
        }
        with open(os.path.join(self._tp, 'management', 'teaparty.yaml'), 'w') as f:
            yaml.safe_dump(config, f)

    def test_empty_when_no_norms_anywhere(self):
        self._write_management_yaml({})
        out = intent_constraints_block(teaparty_home=self._tp)
        self.assertEqual(out, '')

    def test_org_norms_framed_as_constraints(self):
        self._write_management_yaml({'guardrails': ['be honest']})
        out = intent_constraints_block(teaparty_home=self._tp)
        self.assertIn('--- Constraints ---', out)
        self.assertIn('be honest', out)
        self.assertIn('escalate', out)
        self.assertIn('--- end ---', out)

    def test_missing_management_yaml_returns_empty(self):
        """No config available → no constraints injected, no exception."""
        # Don't write anything.
        out = intent_constraints_block(teaparty_home=self._tp)
        self.assertEqual(out, '')


if __name__ == '__main__':
    unittest.main()
