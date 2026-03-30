"""Dashboard statistics, item builders, and display utilities.

Pure computation over state objects — no Textual dependencies.
Extracted from the retired TUI for bridge and test compatibility.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from orchestrator.navigation import DashboardLevel, NavigationContext


@dataclass
class CardItem:
    """A single row in a content card."""
    icon: str = ''
    label: str = ''
    detail: str = ''
    data: object = None  # arbitrary payload for click handling


_TERMINAL_STATES = frozenset({'COMPLETED_WORK', 'WITHDRAWN'})


# ── Display helpers ──────────────────────────────────────────────────────────

def _human_age(seconds: int) -> str:
    if seconds < 0:
        return '\u2014'
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    return f'{seconds // 3600}h{seconds % 3600 // 60}m'


def _status_icon(status: str, needs_input: bool = False, is_orphaned: bool = False) -> str:
    if is_orphaned:
        return '\u26a0'
    if needs_input:
        return '\u23f3'
    if status == 'active':
        return '\u25b6'
    if status == 'complete':
        return '\u2713'
    if status == 'failed':
        return '\u2717'
    return ' '


def _state_display(phase: str, state: str) -> str:
    if not phase and not state:
        return '\u2014'
    if state in ('COMPLETED_WORK', 'WITHDRAWN'):
        return state
    if phase:
        return f'{phase}/{state}'
    return state


def _colored_state(session) -> str:
    """Return the CFA state with color markup for a session."""
    state_text = _state_display(session.cfa_phase, session.cfa_state)
    if session.needs_input:
        return f'[dim red]{state_text}[/dim red]'
    if session.cfa_state == 'COMPLETED_WORK':
        return f'[green]{state_text}[/green]'
    if session.cfa_state == 'WITHDRAWN':
        return f'[dim]{state_text}[/dim]'
    return state_text


def _colored_dispatch_state(dispatch) -> str:
    """Return the CFA state with color markup for a dispatch."""
    state_text = _state_display(dispatch.cfa_phase, dispatch.cfa_state)
    if dispatch.cfa_state in _TERMINAL_STATES:
        if dispatch.cfa_state == 'COMPLETED_WORK':
            return f'[green]{state_text}[/green]  {dispatch.team or "?"}'
        return f'[dim]{state_text}[/dim]  {dispatch.team or "?"}'
    if dispatch.status == 'active':
        return f'{state_text}  {dispatch.team or "?"}  {_human_age(dispatch.stream_age_seconds)}'
    return f'[dim]{state_text}[/dim]  {dispatch.team or "?"}'


def _heartbeat_icon(status: str) -> str:
    """Return a visual indicator for heartbeat three-state status.

    Issue #254: alive (green pulse), stale (yellow), dead (dim).
    """
    if status == 'alive':
        return '[green]\u25cf[/green]'
    if status == 'stale':
        return '[yellow]\u25cb[/yellow]'
    return '[dim]\u2022[/dim]'


# ── Pre-seeded messages for "+ New" buttons ──────────────────────────────────

# Cards handled by existing screens (not pre-seeded)
_NON_PRESEED_CARDS = frozenset({'sessions'})

# Generic (management-level) messages per card type
_GENERIC_MESSAGES: dict[str, str] = {
    'agents': 'I would like to create a new agent',
    'skills': 'I would like to create a new skill',
    'hooks': 'I would like to create a new hook',
    'scheduled_tasks': 'I would like to create a new scheduled task',
    'workgroups': 'I would like to create a new shared workgroup',
    'jobs': 'I would like to create a new job',
    'projects': 'I would like to create a new project',
}

# Project-scoped message templates (format with project=slug)
_PROJECT_MESSAGES: dict[str, str] = {
    'agents': 'I would like to add a new agent to the {project} project',
    'skills': 'I would like to create a new skill for the {project} project',
    'hooks': 'I would like to create a new hook for the {project} project',
    'scheduled_tasks': 'I would like to create a new scheduled task for the {project} project',
    'workgroups': 'I would like to create a new workgroup in the {project} project',
    'jobs': 'I would like to create a new job in the {project} project',
}

# Workgroup-scoped message templates (format with workgroup=id)
_WORKGROUP_MESSAGES: dict[str, str] = {
    'agents': 'I would like to add a new agent to the {workgroup} workgroup',
    'skills': 'I would like to create a new skill for the {workgroup} workgroup',
}


def pre_seeded_message(card_name: str, nav: NavigationContext) -> str | None:
    """Return the pre-seeded message for a "+ New" button click.

    Returns None for card types handled by dedicated screens (sessions,
    projects, jobs). For all others, returns a context-aware message
    following the spec table in creating-things.md.
    """
    if card_name in _NON_PRESEED_CARDS:
        return None

    # Workgroup level — most specific scope
    if nav.level == DashboardLevel.WORKGROUP and nav.workgroup_id:
        template = _WORKGROUP_MESSAGES.get(card_name)
        if template:
            return template.format(workgroup=nav.workgroup_id)

    # Project level
    if nav.project_slug and nav.level in (DashboardLevel.PROJECT, DashboardLevel.WORKGROUP):
        template = _PROJECT_MESSAGES.get(card_name)
        if template:
            return template.format(project=nav.project_slug)

    # Management level — generic
    return _GENERIC_MESSAGES.get(card_name)


# ── Item builders ────────────────────────────────────────────────────────────

def _build_project_items(projects: list) -> list[CardItem]:
    """Build CardItems for the PROJECTS card on the management dashboard.

    Issue #254: Shows numeric escalation badge count instead of boolean indicator.
    """
    items = []
    for proj in projects:
        # Sum escalation_count across all sessions (includes dispatch subtree)
        escalation_total = sum(s.escalation_count for s in proj.sessions)
        badge = f' \u23f3 {escalation_total}' if escalation_total > 0 else ''
        items.append(CardItem(
            icon='\u25b6' if proj.active_count > 0 else '\u2713',
            label=proj.slug,
            detail=f'{proj.active_count} active / {len(proj.sessions)} total{badge}',
            data={'project': proj.slug},
        ))
    return items


def _build_escalation_items(
    tagged_sessions: list[tuple[str, object]],
) -> list[CardItem]:
    """Build CardItems for the ESCALATIONS card from a set of sessions.

    Issue #254: Collects all escalation items (session-level and dispatch-level)
    across the subtree. Each item is a clickable pointer to the relevant chat.
    """
    items = []
    for slug, s in tagged_sessions:
        # Session-level escalation
        if s.needs_input:
            label = f'{slug}/{s.session_id}' if slug else s.session_id
            items.append(CardItem(
                icon='\u23f3',
                label=label,
                detail=f'[dim red]{_state_display(s.cfa_phase, s.cfa_state)}[/dim red]',
                data={'session_id': s.session_id, 'project': slug},
            ))
        # Dispatch-level escalations
        for d in (s.dispatches or []):
            if d.needs_input:
                name = d.worktree_name
                if '--' in name:
                    name = name.split('--', 1)[1][:25]
                elif not name:
                    name = d.team or '?'
                label = f'{slug}/{s.session_id}/{name}' if slug else f'{s.session_id}/{name}'
                items.append(CardItem(
                    icon='\u23f3',
                    label=label,
                    detail=f'[dim red]{_state_display(d.cfa_phase, d.cfa_state)}[/dim red]  {d.team or "?"}',
                    data={'session_id': s.session_id, 'dispatch': d, 'project': slug},
                ))
    return items


def _build_session_items(
    tagged_sessions: list[tuple[str, object]],
    include_project: bool = False,
    hide_done: bool = False,
) -> list[CardItem]:
    """Build sorted, color-coded CardItems from (project_slug, session) pairs.

    Three groups, each sorted newest first:
    1. Escalations (needs_input)
    2. Active (non-terminal, non-escalation)
    3. Terminal (COMPLETED_WORK, WITHDRAWN) — omitted if hide_done
    """
    escalations = []
    active = []
    terminal = []
    for slug, s in tagged_sessions:
        if s.needs_input:
            escalations.append((slug, s))
        elif s.cfa_state in _TERMINAL_STATES:
            terminal.append((slug, s))
        else:
            active.append((slug, s))
    escalations.sort(key=lambda t: t[1].session_id, reverse=True)
    active.sort(key=lambda t: t[1].session_id, reverse=True)
    terminal.sort(key=lambda t: t[1].session_id, reverse=True)

    combined = escalations + active
    if not hide_done:
        combined += terminal

    items = []
    for slug, s in combined:
        icon = _status_icon(s.status, s.needs_input, getattr(s, 'is_orphaned', False))
        label = f'{slug}/{s.session_id}' if include_project and slug else s.session_id
        hb = ''
        hb_status = getattr(s, 'heartbeat_status', '')
        if hb_status and s.status == 'active':
            hb = f' {_heartbeat_icon(hb_status)}'
        detail = f'{_colored_state(s)}  {_human_age(s.duration_seconds)}{hb}'
        data = {'session_id': s.session_id}
        if slug:
            data['project'] = slug
        items.append(CardItem(icon=icon, label=label, detail=detail, data=data))
    return items


def filter_sessions_for_workgroup(
    sessions: list,
    workgroup_name: str,
) -> list:
    """Return sessions that have at least one dispatch from this workgroup's team.

    Matching is case-insensitive: workgroup name 'Coding' matches dispatch team 'coding'.
    """
    team = workgroup_name.lower()
    return [s for s in sessions if any(d.team.lower() == team for d in (s.dispatches or []))]


def _build_workgroup_escalation_items(
    sessions: list,
    workgroup_name: str,
) -> list[CardItem]:
    """Build escalation items scoped to a workgroup's team."""
    team = workgroup_name.lower()
    items: list[CardItem] = []
    for s in sessions:
        if s.needs_input:
            items.append(CardItem(
                icon='\u23f3',
                label=s.session_id,
                detail=f'[dim red]{_state_display(s.cfa_phase, s.cfa_state)}[/dim red]',
                data={'session_id': s.session_id},
            ))
        for d in (s.dispatches or []):
            if d.needs_input and d.team.lower() == team:
                name = d.worktree_name
                if '--' in name:
                    name = name.split('--', 1)[1][:25]
                elif not name:
                    name = d.team or '?'
                items.append(CardItem(
                    icon='\u23f3',
                    label=f'{s.session_id}/{name}',
                    detail=f'[dim red]{_state_display(d.cfa_phase, d.cfa_state)}[/dim red]  {d.team or "?"}',
                    data={'session_id': s.session_id, 'dispatch': d},
                ))
    return items


