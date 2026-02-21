"""SQLModel table definitions for all domain entities.

Exports every ORM model (User, Organization, Workgroup, Agent, Conversation,
Message, etc.) plus the ``new_id`` and ``utc_now`` factory helpers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column, String, UniqueConstraint
from sqlmodel import Field, SQLModel


JSONDict = dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(default_factory=new_id, primary_key=True)
    email: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    name: str = Field(default="")
    picture: str = Field(default="")
    preferences: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    is_system_admin: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)


class Organization(SQLModel, table=True):
    __tablename__ = "organizations"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    icon_url: str = Field(default="")
    owner_id: str = Field(foreign_key="users.id", index=True)
    operations_workgroup_id: str | None = Field(default=None, foreign_key="workgroups.id")
    files: list[JSONDict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    service_description: str = Field(default="")
    is_accepting_engagements: bool = Field(default=False)
    is_discoverable: bool = Field(default=True)
    engagement_base_fee: float = Field(default=0.0)
    engagement_markup_pct: float = Field(default=5.0)
    created_at: datetime = Field(default_factory=utc_now)


class Workgroup(SQLModel, table=True):
    __tablename__ = "workgroups"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    files: list[JSONDict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    owner_id: str = Field(foreign_key="users.id", index=True)
    organization_id: str | None = Field(default=None, foreign_key="organizations.id", index=True)
    is_discoverable: bool = Field(default=False, index=True)
    service_description: str = Field(default="")
    workspace_enabled: bool = Field(default=False)
    team_model: str = Field(default="sonnet")
    team_permission_mode: str = Field(default="acceptEdits")
    team_max_turns: int = Field(default=30)
    team_max_cost_usd: float | None = Field(default=None)
    team_max_time_seconds: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class Workspace(SQLModel, table=True):
    __tablename__ = "workspaces"

    id: str = Field(default_factory=new_id, primary_key=True)
    workgroup_id: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    repo_path: str
    main_worktree_path: str
    status: str = Field(default="active")
    error_message: str = Field(default="")
    last_synced_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class WorkspaceWorktree(SQLModel, table=True):
    __tablename__ = "workspace_worktrees"
    __table_args__ = (UniqueConstraint("workspace_id", "conversation_id", name="uq_worktree_conv"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    conversation_id: str = Field(foreign_key="conversations.id", index=True)
    branch_name: str = Field(index=True)
    worktree_path: str
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=utc_now)
    merged_at: datetime | None = Field(default=None)
    removed_at: datetime | None = Field(default=None)


class Membership(SQLModel, table=True):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workgroup_id", "user_id", name="uq_membership"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    role: str = Field(default="member")
    budget_limit_usd: float | None = Field(default=None)
    budget_used_usd: float = Field(default=0.0)
    budget_refreshed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class Invite(SQLModel, table=True):
    __tablename__ = "invites"

    id: str = Field(default_factory=new_id, primary_key=True)
    workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    invited_by_user_id: str = Field(foreign_key="users.id", index=True)
    email: str = Field(index=True)
    token: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    status: str = Field(default="pending")
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = Field(default=None)
    accepted_at: datetime | None = Field(default=None)


class OrgMembership(SQLModel, table=True):
    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_org_membership"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    organization_id: str = Field(foreign_key="organizations.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    role: str = Field(default="member")  # "owner" | "member"
    created_at: datetime = Field(default_factory=utc_now)


class OrgInvite(SQLModel, table=True):
    __tablename__ = "org_invites"

    id: str = Field(default_factory=new_id, primary_key=True)
    organization_id: str = Field(foreign_key="organizations.id", index=True)
    invited_by_user_id: str = Field(foreign_key="users.id", index=True)
    email: str = Field(index=True)
    token: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    status: str = Field(default="pending")  # pending | accepted | declined | cancelled | expired
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = Field(default=None)
    accepted_at: datetime | None = Field(default=None)


class Agent(SQLModel, table=True):
    __tablename__ = "agents"

    id: str = Field(default_factory=new_id, primary_key=True)
    workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    created_by_user_id: str = Field(foreign_key="users.id", index=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    role: str = Field(default="")
    personality: str = Field(default="Professional and concise")
    backstory: str = Field(default="")
    model: str = Field(default="sonnet")
    temperature: float = Field(default=0.7)
    verbosity: float = Field(default=0.5)
    tool_names: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    response_threshold: float = Field(default=0.55)
    learning_state: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    sentiment_state: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    learned_preferences: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    max_turns: int = Field(default=3)
    is_lead: bool = Field(default=False)
    icon: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: str = Field(default_factory=new_id, primary_key=True)
    workgroup_id: str | None = Field(default=None, foreign_key="workgroups.id", index=True)
    organization_id: str | None = Field(default=None, foreign_key="organizations.id", index=True)
    created_by_user_id: str = Field(foreign_key="users.id", index=True)
    kind: str = Field(default="job", index=True)
    topic: str = Field(default="general")
    name: str = Field(default="general")
    description: str = Field(default="")
    claude_session_id: str | None = Field(default=None)
    is_archived: bool = Field(default=False, index=True)
    archived_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class ConversationParticipant(SQLModel, table=True):
    __tablename__ = "conversation_participants"

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(foreign_key="conversations.id", index=True)
    user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    agent_id: str | None = Field(default=None, foreign_key="agents.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(foreign_key="conversations.id", index=True)
    sender_type: str = Field(index=True)
    sender_user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    sender_agent_id: str | None = Field(default=None, index=True)
    content: str = Field()
    requires_response: bool = Field(default=False)
    response_to_message_id: str | None = Field(default=None, foreign_key="messages.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)


class AgentLearningEvent(SQLModel, table=True):
    __tablename__ = "agent_learning_events"

    id: str = Field(default_factory=new_id, primary_key=True)
    agent_id: str = Field(foreign_key="agents.id", index=True)
    message_id: str = Field(foreign_key="messages.id", index=True)
    signal_type: str = Field(index=True)
    value: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)


class AgentMemory(SQLModel, table=True):
    __tablename__ = "agent_memories"

    id: str = Field(default_factory=new_id, primary_key=True)
    agent_id: str = Field(foreign_key="agents.id", index=True)
    conversation_id: str = Field(foreign_key="conversations.id", index=True)
    memory_type: str = Field(index=True)  # "insight", "correction", "pattern", "domain_knowledge"
    content: str = Field()
    source_summary: str = Field(default="")
    confidence: float = Field(default=0.7)
    created_at: datetime = Field(default_factory=utc_now)


class CrossGroupTask(SQLModel, table=True):
    __tablename__ = "cross_group_tasks"

    id: str = Field(default_factory=new_id, primary_key=True)
    source_workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    target_workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    requested_by_user_id: str = Field(foreign_key="users.id", index=True)

    status: str = Field(default="requested", index=True)
    title: str = Field()
    scope: str = Field(default="")
    requirements: str = Field(default="")
    terms: str = Field(default="")

    target_conversation_id: str | None = Field(default=None, foreign_key="conversations.id", index=True)
    source_conversation_id: str | None = Field(default=None, foreign_key="conversations.id", index=True)

    created_at: datetime = Field(default_factory=utc_now)
    accepted_at: datetime | None = Field(default=None)
    declined_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    satisfied_at: datetime | None = Field(default=None)


class CrossGroupTaskMessage(SQLModel, table=True):
    __tablename__ = "cross_group_task_messages"

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(foreign_key="cross_group_tasks.id", index=True)
    sender_user_id: str = Field(foreign_key="users.id", index=True)
    sender_workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    content: str = Field()
    created_at: datetime = Field(default_factory=utc_now)


class LLMUsageEvent(SQLModel, table=True):
    __tablename__ = "llm_usage_events"

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(foreign_key="conversations.id", index=True)
    agent_id: str | None = Field(default=None, foreign_key="agents.id", index=True)
    model: str = Field(default="")
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    purpose: str = Field(default="reply")
    duration_ms: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)


class SeedRecord(SQLModel, table=True):
    __tablename__ = "seed_records"
    __table_args__ = (UniqueConstraint("seed_key", name="uq_seed_key"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    seed_key: str = Field(index=True)
    entity_type: str = Field(default="")
    entity_id: str = Field(default="")
    seed_version: int = Field(default=1)
    checksum: str = Field(default="")
    applied_at: datetime = Field(default_factory=utc_now)


class Engagement(SQLModel, table=True):
    __tablename__ = "engagements"

    id: str = Field(default_factory=new_id, primary_key=True)
    source_workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    target_workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    proposed_by_user_id: str = Field(foreign_key="users.id", index=True)

    status: str = Field(default="proposed", index=True)
    title: str = Field()
    scope: str = Field(default="")
    requirements: str = Field(default="")
    terms: str = Field(default="")
    deliverables: str = Field(default="")
    files: list[JSONDict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))

    source_conversation_id: str | None = Field(default=None, foreign_key="conversations.id", index=True)
    target_conversation_id: str | None = Field(default=None, foreign_key="conversations.id", index=True)

    created_at: datetime = Field(default_factory=utc_now)
    accepted_at: datetime | None = Field(default=None)
    declined_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    reviewed_at: datetime | None = Field(default=None)
    cancelled_at: datetime | None = Field(default=None)

    review_rating: str | None = Field(default=None)
    review_feedback: str = Field(default="")

    agreed_price_credits: float | None = Field(default=None)
    payment_status: str = Field(default="none")  # none | escrowed | paid | refunded


class EngagementSyncedMessage(SQLModel, table=True):
    __tablename__ = "engagement_synced_messages"
    __table_args__ = (
        UniqueConstraint("origin_message_id", "synced_message_id", name="uq_engagement_synced_message"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    engagement_id: str = Field(foreign_key="engagements.id", index=True)
    origin_message_id: str = Field(foreign_key="messages.id", index=True)
    synced_message_id: str = Field(foreign_key="messages.id", index=True)
    direction: str = Field(index=True)  # "source_to_target" | "target_to_source"
    created_at: datetime = Field(default_factory=utc_now)


class AgentTodoItem(SQLModel, table=True):
    __tablename__ = "agent_todo_items"

    id: str = Field(default_factory=new_id, primary_key=True)
    agent_id: str = Field(foreign_key="agents.id", index=True)
    workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    conversation_id: str | None = Field(default=None, foreign_key="conversations.id", index=True)
    title: str = Field()
    description: str = Field(default="")
    status: str = Field(default="pending", index=True)  # pending | in_progress | done | cancelled
    priority: str = Field(default="medium")  # low | medium | high | urgent
    trigger_type: str = Field(default="manual")  # time | job_stall | message_match | file_changed | job_resolved | todo_completed | manual
    trigger_config: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    triggered_at: datetime | None = Field(default=None)
    due_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(default=None)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(default_factory=new_id, primary_key=True)
    title: str = Field()
    scope: str = Field(default="")
    status: str = Field(default="in_progress", index=True)  # in_progress | completed | cancelled
    engagement_id: str | None = Field(default=None, foreign_key="engagements.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    conversation_id: str | None = Field(default=None, foreign_key="conversations.id", index=True)
    created_by_agent_id: str | None = Field(default=None, foreign_key="agents.id", index=True)
    deliverables: str = Field(default="")
    files: list[JSONDict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(default=None)
    max_rounds: int | None = Field(default=None)
    permission_mode: str = Field(default="acceptEdits")


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(default_factory=new_id, primary_key=True)
    organization_id: str = Field(foreign_key="organizations.id", index=True)
    conversation_id: str | None = Field(default=None, foreign_key="conversations.id", index=True)
    created_by_user_id: str = Field(foreign_key="users.id", index=True)
    name: str = Field(default="Untitled Project")
    prompt: str = Field(default="")
    status: str = Field(default="pending", index=True)  # pending | in_progress | completed | cancelled
    model: str = Field(default="sonnet")
    max_turns: int = Field(default=30)
    permission_mode: str = Field(default="plan")
    max_cost_usd: float | None = Field(default=None)
    max_time_seconds: int | None = Field(default=None)
    max_tokens: int | None = Field(default=None)
    workgroup_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(default=None)


class AgentTask(SQLModel, table=True):
    __tablename__ = "agent_tasks"

    id: str = Field(default_factory=new_id, primary_key=True)
    title: str = Field()
    description: str = Field(default="")
    status: str = Field(default="in_progress", index=True)  # in_progress | completed | cancelled
    agent_id: str = Field(foreign_key="agents.id", index=True)
    workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    conversation_id: str | None = Field(default=None, foreign_key="conversations.id", index=True)
    created_by_user_id: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(default=None)


class SyncedMessage(SQLModel, table=True):
    __tablename__ = "synced_messages"
    __table_args__ = (
        UniqueConstraint("source_message_id", "mirror_message_id", name="uq_synced_message"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(foreign_key="cross_group_tasks.id", index=True)
    source_message_id: str = Field(foreign_key="messages.id", index=True)
    mirror_message_id: str = Field(foreign_key="messages.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)


class Partnership(SQLModel, table=True):
    __tablename__ = "partnerships"

    id: str = Field(default_factory=new_id, primary_key=True)
    source_org_id: str = Field(foreign_key="organizations.id", index=True)
    target_org_id: str = Field(foreign_key="organizations.id", index=True)
    proposed_by_user_id: str = Field(foreign_key="users.id", index=True)
    status: str = Field(default="proposed", index=True)  # proposed | accepted | declined | revoked
    direction: str = Field(default="bidirectional")  # bidirectional | source_to_target | target_to_source
    message: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)
    accepted_at: datetime | None = Field(default=None)
    revoked_at: datetime | None = Field(default=None)


class OrgBalance(SQLModel, table=True):
    __tablename__ = "org_balances"

    id: str = Field(default_factory=new_id, primary_key=True)
    organization_id: str = Field(
        sa_column=Column(String, unique=True, index=True, nullable=False)
    )
    balance_credits: float = Field(default=0.0)
    updated_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)


class PaymentTransaction(SQLModel, table=True):
    __tablename__ = "payment_transactions"

    id: str = Field(default_factory=new_id, primary_key=True)
    organization_id: str = Field(foreign_key="organizations.id", index=True)
    engagement_id: str | None = Field(default=None, foreign_key="engagements.id", index=True)
    transaction_type: str = Field(index=True)  # credit | escrow | release | refund
    amount_credits: float = Field(default=0.0)
    balance_after_credits: float = Field(default=0.0)
    counterparty_org_id: str | None = Field(default=None, foreign_key="organizations.id")
    description: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    type: str = Field(index=True)  # attention_needed | engagement_proposed | partnership_proposed | job_completed
    title: str = Field()
    body: str = Field(default="")
    source_conversation_id: str | None = Field(default=None, foreign_key="conversations.id")
    source_job_id: str | None = Field(default=None, foreign_key="jobs.id")
    source_engagement_id: str | None = Field(default=None, foreign_key="engagements.id")
    source_partnership_id: str | None = Field(default=None, foreign_key="partnerships.id")
    is_read: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now)
