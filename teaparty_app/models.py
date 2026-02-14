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
    created_at: datetime = Field(default_factory=utc_now)


class Workgroup(SQLModel, table=True):
    __tablename__ = "workgroups"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    files: list[JSONDict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    owner_id: str = Field(foreign_key="users.id", index=True)
    is_discoverable: bool = Field(default=False, index=True)
    service_description: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)


class Membership(SQLModel, table=True):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workgroup_id", "user_id", name="uq_membership"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    role: str = Field(default="member")
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
    model: str = Field(default="claude-sonnet-4-5")
    temperature: float = Field(default=0.7)
    verbosity: float = Field(default=0.5)
    tool_names: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    response_threshold: float = Field(default=0.55)
    follow_up_minutes: int = Field(default=60)
    learning_state: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    sentiment_state: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    learned_preferences: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    icon: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: str = Field(default_factory=new_id, primary_key=True)
    workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    created_by_user_id: str = Field(foreign_key="users.id", index=True)
    kind: str = Field(default="topic", index=True)
    topic: str = Field(default="general")
    name: str = Field(default="general")
    description: str = Field(default="")
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
    sender_agent_id: str | None = Field(default=None, foreign_key="agents.id", index=True)
    content: str = Field()
    requires_response: bool = Field(default=False)
    response_to_message_id: str | None = Field(default=None, foreign_key="messages.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)


class AgentFollowUpTask(SQLModel, table=True):
    __tablename__ = "agent_followup_tasks"

    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(foreign_key="conversations.id", index=True)
    agent_id: str = Field(foreign_key="agents.id", index=True)
    origin_message_id: str = Field(foreign_key="messages.id", index=True)
    waiting_on_sender_type: str = Field(default="user")
    waiting_on_user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    waiting_on_agent_id: str | None = Field(default=None, foreign_key="agents.id", index=True)
    reason: str = Field(default="awaiting response")
    due_at: datetime = Field(index=True)
    status: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(default=None)


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


class ToolDefinition(SQLModel, table=True):
    __tablename__ = "tool_definitions"

    id: str = Field(default_factory=new_id, primary_key=True)
    workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    created_by_user_id: str = Field(foreign_key="users.id", index=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    tool_type: str = Field(default="prompt")  # "prompt" or "webhook"
    prompt_template: str = Field(default="")
    webhook_url: str = Field(default="")
    webhook_method: str = Field(default="POST")
    webhook_headers: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    webhook_timeout_seconds: int = Field(default=30)
    input_schema: JSONDict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    is_shared: bool = Field(default=False)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)


class ToolGrant(SQLModel, table=True):
    __tablename__ = "tool_grants"
    __table_args__ = (
        UniqueConstraint("tool_definition_id", "grantee_workgroup_id", name="uq_tool_grant"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    tool_definition_id: str = Field(foreign_key="tool_definitions.id", index=True)
    grantee_workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    granted_by_user_id: str = Field(foreign_key="users.id", index=True)
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
