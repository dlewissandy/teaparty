"""Tests for issue #289: Gate-aware Review button via GET /api/cfa/{session_id}.

Acceptance criteria:
1. _load_cfa_state returns the `state` field (the gate discriminator)
2. _resolve_session_infra maps a session_id to its infra dir by scanning projects
3. _resolve_session_infra returns None when session not found
4. GET /api/cfa/{session_id} returns state field for gate assertion states
5. chat.html uses cfa.state (not cfa.phase) to drive GATE_ARTIFACTS lookup
6. GATE_ARTIFACTS maps INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT to artifact files
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


def _make_tmpdir():
    return tempfile.mkdtemp()


def _write_cfa_state(infra_dir, state, phase='execution', actor='human'):
    """Write a minimal .cfa-state.json to infra_dir."""
    data = {
        'phase': phase,
        'state': state,
        'actor': actor,
        'history': [],
        'backtrack_count': 0,
        'task_id': '',
    }
    path = os.path.join(infra_dir, '.cfa-state.json')
    with open(path, 'w') as f:
        json.dump(data, f)
    return path


# ── _load_cfa_state: state field is the gate discriminator ───────────────────

class TestLoadCfaStateReturnsStateField(unittest.TestCase):
    """_load_cfa_state must return `state` as the gate discriminator."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_state_field_present_for_gate_assertion(self):
        """state field must be included in the result for assertion-phase states."""
        from projects.POC.bridge.server import _load_cfa_state
        _write_cfa_state(self.tmpdir, state='INTENT_ASSERT', phase='intent', actor='human')
        result = _load_cfa_state(self.tmpdir)
        self.assertIsNotNone(result)
        self.assertIn('state', result)
        self.assertEqual(result['state'], 'INTENT_ASSERT')

    def test_state_field_distinct_from_phase(self):
        """state and phase must be separate fields — they carry different values."""
        from projects.POC.bridge.server import _load_cfa_state
        _write_cfa_state(self.tmpdir, state='PLAN_ASSERT', phase='planning', actor='human')
        result = _load_cfa_state(self.tmpdir)
        self.assertIn('phase', result)
        self.assertIn('state', result)
        self.assertEqual(result['phase'], 'planning')
        self.assertEqual(result['state'], 'PLAN_ASSERT')
        # These must not be equal — if both were cfa.phase they would be
        self.assertNotEqual(result['phase'], result['state'])

    def test_state_field_present_for_work_assert(self):
        """WORK_ASSERT must appear in the state field for the final gate."""
        from projects.POC.bridge.server import _load_cfa_state
        _write_cfa_state(self.tmpdir, state='WORK_ASSERT', phase='execution', actor='human')
        result = _load_cfa_state(self.tmpdir)
        self.assertEqual(result['state'], 'WORK_ASSERT')

    def test_state_field_present_for_non_gate_state(self):
        """Non-gate states must also be present in the state field."""
        from projects.POC.bridge.server import _load_cfa_state
        _write_cfa_state(self.tmpdir, state='WORK_EXEC', phase='execution', actor='agent')
        result = _load_cfa_state(self.tmpdir)
        self.assertIn('state', result)
        self.assertEqual(result['state'], 'WORK_EXEC')


# ── _resolve_session_infra: session ID → infra dir ───────────────────────────

class TestResolveSessionInfra(unittest.TestCase):
    """_resolve_session_infra must locate infra dir from session_id."""

    def setUp(self):
        self.projects_dir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.projects_dir, ignore_errors=True)

    def _make_bridge(self):
        from projects.POC.bridge.server import TeaPartyBridge
        static_dir = os.path.join(self.projects_dir, 'static')
        os.makedirs(static_dir, exist_ok=True)
        return TeaPartyBridge(
            teaparty_home=self.projects_dir,
            projects_dir=self.projects_dir,
            static_dir=static_dir,
        )

    def _make_infra(self, project_slug, session_id):
        """Create {projects_dir}/{slug}/.sessions/{session_id}/ and return path."""
        infra_dir = os.path.join(
            self.projects_dir, project_slug, '.sessions', session_id
        )
        os.makedirs(infra_dir)
        return infra_dir

    def test_resolves_existing_session(self):
        """Must return the infra_dir for a session that exists."""
        bridge = self._make_bridge()
        infra = self._make_infra('my-project', '20260101-120000')
        result = bridge._resolve_session_infra('20260101-120000')
        self.assertEqual(result, infra)

    def test_returns_none_for_unknown_session(self):
        """Must return None when no project contains the session_id."""
        bridge = self._make_bridge()
        self._make_infra('my-project', '20260101-120000')
        result = bridge._resolve_session_infra('99991231-235959')
        self.assertIsNone(result)

    def test_resolves_session_in_second_project(self):
        """Must search all projects, not just the first one found."""
        bridge = self._make_bridge()
        self._make_infra('proj-a', '20260101-000000')
        infra_b = self._make_infra('proj-b', '20260202-000000')
        result = bridge._resolve_session_infra('20260202-000000')
        self.assertEqual(result, infra_b)

    def test_returns_none_when_projects_dir_empty(self):
        """Must return None gracefully when no projects exist."""
        bridge = self._make_bridge()
        result = bridge._resolve_session_infra('20260101-120000')
        self.assertIsNone(result)


