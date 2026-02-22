import unittest

from sqlmodel import SQLModel, Session, create_engine

from teaparty_app.models import Agent, Membership, User, Workgroup
from teaparty_app.services.activity import ensure_activity_conversation
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
        prompt="Friendly assistant created for testing",
        model="sonnet",
        tools=["Read", "Write"],
        image="robot",
        permission_mode="acceptEdits",
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
        self.assertEqual(result.prompt, "Friendly assistant created for testing")
        self.assertEqual(result.model, "sonnet")
        self.assertEqual(result.image, "robot")
        self.assertEqual(result.permission_mode, "acceptEdits")
        self.assertIn("Read", result.tools)
        self.assertIn("Write", result.tools)


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