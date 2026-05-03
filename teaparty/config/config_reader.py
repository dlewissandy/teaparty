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
    stale: list[dict] = []
    for pin in raw:
        rel = pin.get('path', '')
        label = pin.get('label') or os.path.basename(rel.rstrip('/\\')) or rel
        abs_path = os.path.normpath(os.path.join(path_root, rel))
        if not os.path.exists(abs_path):
            stale.append(pin)
            continue
        result.append({
            'path': abs_path,
            'rel_path': rel,
            'label': label,
            'is_dir': os.path.isdir(abs_path),
        })
    if stale:
        write_pins(scope_dir, [p for p in raw if p not in stale])
    return result


def add_pin(scope_dir: str, path_root: str, abs_path: str, label: str) -> None:
    """Add abs_path to pins.yaml in scope_dir as a relative path.

    Idempotent: if the path is already pinned, does nothing.
    """
    rel = os.path.relpath(abs_path, path_root)
    pins = read_pins(scope_dir)
    for existing in pins:
        if existing.get('path', '').rstrip('/') == rel.rstrip('/'):
            return
    pins.append({'path': rel, 'label': label})
    write_pins(scope_dir, pins)


def remove_pin(scope_dir: str, path_root: str, abs_path: str) -> None:
    """Remove abs_path from pins.yaml in scope_dir.

    No-op if the path is not pinned or pins.yaml does not exist.
    """
    rel = os.path.relpath(abs_path, path_root)
    pins = read_pins(scope_dir)
    updated = [p for p in pins if p.get('path', '').rstrip('/') != rel.rstrip('/')]
    if len(updated) != len(pins):
        write_pins(scope_dir, updated)


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
    """The root management team from ~/.teaparty/teaparty.yaml.

    Single source of truth for the project roster (#422): every project
    in ``projects`` is a member of the management team — OM can
    dispatch to its lead.  There is no separate ``members.projects``
    list; any legacy YAML value is ignored.  To remove a project from
    the roster, remove it from the catalog.
    """
    name: str
    description: str = ''
    lead: str = ''
    humans: list[Human] = field(default_factory=list)
    projects: list[dict[str, str]] = field(default_factory=list)
    members_agents: list[str] = field(default_factory=list)
    members_skills: list[str] = field(default_factory=list)
    members_workgroups: list[str] = field(default_factory=list)
    workgroups: list[WorkgroupEntry] = field(default_factory=list)
    norms: dict[str, list[str]] = field(default_factory=dict)
    scheduled: list[ScheduledTask] = field(default_factory=list)
    hooks: list[dict[str, str]] = field(default_factory=list)
    budget: dict[str, float] = field(default_factory=dict)
    stats: dict[str, str] = field(default_factory=dict)
    allowed_project_roots: list[str] = field(default_factory=list)

    @property
    def members_projects(self) -> list[str]:
        """Project names in the roster — derived from ``projects``.

        Kept as a property so existing callers (``resolve_launch_placement``,
        ``derive_om_roster``, bridge status, ListTeamMembers) don't
        change.  The list is always the current set of registered
        project names; catalog and roster cannot drift.
        """
        return [p['name'] for p in self.projects if p.get('name')]


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
    # Per-gate escalation mode.  Keys are CfA state names (e.g. INTENT_ASSERT);
    # values are 'always' (always escalate; proxy observes only),
    # 'when_unsure' (default; escalate only when proxy confidence is low),
    # or 'never' (proxy decides; escalation path suppressed).
    escalation: dict[str, str] = field(default_factory=dict)


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


