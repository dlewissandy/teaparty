"""Configuration tree reader and project management for teaparty.yaml and project.yaml.

Loads the two-level configuration tree:
  Level 1: {repo_root}/.teaparty/teaparty.yaml → ManagementTeam
  Level 2: {project}/.teaparty.local/project.yaml → ProjectTeam
  Org workgroups: {teaparty_home}/workgroups/*.yaml → Workgroup
  Project workgroup overrides: {project}/.teaparty.local/workgroups/*.yaml → Workgroup

Project management operations:
  add_project    — register an existing directory as a project
  create_project — create a new project directory with full scaffolding
  remove_project — unregister a project (directory untouched)

See docs/proposals/team-configuration/proposal.md for the design.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

import yaml


# ── Default paths ────────────────────────────────────────────────────────────

def default_teaparty_home() -> str:
    """Return .teaparty/ under the current working directory."""
    return os.path.join(os.getcwd(), '.teaparty')


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
    members_agents: list[str] = field(default_factory=list)
    members_hooks: list[str] = field(default_factory=list)
    humans: list[Human] = field(default_factory=list)
    artifacts: list[dict[str, str]] = field(default_factory=list)
    norms: dict[str, list[str]] = field(default_factory=dict)
    budget: dict[str, float] = field(default_factory=dict)
    stats: dict[str, str] = field(default_factory=dict)


@dataclass
class ManagementTeam:
    """The root management team from ~/.teaparty/teaparty.yaml."""
    name: str
    description: str = ''
    lead: str = ''
    humans: list[Human] = field(default_factory=list)
    projects: list[dict[str, str]] = field(default_factory=list)
    members_projects: list[str] = field(default_factory=list)
    members_agents: list[str] = field(default_factory=list)
    members_skills: list[str] = field(default_factory=list)
    workgroups: list[WorkgroupEntry] = field(default_factory=list)
    norms: dict[str, list[str]] = field(default_factory=dict)
    scheduled: list[ScheduledTask] = field(default_factory=list)
    hooks: list[dict[str, str]] = field(default_factory=list)
    budget: dict[str, float] = field(default_factory=dict)
    stats: dict[str, str] = field(default_factory=dict)


@dataclass
class ProjectTeam:
    """A project team from {project}/.teaparty.local/project.yaml."""
    name: str
    description: str = ''
    lead: str = ''
    humans: list[Human] = field(default_factory=list)
    workgroups: list[WorkgroupRef | WorkgroupEntry] = field(default_factory=list)
    members_workgroups: list[str] = field(default_factory=list)
    norms: dict[str, list[str]] = field(default_factory=dict)
    scheduled: list[ScheduledTask] = field(default_factory=list)
    hooks: list[dict[str, str]] = field(default_factory=list)
    budget: dict[str, float] = field(default_factory=dict)
    stats: dict[str, str] = field(default_factory=dict)
    artifact_pins: list[dict[str, str]] = field(default_factory=list)


# ── Parsers ──────────────────────────────────────────────────────────────────

def _parse_humans(raw: list[dict] | dict | None) -> list[Human]:
    if not raw:
        return []
    if isinstance(raw, dict):
        # New schema: {decider: name, advisors: [...], inform: [...]}
        result: list[Human] = []
        if 'decider' in raw:
            result.append(Human(name=raw['decider'], role='decider'))
        for name in raw.get('advisors', []) or []:
            result.append(Human(name=name, role='advisor'))
        for name in raw.get('inform', []) or []:
            result.append(Human(name=name, role='informed'))
        return result
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


def _parse_projects(raw: list[dict] | None, repo_root: str | None = None) -> list[dict[str, str]]:
    if not raw:
        return []
    result = []
    for t in raw:
        path = os.path.expanduser(t['path'])
        if not os.path.isabs(path) and repo_root:
            path = os.path.normpath(os.path.join(repo_root, path))
        result.append({'name': t['name'], 'path': path, 'config': t.get('config', '')})
    return result


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
    repo_root = os.path.dirname(home)
    path = os.path.join(home, config_filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f'Management team config not found: {path}')

    with open(path) as f:
        data = yaml.safe_load(f)

    members = data.get('members') or {}
    return ManagementTeam(
        name=data['name'],
        description=data.get('description', ''),
        lead=data.get('lead', ''),
        humans=_parse_humans(data.get('humans')),
        projects=_parse_projects(data.get('projects'), repo_root=repo_root),
        members_projects=members.get('projects') or [],
        members_agents=members.get('agents') or [],
        members_skills=members.get('skills') or [],
        workgroups=_parse_management_workgroups(data.get('workgroups')),
        norms=data.get('norms', {}),
        scheduled=_parse_scheduled(data.get('scheduled')),
        hooks=data.get('hooks', []),
        budget=data.get('budget', {}),
        stats=data.get('stats', {}),
    )


def load_project_team(
    project_dir: str,
    config_path: str | None = None,
) -> ProjectTeam:
    """Load a project team from {project}/.teaparty.local/project.yaml.

    Args:
        project_dir: Path to the project root directory.
        config_path: Explicit path to project.yaml (overrides default location).
    """
    if config_path:
        path = config_path
    else:
        path = os.path.join(project_dir, '.teaparty.local', 'project.yaml')

    if not os.path.exists(path):
        raise FileNotFoundError(f'Project config not found: {path}')

    with open(path) as f:
        data = yaml.safe_load(f)

    members = data.get('members') or {}
    return ProjectTeam(
        name=data['name'],
        description=data.get('description', ''),
        lead=data.get('lead', ''),
        humans=_parse_humans(data.get('humans')),
        workgroups=_parse_workgroup_entries(data.get('workgroups')),
        members_workgroups=members.get('workgroups') or [],
        norms=data.get('norms', {}),
        scheduled=_parse_scheduled(data.get('scheduled')),
        hooks=data.get('hooks', []),
        budget=data.get('budget', {}),
        stats=data.get('stats', {}),
        artifact_pins=data.get('artifact_pins', []),
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

    members = data.get('members') or {}
    return Workgroup(
        name=data['name'],
        description=data.get('description', ''),
        lead=data.get('lead', ''),
        members_agents=members.get('agents') or [],
        members_hooks=members.get('hooks') or [],
        humans=_parse_humans(data.get('humans')),
        artifacts=data.get('artifacts') or [],
        norms=data.get('norms', {}),
        budget=data.get('budget', {}),
        stats=data.get('stats', {}),
    )


# ── Discovery & resolution ──────────────────────────────────────────────────

def discover_agents(agents_dir: str) -> list[str]:
    """Scan a .claude/agents/ directory and return agent names (without .md extension).

    Returns an empty list if the directory does not exist.

    Args:
        agents_dir: Absolute path to a .claude/agents/ directory.
    """
    if not os.path.isdir(agents_dir):
        return []
    names = []
    for entry in sorted(os.scandir(agents_dir), key=lambda e: e.name):
        if entry.is_file() and entry.name.endswith('.md'):
            names.append(entry.name[:-3])
    return names


def discover_skills(skills_dir: str) -> list[str]:
    """Scan a .claude/skills/ directory and return skill names.

    A skill is a subdirectory that contains a SKILL.md file.
    Returns an empty list if the directory does not exist.

    Args:
        skills_dir: Absolute path to a .claude/skills/ directory.
    """
    if not os.path.isdir(skills_dir):
        return []
    names = []
    for entry in sorted(os.scandir(skills_dir), key=lambda e: e.name):
        if entry.is_dir() and os.path.exists(os.path.join(entry.path, 'SKILL.md')):
            names.append(entry.name)
    return names


def discover_hooks(settings_json_path: str) -> list[dict[str, str]]:
    """Read Claude Code hooks from a .claude/settings.json file.

    Returns a flat list of hook dicts with keys: event, matcher, type, command.
    The format mirrors what config_reader loads from YAML hooks: entries.
    Returns an empty list if the file does not exist or has no hooks.

    Args:
        settings_json_path: Absolute path to a .claude/settings.json file.
    """
    if not os.path.isfile(settings_json_path):
        return []
    try:
        with open(settings_json_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    hooks_section = data.get('hooks', {})
    if not isinstance(hooks_section, dict):
        return []
    result: list[dict[str, str]] = []
    for event, matchers in hooks_section.items():
        if not isinstance(matchers, list):
            continue
        for entry in matchers:
            if not isinstance(entry, dict):
                continue
            matcher = entry.get('matcher', '')
            for hook in entry.get('hooks', []):
                if not isinstance(hook, dict):
                    continue
                result.append({
                    'event': event,
                    'matcher': matcher,
                    'type': hook.get('type', ''),
                    'command': hook.get('command', ''),
                })
    return result


def discover_projects(team: ManagementTeam) -> list[dict[str, Any]]:
    """Walk projects: entries and check which paths are valid TeaParty projects.

    A directory is a TeaParty project if it contains .git/, .claude/, and
    .teaparty/ (per the design doc). Each returned entry has:
      - name: the project name from teaparty.yaml
      - path: the expanded absolute path
      - valid: True if the path exists and contains required markers

    Returns all entries (including invalid ones) so callers can report
    missing or misconfigured projects.
    """
    required_markers = ['.git', '.claude', '.teaparty']
    result: list[dict[str, Any]] = []
    for entry in team.projects:
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
      1. Project-level: {project_dir}/.teaparty.local/workgroups/{ref}.yaml
      2. Org-level: {teaparty_home}/workgroups/{ref}.yaml
    Project-level overrides org-level (same precedence as .claude/ settings).

    WorkgroupEntry entries are loaded from their config path relative to
    the project's .teaparty.local/ directory or the teaparty home directory.
    """
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    resolved: list[Workgroup] = []

    for entry in entries:
        if isinstance(entry, WorkgroupRef):
            # Try project-level first (.teaparty.local/), then org-level
            project_path = os.path.join(project_dir, '.teaparty.local', 'workgroups', f'{entry.ref}.yaml')
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
            # New schema: config path is repo-root-relative (e.g. .teaparty/workgroups/coding.yaml)
            # Fall back to .teaparty.local/-relative (old schema) then org-level
            repo_root_path = os.path.join(project_dir, entry.config)
            legacy_path = os.path.join(project_dir, '.teaparty.local', entry.config)
            org_path = os.path.join(home, entry.config)
            if os.path.exists(repo_root_path):
                resolved.append(load_workgroup(repo_root_path))
            elif os.path.exists(legacy_path):
                resolved.append(load_workgroup(legacy_path))
            else:
                resolved.append(load_workgroup(org_path))

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


