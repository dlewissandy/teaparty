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
    is_system_admin: bool = False


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
    topic_id: str | None = None


class WorkgroupFileRead(BaseModel):
    id: str
    path: str
    content: str
    topic_id: str = ""


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
    organization_id: str = Field(min_length=1)


class WorkgroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    files: list[WorkgroupFileWrite | str] | None = None
    is_discoverable: bool | None = None
    service_description: str | None = None
    workspace_enabled: bool | None = None
    organization_id: str | None = None  # None means don't change; must be a valid org ID if set


class WorkgroupRead(ORMBaseModel):
    id: str
    name: str
    files: list[WorkgroupFileRead]
    owner_id: str
    organization_id: str | None = None
    organization_name: str = ""
    is_discoverable: bool = False
    service_description: str = ""
    workspace_enabled: bool = False
    created_at: datetime


class OrganizationRead(ORMBaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    operations_workgroup_id: str | None = None
    created_at: datetime


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class OrganizationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


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


class InviteDetailRead(ORMBaseModel):
    id: str
    workgroup_id: str
    workgroup_name: str = ""
    invited_by_name: str = ""
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
    budget_limit_usd: float | None = None
    budget_used_usd: float = 0.0


class MemberRoleUpdateRequest(BaseModel):
    role: Literal["editor", "member"]


class MemberBudgetUpdateRequest(BaseModel):
    budget_limit_usd: float | None = Field(default=None, ge=0.0)
    reset_usage: bool = False


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
    is_archived: bool | None = None


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
    latest_message_at: datetime | None = None


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


# --- Engagement schemas ---


class EngagementCreateRequest(BaseModel):
    target_workgroup_id: str
    source_workgroup_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    scope: str = ""
    requirements: str = ""


class EngagementRespondRequest(BaseModel):
    action: Literal["accept", "decline"]
    terms: str = ""


class EngagementCompleteRequest(BaseModel):
    summary: str = ""


class EngagementReviewRequest(BaseModel):
    rating: Literal["satisfied", "dissatisfied"]
    feedback: str = ""


class EngagementCancelRequest(BaseModel):
    reason: str = ""


class EngagementRead(ORMBaseModel):
    id: str
    source_workgroup_id: str
    target_workgroup_id: str
    proposed_by_user_id: str
    status: str
    title: str
    scope: str
    requirements: str
    terms: str
    deliverables: str
    source_conversation_id: str | None = None
    target_conversation_id: str | None = None
    created_at: datetime
    accepted_at: datetime | None = None
    declined_at: datetime | None = None
    completed_at: datetime | None = None
    reviewed_at: datetime | None = None
    cancelled_at: datetime | None = None
    review_rating: str | None = None
    review_feedback: str = ""


class EngagementDetailRead(EngagementRead):
    source_workgroup_name: str = ""
    target_workgroup_name: str = ""


# --- Job schemas ---


class JobRead(ORMBaseModel):
    id: str
    title: str
    scope: str
    status: str
    engagement_id: str | None = None
    workgroup_id: str
    conversation_id: str | None = None
    created_by_agent_id: str | None = None
    deliverables: str = ""
    created_at: datetime
    completed_at: datetime | None = None


class JobDetailRead(JobRead):
    workgroup_name: str = ""
    engagement_title: str = ""


class AgentMemoryRead(ORMBaseModel):
    id: str
    agent_id: str
    conversation_id: str
    memory_type: str
    content: str
    source_summary: str
    confidence: float
    created_at: datetime


class AgentLearningSignalRead(BaseModel):
    signal_type: str
    value: dict[str, Any]
    created_at: datetime


class AgentLearningsRead(BaseModel):
    learning_state: dict[str, Any]
    sentiment_state: dict[str, Any]
    memories: list[AgentMemoryRead]
    recent_signals: list[AgentLearningSignalRead]


class ToolCatalogEntry(BaseModel):
    name: str
    display_name: str
    description: str
    source: str  # "builtin" | "admin" | "server_side" | "special" | "custom_prompt" | "custom_webhook" | "custom_granted"
    enabled: bool = True
    source_workgroup_id: str | None = None


class ToolCatalogCategory(BaseModel):
    key: str
    label: str
    tools: list[ToolCatalogEntry]


class ToolCatalogRead(BaseModel):
    version: int = 1
    categories: list[ToolCatalogCategory]


class ConversationUsageRead(BaseModel):
    conversation_id: str
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_duration_ms: int
    estimated_cost_usd: float
    api_calls: int
    by_model: dict[str, Any] = {}


class WorkgroupUsageRead(BaseModel):
    workgroup_id: str
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_duration_ms: int
    estimated_cost_usd: float
    api_calls: int
    by_model: dict[str, Any] = {}


# --- Workspace schemas ---


class WorkspaceRead(ORMBaseModel):
    id: str
    workgroup_id: str
    repo_path: str
    main_worktree_path: str
    status: str
    error_message: str = ""
    last_synced_at: datetime | None = None
    created_at: datetime


class WorkspaceWorktreeRead(ORMBaseModel):
    id: str
    workspace_id: str
    conversation_id: str
    branch_name: str
    worktree_path: str
    status: str
    created_at: datetime
    merged_at: datetime | None = None
    removed_at: datetime | None = None


class WorkspaceStatusRead(BaseModel):
    workspace: WorkspaceRead
    worktrees: list[WorkspaceWorktreeRead] = Field(default_factory=list)


class WorkspaceSyncRequest(BaseModel):
    direction: Literal["db_to_fs", "fs_to_db"] = "db_to_fs"
    conversation_id: str | None = None


class WorkspaceSyncResult(BaseModel):
    direction: str
    files_written: int = 0
    files_read: int = 0
    committed: bool = False


class WorkspaceMergeRequest(BaseModel):
    conversation_id: str


class WorkspaceMergeResult(BaseModel):
    merged: bool
    branch_name: str = ""
    conflicts: list[str] = Field(default_factory=list)


class WorkspaceGitLogEntry(BaseModel):
    commit_hash: str
    author: str
    date: str
    message: str


class WorkspaceGitLogRead(BaseModel):
    branch: str = "main"
    entries: list[WorkspaceGitLogEntry] = Field(default_factory=list)


# --- System settings schemas ---


class SystemSettingsRead(BaseModel):
    # LLM Configuration
    llm_default_model: str
    llm_cheap_model: str
    admin_agent_model: str
    intent_probe_model: str
    anthropic_api_key_set: bool
    ollama_base_url: str
    # Agent Behavior
    agent_chain_max: int
    agent_sdk_max_turns: int
    follow_up_scan_limit: int
    # Application
    app_name: str
    workspace_root: str
    admin_agent_use_sdk: bool


class SystemSettingsUpdate(BaseModel):
    # LLM Configuration
    llm_default_model: str | None = None
    llm_cheap_model: str | None = None
    admin_agent_model: str | None = None
    intent_probe_model: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str | None = None
    # Agent Behavior
    agent_chain_max: int | None = Field(default=None, ge=1, le=50)
    agent_sdk_max_turns: int | None = Field(default=None, ge=1, le=50)
    follow_up_scan_limit: int | None = Field(default=None, ge=10, le=1000)
    # Application
    app_name: str | None = None
    workspace_root: str | None = None
    admin_agent_use_sdk: bool | None = None