def build_active_task_items(
    sessions: list,
    workgroup_name: str,
) -> list[CardItem]:
    """Build CardItems for active dispatches belonging to a workgroup's team."""
    team = workgroup_name.lower()
    items: list[CardItem] = []
    for s in sessions:
        for d in (s.dispatches or []):
            if d.team.lower() == team and d.status == 'active':
                name = d.worktree_name
                if '--' in name:
                    name = name.split('--', 1)[1][:25]
                elif not name:
                    name = d.team or '?'
                hb = f' {_heartbeat_icon(d.heartbeat_status)}' if d.heartbeat_status else ''
                job_tag = f'[dim]{s.session_id}[/dim]  ' if s.session_id else ''
                items.append(CardItem(
                    icon='\u25b6',
                    label=name,
                    detail=f'{job_tag}{_state_display(d.cfa_phase, d.cfa_state)}  {_human_age(d.stream_age_seconds)}{hb}',
                    data={'session_id': s.session_id, 'dispatch': d},
                ))
    return items


def build_skill_items(skills: list[str]) -> list[CardItem]:
    """Build CardItems for a list of skill names."""
    return [CardItem(icon='\u2699', label=name, detail='', data={'skill': name}) for name in skills]


def _build_scheduled_task_items(scheduled: list) -> list[CardItem]:
    """Build CardItems for a list of ScheduledTask objects."""
    items: list[CardItem] = []
    for st in scheduled:
        icon = '\u25b6' if st.enabled else '[dim]\u23f8[/dim]'
        detail = f'{st.schedule}  {st.skill}'
        if st.args:
            detail += f' {st.args}'
        items.append(CardItem(icon=icon, label=st.name, detail=detail, data={'scheduled_task': st.name}))
    return items


