"""Roster derivation for recursive bus dispatch.

Produces per-agent ``--agents`` JSON rosters from the configuration tree.
Each roster defines exactly who the agent can communicate with via Send.

See docs/proposals/recursive-dispatch/references/roster-derivation.md
"""

from __future__ import annotations

import os
from typing import Any

from teaparty.config.config_reader import (
    load_management_team,
    load_management_workgroups,
    load_project_team,
    load_workgroup,
    read_agent_frontmatter,
    resolve_workgroups,
)


def _agent_description(agents_dir: str, agent_name: str) -> str:
    """Read description from an agent's frontmatter.

    Supports both layouts:
    - .teaparty style: ``{agents_dir}/{name}/agent.md``
    - .claude style:   ``{agents_dir}/{name}.md``
    """
    for candidate in (
        os.path.join(agents_dir, agent_name, 'agent.md'),
        os.path.join(agents_dir, f'{agent_name}.md'),
    ):
        if os.path.exists(candidate):
            fm = read_agent_frontmatter(candidate)
            return fm.get('description', '')
    return ''


def derive_om_roster(
    teaparty_home: str,
    *,
    agents_dir: str = '',
) -> dict[str, dict[str, Any]]:
    """Derive the Office Manager's roster from teaparty.yaml.

    Returns a dict suitable for ``--agents`` JSON. Keys are agent names
    (project lead names for projects, agent names for management agents).
    Values are dicts with at least a ``description`` field.

    Args:
        teaparty_home: Path to the .teaparty directory.
        agents_dir: Path to .claude/agents/ directory. Defaults to
            {repo_root}/.claude/agents/.
    """
    team = load_management_team(teaparty_home=teaparty_home)
    repo_root = os.path.dirname(teaparty_home)
    if not agents_dir:
        agents_dir = os.path.join(repo_root, '.claude', 'agents')

    roster: dict[str, dict[str, Any]] = {}

    # Project leads from members.projects
    for project_name in team.members_projects:
        # Find the project in the registry to get its path and config
        project_entry = None
        for p in team.projects:
            if p.get('name') == project_name:
                project_entry = p
                break
        if project_entry is None:
            continue

        project_path = project_entry.get('path', '')
        if not os.path.isabs(project_path):
            project_path = os.path.join(repo_root, project_path)

        config_path = project_entry.get('config', '')
        if config_path:
            full_config = os.path.join(project_path, config_path)
        else:
            full_config = None

        try:
            project_team = load_project_team(
                project_path,
                config_path=full_config,
            )
        except FileNotFoundError:
            continue

        lead_name = project_team.lead
        if lead_name:
            roster[lead_name] = {
                'description': project_team.description or project_name,
            }

    return roster


def resolve_lead_project_path(
    lead_name: str,
    teaparty_home: str,
) -> str | None:
    """Return the project directory for a given project lead, or None."""
    team = load_management_team(teaparty_home=teaparty_home)
    repo_root = os.path.dirname(teaparty_home)

    for project_name in team.members_projects:
        project_entry = None
        for p in team.projects:
            if p.get('name') == project_name:
                project_entry = p
                break
        if project_entry is None:
            continue

        project_path = project_entry.get('path', '')
        if not os.path.isabs(project_path):
            project_path = os.path.join(repo_root, project_path)

        config_path = project_entry.get('config', '')
        full_config = os.path.join(project_path, config_path) if config_path else None

        try:
            project_team = load_project_team(project_path, config_path=full_config)
        except FileNotFoundError:
            continue

        if project_team.lead == lead_name:
            return project_path

    return None


def resolve_launch_cwd(
    member: str,
    teaparty_home: str,
    *,
    fallback: str = '',
) -> str:
    """Return the absolute repo directory a chat-tier agent should launch in.

    Project leads launch in their own project's repo (derived from
    teaparty.yaml). Management agents, management leads, and workgroup
    agents dispatched under a project inherit the *fallback* (typically
    the dispatcher's launch_cwd). When no fallback is given the teaparty
    repo root is used.
    """
    try:
        project_path = resolve_lead_project_path(member, teaparty_home)
    except FileNotFoundError:
        project_path = None
    if project_path:
        return project_path
    if fallback:
        return fallback
    return os.path.dirname(os.path.abspath(teaparty_home))


def derive_project_roster(
    project_dir: str,
    teaparty_home: str,
    *,
    agents_dir: str = '',
) -> dict[str, dict[str, Any]]:
    """Derive a project lead's roster from project.yaml.

    Returns a dict keyed by workgroup lead names with descriptions.

    Args:
        project_dir: Path to the project root directory.
        teaparty_home: Path to the .teaparty directory.
        agents_dir: Path to .claude/agents/ directory.
    """
    project_team = load_project_team(project_dir)
    if not agents_dir:
        repo_root = os.path.dirname(teaparty_home)
        agents_dir = os.path.join(repo_root, '.claude', 'agents')

    roster: dict[str, dict[str, Any]] = {}

    # Resolve workgroups to get lead names and descriptions
    workgroups = resolve_workgroups(
        project_team.workgroups,
        project_dir=project_dir,
        teaparty_home=teaparty_home,
    )

    for wg in workgroups:
        if wg.lead:
            roster[wg.lead] = {
                'description': wg.description or wg.name,
            }

    return roster


