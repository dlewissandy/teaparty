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
            'agent-dispatch proposal must not claim caller continues other work after Send',
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


class TestInvocationModelSendDescription(unittest.TestCase):
    """invocation-model.md must describe Send as write-then-exit, not blocking RPC."""

    def test_send_described_as_write_then_exit(self):
        """Send must be described using the write-then-exit execution model."""
        content = _read(_INVOCATION_MODEL)
        self.assertIn(
            'write-then-exit',
            content,
            'invocation-model.md must describe Send using the write-then-exit model',
        )

    def test_send_returns_context_id(self):
        """Send must return a context_id, not block until response."""
        content = _read(_INVOCATION_MODEL)
        self.assertIn(
            'context_id',
            content,
            'invocation-model.md must describe Send returning a context_id',
        )


class TestConversationModelImplementationLabeling(unittest.TestCase):
    """conversation-model.md multi-turn mechanics must be explicitly labeled as implemented."""

    def test_conversation_model_explicitly_labels_mechanics_as_implemented(self):
        """conversation-model.md must explicitly label multi-turn mechanics as implemented.

        Issue #345 required the label to say "Target design" until a code path existed.
        Issues #358 and #359 completed that code path. The label must now say
        "Implementation status" and confirm the model is implemented.
        """
        content = _read(_CONVERSATION_MODEL)
        self.assertIn(
            'Implementation status',
            content,
            'conversation-model.md must contain an explicit "Implementation status" label in the '
            'Multi-Turn Mechanics section confirming the model is implemented',
        )

    def test_conversation_model_acknowledges_retirement_of_dispatch_listener(self):
        """conversation-model.md must record that DispatchListener was retired.

        The status callout must preserve the historical note that AskTeam/DispatchListener
        were the prior implementation, so readers can understand the transition.
        """
        content = _read(_CONVERSATION_MODEL)
        self.assertIn(
            'DispatchListener',
            content,
            'conversation-model.md must acknowledge that DispatchListener has been retired '
            '(issues #358, #359) — preserves the historical transition record',
        )

    def test_proposal_explicitly_labels_agent_to_agent_implementation_status(self):
        """agent-dispatch/proposal.md must contain an "Implementation status" note.

        Issue #345 required this label to distinguish design from implementation.
        Issues #358 and #359 completed the implementation; the note now confirms
        Send/Reply are live and AskTeam/DispatchListener are retired.
        """
        content = _read(_AGENT_DISPATCH_PROPOSAL)
        self.assertIn(
            'Implementation status',
            content,
            'agent-dispatch/proposal.md must contain an "Implementation status" note',
        )


if __name__ == '__main__':
    unittest.main()
