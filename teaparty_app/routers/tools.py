from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Agent, ToolDefinition, ToolGrant, User
from teaparty_app.schemas import (
    AvailableToolRead,
    ToolDefinitionCreateRequest,
    ToolDefinitionRead,
    ToolDefinitionUpdateRequest,
    ToolGrantCreateRequest,
    ToolGrantRead,
)
from teaparty_app.services.permissions import require_workgroup_membership, require_workgroup_owner
from teaparty_app.services.tools import TOOL_REGISTRY, available_tools_for_workgroup

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tools"])


def _build_available_tool_list(session: Session, workgroup_id: str) -> list[AvailableToolRead]:
    results: list[AvailableToolRead] = []

    for name in sorted(TOOL_REGISTRY.keys()):
        results.append(
            AvailableToolRead(
                name=name,
                display_name=name.replace("_", " ").title(),
                description=name.replace("_", " "),
                tool_type="builtin",
            )
        )

    own_tools = session.exec(
        select(ToolDefinition).where(
            ToolDefinition.workgroup_id == workgroup_id,
            ToolDefinition.enabled == True,  # noqa: E712
        )
    ).all()
    for td in own_tools:
        results.append(
            AvailableToolRead(
                name=f"custom:{td.id}",
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
        results.append(
            AvailableToolRead(
                name=f"custom:{td.id}",
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
