import unittest

from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine

from teaparty_app.models import Membership, User, Workgroup
from teaparty_app.services.permissions import require_workgroup_membership, require_workgroup_owner


class PermissionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def _seed_membership(self, role: str = "owner") -> None:
        with Session(self.engine) as session:
            user = User(id="user-1", email="owner@example.com", name="Owner")
            workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
            membership = Membership(workgroup_id=workgroup.id, user_id=user.id, role=role)
            session.add(user)
            session.add(workgroup)
            session.add(membership)
            session.commit()

    def test_require_workgroup_membership_returns_membership(self) -> None:
        self._seed_membership(role="member")
        with Session(self.engine) as session:
            membership = require_workgroup_membership(session, "wg-1", "user-1")
        self.assertEqual(membership.role, "member")

    def test_require_workgroup_membership_raises_for_non_member(self) -> None:
        self._seed_membership(role="owner")
        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                require_workgroup_membership(session, "wg-1", "user-2")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Not a workgroup member")

    def test_require_workgroup_owner_raises_for_member_role(self) -> None:
        self._seed_membership(role="member")
        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                require_workgroup_owner(session, "wg-1", "user-1")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Owner permissions required")

    def test_require_workgroup_owner_returns_owner_membership(self) -> None:
        self._seed_membership(role="owner")
        with Session(self.engine) as session:
            membership = require_workgroup_owner(session, "wg-1", "user-1")
        self.assertEqual(membership.role, "owner")

