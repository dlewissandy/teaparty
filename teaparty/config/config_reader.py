"""Configuration tree reader and project management for teaparty.yaml and project.yaml.

Loads the two-level configuration tree:
  Level 1: {teaparty_home}/management/teaparty.yaml → ManagementTeam
  Level 2: {project}/.teaparty/project/project.yaml → ProjectTeam
  Org workgroups: {teaparty_home}/management/workgroups/*.yaml → Workgroup
  Project workgroup overrides: {project}/.teaparty/project/workgroups/*.yaml → Workgroup

Agent/skill/settings sources live under .teaparty/; .claude/ is a composed
artifact that TeaParty writes into worktrees at dispatch time.

Project management operations:
  add_project    — register an existing directory as a project
  create_project — create a new project directory with full scaffolding
  remove_project — unregister a project (directory untouched)

See docs/proposals/team-configuration/proposal.md for the design.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

import yaml


# ── Default paths ────────────────────────────────────────────────────────────

def default_teaparty_home() -> str:
    """Return .teaparty/ under the current working directory."""
    return os.path.join(os.getcwd(), '.teaparty')


# ── Path helpers ─────────────────────────────────────────────────────────────
# Encode the .teaparty/ layout so path construction is centralized.

def management_dir(teaparty_home: str) -> str:
    """Return the management-level config directory."""
    return os.path.join(teaparty_home, 'management')


def management_agents_dir(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'agents')


def management_skills_dir(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'skills')


def management_settings_path(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'settings.yaml')


def management_yaml_path(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'teaparty.yaml')


def external_projects_path(teaparty_home: str) -> str:
    """Return the path to the gitignored external-projects.yaml."""
    return os.path.join(teaparty_home, 'management', 'external-projects.yaml')


def management_workgroups_dir(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'workgroups')


def project_teaparty_dir(project_dir: str) -> str:
    """Return the .teaparty/project/ directory for a project."""
    return os.path.join(project_dir, '.teaparty', 'project')


def project_agents_dir(project_dir: str) -> str:
    return os.path.join(project_dir, '.teaparty', 'project', 'agents')


def project_skills_dir(project_dir: str) -> str:
    return os.path.join(project_dir, '.teaparty', 'project', 'skills')


def project_settings_path(project_dir: str) -> str:
    return os.path.join(project_dir, '.teaparty', 'project', 'settings.yaml')


def project_config_path(project_dir: str) -> str:
    return os.path.join(project_dir, '.teaparty', 'project', 'project.yaml')


def project_workgroups_dir(project_dir: str) -> str:
    return os.path.join(project_dir, '.teaparty', 'project', 'workgroups')


def project_sessions_dir(project_dir: str) -> str:
    return os.path.join(project_dir, '.teaparty', 'jobs')


# ── Pins ──────────────────────────────────────────────────────────────────────

def read_pins(scope_dir: str) -> list[dict[str, str]]:
    """Read pins.yaml from a scope directory.

    Returns a list of {path, label} dicts. Returns [] if the file
    does not exist. Paths are stored relative to a scope-specific root
    (determined by the caller, not by this function).
    """
    path = os.path.join(scope_dir, 'pins.yaml')
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict) and 'path' in entry]


def write_pins(scope_dir: str, pins: list[dict[str, str]]) -> None:
    """Write pins.yaml to a scope directory.

    Creates the directory and file if they don't exist.
    """
    os.makedirs(scope_dir, exist_ok=True)
    path = os.path.join(scope_dir, 'pins.yaml')
    with open(path, 'w') as f:
        yaml.dump(pins, f, default_flow_style=False, sort_keys=False)


def resolve_pins(
    scope_dir: str,
    path_root: str,
) -> list[dict]:
    """Read pins.yaml and resolve paths to absolute, adding is_dir flag.

    Args:
        scope_dir: Directory containing pins.yaml.
        path_root: Root directory for resolving relative paths.

    Returns list of {path, rel_path, label, is_dir} dicts.
    """
    raw = read_pins(scope_dir)
    result = []
    for pin in raw:
        rel = pin.get('path', '')
        label = pin.get('label') or os.path.basename(rel.rstrip('/\\')) or rel
        abs_path = os.path.normpath(os.path.join(path_root, rel))
        result.append({
            'path': abs_path,
            'rel_path': rel,
            'label': label,
            'is_dir': os.path.isdir(abs_path),
        })
    return result


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
    members_agents: list[str] = field(default_factory=list)
    members_projects: list[str] = field(default_factory=list)
    members_skills: list[str] = field(default_factory=list)
    members_workgroups: list[str] = field(default_factory=list)
    workgroups: list[WorkgroupEntry] = field(default_factory=list)
    norms: dict[str, list[str]] = field(default_factory=dict)
    scheduled: list[ScheduledTask] = field(default_factory=list)
    hooks: list[dict[str, str]] = field(default_factory=list)
    budget: dict[str, float] = field(default_factory=dict)
    stats: dict[str, str] = field(default_factory=dict)


@dataclass
class ProjectTeam:
    """A project team from {project}/.teaparty/project/project.yaml."""
    name: str
    description: str = ''
    lead: str = ''
    humans: list[Human] = field(default_factory=list)
    workgroups: list[WorkgroupRef | WorkgroupEntry] = field(default_factory=list)
    members_workgroups: list[str] = field(default_factory=list)
    members_skills: list[str] | None = None
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
    """Load the management team from management/teaparty.yaml.

    Args:
        teaparty_home: Path to the .teaparty directory (default: repo root).
        config_filename: Name of the config file within management/.
    """
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    repo_root = os.path.dirname(home)
    path = os.path.join(home, 'management', config_filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f'Management team config not found: {path}')

    with open(path) as f:
        data = yaml.safe_load(f)

    # Merge external projects (gitignored, machine-specific paths)
    projects = list(data.get('projects') or [])
    ext_path = external_projects_path(home)
    if os.path.isfile(ext_path):
        with open(ext_path) as f:
            ext = yaml.safe_load(f)
        if isinstance(ext, list):
            projects.extend(ext)

    members = data.get('members') or {}
    return ManagementTeam(
        name=data['name'],
        description=data.get('description', ''),
        lead=data.get('lead', ''),
        humans=_parse_humans(data.get('humans')),
        projects=_parse_projects(projects, repo_root=repo_root),
        members_agents=members.get('agents') or [],
        members_projects=members.get('projects') or [],
        members_skills=members.get('skills') or [],
        members_workgroups=members.get('workgroups') or [],
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
    """Load a project team from {project}/.teaparty/project/project.yaml.

    Falls back to the legacy .teaparty.local/project.yaml for unmigrated projects.

    Args:
        project_dir: Path to the project root directory.
        config_path: Explicit path to project.yaml (overrides default location).
    """
    if config_path:
        path = config_path
    else:
        path = project_config_path(project_dir)
        if not os.path.exists(path):
            legacy = os.path.join(project_dir, '.teaparty.local', 'project.yaml')
            if os.path.exists(legacy):
                path = legacy

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
        members_skills=members.get('skills'),
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
    """Scan an agents/ directory and return agent names.

    Each agent is a subdirectory containing an agent.md file.
    Returns an empty list if the directory does not exist.

    Args:
        agents_dir: Absolute path to an agents/ directory.
    """
    if not os.path.isdir(agents_dir):
        return []
    names = []
    for entry in sorted(os.scandir(agents_dir), key=lambda e: e.name):
        if entry.is_dir() and os.path.exists(os.path.join(entry.path, 'agent.md')):
            names.append(entry.name)
    return names


def discover_skills(skills_dir: str) -> list[str]:
    """Scan a skills/ directory and return skill names.

    A skill is a subdirectory that contains a SKILL.md file.
    Returns an empty list if the directory does not exist.

    Args:
        skills_dir: Absolute path to a skills/ directory.
    """
    if not os.path.isdir(skills_dir):
        return []
    names = []
    for entry in sorted(os.scandir(skills_dir), key=lambda e: e.name):
        if entry.is_dir() and os.path.exists(os.path.join(entry.path, 'SKILL.md')):
            names.append(entry.name)
    return names


def discover_hooks(settings_path: str) -> list[dict[str, str]]:
    """Read hooks from a settings.yaml file.

    Returns a flat list of hook dicts with keys: event, matcher, type, command.
    The YAML schema mirrors Claude Code's hooks structure::

        hooks:
          PreToolUse:
            - matcher: "Edit|Write"
              hooks:
                - type: command
                  command: ./hooks/enforce-ownership.sh

    Returns an empty list if the file does not exist or has no hooks.

    Args:
        settings_path: Absolute path to a settings.yaml file.
    """
    if not os.path.isfile(settings_path):
        return []
    try:
        with open(settings_path) as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
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


@dataclass
class MergedCatalog:
    """Merged catalog combining management-level and project-level entries.

    Project-level entries take precedence over management-level entries with the
    same name (per proposal.md §"Catalog and Active Selection").

    Attributes:
        agents: Unique agent names. Project entries shadow management entries on collision.
        skills: Unique skill names. Project entries shadow management entries on collision.
        hooks: Merged hook dicts. Project hooks shadow management on same (event, matcher).
        project_agents: Names sourced from the project agents/ (for source tagging).
        project_skills: Names sourced from the project skills/ (for source tagging).
    """
    agents: list[str]
    skills: list[str]
    hooks: list[dict]
    project_agents: set[str]
    project_skills: set[str]


def merge_catalog(
    mgmt_base_dir: str,
    project_base_dir: str | None = None,
) -> MergedCatalog:
    """Build a merged catalog from management and optional project-level directories.

    Reads agents, skills, and hooks from each level and merges them with project
    entries taking precedence. If a project defines an agent, skill, or hook with
    the same identifier as a management entry, the project's version is used and
    the management's version is excluded.

    Hook precedence key: (event, matcher). Two hooks with the same event and
    matcher are considered the same hook; the project's wins.

    Args:
        mgmt_base_dir: Path to the management-level directory (contains agents/,
            skills/, settings.yaml).
        project_base_dir: Optional path to the project's config directory
            (contains agents/, skills/, settings.yaml).  If None or the
            directory does not exist, only management entries are returned.

    Returns:
        MergedCatalog with merged agents, skills, and hooks.
    """
    mgmt_agents = discover_agents(os.path.join(mgmt_base_dir, 'agents'))
    mgmt_skills = discover_skills(os.path.join(mgmt_base_dir, 'skills'))
    mgmt_hooks = discover_hooks(os.path.join(mgmt_base_dir, 'settings.yaml'))

    if not project_base_dir or not os.path.isdir(project_base_dir):
        return MergedCatalog(
            agents=mgmt_agents,
            skills=mgmt_skills,
            hooks=mgmt_hooks,
            project_agents=set(),
            project_skills=set(),
        )

    proj_agents = discover_agents(os.path.join(project_base_dir, 'agents'))
    proj_skills = discover_skills(os.path.join(project_base_dir, 'skills'))
    proj_hooks = discover_hooks(os.path.join(project_base_dir, 'settings.yaml'))

    proj_agent_set = set(proj_agents)
    proj_skill_set = set(proj_skills)

    # Project entries come first; management entries not already present are appended.
    merged_agents = list(proj_agents) + [a for a in mgmt_agents if a not in proj_agent_set]
    merged_skills = list(proj_skills) + [s for s in mgmt_skills if s not in proj_skill_set]

    proj_hook_keys = {(h.get('event'), h.get('matcher')) for h in proj_hooks}
    merged_hooks = list(proj_hooks) + [
        h for h in mgmt_hooks
        if (h.get('event'), h.get('matcher')) not in proj_hook_keys
    ]

    return MergedCatalog(
        agents=merged_agents,
        skills=merged_skills,
        hooks=merged_hooks,
        project_agents=proj_agent_set,
        project_skills=proj_skill_set,
    )


def discover_projects(team: ManagementTeam) -> list[dict[str, Any]]:
    """Walk projects: entries and check which paths are valid TeaParty projects.

    A directory is a TeaParty project if it contains .git/ and .teaparty/.
    Each returned entry has:
      - name: the project name from teaparty.yaml
      - path: the expanded absolute path
      - valid: True if the path exists and contains required markers

    Returns all entries (including invalid ones) so callers can report
    missing or misconfigured projects.
    """
    required_markers = ['.git', '.teaparty']
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
        config_path = os.path.join(management_dir(home), entry.config)
        result.append(load_workgroup(config_path))
    return result


def resolve_workgroups(
    entries: list[WorkgroupRef | WorkgroupEntry],
    project_dir: str,
    teaparty_home: str | None = None,
) -> list[Workgroup]:
    """Resolve workgroup entries to fully loaded Workgroup objects.

    Resolution order for ref: entries:
      1. Project-level: {project_dir}/.teaparty/project/workgroups/{ref}.yaml
      2. Org-level: {teaparty_home}/management/workgroups/{ref}.yaml
    Project-level overrides org-level.

    WorkgroupEntry entries are loaded from their config path relative to
    the project directory or the teaparty home directory.
    """
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    resolved: list[Workgroup] = []

    for entry in entries:
        if isinstance(entry, WorkgroupRef):
            # Try project-level first, then legacy, then org-level
            proj_path = os.path.join(project_workgroups_dir(project_dir), f'{entry.ref}.yaml')
            legacy_path = os.path.join(project_dir, '.teaparty.local', 'workgroups', f'{entry.ref}.yaml')
            org_path = os.path.join(management_workgroups_dir(home), f'{entry.ref}.yaml')

            if os.path.exists(proj_path):
                resolved.append(load_workgroup(proj_path))
            elif os.path.exists(legacy_path):
                resolved.append(load_workgroup(legacy_path))
            elif os.path.exists(org_path):
                resolved.append(load_workgroup(org_path))
            else:
                raise FileNotFoundError(
                    f"Workgroup ref '{entry.ref}' not found at "
                    f"{proj_path} or {org_path}"
                )
        elif isinstance(entry, WorkgroupEntry):
            # Config path is relative (e.g. workgroups/coding.yaml).
            # Try: project .teaparty/project/, legacy .teaparty.local/, org management/
            proj_path = os.path.join(project_teaparty_dir(project_dir), entry.config)
            legacy_path = os.path.join(project_dir, '.teaparty.local', entry.config)
            org_path = os.path.join(management_dir(home), entry.config)
            if os.path.exists(proj_path):
                resolved.append(load_workgroup(proj_path))
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
    """Write a management team data dict back to management/teaparty.yaml."""
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    path = os.path.join(home, 'management', config_filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _load_management_yaml(
    teaparty_home: str | None,
    config_filename: str = 'teaparty.yaml',
) -> dict[str, Any]:
    """Load the raw YAML dict from management/teaparty.yaml."""
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    path = os.path.join(home, 'management', config_filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f'Management team config not found: {path}')
    with open(path) as f:
        return yaml.safe_load(f)


_MEMBERSHIP_KEYS = {'agent': 'agents', 'project': 'projects', 'workgroup': 'workgroups', 'skill': 'skills', 'hook': 'hooks', 'scheduled_task': 'scheduled'}


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


def _toggle_scheduled_active(scheduled: list[dict], name: str, active: bool) -> list[dict]:
    """Set the enabled flag on the scheduled task entry with the given name."""
    result = []
    found = False
    for t in scheduled:
        if t.get('name') == name:
            result.append({**t, 'enabled': active})
            found = True
        else:
            result.append(t)
    if not found:
        raise ValueError(f'Scheduled task {name!r} not found')
    return result


def toggle_management_membership(
    teaparty_home: str,
    kind: str,
    name: str,
    active: bool,
) -> None:
    """Add/remove an item from the management team's active list in teaparty.yaml.

    For agents, workgroups, and skills: adds/removes the name from the list.
    For hooks: sets the active flag on the hook entry identified by event name.
    For scheduled_task: sets the enabled flag on the scheduled task entry identified by name.

    Args:
        teaparty_home: Path to the .teaparty/ directory.
        kind: 'agent', 'workgroup', 'skill', 'hook', or 'scheduled_task'.
        name: Name/event of the item to toggle.
        active: True to activate, False to deactivate.
    """
    if kind not in _MEMBERSHIP_KEYS:
        raise ValueError(f'Invalid membership kind: {kind!r}')
    data = _load_management_yaml(teaparty_home)
    if kind == 'hook':
        data['hooks'] = _toggle_hook_active(data.get('hooks') or [], name, active)
    elif kind == 'scheduled_task':
        data['scheduled'] = _toggle_scheduled_active(data.get('scheduled') or [], name, active)
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
    catalog: list[str] | None = None,
) -> None:
    """Add/remove an item from a project team's active list in project.yaml.

    For agents and skills: adds/removes the name from the list.
    For hooks: sets the active flag on the hook entry identified by event name.
    For scheduled_task: sets the enabled flag on the scheduled task entry identified by name.

    When deactivating an item whose membership key doesn't exist yet in the
    YAML (meaning "all active by default"), the catalog must be provided so
    the list can be seeded with all items minus the one being deactivated.

    Args:
        project_dir: Path to the project root directory.
        kind: 'agent', 'skill', 'hook', or 'scheduled_task'.
        name: Name/event of the item to toggle.
        active: True to activate, False to deactivate.
        catalog: Full list of available names for this kind, used to seed
            the membership list on first deactivation.
    """
    if kind not in _MEMBERSHIP_KEYS:
        raise ValueError(f'Invalid membership kind: {kind!r}')
    yaml_path = project_config_path(project_dir)
    if not os.path.exists(yaml_path):
        legacy = os.path.join(project_dir, '.teaparty.local', 'project.yaml')
        if os.path.exists(legacy):
            yaml_path = legacy
        else:
            raise FileNotFoundError(f'project.yaml not found: {yaml_path}')
    with open(yaml_path) as f:
        data = yaml.safe_load(f) or {}
    if kind == 'hook':
        data['hooks'] = _toggle_hook_active(data.get('hooks') or [], name, active)
    elif kind == 'scheduled_task':
        data['scheduled'] = _toggle_scheduled_active(data.get('scheduled') or [], name, active)
    else:
        key = _MEMBERSHIP_KEYS[kind]
        members = data.setdefault('members', {})
        current = members.get(key)
        if current is None:
            # Key not set = "all active by default". Seed from catalog.
            current = list(catalog) if catalog else []
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


_VALID_PARTICIPANT_ROLES = frozenset({'decider', 'advisor', 'inform', 'none'})


def _set_humans_role(data: dict, name: str, role: str) -> None:
    """Mutate data['humans'] to assign name to role, removing from any prior role.

    Schema: {decider: str|None, advisors: [...], inform: [...]}
    Role 'none' removes the person from all lists.
    """
    if role not in _VALID_PARTICIPANT_ROLES:
        raise ValueError(f'Invalid role: {role!r}')
    humans = data.get('humans') or {}
    if isinstance(humans, list):
        # Migrate legacy list format to dict on write
        humans = {}
    # Remove from all roles
    if humans.get('decider') == name:
        humans['decider'] = None
    humans['advisors'] = [n for n in (humans.get('advisors') or []) if n != name]
    humans['inform'] = [n for n in (humans.get('inform') or []) if n != name]
    # Add to new role
    if role == 'decider':
        humans['decider'] = name
    elif role == 'advisor':
        humans['advisors'] = humans['advisors'] + [name]
    elif role == 'inform':
        humans['inform'] = humans['inform'] + [name]
    # Clean up None decider
    if humans.get('decider') is None:
        humans.pop('decider', None)
    data['humans'] = humans


def set_participant_role_management(teaparty_home: str, name: str, role: str) -> None:
    """Set a human participant's role in the management team config."""
    data = _load_management_yaml(teaparty_home)
    _set_humans_role(data, name, role)
    _save_management_yaml(data, teaparty_home)


