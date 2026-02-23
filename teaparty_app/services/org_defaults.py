"""Template-driven creation of system workgroups and agents for new organizations.

Reads ``seeds/defaults/organization.yaml`` once, then applies it when a new
organization is created.  The YAML is the single source of truth for which
workgroups, agents, and tools every org starts with.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlmodel import Session

from teaparty_app.models import (
    Agent,
    Conversation,
    ConversationParticipant,
    Membership,
    Organization,
    User,
    Workgroup,
)
from teaparty_app.services.agent_workgroups import link_agent

_DEFAULTS_PATH = Path(__file__).parent.parent / "seeds" / "defaults" / "organization.yaml"
_cached: list[dict] | None = None


def load_org_defaults() -> list[dict]:
    """Return the system_workgroups list from the org defaults YAML (cached)."""
    global _cached
    if _cached is None:
        with open(_DEFAULTS_PATH) as fh:
            data = yaml.safe_load(fh) or {}
        _cached = data.get("system_workgroups", [])
    return _cached


def create_system_workgroups(
    session: Session,
    org: Organization,
    owner: User,
) -> dict[str, Workgroup]:
    """Create all system workgroups and their agents for a new organization.

    Returns a dict mapping workgroup name to the created Workgroup.
    """
    from teaparty_app.services.admin_workspace.bootstrap import (
        ADMIN_CONVERSATION_NAME,
        ADMINISTRATION_WORKGROUP_NAME,
    )

    specs = load_org_defaults()
    created: dict[str, Workgroup] = {}

    for wg_spec in specs:
        wg_name = wg_spec["name"]

        wg = Workgroup(name=wg_name, files=[], owner_id=owner.id, organization_id=org.id)
        session.add(wg)
        session.flush()
        session.add(Membership(workgroup_id=wg.id, user_id=owner.id, role="owner"))
        created[wg_name] = wg

        # Create agents from spec
        lead_agent = None
        for agent_spec in wg_spec.get("agents", []):
            is_lead = agent_spec.get("is_lead", False)
            agent = Agent(
                organization_id=org.id,
                created_by_user_id=owner.id,
                name=agent_spec["name"],
                description=agent_spec.get("description", ""),
                prompt=agent_spec.get("prompt", "").strip(),
                model=agent_spec.get("model", "sonnet"),
                tools=list(agent_spec.get("tools", [])),
            )
            session.add(agent)
            session.flush()
            link_agent(session, agent.id, wg.id, is_lead=is_lead)
            if is_lead:
                lead_agent = agent

        # Administration workgroup gets an admin conversation
        if wg_name == ADMINISTRATION_WORKGROUP_NAME and lead_agent:
            conv = Conversation(
                workgroup_id=wg.id,
                created_by_user_id=owner.id,
                kind="admin",
                topic=ADMIN_CONVERSATION_NAME,
                name=ADMIN_CONVERSATION_NAME,
                description="System conversation for workgroup administration.",
                is_archived=False,
            )
            session.add(conv)
            session.flush()
            session.add(ConversationParticipant(conversation_id=conv.id, user_id=owner.id))
            session.add(ConversationParticipant(conversation_id=conv.id, agent_id=lead_agent.id))

    return created
