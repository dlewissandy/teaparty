"""Tests for the admin agent team in system Administration workgroups."""

import json
import unittest
import unittest.mock
from pathlib import Path

import yaml
from sqlmodel import SQLModel, Session, create_engine, select

from teaparty_app.models import (
    Agent,
    AgentWorkgroup,
    Conversation,
    ConversationParticipant,
    Membership,
    Message,
    Organization,
    User,
    Workgroup,
)
from teaparty_app.services.admin_workspace.bootstrap import (
    ADMIN_AGENT_SENTINEL,
    ADMIN_TEAM_NAMES,
    ADMIN_TOOL_ADD_AGENT,
    ADMIN_TOOL_LIST_FILES,
    ADMIN_TOOL_LIST_MEMBERS,
    ADMIN_TOOL_NAMES,
    GLOBAL_TOOL_NAMES,
    _ADMIN_TEAM_LEAD_NAME,
    ensure_admin_workspace,
    find_admin_agent,
    find_admin_agents,
    is_admin_agent,
)
from teaparty_app.services.org_defaults import create_system_workgroups, load_org_defaults


_SYSTEM_ADMIN_YAML = Path(__file__).resolve().parent.parent / "teaparty_app" / "seeds" / "defaults" / "system-administration.yaml"


def _load_system_admin_specs():
    """Load agent specs from the system-administration.yaml seed."""
    with open(_SYSTEM_ADMIN_YAML) as fh:
        return (yaml.safe_load(fh) or {}).get("agents", [])


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_user(session, user_id="user-1"):
    user = User(id=user_id, email=f"{user_id}@test.com", name="Owner")
    session.add(user)
    session.flush()
    return user


def _make_org(session, user, org_id="org-1"):
    org = Organization(id=org_id, name="TestOrg", owner_id=user.id)
    session.add(org)
    session.flush()
    return org


def _make_workgroup(session, user, org=None, wg_id="wg-1", name="Administration"):
    wg = Workgroup(
        id=wg_id, name=name, owner_id=user.id,
        files=[],
        organization_id=org.id if org else None,
    )
    session.add(wg)
    session.flush()
    session.add(Membership(workgroup_id=wg.id, user_id=user.id, role="owner"))
    session.flush()
    return wg


def _make_system_admin_wg(session, user):
    """Create a system Administration workgroup and seed the full admin team."""
    wg = _make_workgroup(session, user, org=None, name="Administration")
    ensure_admin_workspace(session, wg)
    session.flush()
    return wg


class OrgDefaultsCreationTests(unittest.TestCase):
    """Test that create_system_workgroups creates workgroups from YAML (no Administration)."""

    def setUp(self):
        self.engine = _make_engine()

    def test_creates_two_workgroups(self):
        with Session(self.engine) as session:
            user = _make_user(session)
            org = _make_org(session, user)

            created = create_system_workgroups(session, org, user)
            session.flush()

            self.assertEqual(set(created.keys()), {"Project Management", "Engagement"})

    def test_lead_agents_in_each_workgroup(self):
        with Session(self.engine) as session:
            user = _make_user(session)
            org = _make_org(session, user)

            created = create_system_workgroups(session, org, user)
            session.flush()

            for wg_name, wg in created.items():
                leads = session.exec(
                    select(Agent)
                    .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
                    .where(
                        AgentWorkgroup.workgroup_id == wg.id,
                        AgentWorkgroup.is_lead == True,
                    )
                ).all()
                self.assertEqual(len(leads), 1, f"{wg_name} should have exactly 1 lead agent")


class AdminTeamCreationTests(unittest.TestCase):
    """Test ensure_admin_workspace behaviour for system Administration workgroup."""

    def setUp(self):
        self.engine = _make_engine()

    def test_system_admin_creates_full_team(self):
        """System Administration workgroup gets the full admin team from seed."""
        with Session(self.engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user, org=None, name="Administration")

            lead, conv, changed = ensure_admin_workspace(session, wg)
            session.flush()

            self.assertTrue(changed)
            agents = find_admin_agents(session, wg.id)
            self.assertEqual(len(agents), 5)
            self.assertEqual(lead.name, "administration-lead")


