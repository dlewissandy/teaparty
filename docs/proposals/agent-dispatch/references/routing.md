[Agent Dispatch](../proposal.md) >

# Routing

## Bus Routing Rules

Routing policy determines which agents can initiate conversations with which others. Rules are derived from workgroup membership at session configuration time — they are not dynamic per-message.

**Within a workgroup:** any agent can message any other agent in the same workgroup. The lead can post to any worker; workers can post back to the lead.

**Cross-workgroup within a project:** requests go through the project lead. A coding worker does not have a direct bus route to a config specialist or a research agent. The project lead is the routing hub for cross-workgroup work.

**Cross-project:** always mediated by the office manager. Project-scoped agents have no bus routes to other projects. The OM is the only agent with cross-project context.

These rules are enforced by the bus dispatcher — a message posted to an unauthorized context ID is rejected at the transport level, not left to the agent's judgment.

## The OM as Cross-Project Gateway

The office manager holds cross-project context. When Project A's lead needs something from Project B:

1. Project A's lead posts to the OM conversation (cross-project request)
2. OM receives the request with full context about what Project A needs
3. OM posts to Project B's lead (or OM) on its own conversation context
4. Response flows back through the OM to Project A's lead

The OM provides framing in both directions — Project B's lead receives a request with sufficient context, not a raw message from an unknown caller. This is the liaison function, implemented as OM mediation rather than a dedicated agent role.

## Disposition of Liaison Agents

The liaison agent concept — a dedicated agent whose role is to bridge between teams — is not implemented. The routing function is covered by bus routing rules. The context translation function is covered by the OM for cross-project work and by the lead for cross-workgroup work within a project.

**Issue #332** (OM chat invocation missing liaisons): the fix is bus routing rules and OM cross-project mediation, not liaison agent definitions. The scope of #332 changes accordingly.

**Chat Experience Pattern 4** (Liaison Chat): deferred in the original proposal for licensing reasons. With this architecture, the routing function does not require a separate agent. If future multi-user scenarios require a liaison *conversation* (human-visible channel between two teams), that is a navigator UI feature, not a new agent role.

## Routing Rule Storage

Routing rules are derived at session start from the active workgroup configuration. They are not stored as static config — they are computed from workgroup membership. The workgroup YAML (team members, lead, project scope) is the input; the routing table is the output.

This means adding an agent to a workgroup automatically grants it the routing access appropriate to that workgroup. Removing it revokes access. No separate routing config to maintain.
