from datetime import timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.deps import get_current_user
from teaparty_app.db import get_session
from teaparty_app.models import Agent, Conversation, Membership, Organization, User, Workgroup, utc_now
from teaparty_app.schemas import (
    AgentRead,
    ConversationRead,
    WorkgroupCreateRequest,
    WorkgroupFileWrite,
    WorkgroupRead,
    WorkgroupTemplateAgentWrite,
    WorkgroupTemplateRead,
    WorkgroupUpdateRequest,
    WorkgroupUsageRead,
)
from teaparty_app.services.activity import (
    ensure_activity_conversation,
    post_bulk_file_change_activity,
)
from teaparty_app.services.admin_workspace import (
    ADMIN_AGENT_SENTINEL,
    ensure_admin_workspace,
    ensure_admin_workspace_for_workgroup_id,
    ensure_lead_agent,
    lead_agent_name,
    list_members as list_workgroup_members,
)
from teaparty_app.services.admin_workspace.bootstrap import ADMINISTRATION_WORKGROUP_NAME
from teaparty_app.services.llm_usage import get_workgroup_usage
from teaparty_app.services.permissions import require_workgroup_editor, require_workgroup_membership, require_workgroup_owner
from teaparty_app.services.sync_events import publish_sync_event
from teaparty_app.services.workgroup_templates import (
    TEMPLATE_ROOT,
    WORKGROUP_STORAGE_ROOT,
    _is_org_storage_path,
    _is_workgroup_storage_path,
    list_workgroup_templates,
    org_storage_files,
    template_storage_files,
    templates_from_storage_files,
    workgroup_storage_files,
)

router = APIRouter(prefix="/api", tags=["workgroups"])


