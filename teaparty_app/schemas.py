from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserRead(ORMBaseModel):
    id: str
    email: EmailStr
    name: str
    picture: str
    preferences: dict[str, Any] = {}


class UserPreferencesUpdate(BaseModel):
    preferences: dict[str, Any]


class GoogleLoginRequest(BaseModel):
    id_token: str


class DevLoginRequest(BaseModel):
    email: EmailStr
    name: str = "Developer"


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class WorkgroupFileWrite(BaseModel):
    id: str | None = None
    path: str = Field(min_length=1, max_length=512)
    content: str = ""


class WorkgroupFileRead(BaseModel):
    id: str
    path: str
    content: str


class WorkgroupTemplateAgentWrite(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    role: str = ""
    personality: str = "Professional and concise"
    backstory: str = ""
    model: str = "claude-sonnet-4-5"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    verbosity: float = Field(default=0.5, ge=0.0, le=1.0)
    tool_names: list[str] = Field(default_factory=list)
    response_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    follow_up_minutes: int = Field(default=60, ge=1, le=10080)


class WorkgroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    template_key: str | None = Field(default=None, min_length=1, max_length=80)
    files: list[WorkgroupFileWrite | str] | None = None
    agents: list[WorkgroupTemplateAgentWrite] | None = None


class WorkgroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    files: list[WorkgroupFileWrite | str] | None = None
    is_discoverable: bool | None = None
    service_description: str | None = None


class WorkgroupRead(ORMBaseModel):
    id: str
    name: str
    files: list[WorkgroupFileRead]
    owner_id: str
    is_discoverable: bool = False
    service_description: str = ""
    created_at: datetime


class WorkgroupTemplateFileRead(BaseModel):
    path: str
    content: str


class WorkgroupTemplateAgentRead(WorkgroupTemplateAgentWrite):
    pass


class WorkgroupTemplateRead(BaseModel):
    key: str
    name: str
    description: str
    files: list[WorkgroupTemplateFileRead] = Field(default_factory=list)
    agents: list[WorkgroupTemplateAgentRead] = Field(default_factory=list)


class InviteCreateRequest(BaseModel):
    email: EmailStr


class InviteRead(ORMBaseModel):
    id: str
    workgroup_id: str
    email: EmailStr
    token: str
    status: str
    created_at: datetime


class MemberRead(BaseModel):
    user_id: str
    email: EmailStr
    name: str
    role: str
    picture: str = ""


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    role: str = ""
    personality: str = "Professional and concise"
    backstory: str = ""
    model: str = "claude-sonnet-4-5"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    verbosity: float = Field(default=0.5, ge=0.0, le=1.0)
    tool_names: list[str] = Field(default_factory=list)
    response_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    follow_up_minutes: int = Field(default=60, ge=1, le=10080)
    learning_state: dict[str, Any] = Field(default_factory=dict)
    sentiment_state: dict[str, Any] = Field(default_factory=dict)
    icon: str = ""


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    role: str | None = None
    personality: str | None = None
    backstory: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    verbosity: float | None = Field(default=None, ge=0.0, le=1.0)
    tool_names: list[str] | None = None
    response_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    follow_up_minutes: int | None = Field(default=None, ge=1, le=10080)
    icon: str | None = None


class AgentCloneRequest(BaseModel):
    target_workgroup_id: str | None = None       # None = same workgroup
    name: str | None = None                       # None = original name + " (copy)"
    include_learned_state: bool = False


class AgentRead(ORMBaseModel):
    id: str
    workgroup_id: str
    name: str
    description: str
    role: str
    personality: str
    backstory: str
    model: str
    temperature: float
    verbosity: float
    tool_names: list[str]
    response_threshold: float
    follow_up_minutes: int
    learning_state: dict[str, Any]
    sentiment_state: dict[str, Any]
    learned_preferences: dict[str, Any]
    icon: str = ""


class AgentConversationClearRead(BaseModel):
    conversation_id: str | None
    deleted_messages: int


class ConversationCreateRequest(BaseModel):
    kind: Literal["direct", "topic"]
    topic: str = "general"
    name: str = ""
    description: str = ""
    participant_user_ids: list[str] = Field(default_factory=list)
    participant_agent_ids: list[str] = Field(default_factory=list)


class ConversationUpdateRequest(BaseModel):
    topic: str | None = None
    name: str | None = None
    description: str | None = None


class ConversationRead(ORMBaseModel):
    id: str
    workgroup_id: str
    kind: str
    topic: str
    name: str
    description: str
    is_archived: bool
    archived_at: datetime | None = None
    created_by_user_id: str
    created_at: datetime


class ConversationHistoryClearResponse(BaseModel):
    conversation_id: str
    deleted_messages: int
    deleted_learning_events: int
    deleted_followup_tasks: int
    cleared_response_links: int


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1)
    requires_response: bool | None = None
    response_to_message_id: str | None = None


