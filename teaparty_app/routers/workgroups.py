from datetime import timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.deps import get_current_user
from teaparty_app.db import get_session
from teaparty_app.models import Agent, AgentLearningEvent, AgentMemory, Conversation, Invite, Membership, User, Workgroup, utc_now
from teaparty_app.schemas import (
    AgentCloneRequest,
    AgentConversationClearRead,
    AgentCreateRequest,
    AgentLearningSignalRead,
    AgentLearningsRead,
    AgentMemoryRead,
    AgentRead,
    AgentUpdateRequest,
    ConversationRead,
    InviteCreateRequest,
    InviteRead,
    MemberRead,
    WorkgroupCreateRequest,
    WorkgroupFileWrite,
    WorkgroupRead,
    WorkgroupTemplateAgentWrite,
    WorkgroupTemplateRead,
    WorkgroupUpdateRequest,
    WorkgroupUsageRead,
)
from teaparty_app.services.activity import (
    add_activity_participant,
    ensure_activity_conversation,
    post_activity,
    post_bulk_file_change_activity,
)
from teaparty_app.services.admin_workspace import (
    ADMIN_AGENT_SENTINEL,
    clear_conversation_messages,
    direct_topic_key_user_agent,
    ensure_admin_workspace,
    ensure_admin_workspace_for_workgroup_id,
    list_members as list_workgroup_members,
)
from teaparty_app.services.llm_usage import get_workgroup_usage
from teaparty_app.services.permissions import require_workgroup_membership, require_workgroup_owner
from teaparty_app.services.tools import available_tools, available_tools_for_workgroup
from teaparty_app.services.workgroup_templates import (
    TEMPLATE_ROOT,
    WORKGROUP_STORAGE_ROOT,
    _is_workgroup_storage_path,
    list_workgroup_templates,
    template_storage_files,
    templates_from_storage_files,
    workgroup_storage_files,
)

router = APIRouter(prefix="/api", tags=["workgroups"])
ADMINISTRATION_WORKGROUP_NAME = "Administration"


def _normalize_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_workgroup_files(files: list[WorkgroupFileWrite | str] | None) -> list[dict[str, str]]:
    if not files:
        return []

    normalized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw in files:
        if isinstance(raw, str):
            path = raw.strip()
            content = ""
            file_id = str(uuid4())
        else:
            path = raw.path.strip()
            content = raw.content if isinstance(raw.content, str) else str(raw.content or "")
            file_id = (raw.id or "").strip() or str(uuid4())

        if not path or path in seen_paths:
            continue
        if len(path) > 512:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Each file entry must be 512 characters or fewer",
            )
        if len(content) > 200000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File content must be 200000 characters or fewer",
            )
        normalized.append({"id": file_id, "path": path, "content": content})
        seen_paths.add(path)
    return normalized


