"""Tests for Partnership model and CRUD endpoints.

Partnerships are asymmetric: A adding B as a partner only appears in A's list.
There is no invite/proposal lifecycle — partnerships are created immediately.
"""

import unittest

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from teaparty_app.models import Organization, Partnership, User, utc_now
from teaparty_app.routers.partnerships import (
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


if __name__ == "__main__":
    unittest.main()