def _enrich_org_names(session: Session, reads: list[WorkgroupRead]) -> list[WorkgroupRead]:
    org_ids = {r.organization_id for r in reads if r.organization_id}
    if not org_ids:
        return reads
    orgs = session.exec(select(Organization).where(Organization.id.in_(org_ids))).all()
    name_map = {o.id: o.name for o in orgs}
    for r in reads:
        if r.organization_id:
            r.organization_name = name_map.get(r.organization_id, "")
    return reads


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
            topic_id = ""
        else:
            path = raw.path.strip()
            content = raw.content if isinstance(raw.content, str) else str(raw.content or "")
            file_id = (raw.id or "").strip() or str(uuid4())
            topic_id = str(raw.topic_id or "").strip() if raw.topic_id is not None else ""

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
        normalized.append({"id": file_id, "path": path, "content": content, "topic_id": topic_id})
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

        topic_id = ""
        if isinstance(item, str):
            path = item.strip()
        elif isinstance(item, dict):
            file_id = str(item.get("id", "")).strip()
            path = str(item.get("path", "")).strip()
            raw_content = item.get("content", "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content or "")
            topic_id = str(item.get("topic_id", "")).strip()
        else:
            continue

        if not path or len(path) > 512 or len(content) > 200000 or path in seen_paths:
            continue

        file_id = file_id or str(uuid4())
        while file_id in seen_ids:
            file_id = str(uuid4())
        seen_ids.add(file_id)
        seen_paths.add(path)
        normalized.append({"id": file_id, "path": path, "content": content, "topic_id": topic_id})
    return normalized


def _template_storage_seed_files() -> list[dict[str, str]]:
    defaults = template_storage_files(list_workgroup_templates())
    return _normalize_workgroup_files([WorkgroupFileWrite(path=item["path"], content=item["content"]) for item in defaults])


def _is_template_storage_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("/")
    return (
        normalized.startswith(f"{TEMPLATE_ROOT}/")
        or normalized.startswith(".templates/workgroups/")
        or normalized.startswith(".templates/organizations/")
        or normalized.startswith("templates/")
    )


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
                "prompt": agent.prompt,
                "model": agent.model,
                "tools": list(agent.tools or []),
                "permission_mode": agent.permission_mode,
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
        .where(
            Workgroup.owner_id == user.id,
            Workgroup.name == ADMINISTRATION_WORKGROUP_NAME,
            Workgroup.organization_id.is_(None),
        )
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


def _reconcile_org_administration_files(session: Session, admin_workgroup: Workgroup) -> bool:
    org_id = admin_workgroup.organization_id
    org = session.get(Organization, org_id)
    if not org:
        return False

    all_workgroups = session.exec(
        select(Workgroup)
        .where(Workgroup.organization_id == org_id)
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
                "prompt": agent.prompt,
                "model": agent.model,
                "tools": list(agent.tools or []),
                "permission_mode": agent.permission_mode,
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

    # Collect unique org-level members with names/emails
    all_member_user_ids = {m.user_id for m in all_memberships}
    member_users = session.exec(
        select(User).where(User.id.in_(all_member_user_ids))
    ).all() if all_member_user_ids else []
    user_map = {u.id: u for u in member_users}
    org_members: list[dict] = []
    seen_member_ids: set[str] = set()
    for m in all_memberships:
        if m.user_id in seen_member_ids:
            continue
        seen_member_ids.add(m.user_id)
        u = user_map.get(m.user_id)
        role = "owner" if m.user_id == org.owner_id else "member"
        org_members.append({
            "user_id": m.user_id,
            "name": (u.name or "") if u else "",
            "email": (u.email or "") if u else "",
            "role": role,
        })

    org_dict = {
        "id": org.id,
        "name": org.name,
        "description": org.description,
        "owner_id": org.owner_id,
    }

    desired_entries = org_storage_files(org_dict, wg_dicts, agents_by_wg, org_members, members_by_wg)
    desired_by_path = {item["path"]: item["content"] for item in desired_entries}

    existing_files = _normalize_persisted_workgroup_files(admin_workgroup.files)
    # Keep files that are neither org-storage nor legacy system-scoped paths
    non_storage_files = [
        dict(f) for f in existing_files
        if not _is_org_storage_path(f["path"])
        and not _is_workgroup_storage_path(f["path"])
        and not _is_template_storage_path(f["path"])
    ]
    existing_storage_files = [dict(f) for f in existing_files if _is_org_storage_path(f["path"])]
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

    # Also detect legacy files that need purging
    legacy_count = len(existing_files) - len(non_storage_files) - len(existing_storage_files)
    changed = changed or legacy_count > 0

    if changed:
        admin_workgroup.files = non_storage_files + canonical_storage_files
        session.add(admin_workgroup)

    return changed


def _sync_workgroup_storage_for_user(session: Session, user: User) -> None:
    admin_wg = session.exec(
        select(Workgroup)
        .where(
            Workgroup.owner_id == user.id,
            Workgroup.name == ADMINISTRATION_WORKGROUP_NAME,
            Workgroup.organization_id.is_(None),
        )
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


def create_workgroup_with_template(
    session: Session,
    owner: User,
    name: str,
    organization_id: str,
    template_key: str | None = None,
) -> Workgroup:
    """Create a workgroup with optional template, returning the new Workgroup.

    Reusable from both the REST endpoint and global admin tools.
    """
    name = name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workgroup name cannot be empty")

    templates, _changed = _load_user_workgroup_templates(session, owner)
    templates_by_key = {item.key: item for item in templates}

    selected_template: WorkgroupTemplateRead | None = None
    if template_key:
        template_key = template_key.strip()
        selected_template = templates_by_key.get(template_key)
        if not selected_template:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown workgroup template '{template_key}'",
            )

    files: list[dict[str, str]] = []
    template_agents: list[WorkgroupTemplateAgentWrite] = []
    if selected_template:
        files = _normalize_workgroup_files(
            [WorkgroupFileWrite(path=item.path, content=item.content) for item in selected_template.files]
        )
        template_agents = [
            WorkgroupTemplateAgentWrite.model_validate(item.model_dump()) for item in selected_template.agents
        ]

    group = Workgroup(name=name, files=files, owner_id=owner.id, organization_id=organization_id)
    session.add(group)
    session.flush()

    session.add(Membership(workgroup_id=group.id, user_id=owner.id, role="owner"))

    for draft in template_agents:
        agent_name = draft.name.strip()
        if not agent_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name cannot be empty")
        session.add(
            Agent(
                workgroup_id=group.id,
                created_by_user_id=owner.id,
                name=agent_name,
                description=draft.description.strip(),
                prompt=draft.prompt.strip(),
                model=draft.model.strip() or "sonnet",
                tools=draft.tools,
            )
        )

    ensure_lead_agent(session, group)
    ensure_admin_workspace(session, group)
    ensure_activity_conversation(session, group)
    session.flush()
    return group


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
    # When explicit files/agents are provided, use the full resolution path
    if payload.files is not None or payload.agents is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workgroup name cannot be empty")

        templates, _changed = _load_user_workgroup_templates(session, user)
        templates_by_key = {item.key: item for item in templates}
        selected_template = _resolve_template_for_create(payload, templates_by_key)
        files = _resolve_workgroup_creation_files(payload, selected_template)
        template_agents = _resolve_workgroup_creation_agents(payload, selected_template)
        org = session.get(Organization, payload.organization_id)
        if not org:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization not found")

        group = Workgroup(name=name, files=files, owner_id=user.id, organization_id=payload.organization_id)
        session.add(group)
        session.flush()
        session.add(Membership(workgroup_id=group.id, user_id=user.id, role="owner"))

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
                    prompt=draft.prompt.strip(),
                    model=draft.model.strip() or "sonnet",
                    tools=draft.tools,
                )
            )

        ensure_lead_agent(session, group)
        ensure_admin_workspace(session, group)
        ensure_activity_conversation(session, group)
    else:
        org = session.get(Organization, payload.organization_id)
        if not org:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization not found")
        group = create_workgroup_with_template(
            session=session,
            owner=user,
            name=payload.name,
            template_key=payload.template_key,
            organization_id=payload.organization_id,
        )

    session.commit()
    publish_sync_event(session, "org", group.organization_id, "sync:workgroups_changed", {"org_id": group.organization_id})
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(group)
    result = WorkgroupRead.model_validate(group)
    return _enrich_org_names(session, [result])[0]


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
        _lead_agent, lead_created = ensure_lead_agent(session, workgroup)
        _admin_agent, _admin_conversation, group_changed = ensure_admin_workspace(session, workgroup)
        _activity_conversation, activity_changed = ensure_activity_conversation(session, workgroup)
        groups_changed = groups_changed or lead_created
        if workgroup.name == ADMINISTRATION_WORKGROUP_NAME and workgroup.organization_id:
            org_changed = _reconcile_org_administration_files(session, workgroup)
            groups_changed = groups_changed or org_changed
        groups_changed = groups_changed or group_changed or activity_changed
    if changed or groups_changed:
        session.commit()

    results = [WorkgroupRead.model_validate(item) for item in rows]
    return _enrich_org_names(session, results)


