"""Tests for hierarchical agent teams: liaison agents, project teams, and relay CLI."""

import json
import unittest
from unittest.mock import MagicMock, patch

from teaparty_app.models import (
    Agent,
    Conversation,
    Job,
    Organization,
    Project,
    Workgroup,
)
from teaparty_app.services.agent_definition import (
    build_liaison_json,
    build_project_lead_json,
    build_project_team_agents,
    slugify,
)
from teaparty_app.services.liaison import (
    TeamParams,
    create_subteam_job,
    resolve_team_params,
)
from teaparty_app.services.team_session import TeamSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(
    *,
    agent_id: str = "a1",
    name: str = "Implementer",
    role: str = "Implementation lead",
    model: str = "sonnet",
    is_lead: bool = False,
    workgroup_id: str = "wg-1",
) -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id=workgroup_id,
        created_by_user_id="user-1",
        name=name,
        role=role,
        personality="Practical",
        model=model,
        max_turns=3,
        tool_names=[],
        is_lead=is_lead,
    )


def _make_workgroup(
    *,
    workgroup_id: str = "wg-1",
    name: str = "Engineering",
    org_id: str = "org-1",
    team_model: str = "sonnet",
    team_permission_mode: str = "acceptEdits",
    team_max_turns: int = 30,
    team_max_cost_usd: float | None = None,
    team_max_time_seconds: int | None = None,
) -> Workgroup:
    wg = Workgroup(
        id=workgroup_id,
        name=name,
        owner_id="user-1",
        organization_id=org_id,
        files=[],
    )
    wg.team_model = team_model
    wg.team_permission_mode = team_permission_mode
    wg.team_max_turns = team_max_turns
    wg.team_max_cost_usd = team_max_cost_usd
    wg.team_max_time_seconds = team_max_time_seconds
    return wg


def _make_project(
    *,
    project_id: str = "proj-1",
    org_id: str = "org-1",
    name: str = "Test Project",
    prompt: str = "Build something amazing",
    workgroup_ids: list[str] | None = None,
    model: str = "sonnet",
    permission_mode: str = "plan",
    max_turns: int = 30,
) -> Project:
    return Project(
        id=project_id,
        organization_id=org_id,
        created_by_user_id="user-1",
        name=name,
        prompt=prompt,
        model=model,
        permission_mode=permission_mode,
        max_turns=max_turns,
        workgroup_ids=workgroup_ids or ["wg-1", "wg-2"],
    )


def _make_organization(
    *,
    org_id: str = "org-1",
) -> Organization:
    return Organization(
        id=org_id,
        name="Test Org",
        created_by_user_id="user-1",
    )


# ---------------------------------------------------------------------------
# Tests: Liaison Agent Definition
# ---------------------------------------------------------------------------

class BuildLiaisonJsonTests(unittest.TestCase):
    """Test liaison agent definition builder."""

    def test_basic_structure(self) -> None:
        wg = _make_workgroup(name="Engineering")
        project = _make_project()
        result = build_liaison_json(wg, project)

        self.assertEqual(result["description"], "Engineering workgroup liaison")
        self.assertIn("model", result)
        self.assertEqual(result["maxTurns"], 10)
        self.assertIn("prompt", result)

    def test_prompt_mentions_relay(self) -> None:
        wg = _make_workgroup(name="Design")
        project = _make_project()
        result = build_liaison_json(wg, project)

        self.assertIn("liaison agent", result["prompt"].lower())
        self.assertIn("relay-to-subteam", result["prompt"])
        self.assertIn("Design", result["prompt"])

    def test_prompt_includes_project_scope(self) -> None:
        wg = _make_workgroup()
        project = _make_project(prompt="Build a REST API with auth")
        result = build_liaison_json(wg, project)

        self.assertIn("Build a REST API with auth", result["prompt"])

    def test_prompt_forbids_direct_work(self) -> None:
        wg = _make_workgroup()
        project = _make_project()
        result = build_liaison_json(wg, project)

        self.assertIn("do not write code", result["prompt"].lower())
        self.assertIn("communication relay", result["prompt"].lower())

    def test_model_uses_project_or_workgroup(self) -> None:
        wg = _make_workgroup(team_model="haiku")
        project = _make_project(model="sonnet")
        result = build_liaison_json(wg, project)

        # Model should resolve to a CLI alias
        self.assertIn(result["model"], ["sonnet", "haiku", "opus"])

    def test_workgroup_id_env_var_in_prompt(self) -> None:
        wg = _make_workgroup(name="Design")
        project = _make_project()
        result = build_liaison_json(wg, project)

        # Should reference the env var for its workgroup ID
        self.assertIn("TEAPARTY_WORKGROUP_ID", result["prompt"])


