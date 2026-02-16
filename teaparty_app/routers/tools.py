from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Agent, ToolDefinition, ToolGrant, User, Workgroup
from teaparty_app.schemas import (
    AvailableToolRead,
    ToolCatalogCategory,
    ToolCatalogEntry,
    ToolCatalogRead,
    ToolDefinitionCreateRequest,
    ToolDefinitionRead,
    ToolDefinitionUpdateRequest,
    ToolGrantCreateRequest,
    ToolGrantRead,
)
from teaparty_app.services.permissions import require_workgroup_membership, require_workgroup_owner
from teaparty_app.services.tools import SERVER_SIDE_TOOLS, TOOL_REGISTRY, available_tools, available_tools_for_workgroup, get_workgroup_disabled_tools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tools"])


def _build_available_tool_list(session: Session, workgroup_id: str) -> list[AvailableToolRead]:
    workgroup = session.get(Workgroup, workgroup_id)
    disabled = get_workgroup_disabled_tools(workgroup) if workgroup else set()

    results: list[AvailableToolRead] = []

    for name in available_tools():
        if name in disabled:
            continue
        tool_type = "builtin"
        if name in SERVER_SIDE_TOOLS:
            tool_type = "server_side"
        elif name == "claude_code":
            tool_type = "special"
        results.append(
            AvailableToolRead(
                name=name,
                display_name=name.replace("_", " ").title(),
                description=TOOL_DESCRIPTIONS.get(name, name.replace("_", " ")),
                tool_type=tool_type,
            )
        )

    own_tools = session.exec(
        select(ToolDefinition).where(
            ToolDefinition.workgroup_id == workgroup_id,
            ToolDefinition.enabled == True,  # noqa: E712
        )
    ).all()
    for td in own_tools:
        ref = f"custom:{td.id}"
        if ref in disabled:
            continue
        results.append(
            AvailableToolRead(
                name=ref,
                display_name=td.name,
                description=td.description,
                tool_type=td.tool_type,
                source_workgroup_id=td.workgroup_id,
                is_shared=td.is_shared,
            )
        )

    granted_tool_ids = session.exec(
        select(ToolGrant.tool_definition_id).where(
            ToolGrant.grantee_workgroup_id == workgroup_id,
        )
    ).all()
    own_tool_ids = {td.id for td in own_tools}
    for tool_def_id in granted_tool_ids:
        if tool_def_id in own_tool_ids:
            continue
        td = session.get(ToolDefinition, tool_def_id)
        if not td or not td.enabled:
            continue
        ref = f"custom:{td.id}"
        if ref in disabled:
            continue
        results.append(
            AvailableToolRead(
                name=ref,
                display_name=td.name,
                description=td.description,
                tool_type=td.tool_type,
                source_workgroup_id=td.workgroup_id,
                is_shared=td.is_shared,
            )
        )

    return results


@router.post("/workgroups/{workgroup_id}/tools", response_model=ToolDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_tool_definition(
    workgroup_id: str,
    payload: ToolDefinitionCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ToolDefinitionRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tool name cannot be empty")

    if name in TOOL_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool name '{name}' conflicts with a built-in tool",
        )

    if payload.tool_type == "prompt" and not payload.prompt_template.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompt tools require a non-empty prompt_template",
        )
    if payload.tool_type == "webhook" and not payload.webhook_url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook tools require a non-empty webhook_url",
        )

    tool_def = ToolDefinition(
        workgroup_id=workgroup_id,
        created_by_user_id=user.id,
        name=name,
        description=payload.description.strip(),
        tool_type=payload.tool_type,
        prompt_template=payload.prompt_template,
        webhook_url=payload.webhook_url.strip(),
        webhook_method=payload.webhook_method,
        webhook_headers=dict(payload.webhook_headers or {}),
        webhook_timeout_seconds=payload.webhook_timeout_seconds,
        input_schema=dict(payload.input_schema or {}),
        is_shared=payload.is_shared,
    )
    session.add(tool_def)
    session.commit()
    session.refresh(tool_def)
    return ToolDefinitionRead.model_validate(tool_def)


