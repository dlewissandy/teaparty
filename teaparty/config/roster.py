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
    resolve_workgroups,
)


def derive_om_roster(
    teaparty_home: str,
    *,
    agents_dir: str = '',
) -> dict[str, dict[str, Any]]:
    """Derive the Office Manager's roster from teaparty.yaml.

    Single source of truth for "who is on the OM's team."  Used by
    routing (``build_session_dispatcher``) to authorize Sends, by
    ``list_team_members_handler`` to report membership to the OM, and
    by anything else that needs to know who the OM dispatches to.

    Returns a dict keyed by the member's agent name (their identity
    everywhere else in the system).  Each value carries:

      * ``role``: one of ``project-lead`` / ``workgroup-lead`` / ``proxy``.
      * ``description``: a default description, sourced from project
        / workgroup config or a proxy template.  Callers that want
        agent.md frontmatter override this.
      * Source info: ``project`` (for project leads), ``workgroup``
        (for workgroup leads), or ``human`` (for proxy).

    The roster includes:

      * **Project leads** — one entry per ``members.projects`` whose
        project YAML declares a ``lead``.
      * **Management workgroup leads** — one entry per workgroup
        declared in ``members.workgroups`` whose YAML declares a
        ``lead``.
      * **Proxy** — one entry per declared human (``humans:``).

    Catalog ≠ membership: workgroups registered in the top-level
    ``workgroups:`` catalog but not declared under
    ``members.workgroups`` are NOT in the roster.

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

    # Project leads — one entry per ``members.projects`` with a declared lead.
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
            roster[project_team.lead] = {
                'role': 'project-lead',
                'project': project_name,
                'description': project_team.description or project_name,
            }

    # Management workgroup leads — declared via ``members.workgroups``.
    # ``member_workgroups`` filters the catalog to declared members.
    try:
        from teaparty.config.config_reader import member_workgroups
        for wg in member_workgroups(team, teaparty_home=teaparty_home):
            if wg.lead:
                roster[wg.lead] = {
                    'role': 'workgroup-lead',
                    'workgroup': wg.name,
                    'description': wg.description or wg.name,
                }
    except Exception:
        pass

    # Proxy — one entry per declared human.
    for human in team.humans:
        roster['proxy'] = {
            'role': 'proxy',
            'human': human.name,
            'description': f'Human proxy for {human.name}',
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
    dispatcher propagated its own scope.

    Resolution order (same as ``resolve_launch_cwd``):
      1. Management lead or member → (teaparty repo, 'management').
      2. Management workgroup lead or member → (teaparty repo, 'management').
      3. Project lead, workgroup lead, or workgroup member →
         (project repo, 'project').

    Raises:
        LaunchCwdNotResolved: member not found anywhere in the registry.
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
        f'resolve_launch_placement({member!r}): not found in management '
        f'team, management workgroups, or any registered project roster '
        f'under {teaparty_home}'
    )


def resolve_launch_cwd(
    member: str,
    teaparty_home: str,
) -> str:
    """Return the launch cwd for a member (scope-agnostic wrapper).

    Most callers want both cwd and scope — prefer
    :func:`resolve_launch_placement`. This wrapper exists for legacy
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
            mgmt_workgroups = load_management_workgroups(team, teaparty_home)
            for wg in mgmt_workgroups:
                if wg.lead == agent_name and wg.members_agents:
                    return True
        except Exception:
            pass

    return False