class AdminTeamIdempotencyTests(unittest.TestCase):
    """Test that running ensure_admin_workspace twice is idempotent."""

    def setUp(self):
        self.engine = _make_engine()

    def test_second_call_no_change(self):
        with Session(self.engine) as session:
            user = _make_user(session)
            wg = _make_system_admin_wg(session, user)

            _, _, changed = ensure_admin_workspace(session, wg)
            self.assertFalse(changed)

    def test_agent_count_stable(self):
        with Session(self.engine) as session:
            user = _make_user(session)
            wg = _make_system_admin_wg(session, user)

            ensure_admin_workspace(session, wg)
            session.flush()

            agents = find_admin_agents(session, wg.id)
            self.assertEqual(len(agents), 5)


class AdminTeamToolAssignmentTests(unittest.TestCase):
    """Test that each agent gets the correct tool subset from the system YAML."""

    def setUp(self):
        self.engine = _make_engine()

    def test_tool_subsets_match_yaml(self):
        specs = _load_system_admin_specs()

        with Session(self.engine) as session:
            user = _make_user(session)
            wg = _make_system_admin_wg(session, user)

            agents = find_admin_agents(session, wg.id)
            by_name = {a.name: a for a in agents}

            for agent_spec in specs:
                agent = by_name[agent_spec["name"]]
                self.assertEqual(
                    sorted(agent.tools), sorted(agent_spec["tools"]),
                    f"Tool mismatch for {agent_spec['name']}",
                )

    def test_lead_has_only_triage_tools(self):
        """The lead agent should only have read/list/delegation tools, not write tools."""
        allowed_prefixes = ("list_",)
        allowed_names = {"Task"}
        specs = _load_system_admin_specs()
        lead_spec = next(a for a in specs if a.get("is_lead"))
        for tool in lead_spec["tools"]:
            self.assertTrue(
                tool in allowed_names or any(tool.startswith(p) for p in allowed_prefixes),
                f"Lead tool '{tool}' is not a triage tool",
            )


class AdminTeamDetectionTests(unittest.TestCase):
    """Test is_admin_agent and find_admin_agent."""

    def setUp(self):
        self.engine = _make_engine()

    def test_is_admin_agent_by_sentinel(self):
        agent = Agent(
            created_by_user_id="u-1", name="workgroup-admin",
            description=ADMIN_AGENT_SENTINEL, tools=["add_agent"],
        )
        self.assertTrue(is_admin_agent(agent))

    def test_is_admin_agent_by_team_name_with_admin_tools(self):
        agent = Agent(
            created_by_user_id="u-1", name="administration-lead",
            description="Administration lead",
            tools=["list_members", "list_files"],
        )
        self.assertTrue(is_admin_agent(agent))

    def test_is_admin_agent_by_sentinel_empty_tools(self):
        """Agents with sentinel description are recognized even with empty tools."""
        agent = Agent(
            created_by_user_id="u-1", name="partner-admin",
            description=ADMIN_AGENT_SENTINEL, tools=[],
        )
        self.assertTrue(is_admin_agent(agent))

    def test_is_admin_agent_rejects_non_admin(self):
        agent = Agent(
            created_by_user_id="u-1", name="helper",
            description="helpful agent", tools=["Read", "Write"],
        )
        self.assertFalse(is_admin_agent(agent))

    def test_find_admin_agent_returns_lead(self):
        with Session(self.engine) as session:
            user = _make_user(session)
            wg = _make_system_admin_wg(session, user)

            lead = find_admin_agent(session, wg.id)
            self.assertIsNotNone(lead)
            self.assertEqual(lead.name, "administration-lead")


class AdminTeamNamesConstantTests(unittest.TestCase):
    """Test the ADMIN_TEAM_NAMES frozenset."""

    def test_contains_all_yaml_names(self):
        specs = _load_system_admin_specs()
        expected = {a["name"] for a in specs}
        self.assertEqual(ADMIN_TEAM_NAMES, expected)

    def test_exactly_five_members(self):
        self.assertEqual(len(ADMIN_TEAM_NAMES), 5)

    def test_lead_name_constant(self):
        self.assertEqual(_ADMIN_TEAM_LEAD_NAME, "administration-lead")


