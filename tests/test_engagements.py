import unittest

from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine

from teaparty_app.models import (
    Conversation,
    ConversationParticipant,
    Engagement,
    Membership,
    Message,
    User,
    Workgroup,
)


class EngagementRouterHelpersTest(unittest.TestCase):
    """Unit tests for engagement router logic using direct model/service calls."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        self._seed()

    def _seed(self) -> None:
        with Session(self.engine) as session:
            self.user_source = User(id="u-src", email="src@example.com", name="Source User")
            self.user_target = User(id="u-tgt", email="tgt@example.com", name="Target User")
            self.user_outsider = User(id="u-out", email="out@example.com", name="Outsider")

            self.wg_source = Workgroup(id="wg-src", name="Source WG", owner_id=self.user_source.id, files=[])
            self.wg_target = Workgroup(id="wg-tgt", name="Target WG", owner_id=self.user_target.id, files=[])

            session.add_all([self.user_source, self.user_target, self.user_outsider,
                             self.wg_source, self.wg_target])

            session.add(Membership(workgroup_id="wg-src", user_id="u-src", role="owner"))
            session.add(Membership(workgroup_id="wg-tgt", user_id="u-tgt", role="owner"))
            session.commit()

    def _create_engagement(self, session: Session, status: str = "proposed") -> Engagement:
        eng = Engagement(
            source_workgroup_id="wg-src",
            target_workgroup_id="wg-tgt",
            proposed_by_user_id="u-src",
            status=status,
            title="Test Engagement",
            scope="Test scope",
            requirements="Test reqs",
        )
        session.add(eng)

        src_conv = Conversation(
            workgroup_id="wg-src",
            created_by_user_id="u-src",
            kind="engagement",
            topic=f"engagement:{eng.id}",
            name="Test Engagement",
        )
        tgt_conv = Conversation(
            workgroup_id="wg-tgt",
            created_by_user_id="u-src",
            kind="engagement",
            topic=f"engagement:{eng.id}",
            name="Test Engagement",
        )
        session.add(src_conv)
        session.add(tgt_conv)
        session.flush()

        eng.source_conversation_id = src_conv.id
        eng.target_conversation_id = tgt_conv.id
        session.add(eng)
        session.flush()
        return eng

    def test_engagement_model_defaults(self) -> None:
        with Session(self.engine) as session:
            eng = self._create_engagement(session)
            session.commit()
            session.refresh(eng)

            self.assertEqual(eng.status, "proposed")
            self.assertIsNotNone(eng.source_conversation_id)
            self.assertIsNotNone(eng.target_conversation_id)
            self.assertIsNone(eng.accepted_at)
            self.assertIsNone(eng.declined_at)
            self.assertIsNone(eng.review_rating)

    def test_engagement_accept_updates_status(self) -> None:
        from teaparty_app.models import utc_now

        with Session(self.engine) as session:
            eng = self._create_engagement(session)
            session.commit()

            eng.status = "in_progress"
            eng.accepted_at = utc_now()
            eng.terms = "50/50 split"
            session.add(eng)
            session.commit()
            session.refresh(eng)

            self.assertEqual(eng.status, "in_progress")
            self.assertIsNotNone(eng.accepted_at)
            self.assertEqual(eng.terms, "50/50 split")

    def test_engagement_decline(self) -> None:
        from teaparty_app.models import utc_now

        with Session(self.engine) as session:
            eng = self._create_engagement(session)
            session.commit()

            eng.status = "declined"
            eng.declined_at = utc_now()
            session.add(eng)
            session.commit()
            session.refresh(eng)

            self.assertEqual(eng.status, "declined")
            self.assertIsNotNone(eng.declined_at)

    def test_engagement_complete_and_review(self) -> None:
        from teaparty_app.models import utc_now

        with Session(self.engine) as session:
            eng = self._create_engagement(session, status="in_progress")
            session.commit()

            eng.status = "completed"
            eng.completed_at = utc_now()
            session.add(eng)
            session.commit()

            eng.status = "reviewed"
            eng.reviewed_at = utc_now()
            eng.review_rating = "satisfied"
            eng.review_feedback = "Great work"
            session.add(eng)
            session.commit()
            session.refresh(eng)

            self.assertEqual(eng.status, "reviewed")
            self.assertEqual(eng.review_rating, "satisfied")
            self.assertEqual(eng.review_feedback, "Great work")

    def test_engagement_cancel(self) -> None:
        from teaparty_app.models import utc_now

        with Session(self.engine) as session:
            eng = self._create_engagement(session, status="in_progress")
            session.commit()

            eng.status = "cancelled"
            eng.cancelled_at = utc_now()
            session.add(eng)
            session.commit()
            session.refresh(eng)

            self.assertEqual(eng.status, "cancelled")
            self.assertIsNotNone(eng.cancelled_at)

    def test_engagement_files_created(self) -> None:
        from teaparty_app.services.engagement_files import create_engagement_files

        with Session(self.engine) as session:
            eng = self._create_engagement(session, status="in_progress")
            session.commit()

            src_wg = session.get(Workgroup, "wg-src")
            tgt_wg = session.get(Workgroup, "wg-tgt")
            create_engagement_files(session, eng, src_wg, tgt_wg)
            session.commit()
            session.refresh(src_wg)
            session.refresh(tgt_wg)

            src_paths = [f["path"] for f in src_wg.files if isinstance(f, dict)]
            tgt_paths = [f["path"] for f in tgt_wg.files if isinstance(f, dict)]

            self.assertTrue(any(f"engagements/{eng.id}/agreement.md" in p for p in src_paths))
            self.assertTrue(any(f"engagements/{eng.id}/deliverables.md" in p for p in src_paths))
            self.assertTrue(any(f"engagements/{eng.id}/agreement.md" in p for p in tgt_paths))
            self.assertTrue(any(f"engagements/{eng.id}/deliverables.md" in p for p in tgt_paths))

    def test_engagement_files_updated(self) -> None:
        from teaparty_app.services.engagement_files import (
            create_engagement_files,
            update_engagement_files,
        )

        with Session(self.engine) as session:
            eng = self._create_engagement(session, status="in_progress")
            session.commit()

            src_wg = session.get(Workgroup, "wg-src")
            tgt_wg = session.get(Workgroup, "wg-tgt")
            create_engagement_files(session, eng, src_wg, tgt_wg)
            session.commit()

            eng.status = "completed"
            session.add(eng)
            session.commit()

            session.refresh(eng)
            session.refresh(src_wg)
            session.refresh(tgt_wg)
            update_engagement_files(session, eng, src_wg, tgt_wg, "Engagement completed", "All done")
            session.commit()

            session.refresh(src_wg)
            agreement_file = next(
                (f for f in src_wg.files if isinstance(f, dict) and f["path"] == f"engagements/{eng.id}/agreement.md"),
                None,
            )
            self.assertIsNotNone(agreement_file)
            self.assertIn("completed", agreement_file["content"])

            deliverables_file = next(
                (f for f in src_wg.files if isinstance(f, dict) and f["path"] == f"engagements/{eng.id}/deliverables.md"),
                None,
            )
            self.assertIsNotNone(deliverables_file)
            self.assertIn("Engagement completed", deliverables_file["content"])
            self.assertIn("All done", deliverables_file["content"])

    def test_require_engagement_participant_blocks_outsider(self) -> None:
        from teaparty_app.routers.engagements import _require_engagement_participant

        with Session(self.engine) as session:
            eng = self._create_engagement(session)
            session.commit()

            with self.assertRaises(HTTPException) as ctx:
                _require_engagement_participant(session, eng, "u-out")
            self.assertEqual(ctx.exception.status_code, 403)

    def test_require_engagement_participant_allows_source(self) -> None:
        from teaparty_app.routers.engagements import _require_engagement_participant

        with Session(self.engine) as session:
            eng = self._create_engagement(session)
            session.commit()

            membership = _require_engagement_participant(session, eng, "u-src")
            self.assertEqual(membership.workgroup_id, "wg-src")

    def test_require_engagement_participant_allows_target(self) -> None:
        from teaparty_app.routers.engagements import _require_engagement_participant

        with Session(self.engine) as session:
            eng = self._create_engagement(session)
            session.commit()

            membership = _require_engagement_participant(session, eng, "u-tgt")
            self.assertEqual(membership.workgroup_id, "wg-tgt")

    def test_engagement_schema_validation(self) -> None:
        from teaparty_app.schemas import EngagementCreateRequest, EngagementRead

        req = EngagementCreateRequest(
            target_workgroup_id="wg-tgt",
            title="Build widget",
            scope="Frontend",
            requirements="Must be responsive",
        )
        self.assertEqual(req.title, "Build widget")
        self.assertIsNone(req.source_workgroup_id)

        with Session(self.engine) as session:
            eng = self._create_engagement(session)
            session.commit()
            session.refresh(eng)

            read = EngagementRead.model_validate(eng)
            self.assertEqual(read.status, "proposed")
            self.assertEqual(read.title, "Test Engagement")


class EngagementLearningEligibilityTest(unittest.TestCase):
    def test_engagement_conversation_not_eligible(self) -> None:
        from teaparty_app.services.agent_learning import is_learning_eligible
        from teaparty_app.models import Conversation

        conv = Conversation(
            workgroup_id="wg-1",
            created_by_user_id="u-1",
            kind="engagement",
            topic="engagement:eng-123",
        )
        self.assertFalse(is_learning_eligible(conv))

    def test_job_conversation_eligible(self) -> None:
        from teaparty_app.services.agent_learning import is_learning_eligible
        from teaparty_app.models import Conversation

        conv = Conversation(
            workgroup_id="wg-1",
            created_by_user_id="u-1",
            kind="job",
            topic="general",
        )
        self.assertTrue(is_learning_eligible(conv))


if __name__ == "__main__":
    unittest.main()