def _build_hook_items(hooks: list[dict]) -> list[CardItem]:
    """Build CardItems for a list of hook dicts."""
    items: list[CardItem] = []
    for hook in hooks:
        event = hook.get('event', '?')
        matcher = hook.get('matcher', '')
        handler = hook.get('handler', hook.get('command', '?'))
        detail = f'{matcher}  {handler}' if matcher else str(handler)
        items.append(CardItem(icon='\u26a1', label=event, detail=detail, data=hook))
    return items


# ── Stat helpers ─────────────────────────────────────────────────────────────

def compute_workgroup_stats(
    sessions: list,
    workgroup_name: str,
) -> dict[str, int]:
    """Compute summary stats for a workgroup from its filtered sessions."""
    team = workgroup_name.lower()
    active_tasks = 0
    complete_tasks = 0
    escalations = 0
    for s in sessions:
        for d in (s.dispatches or []):
            if d.team.lower() == team:
                if d.status == 'active':
                    active_tasks += 1
                elif d.status == 'complete':
                    complete_tasks += 1
                if d.needs_input:
                    escalations += 1
        if s.needs_input:
            escalations += 1
    return {
        'sessions': len(sessions),
        'active_tasks': active_tasks,
        'complete_tasks': complete_tasks,
        'escalations': escalations,
    }


