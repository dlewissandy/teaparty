"""Constants, admin agent/conversation creation, and direct conversation helpers."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlmodel import Session, select

from teaparty_app.config import settings
from teaparty_app.models import (
    Agent,
    AgentWorkgroup,
    Conversation,
    ConversationParticipant,
    Membership,
    User,
    Workgroup,
)

ADMIN_AGENT_SENTINEL = "__system_admin_agent__"
ADMIN_CONVERSATION_NAME = "Administration"
ADMINISTRATION_WORKGROUP_NAME = "Administration"

SYSTEM_WORKGROUP_NAMES = frozenset({"Administration", "Project Management", "Engagement"})


def is_system_workgroup(name: str) -> bool:
    """Return True if this is a mandatory system workgroup name."""
    return name in SYSTEM_WORKGROUP_NAMES


def admin_agent_name(workgroup: "Workgroup") -> str:
    """Return the display name for a workgroup's admin agent (non-org workgroups only)."""
    if workgroup.name == ADMINISTRATION_WORKGROUP_NAME:
        if workgroup.organization_id:
            return _ADMIN_TEAM_LEAD_NAME
        return "system-admin"
    return "workgroup-admin"

ADMIN_TOOL_ADD_JOB = "add_job"
ADMIN_TOOL_ARCHIVE_JOB = "archive_job"
ADMIN_TOOL_UNARCHIVE_JOB = "unarchive_job"
ADMIN_TOOL_ADD_AGENT = "add_agent"
ADMIN_TOOL_ADD_USER = "add_user"
ADMIN_TOOL_LIST_JOBS = "list_jobs"
ADMIN_TOOL_LIST_MEMBERS = "list_members"
ADMIN_TOOL_LIST_FILES = "list_files"
ADMIN_TOOL_CLEAR_JOB_MESSAGES = "clear_job_messages"
ADMIN_TOOL_REMOVE_JOB = "remove_job"
ADMIN_TOOL_REMOVE_MEMBER = "remove_member"
ADMIN_TOOL_ADD_FILE = "add_file"
ADMIN_TOOL_EDIT_FILE = "edit_file"
ADMIN_TOOL_RENAME_FILE = "rename_file"
ADMIN_TOOL_DELETE_FILE = "delete_file"
ADMIN_TOOL_DELETE_WORKGROUP = "delete_workgroup"
ADMIN_TOOL_LIST_TASKS = "list_tasks"
ADMIN_TOOL_ACCEPT_TASK = "accept_task"
ADMIN_TOOL_DECLINE_TASK = "decline_task"
ADMIN_TOOL_COMPLETE_TASK = "complete_task"

ADMIN_TOOL_NAMES = [
    ADMIN_TOOL_ADD_JOB,
    ADMIN_TOOL_ARCHIVE_JOB,
    ADMIN_TOOL_UNARCHIVE_JOB,
    ADMIN_TOOL_ADD_AGENT,
    ADMIN_TOOL_ADD_USER,
    ADMIN_TOOL_LIST_JOBS,
    ADMIN_TOOL_LIST_MEMBERS,
    ADMIN_TOOL_LIST_FILES,
    ADMIN_TOOL_CLEAR_JOB_MESSAGES,
    ADMIN_TOOL_REMOVE_JOB,
    ADMIN_TOOL_REMOVE_MEMBER,
    ADMIN_TOOL_ADD_FILE,
    ADMIN_TOOL_EDIT_FILE,
    ADMIN_TOOL_RENAME_FILE,
    ADMIN_TOOL_DELETE_FILE,
    ADMIN_TOOL_DELETE_WORKGROUP,
    ADMIN_TOOL_LIST_TASKS,
    ADMIN_TOOL_ACCEPT_TASK,
    ADMIN_TOOL_DECLINE_TASK,
    ADMIN_TOOL_COMPLETE_TASK,
]

# Admin team agent names — used for runtime identification of admin agents.
# Agent creation is driven by seeds/defaults/organization.yaml via org_defaults.py.
ADMIN_TEAM_NAMES = frozenset({
    "administration-lead", "workgroup-admin", "organization-admin",
    "partner-admin", "workflow-admin",
})

