#!/usr/bin/env python3
"""Tests for issue #102: Reframe approval gate bridge prompts as alignment validation.

Bridge prompts at each gate should ask the proxy/human to validate alignment,
not just acknowledge the artifact.  Context injection should provide the
upstream artifacts so the reviewer can compare.

Covers:
  1. generate_review_bridge templates use alignment-validation framing
  2. PLAN_ASSERT bridge receives INTENT.md context
  3. WORK_ASSERT bridge receives INTENT.md + PLAN.md context
  4. INTENT_ASSERT bridge receives original task prompt context
  5. Fallback bridge text reflects alignment framing
  6. Context injection degrades gracefully when files are missing
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.scripts.generate_review_bridge import (
    STATE_CONFIG,
    TEMPLATES,
    fallback_bridge,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_tmpdir():
    return tempfile.mkdtemp()


# ── Template alignment framing ──────────────────────────────────────────────

class TestBridgeTemplatesAlignmentFraming(unittest.TestCase):
    """Bridge prompt templates must ask alignment validation questions,
    not agent-perspective summaries like 'I've drafted...'."""

    def test_intent_assert_template_asks_alignment_question(self):
        """INTENT_ASSERT template must ask whether the intent document
        faithfully represents the human's idea."""
        config = STATE_CONFIG['INTENT_ASSERT']
        template = TEMPLATES[config['template']]
        # Must ask the human to validate alignment, not summarize what agent did
        self.assertIn('recognize', template.lower(),
                      "INTENT_ASSERT template should ask human to 'recognize' their idea")
        self.assertNotIn("I've drafted", template,
                         "INTENT_ASSERT template should not use agent-perspective framing")

    def test_plan_assert_template_asks_alignment_question(self):
        """PLAN_ASSERT template must ask whether the plan operationalizes
        the intent well."""
        config = STATE_CONFIG['PLAN_ASSERT']
        template = TEMPLATES[config['template']]
        self.assertIn('recognize', template.lower(),
                      "PLAN_ASSERT template should ask human to 'recognize' the plan")
        self.assertNotIn("I've drafted", template,
                         "PLAN_ASSERT template should not use agent-perspective framing")

    def test_work_assert_template_asks_alignment_question(self):
        """WORK_ASSERT template must ask whether the deliverables faithfully
        implement the human's idea."""
        config = STATE_CONFIG['WORK_ASSERT']
        template = TEMPLATES[config['template']]
        self.assertIn('recognize', template.lower(),
                      "WORK_ASSERT template should ask human to 'recognize' deliverables")
        self.assertNotIn("I worked on", template,
                         "WORK_ASSERT template should not use agent-perspective framing")


# ── Context injection in generate_review_bridge ─────────────────────────────

class TestBridgeContextInjection(unittest.TestCase):
    """Bridge prompt templates must include upstream context so the reviewer
    can compare the artifact against its source of truth."""

    def test_plan_assert_template_includes_intent_context_slot(self):
        """PLAN_ASSERT template must have a slot for INTENT.md content
        so the reviewer can compare plan against intent."""
        config = STATE_CONFIG['PLAN_ASSERT']
        template = TEMPLATES[config['template']]
        self.assertIn('{intent_context}', template,
                      "PLAN_ASSERT template must include {intent_context} slot")

    def test_work_assert_template_includes_intent_context_slot(self):
        """WORK_ASSERT template must have a slot for INTENT.md content."""
        config = STATE_CONFIG['WORK_ASSERT']
        template = TEMPLATES[config['template']]
        self.assertIn('{intent_context}', template,
                      "WORK_ASSERT template must include {intent_context} slot")

    def test_work_assert_template_includes_plan_context_slot(self):
        """WORK_ASSERT template must have a slot for PLAN.md content."""
        config = STATE_CONFIG['WORK_ASSERT']
        template = TEMPLATES[config['template']]
        self.assertIn('{plan_context}', template,
                      "WORK_ASSERT template must include {plan_context} slot")


# ── Context injection in ApprovalGate._generate_bridge ──────────────────────

