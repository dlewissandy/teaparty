"""Configuration tree reader for teaparty.yaml and project.yaml.

Loads the two-level configuration tree:
  Level 1: ~/.teaparty/teaparty.yaml → ManagementTeam
  Level 2: {project}/.teaparty/project.yaml → ProjectTeam
  Workgroups: {level}/.teaparty/workgroups/*.yaml → Workgroup

See docs/proposals/team-configuration/proposal.md for the design.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Human:
    """A human participant with a D-A-I role."""
    name: str
    role: str  # decider | advisor | informed


@dataclass
class ScheduledTask:
    """A skill invocation on a cron schedule."""
    name: str
    schedule: str
    skill: str
    args: str = ''
    enabled: bool = True


@dataclass
class WorkgroupRef:
    """A reference to an org-level shared workgroup (not yet resolved)."""
    ref: str
    status: str = 'active'


@dataclass
class WorkgroupEntry:
    """A project-scoped workgroup definition (points to a config file)."""
    name: str
    config: str
    status: str = 'active'


@dataclass
class Workgroup:
    """A fully loaded workgroup definition."""
    name: str
    description: str = ''
    lead: str = ''
    team_file: str = ''
    agents: list[dict[str, Any]] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    norms: dict[str, list[str]] = field(default_factory=dict)
    stats: dict[str, str] = field(default_factory=dict)


@dataclass
class ManagementTeam:
    """The root management team from ~/.teaparty/teaparty.yaml."""
    name: str
    description: str = ''
    lead: str = ''
    decider: str = ''
    agents: list[str] = field(default_factory=list)
    humans: list[Human] = field(default_factory=list)
    teams: list[dict[str, str]] = field(default_factory=list)
    workgroups: list[WorkgroupEntry] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    scheduled: list[ScheduledTask] = field(default_factory=list)
    norms: dict[str, list[str]] = field(default_factory=dict)
    stats: dict[str, str] = field(default_factory=dict)


@dataclass
class ProjectTeam:
    """A project team from {project}/.teaparty/project.yaml."""
    name: str
    description: str = ''
    lead: str = ''
    decider: str = ''
    agents: list[str] = field(default_factory=list)
    humans: list[Human] = field(default_factory=list)
    workgroups: list[WorkgroupRef | WorkgroupEntry] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    scheduled: list[ScheduledTask] = field(default_factory=list)
    hooks: list[dict[str, str]] = field(default_factory=list)
    norms: dict[str, list[str]] = field(default_factory=dict)
    stats: dict[str, str] = field(default_factory=dict)


# ── Parsers ──────────────────────────────────────────────────────────────────

def _parse_humans(raw: list[dict] | None) -> list[Human]:
    if not raw:
        return []
    return [Human(name=h['name'], role=h['role']) for h in raw]


def _parse_scheduled(raw: list[dict] | None) -> list[ScheduledTask]:
    if not raw:
        return []
    return [
        ScheduledTask(
            name=s['name'],
            schedule=s['schedule'],
            skill=s['skill'],
            args=s.get('args', ''),
            enabled=s.get('enabled', True),
        )
        for s in raw
    ]


def _parse_workgroup_entries(raw: list[dict] | None) -> list[WorkgroupRef | WorkgroupEntry]:
    if not raw:
        return []
    result: list[WorkgroupRef | WorkgroupEntry] = []
    for entry in raw:
        if 'ref' in entry:
            result.append(WorkgroupRef(ref=entry['ref'], status=entry.get('status', 'active')))
        else:
            result.append(WorkgroupEntry(
                name=entry['name'],
                config=entry.get('config', ''),
                status=entry.get('status', 'active'),
            ))
    return result


def _parse_management_workgroups(raw: list[dict] | None) -> list[WorkgroupEntry]:
    if not raw:
        return []
    return [
        WorkgroupEntry(
            name=entry['name'],
            config=entry.get('config', ''),
            status=entry.get('status', 'active'),
        )
        for entry in raw
    ]


def _parse_teams(raw: list[dict] | None) -> list[dict[str, str]]:
    if not raw:
        return []
    return [
        {'name': t['name'], 'path': os.path.expanduser(t['path'])}
        for t in raw
    ]


# ── Loaders ──────────────────────────────────────────────────────────────────

def load_management_team(
    teaparty_home: str = '~/.teaparty',
    config_filename: str = 'teaparty.yaml',
) -> ManagementTeam:
    """Load the management team from teaparty.yaml.

    Args:
        teaparty_home: Path to the .teaparty directory (default ~/.teaparty).
        config_filename: Name of the config file within teaparty_home.
    """
    home = os.path.expanduser(teaparty_home)
    path = os.path.join(home, config_filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f'Management team config not found: {path}')

    with open(path) as f:
        data = yaml.safe_load(f)

    return ManagementTeam(
        name=data['name'],
        description=data.get('description', ''),
        lead=data.get('lead', ''),
        decider=data.get('decider', ''),
        agents=data.get('agents', []),
        humans=_parse_humans(data.get('humans')),
        teams=_parse_teams(data.get('teams')),
        workgroups=_parse_management_workgroups(data.get('workgroups')),
        skills=data.get('skills', []),
        scheduled=_parse_scheduled(data.get('scheduled')),
        norms=data.get('norms', {}),
        stats=data.get('stats', {}),
    )


def load_project_team(
    project_dir: str,
    config_path: str | None = None,
) -> ProjectTeam:
    """Load a project team from {project}/.teaparty/project.yaml.

    Args:
        project_dir: Path to the project root directory.
        config_path: Explicit path to project.yaml (overrides default location).
    """
    if config_path:
        path = config_path
    else:
        path = os.path.join(project_dir, '.teaparty', 'project.yaml')

    if not os.path.exists(path):
        raise FileNotFoundError(f'Project config not found: {path}')

    with open(path) as f:
        data = yaml.safe_load(f)

    return ProjectTeam(
        name=data['name'],
        description=data.get('description', ''),
        lead=data.get('lead', ''),
        decider=data.get('decider', ''),
        agents=data.get('agents', []),
        humans=_parse_humans(data.get('humans')),
        workgroups=_parse_workgroup_entries(data.get('workgroups')),
        skills=data.get('skills', []),
        scheduled=_parse_scheduled(data.get('scheduled')),
        hooks=data.get('hooks', []),
        norms=data.get('norms', {}),
        stats=data.get('stats', {}),
    )


def load_workgroup(path: str) -> Workgroup:
    """Load a workgroup definition from a YAML file.

    Args:
        path: Absolute path to the workgroup YAML file.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f'Workgroup config not found: {path}')

    with open(path) as f:
        data = yaml.safe_load(f)

    return Workgroup(
        name=data['name'],
        description=data.get('description', ''),
        lead=data.get('lead', ''),
        team_file=data.get('team_file', ''),
        agents=data.get('agents', []),
        skills=data.get('skills', []),
        norms=data.get('norms', {}),
        stats=data.get('stats', {}),
    )


