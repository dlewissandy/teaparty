"""Tests for agent tasks: model, router endpoints, and file scoping."""

import unittest
from unittest.mock import MagicMock

from fastapi import BackgroundTasks, HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from teaparty_app.models import (
    Agent,
    AgentTask,
    Conversation,
    ConversationParticipant,
    Membership,
    Message,
    User,
    Workgroup,
)
from teaparty_app.routers.agent_tasks import (
    create_agent_task,
    delete_agent_task,
    list_agent_tasks,
    list_workgroup_agent_tasks,
    update_agent_task,
)
from teaparty_app.schemas import AgentTaskCreateRequest, AgentTaskUpdateRequest
from teaparty_app.services.file_helpers import _topic_id_for_conversation


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _seed(session: Session, *, admin: bool = False) -> tuple[User, Workgroup, Agent]:
    user = User(id="user-1", email="owner@example.com", name="Owner")
    workgroup = Workgroup(id="wg-1", name="Core", owner_id=user.id, files=[])
    membership = Membership(workgroup_id=workgroup.id, user_id=user.id, role="owner")
    agent = Agent(
        id="agent-1",
        workgroup_id=workgroup.id,
        created_by_user_id=user.id,
        name="Helper",
        description="__system_admin_agent__" if admin else "A helpful agent",
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


def _add_second_agent(session: Session) -> Agent:
    agent2 = Agent(
        id="agent-2",
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name="Other",
        description="Other agent",
    )
    session.add(agent2)
    session.flush()
    return agent2


def _insert_task(session: Session, task_id: str, agent_id: str, title: str) -> AgentTask:
    conv = Conversation(
        id=f"conv-{task_id}",
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        kind="task",
        topic=f"task:{agent_id}:{task_id}",
        name=title,
    )
    session.add(conv)
    session.flush()
    task = AgentTask(
        id=task_id,
        title=title,
        agent_id=agent_id,
        workgroup_id="wg-1",
        conversation_id=conv.id,
        created_by_user_id="user-1",
    )
    session.add(task)
    return task


class CreateAgentTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_creates_task_with_conversation_and_participants(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        bg = BackgroundTasks()
        with Session(self.engine) as session:
            result = create_agent_task(
                workgroup_id="wg-1",
                agent_id="agent-1",
                payload=AgentTaskCreateRequest(title="Fix bug", description="It is broken"),
                background_tasks=bg,
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.title, "Fix bug")
        self.assertEqual(result.description, "It is broken")
        self.assertEqual(result.status, "in_progress")
        self.assertEqual(result.agent_id, "agent-1")
        self.assertEqual(result.workgroup_id, "wg-1")
        self.assertEqual(result.created_by_user_id, "user-1")
        self.assertIsNotNone(result.conversation_id)

        with Session(self.engine) as session:
            conv = session.get(Conversation, result.conversation_id)
            self.assertIsNotNone(conv)
            self.assertEqual(conv.kind, "task")
            self.assertEqual(conv.name, "Fix bug")
            self.assertTrue(conv.topic.startswith("task:agent-1:"))

            participants = session.exec(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conv.id
                )
            ).all()
            user_ids = {p.user_id for p in participants if p.user_id}
            agent_ids = {p.agent_id for p in participants if p.agent_id}
            self.assertIn("user-1", user_ids)
            self.assertIn("agent-1", agent_ids)

    def test_posts_initial_message_with_title_and_description(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        bg = BackgroundTasks()
        with Session(self.engine) as session:
            result = create_agent_task(
                workgroup_id="wg-1",
                agent_id="agent-1",
                payload=AgentTaskCreateRequest(title="Fix bug", description="It is broken"),
                background_tasks=bg,
                session=session,
                user=session.get(User, "user-1"),
            )

        with Session(self.engine) as session:
            messages = session.exec(
                select(Message).where(Message.conversation_id == result.conversation_id)
            ).all()
            self.assertEqual(len(messages), 1)
            msg = messages[0]
            self.assertEqual(msg.sender_type, "user")
            self.assertEqual(msg.sender_user_id, "user-1")
            self.assertEqual(msg.content, "Fix bug\n\nIt is broken")
            self.assertTrue(msg.requires_response)

    def test_posts_initial_message_title_only_when_no_description(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        bg = BackgroundTasks()
        with Session(self.engine) as session:
            result = create_agent_task(
                workgroup_id="wg-1",
                agent_id="agent-1",
                payload=AgentTaskCreateRequest(title="Do something"),
                background_tasks=bg,
                session=session,
                user=session.get(User, "user-1"),
            )

        with Session(self.engine) as session:
            messages = session.exec(
                select(Message).where(Message.conversation_id == result.conversation_id)
            ).all()
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].content, "Do something")

    def test_schedules_auto_response_background_task(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        bg = MagicMock(spec=BackgroundTasks)
        with Session(self.engine) as session:
            result = create_agent_task(
                workgroup_id="wg-1",
                agent_id="agent-1",
                payload=AgentTaskCreateRequest(title="Fix bug", description="broken"),
                background_tasks=bg,
                session=session,
                user=session.get(User, "user-1"),
            )

        bg.add_task.assert_called_once()
        args = bg.add_task.call_args
        from teaparty_app.routers.conversations import _process_auto_responses_in_background
        self.assertEqual(args[0][0], _process_auto_responses_in_background)
        self.assertEqual(args[0][1], result.conversation_id)

    def test_admin_agent_blocked(self) -> None:
        with Session(self.engine) as session:
            _seed(session, admin=True)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                create_agent_task(
                    workgroup_id="wg-1",
                    agent_id="agent-1",
                    payload=AgentTaskCreateRequest(title="Test"),
                    background_tasks=BackgroundTasks(),
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 400)

    def test_non_member_blocked(self) -> None:
        with Session(self.engine) as session:
            _seed(session)
            _seed_non_member(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                create_agent_task(
                    workgroup_id="wg-1",
                    agent_id="agent-1",
                    payload=AgentTaskCreateRequest(title="Test"),
                    background_tasks=BackgroundTasks(),
                    session=session,
                    user=session.get(User, "user-2"),
                )
            self.assertEqual(ctx.exception.status_code, 403)

    def test_agent_not_found_404(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                create_agent_task(
                    workgroup_id="wg-1",
                    agent_id="nonexistent",
                    payload=AgentTaskCreateRequest(title="No agent"),
                    background_tasks=BackgroundTasks(),
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 404)

    def test_agent_in_wrong_workgroup_404(self) -> None:
        with Session(self.engine) as session:
            _seed(session)
            wg2 = Workgroup(id="wg-2", name="Other", owner_id="user-1", files=[])
            session.add(wg2)
            session.add(Membership(workgroup_id="wg-2", user_id="user-1", role="owner"))
            session.commit()

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                create_agent_task(
                    workgroup_id="wg-2",
                    agent_id="agent-1",
                    payload=AgentTaskCreateRequest(title="Wrong WG"),
                    background_tasks=BackgroundTasks(),
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 404)


class ListAgentTasksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_lists_only_agents_tasks(self) -> None:
        with Session(self.engine) as session:
            _seed(session)
            _add_second_agent(session)
            _insert_task(session, "t1", "agent-1", "Agent 1 task")
            _insert_task(session, "t2", "agent-2", "Agent 2 task")
            session.commit()

        with Session(self.engine) as session:
            result = list_agent_tasks(
                workgroup_id="wg-1",
                agent_id="agent-1",
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Agent 1 task")

    def test_empty_list_when_no_tasks(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        with Session(self.engine) as session:
            result = list_agent_tasks(
                workgroup_id="wg-1",
                agent_id="agent-1",
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result, [])

    def test_agent_not_found_404(self) -> None:
        with Session(self.engine) as session:
            _seed(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                list_agent_tasks(
                    workgroup_id="wg-1",
                    agent_id="nonexistent",
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 404)

    def test_non_member_blocked(self) -> None:
        with Session(self.engine) as session:
            _seed(session)
            _seed_non_member(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                list_agent_tasks(
                    workgroup_id="wg-1",
                    agent_id="agent-1",
                    session=session,
                    user=session.get(User, "user-2"),
                )
            self.assertEqual(ctx.exception.status_code, 403)


class BulkListAgentTasksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_returns_all_tasks_in_workgroup(self) -> None:
        with Session(self.engine) as session:
            _seed(session)
            _add_second_agent(session)
            _insert_task(session, "t0", "agent-1", "Task 0")
            _insert_task(session, "t1", "agent-2", "Task 1")
            session.commit()

        with Session(self.engine) as session:
            result = list_workgroup_agent_tasks(
                workgroup_id="wg-1",
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(len(result), 2)
        titles = {r.title for r in result}
        self.assertEqual(titles, {"Task 0", "Task 1"})

    def test_excludes_tasks_from_other_workgroups(self) -> None:
        with Session(self.engine) as session:
            _seed(session)
            wg2 = Workgroup(id="wg-2", name="Other WG", owner_id="user-1", files=[])
            agent2 = Agent(
                id="agent-2", workgroup_id="wg-2", created_by_user_id="user-1",
                name="Remote", description="",
            )
            session.add(wg2)
            session.add(agent2)
            session.add(Membership(workgroup_id="wg-2", user_id="user-1", role="owner"))
            _insert_task(session, "t0", "agent-1", "WG1 task")
            # Manually add a task in wg-2
            task2 = AgentTask(
                id="t-other", title="WG2 task", agent_id="agent-2",
                workgroup_id="wg-2", created_by_user_id="user-1",
            )
            session.add(task2)
            session.commit()

        with Session(self.engine) as session:
            result = list_workgroup_agent_tasks(
                workgroup_id="wg-1",
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "WG1 task")

    def test_non_member_blocked(self) -> None:
        with Session(self.engine) as session:
            _seed(session)
            _seed_non_member(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                list_workgroup_agent_tasks(
                    workgroup_id="wg-1",
                    session=session,
                    user=session.get(User, "user-2"),
                )
            self.assertEqual(ctx.exception.status_code, 403)


class UpdateAgentTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _seed(session)
            _insert_task(session, "t1", "agent-1", "Fix bug")
            session.commit()

    def test_update_status_to_completed_sets_completed_at(self) -> None:
        with Session(self.engine) as session:
            result = update_agent_task(
                task_id="t1",
                payload=AgentTaskUpdateRequest(status="completed"),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.status, "completed")
        self.assertIsNotNone(result.completed_at)

    def test_update_status_to_cancelled_sets_completed_at(self) -> None:
        with Session(self.engine) as session:
            result = update_agent_task(
                task_id="t1",
                payload=AgentTaskUpdateRequest(status="cancelled"),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.status, "cancelled")
        self.assertIsNotNone(result.completed_at)

    def test_update_title(self) -> None:
        with Session(self.engine) as session:
            result = update_agent_task(
                task_id="t1",
                payload=AgentTaskUpdateRequest(title="New title"),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.title, "New title")

    def test_update_description(self) -> None:
        with Session(self.engine) as session:
            result = update_agent_task(
                task_id="t1",
                payload=AgentTaskUpdateRequest(description="Updated desc"),
                session=session,
                user=session.get(User, "user-1"),
            )

        self.assertEqual(result.description, "Updated desc")

    def test_update_empty_title_rejected(self) -> None:
        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                update_agent_task(
                    task_id="t1",
                    payload=AgentTaskUpdateRequest(title="   "),
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 400)

    def test_update_nonexistent_task_404(self) -> None:
        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                update_agent_task(
                    task_id="nonexistent",
                    payload=AgentTaskUpdateRequest(status="completed"),
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 404)

    def test_update_non_member_blocked(self) -> None:
        with Session(self.engine) as session:
            _seed_non_member(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                update_agent_task(
                    task_id="t1",
                    payload=AgentTaskUpdateRequest(status="completed"),
                    session=session,
                    user=session.get(User, "user-2"),
                )
            self.assertEqual(ctx.exception.status_code, 403)


class DeleteAgentTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _seed(session)
            _insert_task(session, "t1", "agent-1", "Fix bug")
            session.add(Message(
                conversation_id="conv-t1",
                sender_type="user",
                sender_user_id="user-1",
                content="Fix the bug",
            ))
            session.add(ConversationParticipant(conversation_id="conv-t1", user_id="user-1"))
            session.commit()

    def test_deletes_task_conversation_messages_and_participants(self) -> None:
        with Session(self.engine) as session:
            delete_agent_task(
                task_id="t1",
                session=session,
                user=session.get(User, "user-1"),
            )

        with Session(self.engine) as session:
            self.assertIsNone(session.get(AgentTask, "t1"))
            self.assertIsNone(session.get(Conversation, "conv-t1"))
            msgs = session.exec(select(Message).where(Message.conversation_id == "conv-t1")).all()
            self.assertEqual(len(msgs), 0)
            cps = session.exec(select(ConversationParticipant).where(ConversationParticipant.conversation_id == "conv-t1")).all()
            self.assertEqual(len(cps), 0)

    def test_nonexistent_task_404(self) -> None:
        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                delete_agent_task(
                    task_id="nonexistent",
                    session=session,
                    user=session.get(User, "user-1"),
                )
            self.assertEqual(ctx.exception.status_code, 404)

    def test_non_member_blocked(self) -> None:
        with Session(self.engine) as session:
            _seed_non_member(session)

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as ctx:
                delete_agent_task(
                    task_id="t1",
                    session=session,
                    user=session.get(User, "user-2"),
                )
            self.assertEqual(ctx.exception.status_code, 403)


class TaskFileScopingTests(unittest.TestCase):
    def test_task_conversation_returns_conversation_id(self) -> None:
        conv = Conversation(
            id="conv-task-1",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            kind="task",
            topic="task:agent-1:t1",
            name="Fix bug",
        )
        self.assertEqual(_topic_id_for_conversation(conv), "conv-task-1")

    def test_job_conversation_returns_conversation_id(self) -> None:
        conv = Conversation(
            id="conv-job-1",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            kind="job",
            topic="general",
            name="General",
        )
        self.assertEqual(_topic_id_for_conversation(conv), "conv-job-1")

    def test_direct_conversation_with_dma_returns_agent_scope(self) -> None:
        conv = Conversation(
            id="conv-dm-1",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            kind="direct",
            topic="dma:user-1:agent-1",
            name="DM",
        )
        self.assertEqual(_topic_id_for_conversation(conv), "agent:agent-1")

    def test_direct_conversation_with_dm_returns_topic(self) -> None:
        conv = Conversation(
            id="conv-dm-2",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            kind="direct",
            topic="dm:user-1:user-2",
            name="DM",
        )
        self.assertEqual(_topic_id_for_conversation(conv), "dm:user-1:user-2")

    def test_other_kind_returns_empty(self) -> None:
        conv = Conversation(
            id="conv-other",
            workgroup_id="wg-1",
            created_by_user_id="user-1",
            kind="other",
            topic="something",
        )
        self.assertEqual(_topic_id_for_conversation(conv), "")


if __name__ == "__main__":
    unittest.main()
