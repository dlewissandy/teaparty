"""Tests for issue #273: Dashboard stats completeness.

Verifies that state_reader surfaces all data needed for dashboard stats,
and that dashboard_screen renders the full stat set at each level per the
design docs.

Spec references:
  - docs/proposals/dashboard-ui/references/management-dashboard.md (12 stats)
  - docs/proposals/dashboard-ui/references/project-dashboard.md (same minus Uptime)
  - docs/proposals/dashboard-ui/references/job-dashboard.md (5 stats)
  - docs/proposals/dashboard-ui/references/task-dashboard.md (2 stats)
"""
import json
import os
import sqlite3
import tempfile
import time
import unittest

from projects.POC.orchestrator.state_reader import (
    DispatchState,
    SessionState,
    ProjectState,
    StateReader,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_dispatch(**kwargs):
    defaults = dict(
        team='coding',
        worktree_name='wt-dispatch',
        worktree_path='/tmp/wt-dispatch',
        task='implement feature',
        status='active',
        cfa_state='WORK_IN_PROGRESS',
        cfa_phase='execution',
        is_running=True,
        infra_dir='',
        stream_age_seconds=30,
        needs_input=False,
        heartbeat_status='alive',
    )
    defaults.update(kwargs)
    return DispatchState(**defaults)


def _make_session(**kwargs):
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
        backtrack_count=0,
    )
    defaults.update(kwargs)
    return SessionState(**defaults)


def _make_project(**kwargs):
    defaults = dict(
        slug='test-proj',
        path='/tmp/proj',
        sessions=[],
        active_count=0,
        attention_count=0,
    )
    defaults.update(kwargs)
    return ProjectState(**defaults)


def _make_cfa_json(infra_dir, *, backtrack_count=0, state='WORK_IN_PROGRESS',
                    phase='execution', actor='agent', history=None):
    """Write a .cfa-state.json file in infra_dir."""
    data = {
        'phase': phase,
        'state': state,
        'actor': actor,
        'history': history or [],
        'backtrack_count': backtrack_count,
    }
    os.makedirs(infra_dir, exist_ok=True)
    with open(os.path.join(infra_dir, '.cfa-state.json'), 'w') as f:
        json.dump(data, f)


def _make_proxy_db(project_path, n_chunks=5, n_matched=3):
    """Create a .proxy-memory.db with n_chunks chunks, n_matched with matching predictions."""
    db_path = os.path.join(project_path, '.proxy-memory.db')
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proxy_chunks (
            id TEXT PRIMARY KEY,
            state TEXT DEFAULT '',
            task_type TEXT DEFAULT '',
            content TEXT DEFAULT '',
            outcome TEXT DEFAULT '',
            prior_prediction TEXT DEFAULT '',
            posterior_prediction TEXT DEFAULT '',
            prior_confidence REAL DEFAULT 0.0,
            posterior_confidence REAL DEFAULT 0.0,
            prediction_delta TEXT DEFAULT '',
            salient_percepts TEXT DEFAULT '[]',
            human_response TEXT DEFAULT '',
            traces TEXT DEFAULT '[]',
            deleted INTEGER DEFAULT 0,
            embedding BLOB DEFAULT NULL,
            embedding_model TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proxy_state (
            key TEXT PRIMARY KEY,
            value INTEGER
        )
    """)
    for i in range(n_chunks):
        outcome = 'approve'
        posterior = 'approve' if i < n_matched else 'reject'
        conn.execute(
            "INSERT INTO proxy_chunks (id, state, outcome, posterior_prediction, human_response) "
            "VALUES (?, ?, ?, ?, ?)",
            (f'chunk-{i}', 'WORK_ASSERT', outcome, posterior, 'yes'),
        )
    conn.commit()
    conn.close()
    return db_path


# ── SessionState.backtrack_count ────────────────────────────────────────────

class TestSessionStateBacktrackCount(unittest.TestCase):
    """SessionState must expose backtrack_count from .cfa-state.json."""

    def test_session_state_has_backtrack_count_field(self):
        """SessionState dataclass should have a backtrack_count field."""
        s = _make_session(backtrack_count=3)
        self.assertEqual(s.backtrack_count, 3)

    def test_default_backtrack_count_is_zero(self):
        s = _make_session()
        self.assertEqual(s.backtrack_count, 0)


# ── StateReader extracts backtrack_count ─────────────────────────────────────

class TestStateReaderBacktrackCount(unittest.TestCase):
    """StateReader._build_session must read backtrack_count from .cfa-state.json."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.poc_root = os.path.join(self.tmpdir, 'POC')
        os.makedirs(self.poc_root)
        # Create a project with a session
        self.proj_dir = os.path.join(self.tmpdir, 'test-proj')
        self.sess_dir = os.path.join(self.proj_dir, '.sessions', '20260328-120000')
        os.makedirs(self.sess_dir)
        # Write worktrees.json
        with open(os.path.join(self.tmpdir, 'worktrees.json'), 'w') as f:
            json.dump({'worktrees': []}, f)

    def test_backtrack_count_read_from_cfa_state(self):
        """StateReader should populate backtrack_count from .cfa-state.json."""
        _make_cfa_json(self.sess_dir, backtrack_count=5)
        reader = StateReader(self.poc_root, projects_dir=self.tmpdir)
        reader.reload()
        sessions = reader.sessions
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].backtrack_count, 5)

    def test_backtrack_count_defaults_to_zero_when_missing(self):
        """If .cfa-state.json has no backtrack_count, default to 0."""
        os.makedirs(self.sess_dir, exist_ok=True)
        cfa = {'phase': 'execution', 'state': 'WORK_IN_PROGRESS', 'actor': 'agent'}
        with open(os.path.join(self.sess_dir, '.cfa-state.json'), 'w') as f:
            json.dump(cfa, f)
        reader = StateReader(self.poc_root, projects_dir=self.tmpdir)
        reader.reload()
        self.assertEqual(reader.sessions[0].backtrack_count, 0)