_MEMBERSHIP_KEYS = {'agent': 'agents', 'project': 'projects', 'workgroup': 'workgroups', 'skill': 'skills', 'hook': 'hooks'}


def _toggle_hook_active(hooks: list[dict], event: str, active: bool) -> list[dict]:
    """Set the active flag on the hook entry with the given event name."""
    result = []
    found = False
    for h in hooks:
        if h.get('event') == event:
            result.append({**h, 'active': active})
            found = True
        else:
            result.append(h)
    if not found:
        raise ValueError(f'Hook with event {event!r} not found')
    return result


def toggle_management_membership(
    teaparty_home: str,
    kind: str,
    name: str,
    active: bool,
) -> None:
    """Add/remove an item from the management team's active list in teaparty.yaml.

    For agents and skills: adds/removes the name from the list.
    For hooks: sets the active flag on the hook entry identified by event name.

    Args:
        teaparty_home: Path to the .teaparty/ directory.
        kind: 'agent', 'skill', or 'hook'.
        name: Name/event of the item to toggle.
        active: True to activate, False to deactivate.
    """
    if kind not in _MEMBERSHIP_KEYS:
        raise ValueError(f'Invalid membership kind: {kind!r}')
    data = _load_management_yaml(teaparty_home)
    if kind == 'hook':
        data['hooks'] = _toggle_hook_active(data.get('hooks') or [], name, active)
    else:
        key = _MEMBERSHIP_KEYS[kind]
        members = data.setdefault('members', {})
        current: list = members.get(key) or []
        if active:
            if name not in current:
                current = current + [name]
        else:
            current = [x for x in current if x != name]
        members[key] = current
    _save_management_yaml(data, teaparty_home)


