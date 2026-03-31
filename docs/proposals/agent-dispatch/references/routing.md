[Agent Dispatch](../proposal.md) >

# Routing

## Bus Routing Rules

Routing policy determines which agents can initiate conversations with which others. Rules are computed at session start from workgroup membership, not stored as static config.

**Within a workgroup:** any agent can message any other agent in the same workgroup. The lead can post to any worker; workers can post back to the lead on the existing conversation context using `ReplyTo`.

**Cross-workgroup within a project:** requests go through the project lead. A coding worker has no direct bus route to a config specialist or a research agent. The project lead is the cross-workgroup routing hub and provides framing when forwarding requests between workgroups.

**Cross-project:** always mediated by the office manager. Project-scoped agents have no bus routes to other projects. The OM is the only agent with cross-project context.

These rules are enforced by the bus dispatcher. `AskTeam` checks routing authorization before posting — if the caller has no route to the target role, it raises `RoutingError` in the caller's turn without writing to the bus. This is a client-side pre-check. The bus dispatcher performs the same check at the transport layer as an independent enforcement point; a message that bypasses `AskTeam` and posts directly to an unauthorized context ID is rejected at the transport level. The two checks are not redundant by accident — `AskTeam` gives the caller a clean error to handle; the bus dispatcher ensures enforcement does not depend on all callers going through `AskTeam`.

## Agent Identity

An `agent_id` is the stable, unique identifier for an agent within a session: `{workgroup_name}/{role_name}` (e.g., `coding-team/lead`, `config-team/specialist`). It is stable across all re-invocations within a session — not a per-invocation UUID. The same agent processing three sequential `--resume` calls has the same `agent_id` throughout.

`agent_id` values are derived at session start from the workgroup YAML. Each workgroup has a name; each agent definition within the workgroup has a role name. The derivation algorithm reads these and assigns `{workgroup_name}/{role_name}` as each agent's stable identity. `AskTeam` takes a `role` string (scoped to the caller's workgroup) and resolves it to an `agent_id` through this mapping before performing the routing check.

## Routing Table Format

The routing table is the shared data structure between the derivation algorithm (reads workgroup YAML, writes the table) and the bus dispatcher (reads the table to authorize posts).

The routing table is a set of `(sender_agent_id, recipient_agent_id)` pairs. Each pair encodes a permitted directed communication channel. The derivation algorithm produces one pair for each permitted channel:

- Within-workgroup: one pair for each ordered (agent_a, agent_b) combination where both agents share a workgroup. This covers both directions: `(lead, worker)` and `(worker, lead)`. Workers can reply to leads because the `(worker, lead)` pair exists.
- Cross-workgroup: one pair for each (lead, project_lead) and (project_lead, lead) combination across workgroups within a project.
- Cross-project: one pair for each (project_lead, om) and (om, project_lead) combination.

The table is keyed by `sender_agent_id`. The dispatcher's authorization check is: given the sender's agent ID and the target context ID, is there a routing entry that permits this sender to post to a context owned by the target agent? Context ownership is tracked in the bus conversation context record, which maps `context_id` to both `initiator_agent_id` and `recipient_agent_id`. For `ReplyTo` calls, the dispatcher resolves the target agent from the context record's `initiator_agent_id` field (the agent that created the context), then checks whether a `(sender, initiator)` routing pair exists.

The table is computed once at session start and held in memory by the dispatcher for the session's duration. It is not persisted between sessions.

## The OM as Cross-Project Gateway

The office manager holds cross-project context. Project A's lead posts a cross-project request to the OM conversation. The OM receives it with full context about what Project A needs, then posts to Project B's lead on its own conversation context. The response flows back through the OM to Project A's lead. The OM provides framing in both directions — Project B's lead receives a request with sufficient context, not a raw message from an unknown caller. This is the liaison function, implemented as OM mediation rather than a dedicated agent role.

## Disposition of Liaison Agents

Routing and context translation are handled by bus rules and OM mediation, without a dedicated liaison role.

The current liaison agent definitions in `orchestrator/office_manager.py` (`_make_project_liaison_def()`, `_make_configuration_liaison_def()`, `_build_liaison_agents_json()`) implement this routing function as a dedicated agent layer. This proposal supersedes that approach: the routing function moves to the bus dispatcher and the context translation function moves to the OM. The existing liaison definitions will be removed when the bus routing implementation is complete.

**Issue #332** (OM chat invocation missing liaisons): the fix is bus routing rules and OM cross-project mediation, not liaison agent definitions. The scope of #332 changes accordingly.

**Chat Experience Pattern 4** (Liaison Chat): deferred in the original proposal for licensing reasons. With this architecture, the routing function does not require a separate agent. If future multi-user scenarios require a liaison *conversation* (human-visible channel between two teams), that is a navigator UI feature, not a new agent role.

## Bus Dispatcher Location

The bus dispatcher is a component in the TeaParty orchestrator process — a Python class in `orchestrator/` that sits between the message bus transport and the agent invocation layer. It holds the routing table for the session and performs the transport-level authorization check on every incoming post. `AskTeam` calls it synchronously before writing to the bus; direct bus writes (via `ReplyTo` or any other path) go through the dispatcher's transport-level intercept. The dispatcher is not a separate server or process.

## Routing Rule Storage

Routing rules are computed at session start from workgroup membership. The workgroup YAML — team members, lead, project scope — is the input; the routing table is the output.

Changes to workgroup membership take effect at the start of the next session. Adding an agent to a workgroup grants it the appropriate routing access; removing it revokes access. No separate routing configuration to maintain.
