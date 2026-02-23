"""Tests for the 15 new CRUD global tools.

Tests call handler functions directly (not HTTP), following the project convention
of unittest.TestCase with _make_*() helpers.
"""

import unittest

from sqlmodel import Session, SQLModel, create_engine, select

from teaparty_app.models import (
    Agent,
    AgentWorkgroup,
    Membership,
    Organization,
    Partnership,
    User,
    Workgroup,
)
from teaparty_app.services.admin_workspace.bootstrap import (
    ADMIN_AGENT_SENTINEL,
)
from teaparty_app.services.admin_workspace.global_tools import (
    add_agent_to_workgroup,
    add_partner,
    add_tool_to_agent,
    create_workflow,
    delete_agent,
    delete_partner,
    delete_workflow,
    edit_workgroup,
    find_agent,
    find_organization,
    find_workflow,
    list_partners,
    list_workflows,
    remove_agent_from_workgroup,
    remove_tool_from_agent,
)


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_user(session, user_id="u-1", email="owner@test.com") -> User:
    user = User(id=user_id, email=email, name="Owner")
    session.add(user)
    session.flush()
    return user


def _make_org(session, org_id="org-1", owner_id="u-1", name="TestOrg", is_discoverable=True) -> Organization:
    org = Organization(id=org_id, name=name, owner_id=owner_id, is_discoverable=is_discoverable)
    session.add(org)
    session.flush()
    return org


def _make_workgroup(session, wg_id="wg-1", name="TestWG", owner_id="u-1", org_id=None, files=None) -> Workgroup:
    wg = Workgroup(id=wg_id, name=name, owner_id=owner_id, organization_id=org_id, files=files or [])
    session.add(wg)
    session.flush()
    session.add(Membership(workgroup_id=wg.id, user_id=owner_id, role="owner"))
    session.flush()
    return wg


def _make_agent(session, agent_id="a-1", name="test-agent", org_id=None, tools=None) -> Agent:
    agent = Agent(
        id=agent_id,
        name=name,
        organization_id=org_id,
        created_by_user_id="u-1",
        description="",
        prompt="Test agent",
        model="sonnet",
        tools=tools or [],
    )
    session.add(agent)
    session.flush()
    return agent


def _link_agent(session, agent_id, workgroup_id, is_lead=False):
    link = AgentWorkgroup(agent_id=agent_id, workgroup_id=workgroup_id, is_lead=is_lead)
    session.add(link)
    session.flush()
    return link


class EditWorkgroupTests(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session)
            _make_org(session)
            _make_workgroup(session, org_id="org-1")
            session.commit()

    def test_rename_workgroup(self):
        with Session(self.engine) as session:
            result = edit_workgroup(session, "u-1", {"workgroup_name": "TestWG", "new_name": "Renamed"})
            self.assertIn("Updated workgroup", result)
            self.assertIn("name", result)
            wg = session.get(Workgroup, "wg-1")
            self.assertEqual(wg.name, "Renamed")
            session.commit()

    def test_rename_system_workgroup_blocked(self):
        with Session(self.engine) as session:
            _make_workgroup(session, wg_id="wg-admin", name="Administration", org_id="org-1")
            session.commit()
        with Session(self.engine) as session:
            result = edit_workgroup(session, "u-1", {"workgroup_name": "Administration", "new_name": "Foo"})
            self.assertIn("Cannot rename system workgroup", result)

    def test_update_service_description(self):
        with Session(self.engine) as session:
            result = edit_workgroup(session, "u-1", {
                "workgroup_name": "TestWG",
                "service_description": "New description",
            })
            self.assertIn("service_description", result)
            wg = session.get(Workgroup, "wg-1")
            self.assertEqual(wg.service_description, "New description")
            session.commit()

    def test_update_is_discoverable(self):
        with Session(self.engine) as session:
            result = edit_workgroup(session, "u-1", {
                "workgroup_name": "TestWG",
                "is_discoverable": True,
            })
            self.assertIn("is_discoverable", result)
            session.commit()

    def test_no_fields_to_update(self):
        with Session(self.engine) as session:
            result = edit_workgroup(session, "u-1", {"workgroup_name": "TestWG"})
            self.assertIn("No fields to update", result)

    def test_workgroup_not_found(self):
        with Session(self.engine) as session:
            result = edit_workgroup(session, "u-1", {"workgroup_name": "NoSuchWG", "new_name": "Foo"})
            self.assertIn("not found", result)

    def test_empty_new_name_rejected(self):
        with Session(self.engine) as session:
            result = edit_workgroup(session, "u-1", {"workgroup_name": "TestWG", "new_name": ""})
            self.assertIn("cannot be empty", result)


