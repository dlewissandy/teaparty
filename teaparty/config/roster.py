"""Roster derivation for bus dispatch routing.

ONE public entry point: :func:`derive_team_roster`.  A team is
identified by its **lead**: leads (OM, project leads, workgroup
leads) have 1:1 correspondence with their team.  Given a lead's
agent name, the function returns the **flat** roster of the team
that lead heads — lead + direct members (+ a mesh flag).

Non-lead agents (workgroup members) may belong to multiple teams.
"What team does this agent belong to?" is ill-defined for them and
is not what this function answers.  Pass a lead's name; non-leads
return ``None``.

Routing scope is per-session: each session has its own
``BusDispatcher`` built from this team's flat roster.  No org-wide
tree, no sub-roster nesting — a workgroup loaned to multiple
projects (matrix structure) is one team, and the parent_lead it
reports up to is a *conversation property*, not a team property.

Reporting (``ListTeamMembers`` MCP tool) and routing
(``BusDispatcher`` via ``build_routing_table``) both consume the
result of this one function, so they cannot disagree.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

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
    """Flat roster — describes one team's membership and routing scope.

    The same shape works for the management team (OM as lead), a
    project team (project-lead as lead), or a workgroup (wg-lead as
    lead).  ``build_routing_table`` walks this single team to produce
    the routing pairs.

    No sub-roster nesting: each session builds its own dispatcher
    with its own scope.  A workgroup loaned to multiple projects is
    *one* team in this model, and ``parent_lead`` (the cross-team
    gateway) is set by the conversation context (which project loaned
    it for this session), not baked into a global tree.
    """
    lead: str                              # team's leader (agent name)
    members: list[Member] = field(default_factory=list)
    mesh_among_members: bool = False       # within-team peer-to-peer
    parent_lead: str = ''                  # parent team's leader (cross-team gateway)


# ── Derivation ──────────────────────────────────────────────────────────────

def _team_to_roster(
    *,
    teaparty_home: str,
    project_dir: str = '',
    workgroup_path: str = '',
    parent_lead: str = '',
) -> Roster:
    """Build a single team's flat Roster from its config.

    Internal helper.  Selected by which kwarg is provided:

      * ``workgroup_path`` → workgroup roster (lead + agents, mesh)
      * ``project_dir``    → project roster (lead + workgroup-leads as
                              members; no nesting)
      * neither            → management/OM roster (lead + project-leads
                              + member wg-leads + proxy)

    Public callers must use :func:`derive_team_roster`.
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
        # No sub-roster nesting: a workgroup loaned to multiple projects
        # is one team, not many.  Each workgroup-lead's own session
        # builds the workgroup's roster (with mesh) via its own
        # ``derive_team_roster`` call; the project session only needs
        # the lead↔workgroup-lead member pairs.
        members_lower = {m.lower() for m in proj.members_workgroups}
        members: list[Member] = []
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
        return Roster(
            lead=proj.lead,
            members=members,
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
        mesh_among_members=False,
        parent_lead=parent_lead,
    )


# ── Public entry point ─────────────────────────────────────────────────────


def derive_team_roster(
    lead_name: str,
    teaparty_home: str,
    *,
    parent_lead: str = '',
) -> Roster | None:
    """Return the flat roster of the team headed by ``lead_name``.

    Single public entry point.  A team is identified by its lead;
    leads (OM, project lead, workgroup lead) are in 1:1 correspondence
    with their team.  Direct lookup against the management catalog —
    no global org tree, because a workgroup loaned to multiple
    projects is **one** team (matrix structure), not several.

    The returned roster is **flat**: lead + direct members (and a
    mesh flag when applicable).  Routing within sub-teams is the
    sub-team's own session's concern; each session builds its own
    dispatcher with its own scope.

    ``parent_lead`` is a property of the *conversation context*, not
    of the team.  A workgroup loaned to Comics has parent_lead
    ``comics-lead``; the same workgroup loaned to JokeBook has
    parent_lead ``joke-book-lead``.  Callers that know the context
    (e.g. ``build_session_dispatcher``) pass it in.  When omitted,
    a sensible default is applied for non-matrix cases (project lead
    → OM; mgmt-workgroup lead → OM).

    Returns ``None`` when ``lead_name`` is not a known lead.
    """
    if not lead_name:
        return None

    try:
        team = load_management_team(teaparty_home=teaparty_home)
    except FileNotFoundError:
        return None

    # 1. Management lead.
    if team.lead == lead_name:
        return _team_to_roster(
            teaparty_home=teaparty_home,
            parent_lead=parent_lead,  # typically '' for the OM
        )

    repo_root = os.path.dirname(teaparty_home)

    # 2. Project lead — search every registered project.
    for project_name in team.members_projects:
        project_entry = next(
            (p for p in team.projects if p.get('name') == project_name),
            None,
        )
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
            pt = load_project_team(project_path, config_path=full_config)
        except FileNotFoundError:
            continue
        if pt.lead == lead_name:
            return _team_to_roster(
                teaparty_home=teaparty_home,
                project_dir=project_path,
                parent_lead=parent_lead or team.lead,
            )

    # 3. Management workgroup lead — declared via members.workgroups.
    member_wg_names = {n.lower() for n in team.members_workgroups}
    for entry in team.workgroups:
        if entry.name.lower() not in member_wg_names:
            continue
        wg_path = os.path.join(teaparty_home, 'management', entry.config)
        if not os.path.exists(wg_path):
            continue
        try:
            wg = load_workgroup(wg_path)
        except (FileNotFoundError, OSError):
            continue
        if wg.lead == lead_name:
            return _team_to_roster(
                teaparty_home=teaparty_home,
                workgroup_path=wg_path,
                parent_lead=parent_lead or team.lead,
            )

    # 4. Project workgroup lead — matrix loan: a workgroup may be
    #    referenced by multiple projects, but it is one team.  We
    #    scan referencing projects to find a config path; the team's
    #    membership is identical regardless of which project we found
    #    it through.  ``parent_lead`` for matrix workgroups depends on
    #    conversation context and must be passed by the caller — we
    #    do NOT default it from "first project that referenced it"
    #    because that would arbitrarily pick one of several legitimate
    #    parents.
    for project_name in team.members_projects:
        project_entry = next(
            (p for p in team.projects if p.get('name') == project_name),
            None,
        )
        if project_entry is None:
            continue
        project_path = project_entry.get('path', '')
        if not os.path.isabs(project_path):
            project_path = os.path.join(repo_root, project_path)
        try:
            pt = load_project_team(project_path)
            workgroups = resolve_workgroups(
                pt.workgroups,
                project_dir=project_path,
                teaparty_home=teaparty_home,
            )
        except (FileNotFoundError, OSError):
            continue
        for wg in workgroups:
            if wg.lead == lead_name:
                # Build the workgroup's roster directly from the
                # already-loaded ``Workgroup`` object — we don't need
                # to round-trip through a path.
                return Roster(
                    lead=wg.lead,
                    members=[
                        Member(
                            name=name,
                            role='workgroup-agent',
                            workgroup=wg.name,
                        )
                        for name in wg.members_agents
                    ],
                    mesh_among_members=True,
                    parent_lead=parent_lead,
                )

    return None


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


