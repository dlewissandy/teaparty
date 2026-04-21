"""Issue #387: Statistics page shows all zeros — no data reaches the dashboard.

Tests that:
1. Legacy .sessions/ data is migrated to .teaparty/jobs/ format
2. Stats summary computes non-zero totals from job data
3. Jobs done counts COMPLETED_WORK sessions
4. Tasks done counts completed-work transitions (WORK_ASSERT→approve)
5. Backtracks counts CfA state machine reversals
6. Withdrawals counts cancelled sessions
7. Escalations counts historical human-contact events (not point-in-time)
8. Daily charts produce meaningful time-series data
9. Registry mode (teaparty_home) works end-to-end
"""
from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest

import yaml


def _make_cfa_state(
    *,
    state: str = 'COMPLETED_WORK',
    phase: str = 'work',
    actor: str = 'agent',
    backtrack_count: int = 0,
    history: list | None = None,
) -> dict:
    return {
        'phase': phase,
        'state': state,
        'actor': actor,
        'backtrack_count': backtrack_count,
        'history': history or [],
    }


def _make_job(
    project_dir: str,
    session_id: str,
    *,
    cfa_state: str = 'COMPLETED_WORK',
    cfa_phase: str = 'work',
    backtrack_count: int = 0,
    history: list | None = None,
    prompt: str = '',
) -> str:
    """Create a .teaparty/jobs/ entry with CfA state files."""
    slug = 'test-task'
    dir_name = f'job-{session_id}--{slug}'
    job_dir = os.path.join(project_dir, '.teaparty', 'jobs', dir_name)
    os.makedirs(job_dir, exist_ok=True)

    # job.json
    job_state = {
        'job_id': f'job-{session_id}',
        'slug': slug,
        'issue': None,
        'branch': '',
        'status': 'complete' if cfa_state in ('COMPLETED_WORK', 'WITHDRAWN') else 'active',
        'created_at': '2026-04-01T00:00:00+00:00',
        'updated_at': '2026-04-01T00:00:00+00:00',
    }
    with open(os.path.join(job_dir, 'job.json'), 'w') as f:
        json.dump(job_state, f)

    # .cfa-state.json
    cfa = _make_cfa_state(
        state=cfa_state, phase=cfa_phase,
        backtrack_count=backtrack_count, history=history,
    )
    with open(os.path.join(job_dir, '.cfa-state.json'), 'w') as f:
        json.dump(cfa, f)

    # .heartbeat (terminal)
    with open(os.path.join(job_dir, '.heartbeat'), 'w') as f:
        json.dump({'status': 'completed', 'pid': 99999, 'ts': 0}, f)

    if prompt:
        with open(os.path.join(job_dir, 'PROMPT.txt'), 'w') as f:
            f.write(prompt)

    return job_dir


def _make_legacy_session(project_dir: str, session_id: str, *,
                         cfa_state: str = 'COMPLETED_WORK',
                         backtrack_count: int = 0,
                         history: list | None = None,
                         prompt: str = '') -> str:
    """Create a legacy .sessions/{session_id}/ directory with state files."""
    session_dir = os.path.join(project_dir, '.sessions', session_id)
    os.makedirs(session_dir, exist_ok=True)

    cfa = _make_cfa_state(state=cfa_state, backtrack_count=backtrack_count,
                          history=history)
    with open(os.path.join(session_dir, '.cfa-state.json'), 'w') as f:
        json.dump(cfa, f)
    with open(os.path.join(session_dir, '.heartbeat'), 'w') as f:
        json.dump({'status': 'completed', 'pid': 99999, 'ts': 0}, f)
    if prompt:
        with open(os.path.join(session_dir, 'PROMPT.txt'), 'w') as f:
            f.write(prompt)
    return session_dir