GLOBAL_TOOL_CREATE_ORGANIZATION = "global_create_organization"
GLOBAL_TOOL_LIST_ORGANIZATIONS = "global_list_organizations"
GLOBAL_TOOL_CREATE_WORKGROUP = "global_create_workgroup"
GLOBAL_TOOL_LIST_WORKGROUPS = "global_list_workgroups"
GLOBAL_TOOL_ADD_AGENT = "global_add_agent"
GLOBAL_TOOL_LIST_AGENTS = "global_list_agents"
GLOBAL_TOOL_ADD_JOB = "global_add_job"
GLOBAL_TOOL_LIST_JOBS = "global_list_jobs"
GLOBAL_TOOL_ADD_FILE = "global_add_file"
GLOBAL_TOOL_LIST_TEMPLATES = "global_list_templates"
GLOBAL_TOOL_LIST_AVAILABLE_TOOLS = "global_list_available_tools"
GLOBAL_TOOL_UPDATE_AGENT = "global_update_agent"

# CRUD tools (clean names, no global_ prefix)
GLOBAL_TOOL_EDIT_WORKGROUP = "edit_workgroup"
GLOBAL_TOOL_ADD_AGENT_TO_WORKGROUP = "add_agent_to_workgroup"
GLOBAL_TOOL_REMOVE_AGENT_FROM_WORKGROUP = "remove_agent_from_workgroup"

GLOBAL_TOOL_LIST_PARTNERS = "list_partners"
GLOBAL_TOOL_FIND_ORGANIZATION = "find_organization"
GLOBAL_TOOL_ADD_PARTNER = "add_partner"
GLOBAL_TOOL_DELETE_PARTNER = "delete_partner"

GLOBAL_TOOL_FIND_AGENT = "find_agent"
GLOBAL_TOOL_DELETE_AGENT = "delete_agent"
GLOBAL_TOOL_ADD_TOOL_TO_AGENT = "add_tool_to_agent"
GLOBAL_TOOL_REMOVE_TOOL_FROM_AGENT = "remove_tool_from_agent"

GLOBAL_TOOL_LIST_WORKFLOWS = "list_workflows"
GLOBAL_TOOL_CREATE_WORKFLOW = "create_workflow"
GLOBAL_TOOL_DELETE_WORKFLOW = "delete_workflow"
GLOBAL_TOOL_FIND_WORKFLOW = "find_workflow"

GLOBAL_TOOL_NAMES = [
    GLOBAL_TOOL_CREATE_ORGANIZATION,
    GLOBAL_TOOL_LIST_ORGANIZATIONS,
    GLOBAL_TOOL_CREATE_WORKGROUP,
    GLOBAL_TOOL_LIST_WORKGROUPS,
    GLOBAL_TOOL_ADD_AGENT,
    GLOBAL_TOOL_LIST_AGENTS,
    GLOBAL_TOOL_ADD_JOB,
    GLOBAL_TOOL_LIST_JOBS,
    GLOBAL_TOOL_ADD_FILE,
    GLOBAL_TOOL_LIST_TEMPLATES,
    GLOBAL_TOOL_LIST_AVAILABLE_TOOLS,
    GLOBAL_TOOL_UPDATE_AGENT,
    GLOBAL_TOOL_EDIT_WORKGROUP,
    GLOBAL_TOOL_ADD_AGENT_TO_WORKGROUP,
    GLOBAL_TOOL_REMOVE_AGENT_FROM_WORKGROUP,
    GLOBAL_TOOL_LIST_PARTNERS,
    GLOBAL_TOOL_FIND_ORGANIZATION,
    GLOBAL_TOOL_ADD_PARTNER,
    GLOBAL_TOOL_DELETE_PARTNER,
    GLOBAL_TOOL_FIND_AGENT,
    GLOBAL_TOOL_DELETE_AGENT,
    GLOBAL_TOOL_ADD_TOOL_TO_AGENT,
    GLOBAL_TOOL_REMOVE_TOOL_FROM_AGENT,
    GLOBAL_TOOL_LIST_WORKFLOWS,
    GLOBAL_TOOL_CREATE_WORKFLOW,
    GLOBAL_TOOL_DELETE_WORKFLOW,
    GLOBAL_TOOL_FIND_WORKFLOW,
]

SESSION_DELETE_WORKGROUP_KEY = "delete_workgroup_after_response"


def lead_agent_name(workgroup_name: str) -> str:
    """Return the canonical name for a workgroup's lead agent."""
    return f"{workgroup_name}-lead"


def is_lead_agent(session: Session, agent: Agent, workgroup_id: str) -> bool:
    """Return True if the agent is the lead for the given workgroup."""
    link = session.exec(
        select(AgentWorkgroup).where(
            AgentWorkgroup.agent_id == agent.id,
            AgentWorkgroup.workgroup_id == workgroup_id,
            AgentWorkgroup.is_lead == True,  # noqa: E712
        )
    ).first()
    return link is not None


