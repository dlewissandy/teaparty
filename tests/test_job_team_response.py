import json
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch, AsyncMock

from teaparty_app.models import Agent, Conversation, Message, Workgroup
from teaparty_app.services.agent_runtime import (
    _is_each_invocation,
    _is_team_invocation,
    _run_job_team_response,
    run_agent_auto_responses,
)
from teaparty_app.services.claude_runner import ClaudeResult


def _make_agent(*, agent_id: str, name: str, role: str = "", model: str = "sonnet") -> Agent:
    return Agent(
        id=agent_id,
        workgroup_id="wg-1",
        created_by_user_id="user-1",
        name=name,
        role=role,
        model=model,
        tool_names=[],
    )


def _make_conversation(*, conversation_id: str = "conv-1", kind: str = "job") -> Conversation:
    return Conversation(
        id=conversation_id,
        workgroup_id="wg-1",
        kind=kind,
    )


def _make_trigger(*, message_id: str = "msg-1") -> Message:
    return Message(
        id=message_id,
        conversation_id="conv-1",
        sender_type="user",
        sender_user_id="user-1",
        content="What should we do?",
    )


def _make_result(*, text: str = "", events: list[dict] | None = None, is_error: bool = False, error: str | None = None) -> ClaudeResult:
    return ClaudeResult(
        text=text,
        events=events or [],
        is_error=is_error,
        error=error,
        model="sonnet",
        input_tokens=100,
        output_tokens=50,
        duration_ms=1000,
    )


def _fake_materialized_files(session, workgroup, conversation):
    """A fake context manager replacing materialized_files for tests."""
    @contextmanager
    def _cm():
        ctx = MagicMock()
        ctx.dir_path = "/tmp/test-workdir"
        ctx.settings_json = '{"hooks":{}}'
        ctx.original_file_ids = {}
        yield ctx
    return _cm()


