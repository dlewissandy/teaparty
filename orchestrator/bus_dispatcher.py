"""Bus dispatcher: routing table and transport-level authorization for agent-to-agent messaging.

The RoutingTable holds the set of permitted (sender_agent_id, recipient_agent_id) pairs
derived from workgroup membership at session start.  The BusDispatcher wraps the table
and is the independent enforcement point — every bus post goes through it, whether via
the Send MCP tool or via a direct bus write.

Agent identity format: {project_name}/{workgroup_name}/{role_name}
  e.g. my-backend/coding/team-lead, my-backend/coding/specialist
Project lead: {project_name}/lead
OM (org-level): 'om'

Routing rules (from docs/proposals/agent-dispatch/references/routing.md):
  - Within-workgroup: all agent pairs (both directions)
  - Cross-workgroup: workgroup lead ↔ project lead only
  - Cross-project: project lead ↔ om only
  - Workers have no direct route to the project lead or OM

See docs/proposals/agent-dispatch/references/routing.md for the full specification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class RoutingError(Exception):
    """Raised when a message violates the routing policy."""


@dataclass
class RoutingTable:
    """Set of permitted (sender_agent_id, recipient_agent_id) pairs.

    Built at session start from workgroup membership.  Held in memory by the
    BusEventListener for the session's duration.  Not persisted between sessions.
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
        project_name: str,
        om_agent_id: str = 'om',
    ) -> 'RoutingTable':
        """Derive the routing table for one project from its workgroup definitions.

        Args:
            workgroups: List of workgroup dicts with 'name', 'lead', and 'agents' keys.
                        Each agent entry must have a 'role' key.
            project_name: The project name prefix for all agent IDs.
            om_agent_id: Agent ID for the office manager (default: 'om').

        Returns:
            A RoutingTable with all permitted (sender, recipient) pairs for this project.
        """
        table = cls()
        project_lead = f'{project_name}/lead'

        # Project lead ↔ OM (cross-project gateway)
        table.add_pair(project_lead, om_agent_id)
        table.add_pair(om_agent_id, project_lead)

        for wg in workgroups:
            wg_name = wg['name']
            agents = wg.get('agents', [])
            lead_role = wg.get('lead', '')

            # Build scoped agent IDs for this workgroup
            agent_ids = [
                f'{project_name}/{wg_name}/{a["role"]}' for a in agents
            ]
            lead_id = f'{project_name}/{wg_name}/{lead_role}' if lead_role else None

            # Within-workgroup: every agent can reach every other agent (both directions)
            for i, a_id in enumerate(agent_ids):
                for j, b_id in enumerate(agent_ids):
                    if i != j:
                        table.add_pair(a_id, b_id)

            # Cross-workgroup: workgroup lead ↔ project lead only
            if lead_id:
                table.add_pair(lead_id, project_lead)
                table.add_pair(project_lead, lead_id)

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

    Sits between the bus transport and the agent invocation layer.  Every
    incoming post — whether from the Send MCP tool or a direct bus write —
    must pass through authorize() before being accepted.

    The Send MCP tool performs a client-side pre-check (UnknownMemberError
    when the named member is absent from the roster).  BusDispatcher is the
    independent enforcement point that makes routing correctness independent
    of all callers going through Send.
    """

    def __init__(self, routing_table: RoutingTable) -> None:
        self._table = routing_table

    def authorize(self, sender_agent_id: str, recipient_agent_id: str) -> None:
        """Verify the sender is permitted to post to the recipient.

        Args:
            sender_agent_id: The agent posting the message.
            recipient_agent_id: The intended recipient.

        Raises:
            RoutingError: If no routing entry exists for (sender, recipient).
        """
        if not self._table.allows(sender_agent_id, recipient_agent_id):
            raise RoutingError(
                f'No routing entry: {sender_agent_id!r} → {recipient_agent_id!r}. '
                'Cross-project posts must go through the OM; cross-workgroup posts '
                'must go through the project lead.'
            )
