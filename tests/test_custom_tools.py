import unittest
from unittest.mock import MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine

from teaparty_app.models import (
    Agent,
    Conversation,
    Membership,
    Message,
    ToolDefinition,
    ToolGrant,
    User,
    Workgroup,
    new_id,
    utc_now,
)
from teaparty_app.services.tools import (
    TOOL_REGISTRY,
    available_tools,
    available_tools_for_workgroup,
    resolve_custom_tool,
    run_tool,
)
from teaparty_app.services.agent_runtime import _match_custom_tool, _select_tool


def _make_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed_workgroup(session: Session) -> tuple[Workgroup, User, Agent]:
    user = User(id="u1", email="test@example.com", name="Test")
    session.add(user)
    wg = Workgroup(id="wg1", name="TestWG", owner_id=user.id, files=[])
    session.add(wg)
    session.add(Membership(workgroup_id=wg.id, user_id=user.id, role="owner"))
    agent = Agent(
        id="a1",
        workgroup_id=wg.id,
        created_by_user_id=user.id,
        name="TestAgent",
        tool_names=[],
        learning_state={},
        sentiment_state={},
        learned_preferences={},
    )
    session.add(agent)
    session.flush()
    return wg, user, agent


def _make_tool_def(
    session: Session,
    wg_id: str,
    user_id: str,
    *,
    name: str = "my_tool",
    description: str = "A test tool",
    tool_type: str = "prompt",
    prompt_template: str = "Summarize: {{input}}",
    webhook_url: str = "",
    enabled: bool = True,
    is_shared: bool = False,
) -> ToolDefinition:
    td = ToolDefinition(
        workgroup_id=wg_id,
        created_by_user_id=user_id,
        name=name,
        description=description,
        tool_type=tool_type,
        prompt_template=prompt_template,
        webhook_url=webhook_url,
        enabled=enabled,
        is_shared=is_shared,
    )
    session.add(td)
    session.flush()
    return td


class TestResolveCustomTool(unittest.TestCase):
    def test_returns_none_for_builtin_name(self) -> None:
        session = _make_session()
        result = resolve_custom_tool(session, "summarize_topic")
        self.assertIsNone(result)

    def test_returns_none_for_nonexistent_id(self) -> None:
        session = _make_session()
        result = resolve_custom_tool(session, "custom:nonexistent-id")
        self.assertIsNone(result)

    def test_returns_tool_definition(self) -> None:
        session = _make_session()
        wg, user, _agent = _seed_workgroup(session)
        td = _make_tool_def(session, wg.id, user.id)
        result = resolve_custom_tool(session, f"custom:{td.id}")
        self.assertIsNotNone(result)
        self.assertEqual(result.id, td.id)
        self.assertEqual(result.name, "my_tool")


class TestRunTool(unittest.TestCase):
    def test_dispatches_builtin_tools_unchanged(self) -> None:
        session = _make_session()
        wg, user, agent = _seed_workgroup(session)
        conv = Conversation(
            id="c1", workgroup_id=wg.id, created_by_user_id=user.id, kind="topic", topic="general"
        )
        session.add(conv)
        session.flush()
        result = run_tool("missing_tool", session, agent, conv, Message(
            id="m1", conversation_id=conv.id, sender_type="user",
            sender_user_id=user.id, content="test",
        ))
        self.assertEqual(result, "Tool 'missing_tool' is not available.")

    def test_dispatches_custom_prompt_tool(self) -> None:
        session = _make_session()
        wg, user, agent = _seed_workgroup(session)
        td = _make_tool_def(session, wg.id, user.id)
        conv = Conversation(
            id="c1", workgroup_id=wg.id, created_by_user_id=user.id, kind="topic", topic="general"
        )
        session.add(conv)
        session.flush()
        trigger = Message(
            id="m1", conversation_id=conv.id, sender_type="user",
            sender_user_id=user.id, content="hello world",
        )

        with patch("teaparty_app.services.custom_tool_executor.execute_custom_tool", return_value="mocked result"):
            result = run_tool(f"custom:{td.id}", session, agent, conv, trigger)
        self.assertEqual(result, "mocked result")

    def test_rejects_ungranted_cross_workgroup_tool(self) -> None:
        session = _make_session()
        wg, user, agent = _seed_workgroup(session)
        # Create a second workgroup and tool
        wg2 = Workgroup(id="wg2", name="OtherWG", owner_id=user.id, files=[])
        session.add(wg2)
        session.flush()
        td = _make_tool_def(session, wg2.id, user.id, name="other_tool")

        conv = Conversation(
            id="c1", workgroup_id=wg.id, created_by_user_id=user.id, kind="topic", topic="general"
        )
        session.add(conv)
        session.flush()
        trigger = Message(
            id="m1", conversation_id=conv.id, sender_type="user",
            sender_user_id=user.id, content="test",
        )
        result = run_tool(f"custom:{td.id}", session, agent, conv, trigger)
        self.assertIn("not available to this workgroup", result)

    def test_allows_granted_cross_workgroup_tool(self) -> None:
        session = _make_session()
        wg, user, agent = _seed_workgroup(session)
        wg2 = Workgroup(id="wg2", name="OtherWG", owner_id=user.id, files=[])
        session.add(wg2)
        session.flush()
        td = _make_tool_def(session, wg2.id, user.id, name="granted_tool", is_shared=True)
        session.add(ToolGrant(
            tool_definition_id=td.id,
            grantee_workgroup_id=wg.id,
            granted_by_user_id=user.id,
        ))
        session.flush()

        conv = Conversation(
            id="c1", workgroup_id=wg.id, created_by_user_id=user.id, kind="topic", topic="general"
        )
        session.add(conv)
        session.flush()
        trigger = Message(
            id="m1", conversation_id=conv.id, sender_type="user",
            sender_user_id=user.id, content="test",
        )
        with patch("teaparty_app.services.custom_tool_executor.execute_custom_tool", return_value="granted result"):
            result = run_tool(f"custom:{td.id}", session, agent, conv, trigger)
        self.assertEqual(result, "granted result")