def set_participant_role_project(project_dir: str, name: str, role: str) -> None:
    """Set a human participant's role in a project config."""
    yaml_path = project_config_path(project_dir)
    if not os.path.exists(yaml_path):
        legacy = os.path.join(project_dir, '.teaparty.local', 'project.yaml')
        if os.path.exists(legacy):
            yaml_path = legacy
        else:
            raise FileNotFoundError(f'project.yaml not found: {yaml_path}')
    with open(yaml_path) as f:
        data = yaml.safe_load(f) or {}
    _set_humans_role(data, name, role)
    with open(yaml_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def set_participant_role_workgroup(yaml_path: str, name: str, role: str) -> None:
    """Set a human participant's role in a workgroup config."""
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f'workgroup YAML not found: {yaml_path}')
    with open(yaml_path) as f:
        data = yaml.safe_load(f) or {}
    _set_humans_role(data, name, role)
    with open(yaml_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _ensure_project_dirs(project_dir: str) -> None:
    """Ensure .git, .claude, and .teaparty/project/ structure exists."""
    if not os.path.isdir(os.path.join(project_dir, '.git')):
        subprocess.run(
            ['git', 'init', project_dir],
            check=True,
            capture_output=True,
        )
    os.makedirs(os.path.join(project_dir, '.claude'), exist_ok=True)
    tp_proj = project_teaparty_dir(project_dir)
    os.makedirs(os.path.join(tp_proj, 'agents'), exist_ok=True)
    os.makedirs(os.path.join(tp_proj, 'skills'), exist_ok=True)
    os.makedirs(os.path.join(tp_proj, 'workgroups'), exist_ok=True)


def _scaffold_project_yaml(
    name: str,
    project_dir: str,
    description: str = '',
    lead: str = '',
    decider: str = '',
    workgroups: list | None = None,
    config: str = '.teaparty/project/project.yaml',
) -> None:
    """Create .teaparty/project/project.yaml with frontmatter if it doesn't exist."""
    tp_dir = project_teaparty_dir(project_dir)
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
    config: str = '.teaparty/project/project.yaml',
) -> ManagementTeam:
    """Add an existing directory as a TeaParty project.

    Creates .teaparty/project/project.yaml with the provided frontmatter if
    missing, and adds a projects: entry to external-projects.yaml.

    Raises ValueError if the path does not exist or a project with this name
    already exists.
    """
    path = os.path.expanduser(os.path.realpath(path))

    if not os.path.isdir(path):
        raise ValueError(f'Path does not exist or is not a directory: {path}')

    # Check for duplicates across both tracked and external project lists
    team = load_management_team(teaparty_home=teaparty_home)
    for p in team.projects:
        if p['name'] == name:
            raise ValueError(f"Project '{name}' already exists")

    # Ensure required directory structure exists
    _ensure_project_dirs(path)

    # External projects go in external-projects.yaml (gitignored)
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    ext_path = external_projects_path(home)
    ext: list = []
    if os.path.isfile(ext_path):
        with open(ext_path) as f:
            ext = yaml.safe_load(f) or []
    ext.append({'name': name, 'path': path, 'config': config})
    os.makedirs(os.path.dirname(ext_path), exist_ok=True)
    with open(ext_path, 'w') as f:
        yaml.dump(ext, f, default_flow_style=False, sort_keys=False)

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
    config: str = '.teaparty/project/project.yaml',
) -> ManagementTeam:
    """Create a new project directory with full scaffolding.

    Creates the directory, runs git init, creates .teaparty/project/ with
    subdirectories and project.yaml, and adds a projects: entry to
    external-projects.yaml.

    Raises ValueError if the directory already exists or a project with
    this name already exists.
    """
    path = os.path.expanduser(os.path.realpath(path))

    if os.path.exists(path):
        raise ValueError(f'Directory already exists: {path}')

    # Check for duplicates across both tracked and external project lists
    team = load_management_team(teaparty_home=teaparty_home)
    for p in team.projects:
        if p['name'] == name:
            raise ValueError(f"Project '{name}' already exists")

    # Create directory structure
    os.makedirs(path)
    subprocess.run(
        ['git', 'init', path],
        check=True,
        capture_output=True,
    )
    _ensure_project_dirs(path)

    _scaffold_project_yaml(
        name, path,
        description=description,
        lead=lead,
        decider=decider,
        workgroups=workgroups,
        config=config,
    )

    # Register in external-projects.yaml
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    ext_path = external_projects_path(home)
    ext: list = []
    if os.path.isfile(ext_path):
        with open(ext_path) as f:
            ext = yaml.safe_load(f) or []
    ext.append({'name': name, 'path': path, 'config': config})
    os.makedirs(os.path.dirname(ext_path), exist_ok=True)
    with open(ext_path, 'w') as f:
        yaml.dump(ext, f, default_flow_style=False, sort_keys=False)

    return load_management_team(teaparty_home=teaparty_home)


