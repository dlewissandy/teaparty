"""Constants, admin agent/conversation creation, and direct conversation helpers."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlmodel import Session, select

from teaparty_app.config import settings
from teaparty_app.models import (
    Agent,
    Conversation,
    ConversationParticipant,
    Membership,
    User,
    Workgroup,
)
from teaparty_app.services.admin_workspace.parsing import _parse_temperature

ADMIN_AGENT_SENTINEL = "__system_admin_agent__"
ADMIN_CONVERSATION_NAME = "Administration"
ADMINISTRATION_WORKGROUP_NAME = "Administration"


def admin_agent_name(workgroup: "Workgroup") -> str:
    """Return the display name for a workgroup's admin agent."""
    if workgroup.name == ADMINISTRATION_WORKGROUP_NAME:
        if workgroup.organization_id:
            return "organization-admin"
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
]

SESSION_DELETE_WORKGROUP_KEY = "delete_workgroup_after_response"


def lead_agent_name(workgroup_name: str) -> str:
    """Return the canonical name for a workgroup's lead agent."""
    return f"{workgroup_name}-lead"


def is_lead_agent(agent: Agent) -> bool:
    """Return True if the agent is a workgroup lead."""
    return agent.is_lead


def ensure_lead_agent(session: Session, workgroup: Workgroup) -> tuple[Agent, bool]:
    """Ensure the workgroup has a lead agent, creating one if needed.

    Returns (agent, created) where created is True if a new agent was made.
    """
    from teaparty_app.services.claude_tools import claude_tool_names

    existing = session.exec(
        select(Agent).where(
            Agent.workgroup_id == workgroup.id,
            Agent.is_lead == True,  # noqa: E712
        )
    ).first()

    if existing:
        return existing, False

    agent = Agent(
        workgroup_id=workgroup.id,
        created_by_user_id=workgroup.owner_id,
        name=lead_agent_name(workgroup.name),
        description="",
        role="Team lead",
        personality="Organized and collaborative team coordinator",
        backstory="",
        model="claude-sonnet-4-5",
        temperature=0.7,
        tool_names=claude_tool_names(),
        is_lead=True,
        learning_state={},
        sentiment_state={},
        learned_preferences={},
    )
    session.add(agent)
    session.flush()
    return agent, True


def direct_conversation_key(user_a_id: str, user_b_id: str) -> str:
    ordered = sorted([user_a_id, user_b_id])
    return f"dm:{ordered[0]}:{ordered[1]}"


def direct_conversation_key_user_agent(user_id: str, agent_id: str) -> str:
    return f"dma:{user_id}:{agent_id}"


def is_admin_agent(agent: Agent) -> bool:
    return agent.description == ADMIN_AGENT_SENTINEL


def find_admin_agent(session: Session, workgroup_id: str) -> Agent | None:
    return session.exec(
        select(Agent).where(Agent.workgroup_id == workgroup_id, Agent.description == ADMIN_AGENT_SENTINEL)
    ).first()


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
    changed = False
    expected_admin_name = admin_agent_name(workgroup)
    admin_agent = find_admin_agent(session, workgroup.id)
    if not admin_agent:
        admin_agent = Agent(
            workgroup_id=workgroup.id,
            created_by_user_id=workgroup.owner_id,
            name=expected_admin_name,
            description=ADMIN_AGENT_SENTINEL,
            role="Workgroup administrator",
            personality=(
                "Administrative assistant. Use tools to add/archive/unarchive/clear/remove jobs, "
                "list jobs, list members, list files, add users, add/remove agents, remove members, "
                "add/edit/rename/delete files, and delete workgroups from explicit commands."
            ),
            backstory="You maintain this workspace and enforce ownership and safety constraints.",
            model=settings.admin_agent_model,
            temperature=0.2,
            tool_names=list(ADMIN_TOOL_NAMES),
            response_threshold=0.0,
            learning_state={"engagement_bias": 0.0, "initiative_bias": 0.0, "confidence_bias": 0.4, "brevity_bias": 0.3},
            sentiment_state={"valence": 0.1, "arousal": -0.1, "confidence": 0.4},
            learned_preferences={"engagement_bias": 0.0, "initiative_bias": 0.0, "confidence_bias": 0.4, "brevity_bias": 0.3},
        )
        session.add(admin_agent)
        session.flush()
        changed = True
    else:
        admin_changed = False
        if admin_agent.name != expected_admin_name:
            admin_agent.name = expected_admin_name
            admin_changed = True
        if sorted(admin_agent.tool_names or []) != sorted(ADMIN_TOOL_NAMES):
            admin_agent.tool_names = list(ADMIN_TOOL_NAMES)
            admin_changed = True
        if (admin_agent.model or "").strip() != settings.admin_agent_model:
            admin_agent.model = settings.admin_agent_model
            admin_changed = True
        admin_temp, _ = _parse_temperature(admin_agent.temperature, default=0.7)
        if abs(admin_temp - 0.2) > 1e-9:
            admin_agent.temperature = 0.2
            admin_changed = True
        if not (admin_agent.role or "").strip():
            admin_agent.role = "Workgroup administrator"
            admin_changed = True
        if not (admin_agent.backstory or "").strip():
            admin_agent.backstory = "You maintain this workspace and enforce ownership and safety constraints."
            admin_changed = True
        if not isinstance(admin_agent.learning_state, dict) or not admin_agent.learning_state:
            admin_agent.learning_state = {"engagement_bias": 0.0, "initiative_bias": 0.0, "confidence_bias": 0.4, "brevity_bias": 0.3}
            admin_changed = True
        if not isinstance(admin_agent.sentiment_state, dict) or not admin_agent.sentiment_state:
            admin_agent.sentiment_state = {"valence": 0.1, "arousal": -0.1, "confidence": 0.4}
            admin_changed = True
        if not isinstance(admin_agent.learned_preferences, dict) or not admin_agent.learned_preferences:
            admin_agent.learned_preferences = dict(admin_agent.learning_state or {})
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

    agent = session.get(Agent, agent_id)
    if not agent or agent.workgroup_id != workgroup_id:
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