class AgentWorkgroupLinkTests(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session)
            _make_org(session)
            _make_workgroup(session, wg_id="wg-1", name="WorkgroupA", org_id="org-1")
            _make_workgroup(session, wg_id="wg-2", name="WorkgroupB", org_id="org-1")
            agent = _make_agent(session, agent_id="a-1", name="shared-agent", org_id="org-1")
            _link_agent(session, "a-1", "wg-1")
            session.commit()

    def test_add_agent_to_workgroup(self):
        with Session(self.engine) as session:
            result = add_agent_to_workgroup(session, "u-1", {
                "workgroup_name": "WorkgroupB",
                "agent_name": "shared-agent",
            })
            self.assertIn("Added agent", result)
            link = session.exec(
                select(AgentWorkgroup).where(
                    AgentWorkgroup.agent_id == "a-1",
                    AgentWorkgroup.workgroup_id == "wg-2",
                )
            ).first()
            self.assertIsNotNone(link)
            session.commit()

    def test_add_agent_already_linked(self):
        with Session(self.engine) as session:
            result = add_agent_to_workgroup(session, "u-1", {
                "workgroup_name": "WorkgroupA",
                "agent_name": "shared-agent",
            })
            self.assertIn("already in", result)

    def test_add_agent_not_found(self):
        with Session(self.engine) as session:
            result = add_agent_to_workgroup(session, "u-1", {
                "workgroup_name": "WorkgroupB",
                "agent_name": "nonexistent",
            })
            self.assertIn("not found", result)

    def test_remove_agent_from_workgroup(self):
        with Session(self.engine) as session:
            result = remove_agent_from_workgroup(session, "u-1", {
                "workgroup_name": "WorkgroupA",
                "agent_name": "shared-agent",
            })
            self.assertIn("Removed agent", result)
            link = session.exec(
                select(AgentWorkgroup).where(
                    AgentWorkgroup.agent_id == "a-1",
                    AgentWorkgroup.workgroup_id == "wg-1",
                )
            ).first()
            self.assertIsNone(link)
            session.commit()

    def test_remove_lead_agent_blocked(self):
        with Session(self.engine) as session:
            _make_agent(session, agent_id="a-lead", name="lead-bot", org_id="org-1")
            _link_agent(session, "a-lead", "wg-1", is_lead=True)
            session.commit()
        with Session(self.engine) as session:
            result = remove_agent_from_workgroup(session, "u-1", {
                "workgroup_name": "WorkgroupA",
                "agent_name": "lead-bot",
            })
            self.assertIn("Cannot modify lead agent", result)

    def test_remove_admin_agent_blocked(self):
        with Session(self.engine) as session:
            admin = Agent(
                id="a-admin", name="workgroup-admin", organization_id="org-1",
                created_by_user_id="u-1", description=ADMIN_AGENT_SENTINEL,
                prompt="admin", model="sonnet", tools=[],
            )
            session.add(admin)
            session.flush()
            _link_agent(session, "a-admin", "wg-1")
            session.commit()
        with Session(self.engine) as session:
            # Admin agents aren't found by _resolve_agent_in_workgroup (filtered by sentinel)
            result = remove_agent_from_workgroup(session, "u-1", {
                "workgroup_name": "WorkgroupA",
                "agent_name": "workgroup-admin",
            })
            self.assertIn("not found", result)


