"""Navigation model for hierarchical dashboard drill-down.

Defines the five dashboard levels, navigation context tracking,
breadcrumb generation, and per-level card definitions.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class DashboardLevel(Enum):
    """The five hierarchical dashboard levels."""
    MANAGEMENT = 'management'
    PROJECT = 'project'
    WORKGROUP = 'workgroup'
    JOB = 'job'
    TASK = 'task'


# Ordered from root to leaf for breadcrumb generation
_LEVEL_ORDER = [
    DashboardLevel.MANAGEMENT,
    DashboardLevel.PROJECT,
    DashboardLevel.WORKGROUP,
    DashboardLevel.JOB,
    DashboardLevel.TASK,
]


@dataclass(frozen=True)
class NavigationContext:
    """Tracks the current position in the dashboard hierarchy.

    Each field accumulates as you drill deeper. drill_up() clears
    fields below the target level.
    """
    level: DashboardLevel
    project_slug: str = ''
    workgroup_id: str = ''
    job_id: str = ''
    task_id: str = ''

    def drill_down(self, target: DashboardLevel, **kwargs) -> NavigationContext:
        """Navigate deeper, adding entity context."""
        updates = dict(level=target)
        updates['project_slug'] = kwargs.get('project_slug', self.project_slug)
        updates['workgroup_id'] = kwargs.get('workgroup_id', self.workgroup_id)
        updates['job_id'] = kwargs.get('job_id', self.job_id)
        updates['task_id'] = kwargs.get('task_id', self.task_id)
        return replace(self, **updates)

    def drill_up(self, target: DashboardLevel) -> NavigationContext:
        """Navigate to an ancestor level, clearing deeper context."""
        target_idx = _LEVEL_ORDER.index(target)
        updates: dict = dict(level=target)
        # Clear fields for levels deeper than target
        if target_idx < _LEVEL_ORDER.index(DashboardLevel.PROJECT):
            updates['project_slug'] = ''
        if target_idx < _LEVEL_ORDER.index(DashboardLevel.WORKGROUP):
            updates['workgroup_id'] = ''
        if target_idx < _LEVEL_ORDER.index(DashboardLevel.JOB):
            updates['job_id'] = ''
        if target_idx < _LEVEL_ORDER.index(DashboardLevel.TASK):
            updates['task_id'] = ''
        return replace(self, **updates)


@dataclass
class Breadcrumb:
    """A single breadcrumb in the navigation trail."""
    label: str
    level: DashboardLevel
    nav_context: NavigationContext
    clickable: bool = True


def breadcrumbs_for_level(ctx: NavigationContext) -> list[Breadcrumb]:
    """Generate breadcrumbs for the current navigation context.

    Returns a list from root (Management) to current level.
    All crumbs except the last are clickable.
    """
    crumbs: list[Breadcrumb] = []

    # Management (always present)
    mgmt_ctx = NavigationContext(level=DashboardLevel.MANAGEMENT)
    crumbs.append(Breadcrumb(
        label='TeaParty',
        level=DashboardLevel.MANAGEMENT,
        nav_context=mgmt_ctx,
    ))
    if ctx.level == DashboardLevel.MANAGEMENT:
        crumbs[-1].clickable = False
        return crumbs

    # Project
    if ctx.project_slug:
        proj_ctx = NavigationContext(
            level=DashboardLevel.PROJECT,
            project_slug=ctx.project_slug,
        )
        crumbs.append(Breadcrumb(
            label=ctx.project_slug,
            level=DashboardLevel.PROJECT,
            nav_context=proj_ctx,
        ))
    if ctx.level == DashboardLevel.PROJECT:
        crumbs[-1].clickable = False
        return crumbs

    # Workgroup (only if navigating through a workgroup)
    if ctx.workgroup_id:
        wg_ctx = NavigationContext(
            level=DashboardLevel.WORKGROUP,
            project_slug=ctx.project_slug,
            workgroup_id=ctx.workgroup_id,
        )
        crumbs.append(Breadcrumb(
            label=ctx.workgroup_id,
            level=DashboardLevel.WORKGROUP,
            nav_context=wg_ctx,
        ))
    if ctx.level == DashboardLevel.WORKGROUP:
        crumbs[-1].clickable = False
        return crumbs

    # Job
    if ctx.job_id:
        job_ctx = NavigationContext(
            level=DashboardLevel.JOB,
            project_slug=ctx.project_slug,
            workgroup_id=ctx.workgroup_id,
            job_id=ctx.job_id,
        )
        crumbs.append(Breadcrumb(
            label=ctx.job_id,
            level=DashboardLevel.JOB,
            nav_context=job_ctx,
        ))
    if ctx.level == DashboardLevel.JOB:
        crumbs[-1].clickable = False
        return crumbs

    # Task
    if ctx.task_id:
        task_ctx = NavigationContext(
            level=DashboardLevel.TASK,
            project_slug=ctx.project_slug,
            workgroup_id=ctx.workgroup_id,
            job_id=ctx.job_id,
            task_id=ctx.task_id,
        )
        crumbs.append(Breadcrumb(
            label=ctx.task_id,
            level=DashboardLevel.TASK,
            nav_context=task_ctx,
        ))
    if ctx.level == DashboardLevel.TASK:
        crumbs[-1].clickable = False

    return crumbs


# ── Card definitions per level ──

@dataclass
class CardDef:
    """Definition of a content card at a dashboard level."""
    name: str         # internal key (e.g. 'projects', 'jobs')
    title: str        # display title (e.g. 'PROJECTS', 'JOBS')
    new_button: bool = False    # show "+ New" button
    filter_button: bool = False  # show "Hide Done / Show All" toggle


_CARD_DEFS: dict[DashboardLevel, list[CardDef]] = {
    DashboardLevel.MANAGEMENT: [
        CardDef('sessions', 'SESSIONS', new_button=True, filter_button=True),
        CardDef('projects', 'PROJECTS', new_button=True),
        CardDef('workgroups', 'WORKGROUPS', new_button=True),
        CardDef('humans', 'HUMANS'),
        CardDef('agents', 'AGENTS', new_button=True),
        CardDef('skills', 'SKILLS', new_button=True),
        CardDef('scheduled_tasks', 'SCHEDULED TASKS', new_button=True),
        CardDef('hooks', 'HOOKS', new_button=True),
    ],
    DashboardLevel.PROJECT: [
        CardDef('sessions', 'SESSIONS', new_button=True, filter_button=True),
        CardDef('jobs', 'JOBS', new_button=True, filter_button=True),
        CardDef('workgroups', 'WORKGROUPS', new_button=True),
        CardDef('agents', 'AGENTS', new_button=True),
        CardDef('skills', 'SKILLS', new_button=True),
        CardDef('scheduled_tasks', 'SCHEDULED TASKS', new_button=True),
        CardDef('hooks', 'HOOKS', new_button=True),
    ],
    DashboardLevel.WORKGROUP: [
        CardDef('escalations', 'ESCALATIONS'),
        CardDef('sessions', 'SESSIONS', new_button=True),
        CardDef('active_tasks', 'ACTIVE TASKS'),
        CardDef('agents', 'AGENTS', new_button=True),
        CardDef('skills', 'SKILLS', new_button=True),
    ],
    DashboardLevel.JOB: [
        CardDef('sessions', 'SESSIONS'),
        CardDef('tasks', 'TASKS'),
        CardDef('artifacts', 'ARTIFACTS'),
    ],
    DashboardLevel.TASK: [
        CardDef('artifacts', 'ARTIFACTS'),
        CardDef('todo_list', 'TODO LIST'),
    ],
}


def cards_for_level(level: DashboardLevel) -> list[str]:
    """Return the card names for a dashboard level."""
    return [c.name for c in _CARD_DEFS[level]]


def card_defs_for_level(level: DashboardLevel) -> list[CardDef]:
    """Return full card definitions for a dashboard level."""
    return list(_CARD_DEFS[level])
