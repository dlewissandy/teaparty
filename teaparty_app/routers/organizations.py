from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Membership, Organization, User, Workgroup
from teaparty_app.schemas import OrganizationCreateRequest, OrganizationRead, OrganizationUpdateRequest
from teaparty_app.services.admin_workspace import ensure_admin_workspace
from teaparty_app.services.admin_workspace.bootstrap import ADMINISTRATION_WORKGROUP_NAME

router = APIRouter(prefix="/api", tags=["organizations"])


@router.get("/organizations", response_model=list[OrganizationRead])
def list_organizations(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[OrganizationRead]:
    # Orgs the user owns
    owned = select(Organization.id).where(Organization.owner_id == user.id)

    # Orgs the user is a member of via workgroup membership
    member_org_ids = (
        select(Workgroup.organization_id)
        .join(Membership, Membership.workgroup_id == Workgroup.id)
        .where(Membership.user_id == user.id, Workgroup.organization_id.isnot(None))
    )

    orgs = session.exec(
        select(Organization)
        .where(Organization.id.in_(owned.union(member_org_ids)))
        .order_by(Organization.created_at.asc())
    ).all()
    return [OrganizationRead.model_validate(o) for o in orgs]


@router.post("/organizations", response_model=OrganizationRead)
def create_organization(
    payload: OrganizationCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OrganizationRead:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization name cannot be empty")

    org = Organization(name=name, description=payload.description.strip(), owner_id=user.id)
    session.add(org)
    session.flush()

    # Create an Administration workgroup for this organization
    admin_wg = Workgroup(
        name=ADMINISTRATION_WORKGROUP_NAME,
        files=[],
        owner_id=user.id,
        organization_id=org.id,
    )
    session.add(admin_wg)
    session.flush()
    session.add(Membership(workgroup_id=admin_wg.id, user_id=user.id, role="owner"))
    ensure_admin_workspace(session, admin_wg)

    session.commit()
    session.refresh(org)
    return OrganizationRead.model_validate(org)


@router.patch("/organizations/{org_id}", response_model=OrganizationRead)
def update_organization(
    org_id: str,
    payload: OrganizationUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OrganizationRead:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the organization owner can update it")

    if payload.name is None and payload.description is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No updates provided")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization name cannot be empty")
        org.name = name

    if payload.description is not None:
        org.description = payload.description.strip()

    session.add(org)
    session.commit()
    session.refresh(org)
    return OrganizationRead.model_validate(org)


@router.post("/organizations/{org_id}/admin-conversation")
def ensure_org_admin_conversation(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    # Find or create the org's Administration workgroup
    admin_wg = session.exec(
        select(Workgroup).where(
            Workgroup.organization_id == org_id,
            Workgroup.name == ADMINISTRATION_WORKGROUP_NAME,
        )
    ).first()

    if not admin_wg:
        admin_wg = Workgroup(
            name=ADMINISTRATION_WORKGROUP_NAME,
            files=[],
            owner_id=org.owner_id,
            organization_id=org.id,
        )
        session.add(admin_wg)
        session.flush()
        session.add(Membership(workgroup_id=admin_wg.id, user_id=org.owner_id, role="owner"))

    # Ensure the requesting user has membership
    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == admin_wg.id,
            Membership.user_id == user.id,
        )
    ).first()
    if not membership:
        session.add(Membership(workgroup_id=admin_wg.id, user_id=user.id, role="member"))

    # Ensure admin agent + conversation exist
    _agent, conversation, _changed = ensure_admin_workspace(session, admin_wg)
    session.commit()

    return {
        "workgroup_id": admin_wg.id,
        "conversation_id": conversation.id,
    }


@router.delete("/organizations/{org_id}", status_code=204)
def delete_organization(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the organization owner can delete it")

    # Cascade-delete all workgroups in this org
    from teaparty_app.services.admin_workspace.tools import delete_workgroup_data

    workgroups = session.exec(
        select(Workgroup).where(Workgroup.organization_id == org_id)
    ).all()
    for wg in workgroups:
        delete_workgroup_data(session, wg.id)

    session.delete(org)
    session.commit()
