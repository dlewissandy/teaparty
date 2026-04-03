#!/usr/bin/env python3
"""Tests for Issue #257: Norms system — advisory natural-language statements.

Covers:
 1. ManagementTeam has norms field, loaded from YAML
 2. apply_norms_precedence: project categories replace workgroup categories on conflict
 3. apply_norms_precedence: three-level chain (org → workgroup → project)
 4. apply_norms_precedence: empty inputs handled gracefully
 5. format_norms: renders norms as readable text for prompt injection
 6. resolve_norms: end-to-end three-level resolution + formatting
 7. Norms remain distinct from budget (budget not in norms)
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config_reader import (
    ManagementTeam,
    load_management_team,
    load_project_team,
    load_workgroup,
    apply_norms_precedence,
    format_norms,
    resolve_norms,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_teaparty_home(teaparty_yaml: str) -> str:
    home = tempfile.mkdtemp()
    mgmt_dir = os.path.join(home, '.teaparty', 'management')
    os.makedirs(mgmt_dir)
    with open(os.path.join(mgmt_dir, 'teaparty.yaml'), 'w') as f:
        f.write(teaparty_yaml)
    return home


def _make_yaml_file(content: str) -> str:
    d = tempfile.mkdtemp()
    path = os.path.join(d, 'config.yaml')
    with open(path, 'w') as f:
        f.write(content)
    return path


# ── 1. ManagementTeam norms field ─────────────────────────────────────────────

class TestManagementTeamNorms(unittest.TestCase):
    """ManagementTeam has norms field, loaded from YAML."""

    def test_norms_loaded(self):
        yaml_text = textwrap.dedent("""\
            name: Org
            lead: boss
            decider: boss
            norms:
              quality:
                - All projects must have CI
              communication:
                - Weekly status updates required
        """)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(team.norms['quality'], ['All projects must have CI'])
        self.assertEqual(team.norms['communication'], ['Weekly status updates required'])

    def test_norms_default_empty(self):
        yaml_text = textwrap.dedent("""\
            name: Org
            lead: boss
            decider: boss
        """)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(team.norms, {})


# ── 2. merge_norms precedence ─────────────────────────────────────────────────

class TestApplyNormsPrecedence(unittest.TestCase):
    """apply_norms_precedence: higher-precedence categories replace lower."""

    def test_project_replaces_conflicting_category(self):
        """Per design doc: 'This is not a merge.' Project quality replaces workgroup quality."""
        workgroup = {
            'quality': ['Code review required before merge', 'Test coverage must not decrease'],
            'tools': ['Developers may not use WebSearch'],
        }
        project = {
            'quality': ['All code changes must have integration tests'],
        }
        result = apply_norms_precedence(workgroup, project)
        self.assertEqual(result['quality'], ['All code changes must have integration tests'])
        self.assertEqual(result['tools'], ['Developers may not use WebSearch'])

    def test_non_conflicting_categories_preserved(self):
        workgroup = {'delegation': ['Architect plans, Developer implements']}
        project = {'quality': ['Tests required']}
        result = apply_norms_precedence(workgroup, project)
        self.assertIn('delegation', result)
        self.assertIn('quality', result)

    def test_three_level_chain(self):
        """Org → workgroup → project: each level overrides the previous."""
        org = {
            'communication': ['Weekly status updates'],
            'quality': ['CI required'],
        }
        workgroup = {
            'quality': ['Code review required'],
            'tools': ['No WebSearch'],
        }
        project = {
            'quality': ['Integration tests required'],
        }
        result = apply_norms_precedence(org, workgroup, project)
        # Project wins quality
        self.assertEqual(result['quality'], ['Integration tests required'])
        # Workgroup wins tools (project didn't override)
        self.assertEqual(result['tools'], ['No WebSearch'])
        # Org communication preserved (nobody overrode)
        self.assertEqual(result['communication'], ['Weekly status updates'])

    def test_empty_inputs(self):
        self.assertEqual(apply_norms_precedence({}, {}, {}), {})

    def test_single_level(self):
        norms = {'quality': ['Tests required']}
        self.assertEqual(apply_norms_precedence(norms), norms)

    def test_no_levels(self):
        self.assertEqual(apply_norms_precedence(), {})


# ── 3. format_norms ──────────────────────────────────────────────────────────

class TestFormatNorms(unittest.TestCase):
    """format_norms renders norms as readable text for prompt injection."""

    def test_single_category(self):
        norms = {'quality': ['All code changes must have tests']}
        text = format_norms(norms)
        self.assertIn('quality', text.lower())
        self.assertIn('All code changes must have tests', text)

    def test_multiple_categories(self):
        norms = {
            'quality': ['Tests required', 'Reviews required'],
            'delegation': ['Architect plans'],
        }
        text = format_norms(norms)
        self.assertIn('quality', text.lower())
        self.assertIn('delegation', text.lower())
        self.assertIn('Tests required', text)
        self.assertIn('Architect plans', text)

    def test_empty_norms(self):
        text = format_norms({})
        self.assertEqual(text, '')

    def test_output_is_natural_language(self):
        """Output should be readable prose, not YAML or JSON."""
        norms = {'quality': ['All changes need tests']}
        text = format_norms(norms)
        self.assertNotIn('{', text)
        self.assertNotIn('[', text)


# ── 4. resolve_norms end-to-end ───────────────────────────────────────────────

class TestResolveNorms(unittest.TestCase):
    """resolve_norms: three-level resolution + formatting in one call."""

    def test_three_level_resolution(self):
        org = {'communication': ['Weekly updates']}
        workgroup = {'quality': ['Code review required']}
        project = {'quality': ['Integration tests required']}
        text = resolve_norms(org_norms=org, workgroup_norms=workgroup, project_norms=project)
        self.assertIn('Integration tests required', text)
        self.assertIn('Weekly updates', text)
        # Workgroup quality was overridden, should not appear
        self.assertNotIn('Code review required', text)

    def test_none_inputs(self):
        text = resolve_norms()
        self.assertEqual(text, '')

    def test_partial_levels(self):
        text = resolve_norms(project_norms={'quality': ['Tests required']})
        self.assertIn('Tests required', text)


# ── 5. Norms distinct from budget ────────────────────────────────────────────

class TestNormsBudgetSeparation(unittest.TestCase):
    """Budget keys do not appear in norms; norms do not appear in budget."""

    def test_budget_not_in_norms(self):
        yaml_text = textwrap.dedent("""\
            name: My Backend
            lead: lead
            decider: darrell
            norms:
              quality:
                - Tests required
            budget:
              job_limit_usd: 5.00
        """)
        d = tempfile.mkdtemp()
        tp_project = os.path.join(d, '.teaparty', 'project')
        os.makedirs(tp_project)
        os.makedirs(os.path.join(d, '.git'))
        with open(os.path.join(tp_project, 'project.yaml'), 'w') as f:
            f.write(yaml_text)
        team = load_project_team(d)
        self.assertNotIn('budget', team.norms)
        self.assertNotIn('job_limit_usd', team.norms)


# ── 6. Integration: norms reach session prompt ───────────────────────────────

class TestNormsReachSession(unittest.TestCase):
    """Norms from YAML flow into the session's task prompt."""

    def test_resolve_norms_static_with_project_yaml(self):
        """Session._resolve_norms_static reads .teaparty/project/project.yaml norms."""
        from orchestrator.session import Session

        yaml_text = textwrap.dedent("""\
            name: Test Project
            lead: lead
            decider: darrell
            norms:
              quality:
                - All changes need integration tests
              delegation:
                - Architect plans, Developer implements
        """)
        d = tempfile.mkdtemp()
        tp_project = os.path.join(d, '.teaparty', 'project')
        os.makedirs(tp_project)
        os.makedirs(os.path.join(d, '.git'))
        with open(os.path.join(tp_project, 'project.yaml'), 'w') as f:
            f.write(yaml_text)

        result = Session._resolve_norms_static(d)
        self.assertIn('All changes need integration tests', result)
        self.assertIn('Architect plans, Developer implements', result)
        self.assertIn('Norms (advisory)', result)

    def test_resolve_norms_static_no_config(self):
        """When no .teaparty/ exists, returns empty string."""
        from orchestrator.session import Session

        d = tempfile.mkdtemp()
        result = Session._resolve_norms_static(d)
        self.assertEqual(result, '')

    def test_resolve_norms_static_includes_workgroup_norms(self):
        """Workgroup norms appear as the middle level of the precedence chain."""
        from orchestrator.session import Session

        project_yaml = textwrap.dedent("""\
            name: Test Project
            lead: lead
            decider: darrell
            workgroups:
              - name: coding
                config: workgroups/coding.yaml
            norms:
              quality:
                - Integration tests required
        """)
        workgroup_yaml = textwrap.dedent("""\
            name: coding
            description: Coding workgroup
            norms:
              tools:
                - No WebSearch
              quality:
                - Code review required
        """)
        d = tempfile.mkdtemp()
        tp_project = os.path.join(d, '.teaparty', 'project')
        os.makedirs(tp_project)
        os.makedirs(os.path.join(d, '.git'))
        wg_dir = os.path.join(tp_project, 'workgroups')
        os.makedirs(wg_dir)
        with open(os.path.join(tp_project, 'project.yaml'), 'w') as f:
            f.write(project_yaml)
        with open(os.path.join(wg_dir, 'coding.yaml'), 'w') as f:
            f.write(workgroup_yaml)

        result = Session._resolve_norms_static(d)
        # Workgroup tools norm should appear (not overridden by project)
        self.assertIn('No WebSearch', result)
        # Project quality wins over workgroup quality
        self.assertIn('Integration tests required', result)
        self.assertNotIn('Code review required', result)

    def test_resolve_norms_static_workgroup_norms_overridden_by_project(self):
        """Project norms override workgroup norms on the same category."""
        from orchestrator.session import Session

        project_yaml = textwrap.dedent("""\
            name: Test Project
            lead: lead
            decider: darrell
            workgroups:
              - name: coding
                config: workgroups/coding.yaml
            norms:
              delegation:
                - Project lead decides
        """)
        workgroup_yaml = textwrap.dedent("""\
            name: coding
            description: Coding workgroup
            norms:
              delegation:
                - Architect decides
              tools:
                - Developers may not use WebSearch
        """)
        d = tempfile.mkdtemp()
        tp_project = os.path.join(d, '.teaparty', 'project')
        os.makedirs(tp_project)
        os.makedirs(os.path.join(d, '.git'))
        wg_dir = os.path.join(tp_project, 'workgroups')
        os.makedirs(wg_dir)
        with open(os.path.join(tp_project, 'project.yaml'), 'w') as f:
            f.write(project_yaml)
        with open(os.path.join(wg_dir, 'coding.yaml'), 'w') as f:
            f.write(workgroup_yaml)

        result = Session._resolve_norms_static(d)
        # Project wins delegation
        self.assertIn('Project lead decides', result)
        self.assertNotIn('Architect decides', result)
        # Workgroup tools preserved
        self.assertIn('Developers may not use WebSearch', result)


if __name__ == '__main__':
    unittest.main()
