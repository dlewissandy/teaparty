import unittest

from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine, select

from teaparty_app.models import Agent, Membership, Organization, User, Workgroup
from teaparty_app.services.activity import ensure_activity_conversation
from teaparty_app.services.admin_workspace import ADMIN_AGENT_SENTINEL
from teaparty_app.services.admin_workspace.bootstrap import (
    ensure_lead_agent,
    is_lead_agent,
    lead_agent_name,
)


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_user(session, user_id="user-1"):
    user = User(id=user_id, email=f"{user_id}@example.com", name="Owner")
    session.add(user)
    return user


def _make_workgroup(session, user, name="Core", wg_id="wg-1", org_id=None):
    workgroup = Workgroup(id=wg_id, name=name, owner_id=user.id, files=[], organization_id=org_id)
    session.add(workgroup)
    session.flush()
    session.add(Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner"))
    ensure_activity_conversation(session, workgroup)
    return workgroup


def _make_agent(session, workgroup, user, name="Helper", agent_id="agent-1", is_lead=False):
    agent = Agent(
        id=agent_id,
        workgroup_id=workgroup.id,
        created_by_user_id=user.id,
        name=name,
        description="",
        role="assistant",
        model="claude-sonnet-4-5",
        tool_names=["Read", "Write"],
        is_lead=is_lead,
    )
    session.add(agent)
    session.flush()
    return agent


class LeadAgentNameTests(unittest.TestCase):
    def test_lead_agent_name(self):
        self.assertEqual(lead_agent_name("Design"), "Design-lead")
        self.assertEqual(lead_agent_name("My Team"), "My Team-lead")


class IsLeadAgentTests(unittest.TestCase):
    def test_is_lead_true(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user)
            agent = _make_agent(session, wg, user, is_lead=True)
            session.commit()
        with Session(engine) as session:
            agent = session.get(Agent, "agent-1")
            self.assertTrue(is_lead_agent(agent))

    def test_is_lead_false_by_default(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user)
            agent = _make_agent(session, wg, user)
            session.commit()
        with Session(engine) as session:
            agent = session.get(Agent, "agent-1")
            self.assertFalse(is_lead_agent(agent))


class IsLeadPersistsTests(unittest.TestCase):
    def test_is_lead_persists_through_sqlite(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user)
            agent = _make_agent(session, wg, user, is_lead=True)
            session.commit()
        with Session(engine) as session:
            reloaded = session.get(Agent, "agent-1")
            self.assertTrue(reloaded.is_lead)

    def test_is_lead_defaults_false(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user)
            agent = Agent(
                id="agent-x",
                workgroup_id=wg.id,
                created_by_user_id=user.id,
                name="NoLead",
            )
            session.add(agent)
            session.commit()
        with Session(engine) as session:
            reloaded = session.get(Agent, "agent-x")
            self.assertFalse(reloaded.is_lead)


class EnsureLeadAgentTests(unittest.TestCase):
    def test_creates_lead_when_missing(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user, name="Design")
            session.commit()
        with Session(engine) as session:
            wg = session.get(Workgroup, "wg-1")
            agent, created = ensure_lead_agent(session, wg)
            session.commit()
            self.assertTrue(created)
            self.assertEqual(agent.name, "Design-lead")
            self.assertTrue(agent.is_lead)
            self.assertEqual(agent.role, "Team lead")

    def test_idempotent(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user, name="Design")
            session.commit()
        with Session(engine) as session:
            wg = session.get(Workgroup, "wg-1")
            agent1, created1 = ensure_lead_agent(session, wg)
            agent1_id = agent1.id
            session.commit()
        with Session(engine) as session:
            wg = session.get(Workgroup, "wg-1")
            agent2, created2 = ensure_lead_agent(session, wg)
            session.commit()
            self.assertFalse(created2)
            self.assertEqual(agent1_id, agent2.id)

    def test_renames_on_workgroup_name_change(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user, name="Design")
            session.commit()
        with Session(engine) as session:
            wg = session.get(Workgroup, "wg-1")
            agent, _ = ensure_lead_agent(session, wg)
            session.commit()
            lead_id = agent.id
        with Session(engine) as session:
            wg = session.get(Workgroup, "wg-1")
            wg.name = "Creative"
            session.add(wg)
            session.flush()
            agent, created = ensure_lead_agent(session, wg)
            session.commit()
            self.assertFalse(created)
            self.assertEqual(agent.id, lead_id)
            self.assertEqual(agent.name, "Design-lead")  # name is not auto-renamed

    def test_does_not_create_second_lead(self):
        """If a lead already exists, ensure_lead_agent returns it."""
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user, name="Ops")
            _make_agent(session, wg, user, name="custom-lead", agent_id="custom-1", is_lead=True)
            session.commit()
        with Session(engine) as session:
            wg = session.get(Workgroup, "wg-1")
            agent, created = ensure_lead_agent(session, wg)
            session.commit()
            self.assertFalse(created)
            self.assertEqual(agent.id, "custom-1")


