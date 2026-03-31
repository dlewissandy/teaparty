[Agent Dispatch](../proposal.md) >

# Routing

## Bus Routing Rules

Routing policy determines which agents can initiate conversations with which others. Rules are computed at session start from workgroup membership, not stored as static config.

**Within a workgroup:** any agent can message any other agent in the same workgroup. The lead can post to any worker; workers can post back to the lead on the existing conversation context using `ReplyTo`.

**Cross-workgroup within a project:** requests go through the project lead. A coding worker has no direct bus route to a config specialist or a research agent. The project lead is the cross-workgroup routing hub and provides framing when forwarding requests between workgroups.

**Cross-project:** always mediated by the office manager. Project-scoped agents have no bus routes to other projects. The OM is the only agent with cross-project context.

These rules are enforced by the bus dispatcher. `AskTeam` checks routing authorization before posting — if the caller has no route to the target role, it raises `RoutingError` in the caller's turn without writing to the bus. This is a client-side pre-check. The bus dispatcher performs the same check at the transport layer as an independent enforcement point; a message that bypasses `AskTeam` and posts directly to an unauthorized context ID is rejected at the transport level. The two checks are not redundant by accident — `AskTeam` gives the caller a clean error to handle; the bus dispatcher ensures enforcement does not depend on all callers going through `AskTeam`.

## Agent Identity

An `agent_id` is the stable, unique identifier for an agent within a session. The format is project-scoped: `{project_name}/{workgroup_name}/{role_name}` (e.g., `teaparty/coding-team/lead`, `teaparty/config-team/specialist`). The project lead's `agent_id` is `{project_name}/lead` (e.g., `teaparty/lead`) — it has no workgroup component since it sits above the workgroups. The office manager is org-level and has no project prefix: its `agent_id` is `om`. Agent IDs are stable across all re-invocations within a session — not per-invocation UUIDs. The same agent processing three sequential `--resume` calls has the same `agent_id` throughout.

`agent_id` values are derived at session start. For each active project, the derivation algorithm reads that project's workgroup YAMLs and assigns `{project_name}/{workgroup_name}/{role_name}` to each agent and `{project_name}/lead` to the project lead. The OM is registered as `om`. `AskTeam` takes a `role` string (scoped to the caller's workgroup) and resolves it to a full `agent_id` by prepending the caller's project and workgroup context before performing the routing check.

## Matrixed Workgroup Routing

A matrixed (shared) workgroup can be deployed in multiple projects. When the same workgroup definition appears in project A and project B, the derivation algorithm produces distinct agent IDs for each deployment: `project-a/coding-team/lead` and `project-b/coding-team/lead` are different identities with no routing relationship. Shared workgroup membership does not create cross-project routes.

The derivation algorithm processes each project's workgroup membership independently and scopes all routing entries to that project. A coding agent deployed in project A gets within-workgroup routes to its project-A teammates and a cross-workgroup route to the project-A lead. It has no route to the coding agent in project B, even though both agents come from the same workgroup definition. Cross-project communication between them still flows through their respective project leads and the OM, exactly as it would for non-shared workgroups.

## Routing Table Format

The routing table is the shared data structure between the derivation algorithm (reads workgroup YAML, writes the table) and the bus dispatcher (reads the table to authorize posts).

The routing table is a set of `(sender_agent_id, recipient_agent_id)` pairs. Each pair encodes a permitted directed communication channel. The derivation algorithm produces one pair for each permitted channel:

- Within-workgroup: one pair for each ordered (agent_a, agent_b) combination where both agents share a workgroup within the same project. This covers both directions: `(teaparty/coding-team/lead, teaparty/coding-team/specialist)` and `(teaparty/coding-team/specialist, teaparty/coding-team/lead)`. Workers can reply to leads because the `(worker, lead)` pair exists.
- Cross-workgroup: one pair for each (workgroup_lead, project_lead) and (project_lead, workgroup_lead) combination across workgroups within a project. For example: `(teaparty/coding-team/lead, teaparty/lead)` and `(teaparty/lead, teaparty/coding-team/lead)`.
- Cross-project: one pair for each (project_lead, om) and (om, project_lead) combination. For example: `(teaparty/lead, om)` and `(om, teaparty/lead)`.

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
