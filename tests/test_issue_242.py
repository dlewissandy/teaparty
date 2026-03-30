#!/usr/bin/env python3
"""Tests for Issue #242: Configuration Team proposal validation theory.

The proposal must define what validation means for each artifact type,
distinguishing structural, behavioral, and semantic checks. It must
acknowledge that full semantic validation of LLM-facing artifacts is
an open research problem.

Covers:
 1. Proposal contains a Validation section
 2. Validation section defines three check levels: structural, behavioral, semantic
 3. Each artifact type (agents, skills, hooks, MCP servers, scheduled tasks) has validation coverage
 4. Semantic validation is acknowledged as an open research problem
 5. Behavioral checks are distinguished from semantic checks (the boundary is explicit)
"""
import re
import unittest
from pathlib import Path


PROPOSAL_PATH = (
    Path(__file__).parent.parent
    / 'docs' / 'proposals' / 'configuration-team' / 'proposal.md'
)


def _read_proposal() -> str:
    return PROPOSAL_PATH.read_text()


def _extract_section(text: str, heading: str) -> str | None:
    """Extract content under a markdown heading (## level) until the next same-level heading."""
    pattern = rf'^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)'
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else None


class TestValidationSectionExists(unittest.TestCase):
    """The proposal must contain a dedicated Validation section."""

    def test_proposal_has_validation_section(self):
        """A ## Validation heading exists in the proposal."""
        text = _read_proposal()
        section = _extract_section(text, 'Validation')
        self.assertIsNotNone(section, 'Proposal must have a ## Validation section')
        self.assertGreater(len(section), 200,
                           'Validation section must be substantive, not a stub')


class TestThreeCheckLevels(unittest.TestCase):
    """The validation section must distinguish structural, behavioral, and semantic checks."""

    def setUp(self):
        text = _read_proposal()
        self.section = _extract_section(text, 'Validation')
        if self.section is None:
            self.skipTest('No Validation section found — prerequisite test fails')

    def test_structural_checks_defined(self):
        """Structural checks (parseable, references resolve) are defined."""
        self.assertRegex(self.section.lower(), r'structural',
                         'Validation section must define structural checks')

    def test_behavioral_checks_defined(self):
        """Behavioral checks (artifact completes representative tasks) are defined."""
        self.assertRegex(self.section.lower(), r'behavioral',
                         'Validation section must define behavioral checks')

    def test_semantic_checks_defined(self):
        """Semantic checks (human review, intent alignment) are defined."""
        self.assertRegex(self.section.lower(), r'semantic',
                         'Validation section must define semantic checks')


class TestArtifactTypeCoverage(unittest.TestCase):
    """Each artifact type must appear in the validation section."""

    ARTIFACT_TYPES = ['agent', 'skill', 'hook', 'mcp', 'scheduled']

    def setUp(self):
        text = _read_proposal()
        self.section = _extract_section(text, 'Validation')
        if self.section is None:
            self.skipTest('No Validation section found — prerequisite test fails')

    def test_each_artifact_type_has_validation_coverage(self):
        """Agents, skills, and hooks are all addressed in the validation section."""
        lower = self.section.lower()
        for artifact in self.ARTIFACT_TYPES:
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, lower,
                              f'Validation section must address {artifact} validation')


class TestSemanticValidationAcknowledgment(unittest.TestCase):
    """The proposal must acknowledge semantic validation as an open research problem."""

    def setUp(self):
        text = _read_proposal()
        self.section = _extract_section(text, 'Validation')
        if self.section is None:
            self.skipTest('No Validation section found — prerequisite test fails')

    def test_open_research_problem_acknowledged(self):
        """Semantic validation is framed as an open problem, not a gap to fill."""
        lower = self.section.lower()
        has_open = 'open' in lower
        has_research = 'research' in lower or 'unsolved' in lower or 'beyond automation' in lower
        self.assertTrue(has_open and has_research,
                        'Section must acknowledge semantic validation as an open research problem')


class TestBehavioralSemanticBoundary(unittest.TestCase):
    """The boundary between behavioral and semantic checks must be explicit."""

    def setUp(self):
        text = _read_proposal()
        self.section = _extract_section(text, 'Validation')
        if self.section is None:
            self.skipTest('No Validation section found — prerequisite test fails')

    def test_boundary_is_explicit(self):
        """The section distinguishes where behavioral checks end and human judgment begins."""
        lower = self.section.lower()
        # Must mention human judgment/review in context of the boundary
        has_human_role = ('human' in lower and
                         ('review' in lower or 'judgment' in lower or 'judgement' in lower))
        self.assertTrue(has_human_role,
                        'Section must explicitly state where behavioral checks end '
                        'and human judgment begins')


if __name__ == '__main__':
    unittest.main()