@router.get("/workgroups/{workgroup_id}", response_model=WorkgroupRead)
def get_workgroup(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkgroupRead:
    require_workgroup_membership(session, workgroup_id, user.id)
    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")
    result = WorkgroupRead.model_validate(workgroup)
    return _enrich_org_names(session, [result])[0]


@router.patch("/workgroups/{workgroup_id}", response_model=WorkgroupRead)
def update_workgroup(
    workgroup_id: str,
    payload: WorkgroupUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkgroupRead:
    has_team_config = (
        payload.team_model is not None
        or payload.team_permission_mode is not None
        or payload.team_max_turns is not None
        or payload.team_max_cost_usd is not None
        or payload.team_max_time_seconds is not None
    )
    files_only = (
        payload.files is not None
        and payload.name is None
        and payload.is_discoverable is None
        and payload.service_description is None
        and payload.workspace_enabled is None
        and payload.organization_id is None
        and not has_team_config
    )
    if files_only:
        require_workgroup_editor(session, workgroup_id, user.id)
    else:
        require_workgroup_owner(session, workgroup_id, user.id)

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")

    if (
        payload.name is None
        and payload.files is None
        and payload.is_discoverable is None
        and payload.service_description is None
        and payload.workspace_enabled is None
        and payload.organization_id is None
        and not has_team_config
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No updates provided")

    old_files = _normalize_persisted_workgroup_files(workgroup.files) if payload.files is not None else None

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workgroup name cannot be empty")
        workgroup.name = name
        # Rename the lead agent to match.
        lead = session.exec(
            select(Agent).where(Agent.workgroup_id == workgroup.id, Agent.is_lead == True)  # noqa: E712
        ).first()
        if lead:
            lead.name = lead_agent_name(name)
            session.add(lead)

    if payload.files is not None:
        workgroup.files = _normalize_workgroup_files(payload.files)

    if payload.is_discoverable is not None:
        workgroup.is_discoverable = payload.is_discoverable

    if payload.service_description is not None:
        workgroup.service_description = payload.service_description.strip()

    if payload.workspace_enabled is not None and payload.workspace_enabled != workgroup.workspace_enabled:
        workgroup.workspace_enabled = payload.workspace_enabled
        try:
            from teaparty_app.services.workspace_manager import workspace_root_configured

            if workspace_root_configured():
                if payload.workspace_enabled:
                    from teaparty_app.services.workspace_manager import init_workspace

                    init_workspace(session, workgroup_id)
                else:
                    from teaparty_app.models import Workspace

                    ws = session.exec(
                        select(Workspace).where(Workspace.workgroup_id == workgroup_id)
                    ).first()
                    if ws:
                        from teaparty_app.services.workspace_manager import destroy_workspace

                        destroy_workspace(session, ws)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Workspace toggle failed for workgroup %s", workgroup_id, exc_info=True
            )

    if payload.organization_id is not None:
        if not payload.organization_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workgroups must belong to an organization")
        org = session.get(Organization, payload.organization_id)
        if not org:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization not found")
        workgroup.organization_id = org.id

    if payload.team_model is not None:
        workgroup.team_model = payload.team_model
    if payload.team_permission_mode is not None:
        workgroup.team_permission_mode = payload.team_permission_mode
    if payload.team_max_turns is not None:
        workgroup.team_max_turns = payload.team_max_turns
    if payload.team_max_cost_usd is not None:
        workgroup.team_max_cost_usd = payload.team_max_cost_usd
    if payload.team_max_time_seconds is not None:
        workgroup.team_max_time_seconds = payload.team_max_time_seconds

    if old_files is not None:
        new_files = _normalize_persisted_workgroup_files(workgroup.files)
        post_bulk_file_change_activity(session, workgroup_id, old_files, new_files, actor_user_id=user.id)

    session.add(workgroup)
    session.commit()
    publish_sync_event(session, "workgroup", workgroup.id, "sync:workgroup_updated", {"workgroup_id": workgroup.id})
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(workgroup)
    result = WorkgroupRead.model_validate(workgroup)
    return _enrich_org_names(session, [result])[0]


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
    require_workgroup_owner(session, workgroup_id, user.id)
    _admin_agent, admin_conversation, changed = ensure_admin_workspace_for_workgroup_id(session, workgroup_id)
    if changed:
        session.commit()
    session.refresh(admin_conversation)
    return ConversationRead.model_validate(admin_conversation)