class JobTeamResponseTests(unittest.TestCase):
    """@all/@team uses Claude's multi-agent teams: a SINGLE claude invocation
    with all agents passed via --agents and --output-format stream-json
    --verbose.  The structured events show all inter-agent communication
    directly — no text parsing needed.  The lead delegates to teammates
    autonomously via the Task tool.

    This is NOT hand-rolled orchestration.  TeaParty does not chain agent
    outputs, feed one agent's response to the next, or script collaboration.
    Claude's built-in multi-agent mechanism handles coordination."""

    def _setup_mocks(self):
        """Common mock setup for session and workgroup."""
        session = MagicMock()
        session.get.return_value = Workgroup(id="wg-1", name="Test", owner_id="user-1")
        return session

    @patch("teaparty_app.services.agent_runtime.materialized_files", side_effect=_fake_materialized_files)
    @patch("teaparty_app.services.agent_runtime.commit_with_retry")
    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="User says: What should we do?")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_task_delegation_produces_per_agent_messages(
        self, mock_run, mock_user_msg, mock_usage, mock_commit, mock_materialize
    ) -> None:
        """When the lead delegates via Task tool, the stream-json events
        contain tool_use/tool_result pairs that attribute each subagent's
        response.  Each becomes a separate Message.  This is the primary
        collaboration path — one claude invocation, autonomous delegation,
        structured event attribution."""
        mock_run.return_value = _make_result(
            text="Done",
            events=[
                {"type": "assistant", "message": {"content": [
                    {"type": "text", "text": "Delegating to the team."},
                    {"type": "tool_use", "id": "tu-1", "name": "Task", "input": {"name": "bob"}},
                ]}},
                {"type": "tool_result", "tool_use_id": "tu-1", "content": "Bob's analysis."},
                {"type": "result", "result": "Done", "usage": {}},
            ],
        )

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice", role="Lead")
        bob = _make_agent(agent_id="a2", name="Bob", role="Analyst")

        messages = _run_job_team_response(session, conv, trigger, [alice, bob])

        # One claude invocation for the entire team — not one per agent.
        mock_run.assert_called_once()

        # Two messages: lead text + Bob's delegated contribution.
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].sender_agent_id, "a1")
        self.assertIn("Delegating", messages[0].content)
        self.assertEqual(messages[1].sender_agent_id, "a2")
        self.assertIn("Bob's analysis", messages[1].content)

    @patch("teaparty_app.services.agent_runtime.materialized_files", side_effect=_fake_materialized_files)
    @patch("teaparty_app.services.agent_runtime.commit_with_retry")
    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="msg")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_all_agents_passed_in_single_invocation(
        self, mock_run, mock_user_msg, mock_usage, mock_commit, mock_materialize
    ) -> None:
        """The multi-agent team runs a SINGLE claude invocation with ALL agents
        in agents_json and the lead specified via agent_name.  This is the core
        contract: one process, autonomous delegation — not N separate
        invocations."""
        mock_run.return_value = _make_result(text="Team output.", events=[])

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice")
        bob = _make_agent(agent_id="a2", name="Bob")
        charlie = _make_agent(agent_id="a3", name="Charlie")

        _run_job_team_response(session, conv, trigger, [alice, bob, charlie])

        # Exactly one claude invocation for the whole team.
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]

        # Lead is the first candidate.
        self.assertEqual(call_kwargs["agent_name"], "Alice")

        # All three agents present in agents_json.
        agents_dict = json.loads(call_kwargs["agents_json"])
        self.assertIn("Alice", agents_dict)
        self.assertIn("Bob", agents_dict)
        self.assertIn("Charlie", agents_dict)
        self.assertEqual(len(agents_dict), 3)

    @patch("teaparty_app.services.agent_runtime.materialized_files", side_effect=_fake_materialized_files)
    @patch("teaparty_app.services.agent_runtime.commit_with_retry")
    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="msg")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_lead_attribution_fallback(
        self, mock_run, mock_user_msg, mock_usage, mock_commit, mock_materialize
    ) -> None:
        """When the stream-json events contain no Task delegation at all —
        just the lead's own text — everything is attributed to the lead
        agent as a last resort."""
        mock_run.return_value = _make_result(
            text="A plain response with no structure.",
            events=[],
        )

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice")
        bob = _make_agent(agent_id="a2", name="Bob")

        messages = _run_job_team_response(session, conv, trigger, [alice, bob])

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].sender_agent_id, "a1")
        self.assertIn("plain response", messages[0].content)

    @patch("teaparty_app.services.agent_runtime.materialized_files", side_effect=_fake_materialized_files)
    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="msg")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_error_result_creates_error_message(
        self, mock_run, mock_user_msg, mock_usage, mock_materialize
    ) -> None:
        """When the claude CLI invocation fails, a single error Message is
        created and attributed to the lead agent."""
        mock_run.return_value = _make_result(
            is_error=True,
            error="CLI crashed",
        )

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice")

        messages = _run_job_team_response(session, conv, trigger, [alice])

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].sender_agent_id, "a1")
        self.assertIn("Agent error", messages[0].content)

    @patch("teaparty_app.services.agent_runtime.materialized_files", side_effect=_fake_materialized_files)
    @patch("teaparty_app.services.agent_runtime.commit_with_retry")
    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="msg")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_single_agent_team_still_uses_team_path(
        self, mock_run, mock_user_msg, mock_usage, mock_commit, mock_materialize
    ) -> None:
        """Even with a single agent, @all/@team runs through the multi-agent
        team path (not the fan-out path).  The code path is the same regardless
        of team size."""
        mock_run.return_value = _make_result(
            text="Solo agent response.",
            events=[],
        )

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice")

        messages = _run_job_team_response(session, conv, trigger, [alice])

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].sender_agent_id, "a1")
        self.assertEqual(messages[0].content, "Solo agent response.")

    @patch("teaparty_app.services.agent_runtime.materialized_files", side_effect=_fake_materialized_files)
    @patch("teaparty_app.services.agent_runtime.commit_with_retry")
    @patch("teaparty_app.services.agent_runtime.record_llm_usage")
    @patch("teaparty_app.services.agent_runtime.build_user_message", return_value="msg")
    @patch("teaparty_app.services.agent_runtime.run_claude", new_callable=AsyncMock)
    def test_run_claude_receives_workspace_context(
        self, mock_run, mock_user_msg, mock_usage, mock_commit, mock_materialize
    ) -> None:
        """The team invocation passes the materialized workspace directory and
        settings.json to claude, so agents operate on the workgroup's files."""
        mock_run.return_value = _make_result(text="Response.", events=[])

        session = self._setup_mocks()
        conv = _make_conversation()
        trigger = _make_trigger()
        alice = _make_agent(agent_id="a1", name="Alice")

        _run_job_team_response(session, conv, trigger, [alice])

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        self.assertEqual(call_kwargs["cwd"], "/tmp/test-workdir")
        self.assertEqual(call_kwargs["settings_json"], '{"hooks":{}}')


