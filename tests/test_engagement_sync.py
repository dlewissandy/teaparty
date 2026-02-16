import unittest

from sqlmodel import SQLModel, Session, create_engine

from teaparty_app.models import (
    Agent,
    Conversation,
    Engagement,
    EngagementSyncedMessage,
    Membership,
    Message,
    User,
    Workgroup,
)
from teaparty_app.services.engagement_sync import sync_engagement_messages


class EngagementSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        self._seed()

    def _seed(self) -> None:
        with Session(self.engine) as session:
            user_src = User(id="u-src", email="src@example.com", name="Source User")
            user_tgt = User(id="u-tgt", email="tgt@example.com", name="Target User")
            wg_src = Workgroup(id="wg-src", name="Source WG", owner_id="u-src", files=[])
            wg_tgt = Workgroup(id="wg-tgt", name="Target WG", owner_id="u-tgt", files=[])

            session.add_all([user_src, user_tgt, wg_src, wg_tgt])
            session.add(Membership(workgroup_id="wg-src", user_id="u-src", role="owner"))
            session.add(Membership(workgroup_id="wg-tgt", user_id="u-tgt", role="owner"))
            session.commit()

    def _create_engagement_with_conversations(self, session: Session, status: str = "in_progress") -> Engagement:
        eng = Engagement(
            source_workgroup_id="wg-src",
            target_workgroup_id="wg-tgt",
            proposed_by_user_id="u-src",
            status=status,
            title="Sync Test Engagement",
        )
        session.add(eng)
        session.flush()

        src_conv = Conversation(
            workgroup_id="wg-src",
            created_by_user_id="u-src",
            kind="engagement",
            topic=f"engagement:{eng.id}",
            name="Sync Test",
        )
        tgt_conv = Conversation(
            workgroup_id="wg-tgt",
            created_by_user_id="u-src",
            kind="engagement",
            topic=f"engagement:{eng.id}",
            name="Sync Test",
        )
        session.add(src_conv)
        session.add(tgt_conv)
        session.flush()

        eng.source_conversation_id = src_conv.id
        eng.target_conversation_id = tgt_conv.id
        session.add(eng)
        session.flush()
        return eng

    def test_source_message_syncs_to_target(self) -> None:
        with Session(self.engine) as session:
            eng = self._create_engagement_with_conversations(session)

            # User posts in source conversation
            msg = Message(
                conversation_id=eng.source_conversation_id,
                sender_type="user",
                sender_user_id="u-src",
                content="Hello from source",
                requires_response=False,
            )
            session.add(msg)
            session.commit()

            created = sync_engagement_messages(session, {"wg-src", "wg-tgt"})
            session.commit()

            self.assertEqual(len(created), 1)
            self.assertEqual(created[0].conversation_id, eng.target_conversation_id)
            self.assertIn("[synced from Source User]", created[0].content)
            self.assertIn("Hello from source", created[0].content)

    def test_target_message_syncs_to_source(self) -> None:
        with Session(self.engine) as session:
            eng = self._create_engagement_with_conversations(session)

            msg = Message(
                conversation_id=eng.target_conversation_id,
                sender_type="user",
                sender_user_id="u-tgt",
                content="Hello from target",
                requires_response=False,
            )
            session.add(msg)
            session.commit()

            created = sync_engagement_messages(session, {"wg-src", "wg-tgt"})
            session.commit()

            self.assertEqual(len(created), 1)
            self.assertEqual(created[0].conversation_id, eng.source_conversation_id)
            self.assertIn("[synced from Target User]", created[0].content)

    def test_no_infinite_loop(self) -> None:
        """Synced messages should not be re-synced back."""
        with Session(self.engine) as session:
            eng = self._create_engagement_with_conversations(session)

            msg = Message(
                conversation_id=eng.source_conversation_id,
                sender_type="user",
                sender_user_id="u-src",
                content="Original message",
                requires_response=False,
            )
            session.add(msg)
            session.commit()

            # First sync
            created = sync_engagement_messages(session, {"wg-src", "wg-tgt"})
            session.commit()
            self.assertEqual(len(created), 1)

            # Second sync — should produce nothing
            created2 = sync_engagement_messages(session, {"wg-src", "wg-tgt"})
            session.commit()
            self.assertEqual(len(created2), 0)

    def test_lifecycle_messages_not_synced(self) -> None:
        """System messages like [Engagement proposed] should not be synced."""
        with Session(self.engine) as session:
            eng = self._create_engagement_with_conversations(session)

            lifecycle_msg = Message(
                conversation_id=eng.source_conversation_id,
                sender_type="system",
                content="[Engagement proposed] Test Engagement",
                requires_response=False,
            )
            session.add(lifecycle_msg)
            session.commit()

            created = sync_engagement_messages(session, {"wg-src", "wg-tgt"})
            session.commit()
            self.assertEqual(len(created), 0)

    def test_bidirectional_sync_both_sides(self) -> None:
        """Messages from both sides sync in a single call."""
        with Session(self.engine) as session:
            eng = self._create_engagement_with_conversations(session)

            session.add(Message(
                conversation_id=eng.source_conversation_id,
                sender_type="user",
                sender_user_id="u-src",
                content="From source",
                requires_response=False,
            ))
            session.add(Message(
                conversation_id=eng.target_conversation_id,
                sender_type="user",
                sender_user_id="u-tgt",
                content="From target",
                requires_response=False,
            ))
            session.commit()

            created = sync_engagement_messages(session, {"wg-src", "wg-tgt"})
            session.commit()

            self.assertEqual(len(created), 2)
            conv_ids = {m.conversation_id for m in created}
            self.assertIn(eng.source_conversation_id, conv_ids)
            self.assertIn(eng.target_conversation_id, conv_ids)

    def test_agent_attribution(self) -> None:
        with Session(self.engine) as session:
            eng = self._create_engagement_with_conversations(session)

            agent = Agent(
                id="agent-1",
                workgroup_id="wg-tgt",
                created_by_user_id="u-tgt",
                name="HelperBot",
            )
            session.add(agent)

            msg = Message(
                conversation_id=eng.target_conversation_id,
                sender_type="agent",
                sender_agent_id="agent-1",
                content="I can help with that",
                requires_response=False,
            )
            session.add(msg)
            session.commit()

            created = sync_engagement_messages(session, {"wg-src", "wg-tgt"})
            session.commit()

            self.assertEqual(len(created), 1)
            self.assertIn("[synced from agent HelperBot]", created[0].content)

    def test_no_sync_for_cancelled_engagement(self) -> None:
        with Session(self.engine) as session:
            eng = self._create_engagement_with_conversations(session, status="cancelled")

            msg = Message(
                conversation_id=eng.source_conversation_id,
                sender_type="user",
                sender_user_id="u-src",
                content="This should not sync",
                requires_response=False,
            )
            session.add(msg)
            session.commit()

            created = sync_engagement_messages(session, {"wg-src", "wg-tgt"})
            session.commit()
            self.assertEqual(len(created), 0)

    def test_empty_workgroup_ids(self) -> None:
        result = sync_engagement_messages.__wrapped__(Session(self.engine), set()) if hasattr(sync_engagement_messages, '__wrapped__') else None
        # Direct call
        with Session(self.engine) as session:
            created = sync_engagement_messages(session, set())
        self.assertEqual(len(created), 0)


if __name__ == "__main__":
    unittest.main()