class AdminAgentReplyDelegationTests(unittest.TestCase):
    """Test that build_admin_agent_reply calls run_claude correctly."""

    def setUp(self):
        self.engine = _make_engine()

    def _make_claude_result(self, text: str, session_id: str = "sess-abc", slug: str = ""):
        from teaparty_app.services.claude_runner import ClaudeResult
        return ClaudeResult(
            text=text,
            session_id=session_id,
            slug=slug,
            is_error=False,
            error=None,
            model="claude-sonnet-4-6",
            input_tokens=10,
            output_tokens=20,
            duration_ms=500,
        )

    @unittest.mock.patch("teaparty_app.services.agent_runtime.run_claude", new_callable=unittest.mock.AsyncMock)
    def test_admin_conv_calls_run_claude(self, mock_run_claude):
        """For admin conversations, build_admin_agent_reply delegates to run_claude."""
        mock_run_claude.return_value = self._make_claude_result("Done.", session_id="s1", slug="list-agents")

        from teaparty_app.services.agent_runtime import build_admin_agent_reply

        with Session(self.engine) as session:
            user = _make_user(session)
            wg = _make_system_admin_wg(session, user)

            admin_agent = find_admin_agent(session, wg.id)
            user_id = user.id
            admin_wg_id = wg.id

            conv = session.exec(
                select(Conversation).where(
                    Conversation.workgroup_id == wg.id,
                    Conversation.kind == "admin",
                )
            ).first()

            trigger = Message(
                conversation_id=conv.id,
                sender_type="user",
                sender_user_id=user_id,
                content="list agents",
            )

            result_text, result_slug = build_admin_agent_reply(
                session, admin_agent, conv, trigger
            )

        self.assertEqual(result_text, "Done.")
        self.assertEqual(result_slug, "list-agents")
        mock_run_claude.assert_called_once()
        call_kwargs = mock_run_claude.call_args.kwargs
        self.assertEqual(call_kwargs["permission_mode"], "acceptEdits")
        self.assertIn("Bash", call_kwargs["allowed_tools"])
        self.assertEqual(call_kwargs["max_turns"], 25)
        # Lead agent should be the --agent, with full team in --agents.
        self.assertEqual(call_kwargs["agent_name"], "administration-lead")
        agents_dict = json.loads(call_kwargs["agents_json"])
        self.assertIn("administration-lead", agents_dict)
        self.assertIn("workgroup-admin", agents_dict)
        self.assertIn("organization-admin", agents_dict)
        self.assertIn("partner-admin", agents_dict)
        self.assertIn("workflow-admin", agents_dict)
        extra_env = call_kwargs["extra_env"]
        self.assertEqual(extra_env["TEAPARTY_USER_ID"], user_id)
        self.assertEqual(extra_env["TEAPARTY_WORKGROUP_ID"], admin_wg_id)

    @unittest.mock.patch("teaparty_app.services.agent_runtime.run_claude", new_callable=unittest.mock.AsyncMock)
    def test_direct_conv_calls_run_claude(self, mock_run_claude):
        """For direct conversations, build_admin_agent_reply also delegates to run_claude."""
        mock_run_claude.return_value = self._make_claude_result("Agent handled it.", session_id="s2", slug="add-agent-coder")

        from teaparty_app.services.agent_runtime import build_admin_agent_reply

        with Session(self.engine) as session:
            user = _make_user(session)
            wg = _make_system_admin_wg(session, user)

            admin_agent = find_admin_agent(session, wg.id)
            user_id = user.id
            admin_wg_id = wg.id

            direct_conv = Conversation(
                workgroup_id=wg.id,
                created_by_user_id=user_id,
                kind="direct",
                name="dm-with-admin",
            )
            session.add(direct_conv)
            session.flush()

            trigger = Message(
                conversation_id=direct_conv.id,
                sender_type="user",
                sender_user_id=user_id,
                content="add agent coder",
            )

            result_text, result_slug = build_admin_agent_reply(
                session, admin_agent, direct_conv, trigger
            )

        self.assertEqual(result_text, "Agent handled it.")
        self.assertEqual(result_slug, "add-agent-coder")
        mock_run_claude.assert_called_once()
        call_kwargs = mock_run_claude.call_args.kwargs
        self.assertEqual(call_kwargs["permission_mode"], "acceptEdits")
        self.assertIn("Bash", call_kwargs["allowed_tools"])
        self.assertEqual(call_kwargs["max_turns"], 25)
        extra_env = call_kwargs["extra_env"]
        self.assertEqual(extra_env["TEAPARTY_USER_ID"], user_id)
        self.assertEqual(extra_env["TEAPARTY_WORKGROUP_ID"], admin_wg_id)