def format_stat_value(value) -> str:
    """Format a stat value for display. None → '—' (em dash)."""
    if value is None:
        return '\u2014'
    return str(value)


def format_stats_labels(stats: list[tuple[str, str]]) -> str:
    """Single-line labels row for the stats bar (no newlines)."""
    return '  '.join(f'[dim]{k:>{max(len(k), len(v))}}[/dim]' for k, v in stats)


def format_stats_values(stats: list[tuple[str, str]]) -> str:
    """Single-line values row for the stats bar (no newlines)."""
    return '  '.join(f'[bold]{v:>{max(len(k), len(v))}}[/bold]' for k, v in stats)


def _uptime_str() -> str:
    """Human-readable uptime from system boot time."""
    from orchestrator.state_reader import _get_cached_boot_time
    import time as _time
    boot = _get_cached_boot_time()
    if boot is None:
        return '\u2014'
    elapsed = int(_time.time() - boot)
    return _human_age(elapsed)


def _proxy_stats(project_paths: list[str]) -> tuple:
    """Query proxy_memory.db for accuracy and chunk count across projects.

    Returns (accuracy_str | None, chunk_count | None).
    """
    import sqlite3
    total_correct = 0
    total_eligible = 0
    total_chunks = 0
    found_any = False

    for proj_path in project_paths:
        db_path = os.path.join(proj_path, '.proxy-memory.db')
        if not os.path.exists(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path, timeout=1)
            conn.execute('PRAGMA query_only = ON')
        except Exception:
            continue
        try:
            rows = conn.execute(
                'SELECT posterior_correct, posterior_total FROM proxy_accuracy'
            ).fetchall()
            for row in rows:
                total_correct += row[0]
                total_eligible += row[1]
        except Exception:
            pass
        try:
            count = conn.execute(
                'SELECT COUNT(*) FROM proxy_chunks WHERE deleted = 0'
            ).fetchone()
            if count:
                total_chunks += count[0]
        except Exception:
            pass
        found_any = True
        conn.close()

    if not found_any:
        return (None, None)

    accuracy = None
    if total_eligible > 0:
        pct = int(100 * total_correct / total_eligible)
        accuracy = f'{pct}%'

    return (accuracy, total_chunks)


def _aggregate_sessions(sessions: list, project_paths: list[str] | None = None) -> dict:
    """Compute common aggregated stats from a list of sessions."""
    jobs_done = sum(1 for s in sessions if s.cfa_state == 'COMPLETED_WORK')
    tasks_done = sum(
        1 for s in sessions
        for d in (s.dispatches or [])
        if d.status == 'complete'
    )
    active = sum(1 for s in sessions if s.status == 'active')
    one_shots = sum(
        1 for s in sessions
        if s.cfa_state == 'COMPLETED_WORK' and s.backtrack_count == 0
    )
    backtracks = sum(s.backtrack_count for s in sessions)
    withdrawals = sum(1 for s in sessions if s.cfa_state == 'WITHDRAWN')
    escalations = sum(s.escalation_count for s in sessions)

    proxy_accuracy = None
    skills_learned = None
    if project_paths:
        proxy_accuracy, skills_learned = _proxy_stats(project_paths)

    return {
        'jobs_done': jobs_done,
        'tasks_done': tasks_done,
        'active': active,
        'one_shots': one_shots,
        'backtracks': backtracks,
        'withdrawals': withdrawals,
        'escalations': escalations,
        'interventions': None,
        'proxy_accuracy': proxy_accuracy,
        'tokens': None,
        'skills_learned': skills_learned,
    }


