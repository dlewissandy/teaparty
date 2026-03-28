"""Tests for issue #254: Escalation badge bubbling through dashboard hierarchy.

Verifies:
1. DispatchState carries needs_input for escalation detection at task level
2. SessionState.escalation_count sums dispatch escalations into subtree count
3. ProjectState.attention_count includes dispatch-level escalations
4. ESCALATIONS card appears at management and project levels
5. Project cards show numeric badge count, not just boolean indicator
6. Job-level stats include escalation count from task subtree
7. Heartbeat status (alive/stale/dead) is exposed as a visual indicator
"""
import json
import os
import tempfile
import time
import unittest

from projects.POC.tui.navigation import DashboardLevel, cards_for_level


def _make_dispatch_state(**kwargs):
    """Create a DispatchState with optional overrides."""
    from projects.POC.tui.state_reader import DispatchState
    defaults = dict(
        team='coding',
        worktree_name='wt-001',
        worktree_path='/tmp/wt',
        task='fix bug',
        status='active',
        cfa_state='',
        cfa_phase='',
        is_running=False,
        infra_dir='',
        stream_age_seconds=-1,
    )
    defaults.update(kwargs)
    return DispatchState(**defaults)


def _make_session_state(**kwargs):
    """Create a SessionState with optional overrides."""
    from projects.POC.tui.state_reader import SessionState
    defaults = dict(
        project='test-proj',
        session_id='20260328-120000',
        worktree_name='wt-session',
        worktree_path='/tmp/session',
        task='do something',
        status='active',
        cfa_phase='execution',
        cfa_state='WORK_IN_PROGRESS',
        cfa_actor='uber_team',
        needs_input=False,
        is_orphaned=False,
        dispatches=[],
        stream_age_seconds=10,
        duration_seconds=300,
        infra_dir='',
    )
    defaults.update(kwargs)
    return SessionState(**defaults)


def _make_project_state(**kwargs):
    """Create a ProjectState with optional overrides."""
    from projects.POC.tui.state_reader import ProjectState
    defaults = dict(
        slug='test-proj',
        path='/tmp/proj',
        sessions=[],
        active_count=0,
        attention_count=0,
    )
    defaults.update(kwargs)
    return ProjectState(**defaults)


class TestDispatchStateEscalationDetection(unittest.TestCase):
    """DispatchState must carry needs_input so task-level escalations are detectable."""

    def test_dispatch_state_has_needs_input_field(self):
        """DispatchState exposes needs_input for escalation detection."""
        d = _make_dispatch_state(needs_input=True)
        self.assertTrue(d.needs_input)

    def test_dispatch_state_needs_input_defaults_false(self):
        """DispatchState.needs_input defaults to False."""
        d = _make_dispatch_state()
        self.assertFalse(d.needs_input)


class TestSessionEscalationSubtreeCount(unittest.TestCase):
    """SessionState must aggregate escalation counts from its dispatch subtree."""

    def test_session_escalation_count_includes_own_escalation(self):
        """A session with needs_input=True has escalation_count >= 1."""
        s = _make_session_state(needs_input=True, dispatches=[])
        self.assertGreaterEqual(s.escalation_count, 1)

    def test_session_escalation_count_includes_dispatch_escalations(self):
        """Session escalation_count sums needs_input dispatches."""
        d1 = _make_dispatch_state(needs_input=True)
        d2 = _make_dispatch_state(needs_input=False)
        d3 = _make_dispatch_state(needs_input=True)
        s = _make_session_state(needs_input=False, dispatches=[d1, d2, d3])
        self.assertEqual(s.escalation_count, 2)

    def test_session_escalation_count_zero_when_no_escalations(self):
        """Session with no escalations anywhere has escalation_count == 0."""
        d1 = _make_dispatch_state(needs_input=False)
        s = _make_session_state(needs_input=False, dispatches=[d1])
        self.assertEqual(s.escalation_count, 0)

    def test_session_escalation_count_sums_session_and_dispatches(self):
        """Session escalation + dispatch escalations are summed."""
        d1 = _make_dispatch_state(needs_input=True)
        s = _make_session_state(needs_input=True, dispatches=[d1])
        self.assertEqual(s.escalation_count, 2)


