"""Tests for convention_resolver and CLAUDE.md prompt injection."""

import unittest

from sqlmodel import SQLModel, Session, create_engine

from teaparty_app.models import Agent, Conversation, Membership, Organization, User, Workgroup
from teaparty_app.services.convention_resolver import extract_claude_md, resolve_effective_files
from teaparty_app.services.agent_definition import build_agent_json


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_user(session, user_id="user-1"):
    user = User(id=user_id, email=f"{user_id}@example.com", name="Owner")
    session.add(user)
    return user


def _make_org(session, user, org_id="org-1", files=None):
    org = Organization(id=org_id, name="TestOrg", owner_id=user.id, files=files or [])
    session.add(org)
    session.flush()
    return org


def _make_workgroup(session, user, org=None, wg_id="wg-1", files=None):
    wg = Workgroup(
        id=wg_id, name="TestTeam", owner_id=user.id,
        files=files or [],
        organization_id=org.id if org else None,
    )
    session.add(wg)
    session.flush()
    session.add(Membership(workgroup_id=wg.id, user_id=user.id, role="owner"))
    return wg


def _make_agent(session, workgroup, user, name="Helper", agent_id="agent-1", is_lead=False):
    agent = Agent(
        id=agent_id,
        workgroup_id=workgroup.id,
        created_by_user_id=user.id,
        name=name,
        description="",
        role="assistant",
        model="sonnet",
        tool_names=["Read", "Write"],
        is_lead=is_lead,
    )
    session.add(agent)
    session.flush()
    return agent


def _make_conversation(session, workgroup, user, conv_id="conv-1"):
    conv = Conversation(
        id=conv_id,
        workgroup_id=workgroup.id,
        created_by_user_id=user.id,
        kind="job",
        name="Test Job",
    )
    session.add(conv)
    session.flush()
    return conv


class ExtractClaudeMdTests(unittest.TestCase):
    def test_returns_empty_for_no_files(self):
        self.assertEqual(extract_claude_md(None), "")
        self.assertEqual(extract_claude_md([]), "")

    def test_extracts_claude_md_content(self):
        files = [
            {"path": "README.md", "content": "# Readme"},
            {"path": "CLAUDE.md", "content": "Be concise."},
        ]
        self.assertEqual(extract_claude_md(files), "Be concise.")

    def test_caps_at_max_chars(self):
        files = [{"path": "CLAUDE.md", "content": "x" * 5000}]
        result = extract_claude_md(files, max_chars=100)
        self.assertEqual(len(result), 100)

    def test_returns_empty_when_no_claude_md(self):
        files = [{"path": "README.md", "content": "Hello"}]
        self.assertEqual(extract_claude_md(files), "")

    def test_strips_whitespace(self):
        files = [{"path": "CLAUDE.md", "content": "  content  \n  "}]
        self.assertEqual(extract_claude_md(files), "content")


class ResolveEffectiveFilesTests(unittest.TestCase):
    def test_empty_inputs(self):
        result = resolve_effective_files(None, None, "workflows")
        self.assertEqual(result, [])

    def test_org_only(self):
        org_files = [
            {"path": "workflows/deploy.md", "content": "# Deploy"},
            {"path": "workflows/README.md", "content": "readme"},
        ]
        result = resolve_effective_files(org_files, None, "workflows")
        self.assertEqual(len(result), 2)
        paths = {f["path"] for f in result}
        self.assertIn("workflows/deploy.md", paths)

    def test_workgroup_only(self):
        wg_files = [{"path": "workflows/review.md", "content": "# Review"}]
        result = resolve_effective_files(None, wg_files, "workflows")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["path"], "workflows/review.md")

    def test_workgroup_overrides_org_by_filename(self):
        org_files = [{"path": "workflows/deploy.md", "content": "# Org Deploy"}]
        wg_files = [{"path": "workflows/deploy.md", "content": "# WG Deploy"}]
        result = resolve_effective_files(org_files, wg_files, "workflows")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "# WG Deploy")
        self.assertEqual(result[0]["_source"], "workgroup")

    def test_merges_unique_files(self):
        org_files = [{"path": "workflows/deploy.md", "content": "# Deploy"}]
        wg_files = [{"path": "workflows/review.md", "content": "# Review"}]
        result = resolve_effective_files(org_files, wg_files, "workflows")
        self.assertEqual(len(result), 2)
        paths = {f["path"] for f in result}
        self.assertIn("workflows/deploy.md", paths)
        self.assertIn("workflows/review.md", paths)

    def test_source_annotation(self):
        org_files = [{"path": "workflows/deploy.md", "content": "# Deploy"}]
        wg_files = [{"path": "workflows/review.md", "content": "# Review"}]
        result = resolve_effective_files(org_files, wg_files, "workflows")
        sources = {f["path"]: f["_source"] for f in result}
        self.assertEqual(sources["workflows/deploy.md"], "org")
        self.assertEqual(sources["workflows/review.md"], "workgroup")

    def test_filters_by_prefix_and_extension(self):
        files = [
            {"path": "workflows/deploy.md", "content": "ok"},
            {"path": "commands/build.md", "content": "no"},
            {"path": "workflows/script.py", "content": "no"},
        ]
        result = resolve_effective_files(None, files, "workflows", ".md")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["path"], "workflows/deploy.md")


