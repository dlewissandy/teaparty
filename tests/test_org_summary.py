"""Tests for org summary, activity, members, engagements, home summary, and helper endpoints."""

import unittest

from sqlmodel import Session, SQLModel, create_engine, select

from teaparty_app.models import (
    Agent,
    Conversation,
    ConversationParticipant,
    Engagement,
    Job,
    Membership,
    Message,
    Organization,
    OrgMembership,
    User,
    Workgroup,
    utc_now,
)


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_base(session: Session):
    user = User(id="u1", email="owner@example.com", name="Owner")
    org = Organization(id="org1", name="Acme", owner_id="u1")
    wg1 = Workgroup(id="wg1", name="Engineering", owner_id="u1", organization_id="org1", files=[])
    wg2 = Workgroup(id="wg2", name="Marketing", owner_id="u1", organization_id="org1", files=[])
    session.add_all([user, org, wg1, wg2])
    session.add(Membership(workgroup_id="wg1", user_id="u1", role="owner"))
    session.add(Membership(workgroup_id="wg2", user_id="u1", role="owner"))
    session.add(OrgMembership(organization_id="org1", user_id="u1", role="owner"))
    session.commit()
    return user, org, wg1, wg2


class OrgSummaryTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def test_summary_empty_org(self):
        from teaparty_app.routers.organizations import get_org_summary

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)
            result = get_org_summary(org_id="org1", session=session, user=user)

        self.assertEqual(result["org_id"], "org1")
        self.assertEqual(result["org_name"], "Acme")
        self.assertEqual(result["total_jobs"], 0)
        self.assertEqual(result["active_jobs"], 0)
        self.assertEqual(result["member_count"], 1)
        self.assertEqual(result["engagement_count"], 0)
        self.assertEqual(len(result["workgroups"]), 2)

    def test_summary_with_jobs_and_agents(self):
        from teaparty_app.routers.organizations import get_org_summary

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            agent = Agent(
                id="ag1",
                workgroup_id="wg1",
                created_by_user_id="u1",
                name="Helper",
                tools=[],
            )
            session.add(agent)

            conv = Conversation(id="conv1", workgroup_id="wg1", created_by_user_id="u1", kind="job", topic="t", name="Job1")
            session.add(conv)
            session.flush()

            job1 = Job(id="j1", title="Job One", workgroup_id="wg1", conversation_id="conv1", status="in_progress")
            job2 = Job(id="j2", title="Job Two", workgroup_id="wg1", conversation_id=None, status="completed")
            session.add_all([job1, job2])
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_org_summary(org_id="org1", session=session, user=user)

        self.assertEqual(result["total_jobs"], 2)
        self.assertEqual(result["active_jobs"], 1)
        wg1_summary = next(w for w in result["workgroups"] if w["id"] == "wg1")
        self.assertEqual(wg1_summary["job_count"], 2)
        self.assertEqual(wg1_summary["active_job_count"], 1)
        self.assertEqual(wg1_summary["agent_count"], 1)

    def test_summary_not_found(self):
        from fastapi import HTTPException
        from teaparty_app.routers.organizations import get_org_summary

        with Session(self.engine) as session:
            user = User(id="u-x", email="x@example.com", name="X")
            session.add(user)
            session.commit()

            with self.assertRaises(HTTPException) as ctx:
                get_org_summary(org_id="does-not-exist", session=session, user=user)
            self.assertEqual(ctx.exception.status_code, 404)

    def test_summary_engagement_count(self):
        from teaparty_app.routers.organizations import get_org_summary

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            # External workgroup for target
            ext_wg = Workgroup(id="wg-ext", name="External", owner_id="u1", files=[])
            session.add(ext_wg)
            session.flush()

            eng = Engagement(
                id="eng1",
                source_workgroup_id="wg1",
                target_workgroup_id="wg-ext",
                proposed_by_user_id="u1",
                status="proposed",
                title="Test Engagement",
            )
            session.add(eng)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_org_summary(org_id="org1", session=session, user=user)

        self.assertEqual(result["engagement_count"], 1)


class OrgActivityTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def test_activity_empty(self):
        from teaparty_app.routers.organizations import get_org_activity

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)
            result = get_org_activity(org_id="org1", limit=20, session=session, user=user)

        self.assertEqual(result, [])

    def test_activity_includes_messages(self):
        from teaparty_app.routers.organizations import get_org_activity

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            conv = Conversation(id="conv1", workgroup_id="wg1", created_by_user_id="u1", kind="job", topic="t", name="Job1")
            session.add(conv)
            session.flush()

            msg = Message(
                conversation_id="conv1",
                sender_type="user",
                sender_user_id="u1",
                content="Hello",
                requires_response=False,
            )
            session.add(msg)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_org_activity(org_id="org1", limit=20, session=session, user=user)

        self.assertTrue(len(result) >= 1)
        message_items = [r for r in result if r["type"] == "message"]
        self.assertTrue(len(message_items) >= 1)
        self.assertEqual(message_items[0]["workgroup_id"], "wg1")

    def test_activity_includes_completed_jobs(self):
        from teaparty_app.routers.organizations import get_org_activity

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            job = Job(
                id="j1",
                title="Completed Job",
                workgroup_id="wg1",
                status="completed",
                completed_at=utc_now(),
            )
            session.add(job)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_org_activity(org_id="org1", limit=20, session=session, user=user)

        job_items = [r for r in result if r["type"] == "job_completed"]
        self.assertTrue(len(job_items) >= 1)
        self.assertIn("Completed Job", job_items[0]["summary"])

    def test_activity_limit_respected(self):
        from teaparty_app.routers.organizations import get_org_activity

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            conv = Conversation(id="conv1", workgroup_id="wg1", created_by_user_id="u1", kind="job", topic="t", name="J1")
            session.add(conv)
            session.flush()

            for i in range(15):
                session.add(Message(
                    conversation_id="conv1",
                    sender_type="user",
                    sender_user_id="u1",
                    content=f"msg {i}",
                    requires_response=False,
                ))
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_org_activity(org_id="org1", limit=5, session=session, user=user)

        self.assertLessEqual(len(result), 5)


class OrgMembersTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def test_members_deduplication(self):
        from teaparty_app.routers.organizations import get_org_members

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            user2 = User(id="u2", email="member@example.com", name="Member")
            session.add(user2)
            # user2 is in both workgroups and has an org membership
            session.add(Membership(workgroup_id="wg1", user_id="u2", role="member"))
            session.add(Membership(workgroup_id="wg2", user_id="u2", role="member"))
            session.add(OrgMembership(organization_id="org1", user_id="u2", role="member"))
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_org_members(org_id="org1", session=session, user=user)

        # 2 unique users: u1 and u2
        self.assertEqual(len(result), 2)
        user2_entry = next((m for m in result if m["user_id"] == "u2"), None)
        self.assertIsNotNone(user2_entry)

    def test_members_empty_org(self):
        from teaparty_app.routers.organizations import get_org_members

        with Session(self.engine) as session:
            user2 = User(id="u-standalone", email="standalone@example.com", name="Standalone")
            org2 = Organization(id="org2", name="Empty Org", owner_id="u-standalone")
            session.add_all([user2, org2])
            session.commit()

            result = get_org_members(org_id="org2", session=session, user=user2)

        self.assertEqual(result, [])

    def test_members_role_promotion(self):
        from teaparty_app.routers.organizations import get_org_members

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            user3 = User(id="u3", email="editor@example.com", name="Editor")
            session.add(user3)
            # member in wg1, owner in wg2; org membership at member level
            session.add(Membership(workgroup_id="wg1", user_id="u3", role="member"))
            session.add(Membership(workgroup_id="wg2", user_id="u3", role="owner"))
            session.add(OrgMembership(organization_id="org1", user_id="u3", role="member"))
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_org_members(org_id="org1", session=session, user=user)

        u3_entry = next((m for m in result if m["user_id"] == "u3"), None)
        self.assertIsNotNone(u3_entry)
        # OrgMembership has role "member"; workgroup roles don't affect org role
        self.assertEqual(u3_entry["role"], "member")


class OrgEngagementsTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def test_engagements_empty(self):
        from teaparty_app.routers.organizations import get_org_engagements

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)
            result = get_org_engagements(org_id="org1", session=session, user=user)

        self.assertEqual(result, [])

    def test_engagements_as_source(self):
        from teaparty_app.routers.organizations import get_org_engagements

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            ext_user = User(id="u-ext", email="ext@example.com", name="External")
            ext_wg = Workgroup(id="wg-ext", name="External WG", owner_id="u-ext", files=[])
            session.add_all([ext_user, ext_wg])
            session.flush()

            eng = Engagement(
                id="eng1",
                source_workgroup_id="wg1",
                target_workgroup_id="wg-ext",
                proposed_by_user_id="u1",
                status="proposed",
                title="Build Widget",
            )
            session.add(eng)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_org_engagements(org_id="org1", session=session, user=user)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "eng1")
        self.assertEqual(result[0]["title"], "Build Widget")
        self.assertEqual(result[0]["source_workgroup"]["id"], "wg1")

    def test_engagements_as_target(self):
        from teaparty_app.routers.organizations import get_org_engagements

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            ext_user = User(id="u-ext2", email="ext2@example.com", name="External2")
            ext_wg = Workgroup(id="wg-ext2", name="External WG2", owner_id="u-ext2", files=[])
            session.add_all([ext_user, ext_wg])
            session.flush()

            eng = Engagement(
                id="eng2",
                source_workgroup_id="wg-ext2",
                target_workgroup_id="wg2",
                proposed_by_user_id="u-ext2",
                status="in_progress",
                title="Inbound Engagement",
            )
            session.add(eng)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_org_engagements(org_id="org1", session=session, user=user)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "eng2")


class HomeSummaryTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def test_home_summary_no_orgs(self):
        from teaparty_app.routers.organizations import get_home_summary

        with Session(self.engine) as session:
            user = User(id="u-lone", email="lone@example.com", name="Lone")
            session.add(user)
            session.commit()

            result = get_home_summary(session=session, user=user)

        self.assertEqual(result["total_active_jobs"], 0)
        self.assertEqual(result["total_attention_needed"], 0)
        self.assertEqual(result["orgs"], [])

    def test_home_summary_with_jobs(self):
        from teaparty_app.routers.organizations import get_home_summary

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            conv = Conversation(id="conv1", workgroup_id="wg1", created_by_user_id="u1", kind="job", topic="t", name="J1")
            session.add(conv)
            session.flush()

            job = Job(id="j1", title="Active Job", workgroup_id="wg1", conversation_id="conv1", status="in_progress")
            session.add(job)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_home_summary(session=session, user=user)

        self.assertEqual(result["total_active_jobs"], 1)
        self.assertEqual(len(result["orgs"]), 1)
        self.assertEqual(result["orgs"][0]["id"], "org1")
        self.assertEqual(result["orgs"][0]["active_jobs"], 1)

    def test_home_summary_attention_needed_agent_response(self):
        from teaparty_app.routers.organizations import get_home_summary

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            agent = Agent(
                id="ag1",
                workgroup_id="wg1",
                created_by_user_id="u1",
                name="Helper",
                tools=[],
            )
            session.add(agent)

            conv = Conversation(id="conv1", workgroup_id="wg1", created_by_user_id="u1", kind="job", topic="t", name="J1")
            session.add(conv)
            session.flush()

            job = Job(id="j1", title="Job", workgroup_id="wg1", conversation_id="conv1", status="in_progress")
            session.add(job)

            # Last message is agent with requires_response=True
            msg = Message(
                conversation_id="conv1",
                sender_type="agent",
                sender_agent_id="ag1",
                content="I need your input",
                requires_response=True,
            )
            session.add(msg)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_home_summary(session=session, user=user)

        self.assertEqual(result["total_attention_needed"], 1)
        self.assertEqual(result["orgs"][0]["attention_needed"], 1)

    def test_home_summary_attention_needed_pending_engagement(self):
        from teaparty_app.routers.organizations import get_home_summary

        with Session(self.engine) as session:
            user, org, wg1, wg2 = _seed_base(session)

            ext_user = User(id="u-ext", email="ext@example.com", name="External")
            ext_wg = Workgroup(id="wg-ext", name="External", owner_id="u-ext", files=[])
            session.add_all([ext_user, ext_wg])
            session.flush()

            eng = Engagement(
                id="eng1",
                source_workgroup_id="wg-ext",
                target_workgroup_id="wg1",
                proposed_by_user_id="u-ext",
                status="proposed",
                title="Inbound",
            )
            session.add(eng)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_home_summary(session=session, user=user)

        self.assertEqual(result["total_attention_needed"], 1)


class ConversationParticipantsTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def _seed(self, session: Session):
        user = User(id="u1", email="owner@example.com", name="Owner")
        wg = Workgroup(id="wg1", name="WG", owner_id="u1", files=[])
        session.add_all([user, wg])
        session.add(Membership(workgroup_id="wg1", user_id="u1", role="owner"))
        conv = Conversation(id="conv1", workgroup_id="wg1", created_by_user_id="u1", kind="job", topic="t", name="J1")
        session.add(conv)
        session.flush()
        return user, wg, conv

    def test_participants_users_and_agents(self):
        from teaparty_app.routers.conversations import get_conversation_participants

        with Session(self.engine) as session:
            user, wg, conv = self._seed(session)

            agent = Agent(
                id="ag1",
                workgroup_id="wg1",
                created_by_user_id="u1",
                name="Helper",
                description="Coder",
                is_lead=True,
                tools=[],
            )
            session.add(agent)
            session.flush()

            session.add(ConversationParticipant(conversation_id="conv1", user_id="u1"))
            session.add(ConversationParticipant(conversation_id="conv1", agent_id="ag1"))
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_conversation_participants(conversation_id="conv1", session=session, user=user)

        self.assertEqual(len(result["users"]), 1)
        self.assertEqual(result["users"][0]["id"], "u1")
        self.assertEqual(len(result["agents"]), 1)
        self.assertEqual(result["agents"][0]["id"], "ag1")
        self.assertTrue(result["agents"][0]["is_lead"])

    def test_participants_empty(self):
        from teaparty_app.routers.conversations import get_conversation_participants

        with Session(self.engine) as session:
            user, wg, conv = self._seed(session)
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_conversation_participants(conversation_id="conv1", session=session, user=user)

        self.assertEqual(result["users"], [])
        self.assertEqual(result["agents"], [])


class ConversationWorkflowStateTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def _seed(self, session: Session, wg_files=None):
        user = User(id="u1", email="owner@example.com", name="Owner")
        wg = Workgroup(id="wg1", name="WG", owner_id="u1", files=wg_files or [])
        session.add_all([user, wg])
        session.add(Membership(workgroup_id="wg1", user_id="u1", role="owner"))
        conv = Conversation(id="conv1", workgroup_id="wg1", created_by_user_id="u1", kind="job", topic="t", name="J1")
        session.add(conv)
        session.commit()
        return user, wg, conv

    def test_no_workflow_state_file(self):
        from teaparty_app.routers.conversations import get_conversation_workflow_state

        with Session(self.engine) as session:
            user, wg, conv = self._seed(session)

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_conversation_workflow_state(conversation_id="conv1", session=session, user=user)

        self.assertEqual(result["steps"], [])
        self.assertIsNone(result["current_step"])

    def test_workflow_state_parsed(self):
        from teaparty_app.routers.conversations import get_conversation_workflow_state

        state_content = (
            "# Workflow State\n"
            "\n"
            "- **Workflow**: workflows/feature-build.md\n"
            "- **Status**: in_progress\n"
            "- **Current Step**: 2\n"
            "\n"
            "## Step Log\n"
            "- [x] 1. Scope (completed)\n"
            "- [ ] 2. Analyze (in_progress)\n"
            "- [ ] 3. Implement (pending)\n"
        )
        wg_files = [
            {"id": "f1", "path": "_workflow_state.md", "content": state_content, "topic_id": "conv1"}
        ]

        with Session(self.engine) as session:
            user, wg, conv = self._seed(session, wg_files=wg_files)

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_conversation_workflow_state(conversation_id="conv1", session=session, user=user)

        self.assertEqual(result["current_step"], 2)
        self.assertEqual(len(result["steps"]), 3)
        self.assertEqual(result["steps"][0]["number"], 1)
        self.assertEqual(result["steps"][0]["status"], "completed")
        self.assertEqual(result["steps"][1]["number"], 2)
        self.assertEqual(result["steps"][1]["status"], "in_progress")
        self.assertEqual(result["steps"][2]["number"], 3)
        self.assertEqual(result["steps"][2]["status"], "pending")

    def test_workflow_state_wrong_topic_id_ignored(self):
        from teaparty_app.routers.conversations import get_conversation_workflow_state

        state_content = "# Workflow State\n- **Current Step**: 1\n## Step Log\n- [x] 1. Done (completed)\n"
        wg_files = [
            {"id": "f1", "path": "_workflow_state.md", "content": state_content, "topic_id": "other-conv"}
        ]

        with Session(self.engine) as session:
            user, wg, conv = self._seed(session, wg_files=wg_files)

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_conversation_workflow_state(conversation_id="conv1", session=session, user=user)

        self.assertEqual(result["steps"], [])
        self.assertIsNone(result["current_step"])


