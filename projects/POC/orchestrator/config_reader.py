"""Configuration tree reader and project management for teaparty.yaml and project.yaml.

Loads the two-level configuration tree:
  Level 1: {repo_root}/.teaparty/teaparty.yaml → ManagementTeam
  Level 2: {project}/.teaparty/project.yaml → ProjectTeam
  Workgroups: {level}/.teaparty/workgroups/*.yaml → Workgroup

Project management operations:
  add_project    — register an existing directory as a project
  create_project — create a new project directory with full scaffolding
  remove_project — unregister a project (directory untouched)

See docs/proposals/team-configuration/proposal.md for the design.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

import yaml


# ── Default paths ────────────────────────────────────────────────────────────

_cached_teaparty_home: str | None = None


def default_teaparty_home() -> str:
    """Return the repo-level .teaparty/ directory, cached after first call."""
    global _cached_teaparty_home
    if _cached_teaparty_home is None:
        from projects.POC.orchestrator import find_poc_root
        poc_root = find_poc_root()
        repo_root = os.path.dirname(os.path.dirname(poc_root))
        _cached_teaparty_home = os.path.join(repo_root, '.teaparty')
    return _cached_teaparty_home


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
    budget: dict[str, float] = field(default_factory=dict)
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
    hooks: list[dict[str, str]] = field(default_factory=list)
    norms: dict[str, list[str]] = field(default_factory=dict)
    budget: dict[str, float] = field(default_factory=dict)
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
    budget: dict[str, float] = field(default_factory=dict)
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
    teaparty_home: str | None = None,
    config_filename: str = 'teaparty.yaml',
) -> ManagementTeam:
    """Load the management team from teaparty.yaml.

    Args:
        teaparty_home: Path to the .teaparty directory (default: repo root).
        config_filename: Name of the config file within teaparty_home.
    """
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
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
        hooks=data.get('hooks', []),
        norms=data.get('norms', {}),
        budget=data.get('budget', {}),
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
        budget=data.get('budget', {}),
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
        budget=data.get('budget', {}),
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
    teaparty_home: str | None = None,
) -> list[Workgroup]:
    """Load all workgroup definitions from the management team.

    Each WorkgroupEntry's config path is resolved relative to teaparty_home.
    """
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    result: list[Workgroup] = []
    for entry in team.workgroups:
        config_path = os.path.join(home, entry.config)
        result.append(load_workgroup(config_path))
    return result


def resolve_workgroups(
    entries: list[WorkgroupRef | WorkgroupEntry],
    project_dir: str,
    teaparty_home: str | None = None,
) -> list[Workgroup]:
    """Resolve workgroup entries to fully loaded Workgroup objects.

    Resolution order for ref: entries:
      1. Project-level: {project_dir}/.teaparty/workgroups/{ref}.yaml
      2. Org-level: {teaparty_home}/workgroups/{ref}.yaml
    Project-level overrides org-level (same precedence as .claude/ settings).

    WorkgroupEntry entries are loaded from their config path relative to
    the project or teaparty home directory.
    """
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
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

def apply_norms_precedence(*levels: dict[str, list[str]]) -> dict[str, list[str]]:
    """Apply norms precedence across configuration levels.

    Per the design doc: "This is not a merge." If a higher-precedence level
    defines a category, it fully replaces that category from lower levels.
    Non-conflicting categories from all levels are preserved.

    Args are ordered lowest-to-highest precedence: org, workgroup, project.
    Any number of levels can be passed (including zero).
    """
    result: dict[str, list[str]] = {}
    for level in levels:
        result.update(level)
    return result


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


def resolve_norms(
    org_norms: dict[str, list[str]] | None = None,
    workgroup_norms: dict[str, list[str]] | None = None,
    project_norms: dict[str, list[str]] | None = None,
) -> str:
    """Resolve norms across all three levels and format for prompt injection.

    Applies precedence (org < workgroup < project) and renders as text.
    This is the integration point for injecting norms into agent context.
    """
    effective = apply_norms_precedence(
        org_norms or {},
        workgroup_norms or {},
        project_norms or {},
    )
    return format_norms(effective)


# ── Budgets ───────��───────────────────────────────────────────────────────────

def apply_budget_precedence(*levels: dict[str, float]) -> dict[str, float]:
    """Apply budget precedence across configuration levels.

    Higher-precedence levels override individual keys from lower levels.
    Unlike norms (which replace entire categories), budgets merge at the
    key level — a project can override job_limit_usd without losing the
    org-level project_limit_usd.

    Args are ordered lowest-to-highest precedence: org, workgroup, project.
    """
    result: dict[str, float] = {}
    for level in levels:
        result.update(level)
    return result


def resolve_budget(
    org_budget: dict[str, float] | None = None,
    workgroup_budget: dict[str, float] | None = None,
    project_budget: dict[str, float] | None = None,
) -> dict[str, float]:
    """Resolve budgets across all three levels.

    Applies precedence (org < workgroup < project) and returns the
    effective budget dict.  This is the integration point for reading
    budget limits in the orchestrator.
    """
    return apply_budget_precedence(
        org_budget or {},
        workgroup_budget or {},
        project_budget or {},
    )


# ── YAML persistence ───────────────────────��──────────────────────────────────

def _save_management_yaml(
    data: dict[str, Any],
    teaparty_home: str | None,
    config_filename: str = 'teaparty.yaml',
) -> None:
    """Write a management team data dict back to teaparty.yaml."""
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    path = os.path.join(home, config_filename)
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _load_management_yaml(
    teaparty_home: str | None,
    config_filename: str = 'teaparty.yaml',
) -> dict[str, Any]:
    """Load the raw YAML dict from teaparty.yaml."""
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    path = os.path.join(home, config_filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f'Management team config not found: {path}')
    with open(path) as f:
        return yaml.safe_load(f)


def _scaffold_project_yaml(name: str, project_dir: str) -> None:
    """Create .teaparty/project.yaml with a minimal scaffold if it doesn't exist."""
    tp_dir = os.path.join(project_dir, '.teaparty')
    os.makedirs(tp_dir, exist_ok=True)
    project_yaml_path = os.path.join(tp_dir, 'project.yaml')
    if os.path.exists(project_yaml_path):
        return
    scaffold = {
        'name': name,
        'description': '',
        'lead': '',
        'decider': '',
        'agents': [],
        'humans': [],
        'workgroups': [],
        'skills': [],
    }
    with open(project_yaml_path, 'w') as f:
        yaml.dump(scaffold, f, default_flow_style=False, sort_keys=False)


