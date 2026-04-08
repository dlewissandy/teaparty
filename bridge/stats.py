"""Bridge stats — computes org-wide metrics for the GET /api/stats endpoint.

Derives all data from existing session state files, cost sidecars, and skill
directories.  No new data collection is required.

Issue #304.
"""
from __future__ import annotations

import datetime
import json
import os


_TERMINAL_STATES = frozenset({'COMPLETED_WORK', 'WITHDRAWN'})

# States where the agent escalated to a human (questions and escalations,
# not approval gates which are scheduled checkpoints).
_ESCALATION_STATES = frozenset({
    'INTENT_ESCALATE', 'INTENT_QUESTION',
    'PLANNING_ESCALATE', 'PLANNING_QUESTION',
    'TASK_ESCALATE', 'TASK_QUESTION',
})


def _day_label(dt: datetime.date) -> str:
    """Return 'Mon D' label for a date (e.g. 'Mar 5', 'Mar 29')."""
    # %-d strips the leading zero on POSIX (macOS / Linux).
    return dt.strftime('%b %-d')


def _last_7_days() -> list[str]:
    """Return 7 date labels oldest-first, ending today."""
    today = datetime.date.today()
    return [_day_label(today - datetime.timedelta(days=i)) for i in range(6, -1, -1)]


def _mtime_day_label(path: str, day_labels: list[str]) -> str | None:
    """Return the day label for a file's mtime if it falls within the window."""
    try:
        mtime = os.path.getmtime(path)
        label = _day_label(datetime.date.fromtimestamp(mtime))
        return label if label in day_labels else None
    except OSError:
        return None


def _count_skills(project_dirs: list[str]) -> int:
    """Count .md skill files across all project skill directories.

    Counts *.md files in per-project directories:
      {project_dir}/skills/
      {project_dir}/teams/{team_name}/skills/

    Issue #294: skills are written to per-project directories by
    procedural_learning.py.
    """
    count = 0
    for project_dir in project_dirs:
        # {project_dir}/skills/*.md
        try:
            count += sum(1 for e in os.scandir(os.path.join(project_dir, 'skills'))
                         if e.is_file() and e.name.endswith('.md'))
        except OSError:
            pass

        # {project_dir}/teams/{name}/skills/*.md
        try:
            for team_entry in os.scandir(os.path.join(project_dir, 'teams')):
                if not team_entry.is_dir():
                    continue
                try:
                    count += sum(
                        1 for e in os.scandir(os.path.join(team_entry.path, 'skills'))
                        if e.is_file() and e.name.endswith('.md')
                    )
                except OSError:
                    pass
        except OSError:
            pass

    return count


def _count_completed_tasks(sessions: list) -> int:
    """Count COMPLETED_TASK transitions across all CfA state history files.

    A task completes when the state machine transitions FROM 'TASK_ASSERT'
    via action 'approve'.  This is the canonical history marker for a single
    completed task within a job.
    """
    count = 0
    for session in sessions:
        if not session.infra_dir:
            continue
        cfa_path = os.path.join(session.infra_dir, '.cfa-state.json')
        if not os.path.exists(cfa_path):
            continue
        try:
            with open(cfa_path) as f:
                data = json.load(f)
            for entry in data.get('history', []):
                if entry.get('state') == 'TASK_ASSERT' and entry.get('action') == 'approve':
                    count += 1
        except (OSError, ValueError):
            pass
    return count


def _tasks_by_day(sessions: list, day_labels: list[str]) -> dict[str, int]:
    """Count COMPLETED_TASK transitions (TASK_ASSERT→approve) per day.

    Uses the timestamp recorded in each CfA history entry, matching the
    same transitions counted by _count_completed_tasks() for the summary
    scalar.  This ensures the daily chart and summary use the same unit:
    individual tasks, not jobs.
    """
    counts: dict[str, int] = {}
    for session in sessions:
        if not session.infra_dir:
            continue
        cfa_path = os.path.join(session.infra_dir, '.cfa-state.json')
        if not os.path.exists(cfa_path):
            continue
        try:
            with open(cfa_path) as f:
                data = json.load(f)
            for entry in data.get('history', []):
                if entry.get('state') == 'TASK_ASSERT' and entry.get('action') == 'approve':
                    ts = entry.get('timestamp', '')
                    if not ts:
                        continue
                    try:
                        dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        label = _day_label(dt.date())
                        if label in day_labels:
                            counts[label] = counts.get(label, 0) + 1
                    except (ValueError, AttributeError):
                        pass
        except (OSError, ValueError):
            pass
    return counts


def _cost_by_day(sessions: list, day_labels: list[str]) -> dict[str, float]:
    """Map day label → total USD cost for sessions whose .cost file was last
    modified on that day."""
    totals: dict[str, float] = {}
    for session in sessions:
        if not session.infra_dir:
            continue
        cost_path = os.path.join(session.infra_dir, '.cost')
        day = _mtime_day_label(cost_path, day_labels)
        if not day:
            continue
        try:
            with open(cost_path) as f:
                cost = float(f.read().strip())
            totals[day] = totals.get(day, 0.0) + cost
        except (OSError, ValueError):
            pass
    return totals


