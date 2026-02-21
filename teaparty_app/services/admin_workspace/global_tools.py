"""Global admin tool implementations for the Administration workgroup."""

from __future__ import annotations

import json
import logging

from sqlalchemy import func
from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    Conversation,
    Membership,
    Organization,
    User,
    Workgroup,
)
from teaparty_app.services.admin_workspace.bootstrap import (
    ADMIN_AGENT_SENTINEL,
    ADMINISTRATION_WORKGROUP_NAME,
)
from teaparty_app.services.claude_tools import claude_tool_names
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
            select(func.count(Agent.id)).where(
                Agent.workgroup_id == wg.id,
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
        select(Agent).where(
            Agent.workgroup_id == workgroup.id,
            func.lower(Agent.name) == agent_name.lower(),
            Agent.description != ADMIN_AGENT_SENTINEL,
        )
    ).first()
    if existing:
        return f"Agent '{existing.name}' already exists in '{workgroup.name}' (id={existing.id})."

    role = (tool_input.get("role") or "").strip()
    personality = (tool_input.get("personality") or "Professional and concise").strip()
    backstory = (tool_input.get("backstory") or "").strip()
    model = (tool_input.get("model") or "sonnet").strip()
    temperature = tool_input.get("temperature", 0.7)
    tool_names = tool_input.get("tool_names") or []

    try:
        temperature = float(temperature)
        temperature = max(0.0, min(2.0, temperature))
    except (TypeError, ValueError):
        temperature = 0.7

    if isinstance(tool_names, str):
        tool_names = [t.strip() for t in tool_names.split(",") if t.strip()]

    agent = Agent(
        workgroup_id=workgroup.id,
        created_by_user_id=requester_user_id,
        name=agent_name,
        description=role,
        role=role,
        personality=personality,
        backstory=backstory,
        model=model,
        temperature=temperature,
        tool_names=tool_names,
    )
    session.add(agent)
    session.flush()
    return (
        f"Created agent '{agent.name}' in '{workgroup.name}' (id={agent.id}). "
        f"model={agent.model}, temperature={agent.temperature}, role={agent.role or '(none)'}."
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
        select(Agent).where(
            Agent.workgroup_id == workgroup.id,
            Agent.description != ADMIN_AGENT_SENTINEL,
        ).order_by(Agent.created_at.asc())
    ).all()

    if not agents:
        return f"No agents in '{workgroup.name}'."

    lines = [f"Agents in '{workgroup.name}' (count={len(agents)}):"]
    for agent in agents:
        tools = ", ".join(agent.tool_names) if agent.tool_names else "(none)"
        lines.append(
            f"- {agent.name} (id={agent.id}, model={agent.model}, "
            f"role={agent.role or '(none)'}, tools=[{tools}])"
        )
    return "\n".join(lines)


def global_add_job(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    from teaparty_app.services.admin_workspace.job_tools import admin_tool_add_job

    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."

    job_name = (tool_input.get("job_name") or "").strip()
    if not job_name:
        return "Job name is required."

    description = (tool_input.get("description") or "").strip()

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    result = admin_tool_add_job(
        session=session,
        workgroup_id=workgroup.id,
        requester_user_id=requester_user_id,
        topic_name=job_name,
        description=description,
    )
    return f"[{workgroup.name}] {result}"


def global_list_jobs(
    session: Session, requester_user_id: str, tool_input: dict
) -> str:
    from teaparty_app.services.admin_workspace.job_tools import admin_tool_list_jobs

    workgroup_name = (tool_input.get("workgroup_name") or "").strip()
    if not workgroup_name:
        return "Workgroup name is required."

    workgroup = _resolve_workgroup_by_name(session, requester_user_id, workgroup_name)
    if not workgroup:
        return f"Workgroup '{workgroup_name}' not found."

    result = admin_tool_list_jobs(
        session=session,
        workgroup_id=workgroup.id,
        status=tool_input.get("status", "open"),
    )
    return f"[{workgroup.name}] {result}"


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

    tools = claude_tool_names()

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
        select(Agent).where(
            Agent.workgroup_id == workgroup.id,
            func.lower(Agent.name) == agent_name.lower(),
            Agent.description != ADMIN_AGENT_SENTINEL,
        )
    ).first()
    if not agent:
        return f"Agent '{agent_name}' not found in '{workgroup.name}'."

    updated_fields: list[str] = []

    if "role" in tool_input:
        agent.role = (tool_input["role"] or "").strip()
        updated_fields.append("role")

    if "personality" in tool_input:
        agent.personality = (tool_input["personality"] or "").strip()
        updated_fields.append("personality")

    if "backstory" in tool_input:
        agent.backstory = (tool_input["backstory"] or "").strip()
        updated_fields.append("backstory")

    if "model" in tool_input:
        agent.model = (tool_input["model"] or "sonnet").strip()
        updated_fields.append("model")

    if "temperature" in tool_input:
        try:
            temp = float(tool_input["temperature"])
            agent.temperature = max(0.0, min(2.0, temp))
        except (TypeError, ValueError):
            agent.temperature = 0.7
        updated_fields.append("temperature")

    if "tool_names" in tool_input:
        new_tools = tool_input["tool_names"] or []
        if isinstance(new_tools, str):
            new_tools = [t.strip() for t in new_tools.split(",") if t.strip()]

        agent.tool_names = list(new_tools)
        updated_fields.append("tool_names")

    if not updated_fields:
        return f"No fields to update for agent '{agent.name}'."

    session.add(agent)
    session.flush()
    return (
        f"Updated agent '{agent.name}' in '{workgroup.name}': "
        f"changed [{', '.join(updated_fields)}]."
    )