class InvocationDetectionTests(unittest.TestCase):
    """@each and @all/@team are mutually exclusive collaboration modes:
    - @each  -> independent fan-out (N separate claude invocations, isolated)
    - @all/@team -> Claude multi-agent team (1 claude invocation, --agents)
    @each is NOT a synonym for @all.  @team IS a synonym for @all."""

    def test_each_matches_at_each(self) -> None:
        self.assertTrue(_is_each_invocation("@each what do you think?"))

    def test_each_does_not_match_at_all(self) -> None:
        self.assertFalse(_is_each_invocation("@all what do you think?"))

    def test_each_is_case_insensitive(self) -> None:
        self.assertTrue(_is_each_invocation("@Each weigh in please"))

    def test_team_matches_at_team(self) -> None:
        self.assertTrue(_is_team_invocation("@team let's discuss"))

    def test_team_matches_at_all(self) -> None:
        self.assertTrue(_is_team_invocation("@all let's discuss"))

    def test_team_does_not_match_at_each(self) -> None:
        self.assertFalse(_is_team_invocation("@each let's discuss"))


class RoutingTests(unittest.TestCase):
    """Job conversation routing contract:
    - @each      -> _run_single_agent_responses with ALL candidates (fan-out)
    - @all/@team -> _run_job_team_response (Claude multi-agent team)
    - @name      -> _run_single_agent_responses with ONLY the named agent
    - default    -> _run_single_agent_responses with ONLY the lead agent
    Only user messages trigger routing; agent messages produce no response.
    When both @each and @all/@team appear, @each takes priority."""

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_each_fans_out_via_single_agent_responses(
        self, mock_agents_for, mock_run_single, mock_run_team
    ) -> None:
        """@each fans out independently: _run_single_agent_responses is called
        with ALL candidates.  Each agent gets its own isolated claude
        invocation.  The team path is NOT used."""
        alice = _make_agent(agent_id="a1", name="Alice")
        bob = _make_agent(agent_id="a2", name="Bob")
        mock_agents_for.return_value = [alice, bob]
        mock_run_single.return_value = []

        session = MagicMock()
        conv = _make_conversation(kind="job")
        trigger = _make_trigger()
        trigger.content = "@each what do you think?"
        trigger.sender_type = "user"

        run_agent_auto_responses(session, conv, trigger)

        mock_run_single.assert_called_once()
        passed_candidates = mock_run_single.call_args[0][3]
        self.assertEqual(len(passed_candidates), 2)
        self.assertIn(alice, passed_candidates)
        self.assertIn(bob, passed_candidates)
        mock_run_team.assert_not_called()

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_team_routes_to_multi_agent_team(
        self, mock_agents_for, mock_run_single, mock_run_team
    ) -> None:
        """@team routes to _run_job_team_response: a single claude invocation
        where the lead delegates to teammates autonomously.  The fan-out path
        is NOT used.  @team is a synonym for @all."""
        alice = _make_agent(agent_id="a1", name="Alice")
        bob = _make_agent(agent_id="a2", name="Bob")
        mock_agents_for.return_value = [alice, bob]
        mock_run_team.return_value = []

        session = MagicMock()
        conv = _make_conversation(kind="job")
        trigger = _make_trigger()
        trigger.content = "@team let's discuss"
        trigger.sender_type = "user"

        run_agent_auto_responses(session, conv, trigger)

        mock_run_team.assert_called_once()
        mock_run_single.assert_not_called()

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_all_routes_to_multi_agent_team(
        self, mock_agents_for, mock_run_single, mock_run_team
    ) -> None:
        """@all routes to _run_job_team_response: a single claude invocation
        where the lead delegates to teammates autonomously.  The fan-out path
        is NOT used."""
        alice = _make_agent(agent_id="a1", name="Alice")
        bob = _make_agent(agent_id="a2", name="Bob")
        mock_agents_for.return_value = [alice, bob]
        mock_run_team.return_value = []

        session = MagicMock()
        conv = _make_conversation(kind="job")
        trigger = _make_trigger()
        trigger.content = "@all let's discuss"
        trigger.sender_type = "user"

        run_agent_auto_responses(session, conv, trigger)

        mock_run_team.assert_called_once()
        mock_run_single.assert_not_called()

    @patch("teaparty_app.services.agent_runtime._run_job_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_each_takes_priority_over_all(
        self, mock_agents_for, mock_run_single, mock_run_team
    ) -> None:
        """When both @each and @all appear in the same message, @each wins.
        The message is treated as independent fan-out, not a multi-agent team."""
        alice = _make_agent(agent_id="a1", name="Alice")
        bob = _make_agent(agent_id="a2", name="Bob")
        mock_agents_for.return_value = [alice, bob]
        mock_run_single.return_value = []

        session = MagicMock()
        conv = _make_conversation(kind="job")
        trigger = _make_trigger()
        trigger.content = "@each @all what do you think?"
        trigger.sender_type = "user"

        run_agent_auto_responses(session, conv, trigger)

        mock_run_single.assert_called_once()
        mock_run_team.assert_not_called()


if __name__ == "__main__":
    unittest.main()
