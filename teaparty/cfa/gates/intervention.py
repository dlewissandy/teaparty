"""Intervention queue — holds unsolicited human messages for turn-boundary delivery.

The human can type in a job or task chat at any time.  Since a running
`claude -p` process cannot receive input mid-turn, the orchestrator
queues the message and injects it as the next prompt via ``--resume``
when the current turn completes.

Issue #246.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teaparty.messaging.conversations import MessageBusAdapter
    from teaparty.util.role_enforcer import RoleEnforcer


@dataclass
class InterventionMessage:
    """A single queued intervention."""
    content: str
    sender: str
    timestamp: float


class InterventionQueue:
    """Thread-safe queue for pending human interventions.

    The bridge (or messaging bus) calls ``enqueue()`` from any thread.
    The orchestrator calls ``has_pending()`` and ``drain()`` from the
    async event loop at turn boundaries.

    Optionally records messages in a ``MessageBusAdapter`` for audit.
    Optional ``role_enforcer`` attribute: when set, ``enqueue()`` checks
    the sender's D-A-I role before accepting input.
    """

    role_enforcer: 'RoleEnforcer | None'

    def __init__(
        self,
        message_bus: 'MessageBusAdapter | None' = None,
        conversation_id: str = '',
    ):
        self._lock = threading.Lock()
        self._messages: list[InterventionMessage] = []
        self._message_bus = message_bus
        self._conversation_id = conversation_id
        self.role_enforcer = None

    def enqueue(self, content: str, *, sender: str = 'human') -> None:
        """Add an intervention message to the queue.

        If a role enforcer is configured, checks the sender's D-A-I role
        first (informed members are blocked).
        If a message bus is configured, the message is also persisted
        there for audit trail.
        """
        if self.role_enforcer is not None:
            self.role_enforcer.check_send(sender)
        msg = InterventionMessage(
            content=content,
            sender=sender,
            timestamp=time.time(),
        )
        with self._lock:
            self._messages.append(msg)

        if self._message_bus and self._conversation_id:
            self._message_bus.send(self._conversation_id, sender, content)

    def has_pending(self) -> bool:
        """True if there are messages waiting for delivery."""
        with self._lock:
            return len(self._messages) > 0

    def drain(self) -> list[InterventionMessage]:
        """Remove and return all pending messages."""
        with self._lock:
            msgs = list(self._messages)
            self._messages.clear()
        return msgs


def build_intervention_prompt(
    messages: list[InterventionMessage],
    role_enforcer: 'RoleEnforcer | None' = None,
) -> str:
    """Build the prompt injected via --resume when delivering an intervention.

    Multiple messages are coalesced into a single prompt.  The prompt
    frames the intervention per the CfA extensions spec: the lead has
    full discretion to continue with adjustment, backtrack, or withdraw.

    When a ``role_enforcer`` is provided, advisor messages are framed as
    advisory input (lower weight than authoritative decider input).
    """
    has_advisory = False
    parts: list[str] = []
    for msg in messages:
        is_advisor = role_enforcer and role_enforcer.is_advisory(msg.sender)
        if is_advisor:
            has_advisory = True
            parts.append(f'[Advisory input from {msg.sender}]: {msg.content}')
        elif msg.sender == 'human':
            parts.append(msg.content)
        else:
            parts.append(f'[{msg.sender}]: {msg.content}')

    body = '\n\n'.join(parts)

    prompt = (
        '[CfA INTERVENE: Unsolicited human input received at turn boundary.]\n\n'
        f'{body}\n\n'
        'You have full discretion: continue with adjustment, '
        'backtrack to an earlier phase, or withdraw. '
        'Assess whether this changes the current trajectory.'
    )

    if has_advisory:
        prompt += (
            '\n\nNote: advisory input carries lower weight than '
            'authoritative decider input. Consider it but you are '
            'not obligated to follow it.'
        )

    return prompt