# ---------------------------------------------------------------------------
# Tests: Project Team Agents Builder
# ---------------------------------------------------------------------------

class BuildProjectLeadJsonTests(unittest.TestCase):
    """Test the ephemeral project lead agent definition."""

    def test_basic_structure(self) -> None:
        project = _make_project(name="Auth System", prompt="Build OAuth2")
        result = build_project_lead_json(project, [])

        self.assertIn("project lead", result["description"].lower())
        self.assertIn("Auth System", result["prompt"])
        self.assertIn("Build OAuth2", result["prompt"])
        self.assertIn("model", result)
        self.assertIn("maxTurns", result)

    def test_includes_liaison_roster(self) -> None:
        project = _make_project()
        roster = [
            "- engineering-liaison — Engineering workgroup liaison",
            "- design-liaison — Design workgroup liaison",
        ]
        result = build_project_lead_json(project, roster)

        self.assertIn("engineering-liaison", result["prompt"])
        self.assertIn("design-liaison", result["prompt"])
        self.assertIn("subagent_type", result["prompt"])
        self.assertIn("Your Team", result["prompt"])

    def test_includes_org_instructions(self) -> None:
        project = _make_project()
        org_files = [{"path": "CLAUDE.md", "content": "Always use TypeScript."}]
        result = build_project_lead_json(project, [], org_files=org_files)

        self.assertIn("Always use TypeScript", result["prompt"])


class BuildProjectTeamAgentsTests(unittest.TestCase):
    """Test project team agent definition builder.

    The project team consists of an ephemeral project lead plus one liaison
    for every non-Administration workgroup in the organization.
    """

    def _setup_session_mocks(self, session_mock):
        """Configure a mock session with project workgroups."""
        wg1 = _make_workgroup(workgroup_id="wg-1", name="Engineering", org_id="org-1")
        wg2 = _make_workgroup(workgroup_id="wg-2", name="Design", org_id="org-1")

        # session.get() is called for each workgroup_id in the project.
        session_mock.get.side_effect = lambda cls, id_val: {
            ("wg-1",): wg1, ("wg-2",): wg2,
        }.get((id_val,))

        return wg1, wg2

    def test_returns_lead_and_liaisons(self) -> None:
        session = MagicMock()
        self._setup_session_mocks(session)
        project = _make_project()

        agents_dict, lead_slug, slug_to_id = build_project_team_agents(session, project)

        # Should have project-lead + 1 workgroup liaison per org workgroup
        self.assertEqual(len(agents_dict), 3)
        self.assertEqual(lead_slug, "project-lead")
        self.assertIn("project-lead", agents_dict)
        self.assertIn("engineering-liaison", agents_dict)
        self.assertIn("design-liaison", agents_dict)

    def test_lead_has_teammate_roster(self) -> None:
        session = MagicMock()
        self._setup_session_mocks(session)
        project = _make_project()

        agents_dict, lead_slug, slug_to_id = build_project_team_agents(session, project)

        lead_prompt = agents_dict[lead_slug]["prompt"]
        self.assertIn("engineering-liaison", lead_prompt)
        self.assertIn("design-liaison", lead_prompt)
        self.assertIn("Your Team", lead_prompt)

    def test_slug_to_id_maps_correctly(self) -> None:
        session = MagicMock()
        self._setup_session_mocks(session)
        project = _make_project()

        agents_dict, lead_slug, slug_to_id = build_project_team_agents(session, project)

        self.assertEqual(slug_to_id["project-lead"], "project:proj-1")
        self.assertEqual(slug_to_id["engineering-liaison"], "liaison:wg-1")
        self.assertEqual(slug_to_id["design-liaison"], "liaison:wg-2")


# ---------------------------------------------------------------------------
# Tests: Team Parameter Resolution
# ---------------------------------------------------------------------------

