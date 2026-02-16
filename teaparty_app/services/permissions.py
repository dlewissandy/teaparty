from fastapi import HTTPException, status
from sqlmodel import Session, select

from teaparty_app.models import Membership

EDITOR_ROLES = {"owner", "editor"}


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


def require_workgroup_editor(session: Session, workgroup_id: str, user_id: str) -> Membership:
    """Require at least editor role (owner or editor)."""
    membership = require_workgroup_membership(session, workgroup_id, user_id)
    if membership.role not in EDITOR_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Editor permissions required")
    return membership


def check_budget(membership: Membership) -> None:
    """Raise 403 if member has exceeded their cost budget."""
    if membership.budget_limit_usd is None:
        return
    if membership.budget_used_usd >= membership.budget_limit_usd:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Budget exceeded. Contact the workgroup owner to refresh your budget.",
        )
