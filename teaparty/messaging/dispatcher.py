"""Bus dispatcher: routing table and transport-level authorization for agent-to-agent messaging.

The RoutingTable holds the set of permitted ``(sender, recipient)``
pairs for ONE session, derived from that session's team roster.
Each slot is the agent's **name** as it appears in the roster — an
agent's name is its identity, with 1:1 correspondence between the
string and the agent.  No aliases, no translation map, no parallel
namespace.

The BusDispatcher wraps the table and is the independent enforcement
point — every bus post goes through it, whether via the Send MCP tool
or via a direct bus write.

ONE WAY OF BUILDING ROUTING TABLES: ``build_routing_table(roster)``.
The Roster (in ``teaparty.config.roster``) is **flat** — one team's
lead, members, mesh flag, and parent_lead.  Sub-team routing happens
in the sub-team's own session's dispatcher, built from the sub-team's
own flat roster; no global tree.

Routing rules emerge from the flat Roster:

  * lead ↔ each direct member (always)
  * within-team mesh among members (when ``mesh_among_members``)
  * lead ↔ ``parent_lead`` (cross-team gateway, conversation-scoped)

See docs/proposals/agent-dispatch/references/routing.md for the spec.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from teaparty.config.roster import Roster


class RoutingError(Exception):
    """Raised when a message violates the routing policy."""


class DuplicateAgentName(ValueError):
    """Raised when the same agent name appears as the lead of two teams.

    Leads are in 1:1 correspondence with their team — one lead heads
    exactly one team.  Two teams sharing a lead is a config error.

    Routing-table construction itself can no longer detect this
    (each session builds a flat roster for one team, so its lead
    appears exactly once).  Detection happens at config-load time
    against the management catalog.

    Member-name duplication across teams is *allowed*: the same agent
    can be a member of multiple workgroups; routing simply adds them
    to each group's mesh in each group's own session.
    """


@dataclass
class RoutingTable:
    """Set of permitted (sender_name, recipient_name) pairs.

    Built at session start by ``build_routing_table(roster)``.  Held in
    memory by the BusEventListener for the session's duration.  Not
    persisted between sessions.
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


def build_routing_table(roster: 'Roster') -> RoutingTable:
    """Build a RoutingTable from a flat Roster.

    ONE function, all team types — selected by the roster's flags
    (``mesh_among_members``) and ``parent_lead`` field, not by
    per-team-type branching:

      * lead ↔ each direct member
      * lead ↔ parent_lead (when set, cross-team gateway)
      * within-team mesh among members (when ``mesh_among_members``)
    """
    table = RoutingTable()
    member_names = [m.name for m in roster.members]

    # lead ↔ parent_lead (cross-team gateway)
    if roster.parent_lead and roster.lead:
        table.add_pair(roster.lead, roster.parent_lead)
        table.add_pair(roster.parent_lead, roster.lead)

    # lead ↔ each member
    for name in member_names:
        if roster.lead and name and roster.lead != name:
            table.add_pair(roster.lead, name)
            table.add_pair(name, roster.lead)

    # Within-team mesh (workgroup-style)
    if roster.mesh_among_members:
        for i, a in enumerate(member_names):
            for j, b in enumerate(member_names):
                if i != j and a and b:
                    table.add_pair(a, b)

    return table


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