def _parse_workgroup_entries(raw: list | None) -> list[WorkgroupRef | WorkgroupEntry]:
    if not raw:
        return []
    result: list[WorkgroupRef | WorkgroupEntry] = []
    for entry in raw:
        if isinstance(entry, str):
            result.append(WorkgroupRef(ref=entry, status='active'))
        elif 'ref' in entry:
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
    # ``members.projects`` is deliberately NOT read from disk (#422).
    # The project roster is derived from the catalog — see the
    # ``members_projects`` property on ManagementTeam.  Any legacy
    # value in YAML is ignored.
    return ManagementTeam(
        name=data['name'],
        description=data.get('description', ''),
        lead=data.get('lead', ''),
        humans=_parse_humans(data.get('humans')),
        projects=_parse_projects(projects, repo_root=repo_root),
        members_agents=members.get('agents') or [],
        members_skills=members.get('skills') or [],
        members_workgroups=members.get('workgroups') or [],
        workgroups=_parse_management_workgroups(data.get('workgroups')),
        norms=data.get('norms', {}),
        scheduled=_parse_scheduled(data.get('scheduled')),
        hooks=data.get('hooks', []),
        budget=data.get('budget', {}),
        stats=data.get('stats', {}),
        allowed_project_roots=data.get('allowed_project_roots') or [],
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
        escalation=data.get('escalation', {}) or {},
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


def discover_workgroups(workgroups_dir: str) -> list[str]:
    """Scan a workgroups/ directory and return workgroup names.

    Each workgroup is a {name}.yaml file (ignoring non-yaml files).
    Returns an empty list if the directory does not exist.
    """
    if not os.path.isdir(workgroups_dir):
        return []
    names = []
    for entry in sorted(os.scandir(workgroups_dir), key=lambda e: e.name):
        if entry.is_file() and entry.name.endswith('.yaml'):
            names.append(entry.name[:-5])
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
    """Load all workgroup definitions from the management team's catalog.

    Returns every workgroup registered under ``workgroups:`` in
    teaparty.yaml — the catalog of workgroups whose YAML lives under
    ``management/workgroups/``.  This is NOT the same as the team's
    *members*: a workgroup can appear in the catalog without being
    declared a dispatchable member via ``members.workgroups``.  Use
    ``member_workgroups`` for the membership view.

    Each WorkgroupEntry's config path is resolved relative to teaparty_home.
    """
    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    result: list[Workgroup] = []
    for entry in team.workgroups:
        config_path = os.path.join(management_dir(home), entry.config)
        result.append(load_workgroup(config_path))
    return result


def member_workgroups(
    team: ManagementTeam,
    teaparty_home: str | None = None,
) -> list[Workgroup]:
    """Return the workgroups that are declared members of the team.

    The catalog (``team.workgroups``) lists every workgroup *registered*
    in teaparty.yaml.  The membership (``team.members_workgroups``)
    lists those the team's lead is *authorized to dispatch to*.  These
    are different — a workgroup can be registered without being a
    member.  Routing enforcement and any "who is on this team?" view
    must use membership; only catalog UIs (showing both active and
    inactive entries) need the unfiltered list.
    """
    members_lower = {m.lower() for m in team.members_workgroups}
    return [
        wg for wg in load_management_workgroups(team, teaparty_home=teaparty_home)
        if wg.name.lower() in members_lower
    ]


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
    teaparty_home: str | None = None,
) -> None:
    """Add/remove an item from a project team's active list in project.yaml.

    For agents and skills: adds/removes the name from members list.
    For shared workgroups: also adds/removes the WorkgroupRef entry from the
        workgroups list so the project actually references the org workgroup.
    For hooks: sets the active flag on the hook entry identified by event name.
    For scheduled_task: sets the enabled flag on the scheduled task entry identified by name.

    Args:
        project_dir: Path to the project root directory.
        kind: 'agent', 'workgroup', 'skill', 'hook', or 'scheduled_task'.
        name: Name/event of the item to toggle.
        active: True to activate, False to deactivate.
        catalog: Full list of available names for this kind, used to seed
            the membership list on first deactivation.
        teaparty_home: Path to the .teaparty/ directory, used to locate
            the management workgroups catalog for shared workgroup toggling.
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
    elif kind == 'workgroup':
        home = teaparty_home or default_teaparty_home()
        wg_dir = management_workgroups_dir(home)
        org_wg_path = os.path.join(wg_dir, f'{name}.yaml')
        if not os.path.exists(org_wg_path):
            # Fall back to slugified filename (e.g. 'Quality Control' -> 'quality-control.yaml')
            slug = name.lower().replace(' ', '-')
            candidate = os.path.join(wg_dir, f'{slug}.yaml')
            if os.path.exists(candidate):
                org_wg_path = candidate
        if os.path.exists(org_wg_path):
            wg_ref = os.path.splitext(os.path.basename(org_wg_path))[0]
            wg_list = data.get('workgroups') or []
            if active:
                if not any('ref' in e and e['ref'].lower() == wg_ref.lower() for e in wg_list):
                    wg_list = wg_list + [{'ref': wg_ref}]
            else:
                wg_list = [e for e in wg_list if not ('ref' in e and e['ref'].lower() == wg_ref.lower())]
            data['workgroups'] = wg_list
        members = data.setdefault('members', {})
        current = members.get('workgroups') or []
        name_lower = name.lower()
        if active:
            if not any(m.lower() == name_lower for m in current):
                current = current + [name]
        else:
            current = [m for m in current if m.lower() != name_lower]
        members['workgroups'] = current
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


DESCRIPTION_SENTINEL = '⚠ No description — ask the project lead'

_GITIGNORE_TEMPLATE = """\
# TeaParty — runtime sessions (ephemeral job records)
.teaparty/jobs/