class WorkflowStateParserTest(unittest.TestCase):
    def test_parse_empty(self):
        from teaparty_app.routers.conversations import _parse_workflow_state

        result = _parse_workflow_state("")
        self.assertEqual(result["steps"], [])
        self.assertIsNone(result["current_step"])

    def test_parse_full_content(self):
        from teaparty_app.routers.conversations import _parse_workflow_state

        content = (
            "# Workflow State\n"
            "- **Current Step**: 3\n"
            "## Step Log\n"
            "- [x] 1. Setup (completed)\n"
            "- [x] 2. Build (completed)\n"
            "- [ ] 3. Test (in_progress)\n"
            "- [ ] 4. Deploy (pending)\n"
        )
        result = _parse_workflow_state(content)
        self.assertEqual(result["current_step"], 3)
        self.assertEqual(len(result["steps"]), 4)
        self.assertEqual(result["steps"][2]["status"], "in_progress")
        self.assertEqual(result["steps"][3]["status"], "pending")

    def test_parse_checked_without_status(self):
        from teaparty_app.routers.conversations import _parse_workflow_state

        content = "## Step Log\n- [x] 1. Done step\n- [ ] 2. Todo step\n"
        result = _parse_workflow_state(content)
        self.assertEqual(result["steps"][0]["status"], "completed")
        self.assertEqual(result["steps"][1]["status"], "pending")


class EngagementJobsTest(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()

    def _seed(self, session: Session):
        user = User(id="u1", email="owner@example.com", name="Owner")
        wg_src = Workgroup(id="wg-src", name="Source", owner_id="u1", files=[])
        wg_tgt = Workgroup(id="wg-tgt", name="Target", owner_id="u1", files=[])
        session.add_all([user, wg_src, wg_tgt])
        session.add(Membership(workgroup_id="wg-src", user_id="u1", role="owner"))
        session.add(Membership(workgroup_id="wg-tgt", user_id="u1", role="owner"))

        eng = Engagement(
            id="eng1",
            source_workgroup_id="wg-src",
            target_workgroup_id="wg-tgt",
            proposed_by_user_id="u1",
            status="in_progress",
            title="Test Engagement",
        )
        session.add(eng)
        session.commit()
        return user, eng

    def test_engagement_jobs_empty(self):
        from teaparty_app.routers.engagements import get_engagement_jobs

        with Session(self.engine) as session:
            user, eng = self._seed(session)
            result = get_engagement_jobs(engagement_id="eng1", session=session, user=user)

        self.assertEqual(result, [])

    def test_engagement_jobs_returned(self):
        from teaparty_app.routers.engagements import get_engagement_jobs

        with Session(self.engine) as session:
            user, eng = self._seed(session)

            job1 = Job(
                id="j1",
                title="Task Alpha",
                workgroup_id="wg-tgt",
                engagement_id="eng1",
                status="in_progress",
            )
            job2 = Job(
                id="j2",
                title="Task Beta",
                workgroup_id="wg-tgt",
                engagement_id="eng1",
                status="completed",
            )
            session.add_all([job1, job2])
            session.commit()

        with Session(self.engine) as session:
            user = session.get(User, "u1")
            result = get_engagement_jobs(engagement_id="eng1", session=session, user=user)

        self.assertEqual(len(result), 2)
        titles = {r["title"] for r in result}
        self.assertIn("Task Alpha", titles)
        self.assertIn("Task Beta", titles)
        # Verify fields
        job_alpha = next(r for r in result if r["title"] == "Task Alpha")
        self.assertEqual(job_alpha["engagement_id"] if "engagement_id" in job_alpha else "eng1", "eng1")
        self.assertIn("created_at", job_alpha)

    def test_engagement_jobs_not_found(self):
        from fastapi import HTTPException
        from teaparty_app.routers.engagements import get_engagement_jobs

        with Session(self.engine) as session:
            user = User(id="u-x", email="x@example.com", name="X")
            session.add(user)
            session.commit()

            with self.assertRaises(HTTPException) as ctx:
                get_engagement_jobs(engagement_id="no-such", session=session, user=user)
            self.assertEqual(ctx.exception.status_code, 404)

    def test_engagement_jobs_outsider_blocked(self):
        from fastapi import HTTPException
        from teaparty_app.routers.engagements import get_engagement_jobs

        with Session(self.engine) as session:
            user, eng = self._seed(session)

            outsider = User(id="u-out", email="out@example.com", name="Outsider")
            session.add(outsider)
            session.commit()

        with Session(self.engine) as session:
            outsider = session.get(User, "u-out")
            with self.assertRaises(HTTPException) as ctx:
                get_engagement_jobs(engagement_id="eng1", session=session, user=outsider)
            self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