# ── Discovery & resolution ──────────────────────────────────────────────────

def discover_projects(team: ManagementTeam) -> list[dict[str, Any]]:
    """Walk teams: entries and check which paths are valid TeaParty projects.

    A directory is a TeaParty project if it contains .git/, .claude/, and
    .teaparty/ (per the design doc). Each returned entry has:
      - name: the team name from teaparty.yaml
      - path: the expanded absolute path
      - valid: True if the path exists and contains required markers

    Returns all entries (including invalid ones) so callers can report
    missing or misconfigured projects.
    """
    required_markers = ['.git', '.claude', '.teaparty']
    result: list[dict[str, Any]] = []
    for entry in team.teams:
        path = entry['path']
        valid = os.path.isdir(path) and all(
            os.path.isdir(os.path.join(path, m)) for m in required_markers
        )
        result.append({'name': entry['name'], 'path': path, 'valid': valid})
    return result


def load_management_workgroups(
    team: ManagementTeam,
    teaparty_home: str = '~/.teaparty',
) -> list[Workgroup]:
    """Load all workgroup definitions from the management team.

    Each WorkgroupEntry's config path is resolved relative to teaparty_home.
    """
    home = os.path.expanduser(teaparty_home)
    result: list[Workgroup] = []
    for entry in team.workgroups:
        config_path = os.path.join(home, entry.config)
        result.append(load_workgroup(config_path))
    return result


def resolve_workgroups(
    entries: list[WorkgroupRef | WorkgroupEntry],
    project_dir: str,
    teaparty_home: str = '~/.teaparty',
) -> list[Workgroup]:
    """Resolve workgroup entries to fully loaded Workgroup objects.

    Resolution order for ref: entries:
      1. Project-level: {project_dir}/.teaparty/workgroups/{ref}.yaml
      2. Org-level: {teaparty_home}/workgroups/{ref}.yaml
    Project-level overrides org-level (same precedence as .claude/ settings).

    WorkgroupEntry entries are loaded from their config path relative to
    the project or teaparty home directory.
    """
    home = os.path.expanduser(teaparty_home)
    resolved: list[Workgroup] = []

    for entry in entries:
        if isinstance(entry, WorkgroupRef):
            # Try project-level first, then org-level
            project_path = os.path.join(project_dir, '.teaparty', 'workgroups', f'{entry.ref}.yaml')
            org_path = os.path.join(home, 'workgroups', f'{entry.ref}.yaml')

            if os.path.exists(project_path):
                resolved.append(load_workgroup(project_path))
            elif os.path.exists(org_path):
                resolved.append(load_workgroup(org_path))
            else:
                raise FileNotFoundError(
                    f"Workgroup ref '{entry.ref}' not found at "
                    f"{project_path} or {org_path}"
                )
        elif isinstance(entry, WorkgroupEntry):
            # config path is relative to the project's .teaparty/ dir
            config_path = os.path.join(project_dir, '.teaparty', entry.config)
            if os.path.exists(config_path):
                resolved.append(load_workgroup(config_path))
            else:
                # Try org-level
                config_path = os.path.join(home, entry.config)
                resolved.append(load_workgroup(config_path))

    return resolved


# ── Norms ──────────────────────────────────────────────────────────────────

def merge_norms(
    workgroup_norms: dict[str, list[str]],
    project_norms: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Merge workgroup and project norms with project-wins precedence.

    Per the design doc: "This is not a merge." If the project defines a
    category, it fully replaces the workgroup's version of that category.
    Non-conflicting categories from the workgroup are preserved.
    """
    merged = dict(workgroup_norms)
    merged.update(project_norms)
    return merged


def format_norms(norms: dict[str, list[str]]) -> str:
    """Render norms as natural language for prompt injection.

    Returns readable text organized by category. Returns empty string
    if there are no norms.
    """
    if not norms:
        return ''
    sections = []
    for category, statements in norms.items():
        lines = [f'- {s}' for s in statements]
        sections.append(f'{category.title()}:\n' + '\n'.join(lines))
    return '\n\n'.join(sections)
