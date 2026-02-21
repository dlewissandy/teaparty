"""REST API for organization credit balance and payment transactions."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Organization, PaymentTransaction, User
from teaparty_app.schemas import AddCreditsRequest, OrgBalanceRead, PaymentTransactionRead
from teaparty_app.services.payments import add_credits, get_or_create_balance

router = APIRouter(prefix="/api", tags=["balance"])


def _require_org_owner(session: Session, org_id: str, user: User) -> Organization:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.owner_id != user.id and not user.is_system_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the org owner can access balance")
    return org


@router.get("/organizations/{org_id}/balance", response_model=OrgBalanceRead)
def get_balance(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OrgBalanceRead:
    # Allow any org member to view balance (token economy transparency)
    from teaparty_app.models import OrgMembership
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.owner_id != user.id and not user.is_system_admin:
        membership = session.exec(
            select(OrgMembership).where(
                OrgMembership.organization_id == org_id,
                OrgMembership.user_id == user.id,
            )
        ).first()
        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this organization")
    balance = get_or_create_balance(session, org_id)
    session.commit()
    return OrgBalanceRead.model_validate(balance)


@router.post("/organizations/{org_id}/credits", response_model=PaymentTransactionRead)
def add_org_credits(
    org_id: str,
    payload: AddCreditsRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PaymentTransactionRead:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if not user.is_system_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only system admins can add credits")

    txn = add_credits(session, org_id, payload.amount, payload.description)
    session.commit()
    session.refresh(txn)
    return PaymentTransactionRead.model_validate(txn)


@router.get("/organizations/{org_id}/transactions", response_model=list[PaymentTransactionRead])
def list_transactions(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[PaymentTransactionRead]:
    _require_org_owner(session, org_id, user)
    txns = session.exec(
        select(PaymentTransaction)
        .where(PaymentTransaction.organization_id == org_id)
        .order_by(PaymentTransaction.created_at.desc())
    ).all()
    return [PaymentTransactionRead.model_validate(t) for t in txns]
