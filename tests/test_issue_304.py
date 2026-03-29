"""Tests for issue #304: wire stats.html to live bridge API.

Acceptance criteria:
1. GET /api/stats route is registered on the bridge app
2. compute_stats returns expected shape: summary, daily, phase_escalations, limitations
3. summary.jobs_done counts sessions with cfa_state == COMPLETED_WORK
4. summary.active_jobs counts sessions with non-terminal CfA state
5. summary.backtracks sums backtrack_count across all sessions
6. summary.withdrawals counts sessions with cfa_state == WITHDRAWN
7. summary.escalations counts sessions with needs_input (HUMAN_ACTOR_STATES or .input-request.json)
8. summary.skills_learned counts from {projects_dir}/skills/ AND {projects_dir}/teams/*/skills/
9. daily has exactly 7 entries with today as last entry
10. summary.proxy_accuracy is None (open: issue #281)
11. limitations has proxy_accuracy and token_usage keys (non-empty strings)
12. stats.html fetches from /api/stats, not mockData.stats
"""
import json
import os
import shutil
import tempfile
import unittest
import datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tmpdir():
    return tempfile.mkdtemp()


def _make_session(projects_dir: str, project: str, session_id: str,
                  cfa_state: str = 'TASK_IN_PROGRESS', cfa_phase: str = 'execution',
                  backtrack_count: int = 0, cost: float = 0.0) -> str:
    """Create a session directory with .cfa-state.json and .cost files."""
    sess_dir = os.path.join(projects_dir, project, '.sessions', session_id)
    os.makedirs(sess_dir, exist_ok=True)

    cfa_data = {
        'phase': cfa_phase,
        'state': cfa_state,
        'actor': 'human' if cfa_state in ('WORK_ASSERT', 'PLAN_ASSERT') else 'planning_team',
        'history': [],
        'backtrack_count': backtrack_count,
        'task_id': session_id,
        'parent_id': '',
        'team_id': '',
        'depth': 0,
    }
    with open(os.path.join(sess_dir, '.cfa-state.json'), 'w') as f:
        json.dump(cfa_data, f)

    with open(os.path.join(sess_dir, '.cost'), 'w') as f:
        f.write(str(cost))

    return sess_dir


