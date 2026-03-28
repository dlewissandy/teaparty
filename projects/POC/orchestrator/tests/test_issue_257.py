#!/usr/bin/env python3
"""Tests for Issue #257: Norms system — advisory natural-language statements.

Covers:
 1. ManagementTeam has norms field, loaded from YAML
 2. merge_norms: project categories replace workgroup categories on conflict
 3. merge_norms: non-conflicting categories preserved from both levels
 4. merge_norms: empty inputs handled gracefully
 5. format_norms: renders merged norms as readable text for prompt injection
 6. Norms remain distinct from budget (budget not in norms)
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.config_reader import (
    ManagementTeam,
    load_management_team,
    load_project_team,
    load_workgroup,
    merge_norms,
    format_norms,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_teaparty_home(teaparty_yaml: str) -> str:
    home = tempfile.mkdtemp()
    tp_dir = os.path.join(home, '.teaparty')
    os.makedirs(tp_dir)
    with open(os.path.join(tp_dir, 'teaparty.yaml'), 'w') as f:
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

class TestMergeNorms(unittest.TestCase):
    """merge_norms: project categories replace workgroup categories."""

    def test_project_replaces_conflicting_category(self):
        """Per design doc: 'This is not a merge.' Project quality replaces workgroup quality."""
        workgroup = {
            'quality': ['Code review required before merge', 'Test coverage must not decrease'],
            'tools': ['Developers may not use WebSearch'],
        }
        project = {
            'quality': ['All code changes must have integration tests'],
        }
        merged = merge_norms(workgroup, project)
        # Project quality fully replaces workgroup quality
        self.assertEqual(merged['quality'], ['All code changes must have integration tests'])
        # Non-conflicting workgroup category preserved
        self.assertEqual(merged['tools'], ['Developers may not use WebSearch'])

    def test_non_conflicting_categories_preserved(self):
        workgroup = {'delegation': ['Architect plans, Developer implements']}
        project = {'quality': ['Tests required']}
        merged = merge_norms(workgroup, project)
        self.assertIn('delegation', merged)
        self.assertIn('quality', merged)

    def test_empty_workgroup_norms(self):
        merged = merge_norms({}, {'quality': ['Tests required']})
        self.assertEqual(merged, {'quality': ['Tests required']})

    def test_empty_project_norms(self):
        workgroup = {'quality': ['Code review required']}
        merged = merge_norms(workgroup, {})
        self.assertEqual(merged, {'quality': ['Code review required']})

    def test_both_empty(self):
        merged = merge_norms({}, {})
        self.assertEqual(merged, {})


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


# ── 4. Norms distinct from budget ────────────────────────────────────────────

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
        tp_dir = os.path.join(d, '.teaparty')
        os.makedirs(tp_dir)
        os.makedirs(os.path.join(d, '.git'))
        os.makedirs(os.path.join(d, '.claude'))
        with open(os.path.join(tp_dir, 'project.yaml'), 'w') as f:
            f.write(yaml_text)
        team = load_project_team(d)
        self.assertNotIn('budget', team.norms)
        self.assertNotIn('job_limit_usd', team.norms)


if __name__ == '__main__':
    unittest.main()
