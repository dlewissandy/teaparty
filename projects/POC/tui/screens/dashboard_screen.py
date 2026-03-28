"""Unified dashboard screen — one parameterized screen for all five navigation levels.

Layout: breadcrumb bar, stats bar, scrollable two-column card grid.
Cards, stats, and click behavior are determined by the NavigationContext.
"""
from __future__ import annotations

import logging
import os
import subprocess

_log = logging.getLogger(__name__)

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.screen import Screen
from textual.widgets import Footer, Static

from projects.POC.tui.navigation import (
    DashboardLevel,
    NavigationContext,
    card_defs_for_level,
    breadcrumbs_for_level,
)
from projects.POC.tui.widgets.content_card import CardItem, ContentCard


class _BreadcrumbStatic(Static):
    """A clickable breadcrumb that calls screen.action_breadcrumb_click."""

    def __init__(self, content: str, index: int, **kwargs):
        super().__init__(content, **kwargs)
        self._index = index

    def on_click(self) -> None:
        self.screen.action_breadcrumb_click(self._index)


# ── Helpers ──

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


_TERMINAL_STATES = frozenset({'COMPLETED_WORK', 'WITHDRAWN'})


# ── Pre-seeded messages for "+ New" buttons ──

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


def _heartbeat_icon(status: str) -> str:
    """Return a visual indicator for heartbeat three-state status.

    Issue #254: alive (green pulse), stale (yellow), dead (dim).
    """
    if status == 'alive':
        return '[green]\u25cf[/green]'
    if status == 'stale':
        return '[yellow]\u25cb[/yellow]'
    return '[dim]\u2022[/dim]'


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


