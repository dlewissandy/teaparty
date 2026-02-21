import unittest

from sqlmodel import SQLModel, Session, create_engine

from teaparty_app.models import Conversation, LLMUsageEvent, Membership, User, Workgroup
from teaparty_app.services.llm_usage import get_workgroup_usage


class GetWorkgroupUsageTests(unittest.TestCase):
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

    def test_no_usage_events(self) -> None:
        self._seed()
        with Session(self.engine) as session:
            result = get_workgroup_usage(session, "wg-1")
        self.assertEqual(result["workgroup_id"], "wg-1")
        self.assertEqual(result["total_input_tokens"], 0)
        self.assertEqual(result["total_output_tokens"], 0)
        self.assertEqual(result["total_tokens"], 0)
        self.assertEqual(result["total_duration_ms"], 0)
        self.assertEqual(result["estimated_cost_usd"], 0)
        self.assertEqual(result["api_calls"], 0)
        self.assertEqual(result["by_model"], {})

    def test_aggregates_across_conversations(self) -> None:
        self._seed()
        with Session(self.engine) as session:
            conv1 = Conversation(id="conv-1", workgroup_id="wg-1", created_by_user_id="user-1", topic="t1", name="t1")
            conv2 = Conversation(id="conv-2", workgroup_id="wg-1", created_by_user_id="user-1", topic="t2", name="t2")
            session.add(conv1)
            session.add(conv2)
            session.add(LLMUsageEvent(
                conversation_id="conv-1", model="sonnet",
                input_tokens=100, output_tokens=50, purpose="reply", duration_ms=500,
            ))
            session.add(LLMUsageEvent(
                conversation_id="conv-2", model="sonnet",
                input_tokens=200, output_tokens=100, purpose="reply", duration_ms=700,
            ))
            session.commit()

        with Session(self.engine) as session:
            result = get_workgroup_usage(session, "wg-1")
        self.assertEqual(result["total_input_tokens"], 300)
        self.assertEqual(result["total_output_tokens"], 150)
        self.assertEqual(result["total_tokens"], 450)
        self.assertEqual(result["total_duration_ms"], 1200)
        self.assertEqual(result["api_calls"], 2)
        self.assertGreater(result["estimated_cost_usd"], 0)

    def test_excludes_other_workgroup(self) -> None:
        self._seed()
        with Session(self.engine) as session:
            wg2 = Workgroup(id="wg-2", name="Other", owner_id="user-1", files=[])
            session.add(wg2)
            conv1 = Conversation(id="conv-1", workgroup_id="wg-1", created_by_user_id="user-1", topic="t1", name="t1")
            conv_other = Conversation(id="conv-other", workgroup_id="wg-2", created_by_user_id="user-1", topic="t", name="t")
            session.add(conv1)
            session.add(conv_other)
            session.add(LLMUsageEvent(
                conversation_id="conv-1", model="sonnet",
                input_tokens=100, output_tokens=50, purpose="reply", duration_ms=500,
            ))
            session.add(LLMUsageEvent(
                conversation_id="conv-other", model="sonnet",
                input_tokens=9999, output_tokens=9999, purpose="reply", duration_ms=9999,
            ))
            session.commit()

        with Session(self.engine) as session:
            result = get_workgroup_usage(session, "wg-1")
        self.assertEqual(result["total_input_tokens"], 100)
        self.assertEqual(result["total_output_tokens"], 50)
        self.assertEqual(result["api_calls"], 1)

    def test_by_model_breakdown(self) -> None:
        self._seed()
        with Session(self.engine) as session:
            conv = Conversation(id="conv-1", workgroup_id="wg-1", created_by_user_id="user-1", topic="t", name="t")
            session.add(conv)
            session.add(LLMUsageEvent(
                conversation_id="conv-1", model="sonnet",
                input_tokens=100, output_tokens=50, purpose="reply", duration_ms=300,
            ))
            session.add(LLMUsageEvent(
                conversation_id="conv-1", model="haiku",
                input_tokens=200, output_tokens=80, purpose="reply", duration_ms=200,
            ))
            session.add(LLMUsageEvent(
                conversation_id="conv-1", model="sonnet",
                input_tokens=50, output_tokens=20, purpose="reply", duration_ms=100,
            ))
            session.commit()

        with Session(self.engine) as session:
            result = get_workgroup_usage(session, "wg-1")

        by_model = result["by_model"]
        self.assertIn("sonnet", by_model)
        self.assertIn("haiku", by_model)

        sonnet = by_model["sonnet"]
        self.assertEqual(sonnet["input_tokens"], 150)
        self.assertEqual(sonnet["output_tokens"], 70)
        self.assertEqual(sonnet["calls"], 2)

        haiku = by_model["haiku"]
        self.assertEqual(haiku["input_tokens"], 200)
        self.assertEqual(haiku["output_tokens"], 80)
        self.assertEqual(haiku["calls"], 1)