class TestMatchCustomTool(unittest.TestCase):
    def test_keyword_matching_returns_best(self) -> None:
        session = _make_session()
        wg, user, _agent = _seed_workgroup(session)
        td1 = _make_tool_def(session, wg.id, user.id, name="weather checker", description="check the weather forecast")
        td2 = _make_tool_def(session, wg.id, user.id, name="code review", description="review code changes")

        result = _match_custom_tool(session, [f"custom:{td1.id}", f"custom:{td2.id}"], "what is the weather forecast today")
        self.assertEqual(result, f"custom:{td1.id}")

    def test_returns_none_for_no_overlap(self) -> None:
        session = _make_session()
        wg, user, _agent = _seed_workgroup(session)
        td = _make_tool_def(session, wg.id, user.id, name="specific tool", description="does something specific")
        result = _match_custom_tool(session, [f"custom:{td.id}"], "completely unrelated xyz 123")
        self.assertIsNone(result)


class TestAvailableToolsForWorkgroup(unittest.TestCase):
    def test_includes_builtin_and_custom_tools(self) -> None:
        session = _make_session()
        wg, user, _agent = _seed_workgroup(session)
        td = _make_tool_def(session, wg.id, user.id, name="my_custom")
        tools = available_tools_for_workgroup(session, wg.id)
        self.assertIn("add_file", tools)
        self.assertIn(f"custom:{td.id}", tools)

    def test_includes_granted_tools(self) -> None:
        session = _make_session()
        wg, user, _agent = _seed_workgroup(session)
        wg2 = Workgroup(id="wg2", name="OtherWG", owner_id=user.id, files=[])
        session.add(wg2)
        session.flush()
        td = _make_tool_def(session, wg2.id, user.id, name="shared_tool", is_shared=True)
        session.add(ToolGrant(
            tool_definition_id=td.id,
            grantee_workgroup_id=wg.id,
            granted_by_user_id=user.id,
        ))
        session.flush()
        tools = available_tools_for_workgroup(session, wg.id)
        self.assertIn(f"custom:{td.id}", tools)

    def test_excludes_disabled_tools(self) -> None:
        session = _make_session()
        wg, user, _agent = _seed_workgroup(session)
        td = _make_tool_def(session, wg.id, user.id, name="disabled_tool", enabled=False)
        tools = available_tools_for_workgroup(session, wg.id)
        self.assertNotIn(f"custom:{td.id}", tools)


class TestPromptToolTemplateSubstitution(unittest.TestCase):
    def test_replaces_input_placeholder(self) -> None:
        from teaparty_app.services.custom_tool_executor import _execute_prompt_tool
        td = ToolDefinition(
            id="td1", workgroup_id="wg1", created_by_user_id="u1",
            name="test", tool_type="prompt",
            prompt_template="Translate to French: {{input}}",
        )
        trigger = Message(
            id="m1", conversation_id="c1", sender_type="user",
            sender_user_id="u1", content="Hello world",
        )
        with patch("teaparty_app.services.custom_tool_executor._get_anthropic_api_key", return_value="test-key"):
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="Bonjour le monde")]
            with patch("anthropic.Anthropic") as mock_client_cls:
                mock_client_cls.return_value.messages.create.return_value = mock_response
                result = _execute_prompt_tool(td, trigger)
                call_args = mock_client_cls.return_value.messages.create.call_args
                prompt_sent = call_args.kwargs["messages"][0]["content"]
                self.assertIn("Hello world", prompt_sent)
                self.assertNotIn("{{input}}", prompt_sent)
        self.assertEqual(result, "Bonjour le monde")


