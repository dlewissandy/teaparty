#!/usr/bin/env python3
"""Tests for issue #88: Wire detect_stage.py into post-intent-approval path.

Covers:
 1. After intent approval (INTENT_ASSERT → approve), detect_stage_from_content()
    is called with the INTENT.md content.
 2. The detected stage is written to .current-stage in the infra dir.
 3. If a stage transition occurs (old != new, old != unknown),
    retire_stage_entries() is called on project memory files.
 4. If no INTENT.md exists, detection is skipped gracefully (no crash).
 5. If detect_stage returns 'unknown', no retirement is triggered.
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.engine import Orchestrator
from projects.POC.orchestrator.events import EventBus
from projects.POC.scripts.cfa_state import make_initial_state, transition, save_state


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_orchestrator(tmpdir: str, cfa_state=None) -> Orchestrator:
    """Create a minimal Orchestrator for testing _transition()."""
    infra_dir = os.path.join(tmpdir, '.session')
    worktree = os.path.join(tmpdir, 'worktree')
    project_dir = os.path.join(tmpdir, 'project')
    os.makedirs(infra_dir, exist_ok=True)
    os.makedirs(worktree, exist_ok=True)
    os.makedirs(project_dir, exist_ok=True)

    if cfa_state is None:
        # Advance to INTENT_ASSERT (where human approves intent)
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')       # IDEA → PROPOSAL
        cfa = transition(cfa, 'assert')         # PROPOSAL → INTENT_ASSERT
    else:
        cfa = cfa_state

    config = MagicMock()
    bus = EventBus()

    orch = Orchestrator(
        cfa_state=cfa,
        phase_config=config,
        event_bus=bus,
        input_provider=AsyncMock(),
        infra_dir=infra_dir,
        project_workdir=project_dir,
        session_worktree=worktree,
        proxy_model_path=os.path.join(tmpdir, '.proxy.json'),
        project_slug='test-project',
        poc_root=tmpdir,
        task='test task',
        session_id='20260314-160000',
    )
    return orch


def _make_intent(worktree: str, content: str = '# INTENT: Test\n\nBuild a thing.\n') -> str:
    path = os.path.join(worktree, 'INTENT.md')
    with open(path, 'w') as f:
        f.write(content)
    return path


def _make_actor_result():
    from projects.POC.orchestrator.actors import ActorResult
    return ActorResult(action='approve', data={})


# ── Tests ────────────────────────────────────────────────────────────────────

class TestStageDetectionOnIntentApproval(unittest.TestCase):
    """detect_stage_from_content() must be called when intent is approved."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_detect_stage_called_after_intent_approval(self):
        """After INTENT_ASSERT → approve, detect_stage_from_content is called
        with the INTENT.md content."""
        orch = _make_orchestrator(self.tmpdir)
        _make_intent(orch.session_worktree)

        with patch('projects.POC.orchestrator.engine.detect_stage_from_content',
                   return_value='implementation') as mock_detect:
            _run(orch._transition('approve', _make_actor_result()))

            mock_detect.assert_called_once()
            # First arg should be the INTENT.md content
            call_content = mock_detect.call_args[0][0]
            self.assertIn('INTENT', call_content)

    def test_stage_written_to_file(self):
        """The detected stage is written to .current-stage in infra_dir."""
        orch = _make_orchestrator(self.tmpdir)
        _make_intent(orch.session_worktree)

        with patch('projects.POC.orchestrator.engine.detect_stage_from_content',
                   return_value='implementation'):
            _run(orch._transition('approve', _make_actor_result()))

        stage_file = os.path.join(orch.infra_dir, '.current-stage')
        self.assertTrue(os.path.exists(stage_file), '.current-stage should be created')
        self.assertEqual(Path(stage_file).read_text().strip(), 'implementation')

    def test_stage_transition_triggers_retirement(self):
        """When stage changes from old to new (not unknown), retire_stage_entries
        is called on project memory files."""
        orch = _make_orchestrator(self.tmpdir)
        _make_intent(orch.session_worktree)

        # Set up an old stage
        stage_file = os.path.join(orch.infra_dir, '.current-stage')
        Path(stage_file).write_text('specification\n')

        with patch('projects.POC.orchestrator.engine.detect_stage_from_content',
                   return_value='implementation'), \
             patch('projects.POC.orchestrator.engine.retire_stage_entries',
                   return_value=([], 0)) as mock_retire:
            _run(orch._transition('approve', _make_actor_result()))

            mock_retire.assert_called_once()
            # First arg is entries list, second is old stage
            self.assertEqual(mock_retire.call_args[0][1], 'specification')

    def test_no_intent_skips_detection(self):
        """If INTENT.md doesn't exist, stage detection is skipped (no crash)."""
        orch = _make_orchestrator(self.tmpdir)
        # No INTENT.md created

        with patch('projects.POC.orchestrator.engine.detect_stage_from_content') as mock_detect:
            _run(orch._transition('approve', _make_actor_result()))
            mock_detect.assert_not_called()

    def test_unknown_stage_no_retirement(self):
        """If detect_stage returns 'unknown', no retirement is triggered."""
        orch = _make_orchestrator(self.tmpdir)
        _make_intent(orch.session_worktree)

        # Set old stage
        stage_file = os.path.join(orch.infra_dir, '.current-stage')
        Path(stage_file).write_text('specification\n')

        with patch('projects.POC.orchestrator.engine.detect_stage_from_content',
                   return_value='unknown'), \
             patch('projects.POC.orchestrator.engine.retire_stage_entries') as mock_retire:
            _run(orch._transition('approve', _make_actor_result()))
            mock_retire.assert_not_called()

    def test_non_intent_approval_skips_detection(self):
        """Stage detection only fires on INTENT_ASSERT → approve,
        not on other approval transitions (like PLAN_ASSERT)."""
        # Start at PLAN_ASSERT instead
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')       # → PROPOSAL
        cfa = transition(cfa, 'auto-approve')   # → INTENT
        cfa = transition(cfa, 'plan')           # → DRAFT
        cfa = transition(cfa, 'assert')         # → PLAN_ASSERT

        orch = _make_orchestrator(self.tmpdir, cfa_state=cfa)
        _make_intent(orch.session_worktree)

        with patch('projects.POC.orchestrator.engine.detect_stage_from_content') as mock_detect:
            _run(orch._transition('approve', _make_actor_result()))
            mock_detect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