@router.get("/workgroups/{workgroup_id}/tools", response_model=list[AvailableToolRead])
def list_available_tools(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[AvailableToolRead]:
    require_workgroup_membership(session, workgroup_id, user.id)
    return _build_available_tool_list(session, workgroup_id)


@router.get("/workgroups/{workgroup_id}/tools/definitions", response_model=list[ToolDefinitionRead])
def list_own_tool_definitions(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ToolDefinitionRead]:
    require_workgroup_membership(session, workgroup_id, user.id)
    tools = session.exec(
        select(ToolDefinition)
        .where(ToolDefinition.workgroup_id == workgroup_id)
        .order_by(ToolDefinition.created_at.asc())
    ).all()
    return [ToolDefinitionRead.model_validate(td) for td in tools]


# ── Tool catalog ──

TOOL_CATALOG_CATEGORIES = [
    ("file_management", "File Management", [
        ("list_files", "builtin"), ("add_file", "builtin"), ("edit_file", "builtin"),
        ("rename_file", "builtin"), ("delete_file", "builtin"),
    ]),
    ("job_management", "Job Management", [
        ("add_job", "admin"), ("archive_job", "admin"), ("unarchive_job", "admin"),
        ("remove_job", "admin"), ("clear_job_messages", "admin"), ("list_jobs", "admin"),
    ]),
    ("member_management", "Agent & Member Management", [
        ("add_agent", "admin"), ("add_user", "admin"),
        ("remove_member", "admin"), ("list_members", "admin"),
    ]),
    ("collaboration", "Collaboration", [
        ("list_tasks", "admin"), ("accept_task", "admin"),
        ("decline_task", "admin"), ("complete_task", "admin"),
    ]),
    ("research", "Research", [
        ("web_search", "server_side"), ("claude_code", "special"),
    ]),
    ("utility", "Utility", [
        ("summarize_job", "builtin"), ("list_open_followups", "builtin"),
        ("suggest_next_step", "builtin"),
    ]),
]

TOOL_DESCRIPTIONS: dict[str, str] = {
    # File Management
    "list_files": "List all files in the workgroup.",
    "add_file": "Create a new file in the workgroup.",
    "edit_file": "Edit an existing file's content.",
    "rename_file": "Rename or move a file.",
    "delete_file": "Delete a file from the workgroup.",
    # Job Management
    "add_job": "Create a new job conversation.",
    "archive_job": "Archive a job to hide it from active view.",
    "unarchive_job": "Restore an archived job.",
    "remove_job": "Permanently remove a job and its messages.",
    "clear_job_messages": "Delete all messages in a job.",
    "list_jobs": "List all jobs in the workgroup.",
    # Agent & Member Management
    "add_agent": "Add a new AI agent to the workgroup.",
    "add_user": "Invite a user to the workgroup.",
    "remove_member": "Remove a member or agent from the workgroup.",
    "list_members": "List all members and agents.",
    # Collaboration
    "list_tasks": "List cross-group tasks.",
    "accept_task": "Accept an incoming cross-group task.",
    "decline_task": "Decline an incoming cross-group task.",
    "complete_task": "Mark a cross-group task as complete.",
    # Research
    "web_search": "Search the web for information.",
    "claude_code": "Run Claude Code for advanced coding tasks.",
    # Utility
    "summarize_job": "Summarize recent messages in a job.",
    "list_open_followups": "List pending follow-up tasks.",
    "suggest_next_step": "Suggest the next action for the conversation.",
}


@router.get("/workgroups/{workgroup_id}/tools/catalog", response_model=ToolCatalogRead)
def get_tool_catalog(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ToolCatalogRead:
    require_workgroup_membership(session, workgroup_id, user.id)

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")

    disabled = get_workgroup_disabled_tools(workgroup)

    categories: list[ToolCatalogCategory] = []
    for cat_key, cat_label, tool_list in TOOL_CATALOG_CATEGORIES:
        entries: list[ToolCatalogEntry] = []
        for tool_name, tool_source in tool_list:
            entries.append(ToolCatalogEntry(
                name=tool_name,
                display_name=tool_name.replace("_", " ").title(),
                description=TOOL_DESCRIPTIONS.get(tool_name, tool_name.replace("_", " ")),
                source=tool_source,
                enabled=tool_name not in disabled,
            ))
        categories.append(ToolCatalogCategory(key=cat_key, label=cat_label, tools=entries))

    # Custom tools: own + granted
    custom_entries: list[ToolCatalogEntry] = []
    own_tools = session.exec(
        select(ToolDefinition).where(
            ToolDefinition.workgroup_id == workgroup_id,
            ToolDefinition.enabled == True,  # noqa: E712
        )
    ).all()
    own_tool_ids = {td.id for td in own_tools}
    for td in own_tools:
        ref = f"custom:{td.id}"
        source = "custom_prompt" if td.tool_type == "prompt" else "custom_webhook"
        custom_entries.append(ToolCatalogEntry(
            name=ref,
            display_name=td.name,
            description=td.description or td.name,
            source=source,
            enabled=ref not in disabled,
            source_workgroup_id=td.workgroup_id,
        ))

    granted_tool_ids = session.exec(
        select(ToolGrant.tool_definition_id).where(
            ToolGrant.grantee_workgroup_id == workgroup_id,
        )
    ).all()
    for tool_def_id in granted_tool_ids:
        if tool_def_id in own_tool_ids:
            continue
        td = session.get(ToolDefinition, tool_def_id)
        if not td or not td.enabled:
            continue
        ref = f"custom:{td.id}"
        custom_entries.append(ToolCatalogEntry(
            name=ref,
            display_name=td.name,
            description=td.description or td.name,
            source="custom_granted",
            enabled=ref not in disabled,
            source_workgroup_id=td.workgroup_id,
        ))

    if custom_entries:
        categories.append(ToolCatalogCategory(key="custom", label="Custom Tools", tools=custom_entries))

    return ToolCatalogRead(categories=categories)


@router.get("/workgroups/{workgroup_id}/tools/{tool_id}", response_model=ToolDefinitionRead)
def get_tool_definition(
    workgroup_id: str,
    tool_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ToolDefinitionRead:
    require_workgroup_membership(session, workgroup_id, user.id)
    tool_def = session.get(ToolDefinition, tool_id)
    if not tool_def or tool_def.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool definition not found")
    return ToolDefinitionRead.model_validate(tool_def)


@router.patch("/workgroups/{workgroup_id}/tools/{tool_id}", response_model=ToolDefinitionRead)
def update_tool_definition(
    workgroup_id: str,
    tool_id: str,
    payload: ToolDefinitionUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ToolDefinitionRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    tool_def = session.get(ToolDefinition, tool_id)
    if not tool_def or tool_def.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool definition not found")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tool name cannot be empty")
        if name in TOOL_REGISTRY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tool name '{name}' conflicts with a built-in tool",
            )
        tool_def.name = name
    if payload.description is not None:
        tool_def.description = payload.description.strip()
    if payload.tool_type is not None:
        tool_def.tool_type = payload.tool_type
    if payload.prompt_template is not None:
        tool_def.prompt_template = payload.prompt_template
    if payload.webhook_url is not None:
        tool_def.webhook_url = payload.webhook_url.strip()
    if payload.webhook_method is not None:
        tool_def.webhook_method = payload.webhook_method
    if payload.webhook_headers is not None:
        tool_def.webhook_headers = dict(payload.webhook_headers)
    if payload.webhook_timeout_seconds is not None:
        tool_def.webhook_timeout_seconds = payload.webhook_timeout_seconds
    if payload.input_schema is not None:
        tool_def.input_schema = dict(payload.input_schema)
    if payload.is_shared is not None:
        tool_def.is_shared = payload.is_shared
    if payload.enabled is not None:
        tool_def.enabled = payload.enabled

    session.add(tool_def)
    session.commit()
    session.refresh(tool_def)
    return ToolDefinitionRead.model_validate(tool_def)


@router.delete("/workgroups/{workgroup_id}/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool_definition(
    workgroup_id: str,
    tool_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    require_workgroup_owner(session, workgroup_id, user.id)

    tool_def = session.get(ToolDefinition, tool_id)
    if not tool_def or tool_def.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool definition not found")

    grants = session.exec(
        select(ToolGrant).where(ToolGrant.tool_definition_id == tool_id)
    ).all()
    for grant in grants:
        session.delete(grant)

    custom_ref = f"custom:{tool_id}"
    agents = session.exec(select(Agent)).all()
    for agent in agents:
        if custom_ref in (agent.tool_names or []):
            agent.tool_names = [tn for tn in agent.tool_names if tn != custom_ref]
            session.add(agent)

    session.delete(tool_def)
    session.commit()


@router.post(
    "/workgroups/{workgroup_id}/tools/{tool_id}/grants",
    response_model=ToolGrantRead,
    status_code=status.HTTP_201_CREATED,
)
def create_tool_grant(
    workgroup_id: str,
    tool_id: str,
    payload: ToolGrantCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ToolGrantRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    tool_def = session.get(ToolDefinition, tool_id)
    if not tool_def or tool_def.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool definition not found")

    if not tool_def.is_shared:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tool must be marked as shared before granting access",
        )

    if payload.grantee_workgroup_id == workgroup_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot grant tool to the owning workgroup",
        )

    existing = session.exec(
        select(ToolGrant).where(
            ToolGrant.tool_definition_id == tool_id,
            ToolGrant.grantee_workgroup_id == payload.grantee_workgroup_id,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Grant already exists for this workgroup",
        )

    grant = ToolGrant(
        tool_definition_id=tool_id,
        grantee_workgroup_id=payload.grantee_workgroup_id,
        granted_by_user_id=user.id,
    )
    session.add(grant)
    session.commit()
    session.refresh(grant)
    return ToolGrantRead.model_validate(grant)


@router.get("/workgroups/{workgroup_id}/tools/{tool_id}/grants", response_model=list[ToolGrantRead])
def list_tool_grants(
    workgroup_id: str,
    tool_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ToolGrantRead]:
    require_workgroup_membership(session, workgroup_id, user.id)

    tool_def = session.get(ToolDefinition, tool_id)
    if not tool_def or tool_def.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool definition not found")

    grants = session.exec(
        select(ToolGrant)
        .where(ToolGrant.tool_definition_id == tool_id)
        .order_by(ToolGrant.created_at.asc())
    ).all()
    return [ToolGrantRead.model_validate(g) for g in grants]


@router.delete(
    "/workgroups/{workgroup_id}/tools/{tool_id}/grants/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_tool_grant(
    workgroup_id: str,
    tool_id: str,
    grant_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    require_workgroup_owner(session, workgroup_id, user.id)

    tool_def = session.get(ToolDefinition, tool_id)
    if not tool_def or tool_def.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool definition not found")

    grant = session.get(ToolGrant, grant_id)
    if not grant or grant.tool_definition_id != tool_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grant not found")

    session.delete(grant)
    session.commit()


@router.get("/tools/shared", response_model=list[ToolDefinitionRead])
def list_shared_tools(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ToolDefinitionRead]:
    tools = session.exec(
        select(ToolDefinition)
        .where(
            ToolDefinition.is_shared == True,  # noqa: E712
            ToolDefinition.enabled == True,  # noqa: E712
        )
        .order_by(ToolDefinition.created_at.asc())
    ).all()
    return [ToolDefinitionRead.model_validate(td) for td in tools]
