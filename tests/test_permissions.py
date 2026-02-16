import unittest

from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine

from teaparty_app.models import Membership, User, Workgroup
from teaparty_app.services.permissions import (
    check_budget,
    require_workgroup_editor,
    require_workgroup_membership,
    require_workgroup_owner,
)


class PermissionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def _seed_membership(self, role: str = "owner", budget_limit: float | None = None, budget_used: float = 0.0) -> None:
        with Session(self.engine) as session:
            user = User(id="user-1", email="owner@example.com", name="Owner")
            workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
            membership = Membership(
                workgroup_id=workgroup.id,
                user_id=user.id,
                role=role,
                budget_limit_usd=budget_limit,
                budget_used_usd=budget_used,
            )
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

    # --- Editor role tests ---

    def test_require_workgroup_editor_passes_for_owner(self) -> None:
        self._seed_membership(role="owner")
        with Session(self.engine) as session:
            membership = require_workgroup_editor(session, "wg-1", "user-1")
        self.assertEqual(membership.role, "owner")

    def test_require_workgroup_editor_passes_for_editor(self) -> None:
        self._seed_membership(role="editor")
        with Session(self.engine) as session:
            membership = require_workgroup_editor(session, "wg-1", "user-1")
        self.assertEqual(membership.role, "editor")

    def test_require_workgroup_editor_rejects_member(self) -> None:
        self._seed_membership(role="member")
        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                require_workgroup_editor(session, "wg-1", "user-1")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Editor permissions required")

    # --- Budget check tests ---

    def test_check_budget_passes_when_unlimited(self) -> None:
        self._seed_membership(role="member", budget_limit=None)
        with Session(self.engine) as session:
            membership = require_workgroup_membership(session, "wg-1", "user-1")
            check_budget(membership)  # Should not raise

    def test_check_budget_passes_when_under_limit(self) -> None:
        self._seed_membership(role="member", budget_limit=1.0, budget_used=0.5)
        with Session(self.engine) as session:
            membership = require_workgroup_membership(session, "wg-1", "user-1")
            check_budget(membership)  # Should not raise

    def test_check_budget_raises_when_exceeded(self) -> None:
        self._seed_membership(role="member", budget_limit=1.0, budget_used=1.5)
        with Session(self.engine) as session:
            membership = require_workgroup_membership(session, "wg-1", "user-1")
            with self.assertRaises(HTTPException) as ctx:
                check_budget(membership)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Budget exceeded", ctx.exception.detail)

    def test_check_budget_raises_when_exactly_at_limit(self) -> None:
        self._seed_membership(role="member", budget_limit=1.0, budget_used=1.0)
        with Session(self.engine) as session:
            membership = require_workgroup_membership(session, "wg-1", "user-1")
            with self.assertRaises(HTTPException) as ctx:
                check_budget(membership)
        self.assertEqual(ctx.exception.status_code, 403)