def derive_workgroup_roster(
    workgroup_path: str,
    *,
    agents_dir: str = '',
    teaparty_home: str = '',
) -> dict[str, dict[str, Any]]:
    """Derive a workgroup lead's roster from the workgroup YAML.

    Returns a dict keyed by agent names with descriptions.

    Args:
        workgroup_path: Path to the workgroup YAML file.
        agents_dir: Path to .claude/agents/ directory.
        teaparty_home: Path to the .teaparty directory (for default agents_dir).
    """
    wg = load_workgroup(workgroup_path)
    if not agents_dir and teaparty_home:
        repo_root = os.path.dirname(teaparty_home)
        agents_dir = os.path.join(repo_root, '.claude', 'agents')

    roster: dict[str, dict[str, Any]] = {}

    for agent_name in wg.members_agents:
        desc = ''
        if agents_dir:
            desc = _agent_description(agents_dir, agent_name)
        roster[agent_name] = {
            'description': desc or agent_name,
        }

    return roster


def has_sub_roster(
    agent_name: str,
    teaparty_home: str,
    *,
    project_dir: str = '',
) -> bool:
    """Determine whether an agent has a sub-roster and needs a BusEventListener.

    This is a structural check based on the agent's position in the config tree.
    An agent has a sub-roster if it is a project lead whose project has workgroups,
    or a workgroup lead whose workgroup has agents.

    Args:
        agent_name: The agent definition name (e.g. 'teaparty-lead', 'coding-lead').
        teaparty_home: Path to the .teaparty directory.
        project_dir: Path to the project root (needed for workgroup lead checks).
    """
    team = load_management_team(teaparty_home=teaparty_home)
    repo_root = os.path.dirname(teaparty_home)

    # Check if this agent is a project lead
    for project_name in team.members_projects:
        for p in team.projects:
            if p.get('name') != project_name:
                continue

            p_path = p.get('path', '')
            if not os.path.isabs(p_path):
                p_path = os.path.join(repo_root, p_path)

            config_path = p.get('config', '')
            full_config = os.path.join(p_path, config_path) if config_path else None

            try:
                pt = load_project_team(p_path, config_path=full_config)
            except FileNotFoundError:
                continue

            if pt.lead == agent_name and pt.members_workgroups:
                return True

    # Check if this agent is a workgroup lead with agents
    search_dir = project_dir or repo_root
    if search_dir:
        try:
            pt = load_project_team(search_dir)
            workgroups = resolve_workgroups(
                pt.workgroups,
                project_dir=search_dir,
                teaparty_home=teaparty_home,
            )
            for wg in workgroups:
                if wg.lead == agent_name and wg.members_agents:
                    return True
        except FileNotFoundError:
            pass

    # Check management-level workgroups
    if team.workgroups:
        try:
            mgmt_workgroups = load_management_workgroups(team, teaparty_home)
            for wg in mgmt_workgroups:
                if wg.lead == agent_name and wg.members_agents:
                    return True
        except Exception:
            pass

    return False


def agent_id_map(
    roster: dict[str, dict[str, Any]],
    level: str,
    *,
    project_name: str = '',
    workgroup_name: str = '',
) -> dict[str, str]:
    """Map agent names in a roster to scoped agent IDs.

    Agent ID format follows bus_dispatcher.py conventions:
    - OM level: project leads → '{project}/lead', management agents → 'om/{name}'
    - Project level: workgroup leads → '{project}/{workgroup}/lead'
    - Workgroup level: agents → '{project}/{workgroup}/{name}'

    Args:
        roster: The roster dict (keys are agent names).
        level: One of 'om', 'project', 'workgroup'.
        project_name: Required for project and workgroup levels.
        workgroup_name: Required for workgroup level.

    Returns:
        Dict mapping agent name to agent ID string.
    """
    mapping: dict[str, str] = {}

    for agent_name in roster:
        if level == 'om':
            # Project leads: derive project name from the lead name convention
            # e.g. 'teaparty-lead' → 'teaparty/lead'
            if agent_name.endswith('-lead'):
                proj = agent_name[:-5]  # strip '-lead'
                mapping[agent_name] = f'{proj}/lead'
            else:
                # Management-level agents scope under 'om/'
                mapping[agent_name] = f'om/{agent_name}'
        elif level == 'project':
            # Workgroup leads: '{project}/{workgroup}/lead'
            # e.g. 'coding-lead' → 'teaparty/coding/lead'
            if agent_name.endswith('-lead'):
                wg = agent_name[:-5]  # strip '-lead'
                mapping[agent_name] = f'{project_name}/{wg}/lead'
            else:
                mapping[agent_name] = f'{project_name}/{agent_name}'
        elif level == 'workgroup':
            # Workers: '{project}/{workgroup}/{name}'
            mapping[agent_name] = f'{project_name}/{workgroup_name}/{agent_name}'

    return mapping