def ensure_lead_agent(session: Session, workgroup: Workgroup) -> tuple[Agent, bool]:
    """Ensure the workgroup has a lead agent, creating one if needed.

    Returns (agent, created) where created is True if a new agent was made.
    """
    from teaparty_app.services.claude_tools import claude_tool_names
    from teaparty_app.services.agent_workgroups import lead_agent_for_workgroup, link_agent

    existing = lead_agent_for_workgroup(session, workgroup.id)
    if existing:
        return existing, False

    agent = Agent(
        organization_id=workgroup.organization_id,
        created_by_user_id=workgroup.owner_id,
        name=lead_agent_name(workgroup.name),
        description="",
        prompt="",
        model="sonnet",
        tools=claude_tool_names(),
    )
    session.add(agent)
    session.flush()
    link_agent(session, agent.id, workgroup.id, is_lead=True)
    return agent, True


def direct_conversation_key(user_a_id: str, user_b_id: str) -> str:
    ordered = sorted([user_a_id, user_b_id])
    return f"dm:{ordered[0]}:{ordered[1]}"


def direct_conversation_key_user_agent(user_id: str, agent_id: str) -> str:
    return f"dma:{user_id}:{agent_id}"


def is_admin_agent(agent: Agent) -> bool:
    """Return True if the agent is an admin team agent (sentinel-based or by team name + admin tool subset)."""
    if agent.description == ADMIN_AGENT_SENTINEL:
        return True
    # Recognize admin team members by name + admin/global tool subset
    if agent.name in ADMIN_TEAM_NAMES:
        agent_tools = set(agent.tools or [])
        all_admin_tools = set(ADMIN_TOOL_NAMES) | set(GLOBAL_TOOL_NAMES)
        return not agent_tools or agent_tools <= all_admin_tools
    return False


def _find_admin_team_member(session: Session, workgroup_id: str, name: str) -> Agent | None:
    """Find an admin team member by name in a workgroup."""
    return session.exec(
        select(Agent)
        .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
        .where(
            AgentWorkgroup.workgroup_id == workgroup_id,
            Agent.name == name,
        )
    ).first()


def find_admin_agents(session: Session, workgroup_id: str) -> list[Agent]:
    """Find all admin team agents for a workgroup."""
    from sqlalchemy import or_
    return list(session.exec(
        select(Agent)
        .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
        .where(
            AgentWorkgroup.workgroup_id == workgroup_id,
            or_(Agent.description == ADMIN_AGENT_SENTINEL, Agent.name.in_(ADMIN_TEAM_NAMES)),
        )
    ).all())


_ADMIN_TEAM_LEAD_NAME = "administration-lead"


def find_admin_agent(session: Session, workgroup_id: str) -> Agent | None:
    """Find the admin lead agent for a workgroup."""
    agents = find_admin_agents(session, workgroup_id)
    # Prefer the lead agent
    for agent in agents:
        if agent.name == _ADMIN_TEAM_LEAD_NAME:
            return agent
    return agents[0] if agents else None


def find_admin_conversation(session: Session, workgroup_id: str) -> Conversation | None:
    return session.exec(
        select(Conversation).where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "admin",
        )
    ).first()


