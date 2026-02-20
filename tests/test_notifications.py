"""Tests for the Notification model, service, and REST endpoints."""

import unittest

from sqlmodel import Session, SQLModel, create_engine, select

from teaparty_app.models import Notification, User
from teaparty_app.routers.notifications import (
    get_notification_counts,
    list_notifications,
    mark_notification_read,
)
from teaparty_app.services.notification_service import create_notification


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_user(session: Session, user_id: str = "user-1", email: str = "test@example.com") -> User:
    user = User(id=user_id, email=email, name="Test User")
    session.add(user)
    session.flush()
    return user


def _make_notification(
    session: Session,
    user_id: str = "user-1",
    notification_id: str | None = None,
    type: str = "attention_needed",
    title: str = "Test Notification",
    body: str = "",
    is_read: bool = False,
) -> Notification:
    n = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        is_read=is_read,
    )
    if notification_id:
        n.id = notification_id
    session.add(n)
    session.flush()
    return n


class CreateNotificationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_creates_notification_with_required_fields(self) -> None:
        with Session(self.engine) as session:
            _make_user(session)
            n = create_notification(session, user_id="user-1", type="job_completed", title="Job done")
            session.commit()
            n_id = n.id

        with Session(self.engine) as session:
            n = session.get(Notification, n_id)
            self.assertIsNotNone(n)
            self.assertEqual(n.user_id, "user-1")
            self.assertEqual(n.type, "job_completed")
            self.assertEqual(n.title, "Job done")
            self.assertEqual(n.body, "")
            self.assertFalse(n.is_read)

    def test_creates_notification_with_optional_fields(self) -> None:
        with Session(self.engine) as session:
            _make_user(session)
            n = create_notification(
                session,
                user_id="user-1",
                type="engagement_proposed",
                title="New engagement",
                body="Someone wants to work with you",
                source_engagement_id="eng-1",
            )
            session.commit()
            n_id = n.id

        with Session(self.engine) as session:
            n = session.get(Notification, n_id)
            self.assertEqual(n.body, "Someone wants to work with you")
            self.assertEqual(n.source_engagement_id, "eng-1")
            self.assertIsNone(n.source_conversation_id)
            self.assertIsNone(n.source_job_id)

    def test_created_at_is_set(self) -> None:
        with Session(self.engine) as session:
            _make_user(session)
            n = create_notification(session, user_id="user-1", type="attention_needed", title="Look here")
            session.commit()
            n_id = n.id

        with Session(self.engine) as session:
            n = session.get(Notification, n_id)
            self.assertIsNotNone(n.created_at)

    def test_multiple_notifications_for_same_user(self) -> None:
        with Session(self.engine) as session:
            _make_user(session)
            create_notification(session, user_id="user-1", type="job_completed", title="First")
            create_notification(session, user_id="user-1", type="job_completed", title="Second")
            session.commit()

        with Session(self.engine) as session:
            results = session.exec(
                select(Notification).where(Notification.user_id == "user-1")
            ).all()
            self.assertEqual(len(results), 2)


class ListNotificationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session)
            _make_notification(session, notification_id="n1", type="job_completed", title="Job 1")
            _make_notification(session, notification_id="n2", type="attention_needed", title="Attention", is_read=True)
            _make_notification(session, notification_id="n3", type="job_completed", title="Job 2", is_read=True)
            session.commit()

    def test_lists_all_for_current_user(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = list_notifications(type=None, is_read=None, limit=50, offset=0, session=session, user=user)

        self.assertEqual(len(result), 3)

    def test_filter_by_type(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = list_notifications(type="job_completed", is_read=None, limit=50, offset=0, session=session, user=user)

        self.assertEqual(len(result), 2)
        for n in result:
            self.assertEqual(n.type, "job_completed")

    def test_filter_by_is_read_false(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = list_notifications(type=None, is_read=False, limit=50, offset=0, session=session, user=user)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "n1")

    def test_filter_by_is_read_true(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = list_notifications(type=None, is_read=True, limit=50, offset=0, session=session, user=user)

        self.assertEqual(len(result), 2)

    def test_filter_by_type_and_is_read(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = list_notifications(type="job_completed", is_read=True, limit=50, offset=0, session=session, user=user)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "n3")

    def test_newest_first_ordering(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = list_notifications(type=None, is_read=None, limit=50, offset=0, session=session, user=user)

        timestamps = [n.created_at for n in result]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_pagination_limit(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = list_notifications(type=None, is_read=None, limit=2, offset=0, session=session, user=user)

        self.assertEqual(len(result), 2)

    def test_pagination_offset(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = list_notifications(type=None, is_read=None, limit=50, offset=2, session=session, user=user)

        self.assertEqual(len(result), 1)

    def test_excludes_other_users_notifications(self) -> None:
        with Session(self.engine) as session:
            _make_user(session, user_id="user-2", email="other@example.com")
            _make_notification(session, user_id="user-2", notification_id="n-other", title="Other user")
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = list_notifications(type=None, is_read=None, limit=50, offset=0, session=session, user=user)

        self.assertEqual(len(result), 3)
        ids = {n.id for n in result}
        self.assertNotIn("n-other", ids)


class NotificationCountsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session)
            session.commit()

    def test_counts_unread_notifications(self) -> None:
        with Session(self.engine) as session:
            _make_notification(session, notification_id="n1", is_read=False)
            _make_notification(session, notification_id="n2", is_read=False)
            _make_notification(session, notification_id="n3", is_read=True)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = get_notification_counts(session=session, user=user)

        self.assertEqual(result.unread, 2)

    def test_zero_when_all_read(self) -> None:
        with Session(self.engine) as session:
            _make_notification(session, notification_id="n1", is_read=True)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = get_notification_counts(session=session, user=user)

        self.assertEqual(result.unread, 0)

    def test_zero_when_no_notifications(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = get_notification_counts(session=session, user=user)

        self.assertEqual(result.unread, 0)

    def test_excludes_other_users_unread(self) -> None:
        with Session(self.engine) as session:
            _make_user(session, user_id="user-2", email="other@example.com")
            _make_notification(session, user_id="user-2", notification_id="n-other", is_read=False)
            _make_notification(session, notification_id="n1", is_read=False)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = get_notification_counts(session=session, user=user)

        self.assertEqual(result.unread, 1)


class MarkNotificationReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session)
            _make_notification(session, notification_id="n1", is_read=False)
            session.commit()

    def test_marks_notification_as_read(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = mark_notification_read(notification_id="n1", session=session, user=user)

        self.assertTrue(result.is_read)

    def test_returns_updated_notification(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = mark_notification_read(notification_id="n1", session=session, user=user)

        self.assertEqual(result.id, "n1")
        self.assertEqual(result.user_id, "user-1")

    def test_persists_is_read_flag(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            mark_notification_read(notification_id="n1", session=session, user=user)

        with Session(self.engine) as session:
            n = session.get(Notification, "n1")
            self.assertTrue(n.is_read)

    def test_404_for_nonexistent_notification(self) -> None:
        from fastapi import HTTPException

        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            with self.assertRaises(HTTPException) as ctx:
                mark_notification_read(notification_id="nonexistent", session=session, user=user)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_403_for_other_users_notification(self) -> None:
        from fastapi import HTTPException

        with Session(self.engine) as session:
            _make_user(session, user_id="user-2", email="other@example.com")
            session.commit()

        with Session(self.engine) as session:
            user2 = session.get(User, "user-2")
            with self.assertRaises(HTTPException) as ctx:
                mark_notification_read(notification_id="n1", session=session, user=user2)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_idempotent_when_already_read(self) -> None:
        with Session(self.engine) as session:
            _make_notification(session, notification_id="n2", is_read=True)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "user-1")
            result = mark_notification_read(notification_id="n2", session=session, user=user)

        self.assertTrue(result.is_read)


if __name__ == "__main__":
    unittest.main()