def _count_historical_escalations(sessions: list) -> int:
    """Count total escalation events across all session CfA histories.

    An escalation is a transition INTO a state where the agent contacted
    a human (ESCALATE or QUESTION states). This is a historical sum,
    not a point-in-time snapshot.
    """
    count = 0
    for session in sessions:
        if not session.infra_dir:
            continue
        cfa_path = os.path.join(session.infra_dir, '.cfa-state.json')
        if not os.path.exists(cfa_path):
            continue
        try:
            with open(cfa_path) as f:
                data = json.load(f)
            for entry in data.get('history', []):
                if entry.get('state') in _ESCALATION_STATES:
                    count += 1
        except (OSError, ValueError):
            pass
    return count


def _phase_escalations(sessions: list) -> list[dict]:
    """Return list of {phase, count} for sessions currently awaiting human input.

    Note (issue #288): this reflects active escalations only, not historical.
    Phase is taken from the session's current CfA phase.
    """
    counts: dict[str, int] = {}
    for session in sessions:
        if session.needs_input:
            phase = session.cfa_phase or 'unknown'
            counts[phase] = counts.get(phase, 0) + 1
    return [{'phase': phase, 'count': count} for phase, count in sorted(counts.items())]


def compute_stats(teaparty_home: str, projects_dir: str | None = None) -> dict:
    """Compute org-wide statistics from session state files.

    Returns::

        {
            'summary': {
                'jobs_done': int,
                'tasks_done': int,
                'active_jobs': int,
                'backtracks': int,
                'withdrawals': int,
                'escalations': int,
                'skills_learned': int,
                'total_cost_usd': float,
                'proxy_accuracy': None,  # open: issue #281
            },
            'daily': [
                {'date': str, 'tasks': int, 'cost_usd': float, 'proxy_acc': None},
                ...  # 7 entries, oldest first, last entry = today
            ],
            'phase_escalations': [{'phase': str, 'count': int}, ...],
            'limitations': {
                'proxy_accuracy': str,  # note for issue #281
            },
        }
    """
    from orchestrator.state_reader import StateReader
    from orchestrator.config_reader import (
        load_management_team, discover_projects as _discover,
    )

    # repo root: stats.py lives in bridge/ at repo root
    _bridge_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(_bridge_dir)

    from orchestrator.job_store import migrate_legacy_sessions

    if projects_dir is not None:
        # Migrate legacy .sessions/ data before scanning
        for slug in sorted(os.listdir(projects_dir)):
            proj_path = os.path.join(projects_dir, slug)
            if os.path.isdir(proj_path):
                migrate_legacy_sessions(proj_path)
        reader = StateReader(repo_root=repo_root, projects_dir=projects_dir)
        project_dirs = [
            os.path.join(projects_dir, slug)
            for slug in sorted(os.listdir(projects_dir))
            if os.path.isdir(os.path.join(projects_dir, slug))
        ]
    else:
        reader = StateReader(repo_root=repo_root, teaparty_home=teaparty_home)
        # Get project paths for skill counting and migration
        try:
            mgmt_team = load_management_team(teaparty_home=teaparty_home)
            project_dirs = [e['path'] for e in _discover(mgmt_team)]
        except Exception:
            project_dirs = []
        # Migrate legacy .sessions/ data before scanning
        for proj_path in project_dirs:
            migrate_legacy_sessions(proj_path)
    all_projects = reader.reload()

    all_sessions = [s for p in all_projects for s in p.sessions]

    # ── Summary scalars ──────────────────────────────────────────────────────
    jobs_done   = sum(1 for s in all_sessions if s.cfa_state == 'COMPLETED_WORK')
    withdrawals = sum(1 for s in all_sessions if s.cfa_state == 'WITHDRAWN')
    active_jobs = sum(1 for s in all_sessions if s.cfa_state not in _TERMINAL_STATES)
    backtracks  = sum(s.backtrack_count for s in all_sessions)
    total_cost  = sum(s.total_cost_usd for s in all_sessions)
    escalations = _count_historical_escalations(all_sessions)
    tasks_done  = _count_completed_tasks(all_sessions)
    skills      = _count_skills(project_dirs)

    # ── Time series (last 7 days) ────────────────────────────────────────────
    day_labels = _last_7_days()
    tasks_per_day = _tasks_by_day(all_sessions, day_labels)
    cost_per_day  = _cost_by_day(all_sessions, day_labels)

    daily = [
        {
            'date':      label,
            'tasks':     tasks_per_day.get(label, 0),
            'cost_usd':  round(cost_per_day.get(label, 0.0), 4),
            'proxy_acc': None,  # open: issue #281
        }
        for label in day_labels
    ]

    return {
        'summary': {
            'jobs_done':      jobs_done,
            'tasks_done':     tasks_done,
            'active_jobs':    active_jobs,
            'backtracks':     backtracks,
            'withdrawals':    withdrawals,
            'escalations':    escalations,
            'skills_learned': skills,
            'total_cost_usd': round(total_cost, 4),
            'proxy_accuracy': None,
        },
        'daily': daily,
        'phase_escalations': _phase_escalations(all_sessions),
        'limitations': {
            'proxy_accuracy': (
                'Issue #281: source table, time-series schema, and metric definition '
                'are unresolved — proxy accuracy data is not available'
            ),
        },
    }
