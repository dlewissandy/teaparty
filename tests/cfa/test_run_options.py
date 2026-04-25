"""Tests for ``teaparty.cfa.run_options.RunOptions``.

Cut 23 introduced this bundle to replace the 33-arg
``Orchestrator.__init__``.  The contract:

* All fields have defaults.  ``RunOptions()`` is a valid empty bundle
  and must produce an Orchestrator that runs with vanilla settings.
* The bundle's defaults must match the pre-#23 ``__init__`` defaults
  (any change is a behavior change, not a refactor).
* Every field on ``RunOptions`` must be projected onto the matching
  attribute on ``Orchestrator``.

The third invariant is the load-bearing one — the dataclass exists to
preserve the in-process API while reshaping the constructor's surface.
A field that's defined but not threaded through ``__init__`` is an
abstraction-leak waiting to happen.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from teaparty.cfa.run_options import RunOptions
from teaparty.cfa.engine import Orchestrator
from teaparty.cfa.phase_config import PhaseConfig
from teaparty.cfa.statemachine.cfa_state import CfaState
from teaparty.messaging.bus import EventBus


def _make_phase_config():
    cfg = MagicMock(spec=PhaseConfig)
    cfg.stall_timeout = 1800
    cfg.project_lead = 'lead'
    return cfg


def _make_orchestrator(*, options: RunOptions | None = None) -> Orchestrator:
    return Orchestrator(
        cfa_state=CfaState(state='INTENT', phase='intent', history=[],
                           backtrack_count=0),
        phase_config=_make_phase_config(),
        event_bus=MagicMock(spec=EventBus, publish=AsyncMock()),
        input_provider=AsyncMock(),
        infra_dir='/tmp/infra',
        project_workdir='/tmp/project',
        session_worktree='/tmp/worktree',
        proxy_model_path='/tmp/proxy.json',
        project_slug='test',
        poc_root='/tmp/poc',
        task='do a thing',
        session_id='sess-1',
        options=options,
    )


class TestRunOptionsDefaults(unittest.TestCase):
    """Empty ``RunOptions()`` must reproduce the pre-#23 defaults."""

    def test_empty_bundle_constructs_orchestrator(self):
        """RunOptions() with no args is a valid bundle."""
        orch = _make_orchestrator(options=RunOptions())
        # All run-mode flags fall to their pre-#23 defaults.
        self.assertFalse(orch.skip_intent)
        self.assertFalse(orch.intent_only)
        self.assertFalse(orch.plan_only)
        self.assertFalse(orch.execute_only)
        self.assertFalse(orch.flat)
        self.assertFalse(orch.suppress_backtracks)
        self.assertTrue(orch.proxy_enabled)   # default True
        self.assertFalse(orch.never_escalate)
        self.assertEqual(orch.team_override, '')

    def test_options_none_is_equivalent_to_default(self):
        """Passing options=None must be equivalent to passing RunOptions()."""
        orch = _make_orchestrator(options=None)
        self.assertFalse(orch.skip_intent)
        self.assertTrue(orch.proxy_enabled)
        self.assertEqual(orch.team_override, '')
        self.assertEqual(orch._phase_session_ids, {})
        self.assertEqual(orch._last_actor_data, {})


class TestRunOptionsProjection(unittest.TestCase):
    """Every RunOptions field must be projected onto the Orchestrator."""

    def test_run_mode_flags_project(self):
        opts = RunOptions(
            skip_intent=True,
            intent_only=True,
            plan_only=True,
            execute_only=True,
            flat=True,
            suppress_backtracks=True,
            proxy_enabled=False,
            never_escalate=True,
            team_override='custom-team',
        )
        orch = _make_orchestrator(options=opts)
        self.assertTrue(orch.skip_intent)
        self.assertTrue(orch.intent_only)
        self.assertTrue(orch.plan_only)
        self.assertTrue(orch.execute_only)
        self.assertTrue(orch.flat)
        self.assertTrue(orch.suppress_backtracks)
        self.assertFalse(orch.proxy_enabled)
        self.assertTrue(orch.never_escalate)
        self.assertEqual(orch.team_override, 'custom-team')

    def test_resume_context_projects(self):
        opts = RunOptions(
            phase_session_ids={'intent': 'sid-1', 'planning': 'sid-2'},
            last_actor_data={'feedback': 'good'},
            parent_heartbeat='/tmp/parent.heartbeat',
        )
        orch = _make_orchestrator(options=opts)
        self.assertEqual(
            orch._phase_session_ids,
            {'intent': 'sid-1', 'planning': 'sid-2'},
        )
        self.assertEqual(orch._last_actor_data, {'feedback': 'good'})
        self.assertEqual(orch._parent_heartbeat, '/tmp/parent.heartbeat')

    def test_injected_dependencies_project(self):
        on_dispatch = MagicMock()
        paused_check = MagicMock(return_value=False)
        opts = RunOptions(
            project_dir='/tmp/project-dir',
            on_dispatch=on_dispatch,
            paused_check=paused_check,
            llm_backend='ollama',
        )
        orch = _make_orchestrator(options=opts)
        self.assertEqual(orch.project_dir, '/tmp/project-dir')
        self.assertIs(orch._on_dispatch, on_dispatch)
        self.assertIs(orch._paused_check, paused_check)


class TestRoleEnforcerWiring(unittest.TestCase):
    """role_enforcer projects from RunOptions onto the orchestrator.

    Cut 29 deleted the InterventionQueue + the queue-paired
    role_enforcer wiring; ``role_enforcer`` is now a plain field on
    RunOptions consumed at intervention-delivery time.
    """

    def test_role_enforcer_projects_to_orchestrator(self):
        from teaparty.util.role_enforcer import RoleEnforcer
        enforcer = MagicMock(spec=RoleEnforcer)
        opts = RunOptions(role_enforcer=enforcer)
        orch = _make_orchestrator(options=opts)
        self.assertIs(orch._role_enforcer, enforcer)


if __name__ == '__main__':
    unittest.main()