def remove_project(
    name: str,
    teaparty_home: str | None = None,
) -> ManagementTeam:
    """Remove a project from the project registry.

    Checks both teaparty.yaml (tracked) and external-projects.yaml (gitignored).
    The project directory itself is left untouched.

    Raises ValueError if no project with this name exists.
    """
    home = os.path.expanduser(teaparty_home or default_teaparty_home())

    # Try external-projects.yaml first (most common case)
    ext_path = external_projects_path(home)
    if os.path.isfile(ext_path):
        with open(ext_path) as f:
            ext = yaml.safe_load(f) or []
        filtered = [p for p in ext if p['name'] != name]
        if len(filtered) < len(ext):
            with open(ext_path, 'w') as f:
                yaml.dump(filtered, f, default_flow_style=False, sort_keys=False)
            return load_management_team(teaparty_home=teaparty_home)

    # Fall back to teaparty.yaml (tracked projects)
    data = _load_management_yaml(teaparty_home)
    projects = data.get('projects') or []
    filtered = [p for p in projects if p['name'] != name]
    if len(filtered) == len(projects):
        raise ValueError(f"Project '{name}' not found")
    data['projects'] = filtered
    _save_management_yaml(data, teaparty_home)

    return load_management_team(teaparty_home=teaparty_home)


