"""D-A-I role enforcement for chat participation.

The Decider-Advisor-Informed role model determines who can speak in
team chats.  Deciders can respond to escalations, intervene, and
withdraw.  Advisors can interject with advisory input.  Informed
members can read but not write.

See docs/proposals/chat-experience/proposal.md (Pattern 2: Who can speak)
and docs/proposals/team-configuration/proposal.md (Human Roles table).

Issue #252.
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.config_reader import Human


class DAIRole(Enum):
    DECIDER = 'decider'
    ADVISOR = 'advisor'
    INFORMED = 'informed'


class InformedSendError(PermissionError):
    """Raised when an informed member attempts to write to a conversation."""

    def __init__(self, sender: str):
        super().__init__(
            f"Informed member '{sender}' cannot write to conversations"
        )
        self.sender = sender


class RoleEnforcer:
    """Checks D-A-I roles before accepting chat input.

    Configured with a mapping of human names to DAIRole values.
    Senders not in the map are assumed to be agents or system
    components, and pass through without checks.
    """

    def __init__(self, role_map: dict[str, DAIRole]):
        self._roles = dict(role_map)

    @classmethod
    def from_humans(cls, humans: list[Human]) -> RoleEnforcer:
        """Build a RoleEnforcer from a list of Human config entries."""
        return cls({h.name: DAIRole(h.role) for h in humans})

    def get_role(self, sender: str) -> DAIRole | None:
        """Return the sender's role, or None if not a known human."""
        return self._roles.get(sender)

    def check_send(self, sender: str) -> None:
        """Raise InformedSendError if sender is an informed member.

        Non-human senders (not in the role map) pass through.
        """
        role = self._roles.get(sender)
        if role is DAIRole.INFORMED:
            raise InformedSendError(sender)

    def is_advisory(self, sender: str) -> bool:
        """True if the sender is an advisor (input should be framed as advisory)."""
        return self._roles.get(sender) is DAIRole.ADVISOR