class TestProjectAttentionCountIncludesDispatches(unittest.TestCase):
    """ProjectState.attention_count must include dispatch-level escalations, not just session-level."""

    def test_attention_count_includes_dispatch_escalations(self):
        """A project with dispatch escalations (but no session escalation) still reports attention."""
        d1 = _make_dispatch_state(needs_input=True)
        s = _make_session_state(needs_input=False, dispatches=[d1])
        # Build project from sessions with subtree escalation counts
        total_attention = sum(s.escalation_count for s in [s])
        self.assertGreaterEqual(total_attention, 1)


class TestEscalationsCardAtAllLevels(unittest.TestCase):
    """ESCALATIONS card must appear at management and project levels, not just workgroup."""

    def test_management_has_escalations_card(self):
        """Management dashboard includes an escalations card."""
        card_names = cards_for_level(DashboardLevel.MANAGEMENT)
        self.assertIn('escalations', card_names)

    def test_project_has_escalations_card(self):
        """Project dashboard includes an escalations card."""
        card_names = cards_for_level(DashboardLevel.PROJECT)
        self.assertIn('escalations', card_names)

    def test_workgroup_still_has_escalations_card(self):
        """Workgroup dashboard retains its escalations card."""
        card_names = cards_for_level(DashboardLevel.WORKGROUP)
        self.assertIn('escalations', card_names)

    def test_job_has_escalations_card(self):
        """Job dashboard includes an escalations card for task escalations."""
        card_names = cards_for_level(DashboardLevel.JOB)
        self.assertIn('escalations', card_names)

    def test_task_has_escalations_card(self):
        """Task dashboard includes an escalations card per task-dashboard.md spec."""
        card_names = cards_for_level(DashboardLevel.TASK)
        self.assertIn('escalations', card_names)


class TestProjectCardBadgeCount(unittest.TestCase):
    """Project cards on the management dashboard show numeric escalation badge counts."""

    def test_project_card_detail_shows_numeric_escalation_count(self):
        """Project card detail includes the numeric escalation count, not just a boolean icon."""
        from projects.POC.tui.screens.dashboard_screen import _build_project_items
        d1 = _make_dispatch_state(needs_input=True)
        d2 = _make_dispatch_state(needs_input=True)
        d3 = _make_dispatch_state(needs_input=True)
        s = _make_session_state(needs_input=False, dispatches=[d1, d2, d3])
        proj = _make_project_state(
            sessions=[s],
            active_count=1,
            attention_count=3,
        )
        items = _build_project_items([proj])
        self.assertEqual(len(items), 1)
        # The detail text must contain the numeric count "3", not just a boolean hourglass
        self.assertIn('3', items[0].detail)


class TestHeartbeatStatusIndicator(unittest.TestCase):
    """Heartbeat status (alive/stale/dead) is exposed as a visual indicator."""

    def test_dispatch_state_has_heartbeat_status_field(self):
        """DispatchState exposes heartbeat_status for visual indicator."""
        d = _make_dispatch_state(heartbeat_status='alive')
        self.assertEqual(d.heartbeat_status, 'alive')

    def test_heartbeat_status_alive(self):
        """Active dispatch with live heartbeat shows 'alive' status."""
        d = _make_dispatch_state(heartbeat_status='alive', status='active')
        self.assertEqual(d.heartbeat_status, 'alive')

    def test_heartbeat_status_stale(self):
        """Active dispatch with stale heartbeat shows 'stale' status."""
        d = _make_dispatch_state(heartbeat_status='stale', status='active')
        self.assertEqual(d.heartbeat_status, 'stale')

    def test_heartbeat_status_dead(self):
        """Completed dispatch shows 'dead' heartbeat status."""
        d = _make_dispatch_state(heartbeat_status='dead', status='complete')
        self.assertEqual(d.heartbeat_status, 'dead')

    def test_session_state_has_heartbeat_status_field(self):
        """SessionState exposes heartbeat_status for visual indicator."""
        s = _make_session_state(heartbeat_status='alive')
        self.assertEqual(s.heartbeat_status, 'alive')