def ensure_admin_workspace(
    session: Session,
    workgroup: Workgroup,
) -> tuple[Agent, Conversation, bool]:
    from teaparty_app.services.agent_workgroups import link_agent

    changed = False
    is_org_admin = (workgroup.name == ADMINISTRATION_WORKGROUP_NAME and workgroup.organization_id)

    if is_org_admin:
        # Org-level Administration: agents are created by org_defaults.py at org
        # creation time.  Just find the lead agent for conversation linking.
        admin_agent = find_admin_agent(session, workgroup.id)
    else:
        # Non-org workgroups: single admin agent with all tools.
        expected_admin_name = admin_agent_name(workgroup)
        admin_description = ADMIN_AGENT_SENTINEL

        admin_agent = find_admin_agent(session, workgroup.id)
        if not admin_agent:
            admin_agent = Agent(
                organization_id=workgroup.organization_id,
                created_by_user_id=workgroup.owner_id,
                name=expected_admin_name,
                description=admin_description,
                prompt="Workgroup administrator. You maintain this workspace and enforce ownership and safety constraints.",
                model=settings.admin_agent_model,
                tools=list(ADMIN_TOOL_NAMES),
            )
            session.add(admin_agent)
            session.flush()
            link_agent(session, admin_agent.id, workgroup.id, is_lead=False)
            changed = True
        else:
            admin_changed = False
            if admin_agent.name != expected_admin_name:
                admin_agent.name = expected_admin_name
                admin_changed = True
            if admin_agent.description != admin_description:
                admin_agent.description = admin_description
                admin_changed = True
            # Don't overwrite tools — they may have been manually customized.
            if (admin_agent.model or "").strip() != settings.admin_agent_model:
                admin_agent.model = settings.admin_agent_model
                admin_changed = True
            if admin_changed:
                session.add(admin_agent)
                changed = True

    admin_conversation = find_admin_conversation(session, workgroup.id)
    if not admin_conversation:
        admin_conversation = Conversation(
            workgroup_id=workgroup.id,
            created_by_user_id=workgroup.owner_id,
            kind="admin",
            topic=ADMIN_CONVERSATION_NAME,
            name=ADMIN_CONVERSATION_NAME,
            description="System conversation for workgroup administration.",
            is_archived=False,
        )
        session.add(admin_conversation)
        session.flush()
        changed = True

    owner_participant = session.exec(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == admin_conversation.id,
            ConversationParticipant.user_id == workgroup.owner_id,
        )
    ).first()
    if not owner_participant:
        session.add(
            ConversationParticipant(
                conversation_id=admin_conversation.id,
                user_id=workgroup.owner_id,
            )
        )
        changed = True

    if admin_agent:
        agent_participant = session.exec(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == admin_conversation.id,
                ConversationParticipant.agent_id == admin_agent.id,
            )
        ).first()
        if not agent_participant:
            session.add(
                ConversationParticipant(
                    conversation_id=admin_conversation.id,
                    agent_id=admin_agent.id,
                )
            )
            changed = True

    return admin_agent, admin_conversation, changed


def ensure_admin_workspace_for_workgroup_id(session: Session, workgroup_id: str) -> tuple[Agent, Conversation, bool]:
    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")
    return ensure_admin_workspace(session, workgroup)


def ensure_direct_conversation(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    other_user_id: str,
) -> Conversation:
    if requester_user_id == other_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot create direct conversation with self")

    requester_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == workgroup_id,
            Membership.user_id == requester_user_id,
        )
    ).first()
    if not requester_membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workgroup member")

    target_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == workgroup_id,
            Membership.user_id == other_user_id,
        )
    ).first()
    if not target_membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target member not in workgroup")

    topic_key = direct_conversation_key(requester_user_id, other_user_id)
    existing = session.exec(
        select(Conversation).where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "direct",
            Conversation.topic == topic_key,
        )
    ).first()
    if existing:
        return existing

    conversation = Conversation(
        workgroup_id=workgroup_id,
        created_by_user_id=requester_user_id,
        kind="direct",
        topic=topic_key,
        name=topic_key,
        description="",
        is_archived=False,
    )
    session.add(conversation)
    session.flush()

    session.add(
        ConversationParticipant(
            conversation_id=conversation.id,
            user_id=requester_user_id,
        )
    )
    session.add(
        ConversationParticipant(
            conversation_id=conversation.id,
            user_id=other_user_id,
        )
    )

    return conversation


def ensure_direct_conversation_with_agent(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    agent_id: str,
) -> Conversation:
    requester_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == workgroup_id,
            Membership.user_id == requester_user_id,
        )
    ).first()
    if not requester_membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workgroup member")

    from teaparty_app.services.agent_workgroups import agent_in_workgroup
    agent = session.get(Agent, agent_id)
    if not agent or not agent_in_workgroup(session, agent_id, workgroup_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not in workgroup")

    topic_key = direct_conversation_key_user_agent(requester_user_id, agent_id)
    existing = session.exec(
        select(Conversation).where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "direct",
            Conversation.topic == topic_key,
        )
    ).first()
    if existing:
        return existing

    conversation = Conversation(
        workgroup_id=workgroup_id,
        created_by_user_id=requester_user_id,
        kind="direct",
        topic=topic_key,
        name=topic_key,
        description="",
        is_archived=False,
    )
    session.add(conversation)
    session.flush()

    session.add(
        ConversationParticipant(
            conversation_id=conversation.id,
            user_id=requester_user_id,
        )
    )
    session.add(
        ConversationParticipant(
            conversation_id=conversation.id,
            agent_id=agent_id,
        )
    )

    return conversation


def list_members(session: Session, workgroup_id: str) -> list[tuple[Membership, User]]:
    return session.exec(
        select(Membership, User)
        .join(User, Membership.user_id == User.id)
        .where(Membership.workgroup_id == workgroup_id)
        .order_by(Membership.role.desc(), User.name.asc(), User.email.asc())
    ).all()
