"""Roster derivation for bus dispatch routing.

ONE way of building rosters.  ``derive_roster`` produces a ``Roster``
from any team config (management / project / workgroup); every consumer
that asks "who is on this team?" calls it.  Reporting (``ListTeamMembers``
MCP tool) and routing (``BusDispatcher`` via ``build_routing_table``)
read the same data and cannot disagree.

The Roster shape is recursive — a ManagementTeam roster doesn't nest
project sub-rosters (each project lead's own session builds its own
roster); a project roster nests its workgroup sub-rosters so the
project lead's session has the full within-workgroup mesh available
for routing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from teaparty.config.config_reader import (
    load_management_team,
    load_project_team,
    load_workgroup,
    member_workgroups,
    resolve_workgroups,
)


# ── Roster shape ────────────────────────────────────────────────────────────

@dataclass
class Member:
    """A single team member.

    ``name`` is the agent's identity (its identifier everywhere else
    in the system).  ``role`` and the source-info fields carry the
    metadata reporting consumers need; routing consumers read only
    ``name``.
    """
    name: str
    role: str                  # 'project-lead' | 'workgroup-lead' | 'workgroup-agent' | 'proxy'
    description: str = ''
    project: str = ''          # populated for project-lead
    workgroup: str = ''        # populated for workgroup-lead / workgroup-agent
    human: str = ''            # populated for proxy


@dataclass
class Roster:
    """Recursive roster shape — describes a team's membership.

    The same shape works for the management team (OM as lead), a
    project team (project-lead as lead), or a workgroup (wg-lead as
    lead).  ``build_routing_table`` walks the structure to produce the
    routing pairs.
    """
    lead: str                              # team's leader (agent name)
    members: list[Member] = field(default_factory=list)
    sub_rosters: list['Roster'] = field(default_factory=list)
    mesh_among_members: bool = False       # within-team peer-to-peer
    parent_lead: str = ''                  # parent team's leader (cross-team gateway)


# ── Derivation ──────────────────────────────────────────────────────────────

def derive_roster(
    *,
    teaparty_home: str,
    project_dir: str = '',
    workgroup_path: str = '',
    parent_lead: str = '',
) -> Roster:
    """Derive a roster for any team type.

    Selector:

      * ``workgroup_path`` set → workgroup roster (lead + member agents,
        mesh among members).
      * ``project_dir`` set → project roster (lead + workgroup leads;
        nests each workgroup's roster as a sub-roster).
      * neither set → OM/management roster (lead + project leads +
        member workgroup leads + proxy).

    ``parent_lead`` is the lead of the parent team in the hierarchy:

      * For OM: empty (the OM is the top of the tree).
      * For a project team: the OM's agent name.
      * For a workgroup: the project lead's agent name.

    Recursion: deriving a project roster auto-derives each member
    workgroup's sub-roster.  A workgroup's roster has no sub-rosters
    (the agents are leaves).
    """
    if workgroup_path:
        wg = load_workgroup(workgroup_path)
        members = [
            Member(
                name=name,
                role='workgroup-agent',
                workgroup=wg.name,
            )
            for name in wg.members_agents
        ]
        return Roster(
            lead=wg.lead,
            members=members,
            sub_rosters=[],
            mesh_among_members=True,
            parent_lead=parent_lead,
        )

    if project_dir:
        proj = load_project_team(project_dir)
        workgroups = resolve_workgroups(
            proj.workgroups, project_dir=project_dir,
            teaparty_home=teaparty_home,
        )
        # Project members: workgroup leads (one per resolved workgroup
        # whose name is also declared via ``members.workgroups``).
        members_lower = {m.lower() for m in proj.members_workgroups}
        members: list[Member] = []
        sub_rosters: list[Roster] = []
        for wg in workgroups:
            if wg.name.lower() not in members_lower:
                continue
            if not wg.lead:
                continue
            members.append(Member(
                name=wg.lead,
                role='workgroup-lead',
                workgroup=wg.name,
                description=wg.description or wg.name,
            ))
            # Sub-roster: the workgroup's own roster, parented to this
            # project lead.  Built inline because we already have the
            # resolved workgroup object.
            sub_members = [
                Member(name=a, role='workgroup-agent', workgroup=wg.name)
                for a in wg.members_agents
            ]
            sub_rosters.append(Roster(
                lead=wg.lead,
                members=sub_members,
                sub_rosters=[],
                mesh_among_members=True,
                parent_lead=proj.lead,
            ))
        return Roster(
            lead=proj.lead,
            members=members,
            sub_rosters=sub_rosters,
            mesh_among_members=False,
            parent_lead=parent_lead,
        )

    # OM / management roster.
    team = load_management_team(teaparty_home=teaparty_home)
    repo_root = os.path.dirname(teaparty_home)
    members: list[Member] = []

    # Project leads — one per ``members.projects`` with a declared lead.
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
        full_config = (
            os.path.join(project_path, config_path) if config_path else None
        )

        try:
            project_team = load_project_team(
                project_path, config_path=full_config,
            )
        except FileNotFoundError:
            continue

        if project_team.lead:
            members.append(Member(
                name=project_team.lead,
                role='project-lead',
                project=project_name,
                description=project_team.description or project_name,
            ))

    # Management workgroup leads — declared via ``members.workgroups``.
    try:
        for wg in member_workgroups(team, teaparty_home=teaparty_home):
            if wg.lead:
                members.append(Member(
                    name=wg.lead,
                    role='workgroup-lead',
                    workgroup=wg.name,
                    description=wg.description or wg.name,
                ))
    except Exception:
        pass

    # Proxy — one entry per declared human.  All proxies share the
    # ``proxy`` agent_name (singleton agent that takes a qualifier).
    for human in team.humans:
        members.append(Member(
            name='proxy',
            role='proxy',
            human=human.name,
            description=f'Human proxy for {human.name}',
        ))

    return Roster(
        lead=team.lead,
        members=members,
        sub_rosters=[],
        mesh_among_members=False,
        parent_lead=parent_lead,
    )


# ── Path resolution helpers ─────────────────────────────────────────────────

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


class LaunchCwdNotResolved(ValueError):
    """Raised when a member cannot be placed in the config registry.

    Chat-tier dispatch refuses to silently default to the teaparty repo
    — an unknown member is a configuration error and must surface.
    """


def resolve_launch_placement(
    member: str,
    teaparty_home: str,
) -> tuple[str, str]:
    """Walk the config registry to find where a member should launch.

    Returns ``(launch_cwd, scope)`` — the repo the chat-tier agent
    launches in, and the config scope its definition lives under.

    The scope pairs with ``launch_cwd``: management members launch at
    the teaparty repo under ``management/agents/{name}/``; project
    members launch at the project repo under ``project/agents/{name}/``.
    Without returning both, the caller must guess — and guessing
    produces stale-copy bugs like the one we just deleted, where a
    project lead was served from ``management/agents/`` because the
    name match short-circuited the registry walk.
    """
    repo_root = os.path.dirname(os.path.abspath(teaparty_home))

    try:
        team = load_management_team(teaparty_home=teaparty_home)
    except FileNotFoundError as exc:
        raise LaunchCwdNotResolved(
            f'resolve_launch_placement({member!r}): management team config '
            f'missing ({exc})'
        ) from exc

    # 1. Management lead
    if team.lead and member == team.lead:
        return repo_root, 'management'

    # 2. Management-level members.agents
    if member in (team.members_agents or []):
        return repo_root, 'management'

    # 3. Management workgroups (lead or member)
    try:
        from teaparty.config.config_reader import load_management_workgroups
        mgmt_workgroups = load_management_workgroups(team, teaparty_home)
    except Exception:
        mgmt_workgroups = []
    for wg in mgmt_workgroups:
        if wg.lead == member:
            return repo_root, 'management'
        if member in (wg.members_agents or []):
            return repo_root, 'management'

    # 4. Each project: lead, workgroup leads, workgroup members
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
        full_config = (
            os.path.join(project_path, config_path) if config_path else None
        )

        try:
            project_team = load_project_team(
                project_path, config_path=full_config,
            )
        except FileNotFoundError:
            continue

        if project_team.lead == member:
            return project_path, 'project'

        try:
            workgroups = resolve_workgroups(
                project_team.workgroups,
                project_dir=project_path,
                teaparty_home=teaparty_home,
            )
        except Exception:
            workgroups = []
        for wg in workgroups:
            if wg.lead == member:
                return project_path, 'project'
            if member in (wg.members_agents or []):
                return project_path, 'project'

    raise LaunchCwdNotResolved(
        f'{member!r} is not registered in the management config '
        f'team, management workgroups, or any registered project roster '
        f'(under {teaparty_home}).'
    )


def resolve_launch_cwd(member: str, teaparty_home: str) -> str:
    """Return the launch cwd for a member (scope-agnostic wrapper).

    Most callers want both cwd and scope — prefer
    :func:`resolve_launch_placement`.  This wrapper exists for legacy
    callers that only need the cwd.
    """
    cwd, _scope = resolve_launch_placement(member, teaparty_home)
    return cwd


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
            from teaparty.config.config_reader import load_management_workgroups
            mgmt_workgroups = load_management_workgroups(team, teaparty_home)
            for wg in mgmt_workgroups:
                if wg.lead == agent_name and wg.members_agents:
                    return True
        except Exception:
            pass

    return False
