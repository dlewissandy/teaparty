"""Tests for the fixed admin agent team in org-level Administration workgroups."""

import unittest

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
    ADMIN_TEAM_SPECS,
    ADMIN_TOOL_ADD_AGENT,
    ADMIN_TOOL_ADD_JOB,
    ADMIN_TOOL_LIST_FILES,
    ADMIN_TOOL_LIST_JOBS,
    ADMIN_TOOL_LIST_MEMBERS,
    ADMIN_TOOL_NAMES,
    GLOBAL_TOOL_NAMES,
    _ADMIN_TEAM_LEAD_NAME,
    ensure_admin_workspace,
    find_admin_agent,
    find_admin_agents,
    is_admin_agent,
)


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


class AdminTeamCreationTests(unittest.TestCase):
    """Test that ensure_admin_workspace creates the full 5-agent team for org workgroups."""

    def setUp(self):
        self.engine = _make_engine()

    def test_org_admin_creates_five_agents(self):
        with Session(self.engine) as session:
            user = _make_user(session)
            org = _make_org(session, user)
            wg = _make_workgroup(session, user, org=org, name="Administration")

            lead, conv, changed = ensure_admin_workspace(session, wg)
            session.flush()

            self.assertTrue(changed)
            self.assertEqual(lead.name, "administration-lead")

            agents = find_admin_agents(session, wg.id)
            names = {a.name for a in agents}
            self.assertEqual(names, {
                "administration-lead", "workgroup-admin",
                "organization-admin", "partner-admin", "workflow-admin",
            })

    def test_non_org_admin_creates_single_agent(self):
        """Non-org workgroups still get a single admin agent with all tools."""
        with Session(self.engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user, org=None, name="Administration")

            lead, conv, changed = ensure_admin_workspace(session, wg)
            session.flush()

            self.assertTrue(changed)
            agents = find_admin_agents(session, wg.id)
            self.assertEqual(len(agents), 1)
            self.assertEqual(sorted(agents[0].tools), sorted(ADMIN_TOOL_NAMES))


class AdminTeamIdempotencyTests(unittest.TestCase):
    """Test that running ensure_admin_workspace twice is idempotent."""

    def setUp(self):
        self.engine = _make_engine()

    def test_second_call_no_change(self):
        with Session(self.engine) as session:
            user = _make_user(session)
            org = _make_org(session, user)
            wg = _make_workgroup(session, user, org=org, name="Administration")

            ensure_admin_workspace(session, wg)
            session.flush()

            _, _, changed = ensure_admin_workspace(session, wg)
            self.assertFalse(changed)

    def test_agent_count_stable(self):
        with Session(self.engine) as session:
            user = _make_user(session)
            org = _make_org(session, user)
            wg = _make_workgroup(session, user, org=org, name="Administration")

            ensure_admin_workspace(session, wg)
            session.flush()
            ensure_admin_workspace(session, wg)
            session.flush()

            agents = find_admin_agents(session, wg.id)
            self.assertEqual(len(agents), 5)


class AdminTeamToolAssignmentTests(unittest.TestCase):
    """Test that each agent gets the correct tool subset."""

    def setUp(self):
        self.engine = _make_engine()

    def test_tool_subsets_match_specs(self):
        with Session(self.engine) as session:
            user = _make_user(session)
            org = _make_org(session, user)
            wg = _make_workgroup(session, user, org=org, name="Administration")

            ensure_admin_workspace(session, wg)
            session.flush()

            agents = find_admin_agents(session, wg.id)
            by_name = {a.name: a for a in agents}

            for spec in ADMIN_TEAM_SPECS:
                agent = by_name[spec["name"]]
                self.assertEqual(
                    sorted(agent.tools), sorted(spec["tools"]),
                    f"Tool mismatch for {spec['name']}",
                )

    def test_lead_has_only_read_tools(self):
        """The lead agent should only have read/list tools, not write tools."""
        lead_spec = next(s for s in ADMIN_TEAM_SPECS if s["is_lead"])
        for tool in lead_spec["tools"]:
            self.assertTrue(
                tool.startswith("list_"),
                f"Lead tool '{tool}' is not a list/read tool",
            )

    def test_agents_with_empty_tools_are_valid(self):
        """partner-admin and workflow-admin have empty tools (LLM-only agents)."""
        for spec in ADMIN_TEAM_SPECS:
            if spec["name"] in ("partner-admin", "workflow-admin"):
                self.assertEqual(spec["tools"], [], f"{spec['name']} should have empty tools")


class AdminTeamDetectionTests(unittest.TestCase):
    """Test is_admin_agent and find_admin_agent."""

    def setUp(self):
        self.engine = _make_engine()

    def test_is_admin_agent_by_sentinel(self):
        agent = Agent(
            created_by_user_id="u-1", name="workgroup-admin",
            description=ADMIN_AGENT_SENTINEL, tools=["add_job"],
        )
        self.assertTrue(is_admin_agent(agent))

    def test_is_admin_agent_by_team_name_with_admin_tools(self):
        agent = Agent(
            created_by_user_id="u-1", name="administration-lead",
            description="Administration lead",
            tools=["list_jobs", "list_members", "list_files", "list_tasks"],
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
            org = _make_org(session, user)
            wg = _make_workgroup(session, user, org=org, name="Administration")

            ensure_admin_workspace(session, wg)
            session.flush()

            lead = find_admin_agent(session, wg.id)
            self.assertIsNotNone(lead)
            self.assertEqual(lead.name, "administration-lead")


class AdminTeamRoutingTests(unittest.TestCase):
    """Test deterministic tool filtering by allowed_tools."""

    def setUp(self):
        self.engine = _make_engine()

    def test_allowed_tools_filters_commands(self):
        from teaparty_app.services.admin_workspace import _handle_admin_message_deterministic

        with Session(self.engine) as session:
            user = _make_user(session)
            org = _make_org(session, user)
            wg = _make_workgroup(session, user, org=org, name="Administration")
            session.flush()

            # workgroup-admin can list jobs but NOT list members (if restricted)
            result = _handle_admin_message_deterministic(
                session, wg.id, user.id, "list jobs",
                allowed_tools={"add_job", "list_jobs", "list_files"},
            )
            self.assertIsNotNone(result)

            result = _handle_admin_message_deterministic(
                session, wg.id, user.id, "list members",
                allowed_tools={"add_job", "list_jobs", "list_files"},
            )
            self.assertIsNone(result)

    def test_no_allowed_tools_allows_all(self):
        from teaparty_app.services.admin_workspace import _handle_admin_message_deterministic

        with Session(self.engine) as session:
            user = _make_user(session)
            org = _make_org(session, user)
            wg = _make_workgroup(session, user, org=org, name="Administration")
            session.flush()

            # No filter: all commands work
            result = _handle_admin_message_deterministic(
                session, wg.id, user.id, "list jobs",
                allowed_tools=None,
            )
            self.assertIsNotNone(result)


class AdminTeamNamesConstantTests(unittest.TestCase):
    """Test the ADMIN_TEAM_NAMES frozenset."""

    def test_contains_all_spec_names(self):
        expected = {s["name"] for s in ADMIN_TEAM_SPECS}
        self.assertEqual(ADMIN_TEAM_NAMES, expected)

    def test_exactly_five_members(self):
        self.assertEqual(len(ADMIN_TEAM_SPECS), 5)

    def test_exactly_one_lead(self):
        leads = [s for s in ADMIN_TEAM_SPECS if s["is_lead"]]
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["name"], "administration-lead")

    def test_lead_name_constant(self):
        self.assertEqual(_ADMIN_TEAM_LEAD_NAME, "administration-lead")