class TestApprovalGateBridgeContextInjection(unittest.TestCase):
    """ApprovalGate._generate_bridge must pass upstream context to the
    bridge generator so the reviewer can compare artifacts."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        os.makedirs(self.worktree)
        os.makedirs(self.infra_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_gate(self):
        from unittest.mock import AsyncMock
        from projects.POC.orchestrator.actors import ApprovalGate
        return ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=AsyncMock(),
            poc_root=self.tmpdir,
        )

    def test_plan_assert_bridge_passes_intent_context(self):
        """At PLAN_ASSERT, _generate_bridge must pass INTENT.md content
        to generate_review_bridge.generate()."""
        gate = self._make_gate()
        # Write INTENT.md and PLAN.md
        Path(os.path.join(self.worktree, 'INTENT.md')).write_text(
            '# Intent\nBuild a widget factory.'
        )
        artifact_path = os.path.join(self.worktree, 'PLAN.md')
        Path(artifact_path).write_text('# Plan\nStep 1: Build widgets.')

        with patch('projects.POC.scripts.generate_review_bridge.generate') as mock_gen:
            mock_gen.return_value = 'bridge text'
            gate._generate_bridge(
                artifact_path, 'PLAN_ASSERT', 'Build widgets',
                session_worktree=self.worktree,
                infra_dir=self.infra_dir,
            )
            # The generate function must receive intent_context
            call_kwargs = mock_gen.call_args
            # Check that intent context was passed (either as kwarg or positional)
            all_args = list(call_kwargs.args) + list(call_kwargs.kwargs.values())
            intent_found = any('widget factory' in str(a).lower() for a in all_args)
            self.assertTrue(intent_found,
                            "PLAN_ASSERT bridge must pass INTENT.md content to generate()")

    def test_work_assert_bridge_passes_intent_and_plan_context(self):
        """At WORK_ASSERT, _generate_bridge must pass both INTENT.md and
        PLAN.md content to generate_review_bridge.generate()."""
        gate = self._make_gate()
        Path(os.path.join(self.worktree, 'INTENT.md')).write_text(
            '# Intent\nBuild a widget factory.'
        )
        Path(os.path.join(self.worktree, 'PLAN.md')).write_text(
            '# Plan\nStep 1: Build widgets.'
        )
        artifact_path = os.path.join(self.worktree, '.work-summary.md')
        Path(artifact_path).write_text('# Work Summary\nWidgets built.')

        with patch('projects.POC.scripts.generate_review_bridge.generate') as mock_gen:
            mock_gen.return_value = 'bridge text'
            gate._generate_bridge(
                artifact_path, 'WORK_ASSERT', 'Build widgets',
                session_worktree=self.worktree,
                infra_dir=self.infra_dir,
            )
            call_kwargs = mock_gen.call_args
            all_args = list(call_kwargs.args) + list(call_kwargs.kwargs.values())
            all_text = ' '.join(str(a) for a in all_args).lower()
            self.assertIn('widget factory', all_text,
                          "WORK_ASSERT bridge must pass INTENT.md content")
            self.assertIn('build widgets', all_text,
                          "WORK_ASSERT bridge must pass PLAN.md content")

    def test_bridge_degrades_when_context_files_missing(self):
        """When upstream context files don't exist, _generate_bridge must
        still produce output without crashing."""
        gate = self._make_gate()
        artifact_path = os.path.join(self.worktree, 'PLAN.md')
        Path(artifact_path).write_text('# Plan\nDo stuff.')

        with patch('projects.POC.scripts.generate_review_bridge.generate',
                   return_value='bridge text') as mock_gen:
            # Should not raise even though INTENT.md doesn't exist
            text = gate._generate_bridge(
                artifact_path, 'PLAN_ASSERT', 'task',
                session_worktree=self.worktree,
                infra_dir=self.infra_dir,
            )
            self.assertTrue(text)  # Some output produced


# ── Fallback bridge alignment framing ───────────────────────────────────────

class TestFallbackBridgeAlignmentFraming(unittest.TestCase):
    """fallback_bridge must reflect alignment framing, not agent-perspective."""

    def test_intent_assert_fallback_mentions_alignment(self):
        text = fallback_bridge('/tmp/INTENT.md', 'INTENT_ASSERT')
        # Should reference alignment validation, not just "review document"
        lower = text.lower()
        self.assertTrue(
            'recognize' in lower or 'alignment' in lower or 'intent' in lower,
            f"INTENT_ASSERT fallback should reference alignment: {text}"
        )

    def test_plan_assert_fallback_mentions_alignment(self):
        text = fallback_bridge('/tmp/PLAN.md', 'PLAN_ASSERT')
        lower = text.lower()
        self.assertTrue(
            'recognize' in lower or 'alignment' in lower or 'plan' in lower,
            f"PLAN_ASSERT fallback should reference alignment: {text}"
        )

    def test_work_assert_fallback_mentions_alignment(self):
        text = fallback_bridge('/tmp/work-summary.md', 'WORK_ASSERT')
        lower = text.lower()
        self.assertTrue(
            'recognize' in lower or 'alignment' in lower or 'deliverables' in lower,
            f"WORK_ASSERT fallback should reference alignment: {text}"
        )


if __name__ == '__main__':
    unittest.main()
