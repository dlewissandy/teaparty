"""Bus dispatcher: routing table and transport-level authorization for agent-to-agent messaging.

The RoutingTable holds the set of permitted ``(sender, recipient)``
pairs derived from workgroup membership at session start, where each
slot is the agent's **name** as it appears in the roster (not a
fictional scoped id).  An agent's name is its identity: 1:1
correspondence between the string and the agent — no aliases, no
translation map, no parallel namespace.  A roster with duplicate names
is a configuration error and must be rejected at load time.

The BusDispatcher wraps the table and is the independent enforcement
point — every bus post goes through it, whether via the Send MCP tool
or via a direct bus write.

Routing rules:
  - Within-workgroup: all agent pairs (both directions)
  - Cross-workgroup: workgroup lead ↔ project lead only
  - Cross-project: project lead ↔ OM only
  - Workers have no direct route to the project lead or OM

See docs/proposals/agent-dispatch/references/routing.md for the full specification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class RoutingError(Exception):
    """Raised when a message violates the routing policy."""


class DuplicateAgentName(ValueError):
    """Raised when a roster contains the same agent name twice.

    Agent names are identifiers; uniqueness within a routing scope is a
    correctness precondition, not a soft constraint.  Caller config is
    wrong and must be fixed.
    """


@dataclass
class RoutingTable:
    """Set of permitted (sender_name, recipient_name) pairs.

    Built at session start from workgroup membership.  Held in memory
    by the BusEventListener for the session's duration.  Not persisted
    between sessions.
    """

    _pairs: set[tuple[str, str]] = field(default_factory=set)

    def add_pair(self, sender: str, recipient: str) -> None:
        """Add a permitted directed communication channel."""
        self._pairs.add((sender, recipient))

    def allows(self, sender: str, recipient: str) -> bool:
        """Return True if the (sender, recipient) pair is in the routing table."""
        return (sender, recipient) in self._pairs

    def pairs(self) -> Iterable[tuple[str, str]]:
        """Yield all (sender, recipient) pairs in the table."""
        yield from self._pairs

    @classmethod
    def from_workgroups(
        cls,
        workgroups: list[dict],
        *,
        project_lead_name: str,
        om_agent_name: str,
    ) -> 'RoutingTable':
        """Derive the routing table for one project from its workgroup definitions.

        Args:
            workgroups: List of workgroup dicts with 'name', 'lead', and
                'agents' keys.  Each agent entry has a 'role' key whose
                value is the agent's name (its identity in the roster).
            project_lead_name: The project lead's agent name (e.g.
                ``teaparty-lead``).  Connected directly to the OM.
            om_agent_name: The OM's agent name (e.g. ``office-manager``).

        Raises:
            DuplicateAgentName: if any agent name appears more than once
            across the project's workgroups.  Names are identifiers;
            uniqueness is a precondition.
        """
        table = cls()

        # Project lead ↔ OM (cross-project gateway)
        table.add_pair(project_lead_name, om_agent_name)
        table.add_pair(om_agent_name, project_lead_name)

        # Validate uniqueness: every workgroup lead and every agent role
        # name must be a unique identifier within this project.
        seen: set[str] = set()
        for wg in workgroups:
            for name in [wg.get('lead', '')] + [
                a['role'] for a in wg.get('agents', [])
            ]:
                if not name:
                    continue
                if name in seen:
                    raise DuplicateAgentName(
                        f'Agent name {name!r} appears more than once in '
                        f'project workgroups.  Names are identifiers; '
                        f'rename one or use a workgroup-prefixed role.',
                    )
                seen.add(name)

        for wg in workgroups:
            agent_names = [a['role'] for a in wg.get('agents', [])]
            wg_lead = wg.get('lead', '')

            # Within-workgroup: every agent can reach every other agent.
            for i, a in enumerate(agent_names):
                for j, b in enumerate(agent_names):
                    if i != j:
                        table.add_pair(a, b)

            # Cross-workgroup: workgroup lead ↔ project lead only.
            if wg_lead:
                table.add_pair(wg_lead, project_lead_name)
                table.add_pair(project_lead_name, wg_lead)

        return table

    @classmethod
    def from_management_roster(
        cls,
        roster: dict[str, dict],
        *,
        om_agent_name: str,
    ) -> 'RoutingTable':
        """Derive the routing table for the OM from its roster.

        Args:
            roster: The OM's roster dict (keys are agent names — the
                identifiers used everywhere else: ``teaparty-lead``,
                ``proxy``, etc.).
            om_agent_name: The OM's agent name (e.g. ``office-manager``).

        Returns:
            A RoutingTable with OM ↔ each roster member.

        Raises:
            DuplicateAgentName: if the roster contains the OM's own name
            (the OM is the subject of the roster, not a member).
        """
        table = cls()
        for agent_name in roster:
            if agent_name == om_agent_name:
                raise DuplicateAgentName(
                    f'OM {om_agent_name!r} appears in its own roster; '
                    f'the OM is the subject, not a member.',
                )
            table.add_pair(om_agent_name, agent_name)
            table.add_pair(agent_name, om_agent_name)
        return table

    @classmethod
    def merge(cls, tables: list['RoutingTable']) -> 'RoutingTable':
        """Merge multiple routing tables into one (e.g. for multi-project sessions)."""
        merged = cls()
        for table in tables:
            for sender, recipient in table.pairs():
                merged.add_pair(sender, recipient)
        return merged


class BusDispatcher:
    """Transport-level enforcement of routing rules.

    Sits between the bus transport and the agent invocation layer.
    Every incoming post — whether from the Send MCP tool or a direct
    bus write — must pass through ``authorize()`` before being
    accepted.

    The Send MCP tool performs a client-side pre-check
    (``UnknownMemberError`` when the named member is absent from the
    roster).  BusDispatcher is the independent enforcement point that
    makes routing correctness independent of all callers going through
    Send.
    """

    def __init__(self, routing_table: RoutingTable) -> None:
        self._table = routing_table

    def authorize(self, sender: str, recipient: str) -> None:
        """Verify the sender is permitted to post to the recipient.

        Args:
            sender: The agent's name (its roster identity) posting the
                message.
            recipient: The intended recipient's agent name.

        Raises:
            RoutingError: If no routing entry exists for (sender, recipient).
        """
        if not self._table.allows(sender, recipient):
            raise RoutingError(
                f'No routing entry: {sender!r} → {recipient!r}.  '
                f'Cross-project posts must go through the OM; '
                f'cross-workgroup posts must go through the project lead.',
            )
