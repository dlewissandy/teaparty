"""Tests for the orchestration service."""

import unittest
import unittest.mock
from sqlmodel import SQLModel, Session, create_engine, select

from teaparty_app.models import (
    Agent,
    Conversation,
    Engagement,
    Job,
    Membership,
    Message,
    OrgBalance,
    Organization,
    User,
    Workgroup,
)
from teaparty_app.services.orchestration import (
    browse_directory,
    check_balance,
    complete_engagement_by_agent,
    create_engagement_job,
    list_team_jobs,
    post_to_job,
    propose_engagement_by_agent,
    read_job_status,
    respond_engagement_by_agent,
    set_engagement_price,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_user(session: Session, user_id: str) -> User:
    user = User(id=user_id, email=f"{user_id}@example.com", name=user_id)
    session.add(user)
    return user


def _make_org(
    session: Session,
    user: User,
    org_id: str,
    name: str,
    accepting: bool = False,
) -> Organization:
    org = Organization(
        id=org_id,
        name=name,
        description=f"Description for {name}",
        owner_id=user.id,
        service_description=f"Services by {name}",
        is_accepting_engagements=accepting,
    )
    session.add(org)
    return org


def _make_workgroup(
    session: Session,
    user: User,
    org: Organization,
    wg_id: str,
    name: str,
) -> Workgroup:
    wg = Workgroup(
        id=wg_id,
        name=name,
        owner_id=user.id,
        organization_id=org.id,
        files=[],
    )
    session.add(wg)
    return wg


def _make_agent(
    session: Session,
    workgroup: Workgroup,
    user: User,
    agent_id: str,
    name: str,
    role: str = "",
) -> Agent:
    agent = Agent(
        id=agent_id,
        workgroup_id=workgroup.id,
        created_by_user_id=user.id,
        name=name,
        description=role,
        tools=[],
    )
    session.add(agent)
    return agent


def _make_membership(
    session: Session,
    workgroup: Workgroup,
    user: User,
    role: str = "owner",
) -> Membership:
    membership = Membership(workgroup_id=workgroup.id, user_id=user.id, role=role)
    session.add(membership)
    return membership


# ---------------------------------------------------------------------------
# browse_directory tests
# ---------------------------------------------------------------------------

class BrowseDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_returns_only_accepting_orgs(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            _make_org(session, user, "org-open", "Open Org", accepting=True)
            _make_org(session, user, "org-closed", "Closed Org", accepting=False)
            session.commit()

        with Session(self.engine) as session:
            results = browse_directory(session)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "org-open")
        self.assertEqual(results[0]["name"], "Open Org")

    def test_returns_empty_list_when_none_accepting(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            _make_org(session, user, "org-closed", "Closed Org", accepting=False)
            session.commit()

        with Session(self.engine) as session:
            results = browse_directory(session)

        self.assertEqual(results, [])

    def test_result_contains_expected_fields(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            _make_org(session, user, "org-1", "Acme Corp", accepting=True)
            session.commit()

        with Session(self.engine) as session:
            results = browse_directory(session)

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertIn("id", result)
        self.assertIn("name", result)
        self.assertIn("description", result)
        self.assertIn("service_description", result)

    def test_returns_multiple_accepting_orgs(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            _make_org(session, user, "org-a", "Alpha", accepting=True)
            _make_org(session, user, "org-b", "Beta", accepting=True)
            _make_org(session, user, "org-c", "Gamma", accepting=False)
            session.commit()

        with Session(self.engine) as session:
            results = browse_directory(session)

        self.assertEqual(len(results), 2)
        ids = {r["id"] for r in results}
        self.assertIn("org-a", ids)
        self.assertIn("org-b", ids)
        self.assertNotIn("org-c", ids)


# ---------------------------------------------------------------------------
# check_balance tests
# ---------------------------------------------------------------------------

class CheckBalanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_returns_balance_for_existing_org(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            _make_org(session, user, "org-1", "Acme", accepting=True)
            # Seed a balance record directly
            balance = OrgBalance(organization_id="org-1", balance_credits=250.0)
            session.add(balance)
            session.commit()

        with Session(self.engine) as session:
            result = check_balance(session, "org-1")

        self.assertEqual(result["organization_id"], "org-1")
        self.assertEqual(result["organization_name"], "Acme")
        self.assertEqual(result["balance_credits"], 250.0)

    def test_creates_balance_when_none_exists(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            _make_org(session, user, "org-1", "Acme", accepting=True)
            session.commit()

        with Session(self.engine) as session:
            result = check_balance(session, "org-1")

        self.assertNotIn("error", result)
        self.assertEqual(result["organization_id"], "org-1")
        self.assertEqual(result["balance_credits"], 0.0)

    def test_returns_error_for_nonexistent_org(self) -> None:
        with Session(self.engine) as session:
            result = check_balance(session, "org-nonexistent")

        self.assertIn("error", result)
        self.assertIn("not found", result["error"].lower())


# ---------------------------------------------------------------------------
# propose_engagement_by_agent tests
# ---------------------------------------------------------------------------

class ProposeEngagementByAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            src_user = _make_user(session, "u-src")
            tgt_user = _make_user(session, "u-tgt")

            src_org = _make_org(session, src_user, "org-src", "Source Corp", accepting=True)
            tgt_org = _make_org(session, tgt_user, "org-tgt", "Target Corp", accepting=True)

            src_wg = _make_workgroup(session, src_user, src_org, "wg-src", "Source Team")
            tgt_wg = _make_workgroup(session, tgt_user, tgt_org, "wg-tgt", "Target Team")

            src_org.operations_workgroup_id = src_wg.id
            tgt_org.operations_workgroup_id = tgt_wg.id
            session.add(src_org)
            session.add(tgt_org)

            _make_membership(session, src_wg, src_user)
            _make_membership(session, tgt_wg, tgt_user)

            _make_agent(session, src_wg, src_user, "agent-src", "Coordinator")
            session.commit()

    def test_creates_engagement_with_proposed_status(self) -> None:
        with Session(self.engine) as session:
            result = propose_engagement_by_agent(
                session,
                agent_id="agent-src",
                target_org_id="org-tgt",
                title="Build a widget",
                scope="Frontend only",
                requirements="Must be accessible",
            )

        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["title"], "Build a widget")

    def test_creates_source_and_target_conversations(self) -> None:
        with Session(self.engine) as session:
            result = propose_engagement_by_agent(
                session,
                agent_id="agent-src",
                target_org_id="org-tgt",
                title="Build a widget",
            )
            session.commit()

        self.assertIsNotNone(result.get("source_conversation_id"))
        self.assertIsNotNone(result.get("target_conversation_id"))

        with Session(self.engine) as session:
            src_conv = session.get(Conversation, result["source_conversation_id"])
            tgt_conv = session.get(Conversation, result["target_conversation_id"])

        self.assertIsNotNone(src_conv)
        self.assertIsNotNone(tgt_conv)
        self.assertEqual(src_conv.kind, "engagement")
        self.assertEqual(tgt_conv.kind, "engagement")

    def test_posts_system_messages_to_both_conversations(self) -> None:
        with Session(self.engine) as session:
            result = propose_engagement_by_agent(
                session,
                agent_id="agent-src",
                target_org_id="org-tgt",
                title="Widget project",
                scope="Full stack",
            )
            session.commit()

        with Session(self.engine) as session:
            src_msgs = session.exec(
                select(Message).where(
                    Message.conversation_id == result["source_conversation_id"]
                )
            ).all()
            tgt_msgs = session.exec(
                select(Message).where(
                    Message.conversation_id == result["target_conversation_id"]
                )
            ).all()

        self.assertTrue(len(src_msgs) >= 1)
        self.assertTrue(len(tgt_msgs) >= 1)
        self.assertIn("[Engagement proposed]", src_msgs[0].content)
        self.assertIn("[Engagement proposed]", tgt_msgs[0].content)

    def test_returns_error_for_nonexistent_agent(self) -> None:
        with Session(self.engine) as session:
            result = propose_engagement_by_agent(
                session,
                agent_id="agent-missing",
                target_org_id="org-tgt",
                title="Anything",
            )

        self.assertIn("error", result)

    def test_returns_error_for_nonexistent_target_org(self) -> None:
        with Session(self.engine) as session:
            result = propose_engagement_by_agent(
                session,
                agent_id="agent-src",
                target_org_id="org-nonexistent",
                title="Anything",
            )

        self.assertIn("error", result)

    def test_uses_operations_workgroup_as_target(self) -> None:
        with Session(self.engine) as session:
            result = propose_engagement_by_agent(
                session,
                agent_id="agent-src",
                target_org_id="org-tgt",
                title="Ops workgroup engagement",
            )
            session.commit()

        self.assertNotIn("error", result)
        with Session(self.engine) as session:
            tgt_conv = session.get(Conversation, result["target_conversation_id"])
        self.assertEqual(tgt_conv.workgroup_id, "wg-tgt")

    def test_strips_whitespace_from_title_scope_requirements(self) -> None:
        with Session(self.engine) as session:
            result = propose_engagement_by_agent(
                session,
                agent_id="agent-src",
                target_org_id="org-tgt",
                title="  Trimmed title  ",
                scope="  Trimmed scope  ",
                requirements="  Trimmed reqs  ",
            )
            session.commit()

        self.assertEqual(result["title"], "Trimmed title")

        with Session(self.engine) as session:
            eng = session.get(Engagement, result["engagement_id"])
        self.assertEqual(eng.scope, "Trimmed scope")
        self.assertEqual(eng.requirements, "Trimmed reqs")


# ---------------------------------------------------------------------------
# respond_engagement_by_agent tests
# ---------------------------------------------------------------------------

class RespondEngagementByAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            src_user = _make_user(session, "u-src")
            tgt_user = _make_user(session, "u-tgt")
            other_user = _make_user(session, "u-other")

            src_org = _make_org(session, src_user, "org-src", "Source Corp")
            tgt_org = _make_org(session, tgt_user, "org-tgt", "Target Corp")
            other_org = _make_org(session, other_user, "org-other", "Other Corp")

            src_wg = _make_workgroup(session, src_user, src_org, "wg-src", "Source Team")
            tgt_wg = _make_workgroup(session, tgt_user, tgt_org, "wg-tgt", "Target Team")
            other_wg = _make_workgroup(session, other_user, other_org, "wg-other", "Other Team")

            _make_membership(session, src_wg, src_user)
            _make_membership(session, tgt_wg, tgt_user)
            _make_membership(session, other_wg, other_user)

            _make_agent(session, src_wg, src_user, "agent-src", "Source Agent")
            _make_agent(session, tgt_wg, tgt_user, "agent-tgt", "Target Agent")
            _make_agent(session, other_wg, other_user, "agent-other", "Outsider Agent")

            # Build engagement with conversations
            src_conv = Conversation(
                id="conv-src",
                workgroup_id="wg-src",
                created_by_user_id="u-src",
                kind="engagement",
                topic="engagement:eng-1",
                name="Test Engagement",
            )
            tgt_conv = Conversation(
                id="conv-tgt",
                workgroup_id="wg-tgt",
                created_by_user_id="u-src",
                kind="engagement",
                topic="engagement:eng-1",
                name="Test Engagement",
            )
            session.add(src_conv)
            session.add(tgt_conv)
            session.flush()

            eng = Engagement(
                id="eng-1",
                source_workgroup_id="wg-src",
                target_workgroup_id="wg-tgt",
                proposed_by_user_id="u-src",
                status="proposed",
                title="Test Engagement",
                source_conversation_id="conv-src",
                target_conversation_id="conv-tgt",
            )
            session.add(eng)
            session.commit()

    def test_accept_sets_status_to_in_progress(self) -> None:
        with Session(self.engine) as session:
            result = respond_engagement_by_agent(
                session,
                agent_id="agent-tgt",
                engagement_id="eng-1",
                action="accept",
            )
            session.commit()

        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "in_progress")

        with Session(self.engine) as session:
            eng = session.get(Engagement, "eng-1")
        self.assertEqual(eng.status, "in_progress")
        self.assertIsNotNone(eng.accepted_at)

    def test_accept_with_terms_stores_terms(self) -> None:
        with Session(self.engine) as session:
            respond_engagement_by_agent(
                session,
                agent_id="agent-tgt",
                engagement_id="eng-1",
                action="accept",
                terms="Net 30 payment",
            )
            session.commit()

        with Session(self.engine) as session:
            eng = session.get(Engagement, "eng-1")
        self.assertEqual(eng.terms, "Net 30 payment")

    def test_decline_sets_status_to_declined(self) -> None:
        with Session(self.engine) as session:
            result = respond_engagement_by_agent(
                session,
                agent_id="agent-tgt",
                engagement_id="eng-1",
                action="decline",
            )
            session.commit()

        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "declined")

        with Session(self.engine) as session:
            eng = session.get(Engagement, "eng-1")
        self.assertEqual(eng.status, "declined")
        self.assertIsNotNone(eng.declined_at)

    def test_decline_posts_system_messages(self) -> None:
        with Session(self.engine) as session:
            respond_engagement_by_agent(
                session,
                agent_id="agent-tgt",
                engagement_id="eng-1",
                action="decline",
            )
            session.commit()

        with Session(self.engine) as session:
            src_msgs = session.exec(
                select(Message).where(Message.conversation_id == "conv-src")
            ).all()
            tgt_msgs = session.exec(
                select(Message).where(Message.conversation_id == "conv-tgt")
            ).all()

        self.assertTrue(any("[Engagement declined]" in m.content for m in src_msgs))
        self.assertTrue(any("[Engagement declined]" in m.content for m in tgt_msgs))

    def test_agent_from_wrong_org_is_rejected(self) -> None:
        with Session(self.engine) as session:
            result = respond_engagement_by_agent(
                session,
                agent_id="agent-other",
                engagement_id="eng-1",
                action="accept",
            )

        self.assertIn("error", result)
        self.assertIn("target organization", result["error"])

    def test_cannot_respond_to_completed_engagement(self) -> None:
        with Session(self.engine) as session:
            eng = session.get(Engagement, "eng-1")
            eng.status = "completed"
            session.add(eng)
            session.commit()

        with Session(self.engine) as session:
            result = respond_engagement_by_agent(
                session,
                agent_id="agent-tgt",
                engagement_id="eng-1",
                action="accept",
            )

        self.assertIn("error", result)

    def test_returns_error_for_nonexistent_agent(self) -> None:
        with Session(self.engine) as session:
            result = respond_engagement_by_agent(
                session,
                agent_id="agent-ghost",
                engagement_id="eng-1",
                action="accept",
            )

        self.assertIn("error", result)

    def test_returns_error_for_nonexistent_engagement(self) -> None:
        with Session(self.engine) as session:
            result = respond_engagement_by_agent(
                session,
                agent_id="agent-tgt",
                engagement_id="eng-ghost",
                action="accept",
            )

        self.assertIn("error", result)


# ---------------------------------------------------------------------------
# set_engagement_price tests
# ---------------------------------------------------------------------------

class SetEngagementPriceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            src_wg_row = Workgroup(id="wg-src", name="Source", owner_id="u-1", files=[])
            tgt_wg_row = Workgroup(id="wg-tgt", name="Target", owner_id="u-1", files=[])
            session.add(user)
            session.add(src_wg_row)
            session.add(tgt_wg_row)
            session.flush()

            src_conv = Conversation(
                id="conv-src",
                workgroup_id="wg-src",
                created_by_user_id="u-1",
                kind="engagement",
                topic="engagement:eng-1",
                name="Eng 1",
            )
            tgt_conv = Conversation(
                id="conv-tgt",
                workgroup_id="wg-tgt",
                created_by_user_id="u-1",
                kind="engagement",
                topic="engagement:eng-1",
                name="Eng 1",
            )
            session.add(src_conv)
            session.add(tgt_conv)
            session.flush()

            eng = Engagement(
                id="eng-1",
                source_workgroup_id="wg-src",
                target_workgroup_id="wg-tgt",
                proposed_by_user_id="u-1",
                status="in_progress",
                title="Design project",
                source_conversation_id="conv-src",
                target_conversation_id="conv-tgt",
            )
            session.add(eng)
            session.commit()

    def test_updates_agreed_price(self) -> None:
        with Session(self.engine) as session:
            result = set_engagement_price(session, "eng-1", 500.0)
            session.commit()

        self.assertNotIn("error", result)
        self.assertEqual(result["agreed_price_credits"], 500.0)
        self.assertEqual(result["engagement_id"], "eng-1")

        with Session(self.engine) as session:
            eng = session.get(Engagement, "eng-1")
        self.assertEqual(eng.agreed_price_credits, 500.0)

    def test_posts_price_notifications_to_both_conversations(self) -> None:
        with Session(self.engine) as session:
            set_engagement_price(session, "eng-1", 750.0)
            session.commit()

        with Session(self.engine) as session:
            src_msgs = session.exec(
                select(Message).where(Message.conversation_id == "conv-src")
            ).all()
            tgt_msgs = session.exec(
                select(Message).where(Message.conversation_id == "conv-tgt")
            ).all()

        self.assertTrue(any("[Price agreed]" in m.content for m in src_msgs))
        self.assertTrue(any("[Price agreed]" in m.content for m in tgt_msgs))
        self.assertTrue(any("750.0" in m.content for m in src_msgs))

    def test_returns_error_for_nonexistent_engagement(self) -> None:
        with Session(self.engine) as session:
            result = set_engagement_price(session, "eng-ghost", 100.0)

        self.assertIn("error", result)


# ---------------------------------------------------------------------------
# create_engagement_job tests
# ---------------------------------------------------------------------------

class CreateEngagementJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme Corp")
            coord_wg = _make_workgroup(session, user, org, "wg-coord", "Coordinator")
            exec_wg = _make_workgroup(session, user, org, "wg-exec", "Executors")
            _make_membership(session, coord_wg, user)
            _make_membership(session, exec_wg, user)
            _make_agent(session, coord_wg, user, "agent-coord", "Coordinator Agent")
            session.commit()

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_creates_job_and_conversation(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = create_engagement_job(
                session,
                agent_id="agent-coord",
                team_name="Executors",
                title="Implement login page",
                scope="HTML/CSS/JS",
            )

        self.assertNotIn("error", result)
        self.assertIsNotNone(result.get("job_id"))
        self.assertIsNotNone(result.get("conversation_id"))
        self.assertEqual(result["title"], "Implement login page")
        self.assertEqual(result["team"], "Executors")

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_job_conversation_has_initial_system_message(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = create_engagement_job(
                session,
                agent_id="agent-coord",
                team_name="Executors",
                title="Deploy service",
                scope="Production deployment",
            )

        with Session(self.engine) as session:
            msgs = session.exec(
                select(Message).where(Message.conversation_id == result["conversation_id"])
            ).all()

        self.assertEqual(len(msgs), 1)
        self.assertIn("[Job created by Coordinator]", msgs[0].content)
        self.assertIn("Deploy service", msgs[0].content)
        self.assertTrue(msgs[0].requires_response)

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_triggers_auto_responses(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            create_engagement_job(
                session,
                agent_id="agent-coord",
                team_name="Executors",
                title="Trigger test",
            )

        mock_auto.assert_called_once()

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_includes_scope_in_system_message(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = create_engagement_job(
                session,
                agent_id="agent-coord",
                team_name="Executors",
                title="Build API",
                scope="REST endpoints for users resource",
            )

        with Session(self.engine) as session:
            msgs = session.exec(
                select(Message).where(Message.conversation_id == result["conversation_id"])
            ).all()

        self.assertTrue(any("REST endpoints" in m.content for m in msgs))

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_links_to_engagement_when_provided(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-1")
            src_wg_row = session.get(Workgroup, "wg-coord")
            tgt_wg_row = session.get(Workgroup, "wg-exec")

            src_conv = Conversation(
                workgroup_id="wg-coord",
                created_by_user_id="u-1",
                kind="engagement",
                topic="engagement:eng-linked",
                name="Linked Eng",
            )
            tgt_conv = Conversation(
                workgroup_id="wg-exec",
                created_by_user_id="u-1",
                kind="engagement",
                topic="engagement:eng-linked",
                name="Linked Eng",
            )
            session.add(src_conv)
            session.add(tgt_conv)
            session.flush()

            eng = Engagement(
                id="eng-linked",
                source_workgroup_id="wg-coord",
                target_workgroup_id="wg-exec",
                proposed_by_user_id="u-1",
                status="in_progress",
                title="Linked Engagement",
                source_conversation_id=src_conv.id,
                target_conversation_id=tgt_conv.id,
            )
            session.add(eng)
            session.commit()

        with Session(self.engine) as session:
            result = create_engagement_job(
                session,
                agent_id="agent-coord",
                team_name="Executors",
                title="Job with engagement",
                engagement_id="eng-linked",
            )

        with Session(self.engine) as session:
            job = session.get(Job, result["job_id"])
        self.assertEqual(job.engagement_id, "eng-linked")

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_returns_error_for_nonexistent_agent(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = create_engagement_job(
                session,
                agent_id="agent-ghost",
                team_name="Executors",
                title="Ghost job",
            )

        self.assertIn("error", result)

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_returns_error_for_nonexistent_team(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = create_engagement_job(
                session,
                agent_id="agent-coord",
                team_name="Nonexistent Team",
                title="Lost job",
            )

        self.assertIn("error", result)
        self.assertIn("not found", result["error"])


# ---------------------------------------------------------------------------
# list_team_jobs tests
# ---------------------------------------------------------------------------

class ListTeamJobsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme Corp")
            _make_workgroup(session, user, org, "wg-exec", "Executors")

            conv_a = Conversation(
                id="conv-job-a",
                workgroup_id="wg-exec",
                created_by_user_id="u-1",
                kind="job",
                topic="Job A",
                name="Job A",
            )
            conv_b = Conversation(
                id="conv-job-b",
                workgroup_id="wg-exec",
                created_by_user_id="u-1",
                kind="job",
                topic="Job B",
                name="Job B",
            )
            session.add(conv_a)
            session.add(conv_b)
            session.flush()

            session.add(Job(
                id="job-a",
                title="Job A",
                scope="Scope A",
                status="pending",
                workgroup_id="wg-exec",
                conversation_id="conv-job-a",
            ))
            session.add(Job(
                id="job-b",
                title="Job B",
                scope="Scope B",
                status="completed",
                workgroup_id="wg-exec",
                conversation_id="conv-job-b",
            ))
            session.commit()

    def test_returns_all_jobs_for_team(self) -> None:
        with Session(self.engine) as session:
            result = list_team_jobs(session, "org-1", "Executors")

        self.assertNotIn("error", result)
        self.assertEqual(result["team"], "Executors")
        self.assertEqual(len(result["jobs"]), 2)

    def test_filters_by_status(self) -> None:
        with Session(self.engine) as session:
            result = list_team_jobs(session, "org-1", "Executors", status_filter="pending")

        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["jobs"][0]["id"], "job-a")

    def test_filter_by_completed_status(self) -> None:
        with Session(self.engine) as session:
            result = list_team_jobs(session, "org-1", "Executors", status_filter="completed")

        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["jobs"][0]["id"], "job-b")

    def test_filter_returns_empty_list_when_no_match(self) -> None:
        with Session(self.engine) as session:
            result = list_team_jobs(session, "org-1", "Executors", status_filter="cancelled")

        self.assertEqual(result["jobs"], [])

    def test_returns_error_for_nonexistent_team(self) -> None:
        with Session(self.engine) as session:
            result = list_team_jobs(session, "org-1", "Ghost Team")

        self.assertIn("error", result)

    def test_job_entries_contain_expected_fields(self) -> None:
        with Session(self.engine) as session:
            result = list_team_jobs(session, "org-1", "Executors")

        job_entry = result["jobs"][0]
        self.assertIn("id", job_entry)
        self.assertIn("title", job_entry)
        self.assertIn("status", job_entry)
        self.assertIn("engagement_id", job_entry)
        self.assertIn("created_at", job_entry)


# ---------------------------------------------------------------------------
# read_job_status tests
# ---------------------------------------------------------------------------

class ReadJobStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme Corp")
            _make_workgroup(session, user, org, "wg-exec", "Executors")

            conv = Conversation(
                id="conv-job-1",
                workgroup_id="wg-exec",
                created_by_user_id="u-1",
                kind="job",
                topic="Design homepage",
                name="Design homepage",
            )
            session.add(conv)
            session.flush()

            session.add(Job(
                id="job-1",
                title="Design homepage",
                scope="Responsive layout",
                status="in_progress",
                workgroup_id="wg-exec",
                conversation_id="conv-job-1",
            ))
            session.add(Message(
                conversation_id="conv-job-1",
                sender_type="system",
                content="[Job created by Coordinator] Design homepage",
                requires_response=True,
            ))
            session.add(Message(
                conversation_id="conv-job-1",
                sender_type="agent",
                content="I'll get started on that right away.",
                requires_response=False,
            ))
            session.commit()

    def test_returns_job_details(self) -> None:
        with Session(self.engine) as session:
            result = read_job_status(session, "job-1")

        self.assertNotIn("error", result)
        self.assertEqual(result["id"], "job-1")
        self.assertEqual(result["title"], "Design homepage")
        self.assertEqual(result["scope"], "Responsive layout")
        self.assertEqual(result["status"], "in_progress")

    def test_returns_messages_from_conversation(self) -> None:
        with Session(self.engine) as session:
            result = read_job_status(session, "job-1")

        self.assertIn("messages", result)
        self.assertEqual(len(result["messages"]), 2)

    def test_message_limit_is_respected(self) -> None:
        with Session(self.engine) as session:
            result = read_job_status(session, "job-1", message_limit=1)

        self.assertEqual(len(result["messages"]), 1)

    def test_message_entries_contain_expected_fields(self) -> None:
        with Session(self.engine) as session:
            result = read_job_status(session, "job-1")

        msg_entry = result["messages"][0]
        self.assertIn("sender_type", msg_entry)
        self.assertIn("content", msg_entry)
        self.assertIn("created_at", msg_entry)

    def test_content_is_truncated_at_500_chars(self) -> None:
        long_content = "x" * 600
        with Session(self.engine) as session:
            session.add(Message(
                conversation_id="conv-job-1",
                sender_type="agent",
                content=long_content,
                requires_response=False,
            ))
            session.commit()

        with Session(self.engine) as session:
            result = read_job_status(session, "job-1", message_limit=10)

        long_msgs = [
            m for m in result["messages"]
            if len(m["content"]) <= 500 and m["sender_type"] == "agent"
        ]
        # All messages must have content length <= 500
        for m in result["messages"]:
            self.assertLessEqual(len(m["content"]), 500)

    def test_returns_error_for_nonexistent_job(self) -> None:
        with Session(self.engine) as session:
            result = read_job_status(session, "job-ghost")

        self.assertIn("error", result)

    def test_includes_engagement_id_when_linked(self) -> None:
        with Session(self.engine) as session:
            user = session.get(User, "u-1")

            src_conv = Conversation(
                workgroup_id="wg-exec",
                created_by_user_id="u-1",
                kind="engagement",
                topic="engagement:eng-x",
                name="Eng X",
            )
            tgt_conv = Conversation(
                workgroup_id="wg-exec",
                created_by_user_id="u-1",
                kind="engagement",
                topic="engagement:eng-x",
                name="Eng X",
            )
            session.add(src_conv)
            session.add(tgt_conv)
            session.flush()

            eng = Engagement(
                id="eng-x",
                source_workgroup_id="wg-exec",
                target_workgroup_id="wg-exec",
                proposed_by_user_id="u-1",
                status="in_progress",
                title="X Project",
                source_conversation_id=src_conv.id,
                target_conversation_id=tgt_conv.id,
            )
            session.add(eng)
            session.flush()

            job_conv = Conversation(
                id="conv-job-linked",
                workgroup_id="wg-exec",
                created_by_user_id="u-1",
                kind="job",
                topic="Linked job",
                name="Linked job",
            )
            session.add(job_conv)
            session.flush()

            session.add(Job(
                id="job-linked",
                title="Linked job",
                status="pending",
                workgroup_id="wg-exec",
                conversation_id="conv-job-linked",
                engagement_id="eng-x",
            ))
            session.commit()

        with Session(self.engine) as session:
            result = read_job_status(session, "job-linked")

        self.assertEqual(result["engagement_id"], "eng-x")


# ---------------------------------------------------------------------------
# post_to_job tests
# ---------------------------------------------------------------------------

class PostToJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme Corp")
            coord_wg = _make_workgroup(session, user, org, "wg-coord", "Coordinator")
            exec_wg = _make_workgroup(session, user, org, "wg-exec", "Executors")
            _make_agent(session, coord_wg, user, "agent-coord", "Coordinator Agent")

            conv = Conversation(
                id="conv-job-1",
                workgroup_id="wg-exec",
                created_by_user_id="u-1",
                kind="job",
                topic="Do the thing",
                name="Do the thing",
            )
            session.add(conv)
            session.flush()

            session.add(Job(
                id="job-1",
                title="Do the thing",
                status="in_progress",
                workgroup_id="wg-exec",
                conversation_id="conv-job-1",
            ))
            session.commit()

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_posts_message_to_job_conversation(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = post_to_job(
                session,
                agent_id="agent-coord",
                job_id="job-1",
                message_content="Please prioritize the login flow.",
            )

        self.assertNotIn("error", result)
        self.assertEqual(result["job_id"], "job-1")
        self.assertIsNotNone(result.get("message_id"))
        self.assertTrue(result["posted"])

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_message_content_is_prefixed(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = post_to_job(
                session,
                agent_id="agent-coord",
                job_id="job-1",
                message_content="Urgent update needed.",
            )

        with Session(self.engine) as session:
            msg = session.get(Message, result["message_id"])

        self.assertIn("[Coordinator]", msg.content)
        self.assertIn("Urgent update needed.", msg.content)

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_message_requires_response(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = post_to_job(
                session,
                agent_id="agent-coord",
                job_id="job-1",
                message_content="Status update?",
            )

        with Session(self.engine) as session:
            msg = session.get(Message, result["message_id"])

        self.assertTrue(msg.requires_response)

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_triggers_auto_responses(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            post_to_job(
                session,
                agent_id="agent-coord",
                job_id="job-1",
                message_content="Go.",
            )

        mock_auto.assert_called_once()

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_records_sender_agent_id(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = post_to_job(
                session,
                agent_id="agent-coord",
                job_id="job-1",
                message_content="Hello team.",
            )

        with Session(self.engine) as session:
            msg = session.get(Message, result["message_id"])

        self.assertEqual(msg.sender_agent_id, "agent-coord")

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_returns_error_for_nonexistent_agent(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = post_to_job(
                session,
                agent_id="agent-ghost",
                job_id="job-1",
                message_content="Hello.",
            )

        self.assertIn("error", result)

    @unittest.mock.patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background")
    def test_returns_error_for_nonexistent_job(self, mock_auto: unittest.mock.MagicMock) -> None:
        with Session(self.engine) as session:
            result = post_to_job(
                session,
                agent_id="agent-coord",
                job_id="job-ghost",
                message_content="Hello.",
            )

        self.assertIn("error", result)


# ---------------------------------------------------------------------------
# complete_engagement_by_agent tests
# ---------------------------------------------------------------------------

class CompleteEngagementByAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            src_user = _make_user(session, "u-src")
            tgt_user = _make_user(session, "u-tgt")

            src_org = _make_org(session, src_user, "org-src", "Source Corp")
            tgt_org = _make_org(session, tgt_user, "org-tgt", "Target Corp")

            src_wg = _make_workgroup(session, src_user, src_org, "wg-src", "Source Team")
            tgt_wg = _make_workgroup(session, tgt_user, tgt_org, "wg-tgt", "Target Team")

            _make_membership(session, src_wg, src_user)
            _make_membership(session, tgt_wg, tgt_user)

            _make_agent(session, src_wg, src_user, "agent-src", "Coordinator")

            src_conv = Conversation(
                id="conv-src",
                workgroup_id="wg-src",
                created_by_user_id="u-src",
                kind="engagement",
                topic="engagement:eng-1",
                name="Engagement 1",
            )
            tgt_conv = Conversation(
                id="conv-tgt",
                workgroup_id="wg-tgt",
                created_by_user_id="u-src",
                kind="engagement",
                topic="engagement:eng-1",
                name="Engagement 1",
            )
            session.add(src_conv)
            session.add(tgt_conv)
            session.flush()

            eng = Engagement(
                id="eng-1",
                source_workgroup_id="wg-src",
                target_workgroup_id="wg-tgt",
                proposed_by_user_id="u-src",
                status="in_progress",
                title="Engagement 1",
                source_conversation_id="conv-src",
                target_conversation_id="conv-tgt",
            )
            session.add(eng)
            session.commit()

    def test_transitions_engagement_to_completed(self) -> None:
        with Session(self.engine) as session:
            result = complete_engagement_by_agent(
                session,
                agent_id="agent-src",
                engagement_id="eng-1",
                summary="All deliverables shipped.",
            )
            session.commit()

        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["engagement_id"], "eng-1")

        with Session(self.engine) as session:
            eng = session.get(Engagement, "eng-1")
        self.assertEqual(eng.status, "completed")
        self.assertIsNotNone(eng.completed_at)

    def test_posts_completion_messages_to_both_conversations(self) -> None:
        with Session(self.engine) as session:
            complete_engagement_by_agent(
                session,
                agent_id="agent-src",
                engagement_id="eng-1",
                summary="Work is done.",
            )
            session.commit()

        with Session(self.engine) as session:
            src_msgs = session.exec(
                select(Message).where(Message.conversation_id == "conv-src")
            ).all()
            tgt_msgs = session.exec(
                select(Message).where(Message.conversation_id == "conv-tgt")
            ).all()

        self.assertTrue(any("[Engagement completed]" in m.content for m in src_msgs))
        self.assertTrue(any("[Engagement completed]" in m.content for m in tgt_msgs))

    def test_summary_appears_in_completion_message(self) -> None:
        with Session(self.engine) as session:
            complete_engagement_by_agent(
                session,
                agent_id="agent-src",
                engagement_id="eng-1",
                summary="Delivered all milestones on time.",
            )
            session.commit()

        with Session(self.engine) as session:
            src_msgs = session.exec(
                select(Message).where(Message.conversation_id == "conv-src")
            ).all()

        self.assertTrue(
            any("Delivered all milestones on time." in m.content for m in src_msgs)
        )

    def test_uses_default_summary_when_none_provided(self) -> None:
        with Session(self.engine) as session:
            complete_engagement_by_agent(
                session,
                agent_id="agent-src",
                engagement_id="eng-1",
            )
            session.commit()

        with Session(self.engine) as session:
            src_msgs = session.exec(
                select(Message).where(Message.conversation_id == "conv-src")
            ).all()

        self.assertTrue(
            any("marked as completed" in m.content for m in src_msgs)
        )

    def test_cannot_complete_proposed_engagement(self) -> None:
        with Session(self.engine) as session:
            eng = session.get(Engagement, "eng-1")
            eng.status = "proposed"
            session.add(eng)
            session.commit()

        with Session(self.engine) as session:
            result = complete_engagement_by_agent(
                session,
                agent_id="agent-src",
                engagement_id="eng-1",
            )

        self.assertIn("error", result)
        self.assertIn("proposed", result["error"])

    def test_cannot_complete_already_completed_engagement(self) -> None:
        with Session(self.engine) as session:
            eng = session.get(Engagement, "eng-1")
            eng.status = "completed"
            session.add(eng)
            session.commit()

        with Session(self.engine) as session:
            result = complete_engagement_by_agent(
                session,
                agent_id="agent-src",
                engagement_id="eng-1",
            )

        self.assertIn("error", result)

    def test_returns_error_for_nonexistent_agent(self) -> None:
        with Session(self.engine) as session:
            result = complete_engagement_by_agent(
                session,
                agent_id="agent-ghost",
                engagement_id="eng-1",
            )

        self.assertIn("error", result)

    def test_returns_error_for_nonexistent_engagement(self) -> None:
        with Session(self.engine) as session:
            result = complete_engagement_by_agent(
                session,
                agent_id="agent-src",
                engagement_id="eng-ghost",
            )

        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
