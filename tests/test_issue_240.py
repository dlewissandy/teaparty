#!/usr/bin/env python3
"""Tests for Issue #240: Configuration Team execution model.

The Configuration Team writes runtime artifacts (.claude/, .teaparty/) that
must take effect in the session worktree, not in a child worktree that merges
back later. This requires a "direct" execution model distinct from the default
worktree-isolated model used by content-producing teams.

Covers:
 1. configuration team is registered in phase-config.json
 2. TeamSpec has execution_model field, defaulting to "worktree"
 3. configuration team has execution_model "direct"
 4. dispatch_cli skips worktree creation for direct-model teams
 5. dispatch_cli skips merge-back for direct-model teams
 6. dispatch_listener passes execution_model through to dispatch
 7. existing teams retain worktree execution_model (backward compat)
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator import find_poc_root
from orchestrator.phase_config import PhaseConfig, TeamSpec


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_phase_config():
    return PhaseConfig(find_poc_root())


# ── 1. Configuration team registered ─────────────────────────────────────────

class TestConfigurationTeamRegistered(unittest.TestCase):
    """The configuration team must appear in phase-config.json teams."""

    def test_configuration_team_in_org_catalogue(self):
        """phase-config.json includes a 'configuration' team entry."""
        config = _make_phase_config()
        self.assertIn('configuration', config.teams)

    def test_configuration_team_has_agent_file(self):
        """The configuration team spec references an agent file."""
        config = _make_phase_config()
        team = config.team('configuration')
        self.assertTrue(team.agent_file)

    def test_configuration_team_has_lead(self):
        """The configuration team spec names a team lead."""
        config = _make_phase_config()
        team = config.team('configuration')
        self.assertTrue(team.lead)


# ── 2. TeamSpec execution_model field ────────────────────────────────────────

class TestTeamSpecExecutionModel(unittest.TestCase):
    """TeamSpec has an execution_model field defaulting to 'worktree'."""

    def test_teamspec_has_execution_model_attr(self):
        """TeamSpec dataclass has an execution_model field."""
        spec = TeamSpec(name='test', agent_file='a.json', lead='lead')
        self.assertTrue(hasattr(spec, 'execution_model'))

    def test_default_execution_model_is_worktree(self):
        """TeamSpec.execution_model defaults to 'worktree'."""
        spec = TeamSpec(name='test', agent_file='a.json', lead='lead')
        self.assertEqual(spec.execution_model, 'worktree')


# ── 3. Configuration team uses direct model ──────────────────────────────────

class TestConfigurationTeamDirect(unittest.TestCase):
    """The configuration team's execution_model is 'direct'."""

    def test_configuration_execution_model_is_direct(self):
        """configuration team in phase-config.json has execution_model 'direct'."""
        config = _make_phase_config()
        team = config.team('configuration')
        self.assertEqual(team.execution_model, 'direct')


# ── 4. Dispatch skips worktree for direct model ─────────────────────────────

class TestDispatchSkipsWorktreeForDirect(unittest.TestCase):
    """dispatch() must not create a child worktree for direct-model teams."""

    def test_direct_model_does_not_call_create_dispatch_worktree(self):
        """When execution_model is 'direct', create_dispatch_worktree is not called."""
        from orchestrator.dispatch_cli import dispatch

        poc_root = find_poc_root()
        infra_dir = tempfile.mkdtemp()
        session_worktree = tempfile.mkdtemp()

        # Create minimal CfA state file
        cfa_state = {
            'state': 'EXECUTION',
            'phase': 'execution',
            'task_id': 'test',
            'parent_task_id': '',
            'history': [],
        }
        with open(os.path.join(infra_dir, '.cfa-state.json'), 'w') as f:
            json.dump(cfa_state, f)

        mock_result = MagicMock()
        mock_result.terminal_state = 'COMPLETED_WORK'
        mock_result.backtrack_count = 0
        mock_result.escalation_type = ''

        with patch('orchestrator.dispatch_cli.create_dispatch_worktree') as mock_create, \
             patch('orchestrator.dispatch_cli.Orchestrator') as mock_orch, \
             patch('orchestrator.dispatch_cli.cleanup_worktree', new_callable=AsyncMock), \
             patch('orchestrator.dispatch_cli.load_state', return_value=MagicMock()), \
             patch('orchestrator.dispatch_cli.make_child_state', return_value=MagicMock()), \
             patch('orchestrator.dispatch_cli.save_state'), \
             patch('orchestrator.heartbeat.register_child', return_value=None), \
             patch('orchestrator.heartbeat.finalize_heartbeat', return_value=None):

            mock_orch_inst = MagicMock()
            mock_orch_inst.run = AsyncMock(return_value=mock_result)
            mock_orch.return_value = mock_orch_inst

            result = asyncio.run(
                dispatch(
                    team='configuration',
                    task='create a skill',
                    session_worktree=session_worktree,
                    infra_dir=infra_dir,
                    project_slug='test',
                )
            )

            mock_create.assert_not_called()