class TestLegacyMigration(unittest.TestCase):
    """SC1: Legacy .sessions/ data is migrated to .teaparty/jobs/ format."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self._tmpdir, 'myproject')
        os.makedirs(os.path.join(self.project_dir, '.teaparty'), exist_ok=True)

    def test_migrate_creates_job_entry(self):
        """migrate_legacy_sessions creates a .teaparty/jobs/ entry from .sessions/."""
        _make_legacy_session(self.project_dir, '20260401-120000',
                             cfa_state='COMPLETED_WORK', prompt='Fix the bug')

        from teaparty.workspace.job_store import migrate_legacy_sessions
        migrated = migrate_legacy_sessions(self.project_dir)

        self.assertEqual(migrated, ['20260401-120000'])

        # Job directory exists
        jobs_dir = os.path.join(self.project_dir, '.teaparty', 'jobs')
        self.assertTrue(os.path.isdir(jobs_dir))

        # job.json exists with correct job_id
        entries = os.listdir(jobs_dir)
        job_dirs = [e for e in entries if e.startswith('job-20260401-120000')]
        self.assertEqual(len(job_dirs), 1)

        job_json = os.path.join(jobs_dir, job_dirs[0], 'job.json')
        with open(job_json) as f:
            state = json.load(f)
        self.assertEqual(state['job_id'], 'job-20260401-120000')
        self.assertEqual(state['status'], 'complete')

    def test_migrate_moves_cfa_state(self):
        """CfA state files are moved into the new job directory."""
        _make_legacy_session(self.project_dir, '20260401-120000',
                             cfa_state='COMPLETED_WORK', backtrack_count=3)

        from teaparty.workspace.job_store import migrate_legacy_sessions
        migrate_legacy_sessions(self.project_dir)

        # .sessions/ directory removed
        self.assertFalse(os.path.isdir(
            os.path.join(self.project_dir, '.sessions')))

        # CfA state in new location
        from teaparty.workspace.job_store import find_job
        job = find_job(self.project_dir, job_id='job-20260401-120000')
        self.assertIsNotNone(job)
        cfa_path = os.path.join(job['_job_dir'], '.cfa-state.json')
        with open(cfa_path) as f:
            cfa = json.load(f)
        self.assertEqual(cfa['backtrack_count'], 3)

    def test_migrate_skips_already_migrated(self):
        """Sessions that already have a job entry are not re-migrated."""
        _make_legacy_session(self.project_dir, '20260401-120000')

        from teaparty.workspace.job_store import migrate_legacy_sessions
        migrate_legacy_sessions(self.project_dir)
        # Second call should find nothing to migrate
        migrated = migrate_legacy_sessions(self.project_dir)
        self.assertEqual(migrated, [])

    def test_stats_after_migration(self):
        """compute_stats finds data after legacy migration."""
        _make_legacy_session(self.project_dir, '20260401-120000',
                             cfa_state='COMPLETED_WORK')

        from teaparty.workspace.job_store import migrate_legacy_sessions
        migrate_legacy_sessions(self.project_dir)

        from teaparty.bridge.stats import compute_stats
        stats = compute_stats(teaparty_home='', projects_dir=self._tmpdir)

        self.assertEqual(stats['summary']['jobs_done'], 1)


class TestStatsFromJobs(unittest.TestCase):
    """SC2-6: compute_stats produces correct totals from .teaparty/jobs/ data."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self._tmpdir, 'myproject')
        os.makedirs(os.path.join(self.project_dir, '.teaparty'), exist_ok=True)

    def test_jobs_done_counts_completed_sessions(self):
        _make_job(self.project_dir, '20260401-120000',
                  cfa_state='COMPLETED_WORK')
        _make_job(self.project_dir, '20260402-120000',
                  cfa_state='COMPLETED_WORK')
        _make_job(self.project_dir, '20260403-120000',
                  cfa_state='WITHDRAWN')

        from teaparty.bridge.stats import compute_stats
        stats = compute_stats(teaparty_home='', projects_dir=self._tmpdir)
        self.assertEqual(stats['summary']['jobs_done'], 2)

    def test_withdrawals_counts_withdrawn_sessions(self):
        _make_job(self.project_dir, '20260401-120000',
                  cfa_state='COMPLETED_WORK')
        _make_job(self.project_dir, '20260402-120000',
                  cfa_state='WITHDRAWN')

        from teaparty.bridge.stats import compute_stats
        stats = compute_stats(teaparty_home='', projects_dir=self._tmpdir)
        self.assertEqual(stats['summary']['withdrawals'], 1)

    def test_backtracks_sums_across_sessions(self):
        _make_job(self.project_dir, '20260401-120000',
                  cfa_state='COMPLETED_WORK', backtrack_count=2)
        _make_job(self.project_dir, '20260402-120000',
                  cfa_state='COMPLETED_WORK', backtrack_count=5)

        from teaparty.bridge.stats import compute_stats
        stats = compute_stats(teaparty_home='', projects_dir=self._tmpdir)
        self.assertEqual(stats['summary']['backtracks'], 7)

    def test_tasks_done_counts_work_assert_approve(self):
        history = [
            {'state': 'WORK_ASSERT', 'action': 'approve',
             'timestamp': '2026-04-01T12:00:00+00:00'},
            {'state': 'WORK_ASSERT', 'action': 'approve',
             'timestamp': '2026-04-01T13:00:00+00:00'},
            {'state': 'PLAN_ASSERT', 'action': 'approve',
             'timestamp': '2026-04-01T11:00:00+00:00'},
        ]
        _make_job(self.project_dir, '20260401-120000',
                  cfa_state='COMPLETED_WORK', history=history)

        from teaparty.bridge.stats import compute_stats
        stats = compute_stats(teaparty_home='', projects_dir=self._tmpdir)
        self.assertEqual(stats['summary']['tasks_done'], 2)