# ── Project management operations ─────────────────────────────────────────────

def add_project(
    name: str,
    path: str,
    teaparty_home: str | None = None,
) -> ManagementTeam:
    """Add an existing directory as a TeaParty project.

    Validates that the directory contains .git/ and .claude/, creates
    .teaparty/project.yaml if missing, and adds a teams: entry to
    teaparty.yaml.

    Raises ValueError if the path is invalid, missing required markers,
    or a team with this name already exists.
    """
    path = os.path.expanduser(os.path.realpath(path))

    if not os.path.isdir(path):
        raise ValueError(f'Path does not exist or is not a directory: {path}')
    if not os.path.isdir(os.path.join(path, '.git')):
        raise ValueError(f'Directory missing .git/: {path}')
    if not os.path.isdir(os.path.join(path, '.claude')):
        raise ValueError(f'Directory missing .claude/: {path}')

    data = _load_management_yaml(teaparty_home)
    teams = data.get('teams') or []

    for t in teams:
        if t['name'] == name:
            raise ValueError(f"Team '{name}' already exists in teaparty.yaml")

    teams.append({'name': name, 'path': path})
    data['teams'] = teams
    _save_management_yaml(data, teaparty_home)

    _scaffold_project_yaml(name, path)

    return load_management_team(teaparty_home=teaparty_home)


def create_project(
    name: str,
    path: str,
    teaparty_home: str | None = None,
) -> ManagementTeam:
    """Create a new project directory with full scaffolding.

    Creates the directory, runs git init, creates .claude/ and
    .teaparty/project.yaml, and adds a teams: entry to teaparty.yaml.

    Raises ValueError if the directory already exists or a team with
    this name already exists.
    """
    path = os.path.expanduser(os.path.realpath(path))

    if os.path.exists(path):
        raise ValueError(f'Directory already exists: {path}')

    data = _load_management_yaml(teaparty_home)
    teams = data.get('teams') or []

    for t in teams:
        if t['name'] == name:
            raise ValueError(f"Team '{name}' already exists in teaparty.yaml")

    # Create directory structure
    os.makedirs(path)
    os.makedirs(os.path.join(path, '.claude'))
    subprocess.run(
        ['git', 'init', path],
        check=True,
        capture_output=True,
    )

    _scaffold_project_yaml(name, path)

    teams.append({'name': name, 'path': path})
    data['teams'] = teams
    _save_management_yaml(data, teaparty_home)

    return load_management_team(teaparty_home=teaparty_home)


def remove_project(
    name: str,
    teaparty_home: str | None = None,
) -> ManagementTeam:
    """Remove a project from teams: in teaparty.yaml.

    The project directory itself is left untouched. Only the teams:
    entry in teaparty.yaml is removed.

    Raises ValueError if no team with this name exists.
    """
    data = _load_management_yaml(teaparty_home)
    teams = data.get('teams') or []

    original_len = len(teams)
    teams = [t for t in teams if t['name'] != name]

    if len(teams) == original_len:
        raise ValueError(f"Team '{name}' not found in teaparty.yaml")

    data['teams'] = teams
    _save_management_yaml(data, teaparty_home)

    return load_management_team(teaparty_home=teaparty_home)