class MessageRead(ORMBaseModel):
    id: str
    conversation_id: str
    sender_type: str
    sender_user_id: str | None
    sender_agent_id: str | None
    content: str
    requires_response: bool
    response_to_message_id: str | None
    created_at: datetime


class MessageEnvelope(BaseModel):
    posted: MessageRead
    agent_replies: list[MessageRead] = Field(default_factory=list)


class TickResponse(BaseModel):
    created_messages: list[MessageRead]


class ToolDefinitionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    tool_type: Literal["prompt", "webhook"]
    prompt_template: str = ""
    webhook_url: str = ""
    webhook_method: Literal["GET", "POST"] = "POST"
    webhook_headers: dict[str, Any] = Field(default_factory=dict)
    webhook_timeout_seconds: int = Field(default=30, ge=1, le=120)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    is_shared: bool = False


class ToolDefinitionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    tool_type: Literal["prompt", "webhook"] | None = None
    prompt_template: str | None = None
    webhook_url: str | None = None
    webhook_method: Literal["GET", "POST"] | None = None
    webhook_headers: dict[str, Any] | None = None
    webhook_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    input_schema: dict[str, Any] | None = None
    is_shared: bool | None = None
    enabled: bool | None = None


class ToolDefinitionRead(ORMBaseModel):
    id: str
    workgroup_id: str
    created_by_user_id: str
    name: str
    description: str
    tool_type: str
    prompt_template: str
    webhook_url: str
    webhook_method: str
    webhook_headers: dict[str, Any]
    webhook_timeout_seconds: int
    input_schema: dict[str, Any]
    is_shared: bool
    enabled: bool
    created_at: datetime


class ToolGrantCreateRequest(BaseModel):
    grantee_workgroup_id: str


class ToolGrantRead(ORMBaseModel):
    id: str
    tool_definition_id: str
    grantee_workgroup_id: str
    granted_by_user_id: str
    created_at: datetime


class AvailableToolRead(BaseModel):
    name: str
    display_name: str
    description: str
    tool_type: str  # "builtin", "prompt", "webhook"
    source_workgroup_id: str | None = None
    is_shared: bool = False


# --- Cross-Group Task schemas ---


class WorkgroupDirectoryEntry(BaseModel):
    id: str
    name: str
    service_description: str


class CrossGroupTaskCreateRequest(BaseModel):
    target_workgroup_id: str
    title: str = Field(min_length=1, max_length=200)
    scope: str = ""
    requirements: str = ""


class CrossGroupTaskNegotiateRequest(BaseModel):
    content: str = Field(min_length=1)


class CrossGroupTaskRespondRequest(BaseModel):
    action: Literal["accept", "decline"]
    terms: str = ""


class CrossGroupTaskCompleteRequest(BaseModel):
    summary: str = ""


class CrossGroupTaskSatisfactionRequest(BaseModel):
    action: Literal["satisfied", "dissatisfied"]
    feedback: str = ""


class CrossGroupTaskMessageRead(ORMBaseModel):
    id: str
    task_id: str
    sender_user_id: str
    sender_workgroup_id: str
    content: str
    created_at: datetime


class CrossGroupTaskRead(ORMBaseModel):
    id: str
    source_workgroup_id: str
    target_workgroup_id: str
    requested_by_user_id: str
    status: str
    title: str
    scope: str
    requirements: str
    terms: str
    target_conversation_id: str | None = None
    source_conversation_id: str | None = None
    created_at: datetime
    accepted_at: datetime | None = None
    declined_at: datetime | None = None
    completed_at: datetime | None = None
    satisfied_at: datetime | None = None


class CrossGroupTaskDetailRead(CrossGroupTaskRead):
    messages: list[CrossGroupTaskMessageRead] = Field(default_factory=list)
    source_workgroup_name: str = ""
    target_workgroup_name: str = ""


class AgentMemoryRead(ORMBaseModel):
    id: str
    agent_id: str
    conversation_id: str
    memory_type: str
    content: str
    source_summary: str
    confidence: float
    created_at: datetime


class ConversationUsageRead(BaseModel):
    conversation_id: str
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_duration_ms: int
    estimated_cost_usd: float
    api_calls: int
    by_model: dict[str, Any] = {}