# TeaParty — SQLite databases (auto-initialize on first use)
*.db
*.db-shm
*.db-wal
*.db-journal
"""

_GITIGNORE_MARKER = '# TeaParty — runtime sessions'


def normalize_project_name(name: str) -> str:
    """Normalize a project name: lowercase, collapse whitespace, use hyphens.

    ``"My Project"`` → ``"my-project"``; ``"PyBayes "`` → ``"pybayes"``.
    """
    return re.sub(r'\s+', '-', name.strip().lower())


def _write_project_gitignore(project_dir: str) -> None:
    """Write ``.gitignore`` from the template, or append if one exists.

    Idempotent: the TeaParty stanza is only added once (detected by marker).
    """
    path = os.path.join(project_dir, '.gitignore')
    if not os.path.exists(path):
        with open(path, 'w') as f:
            f.write(_GITIGNORE_TEMPLATE)
        return
    with open(path) as f:
        existing = f.read()
    if _GITIGNORE_MARKER in existing:
        return
    sep = '' if existing.endswith('\n') else '\n'
    with open(path, 'w') as f:
        f.write(existing + sep + '\n' + _GITIGNORE_TEMPLATE)


def _git_initial_commit(project_dir: str) -> None:
    """Stage and commit the scaffolded TeaParty files.

    Uses inline user identity so the operation does not require the caller's
    global git config. Idempotent: nothing is committed if there is nothing
    staged.
    """
    env_args = [
        '-c', 'user.email=teaparty@localhost',
        '-c', 'user.name=TeaParty',
    ]
    to_stage = ['.gitignore', '.teaparty/project']
    for rel in to_stage:
        full = os.path.join(project_dir, rel)
        if os.path.exists(full):
            subprocess.run(
                ['git', 'add', '--', rel],
                cwd=project_dir, check=True, capture_output=True,
            )
    status = subprocess.run(
        ['git', 'diff', '--cached', '--name-only'],
        cwd=project_dir, check=True, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        return
    subprocess.run(
        ['git', *env_args, 'commit', '-m', 'chore: add TeaParty project configuration'],
        cwd=project_dir, check=True, capture_output=True,
    )


def _scaffold_project_yaml(
    name: str,
    project_dir: str,
    description: str = '',
    decider: str = '',
    config: str = '.teaparty/project/project.yaml',
) -> None:
    """Create .teaparty/project/project.yaml with frontmatter if it doesn't exist.

    ``name`` must already be normalized. The lead is always ``{name}-lead``.
    """
    tp_dir = project_teaparty_dir(project_dir)
    os.makedirs(tp_dir, exist_ok=True)
    project_yaml_path = os.path.join(tp_dir, 'project.yaml')
    if os.path.exists(project_yaml_path):
        return
    scaffold = {
        'name': name,
        'description': description or DESCRIPTION_SENTINEL,
        'lead': f'{name}-lead',
        'humans': {'decider': decider} if decider else {},
        'workgroups': [{'ref': 'configuration'}],
        'members': {'workgroups': []},
        'artifact_pins': [],
    }
    with open(project_yaml_path, 'w') as f:
        yaml.dump(scaffold, f, default_flow_style=False, sort_keys=False)


# ── Project management operations ─────────────────────────────────────────────

def _check_allowed_project_roots(path: str, roots: list[str]) -> None:
    """Raise ValueError if path is not under any of the allowed roots.

    If roots is empty, the check is skipped (permissive mode).
    """
    if not roots:
        return
    for root in roots:
        root = os.path.expanduser(os.path.realpath(root))
        if path.startswith(root + os.sep) or path == root:
            return
    raise ValueError(
        f'Path {path!r} is not under any allowed project root. '
        f'Allowed roots: {roots!r}'
    )


PROJECT_LEAD_TOOLS = [
    # Built-in file tools (read project state; write PLAN.md / WORK_SUMMARY.md)
    'Read', 'Glob', 'Grep', 'Write', 'Edit',
    # Built-in web tools (research during planning)
    'WebSearch', 'WebFetch',
    # Built-in shell (execution phase)
    'Bash',
    # Team communication primitives
    'mcp__teaparty-config__Send',
    'mcp__teaparty-config__CloseConversation',
    'mcp__teaparty-config__AskQuestion',
    # Config inspection
    'mcp__teaparty-config__GetAgent',
    'mcp__teaparty-config__ListAgents',
    'mcp__teaparty-config__GetWorkgroup',
    'mcp__teaparty-config__ListWorkgroups',
    'mcp__teaparty-config__GetSkill',
    'mcp__teaparty-config__ListSkills',
    'mcp__teaparty-config__GetProject',
    'mcp__teaparty-config__ListProjects',
    'mcp__teaparty-config__ListTeamMembers',
    'mcp__teaparty-config__ListHooks',
    'mcp__teaparty-config__ListScheduledTasks',
    'mcp__teaparty-config__ListPins',
    'mcp__teaparty-config__PinArtifact',
    'mcp__teaparty-config__UnpinArtifact',
    'mcp__teaparty-config__ProjectStatus',
    'mcp__teaparty-config__WithdrawSession',
]

# Template body for a scaffolded project lead.  Two substitution points:
# `{project_name}` identifies the project; `{decider}` names the human the
# project ultimately serves.  Every other sentence is identical across
# projects so the role definition stays consistent and can be edited once
# here.  The CfA phase framing (deliverable per phase, boundaries, write-
# every-invocation) is supplied by the engine at runtime, not here.
PROJECT_LEAD_BODY_TEMPLATE = '''You are the lead of the **{project_name}** project — root of your team tree. The project's human decider is **{decider}**. Lead; don't execute. Delegate whenever you could.

## What you do

**0. Strategic plan.** Decide the steps, owners, and invariants; drive the plan through completion.

**1. Delegate.** `Send` a task: reference the spec, define done.

**2. Consolidate.** Members `Reply` to signal done. Verify against plan and spec; accept, or `Send` a correction.

**3. Mediate.** The team is a tree — members don't address each other. When A Asks for B, route through you: shape, forward, relay the Reply.

**4. Reconcile.** Members share one worktree. When outputs disagree, an invariant breaks, or an error spans members, untangle and re-dispatch.

**5. Decide done.** When a step's outputs are complete and coherent, advance — next step, or delivery.

**6. Interface externally.** Originators (OM or human), sibling projects, inbound inquiries — all via you. Members `Send` to you to route when they need external reach.

## Tools

`Send` and `Reply` are the team-comm primitives — see tool docstrings for thread semantics. Four intents ride on them: Request, Ask, Answer, Deliver — in the message content, not the tool. `AskQuestion` routes to proxy or human. `CloseConversation` tears down a thread you opened.

Independent tracks: `Send` to each in the same turn; threads run in parallel.

## Escalation

Escalate upward by `Send`ing an Ask to the originator when:
- only the originator can decide,
- the intent is inadequate,
- an interpretation change is non-trivial or irreversible,
- a blocker can't be untangled.

Silent adaptation is wrong when the originator might want to decide.
'''


def scaffold_project_lead(
    project_name: str,
    project_path: str,
    decider: str,
    teaparty_home: str,
) -> None:
    """Create the project-level agent definition for a project lead.

    Writes ``agent.md`` + ``pins.yaml`` under
    ``{project_path}/.teaparty/project/agents/{project_name}-lead/``.
    The tool whitelist lives in the agent.md ``tools:`` frontmatter field,
    same as any other agent created via the UI or ``CreateAgent`` MCP tool.
    ``settings.yaml`` is reserved for folder/Bash permissions and is not
    stamped here.

    Non-destructive: any file that already exists is left untouched so
    customized leads are never clobbered.

    ``project_name`` must already be normalized.
    """
    from teaparty.mcp.tools.config_helpers import _write_agent_file
    lead_name = f'{project_name}-lead'
    agent_dir = os.path.join(project_agents_dir(project_path), lead_name)
    os.makedirs(agent_dir, exist_ok=True)

    agent_md = os.path.join(agent_dir, 'agent.md')
    if not os.path.exists(agent_md):
        description = (
            f'Lead of the {project_name} project — leads the team, '
            f'delegates work, consolidates results. Use for any task '
            f'scoped to the {project_name} project.'
        )
        frontmatter = {
            'name': lead_name,
            'description': description,
            'model': 'sonnet',
            'maxTurns': 30,
            'skills': ['intent-alignment', 'planning', 'execute'],
        }
        body = PROJECT_LEAD_BODY_TEMPLATE.format(
            project_name=project_name, decider=decider,
        )
        body_text = body if body.startswith('\n') else f'\n{body}'
        _write_agent_file(agent_md, frontmatter, body_text)

    settings_yaml = os.path.join(agent_dir, 'settings.yaml')
    if not os.path.exists(settings_yaml):
        with open(settings_yaml, 'w') as f:
            yaml.dump(
                {'permissions': {'allow': list(PROJECT_LEAD_TOOLS)}},
                f, default_flow_style=False, sort_keys=False,
            )

    pins_yaml = os.path.join(agent_dir, 'pins.yaml')
    if not os.path.exists(pins_yaml):
        write_pins(agent_dir, [
            {'path': 'agent.md', 'label': 'Prompt & Identity'},
            {'path': 'settings.yaml', 'label': 'Tool & File Permissions'},
        ])


def _emit_project_added_event(project: str, path: str, created: bool) -> None:
    """Telemetry emission for Step 10 of onboarding.

    Best-effort for any runtime failure (missing tables, I/O errors), but
    a missing event-type constant is a development-time bug and raises
    AssertionError — matches the "no silent fallbacks" rule.
    """
    try:
        from teaparty import telemetry
        from teaparty.telemetry import events as _telem_events
        et = getattr(_telem_events, 'CONFIG_PROJECT_ADDED', None)
        if et is None:
            raise AssertionError(
                '_emit_project_added_event: no CONFIG_PROJECT_ADDED constant '
                'in teaparty.telemetry.events'
            )
        data = {'project': project, 'path': path}
        if created:
            data['created'] = True
        telemetry.record_event(et, scope=project, data=data)
    except AssertionError:
        raise
    except Exception:
        pass


def _resolve_decider(team: ManagementTeam, decider: str) -> str:
    """Resolve and validate the decider for a newly onboarded project.

    Rules:

    - Decider must be a human. Agents can never be deciders.
    - If ``decider`` is empty, default to the management team's own decider
      (the human who runs this TeaParty instance — i.e., the user who
      initiated the project creation, in any single-user dashboard or MCP
      flow).
    - If ``decider`` is supplied, it must match a human registered on the
      management team. Matching an agent name (management or otherwise) is
      rejected with an explicit error.
    - If no decider can be resolved, raise ValueError. A project without a
      decider is not valid.
    """
    human_names = {h.name for h in team.humans}
    agent_names = set(team.members_agents)

    if not decider:
        mgmt_decider = next(
            (h.name for h in team.humans if h.role == 'decider'), '',
        )
        if not mgmt_decider:
            raise ValueError(
                'No decider for project: none supplied and the management '
                "team has no decider configured. Add a human with role "
                "'decider' to teaparty.yaml or pass decider=... explicitly."
            )
        return mgmt_decider

    if decider in agent_names:
        raise ValueError(
            f"decider={decider!r} is an agent; agents can never be deciders. "
            "The decider must be a human registered on the management team."
        )
    if decider not in human_names:
        raise ValueError(
            f"decider={decider!r} is not a known human on the management "
            f"team. Known humans: {sorted(human_names) or '[]'}."
        )
    return decider


def _register_external_project(home: str, name: str, path: str, config: str) -> None:
    ext_path = external_projects_path(home)
    ext: list = []
    if os.path.isfile(ext_path):
        with open(ext_path) as f:
            ext = yaml.safe_load(f) or []
    ext.append({'name': name, 'path': path, 'config': config})
    os.makedirs(os.path.dirname(ext_path), exist_ok=True)
    with open(ext_path, 'w') as f:
        yaml.dump(ext, f, default_flow_style=False, sort_keys=False)


def add_project(
    name: str,
    path: str,
    teaparty_home: str | None = None,
    description: str = '',
    decider: str = '',
    config: str = '.teaparty/project/project.yaml',
) -> ManagementTeam:
    """Add an existing directory as a TeaParty project.

    Performs the full onboarding sequence specified in
    ``docs/guides/project-onboarding.md``: name normalization,
    directory scaffolding, ``project.yaml`` with description sentinel and
    Configuration workgroup, ``.gitignore`` from template, registry entry,
    and initial commit.

    Raises ValueError if the path does not exist or a project with this name
    already exists.
    """
    name = normalize_project_name(name)
    path = os.path.expanduser(os.path.realpath(path))

    if not os.path.isdir(path):
        raise ValueError(f'Path does not exist or is not a directory: {path}')

    team = load_management_team(teaparty_home=teaparty_home)
    _check_allowed_project_roots(path, team.allowed_project_roots)
    for p in team.projects:
        if p['name'] == name:
            raise ValueError(f"Project '{name}' already exists")
    decider = _resolve_decider(team, decider)

    _ensure_project_dirs(path)
    _scaffold_project_yaml(
        name, path, description=description, decider=decider, config=config,
    )
    _write_project_gitignore(path)

    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    _register_external_project(home, name, path, config)
    scaffold_project_lead(name, path, decider, home)
    _git_initial_commit(path)
    _emit_project_added_event(name, path, created=False)

    return load_management_team(teaparty_home=teaparty_home)


def create_project(
    name: str,
    path: str,
    teaparty_home: str | None = None,
    description: str = '',
    decider: str = '',
    config: str = '.teaparty/project/project.yaml',
) -> ManagementTeam:
    """Create a new project directory with full scaffolding.

    Performs the full onboarding sequence specified in
    ``docs/guides/project-onboarding.md``. Raises ValueError if the
    directory already exists or a project with this name is registered.
    """
    name = normalize_project_name(name)
    path = os.path.expanduser(os.path.realpath(path))

    if os.path.exists(path):
        raise ValueError(f'Directory already exists: {path}')

    team = load_management_team(teaparty_home=teaparty_home)
    _check_allowed_project_roots(path, team.allowed_project_roots)
    for p in team.projects:
        if p['name'] == name:
            raise ValueError(f"Project '{name}' already exists")
    decider = _resolve_decider(team, decider)

    os.makedirs(path)
    subprocess.run(['git', 'init', path], check=True, capture_output=True)
    _ensure_project_dirs(path)
    _scaffold_project_yaml(
        name, path, description=description, decider=decider, config=config,
    )
    _write_project_gitignore(path)

    home = os.path.expanduser(teaparty_home or default_teaparty_home())
    _register_external_project(home, name, path, config)
    scaffold_project_lead(name, path, decider, home)
    _git_initial_commit(path)
    _emit_project_added_event(name, path, created=True)

    return load_management_team(teaparty_home=teaparty_home)


def remove_project(
    name: str,
    teaparty_home: str | None = None,
) -> ManagementTeam:
    """Remove a project from the project registry.

    Checks both teaparty.yaml (tracked) and external-projects.yaml (gitignored).
    Also deletes the management-level ``{name}-lead`` agent directory if one
    exists (created by older onboarding code or manually scaffolded there).
    The project directory itself is left untouched.

    Raises ValueError if no project with this name exists.
    """
    import shutil
    home = os.path.expanduser(teaparty_home or default_teaparty_home())

    def _remove_from_members(data: dict[str, Any]) -> dict[str, Any]:
        # ``members.projects`` on disk is legacy (#422): the roster is
        # derived from the catalog now.  If the key still exists, clear
        # any stale reference to the project being removed so disk
        # state stays consistent.  If the key is absent, nothing to do.
        members = data.get('members') or {}
        if 'projects' in members:
            member_projects = members.get('projects') or []
            updated = [n for n in member_projects if n != name]
            if len(updated) < len(member_projects):
                members['projects'] = updated
                data['members'] = members
        return data

    def _remove_lead_agent(normalized: str) -> None:
        lead_dir = os.path.join(home, 'management', 'agents', f'{normalized}-lead')
        if os.path.isdir(lead_dir):
            shutil.rmtree(lead_dir)

    # Try external-projects.yaml first (most common case)
    ext_path = external_projects_path(home)
    if os.path.isfile(ext_path):
        with open(ext_path) as f:
            ext = yaml.safe_load(f) or []
        filtered = [p for p in ext if p['name'] != name]
        if len(filtered) < len(ext):
            with open(ext_path, 'w') as f:
                yaml.dump(filtered, f, default_flow_style=False, sort_keys=False)
            data = _load_management_yaml(teaparty_home)
            _save_management_yaml(_remove_from_members(data), teaparty_home)
            _remove_lead_agent(normalize_project_name(name))
            return load_management_team(teaparty_home=teaparty_home)

    # Fall back to teaparty.yaml (tracked projects)
    data = _load_management_yaml(teaparty_home)
    projects = data.get('projects') or []
    filtered = [p for p in projects if p['name'] != name]
    if len(filtered) == len(projects):
        raise ValueError(f"Project '{name}' not found")
    data['projects'] = filtered
    _save_management_yaml(_remove_from_members(data), teaparty_home)
    _remove_lead_agent(normalize_project_name(name))

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