class TestHistoricalEscalations(unittest.TestCase):
    """SC7: Escalations counts total historical human-contact events."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self._tmpdir, 'myproject')
        os.makedirs(os.path.join(self.project_dir, '.teaparty'), exist_ok=True)

    def test_escalations_zero_when_skills_handle_dialog(self):
        """Intent and planning phases run skills that handle dialog
        internally via AskQuestion; no state-machine ESCALATE states
        remain, so the escalation counter is always zero for these
        historical events."""
        history = [
            {'state': 'WORK_ASSERT', 'action': 'approve',
             'timestamp': '2026-04-01T15:00:00+00:00'},
        ]
        _make_job(self.project_dir, '20260401-120000',
                  cfa_state='COMPLETED_WORK', history=history)

        from teaparty.bridge.stats import compute_stats
        stats = compute_stats(teaparty_home='', projects_dir=self._tmpdir)
        self.assertEqual(stats['summary']['escalations'], 0)


class TestDailyCharts(unittest.TestCase):
    """SC8: Daily charts show meaningful time-series data."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self._tmpdir, 'myproject')
        os.makedirs(os.path.join(self.project_dir, '.teaparty'), exist_ok=True)

    def test_daily_tasks_chart_shows_data(self):
        today = datetime.date.today()
        # Use noon local time to avoid UTC date boundary issues
        local_noon = datetime.datetime(today.year, today.month, today.day, 12, 0, 0,
                                       tzinfo=datetime.timezone.utc)
        today_ts = local_noon.isoformat()
        history = [
            {'state': 'WORK_ASSERT', 'action': 'approve', 'timestamp': today_ts},
        ]
        session_id = today.strftime('%Y%m%d') + '-120000'
        _make_job(self.project_dir, session_id,
                  cfa_state='COMPLETED_WORK', history=history)

        from teaparty.bridge.stats import compute_stats
        stats = compute_stats(teaparty_home='', projects_dir=self._tmpdir)

        daily_tasks = [d['tasks'] for d in stats['daily']]
        self.assertGreater(sum(daily_tasks), 0,
                           'Daily tasks chart should have non-zero entries')


def _make_registry(teaparty_home: str, project_name: str,
                   project_path: str) -> None:
    """Create a minimal teaparty.yaml registry pointing at a project."""
    mgmt_dir = os.path.join(teaparty_home, 'management')
    os.makedirs(mgmt_dir, exist_ok=True)
    config = {
        'name': 'Test Team',
        'projects': [{'name': project_name, 'path': project_path}],
    }
    with open(os.path.join(mgmt_dir, 'teaparty.yaml'), 'w') as f:
        yaml.dump(config, f)


class TestRegistryModeStats(unittest.TestCase):
    """SC9: Registry mode (teaparty_home) discovers jobs and computes stats."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self._tmpdir, 'myproject')
        # Registry requires .git and .teaparty markers
        os.makedirs(os.path.join(self.project_dir, '.git'))
        os.makedirs(os.path.join(self.project_dir, '.teaparty'))
        self.teaparty_home = os.path.join(self._tmpdir, 'tp_home')
        _make_registry(self.teaparty_home, 'TestProject', self.project_dir)

    def test_registry_mode_finds_jobs(self):
        """compute_stats in registry mode discovers jobs via teaparty.yaml."""
        _make_job(self.project_dir, '20260401-120000',
                  cfa_state='COMPLETED_WORK')
        _make_job(self.project_dir, '20260402-120000',
                  cfa_state='WITHDRAWN')

        from teaparty.bridge.stats import compute_stats
        stats = compute_stats(teaparty_home=self.teaparty_home)

        self.assertEqual(stats['summary']['jobs_done'], 1)
        self.assertEqual(stats['summary']['withdrawals'], 1)

    def test_registry_mode_escalations_historical(self):
        """With intent/planning phases running skills that handle dialog
        internally, no state-machine ESCALATE states remain — the
        registry-mode escalation counter mirrors that at zero."""
        _make_job(self.project_dir, '20260401-120000',
                  cfa_state='COMPLETED_WORK', history=[])

        from teaparty.bridge.stats import compute_stats
        stats = compute_stats(teaparty_home=self.teaparty_home)

        self.assertEqual(stats['summary']['escalations'], 0)

    def test_phase_escalations_consistent_with_summary(self):
        """phase_escalations chart counts match the summary escalation total
        (both zero now that intent/planning dialog runs inside skills)."""
        _make_job(self.project_dir, '20260401-120000',
                  cfa_state='COMPLETED_WORK', history=[])

        from teaparty.bridge.stats import compute_stats
        stats = compute_stats(teaparty_home=self.teaparty_home)

        chart_total = sum(e['count'] for e in stats['phase_escalations'])
        self.assertEqual(stats['summary']['escalations'], chart_total)
        self.assertEqual(chart_total, 0)
