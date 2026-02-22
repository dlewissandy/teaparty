"""Tests for Partnership model and CRUD endpoints.

Partnerships are asymmetric: A adding B as a partner only appears in A's list.
There is no invite/proposal lifecycle — partnerships are created immediately.
"""

import unittest

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from teaparty_app.models import (
    Engagement,
    Organization,
    OrgMembership,
    Partnership,
    PaymentTransaction,
    User,
    Workgroup,
    utc_now,
)
from teaparty_app.routers.partnerships import (
    get_partner_engagements,
    get_partner_transactions,
    list_partnerships,
    propose_partnership,
    revoke_partnership,
)
from teaparty_app.schemas import PartnershipProposeRequest


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_user(session: Session, user_id: str, email: str, name: str = "Test User") -> User:
    user = User(id=user_id, email=email, name=name)
    session.add(user)
    session.flush()
    return user


def _make_org(session: Session, org_id: str, owner_id: str, name: str = "Test Org") -> Organization:
    org = Organization(id=org_id, name=name, owner_id=owner_id)
    session.add(org)
    session.flush()
    return org


def _make_partnership(
    session: Session,
    source_org_id: str,
    target_org_id: str,
    proposed_by_user_id: str,
    status: str = "accepted",
    direction: str = "bidirectional",
) -> Partnership:
    p = Partnership(
        source_org_id=source_org_id,
        target_org_id=target_org_id,
        proposed_by_user_id=proposed_by_user_id,
        status=status,
        direction=direction,
    )
    session.add(p)
    session.flush()
    return p


class AddPartnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_user(session, "u-other", "other@example.com", "Other")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            session.commit()

    def test_creates_partnership_immediately_accepted(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = propose_partnership(
                payload=PartnershipProposeRequest(
                    source_org_id="org-src",
                    target_org_id="org-tgt",
                    direction="bidirectional",
                ),
                session=session,
                user=user,
            )

        self.assertEqual(result.source_org_id, "org-src")
        self.assertEqual(result.target_org_id, "org-tgt")
        self.assertEqual(result.status, "accepted")
        self.assertIsNotNone(result.accepted_at)
        self.assertEqual(result.source_org_name, "Source Org")
        self.assertEqual(result.target_org_name, "Target Org")

    def test_self_partnership_rejected(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                propose_partnership(
                    payload=PartnershipProposeRequest(
                        source_org_id="org-src",
                        target_org_id="org-src",
                    ),
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_requires_source_org_ownership(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-other")
            with self.assertRaises(HTTPException) as ctx:
                propose_partnership(
                    payload=PartnershipProposeRequest(
                        source_org_id="org-src",
                        target_org_id="org-tgt",
                    ),
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_target_org_not_found(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                propose_partnership(
                    payload=PartnershipProposeRequest(
                        source_org_id="org-src",
                        target_org_id="org-nonexistent",
                    ),
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_duplicate_same_direction_rejected(self) -> None:
        with Session(self.engine) as session:
            _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                propose_partnership(
                    payload=PartnershipProposeRequest(
                        source_org_id="org-src",
                        target_org_id="org-tgt",
                    ),
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_reverse_direction_allowed(self) -> None:
        """A→B and B→A are independent partnerships."""
        with Session(self.engine) as session:
            _make_partnership(session, "org-tgt", "org-src", "u-tgt", status="accepted")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = propose_partnership(
                payload=PartnershipProposeRequest(
                    source_org_id="org-src",
                    target_org_id="org-tgt",
                ),
                session=session,
                user=user,
            )
        self.assertEqual(result.status, "accepted")

    def test_after_revoked_allowed(self) -> None:
        """Revoked partnerships don't block new ones."""
        with Session(self.engine) as session:
            _make_partnership(session, "org-src", "org-tgt", "u-src", status="revoked")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = propose_partnership(
                payload=PartnershipProposeRequest(
                    source_org_id="org-src",
                    target_org_id="org-tgt",
                ),
                session=session,
                user=user,
            )
        self.assertEqual(result.status, "accepted")

    def test_invalid_direction_rejected(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                propose_partnership(
                    payload=PartnershipProposeRequest(
                        source_org_id="org-src",
                        target_org_id="org-tgt",
                        direction="invalid_dir",
                    ),
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 400)


class RevokePartnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            session.commit()

    def test_revoke_by_source_owner(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = revoke_partnership(
                partnership_id=pid,
                session=session,
                user=user,
            )

        self.assertEqual(result.status, "revoked")
        self.assertIsNotNone(result.revoked_at)

    def test_revoke_by_target_owner_rejected(self) -> None:
        """Target org owner cannot revoke — only source owner can."""
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-tgt")
            with self.assertRaises(HTTPException) as ctx:
                revoke_partnership(
                    partnership_id=pid,
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_revoke_non_accepted_rejected(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="revoked")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                revoke_partnership(
                    partnership_id=pid,
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_revoke_by_unrelated_user_rejected(self) -> None:
        with Session(self.engine) as session:
            _make_user(session, "u-other", "other@example.com", "Outsider")
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-other")
            with self.assertRaises(HTTPException) as ctx:
                revoke_partnership(
                    partnership_id=pid,
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 403)


class ListPartnershipsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_user(session, "u-other", "other@example.com", "Outsider")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            _make_org(session, "org-other", "u-other", "Other Org")
            session.commit()

    def test_list_returns_only_source_partnerships(self) -> None:
        """Asymmetric: only return partnerships where the org is source."""
        with Session(self.engine) as session:
            _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            _make_partnership(session, "org-other", "org-src", "u-other", status="accepted")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            results = list_partnerships(
                org_id="org-src",
                status_filter=None,
                session=session,
                user=user,
            )

        # Only the first partnership (org-src as source), not the second (org-src as target)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].target_org_id, "org-tgt")

    def test_list_filter_by_status(self) -> None:
        with Session(self.engine) as session:
            _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            _make_partnership(session, "org-src", "org-other", "u-src", status="revoked")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            results = list_partnerships(
                org_id="org-src",
                status_filter="accepted",
                session=session,
                user=user,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "accepted")

    def test_list_requires_org_ownership(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-tgt")
            with self.assertRaises(HTTPException) as ctx:
                list_partnerships(
                    org_id="org-src",
                    status_filter=None,
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_list_org_not_found(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                list_partnerships(
                    org_id="nonexistent-org",
                    status_filter=None,
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_list_empty_when_no_partnerships(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            results = list_partnerships(
                org_id="org-src",
                status_filter=None,
                session=session,
                user=user,
            )
        self.assertEqual(len(results), 0)


class PartnershipModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            session.commit()

    def test_model_defaults(self) -> None:
        with Session(self.engine) as session:
            p = Partnership(
                source_org_id="org-src",
                target_org_id="org-tgt",
                proposed_by_user_id="u-src",
            )
            session.add(p)
            session.commit()
            session.refresh(p)

            self.assertEqual(p.status, "proposed")
            self.assertEqual(p.direction, "bidirectional")
            self.assertIsNotNone(p.created_at)
            self.assertIsNone(p.accepted_at)
            self.assertIsNone(p.revoked_at)

    def test_direction_source_to_target(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(
                session, "org-src", "org-tgt", "u-src", direction="source_to_target"
            )
            session.commit()
            session.refresh(p)

        self.assertEqual(p.direction, "source_to_target")


class PartnershipMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            session.commit()

    def test_message_stored(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = propose_partnership(
                payload=PartnershipProposeRequest(
                    source_org_id="org-src",
                    target_org_id="org-tgt",
                    message="Let's collaborate!",
                ),
                session=session,
                user=user,
            )

        self.assertEqual(result.message, "Let's collaborate!")

    def test_message_and_proposer_in_detail(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = propose_partnership(
                payload=PartnershipProposeRequest(
                    source_org_id="org-src",
                    target_org_id="org-tgt",
                    message="Partnership note",
                ),
                session=session,
                user=user,
            )

        self.assertEqual(result.message, "Partnership note")
        self.assertEqual(result.proposed_by_user_name, "Source Owner")

    def test_default_message_is_empty(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src")
            session.commit()
            session.refresh(p)

        self.assertEqual(p.message, "")


def _make_workgroup(
    session: Session,
    wg_id: str,
    owner_id: str,
    org_id: str,
    name: str = "Test WG",
) -> Workgroup:
    wg = Workgroup(id=wg_id, name=name, owner_id=owner_id, organization_id=org_id)
    session.add(wg)
    session.flush()
    return wg


def _make_engagement(
    session: Session,
    source_wg_id: str,
    target_wg_id: str,
    proposed_by: str,
    title: str = "Test Engagement",
    status: str = "proposed",
    review_rating: str | None = None,
    agreed_price_credits: float | None = None,
    payment_status: str = "none",
) -> Engagement:
    eng = Engagement(
        source_workgroup_id=source_wg_id,
        target_workgroup_id=target_wg_id,
        proposed_by_user_id=proposed_by,
        title=title,
        status=status,
        review_rating=review_rating,
        agreed_price_credits=agreed_price_credits,
        payment_status=payment_status,
    )
    session.add(eng)
    session.flush()
    return eng


def _make_transaction(
    session: Session,
    organization_id: str,
    counterparty_org_id: str,
    transaction_type: str = "escrow",
    amount_credits: float = -100.0,
    description: str = "",
    engagement_id: str | None = None,
) -> PaymentTransaction:
    txn = PaymentTransaction(
        organization_id=organization_id,
        counterparty_org_id=counterparty_org_id,
        transaction_type=transaction_type,
        amount_credits=amount_credits,
        description=description,
        engagement_id=engagement_id,
    )
    session.add(txn)
    session.flush()
    return txn


def _make_membership(session: Session, org_id: str, user_id: str) -> OrgMembership:
    m = OrgMembership(organization_id=org_id, user_id=user_id, role="member")
    session.add(m)
    session.flush()
    return m


class PartnerTransactionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_user(session, "u-member", "member@example.com", "Member")
            _make_user(session, "u-other", "other@example.com", "Outsider")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            _make_org(session, "org-other", "u-other", "Other Org")
            _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            session.commit()

    def test_returns_transactions_with_partner(self) -> None:
        with Session(self.engine) as session:
            t1 = _make_transaction(session, "org-src", "org-tgt", "escrow", -50.0, "Escrow for job")
            t2 = _make_transaction(session, "org-src", "org-tgt", "release", 30.0, "Released")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            results = get_partner_transactions(org_id="org-tgt", session=session, user=user)

        self.assertEqual(len(results), 2)
        # Ordered by created_at DESC — most recent first
        self.assertEqual(results[0].description, "Released")
        self.assertEqual(results[1].description, "Escrow for job")

    def test_excludes_transactions_with_other_orgs(self) -> None:
        with Session(self.engine) as session:
            _make_transaction(session, "org-src", "org-tgt", "escrow", -50.0, "With partner")
            _make_transaction(session, "org-src", "org-other", "escrow", -25.0, "With other")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            results = get_partner_transactions(org_id="org-tgt", session=session, user=user)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].description, "With partner")

    def test_requires_accepted_partnership(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-other")
            with self.assertRaises(HTTPException) as ctx:
                get_partner_transactions(org_id="org-tgt", session=session, user=user)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_partner_org_not_found(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                get_partner_transactions(org_id="org-nonexistent", session=session, user=user)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_empty_when_no_transactions(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            results = get_partner_transactions(org_id="org-tgt", session=session, user=user)
        self.assertEqual(len(results), 0)

    def test_member_can_access_via_membership(self) -> None:
        with Session(self.engine) as session:
            _make_membership(session, "org-src", "u-member")
            _make_transaction(session, "org-src", "org-tgt", "escrow", -100.0, "Member visible")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-member")
            results = get_partner_transactions(org_id="org-tgt", session=session, user=user)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].description, "Member visible")


class PartnerEngagementsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_user(session, "u-other", "other@example.com", "Outsider")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            _make_org(session, "org-other", "u-other", "Other Org")
            _make_workgroup(session, "wg-src", "u-src", "org-src", "Source WG")
            _make_workgroup(session, "wg-tgt", "u-tgt", "org-tgt", "Target WG")
            _make_workgroup(session, "wg-other", "u-other", "org-other", "Other WG")
            _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            session.commit()

    def test_returns_engagements_both_directions(self) -> None:
        """Outbound (we hired them) and inbound (they hired us) both appear."""
        with Session(self.engine) as session:
            _make_engagement(session, "wg-src", "wg-tgt", "u-src", title="Outbound job", status="completed")
            _make_engagement(session, "wg-tgt", "wg-src", "u-tgt", title="Inbound job", status="in_progress")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = get_partner_engagements(org_id="org-tgt", session=session, user=user)

        self.assertEqual(result.total, 2)
        titles = {e.title for e in result.engagements}
        self.assertEqual(titles, {"Outbound job", "Inbound job"})
        directions = {e.title: e.direction for e in result.engagements}
        self.assertEqual(directions["Outbound job"], "outbound")
        self.assertEqual(directions["Inbound job"], "inbound")

    def test_excludes_engagements_with_other_orgs(self) -> None:
        with Session(self.engine) as session:
            _make_engagement(session, "wg-src", "wg-tgt", "u-src", title="With partner")
            _make_engagement(session, "wg-src", "wg-other", "u-src", title="With other")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = get_partner_engagements(org_id="org-tgt", session=session, user=user)

        self.assertEqual(result.total, 1)
        self.assertEqual(result.engagements[0].title, "With partner")

    def test_summary_stats(self) -> None:
        with Session(self.engine) as session:
            _make_engagement(
                session, "wg-src", "wg-tgt", "u-src",
                title="Completed happy", status="reviewed",
                review_rating="satisfied", agreed_price_credits=100.0,
                payment_status="paid",
            )
            _make_engagement(
                session, "wg-src", "wg-tgt", "u-src",
                title="Completed unhappy", status="reviewed",
                review_rating="dissatisfied", agreed_price_credits=50.0,
                payment_status="paid",
            )
            _make_engagement(
                session, "wg-tgt", "wg-src", "u-tgt",
                title="Inbound completed", status="completed",
                agreed_price_credits=200.0, payment_status="escrowed",
            )
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = get_partner_engagements(org_id="org-tgt", session=session, user=user)

        self.assertEqual(result.total, 3)
        self.assertEqual(result.completed, 3)
        self.assertEqual(result.reviewed, 2)
        self.assertEqual(result.satisfied, 1)
        self.assertEqual(result.total_spend_credits, 150.0)  # 100 + 50 outbound
        self.assertEqual(result.total_earned_credits, 200.0)  # inbound

    def test_requires_accepted_partnership(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-other")
            with self.assertRaises(HTTPException) as ctx:
                get_partner_engagements(org_id="org-tgt", session=session, user=user)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_partner_org_not_found(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                get_partner_engagements(org_id="org-nonexistent", session=session, user=user)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_empty_when_no_engagements(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = get_partner_engagements(org_id="org-tgt", session=session, user=user)

        self.assertEqual(result.total, 0)
        self.assertEqual(result.engagements, [])

    def test_empty_when_no_workgroups(self) -> None:
        """If either org has no workgroups, returns empty summary."""
        engine = _make_engine()
        with Session(engine) as session:
            _make_user(session, "u-a", "a@example.com")
            _make_user(session, "u-b", "b@example.com")
            _make_org(session, "org-a", "u-a", "Org A")
            _make_org(session, "org-b", "u-b", "Org B")
            _make_partnership(session, "org-a", "org-b", "u-a", status="accepted")
            # No workgroups created
            session.commit()

        with Session(engine) as session:
            user = session.get(User, "u-a")
            result = get_partner_engagements(org_id="org-b", session=session, user=user)

        self.assertEqual(result.total, 0)


if __name__ == "__main__":
    unittest.main()
