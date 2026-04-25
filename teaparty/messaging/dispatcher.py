"""Bus dispatcher: routing table and transport-level authorization for agent-to-agent messaging.

The RoutingTable holds the set of permitted ``(sender, recipient)``
pairs derived from a session's roster.  Each slot is the agent's
**name** as it appears in the roster — an agent's name is its
identity, with 1:1 correspondence between the string and the agent.
No aliases, no translation map, no parallel namespace.  A roster with
duplicate names is a configuration error and must be rejected at load
time.

The BusDispatcher wraps the table and is the independent enforcement
point — every bus post goes through it, whether via the Send MCP tool
or via a direct bus write.

ONE WAY OF BUILDING ROUTING TABLES: ``build_routing_table(roster)``.
The Roster shape (in ``teaparty.config.roster``) is recursive — a
project roster nests its workgroup sub-rosters — and the table builder
walks that structure once.  No per-team-type classmethods.

Routing rules emerge from the Roster shape:

  * lead ↔ each direct member (always)
  * within-team mesh among members + lead (when ``mesh_among_members``)
  * lead ↔ ``parent_lead`` (cross-team gateway)
  * recurse into ``sub_rosters`` and merge

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
    """Raised when a roster contains the same agent name twice.

    Agent names are identifiers; uniqueness within a routing scope is a
    correctness precondition, not a soft constraint.  Caller config is
    wrong and must be fixed.
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
    """Build a RoutingTable from a Roster.

    ONE function, all team types.  Walks the recursive Roster
    structure, adding pairs from each level:

      * lead ↔ each direct member
      * lead ↔ parent_lead (when set)
      * within-team mesh (when ``mesh_among_members``) — every member
        pair plus lead↔member already covered above
      * recursive merge of ``sub_rosters``

    Validates uniqueness across the full tree: collects every name
    visited and raises ``DuplicateAgentName`` on a repeat.  ``proxy``
    is the deliberate exception (one ``proxy`` agent serves multiple
    humans by qualifier).
    """
    table = RoutingTable()
    seen: set[str] = set()
    _populate(table, roster, seen)
    return table


def _populate(
    table: RoutingTable, roster: 'Roster', seen: set[str],
) -> None:
    """Add pairs for one Roster level + recurse into sub_rosters."""
    if roster.lead:
        if roster.lead in seen:
            raise DuplicateAgentName(
                f'Agent name {roster.lead!r} appears more than once in '
                f'the roster tree.  Names are identifiers; rename or '
                f'restructure.',
            )
        seen.add(roster.lead)

    member_names = [m.name for m in roster.members]

    for name in member_names:
        if name == 'proxy':
            continue
        if name in seen:
            raise DuplicateAgentName(
                f'Agent name {name!r} appears more than once in the '
                f'roster tree.  Names are identifiers; rename.',
            )
        seen.add(name)

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

    for sub in roster.sub_rosters:
        _populate(table, sub, seen)


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