class SelectLeadTests(unittest.TestCase):
    def test_select_lead_picks_is_lead(self):
        from teaparty_app.services.agent_runtime import _select_lead

        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user)
            first = _make_agent(session, wg, user, name="First", agent_id="a1")
            second = _make_agent(session, wg, user, name="Second", agent_id="a2", is_lead=True)
            session.commit()

        with Session(engine) as session:
            candidates = session.exec(
                select(Agent).where(Agent.workgroup_id == "wg-1").order_by(Agent.created_at.asc())
            ).all()
            lead = _select_lead(candidates)
            self.assertEqual(lead.id, "a2")

    def test_select_lead_falls_back_to_first(self):
        from teaparty_app.services.agent_runtime import _select_lead

        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user)
            _make_agent(session, wg, user, name="First", agent_id="a1")
            _make_agent(session, wg, user, name="Second", agent_id="a2")
            session.commit()

        with Session(engine) as session:
            candidates = session.exec(
                select(Agent).where(Agent.workgroup_id == "wg-1").order_by(Agent.created_at.asc())
            ).all()
            lead = _select_lead(candidates)
            self.assertEqual(lead.id, "a1")


class DeleteProtectionTests(unittest.TestCase):
    def test_cannot_clone_lead_agent(self):
        from teaparty_app.routers.workgroups import clone_agent
        from teaparty_app.schemas import AgentCloneRequest

        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user)
            _make_agent(session, wg, user, name="Core-lead", agent_id="lead-1", is_lead=True)
            session.commit()

        with Session(engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                clone_agent(
                    workgroup_id="wg-1",
                    agent_id="lead-1",
                    payload=AgentCloneRequest(),
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("lead", ctx.exception.detail.lower())

    def test_cannot_rename_lead_agent(self):
        from teaparty_app.routers.workgroups import update_agent
        from teaparty_app.schemas import AgentUpdateRequest

        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user)
            _make_agent(session, wg, user, name="Core-lead", agent_id="lead-1", is_lead=True)
            session.commit()

        with Session(engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                update_agent(
                    workgroup_id="wg-1",
                    agent_id="lead-1",
                    payload=AgentUpdateRequest(name="NewName"),
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("rename", ctx.exception.detail.lower())

    def test_can_update_lead_agent_other_fields(self):
        from teaparty_app.routers.workgroups import update_agent
        from teaparty_app.schemas import AgentUpdateRequest

        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user)
            _make_agent(session, wg, user, name="Core-lead", agent_id="lead-1", is_lead=True)
            session.commit()

        with Session(engine) as session:
            result = update_agent(
                workgroup_id="wg-1",
                agent_id="lead-1",
                payload=AgentUpdateRequest(role="New role", personality="Chill"),
                session=session,
                user=session.get(User, "user-1"),
            )
            self.assertEqual(result.role, "New role")
            self.assertEqual(result.personality, "Chill")
            self.assertEqual(result.name, "Core-lead")


class AdminToolRemoveMemberLeadProtectionTests(unittest.TestCase):
    def test_admin_tool_blocks_lead_removal(self):
        from teaparty_app.services.admin_workspace.tools import admin_tool_remove_member

        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user)
            lead = _make_agent(session, wg, user, name="Core-lead", agent_id="lead-1", is_lead=True)
            session.commit()

        with Session(engine) as session:
            result = admin_tool_remove_member(
                session=session,
                workgroup_id="wg-1",
                requester_user_id="user-1",
                member_selector="Core-lead",
            )
            self.assertIn("lead", result.lower())
