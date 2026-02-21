import unittest

from sqlmodel import SQLModel, Session, create_engine

from teaparty_app.models import Agent, Membership, User, Workgroup
from teaparty_app.services.activity import ensure_activity_conversation
from teaparty_app.services.admin_workspace import ADMIN_AGENT_SENTINEL
from teaparty_app.routers.workgroups import clone_agent
from teaparty_app.schemas import AgentCloneRequest, AgentRead


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
        role="assistant",
        personality="Friendly",
        backstory="Created for testing",
        model="sonnet",
        temperature=0.8,
        tool_names=["Read", "Write"],
        icon="robot",
    )
    session.add(user)
    session.add(workgroup)
    session.add(membership)
    session.add(agent)
    ensure_activity_conversation(session, workgroup)
    session.commit()
    return user, workgroup, agent


class CloneAgentSameWorkgroupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_clone_default_name_gets_copy_suffix(self) -> None:
        with Session(self.engine) as session:
            user, workgroup, agent = _seed(session)

        with Session(self.engine) as session:
            result = clone_agent(
                workgroup_id="wg-1",
                agent_id="agent-1",
                payload=AgentCloneRequest(),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.name, "Helper (copy)")
        self.assertNotEqual(result.id, "agent-1")
        self.assertEqual(result.workgroup_id, "wg-1")

    def test_clone_copies_config_fields(self) -> None:
        with Session(self.engine) as session:
            user, workgroup, agent = _seed(session)

        with Session(self.engine) as session:
            result = clone_agent(
                workgroup_id="wg-1",
                agent_id="agent-1",
                payload=AgentCloneRequest(),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.description, "A helpful agent")
        self.assertEqual(result.role, "assistant")
        self.assertEqual(result.personality, "Friendly")
        self.assertEqual(result.backstory, "Created for testing")
        self.assertEqual(result.model, "sonnet")
        self.assertEqual(result.temperature, 0.8)
        self.assertEqual(result.icon, "robot")
        self.assertIn("Read", result.tool_names)
        self.assertIn("Write", result.tool_names)


class CloneAgentCustomNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_clone_with_custom_name(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        with Session(self.engine) as session:
            result = clone_agent(
                workgroup_id="wg-1",
                agent_id="agent-1",
                payload=AgentCloneRequest(name="My Custom Agent"),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.name, "My Custom Agent")



class CloneAgentAdminBlockedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_cannot_clone_admin_agent(self) -> None:
        with Session(self.engine) as session:
            user = User(id="user-1", email="owner@example.com", name="Owner")
            workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
            membership = Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner")
            admin_agent = Agent(
                id="admin-1",
                workgroup_id=workgroup.id,
                created_by_user_id=user.id,
                name="Admin",
                description=ADMIN_AGENT_SENTINEL,
            )
            session.add(user)
            session.add(workgroup)
            session.add(membership)
            session.add(admin_agent)
            ensure_activity_conversation(session, workgroup)
            session.commit()

        from fastapi import HTTPException

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                clone_agent(
                    workgroup_id="wg-1",
                    agent_id="admin-1",
                    payload=AgentCloneRequest(),
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 400)