class ResolveTeamParamsTests(unittest.TestCase):
    """Test team parameter merging: project overrides > workgroup defaults."""

    def test_workgroup_defaults_used(self) -> None:
        project = _make_project(
            model="sonnet",  # default value: triggers workgroup fallback
            permission_mode="plan",  # default value
            max_turns=30,  # default value
        )
        wg = _make_workgroup(
            team_model="haiku",
            team_permission_mode="bypassPermissions",
            team_max_turns=50,
            team_max_cost_usd=5.0,
            team_max_time_seconds=300,
        )

        params = resolve_team_params(project, wg)

        self.assertEqual(params.model, "haiku")
        self.assertEqual(params.permission_mode, "bypassPermissions")
        self.assertEqual(params.max_turns, 50)
        self.assertEqual(params.max_cost_usd, 5.0)
        self.assertEqual(params.max_time_seconds, 300)

    def test_project_overrides(self) -> None:
        project = _make_project(
            model="opus",
            permission_mode="acceptEdits",
            max_turns=100,
        )
        project.max_cost_usd = 10.0
        project.max_time_seconds = 600

        wg = _make_workgroup(
            team_model="haiku",
            team_permission_mode="bypassPermissions",
            team_max_turns=50,
        )

        params = resolve_team_params(project, wg)

        self.assertEqual(params.model, "opus")
        self.assertEqual(params.permission_mode, "acceptEdits")
        self.assertEqual(params.max_turns, 100)
        self.assertEqual(params.max_cost_usd, 10.0)
        self.assertEqual(params.max_time_seconds, 600)

    def test_defaults(self) -> None:
        params = TeamParams()

        self.assertEqual(params.model, "sonnet")
        self.assertEqual(params.permission_mode, "acceptEdits")
        self.assertEqual(params.max_turns, 30)
        self.assertIsNone(params.max_cost_usd)
        self.assertIsNone(params.max_time_seconds)


# ---------------------------------------------------------------------------
# Tests: Create Subteam Job
# ---------------------------------------------------------------------------

class CreateSubteamJobTests(unittest.TestCase):
    """Test job + conversation creation for sub-teams."""

    def test_creates_job_and_conversation(self) -> None:
        session = MagicMock()
        wg = _make_workgroup(workgroup_id="wg-1")
        project = _make_project(project_id="proj-1")

        session.get.side_effect = lambda cls, id_val: {
            (Workgroup, "wg-1"): wg,
            (Project, "proj-1"): project,
        }.get((cls, id_val))

        added_objects = []
        session.add.side_effect = lambda obj: added_objects.append(obj)
        session.flush.return_value = None

        job, conv = create_subteam_job(session, "proj-1", "wg-1", "Build the API")

        self.assertIsInstance(job, Job)
        self.assertIsInstance(conv, Conversation)
        self.assertEqual(conv.kind, "job")
        self.assertEqual(conv.workgroup_id, "wg-1")
        self.assertEqual(job.project_id, "proj-1")
        self.assertIn("Build the API", job.scope)

    def test_raises_for_missing_workgroup(self) -> None:
        session = MagicMock()
        session.get.return_value = None

        with self.assertRaises(ValueError):
            create_subteam_job(session, "proj-1", "wg-bad", "task")

    def test_derives_title_from_message(self) -> None:
        session = MagicMock()
        wg = _make_workgroup(workgroup_id="wg-1")
        project = _make_project(project_id="proj-1")

        session.get.side_effect = lambda cls, id_val: {
            (Workgroup, "wg-1"): wg,
            (Project, "proj-1"): project,
        }.get((cls, id_val))
        session.add.return_value = None
        session.flush.return_value = None

        job, conv = create_subteam_job(
            session, "proj-1", "wg-1",
            "Implement authentication\nWith OAuth2 support",
        )

        self.assertEqual(job.title, "Implement authentication")
        self.assertEqual(conv.name, "Implement authentication")


# ---------------------------------------------------------------------------
# Tests: Project Dispatch Routing
# ---------------------------------------------------------------------------

