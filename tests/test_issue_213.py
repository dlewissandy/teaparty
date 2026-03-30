"""Tests for Issue #213: approval-gate.md must match actual proxy flow.

The doc described a should_escalate() pre-filter step that gates whether
the proxy agent runs.  The actual code (proxy_agent.py:consult_proxy)
always invokes the proxy agent, then calibrates confidence post-hoc.
The doc also omitted ACT-R memory retrieval.

These tests verify:
1. The doc's described flow matches the code's actual structure.
2. should_escalate() is never called from the proxy invocation path.
3. ACT-R retrieval is documented.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]  # teaparty root
_DOC_PATH = _REPO / 'docs' / 'detailed-design' / 'approval-gate.md'
_PROXY_AGENT = _REPO / 'orchestrator' / 'proxy_agent.py'


class TestDocMatchesCode(unittest.TestCase):
    """The approval-gate doc must accurately describe consult_proxy()."""

    # -- Code-level invariants -----------------------------------------------

    def test_consult_proxy_does_not_reference_should_escalate(self):
        """consult_proxy() must not call should_escalate().

        The architectural decision (commit 8aa5ced) is that the proxy agent
        always runs; statistics calibrate post-hoc, never gate invocation.
        """
        source = _PROXY_AGENT.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'consult_proxy':
                body_source = ast.get_source_segment(source, node)
                self.assertNotIn(
                    'should_escalate',
                    body_source,
                    'consult_proxy() must not reference should_escalate — '
                    'the proxy agent always runs',
                )
                return
        self.fail('consult_proxy() not found in proxy_agent.py')

    def test_consult_proxy_retrieves_actr_before_agent(self):
        """consult_proxy() must call _retrieve_actr_memories before run_proxy_agent.

        The flow is: gather context (including ACT-R retrieval) -> invoke agent.
        """
        source = _PROXY_AGENT.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'consult_proxy':
                body_source = ast.get_source_segment(source, node)
                actr_pos = body_source.find('_retrieve_actr_memories')
                agent_pos = body_source.find('run_proxy_agent')
                self.assertGreater(
                    actr_pos, -1,
                    'consult_proxy must call _retrieve_actr_memories',
                )
                self.assertGreater(
                    agent_pos, -1,
                    'consult_proxy must call run_proxy_agent',
                )
                self.assertLess(
                    actr_pos, agent_pos,
                    '_retrieve_actr_memories must be called before run_proxy_agent',
                )
                return
        self.fail('consult_proxy() not found in proxy_agent.py')

    # -- Documentation accuracy ----------------------------------------------

    def test_doc_does_not_claim_should_escalate_pre_filters(self):
        """The doc must not describe should_escalate() as a pre-filter
        in the consult_proxy flow.

        The old doc (lines 51-69) described should_escalate() as step 4,
        gating whether the proxy agent runs.  This is wrong — the agent
        always runs.
        """
        doc = _DOC_PATH.read_text()
        # The numbered flow section describes consult_proxy's steps.
        # It should not contain should_escalate() as a step that gates
        # the proxy agent invocation.
        flow_section = _extract_section(doc, 'The Proxy Agent')
        self.assertIsNotNone(
            flow_section,
            'Doc must have a "The Proxy Agent" section',
        )
        self.assertNotIn(
            'should_escalate()',
            flow_section,
            'The Proxy Agent section must not describe should_escalate() '
            'as part of the consult_proxy flow — the agent always runs',
        )

    def test_doc_describes_actr_retrieval(self):
        """The doc must describe ACT-R memory retrieval in the proxy flow."""
        doc = _DOC_PATH.read_text()
        flow_section = _extract_section(doc, 'The Proxy Agent')
        self.assertIsNotNone(
            flow_section,
            'Doc must have a "The Proxy Agent" section',
        )
        self.assertRegex(
            flow_section,
            re.compile(r'ACT-R|actr|memory retrieval', re.IGNORECASE),
            'The Proxy Agent section must describe ACT-R memory retrieval',
        )

    def test_doc_describes_two_pass_prediction(self):
        """The doc must describe the two-pass prediction flow (prior/posterior)."""
        doc = _DOC_PATH.read_text()
        flow_section = _extract_section(doc, 'The Proxy Agent')
        self.assertIsNotNone(
            flow_section,
            'Doc must have a "The Proxy Agent" section',
        )
        self.assertRegex(
            flow_section,
            re.compile(r'two.pass|prior.*posterior|pass\s*1.*pass\s*2', re.IGNORECASE),
            'The Proxy Agent section must describe two-pass prediction',
        )

    def test_doc_describes_cold_start_gating_via_memory_depth(self):
        """The doc must describe cold-start gating based on ACT-R memory depth,
        not the old should_escalate() observation count."""
        doc = _DOC_PATH.read_text()
        self.assertRegex(
            doc,
            re.compile(r'memory.depth|MEMORY_DEPTH_THRESHOLD', re.IGNORECASE),
            'Doc must describe cold-start gating via ACT-R memory depth',
        )


def _extract_section(doc: str, heading: str) -> str | None:
    """Extract text from a markdown section by heading."""
    pattern = re.compile(
        rf'^##+ {re.escape(heading)}\s*$',
        re.MULTILINE,
    )
    match = pattern.search(doc)
    if not match:
        return None
    start = match.end()
    # Find next heading at same or higher level
    next_heading = re.search(r'^##+ ', doc[start:], re.MULTILINE)
    if next_heading:
        return doc[start:start + next_heading.start()]
    return doc[start:]


if __name__ == '__main__':
    unittest.main()
