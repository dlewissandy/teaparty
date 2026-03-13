"""Tests for orchestrator actor runners."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.actors import (
    ActorContext,
    ActorResult,
    AgentRunner,
)
from projects.POC.orchestrator.claude_runner import ClaudeResult
from projects.POC.orchestrator.events import EventBus
from projects.POC.orchestrator.phase_config import PhaseSpec


# -- Helpers -------------------------------------------------------------------

def _make_event_bus() -> EventBus:
    return EventBus()


def _make_phase_spec(
    artifact: str | None = 'INTENT.md',
    escalation_file: str = '.intent-escalation.md',
    approval_state: str = 'INTENT_ASSERT',
) -> PhaseSpec:
    return PhaseSpec(
        name='intent',
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact=artifact,
        approval_state=approval_state,
        escalation_state='INTENT_ESCALATE',
        escalation_file=escalation_file,
        settings_overlay={},
    )


def _make_ctx(
    state: str = 'PROPOSAL',
    session_worktree: str = '/tmp/worktree',
    phase_spec: PhaseSpec | None = None,
    infra_dir: str = '/tmp/infra',
) -> ActorContext:
    if phase_spec is None:
        phase_spec = _make_phase_spec()
    return ActorContext(
        state=state,
        phase='intent',
        task='Write a blog post about AI',
        infra_dir=infra_dir,
        project_workdir='/tmp/project',
        session_worktree=session_worktree,
        stream_file='.intent-stream.jsonl',
        phase_spec=phase_spec,
        poc_root='/tmp/poc',
        event_bus=_make_event_bus(),
        session_id='test-session',
    )


def _make_claude_result(exit_code: int = 0, session_id: str = 'claude-abc') -> ClaudeResult:
    return ClaudeResult(exit_code=exit_code, session_id=session_id)


# -- _interpret_output ---------------------------------------------------------

class TestInterpretOutput(unittest.TestCase):
    """Core _interpret_output behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_present_artifact_uses_assert(self):
        """When the expected artifact exists, action is 'assert'."""
        spec = _make_phase_spec(artifact='INTENT.md')
        ctx = _make_ctx(session_worktree=self.tmpdir, phase_spec=spec)
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text('# Intent')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertIn('artifact_path', result.data)

    def test_no_artifact_with_approval_state_routes_to_assert(self):
        """When artifact is None but approval_state is set, route through the gate."""
        spec = _make_phase_spec(artifact=None, approval_state='INTENT_ASSERT')
        ctx = _make_ctx(session_worktree=self.tmpdir, phase_spec=spec)

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertNotEqual(result.action, 'auto-approve')

    def test_no_artifact_no_approval_state_uses_auto_approve(self):
        """When both artifact and approval_state are empty, auto-approve is correct."""
        spec = _make_phase_spec(artifact=None, approval_state='')
        ctx = _make_ctx(session_worktree=self.tmpdir, phase_spec=spec)

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'auto-approve')

    def test_escalation_file_takes_priority(self):
        """If escalation file exists, escalate action wins before artifact check."""
        spec = _make_phase_spec(artifact='INTENT.md', escalation_file='.intent-escalation.md')
        ctx = _make_ctx(session_worktree=self.tmpdir, phase_spec=spec)

        Path(os.path.join(self.tmpdir, '.intent-escalation.md')).write_text('Need help')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'escalate')
        self.assertIn('escalation_file', result.data)


# -- Execution phase: WORK_ASSERT gate ----------------------------------------