def _normalize_persisted_workgroup_files(raw_files: object) -> list[dict[str, str]]:
    if not isinstance(raw_files, list):
        return []

    normalized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    for item in raw_files:
        file_id = ""
        path = ""
        content = ""

        if isinstance(item, str):
            path = item.strip()
        elif isinstance(item, dict):
            file_id = str(item.get("id", "")).strip()
            path = str(item.get("path", "")).strip()
            raw_content = item.get("content", "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content or "")
        else:
            continue

        if not path or len(path) > 512 or len(content) > 200000 or path in seen_paths:
            continue

        file_id = file_id or str(uuid4())
        while file_id in seen_ids:
            file_id = str(uuid4())
        seen_ids.add(file_id)
        seen_paths.add(path)
        normalized.append({"id": file_id, "path": path, "content": content})
    return normalized


def _template_storage_seed_files() -> list[dict[str, str]]:
    defaults = template_storage_files(list_workgroup_templates())
    return _normalize_workgroup_files([WorkgroupFileWrite(path=item["path"], content=item["content"]) for item in defaults])


def _is_template_storage_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("/")
    return normalized.startswith(f"{TEMPLATE_ROOT}/") or normalized.startswith("templates/")


def _reconcile_administration_template_files(existing_files: list[dict[str, str]]) -> tuple[list[dict[str, str]], bool]:
    non_template_files = [dict(item) for item in existing_files if not _is_template_storage_path(item["path"])]
    existing_template_files = [dict(item) for item in existing_files if _is_template_storage_path(item["path"])]

    parsed_templates = templates_from_storage_files(existing_template_files)
    if not parsed_templates:
        parsed_templates = list_workgroup_templates()

    desired_entries = template_storage_files(parsed_templates)
    default_entries = template_storage_files(list_workgroup_templates())
    desired_by_path = {item["path"]: item["content"] for item in desired_entries}
    for item in default_entries:
        desired_by_path.setdefault(item["path"], item["content"])

    existing_ids_by_path = {item["path"]: item["id"] for item in existing_template_files}
    canonical_template_files: list[dict[str, str]] = []
    for path, content in sorted(desired_by_path.items()):
        canonical_template_files.append(
            {
                "id": existing_ids_by_path.get(path, str(uuid4())),
                "path": path,
                "content": content,
            }
        )

    existing_signature = [(item["path"], item["content"]) for item in existing_template_files]
    canonical_signature = [(item["path"], item["content"]) for item in canonical_template_files]
    changed = existing_signature != canonical_signature
    return non_template_files + canonical_template_files, changed


def _reconcile_administration_workgroup_files(session: Session, admin_workgroup: Workgroup) -> bool:
    owner_id = admin_workgroup.owner_id
    all_workgroups = session.exec(
        select(Workgroup)
        .join(Membership, Membership.workgroup_id == Workgroup.id)
        .where(Membership.user_id == owner_id)
        .order_by(Workgroup.created_at.asc())
    ).all()
    wg_ids = {wg.id for wg in all_workgroups}
    all_agents = session.exec(
        select(Agent).where(Agent.workgroup_id.in_(wg_ids)).order_by(Agent.created_at.asc())
    ).all()

    wg_dicts = [
        {
            "id": wg.id,
            "name": wg.name,
            "owner_id": wg.owner_id,
            "is_discoverable": wg.is_discoverable,
            "service_description": wg.service_description,
            "created_at": wg.created_at,
        }
        for wg in all_workgroups
    ]
    agents_by_wg: dict[str, list[dict]] = {}
    for agent in all_agents:
        if agent.description == ADMIN_AGENT_SENTINEL:
            continue
        agents_by_wg.setdefault(agent.workgroup_id, []).append(
            {
                "id": agent.id,
                "name": agent.name,
                "description": agent.description,
                "role": agent.role,
                "personality": agent.personality,
                "backstory": agent.backstory,
                "model": agent.model,
                "temperature": agent.temperature,
                "verbosity": agent.verbosity,
                "tool_names": list(agent.tool_names or []),
                "response_threshold": agent.response_threshold,
                "follow_up_minutes": agent.follow_up_minutes,
            }
        )

    all_memberships = session.exec(
        select(Membership).where(Membership.workgroup_id.in_(wg_ids))
    ).all()
    members_by_wg: dict[str, list[dict]] = {}
    for m in all_memberships:
        members_by_wg.setdefault(m.workgroup_id, []).append(
            {"user_id": m.user_id, "role": m.role}
        )

    desired_entries = workgroup_storage_files(wg_dicts, agents_by_wg, members_by_wg)
    desired_by_path = {item["path"]: item["content"] for item in desired_entries}

    existing_files = _normalize_persisted_workgroup_files(admin_workgroup.files)
    non_storage_files = [dict(f) for f in existing_files if not _is_workgroup_storage_path(f["path"])]
    existing_storage_files = [dict(f) for f in existing_files if _is_workgroup_storage_path(f["path"])]
    existing_ids_by_path = {f["path"]: f["id"] for f in existing_storage_files}

    canonical_storage_files: list[dict[str, str]] = []
    for path, content in sorted(desired_by_path.items()):
        canonical_storage_files.append({
            "id": existing_ids_by_path.get(path, str(uuid4())),
            "path": path,
            "content": content,
        })

    existing_signature = [(f["path"], f["content"]) for f in existing_storage_files]
    canonical_signature = [(f["path"], f["content"]) for f in canonical_storage_files]
    changed = existing_signature != canonical_signature

    if changed:
        admin_workgroup.files = non_storage_files + canonical_storage_files
        session.add(admin_workgroup)

    return changed


def _ensure_administration_workgroup(session: Session, user: User) -> tuple[Workgroup, bool]:
    workgroup = session.exec(
        select(Workgroup)
        .where(Workgroup.owner_id == user.id, Workgroup.name == ADMINISTRATION_WORKGROUP_NAME)
        .order_by(Workgroup.created_at.asc())
    ).first()

    changed = False
    if not workgroup:
        workgroup = Workgroup(
            name=ADMINISTRATION_WORKGROUP_NAME,
            files=_template_storage_seed_files(),
            owner_id=user.id,
        )
        session.add(workgroup)
        session.flush()
        session.add(Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner"))
        changed = True
    else:
        membership = session.exec(
            select(Membership).where(
                Membership.workgroup_id == workgroup.id,
                Membership.user_id == user.id,
            )
        ).first()
        if not membership:
            session.add(Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner"))
            changed = True

        existing_files = _normalize_persisted_workgroup_files(workgroup.files)
        merged_files, files_changed = _reconcile_administration_template_files(existing_files)
        if files_changed:
            workgroup.files = merged_files
            session.add(workgroup)
            changed = True

    wg_storage_changed = _reconcile_administration_workgroup_files(session, workgroup)
    changed = changed or wg_storage_changed

    _admin_agent, _admin_conversation, admin_changed = ensure_admin_workspace(session, workgroup)
    changed = changed or admin_changed
    return workgroup, changed


def _sync_workgroup_storage_for_user(session: Session, user: User) -> None:
    admin_wg = session.exec(
        select(Workgroup)
        .where(Workgroup.owner_id == user.id, Workgroup.name == ADMINISTRATION_WORKGROUP_NAME)
        .order_by(Workgroup.created_at.asc())
    ).first()
    if admin_wg and _reconcile_administration_workgroup_files(session, admin_wg):
        session.commit()


def _load_user_workgroup_templates(session: Session, user: User) -> tuple[list[WorkgroupTemplateRead], bool]:
    admin_workgroup, changed = _ensure_administration_workgroup(session, user)
    normalized_files = _normalize_persisted_workgroup_files(admin_workgroup.files)
    parsed = templates_from_storage_files(normalized_files)
    if not parsed:
        parsed = list_workgroup_templates()
    return [WorkgroupTemplateRead.model_validate(item) for item in parsed], changed


def _resolve_template_for_create(
    payload: WorkgroupCreateRequest,
    templates_by_key: dict[str, WorkgroupTemplateRead],
) -> WorkgroupTemplateRead | None:
    template_key = (payload.template_key or "").strip()
    if not template_key:
        return None
    template = templates_by_key.get(template_key)
    if template:
        return template
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unknown workgroup template '{template_key}'",
    )


def _resolve_workgroup_creation_files(
    payload: WorkgroupCreateRequest,
    template: WorkgroupTemplateRead | None,
) -> list[dict[str, str]]:
    if payload.files is not None:
        return _normalize_workgroup_files(payload.files)

    if not template:
        return []

    return _normalize_workgroup_files(
        [WorkgroupFileWrite(path=item.path, content=item.content) for item in template.files]
    )


def _resolve_workgroup_creation_agents(
    payload: WorkgroupCreateRequest,
    template: WorkgroupTemplateRead | None,
) -> list[WorkgroupTemplateAgentWrite]:
    if payload.agents is not None:
        return [WorkgroupTemplateAgentWrite.model_validate(agent) for agent in payload.agents]

    if not template:
        return []

    return [WorkgroupTemplateAgentWrite.model_validate(item.model_dump()) for item in template.agents]


@router.get("/workgroup-templates", response_model=list[WorkgroupTemplateRead])
def list_available_workgroup_templates(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[WorkgroupTemplateRead]:
    templates, changed = _load_user_workgroup_templates(session, user)
    if changed:
        session.commit()
    return templates


@router.post("/workgroups", response_model=WorkgroupRead)
def create_workgroup(
    payload: WorkgroupCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkgroupRead:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workgroup name cannot be empty")

    templates, _changed = _load_user_workgroup_templates(session, user)
    templates_by_key = {item.key: item for item in templates}
    selected_template = _resolve_template_for_create(payload, templates_by_key)
    files = _resolve_workgroup_creation_files(payload, selected_template)
    template_agents = _resolve_workgroup_creation_agents(payload, selected_template)
    allowed_tools = set(available_tools())
    requested_tools = sorted({tool for agent in template_agents for tool in agent.tool_names})
    unknown_tools = sorted(
        tool for tool in set(requested_tools) - allowed_tools if not tool.startswith("custom:")
    )
    if unknown_tools:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown tools: {', '.join(unknown_tools)}",
        )

    group = Workgroup(name=name, files=files, owner_id=user.id)
    session.add(group)
    session.flush()

    owner_membership = Membership(workgroup_id=group.id, user_id=user.id, role="owner")
    session.add(owner_membership)

    for draft in template_agents:
        agent_name = draft.name.strip()
        if not agent_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name cannot be empty")
        session.add(
            Agent(
                workgroup_id=group.id,
                created_by_user_id=user.id,
                name=agent_name,
                description=draft.description.strip(),
                role=(draft.role.strip() or draft.description.strip()),
                personality=draft.personality.strip(),
                backstory=draft.backstory.strip(),
                model=draft.model.strip() or "claude-sonnet-4-5",
                temperature=draft.temperature,
                verbosity=draft.verbosity,
                tool_names=draft.tool_names,
                response_threshold=draft.response_threshold,
                follow_up_minutes=draft.follow_up_minutes,
                learning_state={},
                sentiment_state={},
                learned_preferences={},
            )
        )

    ensure_admin_workspace(session, group)
    ensure_activity_conversation(session, group)
    session.commit()
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(group)
    return WorkgroupRead.model_validate(group)


@router.get("/workgroups", response_model=list[WorkgroupRead])
def list_workgroups(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[WorkgroupRead]:
    _, changed = _ensure_administration_workgroup(session, user)

    rows = session.exec(
        select(Workgroup)
        .join(Membership, Membership.workgroup_id == Workgroup.id)
        .where(Membership.user_id == user.id)
        .order_by(Workgroup.created_at.desc())
    ).all()

    groups_changed = False
    for workgroup in rows:
        _admin_agent, _admin_conversation, group_changed = ensure_admin_workspace(session, workgroup)
        _activity_conversation, activity_changed = ensure_activity_conversation(session, workgroup)
        groups_changed = groups_changed or group_changed or activity_changed
    if changed or groups_changed:
        session.commit()

    return [WorkgroupRead.model_validate(item) for item in rows]


@router.patch("/workgroups/{workgroup_id}", response_model=WorkgroupRead)
def update_workgroup(
    workgroup_id: str,
    payload: WorkgroupUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkgroupRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")

    if payload.name is None and payload.files is None and payload.is_discoverable is None and payload.service_description is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No updates provided")

    old_files = _normalize_persisted_workgroup_files(workgroup.files) if payload.files is not None else None

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workgroup name cannot be empty")
        workgroup.name = name

    if payload.files is not None:
        workgroup.files = _normalize_workgroup_files(payload.files)

    if payload.is_discoverable is not None:
        workgroup.is_discoverable = payload.is_discoverable

    if payload.service_description is not None:
        workgroup.service_description = payload.service_description.strip()

    if old_files is not None:
        new_files = _normalize_persisted_workgroup_files(workgroup.files)
        post_bulk_file_change_activity(session, workgroup_id, old_files, new_files, actor_user_id=user.id)

    session.add(workgroup)
    session.commit()
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(workgroup)
    return WorkgroupRead.model_validate(workgroup)


@router.post("/workgroups/{workgroup_id}/invites", response_model=InviteRead)
def create_invite(
    workgroup_id: str,
    payload: InviteCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> InviteRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    invite = Invite(
        workgroup_id=workgroup_id,
        invited_by_user_id=user.id,
        email=str(payload.email).lower(),
        token=str(uuid4()),
        expires_at=utc_now() + timedelta(days=7),
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return InviteRead.model_validate(invite)


@router.get("/workgroups/{workgroup_id}/invites", response_model=list[InviteRead])
def list_invites(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[InviteRead]:
    require_workgroup_owner(session, workgroup_id, user.id)
    invites = session.exec(
        select(Invite)
        .where(Invite.workgroup_id == workgroup_id)
        .order_by(Invite.created_at.desc())
    ).all()
    return [InviteRead.model_validate(item) for item in invites]


@router.post("/workgroups/{workgroup_id}/invites/{token}/accept", response_model=WorkgroupRead)
def accept_invite(
    workgroup_id: str,
    token: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkgroupRead:
    invite = session.exec(
        select(Invite).where(
            Invite.workgroup_id == workgroup_id,
            Invite.token == token,
            Invite.status == "pending",
        )
    ).first()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    expires_at = _normalize_utc(invite.expires_at)
    if expires_at and expires_at < utc_now():
        invite.status = "expired"
        session.add(invite)
        session.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite has expired")

    if invite.email.lower() != user.email.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invite email does not match current user")

    existing = session.exec(
        select(Membership).where(Membership.workgroup_id == workgroup_id, Membership.user_id == user.id)
    ).first()
    if not existing:
        session.add(Membership(workgroup_id=workgroup_id, user_id=user.id, role="member"))

    invite.status = "accepted"
    invite.accepted_at = utc_now()
    session.add(invite)

    add_activity_participant(session, workgroup_id, user.id)
    display_name = (user.name or "").strip() or user.email
    post_activity(session, workgroup_id, "member_joined", display_name, actor_user_id=user.id)

    session.commit()

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")
    return WorkgroupRead.model_validate(workgroup)


@router.post("/workgroups/{workgroup_id}/agents", response_model=AgentRead)
def create_agent(
    workgroup_id: str,
    payload: AgentCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    allowed_for_wg = set(available_tools_for_workgroup(session, workgroup_id))
    unknown_tools = sorted(set(payload.tool_names) - allowed_for_wg)
    if unknown_tools:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown tools: {', '.join(unknown_tools)}",
        )

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name cannot be empty")

    agent = Agent(
        workgroup_id=workgroup_id,
        created_by_user_id=user.id,
        name=name,
        description=payload.description.strip(),
        role=(payload.role.strip() or payload.description.strip()),
        personality=payload.personality.strip(),
        backstory=payload.backstory.strip(),
        model=payload.model.strip() or "claude-sonnet-4-5",
        temperature=payload.temperature,
        verbosity=payload.verbosity,
        tool_names=payload.tool_names,
        response_threshold=payload.response_threshold,
        follow_up_minutes=payload.follow_up_minutes,
        learning_state=dict(payload.learning_state or {}),
        sentiment_state=dict(payload.sentiment_state or {}),
        learned_preferences=dict(payload.learning_state or {}),
        icon=payload.icon or "",
    )
    session.add(agent)
    session.flush()
    post_activity(session, workgroup_id, "agent_created", agent.name, actor_user_id=user.id)
    session.commit()
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(agent)
    return AgentRead.model_validate(agent)


@router.get("/workgroups/{workgroup_id}/agents", response_model=list[AgentRead])
def list_agents(
    workgroup_id: str,
    include_hidden: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[AgentRead]:
    require_workgroup_membership(session, workgroup_id, user.id)
    query = select(Agent).where(Agent.workgroup_id == workgroup_id)
    if not include_hidden:
        query = query.where(Agent.description != ADMIN_AGENT_SENTINEL)
    agents = session.exec(query.order_by(Agent.created_at.asc())).all()
    return [AgentRead.model_validate(agent) for agent in agents]


@router.patch("/workgroups/{workgroup_id}/agents/{agent_id}", response_model=AgentRead)
def update_agent(
    workgroup_id: str,
    agent_id: str,
    payload: AgentUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or agent.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if payload.tool_names is not None:
        allowed_for_wg = set(available_tools_for_workgroup(session, workgroup_id))
        unknown_tools = sorted(set(payload.tool_names) - allowed_for_wg)
        if unknown_tools:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown tools: {', '.join(unknown_tools)}",
            )
        agent.tool_names = payload.tool_names

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name cannot be empty")
        agent.name = name

    if payload.description is not None:
        agent.description = payload.description.strip()
    if payload.role is not None:
        agent.role = payload.role.strip()
    if payload.personality is not None:
        agent.personality = payload.personality.strip()
    if payload.backstory is not None:
        agent.backstory = payload.backstory.strip()

    if payload.model is not None:
        model = payload.model.strip()
        if not model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent model cannot be empty")
        agent.model = model

    if payload.temperature is not None:
        agent.temperature = payload.temperature
    if payload.verbosity is not None:
        agent.verbosity = payload.verbosity
    if payload.response_threshold is not None:
        agent.response_threshold = payload.response_threshold
    if payload.follow_up_minutes is not None:
        agent.follow_up_minutes = payload.follow_up_minutes
    if payload.icon is not None:
        agent.icon = payload.icon

    session.add(agent)
    post_activity(session, workgroup_id, "agent_updated", agent.name, actor_user_id=user.id)
    session.commit()
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(agent)
    return AgentRead.model_validate(agent)


@router.post("/workgroups/{workgroup_id}/agents/{agent_id}/clear-conversation", response_model=AgentConversationClearRead)
def clear_agent_conversation(
    workgroup_id: str,
    agent_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentConversationClearRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or agent.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    conversation = session.exec(
        select(Conversation).where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "direct",
            Conversation.topic == direct_topic_key_user_agent(user.id, agent_id),
        )
    ).first()

    if not conversation:
        return AgentConversationClearRead(conversation_id=None, deleted_messages=0)

    counts = clear_conversation_messages(session, conversation.id)
    session.commit()
    return AgentConversationClearRead(
        conversation_id=conversation.id,
        deleted_messages=counts.get("messages", 0),
    )


@router.post("/workgroups/{workgroup_id}/agents/{agent_id}/clone", response_model=AgentRead)
def clone_agent(
    workgroup_id: str,
    agent_id: str,
    payload: AgentCloneRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or agent.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.description == ADMIN_AGENT_SENTINEL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot clone the admin agent")

    target_workgroup_id = payload.target_workgroup_id or workgroup_id
    if target_workgroup_id != workgroup_id:
        require_workgroup_owner(session, target_workgroup_id, user.id)
        target_workgroup = session.get(Workgroup, target_workgroup_id)
        if not target_workgroup:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target workgroup not found")

    name = payload.name.strip() if payload.name else f"{agent.name} (copy)"
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name cannot be empty")

    # Validate tools against target workgroup — keep only valid ones
    allowed_for_target = set(available_tools_for_workgroup(session, target_workgroup_id))
    valid_tools = [t for t in (agent.tool_names or []) if t in allowed_for_target]

    cloned = Agent(
        workgroup_id=target_workgroup_id,
        created_by_user_id=user.id,
        name=name,
        description=agent.description,
        role=agent.role,
        personality=agent.personality,
        backstory=agent.backstory,
        model=agent.model,
        temperature=agent.temperature,
        verbosity=agent.verbosity,
        tool_names=valid_tools,
        response_threshold=agent.response_threshold,
        follow_up_minutes=agent.follow_up_minutes,
        learning_state=dict(agent.learning_state) if payload.include_learned_state else {},
        sentiment_state=dict(agent.sentiment_state) if payload.include_learned_state else {},
        learned_preferences=dict(agent.learned_preferences) if payload.include_learned_state else {},
        icon=agent.icon or "",
    )
    session.add(cloned)
    session.flush()
    post_activity(session, target_workgroup_id, "agent_cloned", cloned.name, actor_user_id=user.id)
    session.commit()
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(cloned)
    return AgentRead.model_validate(cloned)


@router.get("/workgroups/{workgroup_id}/agents/{agent_id}/learnings", response_model=AgentLearningsRead)
def get_agent_learnings(
    workgroup_id: str,
    agent_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentLearningsRead:
    require_workgroup_membership(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or agent.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    memories = session.exec(
        select(AgentMemory)
        .where(AgentMemory.agent_id == agent_id)
        .order_by(AgentMemory.created_at.desc())
        .limit(20)
    ).all()

    signals = session.exec(
        select(AgentLearningEvent)
        .where(AgentLearningEvent.agent_id == agent_id)
        .order_by(AgentLearningEvent.created_at.desc())
        .limit(15)
    ).all()

    return AgentLearningsRead(
        learning_state=dict(agent.learning_state or {}),
        sentiment_state=dict(agent.sentiment_state or {}),
        memories=[AgentMemoryRead.model_validate(m) for m in memories],
        recent_signals=[
            AgentLearningSignalRead(
                signal_type=s.signal_type,
                value=dict(s.value or {}),
                created_at=s.created_at,
            )
            for s in signals
        ],
    )


@router.get("/workgroups/{workgroup_id}/members", response_model=list[MemberRead])
def list_members(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[MemberRead]:
    require_workgroup_membership(session, workgroup_id, user.id)
    rows = list_workgroup_members(session, workgroup_id)
    return [
        MemberRead(
            user_id=row_user.id,
            email=row_user.email,
            name=row_user.name,
            role=row_membership.role,
            picture=row_user.picture or "",
        )
        for row_membership, row_user in rows
    ]


@router.get("/workgroups/{workgroup_id}/usage", response_model=WorkgroupUsageRead)
def get_usage(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkgroupUsageRead:
    require_workgroup_membership(session, workgroup_id, user.id)
    usage = get_workgroup_usage(session, workgroup_id)
    return WorkgroupUsageRead(**usage)


@router.get("/workgroups/{workgroup_id}/administration", response_model=ConversationRead)
def get_administration_conversation(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ConversationRead:
    require_workgroup_membership(session, workgroup_id, user.id)
    _admin_agent, admin_conversation, changed = ensure_admin_workspace_for_workgroup_id(session, workgroup_id)
    if changed:
        session.commit()
    session.refresh(admin_conversation)
    return ConversationRead.model_validate(admin_conversation)
