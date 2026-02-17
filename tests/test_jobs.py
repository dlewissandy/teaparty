"""Tests for job endpoints: create_job, update_job, delete_job."""

import unittest
from unittest.mock import MagicMock

from fastapi import BackgroundTasks, HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from teaparty_app.models import (
    Agent,
    Conversation,
    ConversationParticipant,
    Job,
    Membership,
    Message,
    User,
    Workgroup,
)
from teaparty_app.routers.jobs import create_job, delete_job, update_job
from teaparty_app.schemas import JobCreateRequest, JobUpdateRequest


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _seed(session: Session) -> tuple[User, Workgroup, Agent]:
    user = User(id="user-1", email="owner@example.com", name="Owner")
    workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
    membership = Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner")
    agent = Agent(
        id="agent-1",
        workgroup_id=workgroup.id,
        created_by_user_id=user.id,
        name="Helper",
        description="A helpful agent",
    )
    session.add(user)
    session.add(workgroup)
    session.add(membership)
    session.add(agent)
    session.commit()
    return user, workgroup, agent


def _seed_non_member(session: Session) -> User:
    user2 = User(id="user-2", email="outsider@example.com", name="Outsider")
    session.add(user2)
    session.commit()
    return user2


def _insert_job(session: Session, job_id: str, title: str) -> Job:
    conv = Conversation(
        id=f"conv-{job_id}",
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        kind="job",
        topic=title,
        name=title,
    )
    session.add(conv)
    session.flush()
    job = Job(
        id=job_id,
        title=title,
        scope="",
        workgroup_id="wg-1",
        conversation_id=conv.id,
    )
    session.add(job)
    return job


class CreateJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_creates_job_with_conversation_and_message(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        bg = BackgroundTasks()
        with Session(self.engine) as session:
            result = create_job(
                workgroup_id="wg-1",
                payload=JobCreateRequest(title="Build API", description="REST endpoints needed"),
                background_tasks=bg,
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.title, "Build API")
        self.assertEqual(result.scope, "REST endpoints needed")
        self.assertEqual(result.status, "pending")
        self.assertEqual(result.workgroup_id, "wg-1")
        self.assertIsNotNone(result.conversation_id)

        with Session(self.engine) as session:
            conv = session.get(Conversation, result.conversation_id)
            self.assertIsNotNone(conv)
            self.assertEqual(conv.kind, "job")
            self.assertEqual(conv.name, "Build API")

            messages = session.exec(
                select(Message).where(Message.conversation_id == conv.id)
            ).all()
            self.assertEqual(len(messages), 1)
            msg = messages[0]
            self.assertEqual(msg.sender_type, "user")
            self.assertEqual(msg.sender_user_id, "user-1")
            self.assertEqual(msg.content, "Build API\n\nREST endpoints needed")
            self.assertTrue(msg.requires_response)

    def test_creates_job_with_title_only_when_no_description(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        bg = BackgroundTasks()
        with Session(self.engine) as session:
            result = create_job(
                workgroup_id="wg-1",
                payload=JobCreateRequest(title="Quick job"),
                background_tasks=bg,
                session=session,
                user=session.get(User, "user-1"),
            )

        with Session(self.engine) as session:
            messages = session.exec(
                select(Message).where(Message.conversation_id == result.conversation_id)
            ).all()
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].content, "Quick job")

    def test_schedules_auto_response_background_task(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        bg = MagicMock(spec=BackgroundTasks)
        with Session(self.engine) as session:
            result = create_job(
                workgroup_id="wg-1",
                payload=JobCreateRequest(title="Deploy service", description="Ship it"),
                background_tasks=bg,
                session=session,
                user=session.get(User, "user-1"),
            )

        bg.add_task.assert_called_once()
        args = bg.add_task.call_args
        from teaparty_app.routers.conversations import _process_auto_responses_in_background
        self.assertEqual(args[0][0], _process_auto_responses_in_background)
        self.assertEqual(args[0][1], result.conversation_id)

    def test_non_member_blocked(self) -> None:
        with Session(self.engine) as session:
            _seed(session)
            _seed_non_member(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                create_job(
                    workgroup_id="wg-1",
                    payload=JobCreateRequest(title="Sneaky job"),
                    background_tasks=BackgroundTasks(),
                    session=session,
                    user=session.get(User, "user-2"),
                )
            self.assertEqual(ctx.exception.status_code, 403)

    def test_workgroup_not_found_raises_http_error(self) -> None:
        # require_workgroup_membership runs before the workgroup lookup, so a
        # non-existent workgroup_id fails with 403 (user is not a member of a
        # workgroup that does not exist).
        with Session(self.engine) as session:
            _seed(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                create_job(
                    workgroup_id="wg-nonexistent",
                    payload=JobCreateRequest(title="Lost job"),
                    background_tasks=BackgroundTasks(),
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertIn(ctx.exception.status_code, (403, 404))


class UpdateJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _seed(session)
            _insert_job(session, "job-1", "Initial title")
            session.commit()

    def test_update_status_to_completed_sets_completed_at(self) -> None:
        with Session(self.engine) as session:
            result = update_job(
                job_id="job-1",
                payload=JobUpdateRequest(status="completed"),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.status, "completed")
        self.assertIsNotNone(result.completed_at)

    def test_update_status_to_cancelled_sets_completed_at(self) -> None:
        with Session(self.engine) as session:
            result = update_job(
                job_id="job-1",
                payload=JobUpdateRequest(status="cancelled"),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.status, "cancelled")
        self.assertIsNotNone(result.completed_at)

    def test_update_status_to_in_progress_no_completed_at(self) -> None:
        with Session(self.engine) as session:
            result = update_job(
                job_id="job-1",
                payload=JobUpdateRequest(status="in_progress"),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.status, "in_progress")
        self.assertIsNone(result.completed_at)

    def test_update_title(self) -> None:
        with Session(self.engine) as session:
            result = update_job(
                job_id="job-1",
                payload=JobUpdateRequest(title="Renamed title"),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.title, "Renamed title")

    def test_update_nonexistent_job_404(self) -> None:
        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                update_job(
                    job_id="nonexistent",
                    payload=JobUpdateRequest(status="completed"),
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 404)

    def test_update_non_member_blocked(self) -> None:
        with Session(self.engine) as session:
            _seed_non_member(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                update_job(
                    job_id="job-1",
                    payload=JobUpdateRequest(status="completed"),
                    session=session,
                    user=session.get(User, "user-2"),
                )
            self.assertEqual(ctx.exception.status_code, 403)


class DeleteJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _seed(session)
            _insert_job(session, "job-1", "Delete me")
            session.add(Message(
                conversation_id="conv-job-1",
                sender_type="user",
                sender_user_id="user-1",
                content="Please do the job",
            ))
            session.add(ConversationParticipant(conversation_id="conv-job-1", user_id="user-1"))
            session.commit()

    def test_deletes_job_conversation_messages_and_participants(self) -> None:
        with Session(self.engine) as session:
            delete_job(
                job_id="job-1",
                session=session,
                user=session.get(User, "user-1"),
            )

        with Session(self.engine) as session:
            self.assertIsNone(session.get(Job, "job-1"))
            self.assertIsNone(session.get(Conversation, "conv-job-1"))
            msgs = session.exec(
                select(Message).where(Message.conversation_id == "conv-job-1")
            ).all()
            self.assertEqual(len(msgs), 0)
            cps = session.exec(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == "conv-job-1"
                )
            ).all()
            self.assertEqual(len(cps), 0)

    def test_nonexistent_job_404(self) -> None:
        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                delete_job(
                    job_id="nonexistent",
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 404)

    def test_non_member_blocked(self) -> None:
        with Session(self.engine) as session:
            _seed_non_member(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                delete_job(
                    job_id="job-1",
                    session=session,
                    user=session.get(User, "user-2"),
                )
            self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