class TestHeartbeatStatusIcon(unittest.TestCase):
    """Heartbeat status maps to distinct visual indicators."""

    def test_alive_gets_distinct_icon(self):
        """Alive heartbeat produces a visual indicator."""
        from projects.POC.tui.screens.dashboard_screen import _heartbeat_icon
        icon = _heartbeat_icon('alive')
        self.assertTrue(len(icon) > 0)

    def test_stale_gets_distinct_icon(self):
        """Stale heartbeat produces a different indicator from alive."""
        from projects.POC.tui.screens.dashboard_screen import _heartbeat_icon
        alive = _heartbeat_icon('alive')
        stale = _heartbeat_icon('stale')
        self.assertNotEqual(alive, stale)

    def test_dead_gets_distinct_icon(self):
        """Dead heartbeat produces a different indicator from alive and stale."""
        from projects.POC.tui.screens.dashboard_screen import _heartbeat_icon
        alive = _heartbeat_icon('alive')
        stale = _heartbeat_icon('stale')
        dead = _heartbeat_icon('dead')
        self.assertNotEqual(dead, alive)
        self.assertNotEqual(dead, stale)


class TestBuildEscalationItems(unittest.TestCase):
    """Escalation items are built from the subtree for ESCALATIONS cards."""

    def test_build_escalation_items_from_sessions(self):
        """Escalation items include sessions with needs_input."""
        from projects.POC.tui.screens.dashboard_screen import _build_escalation_items
        s1 = _make_session_state(session_id='s1', needs_input=True)
        s2 = _make_session_state(session_id='s2', needs_input=False)
        items = _build_escalation_items([('proj', s1), ('proj', s2)])
        # Only s1 is an escalation
        self.assertEqual(len(items), 1)
        self.assertIn('s1', items[0].label)

    def test_build_escalation_items_includes_dispatch_escalations(self):
        """Escalation items include dispatches with needs_input within sessions."""
        from projects.POC.tui.screens.dashboard_screen import _build_escalation_items
        d1 = _make_dispatch_state(needs_input=True, team='coding', worktree_name='d1')
        d2 = _make_dispatch_state(needs_input=False, team='writing', worktree_name='d2')
        s = _make_session_state(session_id='s1', needs_input=False, dispatches=[d1, d2])
        items = _build_escalation_items([('proj', s)])
        # d1 is an escalation within s1
        self.assertGreaterEqual(len(items), 1)


class TestStateReaderDispatchNeedsInput(unittest.TestCase):
    """StateReader._build_dispatch detects escalation state in dispatch CFA."""

    def test_dispatch_with_human_actor_state_has_needs_input(self):
        """A dispatch in a HUMAN_ACTOR_STATE has needs_input=True."""
        from projects.POC.tui.state_reader import HUMAN_ACTOR_STATES
        # Verify the constant exists and has the expected states
        self.assertIn('INTENT_ASSERT', HUMAN_ACTOR_STATES)
        self.assertIn('PLAN_ASSERT', HUMAN_ACTOR_STATES)
        self.assertIn('WORK_ASSERT', HUMAN_ACTOR_STATES)

    def test_build_dispatch_sets_needs_input_for_human_actor_state(self):
        """StateReader._build_dispatch sets needs_input when CFA state is in HUMAN_ACTOR_STATES."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a CFA state file with a human-actor state
            cfa_path = os.path.join(tmpdir, '.cfa-state.json')
            with open(cfa_path, 'w') as f:
                json.dump({'phase': 'intent', 'state': 'INTENT_ASSERT', 'actor': 'human'}, f)

            from projects.POC.tui.state_reader import StateReader
            reader = StateReader(poc_root=tmpdir)
            entry = {
                'name': 'test-dispatch',
                'path': '/tmp/wt',
                'team': 'coding',
                'task': 'fix bug',
                'session_id': '20260328-120000',
                'status': 'active',
                '_infra_dir': tmpdir,
            }
            dispatch = reader._build_dispatch(entry, time.time())
            self.assertTrue(dispatch.needs_input)

    def test_build_dispatch_needs_input_false_for_non_human_state(self):
        """StateReader._build_dispatch sets needs_input=False for non-human CFA states."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfa_path = os.path.join(tmpdir, '.cfa-state.json')
            with open(cfa_path, 'w') as f:
                json.dump({'phase': 'execution', 'state': 'WORK_IN_PROGRESS', 'actor': 'uber_team'}, f)

            from projects.POC.tui.state_reader import StateReader
            reader = StateReader(poc_root=tmpdir)
            entry = {
                'name': 'test-dispatch',
                'path': '/tmp/wt',
                'team': 'coding',
                'task': 'fix bug',
                'session_id': '20260328-120000',
                'status': 'active',
                '_infra_dir': tmpdir,
            }
            dispatch = reader._build_dispatch(entry, time.time())
            self.assertFalse(dispatch.needs_input)


