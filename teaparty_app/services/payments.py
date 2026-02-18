"""Credit balance, escrow, release, and refund operations for engagements."""

from __future__ import annotations

from sqlmodel import Session, select

from teaparty_app.models import (
    Engagement,
    OrgBalance,
    Organization,
    PaymentTransaction,
    Workgroup,
    utc_now,
)


class InsufficientBalanceError(Exception):
    def __init__(self, available: float, required: float):
        self.available = available
        self.required = required
        super().__init__(f"Insufficient balance: {available} available, {required} required")


def get_or_create_balance(session: Session, org_id: str) -> OrgBalance:
    balance = session.exec(
        select(OrgBalance).where(OrgBalance.organization_id == org_id)
    ).first()
    if balance:
        return balance
    balance = OrgBalance(organization_id=org_id)
    session.add(balance)
    session.flush()
    return balance


def add_credits(
    session: Session,
    org_id: str,
    amount: float,
    description: str = "",
) -> PaymentTransaction:
    balance = get_or_create_balance(session, org_id)
    balance.balance_credits += amount
    balance.updated_at = utc_now()
    session.add(balance)

    txn = PaymentTransaction(
        organization_id=org_id,
        transaction_type="credit",
        amount_credits=amount,
        balance_after_credits=balance.balance_credits,
        description=description or "Credits added",
    )
    session.add(txn)
    session.flush()
    return txn


def escrow_for_engagement(
    session: Session,
    engagement: Engagement,
) -> PaymentTransaction | None:
    """Hold credits from the source org's balance for an engagement.

    Returns None if the engagement has no agreed price (free engagement).
    Raises InsufficientBalanceError if balance is too low.
    """
    price = engagement.agreed_price_credits
    if not price or price <= 0:
        return None

    # Find the source org
    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    if not source_wg or not source_wg.organization_id:
        return None
    source_org_id = source_wg.organization_id

    # Find the target org for counterparty tracking
    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    target_org_id = target_wg.organization_id if target_wg else None

    balance = get_or_create_balance(session, source_org_id)
    if balance.balance_credits < price:
        raise InsufficientBalanceError(balance.balance_credits, price)

    balance.balance_credits -= price
    balance.updated_at = utc_now()
    session.add(balance)

    txn = PaymentTransaction(
        organization_id=source_org_id,
        engagement_id=engagement.id,
        transaction_type="escrow",
        amount_credits=-price,
        balance_after_credits=balance.balance_credits,
        counterparty_org_id=target_org_id,
        description=f"Escrow for engagement: {engagement.title}",
    )
    session.add(txn)

    engagement.payment_status = "escrowed"
    session.add(engagement)
    session.flush()
    return txn


def release_escrow(
    session: Session,
    engagement: Engagement,
) -> PaymentTransaction | None:
    """Release escrowed credits to the target org on successful review."""
    if engagement.payment_status != "escrowed":
        return None

    price = engagement.agreed_price_credits
    if not price or price <= 0:
        return None

    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    if not target_wg or not target_wg.organization_id:
        return None
    target_org_id = target_wg.organization_id

    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    source_org_id = source_wg.organization_id if source_wg else None

    # Credit the target org
    target_balance = get_or_create_balance(session, target_org_id)
    target_balance.balance_credits += price
    target_balance.updated_at = utc_now()
    session.add(target_balance)

    txn = PaymentTransaction(
        organization_id=target_org_id,
        engagement_id=engagement.id,
        transaction_type="release",
        amount_credits=price,
        balance_after_credits=target_balance.balance_credits,
        counterparty_org_id=source_org_id,
        description=f"Payment received for engagement: {engagement.title}",
    )
    session.add(txn)

    engagement.payment_status = "paid"
    session.add(engagement)
    session.flush()
    return txn


def refund_escrow(
    session: Session,
    engagement: Engagement,
) -> PaymentTransaction | None:
    """Return escrowed credits to the source org on cancellation."""
    if engagement.payment_status != "escrowed":
        return None

    price = engagement.agreed_price_credits
    if not price or price <= 0:
        return None

    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    if not source_wg or not source_wg.organization_id:
        return None
    source_org_id = source_wg.organization_id

    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    target_org_id = target_wg.organization_id if target_wg else None

    balance = get_or_create_balance(session, source_org_id)
    balance.balance_credits += price
    balance.updated_at = utc_now()
    session.add(balance)

    txn = PaymentTransaction(
        organization_id=source_org_id,
        engagement_id=engagement.id,
        transaction_type="refund",
        amount_credits=price,
        balance_after_credits=balance.balance_credits,
        counterparty_org_id=target_org_id,
        description=f"Refund for cancelled engagement: {engagement.title}",
    )
    session.add(txn)

    engagement.payment_status = "refunded"
    session.add(engagement)
    session.flush()
    return txn
