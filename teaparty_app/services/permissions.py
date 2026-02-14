from fastapi import HTTPException, status
from sqlmodel import Session, select

from teaparty_app.models import Membership


def require_workgroup_membership(session: Session, workgroup_id: str, user_id: str) -> Membership:
    membership = session.exec(
        select(Membership).where(Membership.workgroup_id == workgroup_id, Membership.user_id == user_id)
    ).first()
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workgroup member")
    return membership


def require_workgroup_owner(session: Session, workgroup_id: str, user_id: str) -> Membership:
    membership = require_workgroup_membership(session, workgroup_id, user_id)
    if membership.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner permissions required")
    return membership