def build_agent_items(agents: list, search_dirs: list[str] | None = None) -> list[CardItem]:
    """Build CardItems from an agent list.

    Handles both forms:
    - list of strings (management/project level): ['office-manager', 'auditor']
    - list of dicts (workgroup level): [{'name': 'Arch', 'role': 'specialist', 'model': '...'}]

    If search_dirs is provided, attempts to read .claude/agents/{name}.md
    files to enrich the config with model, tools, prompt, etc.
    """
    from projects.POC.tui.screens.agent_config_modal import enrich_agent_config

    items: list[CardItem] = []
    for agent in agents:
        if isinstance(agent, str):
            data = {'name': agent, 'file': f'.claude/agents/{agent}.md'}
            data = enrich_agent_config(data, search_dirs)
            role = data.get('role', '')
            model = data.get('model', '')
            detail_parts = [p for p in [role, model] if p]
            items.append(CardItem(
                icon='●',
                label=agent,
                detail='  '.join(detail_parts),
                data=data,
            ))
        elif isinstance(agent, dict):
            name = agent.get('name', '?')
            data = dict(agent)
            if 'name' not in data:
                data['name'] = name
            data = enrich_agent_config(data, search_dirs)
            role = data.get('role', '')
            model = data.get('model', '')
            detail_parts = [p for p in [role, model] if p]
            items.append(CardItem(
                icon='●',
                label=name,
                detail='  '.join(detail_parts),
                data=data,
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
        # Issue #254: heartbeat indicator on active sessions
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
    """Build escalation items scoped to a workgroup's team.

    Only includes dispatch-level escalations from matching team dispatches,
    plus session-level escalations (which apply to the whole job).
    """
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
                # Show parent job so users know which job each task belongs to
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


# ── Stat helpers (issue #273) ──

def format_stat_value(value) -> str:
    """Format a stat value for display. None → '—' (em dash)."""
    if value is None:
        return '\u2014'
    return str(value)


def _uptime_str() -> str:
    """Human-readable uptime from system boot time."""
    from projects.POC.tui.state_reader import _get_cached_boot_time
    import time as _time
    boot = _get_cached_boot_time()
    if boot is None:
        return '\u2014'
    elapsed = int(_time.time() - boot)
    return _human_age(elapsed)


def _aggregate_sessions(sessions: list) -> dict:
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
    return {
        'jobs_done': jobs_done,
        'tasks_done': tasks_done,
        'active': active,
        'one_shots': one_shots,
        'backtracks': backtracks,
        'withdrawals': withdrawals,
        'escalations': escalations,
        # Optional subsystems — None means unavailable
        'interventions': None,
        'proxy_accuracy': None,
        'tokens': None,
        'skills_learned': None,
    }


def compute_management_stats(projects: list) -> dict:
    """Compute all 12 management dashboard stats from project list."""
    all_sessions = [s for p in projects for s in p.sessions]
    stats = _aggregate_sessions(all_sessions)
    stats['uptime'] = _uptime_str()
    return stats


def compute_project_stats(sessions: list) -> dict:
    """Compute project dashboard stats (same as management minus Uptime)."""
    return _aggregate_sessions(sessions)


def compute_job_stats(session) -> dict:
    """Compute job dashboard stats: Tasks, Backtracks, Escalations, Tokens, Elapsed."""
    dispatches = session.dispatches or []
    complete_d = sum(1 for d in dispatches if d.status == 'complete')
    return {
        'tasks': f'{complete_d}/{len(dispatches)}',
        'backtracks': session.backtrack_count,
        'escalations': session.escalation_count,
        'tokens': None,  # Not yet persisted to disk
        'elapsed': _human_age(session.duration_seconds),
    }


def compute_task_stats(dispatch) -> dict:
    """Compute task dashboard stats: Tokens, Elapsed."""
    return {
        'tokens': None,  # Not yet persisted to disk
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


def format_project_stats(sessions: list) -> list[tuple[str, str]]:
    """Format project stats as (label, value) pairs for the stats bar."""
    stats = compute_project_stats(sessions)
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


# ── Screen ──

class DashboardScreen(Screen):
    """Unified dashboard for all five navigation levels."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
        Binding('r', 'refresh', 'Refresh', show=True),
        Binding('q', 'quit_app', 'Quit', show=True),
        Binding('c', 'open_chat', 'Chat', show=True),
        Binding('f', 'change_folder', 'Folder', show=False),
        Binding('n', 'new_session', 'New Session', show=False),
        Binding('p', 'new_project', 'New Project', show=False),
        Binding('d', 'diagnostics', 'Diagnostics', show=False),
        Binding('x', 'proxy_review', 'Proxy Review', show=False),
    ]

    _LEVEL_TITLES = {
        DashboardLevel.MANAGEMENT: 'Management Dashboard',
        DashboardLevel.PROJECT: 'Project Dashboard',
        DashboardLevel.WORKGROUP: 'Workgroup Dashboard',
        DashboardLevel.JOB: 'Job Dashboard',
        DashboardLevel.TASK: 'Task Dashboard',
    }

    def __init__(self, nav_context: NavigationContext | None = None):
        super().__init__()
        self._nav = nav_context or NavigationContext(level=DashboardLevel.MANAGEMENT)
        self._breadcrumb_contexts: list[NavigationContext] = []
        self._hide_done: dict[str, bool] = {'sessions': True, 'jobs': True}  # default: hide terminal

    def _title_text(self) -> str:
        title = self._LEVEL_TITLES.get(self._nav.level, 'Dashboard')
        # Add context info
        if self._nav.project_slug:
            title += f' \u2014 {self._nav.project_slug}'
        if self._nav.job_id:
            title += f' \u2014 {self._nav.job_id}'
        if self._nav.task_id:
            title += f' \u2014 {self._nav.task_id}'
        return f'[bold]{title}[/bold]'

    def _compose_breadcrumbs(self) -> ComposeResult:
        crumbs = breadcrumbs_for_level(self._nav)
        self._breadcrumb_contexts = []
        widgets = []
        for i, crumb in enumerate(crumbs):
            if i > 0:
                widgets.append(Static(' > ', classes='crumb-sep'))
            if crumb.clickable:
                self._breadcrumb_contexts.append(crumb.nav_context)
                idx = len(self._breadcrumb_contexts) - 1
                w = _BreadcrumbStatic(f'[bold]{crumb.label}[/bold]', index=idx, classes='crumb-link')
                widgets.append(w)
            else:
                widgets.append(Static(f'[dim]{crumb.label}[/dim]', classes='crumb-current'))
        return widgets

    def action_breadcrumb_click(self, index: int) -> None:
        if 0 <= index < len(self._breadcrumb_contexts):
            self._navigate(self._breadcrumb_contexts[index])

    def compose(self) -> ComposeResult:
        yield Static(self._title_text(), id='dash-title')
        yield Horizontal(*self._compose_breadcrumbs(), id='dash-breadcrumbs')
        yield Static('', id='dash-stats')
        card_defs = card_defs_for_level(self._nav.level)
        mid = (len(card_defs) + 1) // 2
        left_defs = card_defs[:mid]
        right_defs = card_defs[mid:]
        yield VerticalScroll(
            Horizontal(
                Vertical(
                    *(ContentCard(d.title, d.name, show_new_button=d.new_button, show_filter_button=d.filter_button)
                      for d in left_defs),
                    id='card-col-left',
                    classes='card-column',
                ),
                Vertical(
                    *(ContentCard(d.title, d.name, show_new_button=d.new_button, show_filter_button=d.filter_button)
                      for d in right_defs),
                    id='card-col-right',
                    classes='card-column',
                ),
                id='card-cols',
                classes='card-columns',
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        # Set initial filter state on cards
        for card_name, active in self._hide_done.items():
            card = self._find_card(card_name)
            if card:
                card.set_filter_active(active)
        self._refresh_data()
        self._update_columns()

    def on_resize(self) -> None:
        self._update_columns()

    def _update_columns(self) -> None:
        try:
            cols = self.query_one('#card-cols')
            if self.size.width < 80:
                cols.add_class('-narrow')
            else:
                cols.remove_class('-narrow')
        except Exception:
            pass

    # ── Data refresh ──

    def _refresh_data(self) -> None:
        reader = self.app.state_reader
        reader.reload()
        level = self._nav.level

        if level == DashboardLevel.MANAGEMENT:
            self._refresh_management(reader)
        elif level == DashboardLevel.PROJECT:
            proj = reader.find_project(self._nav.project_slug)
            self._refresh_project(reader, proj)
        elif level == DashboardLevel.WORKGROUP:
            self._refresh_workgroup()
        elif level == DashboardLevel.JOB:
            session = reader.find_session(self._nav.job_id)
            self._refresh_job(reader, session)
        elif level == DashboardLevel.TASK:
            session = reader.find_session(self._nav.job_id)
            dispatch = self._find_dispatch(session)
            self._refresh_task(reader, session, dispatch)

    def _refresh_management(self, reader) -> None:
        projects = reader.projects
        # Issue #273: full stat set from management-dashboard.md
        self._set_stats(format_management_stats(projects))

        # Escalations — all escalation items across all projects
        tagged = [(proj.slug, s) for proj in projects for s in proj.sessions]
        self._set_card('escalations', _build_escalation_items(tagged))

        # Sessions — escalations first, then rest, newest first
        self._set_card('sessions', _build_session_items(tagged, include_project=True, hide_done=self._hide_done.get('sessions', True)))

        # Projects — Issue #254: numeric badge count
        self._set_card('projects', _build_project_items(projects))

        # Humans — always show the current user
        import getpass
        username = getpass.getuser()
        self._set_card('humans', [
            CardItem(icon='\u263a', label=username, detail='decider'),
        ])

        # Agents — from config_reader if available
        self._set_card('agents', self._load_management_agents())

        # Workgroups — from config_reader if available
        self._set_card('workgroups', self._load_management_workgroups())

    def _refresh_project(self, reader, proj) -> None:
        if not proj:
            return
        # Issue #273: full stat set from project-dashboard.md
        self._set_stats(format_project_stats(proj.sessions))

        # Escalations — all escalation items within this project
        tagged = [('', s) for s in proj.sessions]
        self._set_card('escalations', _build_escalation_items(tagged))

        # Sessions (active only)
        active = [('', s) for s in proj.sessions if s.status == 'active']
        self._set_card('sessions', _build_session_items(active, hide_done=self._hide_done.get('sessions', True)))

        # Jobs (all)
        all_jobs = [('', s) for s in proj.sessions]
        self._set_card('jobs', _build_session_items(all_jobs, hide_done=self._hide_done.get('jobs', True)))

        # Agents — from project config if available
        self._set_card('agents', self._load_project_agents(proj))

        # Workgroups — from project config if available
        self._set_card('workgroups', self._load_project_workgroups(proj))

    def _refresh_workgroup(self) -> None:
        """Refresh the workgroup dashboard — all five cards from config + state."""
        reader = self.app.state_reader
        project_slug = self._nav.project_slug
        wg_id = self._nav.workgroup_id
        if not project_slug or not wg_id:
            return

        proj = reader.find_project(project_slug)
        if not proj:
            return

        # Filter sessions to those with dispatches from this workgroup's team
        wg_sessions = filter_sessions_for_workgroup(proj.sessions, wg_id)

        # Stats
        stats = compute_workgroup_stats(wg_sessions, wg_id)
        self._set_stats([
            ('Sessions', str(stats['sessions'])),
            ('Active', str(stats['active_tasks'])),
            ('Done', str(stats['complete_tasks'])),
            ('Escalations', str(stats['escalations'])),
        ])

        # Escalations — only from this workgroup's team
        self._set_card('escalations', _build_workgroup_escalation_items(wg_sessions, wg_id))

        # Sessions
        tagged = [('', s) for s in wg_sessions]
        self._set_card('sessions', _build_session_items(tagged, hide_done=self._hide_done.get('sessions', True)))

        # Active Tasks
        self._set_card('active_tasks', build_active_task_items(wg_sessions, wg_id))

        # Agents
        self._set_card('agents', self._load_workgroup_agents())

        # Skills
        self._set_card('skills', self._load_workgroup_skills())

    def _refresh_job(self, reader, session) -> None:
        if not session:
            return
        # Issue #273: full stat set from job-dashboard.md
        self._set_stats(format_job_stats(session))

        # Escalations — dispatch-level escalations within this job
        escalation_items = []
        for d in dispatches:
            if d.needs_input:
                name = d.worktree_name
                if '--' in name:
                    name = name.split('--', 1)[1][:25]
                elif not name:
                    name = d.team or '?'
                escalation_items.append(CardItem(
                    icon='\u23f3',
                    label=name,
                    detail=f'[dim red]{_state_display(d.cfa_phase, d.cfa_state)}[/dim red]  {d.team or "?"}',
                    data={'session_id': session.session_id, 'dispatch': d},
                ))
        if session.needs_input:
            escalation_items.insert(0, CardItem(
                icon='\u23f3',
                label=session.session_id,
                detail=f'[dim red]{_state_display(session.cfa_phase, session.cfa_state)}[/dim red]',
                data={'session_id': session.session_id},
            ))
        self._set_card('escalations', escalation_items)

        # Sessions — parent job session + all dispatch (subteam) sessions
        session_items = _build_session_items([('', session)])
        for d in dispatches:
            name = d.worktree_name
            if '--' in name:
                name = name.split('--', 1)[1][:25]
            elif not name:
                name = os.path.basename(d.infra_dir) if d.infra_dir else '?'
            state_text = _state_display(d.cfa_phase, d.cfa_state)
            # Issue #254: heartbeat indicator on active dispatches
            hb = f' {_heartbeat_icon(d.heartbeat_status)}' if d.status == 'active' and d.heartbeat_status else ''
            if d.status == 'active':
                icon = '\u25b6'
                detail = f'{state_text}  {d.team or "?"}  {_human_age(d.stream_age_seconds)}{hb}'
            elif d.status == 'complete':
                icon = '\u2713'
                detail = f'[green]{state_text}[/green]  {d.team or "?"}'
            else:
                icon = '\u2717'
                detail = f'[dim]{state_text}[/dim]  {d.team or "?"}'
            session_items.append(CardItem(
                icon=icon, label=name, detail=detail,
                data={'dispatch': d},
            ))
        self._set_card('sessions', session_items)

        # Tasks — all dispatches with CFA state, same color coding
        task_items = []
        for d in dispatches:
            name = d.worktree_name
            if '--' in name:
                name = name.split('--', 1)[1][:25]
            elif not name:
                name = os.path.basename(d.infra_dir) if d.infra_dir else '?'
            # Issue #254: heartbeat + escalation indicators on task items
            task_icon = _status_icon(d.status, d.needs_input, False)
            hb = f' {_heartbeat_icon(d.heartbeat_status)}' if d.status == 'active' and d.heartbeat_status else ''
            task_items.append(CardItem(
                icon=task_icon,
                label=name,
                detail=f'{_colored_dispatch_state(d)}{hb}',
                data={'dispatch': d},
            ))
        self._set_card('tasks', task_items)

        # Artifacts
        items = []
        for name, label in [('INTENT.md', 'Intent'), ('plan.md', 'Plan'), ('.work-summary.md', 'Work Summary')]:
            path = self._find_doc(session, name)
            if path:
                items.append(CardItem(icon='\u2713', label=label, detail=name, data={'path': path}))
            else:
                items.append(CardItem(icon='\u2591', label=f'[dim]{label}[/dim]'))
        self._set_card('artifacts', items)

    def _refresh_task(self, reader, session, dispatch) -> None:
        if not dispatch:
            return
        # Issue #273: full stat set from task-dashboard.md
        self._set_stats(format_task_stats(dispatch))

        # Escalations — this task's own escalation state
        escalation_items = []
        if dispatch.needs_input:
            name = dispatch.worktree_name or dispatch.team or '?'
            escalation_items.append(CardItem(
                icon='\u23f3',
                label=name,
                detail=f'[dim red]{_state_display(dispatch.cfa_phase, dispatch.cfa_state)}[/dim red]',
                data={'session_id': session.session_id if session else '', 'dispatch': dispatch},
            ))
        self._set_card('escalations', escalation_items)

        # Artifacts (changed files)
        wt = self._dispatch_worktree(dispatch, session)
        items = []
        if wt:
            try:
                result = subprocess.run(
                    ['git', 'diff', '--name-only', 'HEAD'],
                    cwd=wt, capture_output=True, text=True, timeout=5,
                )
                for f in result.stdout.strip().split('\n'):
                    if f:
                        items.append(CardItem(label=f))
            except (subprocess.TimeoutExpired, OSError):
                pass
        self._set_card('artifacts', items)

        # Todo list
        from projects.POC.tui.todo_reader import read_todos_from_streams
        stream_files = self._dispatch_stream_files(dispatch)
        todos = read_todos_from_streams(stream_files)
        items = []
        for todo in todos:
            status = todo.get('status', 'pending')
            icon = '\u2713' if status == 'completed' else '\u2610' if status == 'in_progress' else '\u2591'
            items.append(CardItem(icon=icon, label=todo.get('content', '?')))
        self._set_card('todo_list', items)

    # ── Config-reader integration ──

    def _load_management_agents(self) -> list[CardItem]:
        """Load agent list from teaparty.yaml via config_reader."""
        try:
            from projects.POC.orchestrator.config_reader import load_management_team, default_teaparty_home
            team = load_management_team()
            home = default_teaparty_home()
            return build_agent_items(team.agents, search_dirs=[home])
        except Exception:
            _log.warning('Failed to load management agents', exc_info=True)
            return []

    def _load_project_agents(self, proj) -> list[CardItem]:
        """Load agent list from project.yaml via config_reader."""
        try:
            from projects.POC.orchestrator.config_reader import load_project_team
            pt = load_project_team(proj.path)
            return build_agent_items(pt.agents, search_dirs=[proj.path])
        except Exception:
            _log.warning('Failed to load project agents for %s', proj.slug, exc_info=True)
            return []

    def _load_workgroup_agents(self) -> list[CardItem]:
        """Load agent list from workgroup YAML via config_reader.

        Resolves the workgroup from the nav context's workgroup_id.
        Workgroup agents are dicts with name, role, model.
        """
        try:
            from projects.POC.orchestrator.config_reader import (
                load_project_team,
                resolve_workgroups,
            )
            project_slug = self._nav.project_slug
            wg_id = self._nav.workgroup_id
            if not project_slug or not wg_id:
                return []
            reader = self.app.state_reader
            proj = reader.find_project(project_slug)
            if not proj:
                return []
            pt = load_project_team(proj.path)
            workgroups = resolve_workgroups(pt.workgroups, proj.path)
            for wg in workgroups:
                if wg.name == wg_id:
                    return build_agent_items(wg.agents, search_dirs=[proj.path])
            return []
        except Exception:
            _log.warning('Failed to load workgroup agents for %s/%s',
                         self._nav.project_slug, self._nav.workgroup_id,
                         exc_info=True)
            return []

    def _load_workgroup_skills(self) -> list[CardItem]:
        """Load skill list from workgroup YAML via config_reader."""
        try:
            from projects.POC.orchestrator.config_reader import (
                load_project_team,
                resolve_workgroups,
            )
            project_slug = self._nav.project_slug
            wg_id = self._nav.workgroup_id
            if not project_slug or not wg_id:
                return []
            reader = self.app.state_reader
            proj = reader.find_project(project_slug)
            if not proj:
                return []
            pt = load_project_team(proj.path)
            workgroups = resolve_workgroups(pt.workgroups, proj.path)
            for wg in workgroups:
                if wg.name == wg_id:
                    return build_skill_items(wg.skills)
            return []
        except Exception:
            _log.warning('Failed to load workgroup skills for %s/%s',
                         self._nav.project_slug, self._nav.workgroup_id,
                         exc_info=True)
            return []

    def _load_management_workgroups(self) -> list[CardItem]:
        """Load workgroup list from teaparty.yaml via config_reader."""
        try:
            from projects.POC.orchestrator.config_reader import (
                load_management_team,
                load_management_workgroups,
            )
            team = load_management_team()
            workgroups = load_management_workgroups(team)
            items: list[CardItem] = []
            for wg in workgroups:
                agent_count = len(wg.agents)
                detail = f'{agent_count} agent{"s" if agent_count != 1 else ""}'
                if wg.lead:
                    detail = f'{wg.lead}  {detail}'
                items.append(CardItem(
                    icon='\u25cb',
                    label=wg.name,
                    detail=detail,
                    data={'workgroup_id': wg.name},
                ))
            return items
        except Exception:
            _log.warning('Failed to load management workgroups', exc_info=True)
            return []

    def _load_project_workgroups(self, proj) -> list[CardItem]:
        """Load workgroup list from project.yaml via config_reader."""
        try:
            from projects.POC.orchestrator.config_reader import (
                load_project_team,
                resolve_workgroups,
            )
            pt = load_project_team(proj.path)
            workgroups = resolve_workgroups(pt.workgroups, proj.path)
            items: list[CardItem] = []
            for wg in workgroups:
                agent_count = len(wg.agents)
                detail = f'{agent_count} agent{"s" if agent_count != 1 else ""}'
                if wg.lead:
                    detail = f'{wg.lead}  {detail}'
                items.append(CardItem(
                    icon='\u25cb',
                    label=wg.name,
                    detail=detail,
                    data={'workgroup_id': wg.name},
                ))
            return items
        except Exception:
            _log.warning('Failed to load project workgroups for %s', proj.slug, exc_info=True)
            return []

    # ── Card/stats helpers ──

    def _set_stats(self, stats: list[tuple[str, str]]) -> None:
        parts = [f'[bold]{k}:[/bold] {v}' for k, v in stats]
        try:
            self.query_one('#dash-stats', Static).update('  \u2502  '.join(parts))
        except Exception:
            pass

    def _set_card(self, card_name: str, items: list[CardItem]) -> None:
        try:
            for widget in self.query(ContentCard):
                if widget._card_name == card_name:
                    widget.update_items(items)
                    break
        except Exception:
            pass

    # ── Click routing (called directly from item markup via screen.card_click) ──

    def _find_card(self, card_name: str) -> ContentCard | None:
        for widget in self.query(ContentCard):
            if widget._card_name == card_name:
                return widget
        return None

    def action_card_click(self, card_name: str, index: int) -> None:
        """Handle click on a card item. Called via [@click=screen.card_click(...)]."""
        card = self._find_card(card_name)
        if not card or index < 0 or index >= len(card._items):
            return
        item = card._items[index]
        data = item.data or {}
        level = self._nav.level

        if card_name == 'projects':
            slug = data.get('project', '')
            if slug:
                self._navigate(self._nav.drill_down(DashboardLevel.PROJECT, project_slug=slug))

        elif card_name == 'jobs':
            if level == DashboardLevel.MANAGEMENT:
                project = data.get('project', '')
                sid = data.get('session_id', '')
                if project and sid:
                    self._navigate(self._nav.drill_down(
                        DashboardLevel.JOB, project_slug=project, job_id=sid,
                    ))
            else:
                sid = data.get('session_id', '')
                if sid:
                    self._navigate(self._nav.drill_down(DashboardLevel.JOB, job_id=sid))

        elif card_name == 'escalations':
            # Escalation clicks always open the relevant chat (per spec)
            sid = data.get('session_id', '')
            conv = f'session:{sid}' if sid else ''
            open_chat_window(self.app, conversation=conv)

        elif card_name == 'sessions':
            # At job level, dispatch items navigate to task dashboard
            dispatch = data.get('dispatch')
            if dispatch:
                task_id = os.path.basename(dispatch.infra_dir) if dispatch.infra_dir else dispatch.worktree_name
                self._navigate(self._nav.drill_down(DashboardLevel.TASK, task_id=task_id))
            else:
                sid = data.get('session_id', '')
                conv = f'session:{sid}' if sid else ''
                open_chat_window(self.app, conversation=conv)

        elif card_name == 'humans':
            import getpass
            open_chat_window(self.app, ensure_proxy_review=getpass.getuser())

        elif card_name == 'agents':
            from projects.POC.tui.screens.agent_config_modal import AgentConfigModal
            if data:
                self.app.push_screen(AgentConfigModal(data))

        elif card_name == 'workgroups':
            wg_id = data.get('workgroup_id', '')
            if wg_id:
                self._navigate(self._nav.drill_down(DashboardLevel.WORKGROUP, workgroup_id=wg_id))

        elif card_name in ('tasks', 'active_tasks'):
            dispatch = data.get('dispatch')
            if dispatch:
                task_id = os.path.basename(dispatch.infra_dir) if dispatch.infra_dir else dispatch.worktree_name
                self._navigate(self._nav.drill_down(DashboardLevel.TASK, task_id=task_id))

        elif card_name == 'artifacts':
            path = data.get('path', '')
            if path:
                from projects.POC.tui.platform_utils import open_file
                open_file(path)

    def action_card_new(self, card_name: str) -> None:
        """Handle '+ New' click on a card."""
        if card_name == 'sessions':
            self.action_new_session()
        else:
            msg = pre_seeded_message(card_name, self._nav)
            if msg:
                open_chat_window(self.app, conversation='om:new', pre_seed=msg)

    def action_card_filter(self, card_name: str) -> None:
        """Toggle hide/show terminal states on a card."""
        self._hide_done[card_name] = not self._hide_done.get(card_name, False)
        # Update the toggle label
        card = self._find_card(card_name)
        if card:
            card.set_filter_active(self._hide_done[card_name])
        # Re-populate
        self._refresh_data()

    # ── Navigation ──

    def _navigate(self, ctx: NavigationContext) -> None:
        navigate_to(self.app, ctx)

    # ── Actions ──

    def action_go_back(self) -> None:
        if self._nav.level == DashboardLevel.MANAGEMENT:
            self.app.exit()
        else:
            # Navigate to parent level via breadcrumbs
            crumbs = breadcrumbs_for_level(self._nav)
            if len(crumbs) >= 2:
                # Second-to-last crumb is the parent
                parent_ctx = crumbs[-2].nav_context
                self._navigate(parent_ctx)
            else:
                self._navigate(NavigationContext(level=DashboardLevel.MANAGEMENT))

    def action_refresh(self) -> None:
        self._refresh_data()

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_open_chat(self) -> None:
        open_chat_window(self.app)

    def action_new_session(self) -> None:
        from projects.POC.tui.screens.launch import LaunchScreen
        project = self._nav.project_slug
        if not project:
            reader = self.app.state_reader
            project = reader.projects[0].slug if reader.projects else ''
        self.app.push_screen(LaunchScreen(project, workgroup=self._nav.workgroup_id))

    def action_new_project(self) -> None:
        from projects.POC.tui.screens.new_project import NewProjectScreen
        self.app.push_screen(NewProjectScreen())

    def action_diagnostics(self) -> None:
        from projects.POC.tui.screens.diagnostics import DiagnosticsScreen
        self.app.push_screen(DiagnosticsScreen())

    def action_change_folder(self) -> None:
        from projects.POC.tui.screens.dashboard import ChangeProjectDirScreen
        self.app.push_screen(ChangeProjectDirScreen())

    def action_proxy_review(self) -> None:
        import getpass
        open_chat_window(self.app, ensure_proxy_review=getpass.getuser())

    def periodic_refresh(self) -> None:
        self._refresh_data()

    # ── File resolution helpers ──

    def _find_doc(self, session, filename: str) -> str | None:
        if session and session.infra_dir:
            p = os.path.join(session.infra_dir, filename)
            if os.path.exists(p):
                return p
        if session and session.worktree_path and os.path.isdir(session.worktree_path):
            p = os.path.join(session.worktree_path, filename)
            if os.path.exists(p):
                return p
        return None

    def _find_dispatch(self, session) -> object | None:
        if not session:
            return None
        for d in session.dispatches:
            task_id = os.path.basename(d.infra_dir) if d.infra_dir else d.worktree_name
            if task_id == self._nav.task_id:
                return d
        return session.dispatches[0] if session.dispatches else None

    def _dispatch_worktree(self, dispatch, session) -> str | None:
        if not dispatch:
            return None
        if dispatch.worktree_path and os.path.isdir(dispatch.worktree_path):
            return dispatch.worktree_path
        if dispatch.worktree_name and session:
            proj = self.app.state_reader.find_project(session.project)
            if proj:
                wt = os.path.join(proj.path, '.worktrees', dispatch.worktree_name)
                if os.path.isdir(wt):
                    return wt
        return None

    def _dispatch_stream_files(self, dispatch) -> list[str]:
        if not dispatch or not dispatch.infra_dir or not os.path.isdir(dispatch.infra_dir):
            return []
        files = []
        try:
            for name in os.listdir(dispatch.infra_dir):
                if name.endswith('.jsonl'):
                    files.append(os.path.join(dispatch.infra_dir, name))
        except OSError:
            pass
        return files


# ── Module-level helpers (used by app.py and other screens) ──

def navigate_to(app, ctx: NavigationContext) -> None:
    """Navigate the app to the screen for the given NavigationContext.

    Pops all pushed screens, then pushes a fresh DashboardScreen.
    The base screen (Textual's _default) is never touched.
    """
    while len(app.screen_stack) > 2:
        app.pop_screen()
    # Pop the last pushed DashboardScreen if there is one
    if len(app.screen_stack) > 1:
        app.pop_screen()
    # Push the target level
    app.push_screen(DashboardScreen(ctx))


def open_chat_window(app, conversation: str = '', ensure_proxy_review: str = '', pre_seed: str = '') -> None:
    """Spawn the chat UI in a separate terminal window.

    If conversation is given, the chat opens to that specific conversation.
    If pre_seed is given, the chat sends that message into the conversation on open.
    """
    from pathlib import Path
    from projects.POC.tui.platform_utils import open_terminal
    repo_root = str(Path(app.poc_root).parent.parent)
    cmd = ['uv', 'run', 'python', '-m', 'projects.POC.tui.chat_main',
           '--project-dir', app.projects_dir]
    if conversation:
        cmd += ['--conversation', conversation]
    if ensure_proxy_review:
        cmd += ['--ensure-proxy-review', ensure_proxy_review]
    if pre_seed:
        cmd += ['--pre-seed', pre_seed]
    open_terminal(cmd, title='TeaParty Chat', cwd=repo_root)