def _make_bridge(tmpdir):
    from projects.POC.bridge.server import TeaPartyBridge
    static_dir = os.path.join(tmpdir, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(
        teaparty_home=tmpdir,
        projects_dir=tmpdir,
        static_dir=static_dir,
    )


def _get_route_paths(app):
    return {resource.canonical for resource in app.router.resources()}


# ── Route registration ─────────────────────────────────────────────────────────

class TestStatsRouteRegistered(unittest.TestCase):
    """GET /api/stats must be registered on the bridge app."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        self.app = self.bridge._build_app()
        self.paths = _get_route_paths(self.app)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_api_stats_route_registered(self):
        self.assertIn('/api/stats', self.paths,
                      'GET /api/stats must be registered on the bridge app')


# ── compute_stats shape ────────────────────────────────────────────────────────

class TestComputeStatsShape(unittest.TestCase):
    """compute_stats must return the expected top-level shape."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        os.makedirs(os.path.join(self.tmpdir, 'POC', '.sessions'), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _compute(self):
        from projects.POC.bridge.stats import compute_stats
        return compute_stats(self.tmpdir, self.tmpdir)

    def test_returns_summary_key(self):
        result = self._compute()
        self.assertIn('summary', result)

    def test_returns_daily_key(self):
        result = self._compute()
        self.assertIn('daily', result)

    def test_returns_phase_escalations_key(self):
        result = self._compute()
        self.assertIn('phase_escalations', result)

    def test_returns_limitations_key(self):
        result = self._compute()
        self.assertIn('limitations', result)

    def test_summary_has_required_fields(self):
        result = self._compute()
        summary = result['summary']
        for field in ('jobs_done', 'tasks_done', 'active_jobs', 'backtracks',
                      'withdrawals', 'escalations', 'skills_learned',
                      'total_cost_usd', 'proxy_accuracy'):
            self.assertIn(field, summary, f'summary missing field: {field}')


# ── Jobs and terminal states ───────────────────────────────────────────────────

class TestComputeStatsSummaryMetrics(unittest.TestCase):
    """Summary metrics must be derived from real session state files."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        # Three sessions: one done, one withdrawn, one active
        _make_session(self.tmpdir, 'POC', '20260101-120000',
                      cfa_state='COMPLETED_WORK', cfa_phase='execution')
        _make_session(self.tmpdir, 'POC', '20260102-120000',
                      cfa_state='WITHDRAWN', cfa_phase='intent')
        _make_session(self.tmpdir, 'POC', '20260103-120000',
                      cfa_state='TASK_IN_PROGRESS', cfa_phase='execution',
                      backtrack_count=3)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _compute(self):
        from projects.POC.bridge.stats import compute_stats
        return compute_stats(self.tmpdir, self.tmpdir)

    def test_jobs_done_counts_completed_work_sessions(self):
        result = self._compute()
        self.assertEqual(result['summary']['jobs_done'], 1)

    def test_withdrawals_counts_withdrawn_sessions(self):
        result = self._compute()
        self.assertEqual(result['summary']['withdrawals'], 1)

    def test_active_jobs_excludes_terminal_states(self):
        result = self._compute()
        # TASK_IN_PROGRESS is non-terminal → 1 active
        self.assertEqual(result['summary']['active_jobs'], 1)

    def test_backtracks_sums_across_sessions(self):
        result = self._compute()
        # Only the TASK_IN_PROGRESS session has backtrack_count=3
        self.assertEqual(result['summary']['backtracks'], 3)

    def test_total_cost_is_non_negative(self):
        result = self._compute()
        self.assertGreaterEqual(result['summary']['total_cost_usd'], 0.0)


# ── Escalations ────────────────────────────────────────────────────────────────

class TestEscalationCounting(unittest.TestCase):
    """Escalations must count sessions in HUMAN_ACTOR_STATES or with .input-request.json."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        # Session waiting at WORK_ASSERT (human actor state → needs_input)
        _make_session(self.tmpdir, 'POC', '20260101-120000',
                      cfa_state='WORK_ASSERT', cfa_phase='execution')
        # Normal active session
        _make_session(self.tmpdir, 'POC', '20260102-120000',
                      cfa_state='TASK_IN_PROGRESS', cfa_phase='execution')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _compute(self):
        from projects.POC.bridge.stats import compute_stats
        return compute_stats(self.tmpdir, self.tmpdir)

    def test_escalation_counts_human_actor_state_session(self):
        result = self._compute()
        self.assertEqual(result['summary']['escalations'], 1)

    def test_normal_active_session_not_counted_as_escalation(self):
        result = self._compute()
        # TASK_IN_PROGRESS is not a human-actor state → only 1 escalation total
        self.assertEqual(result['summary']['escalations'], 1)

    def test_input_request_file_triggers_escalation_count(self):
        # Session with .input-request.json must be counted
        sess_dir = os.path.join(self.tmpdir, 'POC', '.sessions', '20260103-120000')
        os.makedirs(sess_dir, exist_ok=True)
        cfa_data = {
            'phase': 'execution', 'state': 'TASK_IN_PROGRESS', 'actor': 'planning_team',
            'history': [], 'backtrack_count': 0, 'task_id': '', 'parent_id': '',
            'team_id': '', 'depth': 0,
        }
        with open(os.path.join(sess_dir, '.cfa-state.json'), 'w') as f:
            json.dump(cfa_data, f)
        with open(os.path.join(sess_dir, '.input-request.json'), 'w') as f:
            json.dump({'question': 'proceed?'}, f)

        result = self._compute()
        # Now 2: WORK_ASSERT + .input-request.json
        self.assertEqual(result['summary']['escalations'], 2)


# ── Skills learned ─────────────────────────────────────────────────────────────

class TestSkillsLearnedCount(unittest.TestCase):
    """Skills count must scan per-project directories, not the top-level projects_dir."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        os.makedirs(os.path.join(self.tmpdir, 'POC', '.sessions'), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _compute(self):
        from projects.POC.bridge.stats import compute_stats
        return compute_stats(self.tmpdir, self.tmpdir)

    def test_zero_skills_when_no_skills_dirs(self):
        result = self._compute()
        self.assertEqual(result['summary']['skills_learned'], 0)

    def test_counts_project_level_skills(self):
        # Skills live inside each project directory: {projects_dir}/{slug}/skills/*.md
        # procedural_learning.py writes to {project_dir}/skills/, not {projects_dir}/skills/
        skills_dir = os.path.join(self.tmpdir, 'POC', 'skills')
        os.makedirs(skills_dir, exist_ok=True)
        open(os.path.join(skills_dir, 'fix-bug.md'), 'w').close()
        open(os.path.join(skills_dir, 'refactor.md'), 'w').close()
        result = self._compute()
        self.assertEqual(result['summary']['skills_learned'], 2)

    def test_counts_team_scoped_skills(self):
        # {project_dir}/teams/{name}/skills/*.md (issue #294)
        team_skills = os.path.join(self.tmpdir, 'POC', 'teams', 'coding', 'skills')
        os.makedirs(team_skills, exist_ok=True)
        open(os.path.join(team_skills, 'optimize.md'), 'w').close()
        result = self._compute()
        self.assertEqual(result['summary']['skills_learned'], 1)

    def test_counts_both_project_and_team_skills(self):
        skills_dir = os.path.join(self.tmpdir, 'POC', 'skills')
        os.makedirs(skills_dir, exist_ok=True)
        open(os.path.join(skills_dir, 'fix-bug.md'), 'w').close()
        team1 = os.path.join(self.tmpdir, 'POC', 'teams', 'coding', 'skills')
        os.makedirs(team1, exist_ok=True)
        open(os.path.join(team1, 'optimize.md'), 'w').close()
        team2 = os.path.join(self.tmpdir, 'POC', 'teams', 'writing', 'skills')
        os.makedirs(team2, exist_ok=True)
        open(os.path.join(team2, 'summarize.md'), 'w').close()
        result = self._compute()
        self.assertEqual(result['summary']['skills_learned'], 3)


# ── Limitations and open issues ───────────────────────────────────────────────

class TestOpenIssueLimitations(unittest.TestCase):
    """Metrics blocked by open issues must have None values and documented limitations."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        os.makedirs(os.path.join(self.tmpdir, 'POC', '.sessions'), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _compute(self):
        from projects.POC.bridge.stats import compute_stats
        return compute_stats(self.tmpdir, self.tmpdir)

    def test_proxy_accuracy_is_none(self):
        """proxy_accuracy is None until issue #281 resolves."""
        result = self._compute()
        self.assertIsNone(result['summary']['proxy_accuracy'])

    def test_limitations_has_proxy_accuracy_note(self):
        result = self._compute()
        self.assertIn('proxy_accuracy', result['limitations'])
        self.assertTrue(result['limitations']['proxy_accuracy'],
                        'proxy_accuracy limitation must be a non-empty string')

    def test_limitations_has_token_usage_note(self):
        """Token usage shows USD cost, not tokens (issue #285)."""
        result = self._compute()
        self.assertIn('token_usage', result['limitations'])
        self.assertTrue(result['limitations']['token_usage'],
                        'token_usage limitation must be a non-empty string')


# ── Daily time series ──────────────────────────────────────────────────────────

class TestDailyTimeSeries(unittest.TestCase):
    """Daily array must cover exactly 7 days with date labels and metric keys."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        os.makedirs(os.path.join(self.tmpdir, 'POC', '.sessions'), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _compute(self):
        from projects.POC.bridge.stats import compute_stats
        return compute_stats(self.tmpdir, self.tmpdir)

    def test_daily_has_7_entries(self):
        result = self._compute()
        self.assertEqual(len(result['daily']), 7)

    def test_daily_last_entry_is_today(self):
        result = self._compute()
        today_label = datetime.date.today().strftime('%b %-d')
        self.assertEqual(result['daily'][-1]['date'], today_label)

    def test_daily_entries_have_required_fields(self):
        result = self._compute()
        for entry in result['daily']:
            for field in ('date', 'tasks', 'cost_usd', 'proxy_acc'):
                self.assertIn(field, entry, f'daily entry missing field: {field}')

    def test_daily_proxy_acc_is_none(self):
        """proxy_acc is None for every day until issue #281 resolves."""
        result = self._compute()
        for entry in result['daily']:
            self.assertIsNone(entry['proxy_acc'])

    def test_daily_tasks_counts_task_completions_from_cfa_history(self):
        """Daily tasks chart counts TASK_ASSERT→approve transitions, not completed jobs.

        A session with 2 task completions today must contribute 2, not 1.
        """
        today = datetime.date.today()
        ts = today.isoformat() + 'T12:00:00+00:00'
        sess_dir = os.path.join(self.tmpdir, 'POC', '.sessions', '20260101-120000')
        os.makedirs(sess_dir, exist_ok=True)
        cfa_data = {
            'phase': 'execution', 'state': 'COMPLETED_WORK', 'actor': 'system',
            'history': [
                {'state': 'TASK_ASSERT', 'action': 'approve', 'actor': 'human', 'timestamp': ts},
                {'state': 'TASK_ASSERT', 'action': 'approve', 'actor': 'human', 'timestamp': ts},
            ],
            'backtrack_count': 0, 'task_id': '', 'parent_id': '', 'team_id': '', 'depth': 0,
        }
        with open(os.path.join(sess_dir, '.cfa-state.json'), 'w') as f:
            json.dump(cfa_data, f)

        result = self._compute()
        today_label = today.strftime('%b %-d')
        today_entry = next(e for e in result['daily'] if e['date'] == today_label)
        self.assertEqual(today_entry['tasks'], 2,
                         'Two TASK_ASSERT→approve transitions must yield tasks=2 for today')


# ── Phase escalations ──────────────────────────────────────────────────────────

class TestPhaseEscalations(unittest.TestCase):
    """phase_escalations must group active escalations by CfA phase."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        # Two sessions awaiting input in different phases
        _make_session(self.tmpdir, 'POC', '20260101-120000',
                      cfa_state='WORK_ASSERT', cfa_phase='execution')
        _make_session(self.tmpdir, 'POC', '20260102-120000',
                      cfa_state='PLAN_ASSERT', cfa_phase='planning')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _compute(self):
        from projects.POC.bridge.stats import compute_stats
        return compute_stats(self.tmpdir, self.tmpdir)

    def test_phase_escalations_groups_by_phase(self):
        result = self._compute()
        phases = {e['phase']: e['count'] for e in result['phase_escalations']}
        self.assertIn('execution', phases)
        self.assertIn('planning', phases)
        self.assertEqual(phases['execution'], 1)
        self.assertEqual(phases['planning'], 1)

    def test_no_escalations_returns_empty_list(self):
        # Replace setup with non-escalating sessions
        shutil.rmtree(self.tmpdir)
        self.tmpdir = _make_tmpdir()
        os.makedirs(os.path.join(self.tmpdir, 'POC', '.sessions'), exist_ok=True)
        _make_session(self.tmpdir, 'POC', '20260101-120000',
                      cfa_state='TASK_IN_PROGRESS', cfa_phase='execution')
        result = self._compute()
        self.assertEqual(result['phase_escalations'], [])


# ── stats.html wired to API ────────────────────────────────────────────────────

class TestStatsHtmlUsesLiveApi(unittest.TestCase):
    """stats.html must fetch from /api/stats instead of using mockData.stats."""

    _STATS_HTML = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'docs', 'proposals', 'ui-redesign', 'mockup', 'stats.html',
    )

    def _read_stats_html(self):
        with open(self._STATS_HTML) as f:
            return f.read()

    def test_stats_html_fetches_from_api_stats(self):
        html = self._read_stats_html()
        self.assertIn('/api/stats', html,
                      'stats.html must call /api/stats to fetch live data')

    def test_stats_html_does_not_use_mockdata_stats(self):
        html = self._read_stats_html()
        self.assertNotIn('mockData.stats', html,
                         'stats.html must not reference mockData.stats')


if __name__ == '__main__':
    unittest.main()