# ── Management dashboard stats ───────────────────────────────────────────────

class TestManagementDashboardStats(unittest.TestCase):
    """Management dashboard must render all 12 stats from the spec."""

    def test_management_stats_include_all_spec_keys(self):
        """Stats bar should contain all 12 keys from management-dashboard.md."""
        from projects.POC.orchestrator.dashboard_stats import compute_management_stats
        completed = _make_session(
            session_id='20260328-100000',
            cfa_state='COMPLETED_WORK', status='complete',
            backtrack_count=0,
        )
        backtracked = _make_session(
            session_id='20260328-110000',
            cfa_state='COMPLETED_WORK', status='complete',
            backtrack_count=2,
            dispatches=[_make_dispatch(status='complete'), _make_dispatch(status='complete')],
        )
        active = _make_session(
            session_id='20260328-120000',
            status='active', needs_input=True,
            dispatches=[_make_dispatch(status='active')],
        )
        withdrawn = _make_session(
            session_id='20260328-130000',
            cfa_state='WITHDRAWN', status='complete',
        )
        projects = [_make_project(sessions=[completed, backtracked, active, withdrawn])]

        stats = compute_management_stats(projects)

        expected_keys = {
            'jobs_done', 'tasks_done', 'active', 'one_shots',
            'backtracks', 'withdrawals', 'escalations', 'interventions',
            'proxy_accuracy', 'tokens', 'skills_learned', 'uptime',
        }
        self.assertEqual(set(stats.keys()), expected_keys)

    def test_jobs_done_counts_completed_work(self):
        from projects.POC.orchestrator.dashboard_stats import compute_management_stats
        done = _make_session(cfa_state='COMPLETED_WORK')
        active = _make_session(session_id='20260328-130000', cfa_state='WORK_IN_PROGRESS')
        stats = compute_management_stats([_make_project(sessions=[done, active])])
        self.assertEqual(stats['jobs_done'], 1)

    def test_tasks_done_counts_completed_dispatches(self):
        from projects.POC.orchestrator.dashboard_stats import compute_management_stats
        d1 = _make_dispatch(status='complete')
        d2 = _make_dispatch(status='active')
        s = _make_session(dispatches=[d1, d2])
        stats = compute_management_stats([_make_project(sessions=[s])])
        self.assertEqual(stats['tasks_done'], 1)

    def test_one_shots_counts_completed_with_zero_backtracks(self):
        from projects.POC.orchestrator.dashboard_stats import compute_management_stats
        oneshot = _make_session(
            session_id='20260328-100000',
            cfa_state='COMPLETED_WORK', backtrack_count=0,
        )
        backtracked = _make_session(
            session_id='20260328-110000',
            cfa_state='COMPLETED_WORK', backtrack_count=1,
        )
        stats = compute_management_stats([_make_project(sessions=[oneshot, backtracked])])
        self.assertEqual(stats['one_shots'], 1)

    def test_backtracks_sums_backtrack_counts(self):
        from projects.POC.orchestrator.dashboard_stats import compute_management_stats
        s1 = _make_session(session_id='20260328-100000', backtrack_count=2)
        s2 = _make_session(session_id='20260328-110000', backtrack_count=3)
        stats = compute_management_stats([_make_project(sessions=[s1, s2])])
        self.assertEqual(stats['backtracks'], 5)

    def test_unavailable_stats_are_none(self):
        """Stats that depend on optional subsystems should be None when unavailable."""
        from projects.POC.orchestrator.dashboard_stats import compute_management_stats
        stats = compute_management_stats([_make_project(sessions=[])])
        self.assertIsNone(stats['tokens'])
        self.assertIsNone(stats['proxy_accuracy'])
        self.assertIsNone(stats['skills_learned'])
        self.assertIsNone(stats['interventions'])


