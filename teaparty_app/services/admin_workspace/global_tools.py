"""Global admin tool implementations for the Administration workgroup."""

from __future__ import annotations

import json
import logging

from sqlalchemy import func
from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    AgentWorkgroup,
    Conversation,
    Membership,
    Organization,
    Partnership,
    User,
    Workgroup,
    utc_now,
)
from teaparty_app.services.admin_workspace.bootstrap import (
    ADMIN_AGENT_SENTINEL,
    ADMIN_TEAM_NAMES,
    ADMINISTRATION_WORKGROUP_NAME,
)
from teaparty_app.services.claude_tools import all_tool_names, claude_tool_names
from teaparty_app.services.workgroup_templates import list_workgroup_templates

logger = logging.getLogger(__name__)


def _resolve_organization_by_name(
    session: Session, owner_id: str, org_name: str
) -> Organization | None:
    """Lookup an organization by name (case-insensitive) among those owned by the user."""
    normalized = org_name.strip()
    if not normalized:
        return None
    return session.exec(
        select(Organization).where(
            Organization.owner_id == owner_id,
            func.lower(Organization.name) == normalized.lower(),
        )
    ).first()


def _resolve_workgroup_by_name(
    session: Session, owner_id: str, workgroup_name: str
) -> Workgroup | None:
    """Lookup a workgroup by name (case-insensitive) among those owned by the user."""
    normalized = workgroup_name.strip()
    if not normalized:
        return None
    return session.exec(
        select(Workgroup).where(
            Workgroup.owner_id == owner_id,
            func.lower(Workgroup.name) == normalized.lower(),
        )
    ).first()


