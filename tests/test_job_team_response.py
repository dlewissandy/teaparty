import unittest
from unittest.mock import MagicMock, patch

from teaparty_app.models import Agent, Conversation, Message
from teaparty_app.services.agent_runtime import (
    _is_each_invocation,
    _is_team_invocation,
    run_agent_auto_responses,
)


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


class InvocationDetectionTests(unittest.TestCase):
    """@each and @all/@team are mutually exclusive collaboration modes:
    - @each  -> independent fan-out (N separate claude invocations, isolated)
    - @all/@team -> Claude multi-agent team (persistent team session)
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
    - @all/@team -> _run_team_response (persistent team session)
    - @name      -> _run_single_agent_responses with ONLY the named agent
    - default    -> _run_team_response when multiple agents, single otherwise
    Only user messages trigger routing; agent messages produce no response.
    When both @each and @all/@team appear, @each takes priority."""

    @patch("teaparty_app.services.agent_runtime._run_team_response")
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

    @patch("teaparty_app.services.agent_runtime._run_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_team_routes_to_multi_agent_team(
        self, mock_agents_for, mock_run_single, mock_run_team
    ) -> None:
        """@team routes to _run_team_response: a persistent team session
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

    @patch("teaparty_app.services.agent_runtime._run_team_response")
    @patch("teaparty_app.services.agent_runtime._run_single_agent_responses")
    @patch("teaparty_app.services.agent_runtime._agents_for_auto_response")
    def test_all_routes_to_multi_agent_team(
        self, mock_agents_for, mock_run_single, mock_run_team
    ) -> None:
        """@all routes to _run_team_response: a persistent team session
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

    @patch("teaparty_app.services.agent_runtime._run_team_response")
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