def compute_management_stats(projects: list) -> dict:
    """Compute all 12 management dashboard stats from project list."""
    all_sessions = [s for p in projects for s in p.sessions]
    project_paths = [p.path for p in projects]
    stats = _aggregate_sessions(all_sessions, project_paths)
    stats['uptime'] = _uptime_str()
    return stats


def compute_project_stats(sessions: list, project_path: str = '') -> dict:
    """Compute project dashboard stats (same as management minus Uptime)."""
    paths = [project_path] if project_path else []
    return _aggregate_sessions(sessions, paths)


def compute_job_stats(session) -> dict:
    """Compute job dashboard stats: Tasks, Backtracks, Escalations, Tokens, Elapsed."""
    dispatches = session.dispatches or []
    complete_d = sum(1 for d in dispatches if d.status == 'complete')
    return {
        'tasks': f'{complete_d}/{len(dispatches)}',
        'backtracks': session.backtrack_count,
        'escalations': session.escalation_count,
        'tokens': None,
        'elapsed': _human_age(session.duration_seconds),
    }


def compute_task_stats(dispatch) -> dict:
    """Compute task dashboard stats: Tokens, Elapsed."""
    return {
        'tokens': None,
        'elapsed': _human_age(dispatch.stream_age_seconds),
    }


def format_management_stats(projects: list) -> list[tuple[str, str]]:
    """Format management stats as (label, value) pairs for the stats bar."""
    stats = compute_management_stats(projects)
    return [
        ('Jobs Done', format_stat_value(stats['jobs_done'])),
        ('Tasks Done', format_stat_value(stats['tasks_done'])),
        ('Active', format_stat_value(stats['active'])),
        ('One-shots', format_stat_value(stats['one_shots'])),
        ('Backtracks', format_stat_value(stats['backtracks'])),
        ('Withdrawals', format_stat_value(stats['withdrawals'])),
        ('Escalations', format_stat_value(stats['escalations'])),
        ('Interventions', format_stat_value(stats['interventions'])),
        ('Proxy Acc.', format_stat_value(stats['proxy_accuracy'])),
        ('Tokens', format_stat_value(stats['tokens'])),
        ('Skills Learned', format_stat_value(stats['skills_learned'])),
        ('Uptime', format_stat_value(stats['uptime'])),
    ]


def format_project_stats(sessions: list, project_path: str = '') -> list[tuple[str, str]]:
    """Format project stats as (label, value) pairs for the stats bar."""
    stats = compute_project_stats(sessions, project_path)
    return [
        ('Jobs Done', format_stat_value(stats['jobs_done'])),
        ('Tasks Done', format_stat_value(stats['tasks_done'])),
        ('Active', format_stat_value(stats['active'])),
        ('One-shots', format_stat_value(stats['one_shots'])),
        ('Backtracks', format_stat_value(stats['backtracks'])),
        ('Withdrawals', format_stat_value(stats['withdrawals'])),
        ('Escalations', format_stat_value(stats['escalations'])),
        ('Interventions', format_stat_value(stats['interventions'])),
        ('Proxy Acc.', format_stat_value(stats['proxy_accuracy'])),
        ('Tokens', format_stat_value(stats['tokens'])),
        ('Skills Learned', format_stat_value(stats['skills_learned'])),
    ]


def format_job_stats(session) -> list[tuple[str, str]]:
    """Format job stats as (label, value) pairs for the stats bar."""
    stats = compute_job_stats(session)
    return [
        ('Tasks', format_stat_value(stats['tasks'])),
        ('Backtracks', format_stat_value(stats['backtracks'])),
        ('Escalations', format_stat_value(stats['escalations'])),
        ('Tokens', format_stat_value(stats['tokens'])),
        ('Elapsed', format_stat_value(stats['elapsed'])),
    ]


def format_task_stats(dispatch) -> list[tuple[str, str]]:
    """Format task stats as (label, value) pairs for the stats bar."""
    stats = compute_task_stats(dispatch)
    return [
        ('Tokens', format_stat_value(stats['tokens'])),
        ('Elapsed', format_stat_value(stats['elapsed'])),
    ]