class PartnerToolTests(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session, "u-1", "owner1@test.com")
            _make_user(session, "u-2", "owner2@test.com")
            _make_org(session, "org-1", "u-1", "AlphaOrg")
            _make_org(session, "org-2", "u-2", "BetaOrg", is_discoverable=True)
            session.commit()

    def test_find_organization_owned(self):
        with Session(self.engine) as session:
            result = find_organization(session, "u-1", {"query": "Alpha"})
            self.assertIn("AlphaOrg", result)
            self.assertIn("(owned)", result)

    def test_find_organization_discoverable(self):
        with Session(self.engine) as session:
            result = find_organization(session, "u-1", {"query": "Beta"})
            self.assertIn("BetaOrg", result)
            self.assertIn("(discoverable)", result)

    def test_find_organization_no_results(self):
        with Session(self.engine) as session:
            result = find_organization(session, "u-1", {"query": "Zzzz"})
            self.assertIn("No organizations found", result)

    def test_add_partner(self):
        with Session(self.engine) as session:
            result = add_partner(session, "u-1", {
                "source_organization_name": "AlphaOrg",
                "target_organization_name": "BetaOrg",
            })
            self.assertIn("Created partnership", result)
            p = session.exec(select(Partnership)).first()
            self.assertIsNotNone(p)
            self.assertEqual(p.status, "accepted")
            session.commit()

    def test_add_partner_duplicate(self):
        with Session(self.engine) as session:
            add_partner(session, "u-1", {
                "source_organization_name": "AlphaOrg",
                "target_organization_name": "BetaOrg",
            })
            session.commit()
        with Session(self.engine) as session:
            result = add_partner(session, "u-1", {
                "source_organization_name": "AlphaOrg",
                "target_organization_name": "BetaOrg",
            })
            self.assertIn("already exists", result)

    def test_add_partner_same_org(self):
        with Session(self.engine) as session:
            result = add_partner(session, "u-1", {
                "source_organization_name": "AlphaOrg",
                "target_organization_name": "AlphaOrg",
            })
            self.assertIn("must be different", result)

    def test_add_partner_invalid_direction(self):
        with Session(self.engine) as session:
            result = add_partner(session, "u-1", {
                "source_organization_name": "AlphaOrg",
                "target_organization_name": "BetaOrg",
                "direction": "invalid",
            })
            self.assertIn("Invalid direction", result)

    def test_list_partners_empty(self):
        with Session(self.engine) as session:
            result = list_partners(session, "u-1", {"organization_name": "AlphaOrg"})
            self.assertIn("No partnerships found", result)

    def test_list_partners_with_data(self):
        with Session(self.engine) as session:
            add_partner(session, "u-1", {
                "source_organization_name": "AlphaOrg",
                "target_organization_name": "BetaOrg",
            })
            session.commit()
        with Session(self.engine) as session:
            result = list_partners(session, "u-1", {"organization_name": "AlphaOrg"})
            self.assertIn("BetaOrg", result)
            self.assertIn("count=1", result)

    def test_delete_partner(self):
        with Session(self.engine) as session:
            add_partner(session, "u-1", {
                "source_organization_name": "AlphaOrg",
                "target_organization_name": "BetaOrg",
            })
            session.commit()
        with Session(self.engine) as session:
            result = delete_partner(session, "u-1", {
                "source_organization_name": "AlphaOrg",
                "target_organization_name": "BetaOrg",
            })
            self.assertIn("Revoked", result)
            p = session.exec(select(Partnership)).first()
            self.assertEqual(p.status, "revoked")

    def test_delete_partner_not_found(self):
        with Session(self.engine) as session:
            result = delete_partner(session, "u-1", {
                "source_organization_name": "AlphaOrg",
                "target_organization_name": "BetaOrg",
            })
            self.assertIn("No accepted partnership", result)


class AgentManagementToolTests(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session)
            _make_org(session)
            wg = _make_workgroup(session, wg_id="wg-1", name="DevTeam", org_id="org-1")
            agent = _make_agent(session, agent_id="a-1", name="coder", org_id="org-1", tools=["web_search"])
            _link_agent(session, "a-1", "wg-1")
            session.commit()

    def test_find_agent(self):
        with Session(self.engine) as session:
            result = find_agent(session, "u-1", {"agent_name": "coder"})
            self.assertIn("coder", result)
            self.assertIn("DevTeam", result)

    def test_find_agent_not_found(self):
        with Session(self.engine) as session:
            result = find_agent(session, "u-1", {"agent_name": "nonexistent"})
            self.assertIn("No agents found", result)

    def test_add_tool_to_agent(self):
        with Session(self.engine) as session:
            result = add_tool_to_agent(session, "u-1", {
                "workgroup_name": "DevTeam",
                "agent_name": "coder",
                "tools": ["code_editor", "file_read"],
            })
            self.assertIn("Added tools", result)
            agent = session.get(Agent, "a-1")
            self.assertIn("code_editor", agent.tools)
            self.assertIn("file_read", agent.tools)
            self.assertIn("web_search", agent.tools)
            session.commit()

    def test_add_tool_already_present(self):
        with Session(self.engine) as session:
            result = add_tool_to_agent(session, "u-1", {
                "workgroup_name": "DevTeam",
                "agent_name": "coder",
                "tools": ["web_search"],
            })
            self.assertIn("already has all", result)

    def test_remove_tool_from_agent(self):
        with Session(self.engine) as session:
            result = remove_tool_from_agent(session, "u-1", {
                "workgroup_name": "DevTeam",
                "agent_name": "coder",
                "tools": ["web_search"],
            })
            self.assertIn("Removed tools", result)
            agent = session.get(Agent, "a-1")
            self.assertNotIn("web_search", agent.tools)
            session.commit()

    def test_remove_tool_not_present(self):
        with Session(self.engine) as session:
            result = remove_tool_from_agent(session, "u-1", {
                "workgroup_name": "DevTeam",
                "agent_name": "coder",
                "tools": ["nonexistent_tool"],
            })
            self.assertIn("does not have", result)

    def test_delete_agent(self):
        with Session(self.engine) as session:
            result = delete_agent(session, "u-1", {
                "workgroup_name": "DevTeam",
                "agent_name": "coder",
            })
            self.assertIn("Removed member", result)
            session.commit()

    def test_delete_agent_not_found(self):
        with Session(self.engine) as session:
            result = delete_agent(session, "u-1", {
                "workgroup_name": "DevTeam",
                "agent_name": "nonexistent",
            })
            self.assertIn("not found", result)