class ProjectDispatchTests(unittest.TestCase):
    """Test that kind='project' conversations route to project team handler."""

    @patch("teaparty_app.services.agent_runtime._run_project_team_response")
    def test_project_kind_routes_to_handler(self, mock_handler) -> None:
        from teaparty_app.models import Message
        from teaparty_app.services.agent_runtime import run_agent_auto_responses

        session = MagicMock()
        conv = MagicMock(spec=Conversation)
        conv.id = "conv-1"
        conv.kind = "project"
        conv.is_archived = False

        trigger = Message(
            id="msg-1",
            conversation_id="conv-1",
            sender_type="user",
            sender_user_id="user-1",
            content="Start the project",
            requires_response=True,
        )

        project = _make_project()

        # Mock session.exec().first() to return the project
        exec_result = MagicMock()
        exec_result.first.return_value = project
        session.exec.return_value = exec_result

        mock_handler.return_value = []

        run_agent_auto_responses(session, conv, trigger)
        mock_handler.assert_called_once_with(session, conv, trigger, project)

    @patch("teaparty_app.services.agent_runtime._run_project_team_response")
    def test_project_kind_ignores_agent_messages(self, mock_handler) -> None:
        from teaparty_app.models import Message
        from teaparty_app.services.agent_runtime import run_agent_auto_responses

        session = MagicMock()
        conv = MagicMock(spec=Conversation)
        conv.id = "conv-1"
        conv.kind = "project"
        conv.is_archived = False

        trigger = Message(
            id="msg-1",
            conversation_id="conv-1",
            sender_type="agent",
            sender_agent_id="a1",
            content="Some agent response",
            requires_response=False,
        )

        result = run_agent_auto_responses(session, conv, trigger)
        self.assertEqual(result, [])
        mock_handler.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: TeamSession Pre-built Agents
# ---------------------------------------------------------------------------

class TeamSessionPrebuiltAgentsTests(unittest.TestCase):
    """Test TeamSession.run() with pre-built agents_dict."""

    @patch("teaparty_app.services.team_session.subprocess.Popen")
    def test_accepts_prebuilt_agents_dict(self, mock_popen) -> None:
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        team = TeamSession("conv-1", worktree_path="/tmp/test")

        agents_dict = {
            "lead": {"description": "Team lead", "prompt": "You are a lead", "model": "sonnet", "maxTurns": 5},
            "engineering-liaison": {"description": "Engineering workgroup liaison", "prompt": "Relay tasks", "model": "sonnet", "maxTurns": 10},
        }
        slug_to_id = {"lead": "agent-1", "engineering-liaison": "liaison:wg-1"}

        team.run(
            agents_dict=agents_dict,
            slug_to_id=slug_to_id,
            user_message="Start the project",
            lead_slug="lead",
        )

        # Verify lead_slug and lead_agent_id are set correctly
        self.assertEqual(team.lead_slug, "lead")
        self.assertEqual(team.lead_agent_id, "agent-1")

        # Verify agent slugs were set from slug_to_id
        self.assertEqual(team.get_agent_id("lead"), "agent-1")
        self.assertEqual(team.get_agent_id("engineering-liaison"), "liaison:wg-1")

        # Verify the claude command was called with --agents
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        self.assertIn("--agents", cmd)
        agents_idx = cmd.index("--agents")
        agents_json = json.loads(cmd[agents_idx + 1])
        self.assertIn("lead", agents_json)
        self.assertIn("engineering-liaison", agents_json)

    @patch("teaparty_app.services.team_session.subprocess.Popen")
    def test_extra_env_merged(self, mock_popen) -> None:
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        team = TeamSession("conv-1", worktree_path="/tmp/test")

        agents_dict = {
            "lead": {"description": "Lead", "prompt": "Lead", "model": "sonnet", "maxTurns": 5},
        }

        team.run(
            agents_dict=agents_dict,
            slug_to_id={"lead": "a1"},
            user_message="Go",
            lead_slug="lead",
            extra_env={"TEAPARTY_PROJECT_ID": "proj-1", "TEAPARTY_ORG_ID": "org-1"},
        )

        call_args = mock_popen.call_args
        env = call_args[1]["env"]
        self.assertEqual(env["TEAPARTY_PROJECT_ID"], "proj-1")
        self.assertEqual(env["TEAPARTY_ORG_ID"], "org-1")

    @patch("teaparty_app.services.team_session.subprocess.Popen")
    def test_max_turns_override(self, mock_popen) -> None:
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        team = TeamSession("conv-1", worktree_path="/tmp/test")

        agents_dict = {
            "lead": {"description": "Lead", "prompt": "Lead", "model": "sonnet", "maxTurns": 5},
        }

        team.run(
            agents_dict=agents_dict,
            slug_to_id={"lead": "a1"},
            user_message="Go",
            lead_slug="lead",
            max_turns_override=50,
        )

        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        turns_idx = cmd.index("--max-turns")
        self.assertEqual(cmd[turns_idx + 1], "50")


if __name__ == "__main__":
    unittest.main()
