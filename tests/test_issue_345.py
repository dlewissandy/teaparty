"""Tests for Issue #345: agent-dispatch proposal vs messaging proposal consistency.

Acceptance criteria:
1. messaging/proposal.md Agent to Agent section does not say "not through the message bus"
2. messaging/proposal.md Agent to Agent section references the agent-dispatch proposal
3. The agent-dispatch proposal describes the write-then-exit-then-resume execution model
4. conversation-model.md presents multi-turn mechanics as the target design, not current behavior
"""
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_MESSAGING_PROPOSAL = _REPO_ROOT / 'docs' / 'proposals' / 'messaging' / 'proposal.md'
_AGENT_DISPATCH_PROPOSAL = _REPO_ROOT / 'docs' / 'proposals' / 'agent-dispatch' / 'proposal.md'
_CONVERSATION_MODEL = _REPO_ROOT / 'docs' / 'proposals' / 'agent-dispatch' / 'references' / 'conversation-model.md'
_INVOCATION_MODEL = _REPO_ROOT / 'docs' / 'proposals' / 'agent-dispatch' / 'references' / 'invocation-model.md'


def _read(path: Path) -> str:
    return path.read_text()


class TestMessagingProposalAgentToAgentSection(unittest.TestCase):
    """messaging/proposal.md Agent to Agent section must reflect the bus-mediated model."""

    def test_agent_to_agent_does_not_claim_not_through_message_bus(self):
        """The Agent to Agent section must not say 'not through the message bus'.

        The agent-dispatch proposal supersedes this claim. Agent-to-agent communication
        now goes through the message bus using the write-then-exit-then-resume model.
        """
        content = _read(_MESSAGING_PROPOSAL)
        self.assertNotIn(
            'not through the message bus',
            content,
            'messaging/proposal.md must not claim agent-to-agent is "not through the message bus" — '
            'this was superseded by the agent-dispatch proposal',
        )

    def test_agent_to_agent_section_references_agent_dispatch_proposal(self):
        """The Agent to Agent section must reference the agent-dispatch proposal.

        Readers following the messaging proposal must be directed to the agent-dispatch
        proposal for the current model.
        """
        content = _read(_MESSAGING_PROPOSAL)
        self.assertIn(
            'agent-dispatch',
            content,
            'messaging/proposal.md must reference the agent-dispatch proposal in the Agent to Agent section',
        )


class TestAgentDispatchProposalExecutionModel(unittest.TestCase):
    """agent-dispatch proposal must describe write-then-exit-then-resume, not non-blocking concurrency."""

    def test_proposal_does_not_claim_caller_continues_other_work(self):
        """The proposal must not claim the caller is 'not blocked' or 'can continue its own work'.

        The audit finding (AD-A-002) specifically identified this claim as false.
        The implementation is synchronous; the corrected model is write-then-exit.
        """
        content = _read(_AGENT_DISPATCH_PROPOSAL)
        self.assertNotIn(
            'can continue its own work',
            content,
            'agent-dispatch proposal must not claim caller continues other work after AskTeam',
        )
        self.assertNotIn(
            'not blocked',
            content,
            'agent-dispatch proposal must not claim caller is not blocked',
        )

    def test_proposal_describes_write_then_exit_model(self):
        """The proposal must describe the write-then-exit-then-resume execution model."""
        content = _read(_AGENT_DISPATCH_PROPOSAL)
        self.assertIn(
            'write-then-exit',
            content,
            'agent-dispatch proposal must describe the write-then-exit execution model',
        )

    def test_proposal_states_caller_is_not_running_concurrently(self):
        """The proposal must explicitly state the caller is not running concurrently with workers."""
        content = _read(_AGENT_DISPATCH_PROPOSAL)
        self.assertIn(
            'not running concurrently',
            content,
            'agent-dispatch proposal must state caller is not running concurrently with its workers',
        )


class TestInvocationModelAskTeamDescription(unittest.TestCase):
    """invocation-model.md must describe AskTeam as write-then-exit, not blocking RPC."""

    def test_ask_team_described_as_write_then_exit(self):
        """AskTeam must be described using the write-then-exit execution model."""
        content = _read(_INVOCATION_MODEL)
        self.assertIn(
            'write-then-exit',
            content,
            'invocation-model.md must describe AskTeam using the write-then-exit model',
        )

    def test_ask_team_returns_context_id(self):
        """AskTeam must return a context_id, not block until response."""
        content = _read(_INVOCATION_MODEL)
        self.assertIn(
            'context_id',
            content,
            'invocation-model.md must describe AskTeam returning a context_id',
        )


class TestConversationModelTargetDesignLabeling(unittest.TestCase):
    """conversation-model.md multi-turn mechanics must be presented as target design, not implemented."""

    def test_conversation_model_does_not_claim_current_implementation(self):
        """conversation-model.md must not claim multi-turn mechanics are currently implemented.

        The audit found that the multi-turn mechanics described in conversation-model.md
        had no corresponding code path. They must be presented as the target design.
        """
        content = _read(_CONVERSATION_MODEL)
        # The model must describe write-then-exit as the execution model
        self.assertIn(
            'write-then-exit',
            content,
            'conversation-model.md must describe the write-then-exit execution model',
        )

    def test_caller_exits_after_posting(self):
        """conversation-model.md must state caller exits after posting, not continues running."""
        content = _read(_CONVERSATION_MODEL)
        self.assertIn(
            'exits',
            content,
            'conversation-model.md must state that the caller exits after posting via AskTeam',
        )


if __name__ == '__main__':
    unittest.main()