class TestHeartbeatThreeStateThresholds(unittest.TestCase):
    """_heartbeat_three_state uses the correct thresholds from the design spec."""

    def test_fresh_heartbeat_is_alive(self):
        """Heartbeat touched within 30s reports 'alive'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hb_path = os.path.join(tmpdir, '.heartbeat')
            with open(hb_path, 'w') as f:
                json.dump({'pid': os.getpid(), 'status': 'running'}, f)
            # mtime is now (< 30s ago)
            from projects.POC.tui.state_reader import _heartbeat_three_state
            self.assertEqual(_heartbeat_three_state(tmpdir), 'alive')

    def test_heartbeat_older_than_30s_is_stale(self):
        """Heartbeat not touched for > 30s but < 300s reports 'stale'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hb_path = os.path.join(tmpdir, '.heartbeat')
            with open(hb_path, 'w') as f:
                json.dump({'pid': os.getpid(), 'status': 'running'}, f)
            # Backdate mtime to 60s ago
            old_time = time.time() - 60
            os.utime(hb_path, (old_time, old_time))
            from projects.POC.tui.state_reader import _heartbeat_three_state
            self.assertEqual(_heartbeat_three_state(tmpdir), 'stale')

    def test_heartbeat_older_than_300s_is_dead(self):
        """Heartbeat not touched for > 300s reports 'dead'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hb_path = os.path.join(tmpdir, '.heartbeat')
            with open(hb_path, 'w') as f:
                json.dump({'pid': os.getpid(), 'status': 'running'}, f)
            # Backdate mtime to 600s ago
            old_time = time.time() - 600
            os.utime(hb_path, (old_time, old_time))
            from projects.POC.tui.state_reader import _heartbeat_three_state
            self.assertEqual(_heartbeat_three_state(tmpdir), 'dead')

    def test_terminal_heartbeat_is_dead(self):
        """Completed heartbeat reports 'dead' regardless of mtime."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hb_path = os.path.join(tmpdir, '.heartbeat')
            with open(hb_path, 'w') as f:
                json.dump({'pid': os.getpid(), 'status': 'completed'}, f)
            from projects.POC.tui.state_reader import _heartbeat_three_state
            self.assertEqual(_heartbeat_three_state(tmpdir), 'dead')

    def test_no_heartbeat_file_is_dead(self):
        """Missing heartbeat file reports 'dead'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from projects.POC.tui.state_reader import _heartbeat_three_state
            self.assertEqual(_heartbeat_three_state(tmpdir), 'dead')

    def test_alive_threshold_matches_beat_interval(self):
        """The alive threshold (30s) matches claude_runner.py BEAT_INTERVAL."""
        from projects.POC.tui.state_reader import _ALIVE_THRESHOLD
        self.assertEqual(_ALIVE_THRESHOLD, 30)

    def test_dead_threshold_is_five_minutes(self):
        """The dead threshold (300s) matches the design spec's 5-minute boundary."""
        from projects.POC.tui.state_reader import _DEAD_THRESHOLD
        self.assertEqual(_DEAD_THRESHOLD, 300)


if __name__ == '__main__':
    unittest.main()