# ── Agent file helpers ────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r'^---\n(.*?\n)---\n(.*)', re.DOTALL)


def read_agent_frontmatter(path: str) -> dict[str, Any]:
    """Parse the YAML frontmatter from an agents/{name}/agent.md file.

    Returns the frontmatter as a dict. Returns an empty dict when the file
    has no frontmatter block (i.e. does not start with ``---``).

    Args:
        path: Absolute path to the agent .md file.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    with open(path) as f:
        content = f.read()
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def write_agent_frontmatter(path: str, updates: dict[str, Any]) -> None:
    """Update frontmatter fields in an agents/{name}/agent.md file.

    Merges *updates* into the existing frontmatter. Fields not present in
    *updates* are preserved. The prose body (everything after the closing
    ``---``) is left unchanged.

    Args:
        path: Absolute path to the agent .md file.
        updates: Frontmatter fields to set. Existing fields absent from
            *updates* are preserved unchanged.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    with open(path) as f:
        content = f.read()
    m = _FRONTMATTER_RE.match(content)
    if m:
        fm: dict[str, Any] = yaml.safe_load(m.group(1)) or {}
        body = m.group(2)
    else:
        fm = {}
        body = content
    fm.update(updates)
    fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False).rstrip()
    with open(path, 'w') as f:
        f.write(f'---\n{fm_str}\n---\n{body}')
