#!/usr/bin/env python3
"""Tests for Issue #243: Configuration Team partial-failure handling for multi-artifact creation.

Spec requirements tested (from issue #243):

  Dependency classification:
   1. Proposal defines artifact dependency categories (hard vs soft)
   2. Hard dependencies are explicitly listed with rationale
   3. Soft dependencies are explicitly listed with rationale

  Failure handling strategy:
   4. Proposal defines Configuration Lead behavior on specialist failure
   5. Failure handling covers the case where prior specialists succeeded
   6. The strategy addresses reporting — no silent partial success

  Request flow integration:
   7. "Create a new workgroup" flow in request-flows.md includes failure handling
   8. Flow specifies what happens when a step fails after prior steps succeeded
"""
import os
import sys
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_proposal():
    """Read the configuration-team proposal."""
    path = Path(__file__).parent.parent / \
        'docs' / 'proposals' / 'configuration-team' / 'proposal.md'
    return path.read_text()


def _read_request_flows():
    """Read the request-flows reference doc."""
    path = Path(__file__).parent.parent / \
        'docs' / 'proposals' / 'configuration-team' / 'references' / 'request-flows.md'
    return path.read_text()


# ── Tests ────────────────────────────────────────────────────────────────────

class TestDependencyClassification(unittest.TestCase):
    """Proposal must classify cross-artifact dependencies."""

    def test_proposal_defines_dependency_categories(self):
        """Requirement 1: Proposal defines hard vs soft dependency categories."""
        text = _read_proposal().lower()
        self.assertIn('hard', text)
        self.assertIn('soft', text)
        # Must have a section discussing partial failure or dependencies
        self.assertTrue(
            'partial' in text or 'dependenc' in text or 'failure' in text,
            "Proposal must discuss partial failure or artifact dependencies"
        )

    def test_hard_dependencies_listed(self):
        """Requirement 2: Hard dependencies explicitly listed."""
        text = _read_proposal()
        # Must identify which artifact pairs cannot exist without each other
        self.assertTrue(
            'hard' in text.lower() and ('agent' in text.lower() or 'skill' in text.lower()),
            "Proposal must list hard dependencies between specific artifact types"
        )

    def test_soft_dependencies_listed(self):
        """Requirement 3: Soft dependencies explicitly listed."""
        text = _read_proposal()
        self.assertTrue(
            'soft' in text.lower() and ('independen' in text.lower() or 'optional' in text.lower() or 'later' in text.lower()),
            "Proposal must describe soft dependencies as independently viable"
        )


class TestFailureHandlingStrategy(unittest.TestCase):
    """Proposal must define Configuration Lead behavior on failure."""

    def test_configuration_lead_failure_behavior(self):
        """Requirement 4: Proposal defines what the Lead does on specialist failure."""
        text = _read_proposal().lower()
        # Must mention Configuration Lead in context of failure
        self.assertTrue(
            'configuration lead' in text and 'fail' in text,
            "Proposal must describe Configuration Lead's response to specialist failure"
        )

    def test_prior_success_handling(self):
        """Requirement 5: Strategy covers case where prior specialists already succeeded."""
        text = _read_proposal().lower()
        self.assertTrue(
            ('succeed' in text or 'already created' in text or 'prior' in text)
            and 'fail' in text,
            "Proposal must address what happens to artifacts from prior successful specialists"
        )

    def test_no_silent_partial_success(self):
        """Requirement 6: Strategy ensures explicit reporting, no silent partial success."""
        text = _read_proposal().lower()
        self.assertTrue(
            'report' in text and ('partial' in text or 'fail' in text),
            "Proposal must require explicit reporting of partial results"
        )


class TestRequestFlowIntegration(unittest.TestCase):
    """The 'create a new workgroup' flow must reflect failure handling."""

    def test_workgroup_flow_includes_failure_handling(self):
        """Requirement 7: Workgroup flow includes failure handling."""
        text = _read_request_flows().lower()
        # The workgroup section must mention failure
        workgroup_section = text.split('create a new workgroup')[1] if 'create a new workgroup' in text else ''
        # Trim to just the workgroup section (before next major heading)
        if '## ' in workgroup_section:
            workgroup_section = workgroup_section[:workgroup_section.index('## ')]
        self.assertTrue(
            'fail' in workgroup_section or 'partial' in workgroup_section,
            "Workgroup creation flow must address failure scenarios"
        )

    def test_workgroup_flow_addresses_mid_sequence_failure(self):
        """Requirement 8: Flow specifies what happens when step N fails after step N-1 succeeded."""
        text = _read_request_flows().lower()
        workgroup_section = text.split('create a new workgroup')[1] if 'create a new workgroup' in text else ''
        if '## ' in workgroup_section:
            workgroup_section = workgroup_section[:workgroup_section.index('## ')]
        self.assertTrue(
            ('succeed' in workgroup_section or 'already' in workgroup_section or 'prior' in workgroup_section)
            and 'fail' in workgroup_section,
            "Workgroup flow must describe mid-sequence failure behavior"
        )


if __name__ == '__main__':
    unittest.main()