def toggle_project_membership(
    project_dir: str,
    kind: str,
    name: str,
    active: bool,
) -> None:
    """Add/remove an item from a project team's active list in project.yaml.

    For agents and skills: adds/removes the name from the list.
    For hooks: sets the active flag on the hook entry identified by event name.

    Args:
        project_dir: Path to the project root directory.
        kind: 'agent', 'skill', or 'hook'.
        name: Name/event of the item to toggle.
        active: True to activate, False to deactivate.
    """
    if kind not in _MEMBERSHIP_KEYS:
        raise ValueError(f'Invalid membership kind: {kind!r}')
    yaml_path = os.path.join(project_dir, '.teaparty.local', 'project.yaml')
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f'project.yaml not found: {yaml_path}')
    with open(yaml_path) as f:
        data = yaml.safe_load(f) or {}
    if kind == 'hook':
        data['hooks'] = _toggle_hook_active(data.get('hooks') or [], name, active)
    else:
        key = _MEMBERSHIP_KEYS[kind]
        members = data.setdefault('members', {})
        current: list = members.get(key) or []
        if active:
            if name not in current:
                current = current + [name]
        else:
            current = [x for x in current if x != name]
        members[key] = current
    with open(yaml_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def toggle_workgroup_membership(
    workgroup_yaml_path: str,
    kind: str,
    name: str,
    active: bool,
) -> None:
    """Add or remove an agent or hook from a workgroup YAML file.

    Workgroups have no skill membership (skills are per-agent, not per-workgroup).

    Args:
        workgroup_yaml_path: Absolute path to the workgroup's .yaml file.
        kind: 'agent' or 'hook'.
        name: Name of the agent or event name of the hook to toggle.
        active: True to add, False to remove.
    """
    if kind not in ('agent', 'hook'):
        raise ValueError(f'Invalid membership kind for workgroup: {kind!r}')
    if not os.path.exists(workgroup_yaml_path):
        raise FileNotFoundError(f'workgroup YAML not found: {workgroup_yaml_path}')
    with open(workgroup_yaml_path) as f:
        data = yaml.safe_load(f) or {}
    members = data.setdefault('members', {})
    if kind == 'agent':
        agents = members.get('agents') or []
        if active and name not in agents:
            agents = agents + [name]
        elif not active:
            agents = [a for a in agents if a != name]
        members['agents'] = agents
    else:
        hooks = members.get('hooks') or []
        if active and name not in hooks:
            hooks = hooks + [name]
        elif not active:
            hooks = [h for h in hooks if h != name]
        members['hooks'] = hooks
    with open(workgroup_yaml_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _scaffold_project_yaml(
    name: str,
    project_dir: str,
    description: str = '',
    lead: str = '',
    decider: str = '',
    workgroups: list | None = None,
    config: str = '.teaparty/project.yaml',
) -> None:
    """Create .teaparty.local/project.yaml with new-schema frontmatter if it doesn't exist."""
    tp_dir = os.path.join(project_dir, '.teaparty.local')
    os.makedirs(tp_dir, exist_ok=True)
    project_yaml_path = os.path.join(tp_dir, 'project.yaml')
    if os.path.exists(project_yaml_path):
        return
    humans_block = {'decider': decider} if decider else {}
    scaffold = {
        'name': name,
        'description': description,
        'lead': lead,
        'humans': humans_block,
        'workgroups': workgroups or [],
        'members': {'workgroups': []},
        'artifact_pins': [],
    }
    with open(project_yaml_path, 'w') as f:
        yaml.dump(scaffold, f, default_flow_style=False, sort_keys=False)


# ── Project management operations ─────────────────────────────────────────────

def add_project(
    name: str,
    path: str,
    teaparty_home: str | None = None,
    description: str = '',
    lead: str = '',
    decider: str = '',
    workgroups: list | None = None,
    config: str = '.teaparty/project.yaml',
) -> ManagementTeam:
    """Add an existing directory as a TeaParty project.

    Creates .teaparty.local/project.yaml with the provided frontmatter if
    missing, and adds a projects: entry to teaparty.yaml.  Prerequisites (.git/,
    .claude/) are not validated here — the OM handles bootstrapping.

    Raises ValueError if the path does not exist or a project with this name
    already exists.
    """
    path = os.path.expanduser(os.path.realpath(path))

    if not os.path.isdir(path):
        raise ValueError(f'Path does not exist or is not a directory: {path}')

    data = _load_management_yaml(teaparty_home)
    projects = data.get('projects') or []

    for p in projects:
        if p['name'] == name:
            raise ValueError(f"Project '{name}' already exists in teaparty.yaml")

    projects.append({'name': name, 'path': path, 'config': config})
    data['projects'] = projects
    _save_management_yaml(data, teaparty_home)

    _scaffold_project_yaml(
        name, path,
        description=description,
        lead=lead,
        decider=decider,
        workgroups=workgroups,
        config=config,
    )

    return load_management_team(teaparty_home=teaparty_home)


def create_project(
    name: str,
    path: str,
    teaparty_home: str | None = None,
    description: str = '',
    lead: str = '',
    decider: str = '',
    workgroups: list | None = None,
    config: str = '.teaparty/project.yaml',
) -> ManagementTeam:
    """Create a new project directory with full scaffolding.

    Creates the directory, runs git init, creates .claude/ and
    .teaparty.local/project.yaml with the provided frontmatter, and adds a
    projects: entry to teaparty.yaml.

    Raises ValueError if the directory already exists or a project with
    this name already exists.
    """
    path = os.path.expanduser(os.path.realpath(path))

    if os.path.exists(path):
        raise ValueError(f'Directory already exists: {path}')

    data = _load_management_yaml(teaparty_home)
    projects = data.get('projects') or []

    for p in projects:
        if p['name'] == name:
            raise ValueError(f"Project '{name}' already exists in teaparty.yaml")

    # Create directory structure
    os.makedirs(path)
    os.makedirs(os.path.join(path, '.claude'))
    subprocess.run(
        ['git', 'init', path],
        check=True,
        capture_output=True,
    )

    _scaffold_project_yaml(
        name, path,
        description=description,
        lead=lead,
        decider=decider,
        workgroups=workgroups,
        config=config,
    )

    projects.append({'name': name, 'path': path, 'config': config})
    data['projects'] = projects
    _save_management_yaml(data, teaparty_home)

    return load_management_team(teaparty_home=teaparty_home)


def remove_project(
    name: str,
    teaparty_home: str | None = None,
) -> ManagementTeam:
    """Remove a project from projects: in teaparty.yaml.

    The project directory itself is left untouched. Only the projects:
    entry in teaparty.yaml is removed.

    Raises ValueError if no project with this name exists.
    """
    data = _load_management_yaml(teaparty_home)
    projects = data.get('projects') or []

    original_len = len(projects)
    projects = [p for p in projects if p['name'] != name]

    if len(projects) == original_len:
        raise ValueError(f"Project '{name}' not found in teaparty.yaml")

    data['projects'] = projects
    _save_management_yaml(data, teaparty_home)

    return load_management_team(teaparty_home=teaparty_home)
