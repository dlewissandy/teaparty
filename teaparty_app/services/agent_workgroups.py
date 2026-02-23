"""Helpers for managing agent-workgroup many-to-many relationships."""

from sqlmodel import Session, select

from teaparty_app.models import Agent, AgentWorkgroup


def agents_for_workgroup(session: Session, workgroup_id: str) -> list[Agent]:
    """Return all agents linked to a workgroup."""
    return list(
        session.exec(
            select(Agent)
            .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
            .where(AgentWorkgroup.workgroup_id == workgroup_id)
        ).all()
    )


def link_agent(session: Session, agent_id: str, workgroup_id: str, *, is_lead: bool = False) -> AgentWorkgroup:
    """Link an agent to a workgroup. No-op if already linked."""
    existing = session.exec(
        select(AgentWorkgroup).where(
            AgentWorkgroup.agent_id == agent_id,
            AgentWorkgroup.workgroup_id == workgroup_id,
        )
    ).first()
    if existing:
        return existing
    link = AgentWorkgroup(agent_id=agent_id, workgroup_id=workgroup_id, is_lead=is_lead)
    session.add(link)
    session.flush()
    return link


def unlink_agent(session: Session, agent_id: str, workgroup_id: str) -> None:
    """Remove an agent from a workgroup."""
    link = session.exec(
        select(AgentWorkgroup).where(
            AgentWorkgroup.agent_id == agent_id,
            AgentWorkgroup.workgroup_id == workgroup_id,
        )
    ).first()
    if link:
        session.delete(link)


def agent_in_workgroup(session: Session, agent_id: str, workgroup_id: str) -> bool:
    """Check if an agent is linked to a workgroup."""
    return session.exec(
        select(AgentWorkgroup).where(
            AgentWorkgroup.agent_id == agent_id,
            AgentWorkgroup.workgroup_id == workgroup_id,
        )
    ).first() is not None


def agent_is_lead(session: Session, agent_id: str) -> bool:
    """Check if an agent is a lead in any workgroup."""
    return session.exec(
        select(AgentWorkgroup).where(
            AgentWorkgroup.agent_id == agent_id,
            AgentWorkgroup.is_lead == True,  # noqa: E712
        )
    ).first() is not None


def lead_agent_for_workgroup(session: Session, workgroup_id: str) -> Agent | None:
    """Return the lead agent for a workgroup, or None."""
    return session.exec(
        select(Agent)
        .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
        .where(AgentWorkgroup.workgroup_id == workgroup_id, AgentWorkgroup.is_lead == True)  # noqa: E712
    ).first()


def workgroup_ids_for_agent(session: Session, agent_id: str) -> list[str]:
    """Return all workgroup IDs an agent is linked to."""
    links = session.exec(
        select(AgentWorkgroup.workgroup_id).where(AgentWorkgroup.agent_id == agent_id)
    ).all()
    return list(links)


def agent_read_with_workgroups(session: Session, agent: Agent) -> dict:
    """Build an AgentRead-compatible dict with workgroup_ids populated."""
    wg_ids = workgroup_ids_for_agent(session, agent.id)
    # Check if agent is lead in any workgroup
    is_lead = session.exec(
        select(AgentWorkgroup).where(
            AgentWorkgroup.agent_id == agent.id,
            AgentWorkgroup.is_lead == True,  # noqa: E712
        )
    ).first() is not None
    data = {
        "id": agent.id,
        "organization_id": agent.organization_id,
        "workgroup_ids": wg_ids,
        "name": agent.name,
        "image": agent.image,
        "description": agent.description,
        "prompt": agent.prompt,
        "model": agent.model,
        "tools": list(agent.tools or []),
        "permission_mode": agent.permission_mode,
        "hooks": dict(agent.hooks or {}),
        "memory": agent.memory,
        "background": agent.background,
        "isolation": agent.isolation,
        "is_lead": is_lead,
    }
    return data
