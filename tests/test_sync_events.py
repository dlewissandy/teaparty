import unittest
from unittest.mock import patch, call
from sqlmodel import Session, SQLModel, create_engine

from teaparty_app.models import (
    Engagement,
    Membership,
    OrgMembership,
    Organization,
    User,
    Workgroup,
)
from teaparty_app.services.sync_events import (
    _engagement_user_ids,
    _org_user_ids,
    _workgroup_user_ids,
    publish_sync_event,
)


def _make_user(uid: str, email: str | None = None) -> User:
    return User(id=uid, email=email or f"{uid}@example.com", name=uid)


def _make_workgroup(wgid: str, owner_id: str) -> Workgroup:
    return Workgroup(id=wgid, name=wgid, owner_id=owner_id, files=[])


def _make_org(org_id: str, owner_id: str) -> Organization:
    return Organization(id=org_id, name=org_id, owner_id=owner_id)


def _make_membership(wg_id: str, user_id: str, role: str = "member") -> Membership:
    return Membership(workgroup_id=wg_id, user_id=user_id, role=role)


def _make_org_membership(org_id: str, user_id: str, role: str = "member") -> OrgMembership:
    return OrgMembership(organization_id=org_id, user_id=user_id, role=role)


class SyncEventsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    # ── test 1 ──────────────────────────────────────────────────────────────

    def test_workgroup_scope_finds_all_members(self):
        """_workgroup_user_ids returns all user_ids with membership in a workgroup."""
        with Session(self.engine) as session:
            owner = _make_user("u-owner")
            u1 = _make_user("u-1")
            u2 = _make_user("u-2")
            wg = _make_workgroup("wg-a", "u-owner")
            session.add_all([owner, u1, u2, wg])
            session.add(_make_membership("wg-a", "u-owner", role="owner"))
            session.add(_make_membership("wg-a", "u-1"))
            session.add(_make_membership("wg-a", "u-2"))
            session.commit()

            result = _workgroup_user_ids(session, "wg-a")

        self.assertCountEqual(result, ["u-owner", "u-1", "u-2"])

    # ── test 2 ──────────────────────────────────────────────────────────────

    def test_org_scope_finds_all_members(self):
        """_org_user_ids returns all user_ids with membership in an organization."""
        with Session(self.engine) as session:
            owner = _make_user("u-org-owner")
            u1 = _make_user("u-org-1")
            u2 = _make_user("u-org-2")
            org = _make_org("org-x", "u-org-owner")
            session.add_all([owner, u1, u2, org])
            session.add(_make_org_membership("org-x", "u-org-owner", role="owner"))
            session.add(_make_org_membership("org-x", "u-org-1"))
            session.add(_make_org_membership("org-x", "u-org-2"))
            session.commit()

            result = _org_user_ids(session, "org-x")

        self.assertCountEqual(result, ["u-org-owner", "u-org-1", "u-org-2"])

    # ── test 3 ──────────────────────────────────────────────────────────────

    def test_engagement_scope_unions_both_workgroups(self):
        """_engagement_user_ids returns the union of both workgroups' members with no duplicates."""
        with Session(self.engine) as session:
            # u-shared belongs to both workgroups
            u_src = _make_user("u-src")
            u_tgt = _make_user("u-tgt")
            u_shared = _make_user("u-shared")

            wg_src = _make_workgroup("wg-src", "u-src")
            wg_tgt = _make_workgroup("wg-tgt", "u-tgt")
            session.add_all([u_src, u_tgt, u_shared, wg_src, wg_tgt])

            session.add(_make_membership("wg-src", "u-src", role="owner"))
            session.add(_make_membership("wg-src", "u-shared"))
            session.add(_make_membership("wg-tgt", "u-tgt", role="owner"))
            session.add(_make_membership("wg-tgt", "u-shared"))

            eng = Engagement(
                id="eng-1",
                source_workgroup_id="wg-src",
                target_workgroup_id="wg-tgt",
                proposed_by_user_id="u-src",
                status="in_progress",
                title="Union Test",
            )
            session.add(eng)
            session.commit()

            result = _engagement_user_ids(session, "eng-1")

        # u-shared appears in both workgroups but must not be duplicated
        self.assertCountEqual(result, ["u-src", "u-tgt", "u-shared"])
        self.assertEqual(len(result), len(set(result)), "Duplicates found in engagement user ids")

    # ── test 4 ──────────────────────────────────────────────────────────────

    def test_publish_calls_event_bus(self):
        """publish_sync_event resolves workgroup members and calls publish_user for each."""
        with Session(self.engine) as session:
            u1 = _make_user("u-pub-1")
            u2 = _make_user("u-pub-2")
            wg = _make_workgroup("wg-pub", "u-pub-1")
            session.add_all([u1, u2, wg])
            session.add(_make_membership("wg-pub", "u-pub-1", role="owner"))
            session.add(_make_membership("wg-pub", "u-pub-2"))
            session.commit()

            payload = {"workgroup_id": "wg-pub"}
            with patch("teaparty_app.services.event_bus.publish_user") as mock_publish:
                publish_sync_event(
                    session,
                    "workgroup",
                    "wg-pub",
                    "sync:tree_changed",
                    payload,
                )

        expected_event = {"type": "sync:tree_changed", "workgroup_id": "wg-pub"}
        mock_publish.assert_called()
        self.assertEqual(mock_publish.call_count, 2)
        # Both user_ids must have been published the correct event
        called_user_ids = {c.args[0] for c in mock_publish.call_args_list}
        self.assertEqual(called_user_ids, {"u-pub-1", "u-pub-2"})
        for c in mock_publish.call_args_list:
            self.assertEqual(c.args[1], expected_event)

    # ── test 5 ──────────────────────────────────────────────────────────────

    def test_empty_membership_no_error(self):
        """publish_sync_event on a workgroup with no members does not crash and never calls publish_user."""
        with Session(self.engine) as session:
            owner = _make_user("u-empty-owner")
            wg = _make_workgroup("wg-empty", "u-empty-owner")
            session.add_all([owner, wg])
            session.commit()

            with patch("teaparty_app.services.event_bus.publish_user") as mock_publish:
                publish_sync_event(
                    session,
                    "workgroup",
                    "wg-empty",
                    "sync:tree_changed",
                    {"workgroup_id": "wg-empty"},
                )

        mock_publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