class ClaudeMdPromptInjectionTests(unittest.TestCase):
    def test_org_claude_md_in_prompt(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            org = _make_org(session, user, files=[{"path": "CLAUDE.md", "content": "Org rule: be formal."}])
            wg = _make_workgroup(session, user, org=org)
            agent = _make_agent(session, wg, user)
            conv = _make_conversation(session, wg, user)
            session.commit()

            result = build_agent_json(agent, conv, wg, org_files=org.files)
            prompt = result["prompt"]
            self.assertIn("## Organization Instructions", prompt)
            self.assertIn("Org rule: be formal.", prompt)

    def test_wg_claude_md_in_prompt(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user, files=[{"path": "CLAUDE.md", "content": "WG rule: use tests."}])
            agent = _make_agent(session, wg, user)
            conv = _make_conversation(session, wg, user)
            session.commit()

            result = build_agent_json(agent, conv, wg)
            prompt = result["prompt"]
            self.assertIn("## Workgroup Instructions", prompt)
            self.assertIn("WG rule: use tests.", prompt)

    def test_cascade_order_org_before_workgroup(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            org = _make_org(session, user, files=[{"path": "CLAUDE.md", "content": "Org first."}])
            wg = _make_workgroup(session, user, org=org, files=[{"path": "CLAUDE.md", "content": "WG second."}])
            agent = _make_agent(session, wg, user)
            conv = _make_conversation(session, wg, user)
            session.commit()

            result = build_agent_json(agent, conv, wg, org_files=org.files)
            prompt = result["prompt"]
            org_pos = prompt.index("## Organization Instructions")
            wg_pos = prompt.index("## Workgroup Instructions")
            self.assertLess(org_pos, wg_pos)

    def test_no_claude_md_no_sections(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user, files=[{"path": "README.md", "content": "hello"}])
            agent = _make_agent(session, wg, user)
            conv = _make_conversation(session, wg, user)
            session.commit()

            result = build_agent_json(agent, conv, wg)
            prompt = result["prompt"]
            self.assertNotIn("## Organization Instructions", prompt)
            self.assertNotIn("## Workgroup Instructions", prompt)


class WorkflowsNotInjectedTests(unittest.TestCase):
    """Workflows are just files — not injected into agent prompts."""

    def test_workflows_not_in_prompt(self):
        engine = _make_engine()
        wg_files = [
            {"path": "workflows/deploy.md", "content": "# Deploy\n\n## Trigger\nDeploy requested."},
        ]
        with Session(engine) as session:
            user = _make_user(session)
            wg = _make_workgroup(session, user, files=wg_files)
            agent = _make_agent(session, wg, user, name="Lead", agent_id="lead-1", is_lead=True)
            conv = _make_conversation(session, wg, user)
            session.commit()

            result = build_agent_json(agent, conv, wg)
            prompt = result["prompt"]
            self.assertNotIn("Available Workflows", prompt)
            self.assertNotIn("Active Workflow", prompt)
            self.assertNotIn("Deploy", prompt)


class OrgFilesModelTests(unittest.TestCase):
    def test_org_files_persist(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            org = _make_org(session, user, files=[
                {"path": "CLAUDE.md", "content": "Be helpful."},
                {"path": "workflows/deploy.md", "content": "# Deploy"},
            ])
            session.commit()

        with Session(engine) as session:
            reloaded = session.get(Organization, "org-1")
            self.assertEqual(len(reloaded.files), 2)
            paths = {f["path"] for f in reloaded.files}
            self.assertIn("CLAUDE.md", paths)
            self.assertIn("workflows/deploy.md", paths)

    def test_org_files_default_empty(self):
        engine = _make_engine()
        with Session(engine) as session:
            user = _make_user(session)
            org = Organization(id="org-2", name="Empty", owner_id=user.id)
            session.add(org)
            session.commit()

        with Session(engine) as session:
            reloaded = session.get(Organization, "org-2")
            self.assertEqual(reloaded.files, [])