class WorkflowToolTests(unittest.TestCase):
    def setUp(self):
        self.engine = _make_engine()
        with Session(self.engine) as session:
            _make_user(session)
            _make_org(session)
            _make_workgroup(session, wg_id="wg-1", name="DevTeam", org_id="org-1", files=[])
            session.commit()

    def test_create_workflow(self):
        with Session(self.engine) as session:
            result = create_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "onboarding",
                "content": "# Onboarding\nStep 1...",
            })
            self.assertIn("Created workflow", result)
            self.assertIn("workflows/onboarding.md", result)
            wg = session.get(Workgroup, "wg-1")
            self.assertEqual(len(wg.files), 1)
            self.assertEqual(wg.files[0]["path"], "workflows/onboarding.md")
            session.commit()

    def test_create_workflow_auto_normalize_path(self):
        with Session(self.engine) as session:
            result = create_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "workflows/review.md",
                "content": "# Review",
            })
            self.assertIn("workflows/review.md", result)
            session.commit()

    def test_create_workflow_duplicate(self):
        with Session(self.engine) as session:
            create_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "onboarding",
                "content": "v1",
            })
            session.commit()
        with Session(self.engine) as session:
            result = create_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "onboarding",
                "content": "v2",
            })
            self.assertIn("already exists", result)

    def test_list_workflows_empty(self):
        with Session(self.engine) as session:
            result = list_workflows(session, "u-1", {"workgroup_name": "DevTeam"})
            self.assertIn("No workflows found", result)

    def test_list_workflows_with_data(self):
        with Session(self.engine) as session:
            create_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "deploy",
                "content": "Deploy steps",
            })
            session.commit()
        with Session(self.engine) as session:
            result = list_workflows(session, "u-1", {"workgroup_name": "DevTeam"})
            self.assertIn("workflows/deploy.md", result)
            self.assertIn("count=1", result)

    def test_find_workflow(self):
        with Session(self.engine) as session:
            create_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "standup",
                "content": "# Daily Standup\nShare updates.",
            })
            session.commit()
        with Session(self.engine) as session:
            result = find_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "standup",
            })
            self.assertIn("Daily Standup", result)
            self.assertIn("Share updates", result)

    def test_find_workflow_not_found(self):
        with Session(self.engine) as session:
            result = find_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "nonexistent",
            })
            self.assertIn("not found", result)

    def test_delete_workflow(self):
        with Session(self.engine) as session:
            create_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "old-process",
                "content": "deprecated",
            })
            session.commit()
        with Session(self.engine) as session:
            result = delete_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "old-process",
            })
            self.assertIn("Deleted workflow", result)
            wg = session.get(Workgroup, "wg-1")
            self.assertEqual(len(wg.files), 0)
            session.commit()

    def test_delete_workflow_not_found(self):
        with Session(self.engine) as session:
            result = delete_workflow(session, "u-1", {
                "workgroup_name": "DevTeam",
                "name": "nonexistent",
            })
            self.assertIn("not found", result)


if __name__ == "__main__":
    unittest.main()