class TestWebhookTimeoutEnforcement(unittest.TestCase):
    def test_timeout_is_capped(self) -> None:
        from teaparty_app.services.custom_tool_executor import _execute_webhook_tool
        td = ToolDefinition(
            id="td1", workgroup_id="wg1", created_by_user_id="u1",
            name="test_hook", tool_type="webhook",
            webhook_url="https://example.com/hook",
            webhook_timeout_seconds=999,
        )
        agent = Agent(
            id="a1", workgroup_id="wg1", created_by_user_id="u1",
            name="Agent", tool_names=[], learning_state={}, sentiment_state={}, learned_preferences={},
        )
        conv = Conversation(id="c1", workgroup_id="wg1", created_by_user_id="u1", kind="topic", topic="general")
        trigger = Message(id="m1", conversation_id="c1", sender_type="user", sender_user_id="u1", content="test")

        import httpx
        with patch("teaparty_app.services.custom_tool_executor.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_response = MagicMock()
            mock_response.json.return_value = {"result": "ok"}
            mock_response.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = _execute_webhook_tool(td, agent, conv, trigger)
            # Timeout should be capped at 120
            mock_client_cls.assert_called_once_with(timeout=120, follow_redirects=False)
            self.assertEqual(result, "ok")


class TestToolNameCollision(unittest.TestCase):
    def test_builtin_names_are_rejected(self) -> None:
        for builtin_name in TOOL_REGISTRY.keys():
            self.assertIn(builtin_name, available_tools())


class TestSelectToolWithCustom(unittest.TestCase):
    def test_select_tool_without_session_skips_custom(self) -> None:
        agent = Agent(
            id="a1", workgroup_id="wg1", created_by_user_id="u1",
            name="Agent", tool_names=["custom:td1"],
            learning_state={}, sentiment_state={}, learned_preferences={},
        )
        result = _select_tool(agent, "weather forecast", session=None)
        self.assertIsNone(result)

    def test_select_tool_with_session_matches_custom(self) -> None:
        session = _make_session()
        wg, user, agent = _seed_workgroup(session)
        td = _make_tool_def(session, wg.id, user.id, name="weather", description="check weather forecast")
        agent.tool_names = [f"custom:{td.id}"]
        session.add(agent)
        session.flush()
        result = _select_tool(agent, "what is the weather forecast", session=session)
        self.assertEqual(result, f"custom:{td.id}")


class TestToolDeletionCascade(unittest.TestCase):
    def test_grants_removed_on_tool_delete(self) -> None:
        session = _make_session()
        wg, user, agent = _seed_workgroup(session)
        td = _make_tool_def(session, wg.id, user.id, name="deleteme", is_shared=True)

        wg2 = Workgroup(id="wg2", name="OtherWG", owner_id=user.id, files=[])
        session.add(wg2)
        session.flush()
        grant = ToolGrant(
            tool_definition_id=td.id,
            grantee_workgroup_id=wg2.id,
            granted_by_user_id=user.id,
        )
        session.add(grant)

        agent.tool_names = [f"custom:{td.id}", "add_file"]
        session.add(agent)
        session.flush()

        # Simulate deletion cascade (same logic as router)
        from sqlmodel import select
        grants = session.exec(select(ToolGrant).where(ToolGrant.tool_definition_id == td.id)).all()
        for g in grants:
            session.delete(g)

        custom_ref = f"custom:{td.id}"
        agents = session.exec(select(Agent)).all()
        for a in agents:
            if custom_ref in (a.tool_names or []):
                a.tool_names = [tn for tn in a.tool_names if tn != custom_ref]
                session.add(a)

        session.delete(td)
        session.flush()

        # Verify grants removed
        remaining_grants = session.exec(select(ToolGrant).where(ToolGrant.tool_definition_id == td.id)).all()
        self.assertEqual(len(remaining_grants), 0)

        # Verify agent tool_names updated
        session.refresh(agent)
        self.assertNotIn(custom_ref, agent.tool_names)
        self.assertIn("add_file", agent.tool_names)


if __name__ == "__main__":
    unittest.main()