def global_create_organization(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    name = (tool_input.get("name") or "").strip()
    if not name:
        return "Organization name is required."

    description = (tool_input.get("description") or "").strip()

    existing = _resolve_organization_by_name(session, requester_user_id, name)
    if existing:
        return f"Organization '{existing.name}' already exists (id={existing.id})."

    org = Organization(
        name=name,
        description=description,
        owner_id=requester_user_id,
    )
    session.add(org)
    session.flush()
    return f"Created organization '{org.name}' (id={org.id})."


def global_list_organizations(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    orgs = session.exec(
        select(Organization)
        .where(Organization.owner_id == requester_user_id)
        .order_by(Organization.created_at.asc())
    ).all()

    if not orgs:
        return "No organizations found. Use global_create_organization to create one."

    lines = [f"Organizations (count={len(orgs)}):"]
    for org in orgs:
        desc = f" :: {org.description}" if org.description else ""
        lines.append(f"- {org.name} (id={org.id}){desc}")
    return "\n".join(lines)


def global_create_workgroup(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    from teaparty_app.routers.workgroups import (
        _sync_workgroup_storage_for_user,
        create_workgroup_with_template,
    )

    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."

    organization_name = (tool_input.get("organization_name") or "").strip()
    if not organization_name:
        return "Organization name is required. Every workgroup must belong to an organization."
    template_key = (tool_input.get("template_key") or "").strip() or None

    org = _resolve_organization_by_name(session, requester_user_id, organization_name)
    if not org:
        return f"Organization '{organization_name}' not found. Create it first with global_create_organization."
    organization_id = org.id

    # Check for existing workgroup with same name
    existing = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if existing:
        return f"Workgroup '{existing.name}' already exists (id={existing.id})."

    owner = session.get(User, requester_user_id)
    if not owner:
        return "User not found."

    try:
        group = create_workgroup_with_template(
            session=session,
            owner=owner,
            name=workgroup_name,
            template_key=template_key,
            organization_id=organization_id,
        )
    except Exception as exc:
        return f"Error creating workgroup: {exc}"

    session.commit()
    _sync_workgroup_storage_for_user(session, owner)
    session.refresh(group)

    template_note = f" from template '{template_key}'" if template_key else ""
    org_note = f" in organization '{organization_name}'" if organization_name else ""
    return f"Created workgroup '{group.name}' (id={group.id}){template_note}{org_note}."


def global_list_workgroups(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    organization_name = (tool_input.get("organization_name") or "").strip()

    query = (
        select(Workgroup)
        .join(Membership, Membership.workgroup_id == Workgroup.id)
        .where(Membership.user_id == requester_user_id)
    )

    if organization_name:
        org = _resolve_organization_by_name(session, requester_user_id, organization_name)
        if not org:
            return f"Organization '{organization_name}' not found."
        query = query.where(Workgroup.organization_id == org.id)

    workgroups = session.exec(query.order_by(Workgroup.created_at.asc())).all()

    if not workgroups:
        scope = f" in organization '{organization_name}'" if organization_name else ""
        return f"No workgroups found{scope}."

    scope = f" in '{organization_name}'" if organization_name else ""
    lines = [f"Workgroups{scope} (count={len(workgroups)}):"]
    for wg in workgroups:
        agents_count = session.exec(
            select(func.count(Agent.id))
            .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
            .where(
                AgentWorkgroup.workgroup_id == wg.id,
                Agent.description != ADMIN_AGENT_SENTINEL,
            )
        ).one()
        org_label = ""
        if wg.organization_id and not organization_name:
            org = session.get(Organization, wg.organization_id)
            org_label = f" [org={org.name}]" if org else ""
        lines.append(f"- {wg.name} (id={wg.id}, agents={agents_count}){org_label}")
    return "\n".join(lines)


def global_add_agent(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."

    agent_name = (tool_input.get("agent_name") or "").strip()
    if not agent_name:
        return "Agent name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    # Check for duplicate agent name
    existing = session.exec(
        select(Agent)
        .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
        .where(
            AgentWorkgroup.workgroup_id == workgroup.id,
            func.lower(Agent.name) == agent_name.lower(),
            Agent.description != ADMIN_AGENT_SENTINEL,
        )
    ).first()
    if existing:
        return f"Agent '{existing.name}' already exists in '{workgroup.name}' (id={existing.id})."

    prompt = (tool_input.get("prompt") or "").strip()
    description = (tool_input.get("description") or "").strip()
    model = (tool_input.get("model") or "sonnet").strip()
    tool_names = tool_input.get("tools") or []

    if isinstance(tool_names, str):
        tool_names = [t.strip() for t in tool_names.split(",") if t.strip()]

    from teaparty_app.services.agent_workgroups import link_agent
    agent = Agent(
        organization_id=workgroup.organization_id,
        created_by_user_id=requester_user_id,
        name=agent_name,
        description=description,
        prompt=prompt,
        model=model,
        tools=tool_names,
    )
    session.add(agent)
    session.flush()
    link_agent(session, agent.id, workgroup.id)
    return (
        f"Created agent '{agent.name}' in '{workgroup.name}' (id={agent.id}). "
        f"model={agent.model}, prompt={agent.prompt[:40] or '(none)'}."
    )


def global_list_agents(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    agents = session.exec(
        select(Agent)
        .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
        .where(
            AgentWorkgroup.workgroup_id == workgroup.id,
            Agent.description != ADMIN_AGENT_SENTINEL,
        )
        .order_by(Agent.created_at.asc())
    ).all()

    if not agents:
        return f"No agents in '{workgroup.name}'."

    lines = [f"Agents in '{workgroup.name}' (count={len(agents)}):"]
    for agent in agents:
        tools = ", ".join(agent.tools) if agent.tools else "(none)"
        lines.append(
            f"- {agent.name} (id={agent.id}, model={agent.model}, "
            f"prompt={agent.prompt[:40] or '(none)'}, tools=[{tools}])"
        )
    return "\n".join(lines)


def global_add_file(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    from teaparty_app.services.admin_workspace.file_tools import admin_tool_add_file

    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."

    path = (tool_input.get("path") or "").strip()
    if not path:
        return "File path is required."

    content = tool_input.get("content", "")

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    result = admin_tool_add_file(
        session=session,
        workgroup_id=workgroup.id,
        requester_user_id=requester_user_id,
        path=path,
        content=content,
    )
    return f"[{workgroup.name}] {result}"


def global_list_templates(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    templates = list_workgroup_templates()

    if not templates:
        return "No workgroup templates available."

    lines = [f"Available workgroup templates (count={len(templates)}):"]
    for template in templates:
        agents_summary = ", ".join(a["name"] for a in template["agents"]) if template["agents"] else "(none)"
        files_count = len(template["files"])
        lines.append(
            f"- **{template['name']}** (key={template['key']}): "
            f"{template['description'] or '(no description)'}. "
            f"Agents: [{agents_summary}]. Files: {files_count}."
        )
    return "\n".join(lines)


def global_list_available_tools(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    tools = all_tool_names()

    lines = [f"Available tools for '{workgroup.name}' (count={len(tools)}):"]
    for t in tools:
        lines.append(f"- {t}")
    return "\n".join(lines)


def global_update_agent(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."

    agent_name = (tool_input.get("agent_name") or "").strip()
    if not agent_name:
        return "Agent name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    agent = session.exec(
        select(Agent)
        .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
        .where(
            AgentWorkgroup.workgroup_id == workgroup.id,
            func.lower(Agent.name) == agent_name.lower(),
            Agent.description != ADMIN_AGENT_SENTINEL,
        )
    ).first()
    if not agent:
        return f"Agent '{agent_name}' not found in '{workgroup.name}'."

    updated_fields: list[str] = []

    if "prompt" in tool_input:
        agent.prompt = (tool_input["prompt"] or "").strip()
        updated_fields.append("prompt")

    if "permission_mode" in tool_input:
        agent.permission_mode = (tool_input["permission_mode"] or "default").strip()
        updated_fields.append("permission_mode")

    if "model" in tool_input:
        agent.model = (tool_input["model"] or "sonnet").strip()
        updated_fields.append("model")

    if "tools" in tool_input:
        new_tools = tool_input["tools"] or []
        if isinstance(new_tools, str):
            new_tools = [t.strip() for t in new_tools.split(",") if t.strip()]

        agent.tools = list(new_tools)
        updated_fields.append("tools")

    if not updated_fields:
        return f"No fields to update for agent '{agent.name}'."

    session.add(agent)
    session.flush()
    return (
        f"Updated agent '{agent.name}' in '{workgroup.name}': "
        f"changed [{', '.join(updated_fields)}]."
    )


# ---------------------------------------------------------------------------
# CRUD tools (clean names)
# ---------------------------------------------------------------------------


def _resolve_agent_in_workgroup(
    session: Session, workgroup: Workgroup, agent_name: str
) -> Agent | None:
    """Find a non-admin agent by name in a workgroup."""
    return session.exec(
        select(Agent)
        .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
        .where(
            AgentWorkgroup.workgroup_id == workgroup.id,
            func.lower(Agent.name) == agent_name.lower(),
            Agent.description != ADMIN_AGENT_SENTINEL,
        )
    ).first()


def _is_protected_agent(session: Session, agent: Agent, workgroup_id: str) -> str | None:
    """Return an error string if the agent is protected from modification, else None."""
    from teaparty_app.services.admin_workspace.bootstrap import is_admin_agent
    if is_admin_agent(agent):
        return f"Cannot modify admin agent '{agent.name}'."
    lead_link = session.exec(
        select(AgentWorkgroup).where(
            AgentWorkgroup.agent_id == agent.id,
            AgentWorkgroup.workgroup_id == workgroup_id,
            AgentWorkgroup.is_lead == True,  # noqa: E712
        )
    ).first()
    if lead_link:
        return f"Cannot modify lead agent '{agent.name}'."
    return None


# -- Workgroup management ---------------------------------------------------


def edit_workgroup(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    updated: list[str] = []

    if "new_name" in tool_input:
        new_name = (tool_input["new_name"] or "").strip()
        if not new_name:
            return "new_name cannot be empty."
        from teaparty_app.services.admin_workspace.bootstrap import is_system_workgroup
        if is_system_workgroup(workgroup.name):
            return f"Cannot rename system workgroup '{workgroup.name}'."
        workgroup.name = new_name
        updated.append("name")

    if "description" in tool_input:
        # Workgroup doesn't have a description field — store in files as README
        # Actually workgroups don't have a description column. Use service_description.
        pass

    if "service_description" in tool_input:
        workgroup.service_description = (tool_input["service_description"] or "").strip()
        updated.append("service_description")

    if "is_discoverable" in tool_input:
        workgroup.is_discoverable = bool(tool_input["is_discoverable"])
        updated.append("is_discoverable")

    if not updated:
        return f"No fields to update for workgroup '{workgroup.name}'."

    session.add(workgroup)
    session.flush()
    return f"Updated workgroup '{workgroup.name}': changed [{', '.join(updated)}]."


def add_agent_to_workgroup(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    from teaparty_app.services.agent_workgroups import link_agent

    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."
    agent_name = (tool_input.get("agent_name") or "").strip()
    if not agent_name:
        return "Agent name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    # Find agent by name in the same organization
    query = select(Agent).where(
        func.lower(Agent.name) == agent_name.lower(),
        Agent.description != ADMIN_AGENT_SENTINEL,
    )
    if workgroup.organization_id:
        query = query.where(Agent.organization_id == workgroup.organization_id)
    agent = session.exec(query).first()
    if not agent:
        return f"Agent '{agent_name}' not found in organization."

    # Check if already linked
    existing_link = session.exec(
        select(AgentWorkgroup).where(
            AgentWorkgroup.agent_id == agent.id,
            AgentWorkgroup.workgroup_id == workgroup.id,
        )
    ).first()
    if existing_link:
        return f"Agent '{agent.name}' is already in '{workgroup.name}'."

    link_agent(session, agent.id, workgroup.id)
    return f"Added agent '{agent.name}' to '{workgroup.name}'."


def remove_agent_from_workgroup(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    from teaparty_app.services.agent_workgroups import unlink_agent

    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."
    agent_name = (tool_input.get("agent_name") or "").strip()
    if not agent_name:
        return "Agent name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    agent = _resolve_agent_in_workgroup(session, workgroup, agent_name)
    if not agent:
        return f"Agent '{agent_name}' not found in '{workgroup.name}'."

    err = _is_protected_agent(session, agent, workgroup.id)
    if err:
        return err

    unlink_agent(session, agent.id, workgroup.id)
    return f"Removed agent '{agent.name}' from '{workgroup.name}'."


# -- Partnership management -------------------------------------------------


def list_partners(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    organization_name = (tool_input.get("organization_name") or "").strip()
    if not organization_name:
        return "Organization name is required."

    org = _resolve_organization_by_name(session, requester_user_id, organization_name)
    if not org:
        return f"Organization '{organization_name}' not found."

    status_filter = (tool_input.get("status") or "accepted").strip().lower()

    query = select(Partnership).where(Partnership.source_org_id == org.id)
    if status_filter != "all":
        query = query.where(Partnership.status == status_filter)

    partnerships = session.exec(query.order_by(Partnership.created_at.desc())).all()

    if not partnerships:
        return f"No partnerships found for '{org.name}' (status={status_filter})."

    lines = [f"Partnerships for '{org.name}' (count={len(partnerships)}):"]
    for p in partnerships:
        target = session.get(Organization, p.target_org_id)
        target_name = target.name if target else p.target_org_id
        lines.append(
            f"- {target_name} (id={p.id}, status={p.status}, direction={p.direction})"
        )
    return "\n".join(lines)


def find_organization(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    query_str = (tool_input.get("query") or "").strip()
    if not query_str:
        return "Search query is required."

    pattern = f"%{query_str}%"

    # Search owned orgs + discoverable orgs
    owned = session.exec(
        select(Organization).where(
            Organization.owner_id == requester_user_id,
            func.lower(Organization.name).like(pattern.lower()),
        )
    ).all()

    discoverable = session.exec(
        select(Organization).where(
            Organization.is_discoverable == True,  # noqa: E712
            Organization.owner_id != requester_user_id,
            func.lower(Organization.name).like(pattern.lower()),
        )
    ).all()

    results = list(owned) + list(discoverable)
    if not results:
        return f"No organizations found matching '{query_str}'."

    lines = [f"Organizations matching '{query_str}' (count={len(results)}):"]
    for org in results:
        owner_label = "(owned)" if org.owner_id == requester_user_id else "(discoverable)"
        lines.append(f"- {org.name} (id={org.id}) {owner_label}")
    return "\n".join(lines)


def add_partner(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    source_name = (tool_input.get("source_organization_name") or "").strip()
    target_name = (tool_input.get("target_organization_name") or "").strip()
    if not source_name:
        return "Source organization name is required."
    if not target_name:
        return "Target organization name is required."

    source_org = _resolve_organization_by_name(session, requester_user_id, source_name)
    if not source_org:
        return f"Source organization '{source_name}' not found (must be owned by you)."

    # Target can be any org (owned or discoverable)
    target_org = session.exec(
        select(Organization).where(
            func.lower(Organization.name) == target_name.lower(),
        )
    ).first()
    if not target_org:
        return f"Target organization '{target_name}' not found."

    if source_org.id == target_org.id:
        return "Source and target organizations must be different."

    # Check for existing partnership
    existing = session.exec(
        select(Partnership).where(
            Partnership.source_org_id == source_org.id,
            Partnership.target_org_id == target_org.id,
            Partnership.status == "accepted",
        )
    ).first()
    if existing:
        return f"Partnership between '{source_org.name}' and '{target_org.name}' already exists."

    direction = (tool_input.get("direction") or "bidirectional").strip()
    valid_directions = {"bidirectional", "source_to_target", "target_to_source"}
    if direction not in valid_directions:
        return f"Invalid direction. Must be one of: {', '.join(sorted(valid_directions))}"

    partnership = Partnership(
        source_org_id=source_org.id,
        target_org_id=target_org.id,
        proposed_by_user_id=requester_user_id,
        direction=direction,
        status="accepted",
        accepted_at=utc_now(),
    )
    session.add(partnership)
    session.flush()
    return (
        f"Created partnership between '{source_org.name}' and '{target_org.name}' "
        f"(id={partnership.id}, direction={direction})."
    )


def delete_partner(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    source_name = (tool_input.get("source_organization_name") or "").strip()
    target_name = (tool_input.get("target_organization_name") or "").strip()
    if not source_name:
        return "Source organization name is required."
    if not target_name:
        return "Target organization name is required."

    source_org = _resolve_organization_by_name(session, requester_user_id, source_name)
    if not source_org:
        return f"Source organization '{source_name}' not found."

    target_org = session.exec(
        select(Organization).where(
            func.lower(Organization.name) == target_name.lower(),
        )
    ).first()
    if not target_org:
        return f"Target organization '{target_name}' not found."

    partnership = session.exec(
        select(Partnership).where(
            Partnership.source_org_id == source_org.id,
            Partnership.target_org_id == target_org.id,
            Partnership.status == "accepted",
        )
    ).first()
    if not partnership:
        return f"No accepted partnership found between '{source_org.name}' and '{target_org.name}'."

    partnership.status = "revoked"
    partnership.revoked_at = utc_now()
    session.add(partnership)
    session.flush()
    return f"Revoked partnership between '{source_org.name}' and '{target_org.name}'."


# -- Agent management -------------------------------------------------------


def find_agent(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    agent_name = (tool_input.get("agent_name") or "").strip()
    if not agent_name:
        return "Agent name is required."

    organization_name = (tool_input.get("organization_name") or "").strip()

    query = (
        select(Agent, Workgroup)
        .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
        .join(Workgroup, AgentWorkgroup.workgroup_id == Workgroup.id)
        .where(
            Workgroup.owner_id == requester_user_id,
            func.lower(Agent.name).like(f"%{agent_name.lower()}%"),
            Agent.description != ADMIN_AGENT_SENTINEL,
        )
    )

    if organization_name:
        org = _resolve_organization_by_name(session, requester_user_id, organization_name)
        if not org:
            return f"Organization '{organization_name}' not found."
        query = query.where(Workgroup.organization_id == org.id)

    results = session.exec(query).all()
    if not results:
        return f"No agents found matching '{agent_name}'."

    lines = [f"Agents matching '{agent_name}' (count={len(results)}):"]
    for agent, wg in results:
        tools = ", ".join(agent.tools) if agent.tools else "(none)"
        lines.append(
            f"- {agent.name} in '{wg.name}' (id={agent.id}, model={agent.model}, tools=[{tools}])"
        )
    return "\n".join(lines)


def delete_agent(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."
    agent_name = (tool_input.get("agent_name") or "").strip()
    if not agent_name:
        return "Agent name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    agent = _resolve_agent_in_workgroup(session, workgroup, agent_name)
    if not agent:
        return f"Agent '{agent_name}' not found in '{workgroup.name}'."

    err = _is_protected_agent(session, agent, workgroup.id)
    if err:
        return err

    from teaparty_app.services.admin_workspace.member_tools import admin_tool_remove_member
    return admin_tool_remove_member(session, workgroup.id, requester_user_id, agent.name)


def add_tool_to_agent(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."
    agent_name = (tool_input.get("agent_name") or "").strip()
    if not agent_name:
        return "Agent name is required."
    tools = tool_input.get("tools") or []
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",") if t.strip()]
    if not tools:
        return "Tools list is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    agent = _resolve_agent_in_workgroup(session, workgroup, agent_name)
    if not agent:
        return f"Agent '{agent_name}' not found in '{workgroup.name}'."

    err = _is_protected_agent(session, agent, workgroup.id)
    if err:
        return err

    current = list(agent.tools or [])
    added = [t for t in tools if t not in current]
    if not added:
        return f"Agent '{agent.name}' already has all specified tools."

    agent.tools = current + added
    session.add(agent)
    session.flush()
    return f"Added tools [{', '.join(added)}] to agent '{agent.name}'. Tools now: [{', '.join(agent.tools)}]."


def remove_tool_from_agent(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."
    agent_name = (tool_input.get("agent_name") or "").strip()
    if not agent_name:
        return "Agent name is required."
    tools = tool_input.get("tools") or []
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",") if t.strip()]
    if not tools:
        return "Tools list is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    agent = _resolve_agent_in_workgroup(session, workgroup, agent_name)
    if not agent:
        return f"Agent '{agent_name}' not found in '{workgroup.name}'."

    err = _is_protected_agent(session, agent, workgroup.id)
    if err:
        return err

    current = list(agent.tools or [])
    to_remove = set(tools)
    removed = [t for t in tools if t in current]
    if not removed:
        return f"Agent '{agent.name}' does not have any of the specified tools."

    agent.tools = [t for t in current if t not in to_remove]
    session.add(agent)
    session.flush()
    return f"Removed tools [{', '.join(removed)}] from agent '{agent.name}'. Tools now: [{', '.join(agent.tools)}]."


# -- Workflow management -----------------------------------------------------


def _normalize_workflow_path(name: str) -> str:
    """Normalize a workflow name to a path like workflows/<name>.md."""
    name = name.strip()
    if not name.startswith("workflows/"):
        name = f"workflows/{name}"
    if not name.endswith(".md"):
        name = f"{name}.md"
    return name


def list_workflows(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    from teaparty_app.services.admin_workspace.parsing import _normalize_workgroup_files_for_tool

    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    files = _normalize_workgroup_files_for_tool(workgroup)
    workflows = [f for f in files if f["path"].startswith("workflows/") and f["path"].endswith(".md")]

    if not workflows:
        return f"No workflows found in '{workgroup.name}'."

    lines = [f"Workflows in '{workgroup.name}' (count={len(workflows)}):"]
    for wf in workflows:
        lines.append(f"- {wf['path']}")
    return "\n".join(lines)


def create_workflow(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    from teaparty_app.services.admin_workspace.parsing import _normalize_workgroup_files_for_tool
    from uuid import uuid4

    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."
    name = (tool_input.get("name") or "").strip()
    if not name:
        return "Workflow name is required."
    content = tool_input.get("content", "")

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    path = _normalize_workflow_path(name)
    files = _normalize_workgroup_files_for_tool(workgroup)

    # Check for duplicate path
    for f in files:
        if f["path"] == path:
            return f"Workflow '{path}' already exists in '{workgroup.name}'."

    files.append({"id": str(uuid4()), "path": path, "content": content, "topic_id": ""})
    workgroup.files = files
    session.add(workgroup)
    session.flush()
    return f"Created workflow '{path}' in '{workgroup.name}'."


def delete_workflow(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    from teaparty_app.services.admin_workspace.parsing import _normalize_workgroup_files_for_tool

    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."
    name = (tool_input.get("name") or "").strip()
    if not name:
        return "Workflow name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    path = _normalize_workflow_path(name)
    files = _normalize_workgroup_files_for_tool(workgroup)

    new_files = [f for f in files if f["path"] != path]
    if len(new_files) == len(files):
        return f"Workflow '{path}' not found in '{workgroup.name}'."

    workgroup.files = new_files
    session.add(workgroup)
    session.flush()
    return f"Deleted workflow '{path}' from '{workgroup.name}'."


def find_workflow(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    from teaparty_app.services.admin_workspace.parsing import _normalize_workgroup_files_for_tool

    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."
    name = (tool_input.get("name") or "").strip()
    if not name:
        return "Workflow name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    path = _normalize_workflow_path(name)
    files = _normalize_workgroup_files_for_tool(workgroup)

    for f in files:
        if f["path"] == path:
            content = f["content"] or "(empty)"
            return f"Workflow '{path}' in '{workgroup.name}':\n{content}"

    return f"Workflow '{path}' not found in '{workgroup.name}'."
