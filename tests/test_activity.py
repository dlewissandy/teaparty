import unittest

from sqlmodel import SQLModel, Session, create_engine, select

from teaparty_app.models import Conversation, ConversationParticipant, Membership, Message, User, Workgroup
from teaparty_app.services.activity import (
    _compute_file_diff,
    add_activity_participant,
    ensure_activity_conversation,
    post_activity,
    post_bulk_file_change_activity,
)


class ComputeFileDiffTests(unittest.TestCase):
    def test_empty_to_files(self) -> None:
        lines = _compute_file_diff([], [{"id": "1", "path": "a.txt", "content": ""}])
        self.assertEqual(lines, ["Added 'a.txt'"])

    def test_files_to_empty(self) -> None:
        lines = _compute_file_diff([{"id": "1", "path": "a.txt", "content": ""}], [])
        self.assertEqual(lines, ["Removed 'a.txt'"])

    def test_content_change(self) -> None:
        old = [{"id": "1", "path": "a.txt", "content": "old"}]
        new = [{"id": "1", "path": "a.txt", "content": "new"}]
        lines = _compute_file_diff(old, new)
        self.assertEqual(lines, ["Modified 'a.txt'"])

    def test_no_change(self) -> None:
        files = [{"id": "1", "path": "a.txt", "content": "same"}]
        lines = _compute_file_diff(files, list(files))
        self.assertEqual(lines, [])

    def test_mixed_add_remove_modify(self) -> None:
        old = [
            {"id": "1", "path": "a.txt", "content": "aaa"},
            {"id": "2", "path": "b.txt", "content": "bbb"},
        ]
        new = [
            {"id": "1", "path": "a.txt", "content": "aaa-modified"},
            {"id": "3", "path": "c.txt", "content": "ccc"},
        ]
        lines = _compute_file_diff(old, new)
        self.assertIn("Modified 'a.txt'", lines)
        self.assertIn("Added 'c.txt'", lines)
        self.assertIn("Removed 'b.txt'", lines)

    def test_rename_detection_by_id(self) -> None:
        old = [{"id": "1", "path": "old.txt", "content": "data"}]
        new = [{"id": "1", "path": "new.txt", "content": "data"}]
        lines = _compute_file_diff(old, new)
        self.assertEqual(lines, ["Renamed 'old.txt' to 'new.txt'"])

    def test_rename_with_content_change(self) -> None:
        old = [{"id": "1", "path": "old.txt", "content": "data"}]
        new = [{"id": "1", "path": "new.txt", "content": "updated"}]
        lines = _compute_file_diff(old, new)
        self.assertIn("Renamed 'old.txt' to 'new.txt'", lines)
        self.assertIn("Modified 'new.txt'", lines)


class EnsureActivityConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def _seed(self) -> None:
        with Session(self.engine) as session:
            user = User(id="user-1", email="owner@example.com", name="Owner")
            workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
            membership = Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner")
            session.add(user)
            session.add(workgroup)
            session.add(membership)
            session.commit()

    def test_creates_activity_conversation(self) -> None:
        self._seed()
        with Session(self.engine) as session:
            workgroup = session.get(Workgroup, "wg-1")
            conversation, changed = ensure_activity_conversation(session, workgroup)
            session.commit()

            self.assertTrue(changed)
            self.assertEqual(conversation.kind, "activity")
            self.assertEqual(conversation.topic, "Activity")
            self.assertEqual(conversation.name, "Activity")
            conv_id = conversation.id

        with Session(self.engine) as session:
            participants = session.exec(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conv_id,
                )
            ).all()
            user_ids = {p.user_id for p in participants}
            self.assertIn("user-1", user_ids)

    def test_idempotent(self) -> None:
        self._seed()
        with Session(self.engine) as session:
            workgroup = session.get(Workgroup, "wg-1")
            conv1, changed1 = ensure_activity_conversation(session, workgroup)
            conv1_id = conv1.id
            session.commit()

        with Session(self.engine) as session:
            workgroup = session.get(Workgroup, "wg-1")
            conv2, changed2 = ensure_activity_conversation(session, workgroup)
            self.assertEqual(conv1_id, conv2.id)
            self.assertFalse(changed2)
            session.commit()


class AddActivityParticipantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def _seed_with_activity(self) -> str:
        with Session(self.engine) as session:
            user = User(id="user-1", email="owner@example.com", name="Owner")
            user2 = User(id="user-2", email="member@example.com", name="Member")
            workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
            session.add(user)
            session.add(user2)
            session.add(workgroup)
            session.add(Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner"))
            session.add(Membership(workgroup_id=workgroup.id, user_id=user2.id, role="member"))
            conversation, _ = ensure_activity_conversation(session, workgroup)
            conv_id = conversation.id
            session.commit()
            return conv_id

    def test_adds_participant(self) -> None:
        self._seed_with_activity()
        with Session(self.engine) as session:
            result = add_activity_participant(session, "wg-1", "user-2")
            session.commit()

        # user-2 was already added by ensure_activity_conversation since they're a member
        self.assertFalse(result)

    def test_adds_new_participant(self) -> None:
        with Session(self.engine) as session:
            user = User(id="user-1", email="owner@example.com", name="Owner")
            workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
            session.add(user)
            session.add(workgroup)
            session.add(Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner"))
            ensure_activity_conversation(session, workgroup)
            session.commit()

        with Session(self.engine) as session:
            user3 = User(id="user-3", email="new@example.com", name="New")
            session.add(user3)
            session.commit()

        with Session(self.engine) as session:
            result = add_activity_participant(session, "wg-1", "user-3")
            session.commit()
        self.assertTrue(result)

    def test_idempotent(self) -> None:
        with Session(self.engine) as session:
            user = User(id="user-1", email="owner@example.com", name="Owner")
            workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
            session.add(user)
            session.add(workgroup)
            session.add(Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner"))
            ensure_activity_conversation(session, workgroup)
            session.commit()

        with Session(self.engine) as session:
            user3 = User(id="user-3", email="new@example.com", name="New")
            session.add(user3)
            session.commit()

        with Session(self.engine) as session:
            add_activity_participant(session, "wg-1", "user-3")
            session.commit()

        with Session(self.engine) as session:
            result = add_activity_participant(session, "wg-1", "user-3")
            session.commit()
        self.assertFalse(result)


class PostActivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def _seed_with_activity(self) -> None:
        with Session(self.engine) as session:
            user = User(id="user-1", email="owner@example.com", name="Owner")
            workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
            session.add(user)
            session.add(workgroup)
            session.add(Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner"))
            ensure_activity_conversation(session, workgroup)
            session.commit()

    def test_creates_system_message(self) -> None:
        self._seed_with_activity()
        with Session(self.engine) as session:
            message = post_activity(session, "wg-1", "file_added", "notes.md", actor_user_id="user-1")
            session.commit()

            self.assertIsNotNone(message)
            session.refresh(message)
            self.assertEqual(message.sender_type, "system")
            self.assertEqual(message.content, "[file_added] notes.md")
            self.assertEqual(message.sender_user_id, "user-1")
            self.assertFalse(message.requires_response)

    def test_returns_none_when_no_activity_conversation(self) -> None:
        with Session(self.engine) as session:
            user = User(id="user-1", email="owner@example.com", name="Owner")
            workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
            session.add(user)
            session.add(workgroup)
            session.commit()

        with Session(self.engine) as session:
            message = post_activity(session, "wg-1", "file_added", "notes.md", actor_user_id="user-1")
        self.assertIsNone(message)


class PostBulkFileChangeActivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def _seed_with_activity(self) -> None:
        with Session(self.engine) as session:
            user = User(id="user-1", email="owner@example.com", name="Owner")
            workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
            session.add(user)
            session.add(workgroup)
            session.add(Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner"))
            ensure_activity_conversation(session, workgroup)
            session.commit()

    def test_posts_add_message(self) -> None:
        self._seed_with_activity()
        with Session(self.engine) as session:
            message = post_bulk_file_change_activity(
                session, "wg-1",
                [],
                [{"id": "1", "path": "a.txt", "content": ""}],
                actor_user_id="user-1",
            )
            session.commit()

            self.assertIsNotNone(message)
            session.refresh(message)
            self.assertIn("Added 'a.txt'", message.content)
            self.assertIn("[files_changed]", message.content)

    def test_posts_remove_message(self) -> None:
        self._seed_with_activity()
        with Session(self.engine) as session:
            message = post_bulk_file_change_activity(
                session, "wg-1",
                [{"id": "1", "path": "a.txt", "content": ""}],
                [],
                actor_user_id="user-1",
            )
            session.commit()

            self.assertIsNotNone(message)
            session.refresh(message)
            self.assertIn("Removed 'a.txt'", message.content)

    def test_posts_modify_message(self) -> None:
        self._seed_with_activity()
        with Session(self.engine) as session:
            message = post_bulk_file_change_activity(
                session, "wg-1",
                [{"id": "1", "path": "a.txt", "content": "old"}],
                [{"id": "1", "path": "a.txt", "content": "new"}],
                actor_user_id="user-1",
            )
            session.commit()

            self.assertIsNotNone(message)
            session.refresh(message)
            self.assertIn("Modified 'a.txt'", message.content)

    def test_no_change_returns_none(self) -> None:
        self._seed_with_activity()
        with Session(self.engine) as session:
            message = post_bulk_file_change_activity(
                session, "wg-1",
                [{"id": "1", "path": "a.txt", "content": "same"}],
                [{"id": "1", "path": "a.txt", "content": "same"}],
                actor_user_id="user-1",
            )
        self.assertIsNone(message)