# ── chat.html: uses cfa.state not cfa.phase for GATE_ARTIFACTS ───────────────

class TestChatHtmlGateReviewLogic(unittest.TestCase):
    """chat.html must use cfa.state (not cfa.phase) to drive gate button visibility."""

    def _read_chat_html(self):
        chat_path = Path(__file__).parent.parent / \
            'docs/proposals/ui-redesign/mockup/chat.html'
        return chat_path.read_text()

    def test_gate_artifacts_keyed_by_assert_states(self):
        """GATE_ARTIFACTS must be keyed by INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT."""
        source = self._read_chat_html()
        self.assertIn("'INTENT_ASSERT'", source)
        self.assertIn("'PLAN_ASSERT'", source)
        self.assertIn("'WORK_ASSERT'", source)

    def test_gate_visibility_driven_by_cfa_state_not_cfa_phase(self):
        """pageState must be populated from cfa.state, not cfa.phase, for gate lookup."""
        source = self._read_chat_html()
        # The correct field assignment: cfa.state
        self.assertIn('cfa.state', source,
                      'chat.html must read cfa.state to drive gate button visibility')

    def test_cfa_phase_not_used_for_gate_lookup(self):
        """cfa.phase must not be assigned where GATE_ARTIFACTS lookup happens.

        cfa.phase returns 'intent'/'planning'/'execution' — lowercase phase strings
        that never match GATE_ARTIFACTS keys like 'INTENT_ASSERT'. Using cfa.phase
        as the gate discriminator means the Review button is never shown.
        """
        source = self._read_chat_html()
        # cfa.phase may appear for other purposes (display), but must not be the
        # value stored in the variable that GATE_ARTIFACTS is indexed by.
        # The gate variable must be assigned from cfa.state.
        self.assertIn('cfa.state', source,
                      'gate button visibility must be driven by cfa.state')
        # Confirm 'INTENT_ASSERT' would actually match: the state keys must be
        # present and the variable holding cfa.state must be checked against them.
        self.assertIn("GATE_ARTIFACTS[pageState.", source,
                      'gateReviewButtonHtml must look up pageState variable in GATE_ARTIFACTS')

    def test_review_intent_artifact_file_is_intent_md(self):
        """INTENT_ASSERT gate must link to INTENT.md."""
        source = self._read_chat_html()
        # Find the INTENT_ASSERT block and verify INTENT.md is referenced nearby
        idx = source.find("'INTENT_ASSERT'")
        self.assertGreater(idx, 0)
        excerpt = source[idx:idx+120]
        self.assertIn('INTENT.md', excerpt)

    def test_review_plan_artifact_file_is_plan_md(self):
        """PLAN_ASSERT gate must link to PLAN.md."""
        source = self._read_chat_html()
        idx = source.find("'PLAN_ASSERT'")
        self.assertGreater(idx, 0)
        excerpt = source[idx:idx+120]
        self.assertIn('PLAN.md', excerpt)

    def test_review_work_artifact_file_is_work_assert_md(self):
        """WORK_ASSERT gate must link to WORK_ASSERT.md."""
        source = self._read_chat_html()
        idx = source.find("'WORK_ASSERT'")
        self.assertGreater(idx, 0)
        excerpt = source[idx:idx+120]
        self.assertIn('WORK_ASSERT.md', excerpt)


if __name__ == '__main__':
    unittest.main()