class TestExecutionPhaseRoutesToWorkAssert(unittest.TestCase):
    """Verify execution phase (artifact=null) routes through WORK_ASSERT, not auto-approve.

    Fix for issue #116: execution has artifact=null because work output is a
    worktree of changes, not a single file. Previously, artifact=null caused
    _interpret_output to auto-approve unconditionally, making WORK_ASSERT
    unreachable dead code.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_execution_spec(self) -> PhaseSpec:
        return PhaseSpec(
            name='execution',
            agent_file='agents/uber-team.json',
            lead='project-lead',
            permission_mode='acceptEdits',
            stream_file='.exec-stream.jsonl',
            artifact=None,
            approval_state='WORK_ASSERT',
            escalation_state='TASK_ESCALATE',
            escalation_file='.task-escalation.md',
            settings_overlay={},
        )

    def test_execution_routes_to_assert_not_auto_approve(self):
        """Execution phase must route to assert (WORK_ASSERT gate), not auto-approve."""
        spec = self._make_execution_spec()
        ctx = _make_ctx(
            state='WORK_IN_PROGRESS',
            session_worktree=self.tmpdir,
            phase_spec=spec,
        )

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertNotEqual(
            result.action, 'auto-approve',
            "Execution phase must not auto-approve -- WORK_ASSERT would be unreachable",
        )

    def test_execution_does_not_flag_artifact_missing(self):
        """artifact=null means no artifact is expected -- no missing-artifact flag."""
        spec = self._make_execution_spec()
        ctx = _make_ctx(
            state='WORK_IN_PROGRESS',
            session_worktree=self.tmpdir,
            phase_spec=spec,
        )

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertNotIn('artifact_missing', result.data)

    def test_execution_config_matches_expected_values(self):
        """Verify phase-config.json execution phase declares WORK_ASSERT."""
        config_path = Path(__file__).parent.parent / 'phase-config.json'
        with open(config_path) as f:
            import json
            config = json.load(f)

        exec_phase = config['phases']['execution']
        self.assertIsNone(exec_phase['artifact'],
                          "Execution artifact should be null (work = worktree changes)")
        self.assertEqual(exec_phase['approval_state'], 'WORK_ASSERT',
                         "Execution approval_state must be WORK_ASSERT")


# -- Phase config artifact regression guards -----------------------------------

class TestPhaseConfigArtifacts(unittest.TestCase):
    """Verify phase-config.json artifact fields are correctly set for approval gates."""

    def _load_config(self) -> dict:
        config_path = Path(__file__).parent.parent / 'phase-config.json'
        with open(config_path) as f:
            import json
            return json.load(f)

    def test_planning_phase_has_approval_state(self):
        """Planning phase must declare PLAN_ASSERT so the gate is reachable."""
        config = self._load_config()
        self.assertEqual(config['phases']['planning']['approval_state'], 'PLAN_ASSERT')

    def test_intent_phase_has_intent_md_artifact(self):
        """Intent phase artifact must remain INTENT.md (regression guard)."""
        config = self._load_config()
        self.assertEqual(config['phases']['intent']['artifact'], 'INTENT.md')

    def test_all_phases_with_approval_state_are_reachable(self):
        """Every phase with a non-empty approval_state must route through its gate."""
        config = self._load_config()
        runner = AgentRunner()
        tmpdir = tempfile.mkdtemp()

        try:
            for name, spec_data in config['phases'].items():
                if not spec_data.get('approval_state'):
                    continue
                spec = PhaseSpec(
                    name=name,
                    agent_file=spec_data['agent_file'],
                    lead=spec_data['lead'],
                    permission_mode=spec_data['permission_mode'],
                    stream_file=spec_data['stream_file'],
                    artifact=spec_data.get('artifact'),
                    approval_state=spec_data['approval_state'],
                    escalation_state=spec_data.get('escalation_state', ''),
                    escalation_file=spec_data.get('escalation_file', ''),
                    settings_overlay=spec_data.get('settings_overlay', {}),
                )
                # If phase has an artifact, write it so the artifact-present path fires
                if spec.artifact:
                    Path(os.path.join(tmpdir, spec.artifact)).write_text(f'# {name}')

                ctx = _make_ctx(state='PROPOSAL', session_worktree=tmpdir, phase_spec=spec)
                result = runner._interpret_output(ctx, _make_claude_result())

                self.assertNotEqual(
                    result.action, 'auto-approve',
                    f"Phase '{name}' with approval_state='{spec.approval_state}' "
                    f"must not auto-approve",
                )
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
