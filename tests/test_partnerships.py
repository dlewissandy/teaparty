"""Tests for Partnership model and CRUD endpoints."""

import unittest

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from teaparty_app.models import Organization, Partnership, User, utc_now
from teaparty_app.routers.partnerships import (
    accept_partnership,
    decline_partnership,
    list_partnerships,
    propose_partnership,
    revoke_partnership,
    withdraw_partnership,
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
    status: str = "proposed",
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


class ProposePartnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_user(session, "u-other", "other@example.com", "Other")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            session.commit()

    def test_propose_creates_partnership(self) -> None:
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
        self.assertEqual(result.status, "proposed")
        self.assertEqual(result.direction, "bidirectional")
        self.assertEqual(result.source_org_name, "Source Org")
        self.assertEqual(result.target_org_name, "Target Org")
        self.assertIsNone(result.accepted_at)
        self.assertIsNone(result.revoked_at)

    def test_propose_self_partnership_rejected(self) -> None:
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

    def test_propose_requires_source_org_ownership(self) -> None:
        with Session(self.engine) as session:
            # u-other doesn't own org-src
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

    def test_propose_target_org_not_found(self) -> None:
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

    def test_propose_duplicate_rejected(self) -> None:
        with Session(self.engine) as session:
            _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
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

    def test_propose_reverse_direction_duplicate_rejected(self) -> None:
        # Existing partnership in reverse direction should also block
        with Session(self.engine) as session:
            _make_partnership(session, "org-tgt", "org-src", "u-tgt", status="accepted")
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

    def test_propose_after_declined_allowed(self) -> None:
        # Declined partnerships don't block new proposals
        with Session(self.engine) as session:
            _make_partnership(session, "org-src", "org-tgt", "u-src", status="declined")
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
        self.assertEqual(result.status, "proposed")

    def test_propose_invalid_direction_rejected(self) -> None:
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


class AcceptPartnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            session.commit()

    def test_accept_proposed_partnership(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-tgt")
            result = accept_partnership(
                partnership_id=pid,
                session=session,
                user=user,
            )

        self.assertEqual(result.status, "accepted")
        self.assertIsNotNone(result.accepted_at)

    def test_accept_requires_target_org_owner(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            # Source owner cannot accept
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                accept_partnership(
                    partnership_id=pid,
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_accept_non_proposed_status_rejected(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-tgt")
            with self.assertRaises(HTTPException) as ctx:
                accept_partnership(
                    partnership_id=pid,
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_accept_not_found(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-tgt")
            with self.assertRaises(HTTPException) as ctx:
                accept_partnership(
                    partnership_id="nonexistent-id",
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 404)


class DeclinePartnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            session.commit()

    def test_decline_proposed_partnership(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-tgt")
            result = decline_partnership(
                partnership_id=pid,
                session=session,
                user=user,
            )

        self.assertEqual(result.status, "declined")

    def test_decline_requires_target_org_owner(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                decline_partnership(
                    partnership_id=pid,
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_decline_non_proposed_rejected(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-tgt")
            with self.assertRaises(HTTPException) as ctx:
                decline_partnership(
                    partnership_id=pid,
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

    def test_revoke_by_target_owner(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-tgt")
            result = revoke_partnership(
                partnership_id=pid,
                session=session,
                user=user,
            )

        self.assertEqual(result.status, "revoked")

    def test_revoke_non_accepted_rejected(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
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


class WithdrawPartnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-src", "src@example.com", "Source Owner")
            _make_user(session, "u-tgt", "tgt@example.com", "Target Owner")
            _make_org(session, "org-src", "u-src", "Source Org")
            _make_org(session, "org-tgt", "u-tgt", "Target Org")
            session.commit()

    def test_withdraw_proposed_partnership(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            result = withdraw_partnership(
                partnership_id=pid,
                session=session,
                user=user,
            )

        self.assertEqual(result.status, "withdrawn")

    def test_withdraw_requires_source_org_owner(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-tgt")
            with self.assertRaises(HTTPException) as ctx:
                withdraw_partnership(
                    partnership_id=pid,
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_withdraw_accepted_rejected(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="accepted")
            pid = p.id
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            with self.assertRaises(HTTPException) as ctx:
                withdraw_partnership(
                    partnership_id=pid,
                    session=session,
                    user=user,
                )
        self.assertEqual(ctx.exception.status_code, 400)


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

    def test_list_returns_source_and_target_partnerships(self) -> None:
        with Session(self.engine) as session:
            # org-src is source of p1, target of p2
            _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
            _make_partnership(session, "org-other", "org-src", "u-other", status="accepted")
            # unrelated partnership
            _make_partnership(session, "org-tgt", "org-other", "u-tgt", status="proposed")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u-src")
            results = list_partnerships(
                org_id="org-src",
                status_filter=None,
                session=session,
                user=user,
            )

        self.assertEqual(len(results), 2)

    def test_list_filter_by_status(self) -> None:
        with Session(self.engine) as session:
            _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
            _make_partnership(session, "org-src", "org-other", "u-src", status="accepted")
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
            p = _make_partnership(session, "org-src", "org-tgt", "u-src")
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

    def test_full_lifecycle(self) -> None:
        with Session(self.engine) as session:
            p = _make_partnership(session, "org-src", "org-tgt", "u-src", status="proposed")
            p.status = "accepted"
            p.accepted_at = utc_now()
            session.add(p)
            session.commit()
            session.refresh(p)

            self.assertEqual(p.status, "accepted")
            self.assertIsNotNone(p.accepted_at)

            p.status = "revoked"
            p.revoked_at = utc_now()
            session.add(p)
            session.commit()
            session.refresh(p)

            self.assertEqual(p.status, "revoked")
            self.assertIsNotNone(p.revoked_at)


if __name__ == "__main__":
    unittest.main()