# ── Proxy stats from proxy_memory.db ─────────────────────────────────────────

class TestProxyStatsFromDB(unittest.TestCase):
    """Proxy accuracy and skills learned should be queried from proxy_memory.db."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proj_path = os.path.join(self.tmpdir, 'test-proj')
        os.makedirs(self.proj_path)

    def test_proxy_accuracy_computed_from_db(self):
        """When proxy_memory.db exists with accuracy data, proxy_accuracy should be a percentage string."""
        from projects.POC.orchestrator.dashboard_stats import _proxy_stats
        _make_proxy_db(self.proj_path, n_chunks=10, n_matched=7)
        # Also populate proxy_accuracy table
        db_path = os.path.join(self.proj_path, '.proxy-memory.db')
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS proxy_accuracy "
            "(state TEXT, task_type TEXT, prior_correct INTEGER, prior_total INTEGER, "
            "posterior_correct INTEGER, posterior_total INTEGER, last_updated TEXT, "
            "PRIMARY KEY (state, task_type))"
        )
        conn.execute(
            "INSERT INTO proxy_accuracy VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('WORK_ASSERT', 'fix', 6, 10, 7, 10, '2026-03-28'),
        )
        conn.commit()
        conn.close()
        accuracy, chunks = _proxy_stats([self.proj_path])
        self.assertEqual(accuracy, '70%')

    def test_skills_learned_from_chunk_count(self):
        """Skills learned should equal non-deleted chunk count."""
        from projects.POC.orchestrator.dashboard_stats import _proxy_stats
        _make_proxy_db(self.proj_path, n_chunks=8, n_matched=5)
        _, chunks = _proxy_stats([self.proj_path])
        self.assertEqual(chunks, 8)

    def test_no_db_returns_none(self):
        """When no proxy_memory.db exists, return None for both."""
        from projects.POC.orchestrator.dashboard_stats import _proxy_stats
        accuracy, chunks = _proxy_stats([self.proj_path])
        self.assertIsNone(accuracy)
        self.assertIsNone(chunks)

    def test_management_stats_wire_proxy_data(self):
        """compute_management_stats should pass project paths to _proxy_stats."""
        from projects.POC.orchestrator.dashboard_stats import compute_management_stats
        _make_proxy_db(self.proj_path, n_chunks=5, n_matched=3)
        proj = _make_project(slug='test-proj', path=self.proj_path,
                             sessions=[_make_session()])
        stats = compute_management_stats([proj])
        self.assertEqual(stats['skills_learned'], 5)


# ── Project dashboard stats ──────────────────────────────────────────────────

class TestProjectDashboardStats(unittest.TestCase):
    """Project dashboard stats: same as management minus Uptime."""

    def test_project_stats_exclude_uptime(self):
        from projects.POC.orchestrator.dashboard_stats import compute_project_stats
        stats = compute_project_stats([])
        self.assertNotIn('uptime', stats)

    def test_project_stats_include_core_keys(self):
        from projects.POC.orchestrator.dashboard_stats import compute_project_stats
        s = _make_session(cfa_state='COMPLETED_WORK', backtrack_count=0)
        stats = compute_project_stats([s])
        for key in ('jobs_done', 'tasks_done', 'active', 'one_shots',
                    'backtracks', 'withdrawals', 'escalations'):
            self.assertIn(key, stats, f'Missing key: {key}')


# ── Job dashboard stats ──────────────────────────────────────────────────────

class TestJobDashboardStats(unittest.TestCase):
    """Job dashboard: Tasks, Backtracks, Escalations, Tokens, Elapsed."""

    def test_job_stats_include_spec_keys(self):
        from projects.POC.orchestrator.dashboard_stats import compute_job_stats
        d1 = _make_dispatch(status='complete')
        d2 = _make_dispatch(status='active')
        s = _make_session(dispatches=[d1, d2], backtrack_count=3, duration_seconds=600)
        stats = compute_job_stats(s)
        self.assertIn('tasks', stats)
        self.assertIn('backtracks', stats)
        self.assertIn('escalations', stats)
        self.assertIn('tokens', stats)
        self.assertIn('elapsed', stats)

    def test_job_backtracks_from_session(self):
        from projects.POC.orchestrator.dashboard_stats import compute_job_stats
        s = _make_session(backtrack_count=4)
        stats = compute_job_stats(s)
        self.assertEqual(stats['backtracks'], 4)


# ── Task dashboard stats ─────────────────────────────────────────────────────

class TestTaskDashboardStats(unittest.TestCase):
    """Task dashboard: Tokens, Elapsed."""

    def test_task_stats_include_spec_keys(self):
        from projects.POC.orchestrator.dashboard_stats import compute_task_stats
        d = _make_dispatch(stream_age_seconds=120)
        stats = compute_task_stats(d)
        self.assertIn('tokens', stats)
        self.assertIn('elapsed', stats)


# ── Dashboard rendering uses full stat set ───────────────────────────────────

class TestDashboardStatsRendering(unittest.TestCase):
    """The _refresh_* methods must pass all stats to _set_stats."""

    def test_management_stats_bar_has_twelve_entries(self):
        """Management stats bar should have 12 stat entries."""
        from projects.POC.orchestrator.dashboard_stats import format_management_stats
        completed = _make_session(
            session_id='20260328-100000',
            cfa_state='COMPLETED_WORK', backtrack_count=0,
        )
        projects = [_make_project(sessions=[completed])]
        pairs = format_management_stats(projects)
        self.assertEqual(len(pairs), 12)

    def test_job_stats_bar_has_five_entries(self):
        """Job stats bar should have 5 stat entries per spec."""
        from projects.POC.orchestrator.dashboard_stats import format_job_stats
        s = _make_session(
            dispatches=[_make_dispatch(status='complete')],
            backtrack_count=1, duration_seconds=600,
        )
        pairs = format_job_stats(s)
        self.assertEqual(len(pairs), 5)

    def test_task_stats_bar_has_two_entries(self):
        """Task stats bar should have 2 stat entries per spec."""
        from projects.POC.orchestrator.dashboard_stats import format_task_stats
        d = _make_dispatch(stream_age_seconds=120)
        pairs = format_task_stats(d)
        self.assertEqual(len(pairs), 2)


# ── Graceful degradation ─────────────────────────────────────────────────────

class TestGracefulDegradation(unittest.TestCase):
    """Stats that depend on optional subsystems show '—' when unavailable."""

    def test_none_stats_format_as_dash(self):
        from projects.POC.orchestrator.dashboard_stats import format_stat_value
        self.assertEqual(format_stat_value(None), '\u2014')

    def test_numeric_stats_format_normally(self):
        from projects.POC.orchestrator.dashboard_stats import format_stat_value
        self.assertEqual(format_stat_value(42), '42')

    def test_string_stats_pass_through(self):
        from projects.POC.orchestrator.dashboard_stats import format_stat_value
        self.assertEqual(format_stat_value('5m'), '5m')


if __name__ == '__main__':
    unittest.main()