# ── 5. Dispatch skips merge for direct model ─────────────────────────────────

class TestDispatchSkipsMergeForDirect(unittest.TestCase):
    """dispatch() must not squash-merge for direct-model teams."""

    def test_direct_model_does_not_call_squash_merge(self):
        """When execution_model is 'direct', squash_merge is not called."""
        from orchestrator.dispatch_cli import dispatch

        poc_root = find_poc_root()
        infra_dir = tempfile.mkdtemp()
        session_worktree = tempfile.mkdtemp()

        cfa_state = {
            'state': 'EXECUTION',
            'phase': 'execution',
            'task_id': 'test',
            'parent_task_id': '',
            'history': [],
        }
        with open(os.path.join(infra_dir, '.cfa-state.json'), 'w') as f:
            json.dump(cfa_state, f)

        mock_result = MagicMock()
        mock_result.terminal_state = 'COMPLETED_WORK'
        mock_result.backtrack_count = 0
        mock_result.escalation_type = ''

        with patch('orchestrator.dispatch_cli.create_dispatch_worktree') as mock_create, \
             patch('orchestrator.dispatch_cli.squash_merge') as mock_merge, \
             patch('orchestrator.dispatch_cli.Orchestrator') as mock_orch, \
             patch('orchestrator.dispatch_cli.cleanup_worktree', new_callable=AsyncMock), \
             patch('orchestrator.dispatch_cli.load_state', return_value=MagicMock()), \
             patch('orchestrator.dispatch_cli.make_child_state', return_value=MagicMock()), \
             patch('orchestrator.dispatch_cli.save_state'), \
             patch('orchestrator.heartbeat.register_child', return_value=None), \
             patch('orchestrator.heartbeat.finalize_heartbeat', return_value=None):

            mock_orch_inst = MagicMock()
            mock_orch_inst.run = AsyncMock(return_value=mock_result)
            mock_orch.return_value = mock_orch_inst

            result = asyncio.run(
                dispatch(
                    team='configuration',
                    task='create a skill',
                    session_worktree=session_worktree,
                    infra_dir=infra_dir,
                    project_slug='test',
                )
            )

            mock_merge.assert_not_called()


# ── 6. DispatchListener passes execution model ──────────────────────────────

class TestDispatchListenerExecutionModel(unittest.TestCase):
    """DispatchListener allows configuration team dispatches."""

    def test_configuration_team_not_rejected_by_listener(self):
        """configuration team is in _valid_teams so dispatch is not rejected."""
        from orchestrator.dispatch_listener import DispatchListener
        from orchestrator.events import EventBus

        listener = DispatchListener(
            event_bus=EventBus(),
            session_worktree='/tmp/worktree',
            infra_dir='/tmp/infra',
            project_slug='test',
            poc_root=find_poc_root(),
        )
        self.assertIn('configuration', listener._valid_teams)


# ── 7. Existing teams retain worktree model ──────────────────────────────────

class TestExistingTeamsBackwardCompat(unittest.TestCase):
    """All pre-existing teams keep execution_model 'worktree'."""

    def test_content_teams_use_worktree_model(self):
        """art, writing, editorial, research, coding all use 'worktree'."""
        config = _make_phase_config()
        for name in ('art', 'writing', 'editorial', 'research', 'coding'):
            team = config.team(name)
            self.assertEqual(
                team.execution_model, 'worktree',
                f'{name} should use worktree execution model',
            )


if __name__ == '__main__':
    unittest.main()
