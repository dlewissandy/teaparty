[Agent Dispatch](../proposal.md) >

# Routing

## Bus Routing Rules

Routing policy determines which agents can communicate with which others. An agent can only `Send` to members explicitly listed in its `--agents` roster. TeaParty composes the roster at spawn time — an agent has no visibility into, and no route to, any agent not in its roster.

Within a workgroup, each agent's roster includes all other agents in the same workgroup. The lead's roster includes all workers; each worker's roster includes the lead (via requestor injection) and, optionally, peer workers if peer communication is permitted for that workgroup. Cross-workgroup within a project, a workgroup lead's roster includes the project lead and vice versa; workers do not have the project lead in their roster and cross-workgroup requests go through the workgroup lead. Cross-project, only the project lead and OM have routes to each other — the project lead's roster includes the OM, and the OM's roster includes all project leads.

Routing is enforced at two layers. `Send` performs a client-side pre-check: if the named member is not in the agent's roster, it raises `UnknownMemberError` before touching the bus. The bus dispatcher is an independent enforcement point: it performs a transport level check on every post, verifying a routing entry exists for `(sender_agent_id, recipient_agent_id)`. A message that reaches the bus without going through `Send` is still rejected at the transport level if no routing entry exists. The two checks are not redundant — `Send` gives the agent a clean error to handle in its own turn; the dispatcher ensures routing cannot be bypassed even when callers post directly to the bus transport.

Note that directed sends used for INTERVENE/escalation bypass both of these checks. Authorization for escalation is by conversation hierarchy position, not by routing table entry. Workers do not have project-lead routing entries, and the escalation path is deliberately carved out from normal routing enforcement to allow any spawned agent to reach its ancestry. This carve-out is described in [Escalation Routing](conversation-model.md#escalation-routing).

## Agent Identity

An `agent_id` is the stable, unique identifier for an agent within a session. The format is project-scoped: `{project_name}/{workgroup_name}/{role_name}` (e.g., `my-backend/coding/team-lead`, `my-backend/coding/specialist`). The project lead's `agent_id` is `{project_name}/lead` (e.g., `my-backend/lead`) — it has no workgroup component since it sits above the workgroups. The office manager is org-level and has no project prefix: its `agent_id` is `om`. Agent IDs are stable across all re-invocations within a session — not per-invocation UUIDs. The same agent processing three sequential `--resume` calls has the same `agent_id` throughout.

`agent_id` values are derived at session start from the configuration YAML files. For each active project:

- `project_name` — the project's directory name (e.g., `my-backend` from `path: ~/git/my-backend` in `teaparty.yaml`)
- `workgroup_name` — the workgroup's key in `project.yaml`: the `ref:` value for org-level shared workgroups (e.g., `ref: coding` → `coding`) or the inline `name:` slug for project-scoped workgroups
- `role_name` — the `agents[].role` field in the workgroup YAML (e.g., `role: team-lead`, `role: specialist`)
- `project_name/lead` — the project lead's `agent_id`, assigned regardless of what agent definition name the `lead:` field in `project.yaml` points to
- `om` — the office manager's `agent_id`, a hardcoded convention for the management team lead; it is registered unconditionally at session start regardless of what the `lead:` field in `teaparty.yaml` names

`Send` takes a `member` string (the name key of a roster entry) and resolves it to a full `agent_id` by looking up TeaParty's roster map for the calling agent. Both `member` name-based lookup and the underlying routing check operate against the same routing table derived from workgroup YAML at session start.

## Matrixed Workgroup Routing

A matrixed (shared) workgroup can be deployed in multiple projects. When the same workgroup definition appears in project A and project B, the derivation algorithm produces distinct agent IDs for each deployment: `project-a/coding/team-lead` and `project-b/coding/team-lead` are different identities with no routing relationship. Shared workgroup membership does not create cross-project routes.

The derivation algorithm processes each project's workgroup membership independently and scopes all routing entries to that project. A coding agent deployed in project A gets within-workgroup routes to its project-A teammates and a cross-workgroup route to the project-A lead. It has no route to the coding agent in project B, even though both agents come from the same workgroup definition. Cross-project communication between them still flows through their respective project leads and the OM, exactly as it would for non-shared workgroups.

## Routing Table Format

The routing table is the shared data structure between the roster composition step (reads workgroup YAML and participant config, writes the table) and the bus dispatcher (reads the table to authorize posts).

Derived from roster compositions: for every agent spawned in the session, TeaParty reads its roster map entries and extracts `(caller_agent_id, member_agent_id)` pairs — one pair per roster entry, where `caller_agent_id` is the spawned agent's identity and `member_agent_id` is the `agent_id` from TeaParty's roster map for that entry. The union of all such pairs across all spawned agents is the routing table.

The table is a set of `(sender_agent_id, recipient_agent_id)` pairs. Each pair encodes a permitted directed communication channel. Examples derived from roster composition:

- Within-workgroup (bidirectional): `(my-backend/coding/team-lead, my-backend/coding/specialist)` and `(my-backend/coding/specialist, my-backend/coding/team-lead)` — present because each agent's roster includes the other.
- Cross-workgroup: `(my-backend/coding/team-lead, my-backend/lead)` and `(my-backend/lead, my-backend/coding/team-lead)` — present because the workgroup lead's roster includes the project lead, and the project lead's roster includes the workgroup lead.
- Cross-project: `(my-backend/lead, om)` and `(om, my-backend/lead)` — present because the project lead's roster includes the OM and vice versa.

The table is keyed by `sender_agent_id`. The dispatcher's authorization check: given the sender's `agent_id` and the target context ID, does a routing entry exist for `(sender_agent_id, recipient_agent_id)`? Context ownership is tracked in the bus conversation context record, which stores both `initiator_agent_id` and `recipient_agent_id`. For `Reply` calls, the dispatcher resolves the target from the context record's `initiator_agent_id` field, then checks whether a `(sender, initiator)` routing pair exists.

The table is built incrementally as agents are spawned and held in memory by the bus event listener for the session's duration. It is not persisted between sessions. An agent spawned mid-session has its roster entries added to the table at spawn time.

**Restart recovery.** Because the routing table is ephemeral but bus context records are durable, a restart leaves open contexts with no corresponding routing entries. Recovery rebuilds the routing table from configuration before re-invoking any waiting callers. Full recovery mechanics — including handling of cyclic graphs from mid-task clarification — are in [Routing Table Recovery After Restart](invocation-model.md#routing-table-recovery-after-restart).

## The OM as Cross-Project Gateway

The office manager holds cross-project context. Project A's lead posts a cross-project request to the OM conversation. The OM receives it with full context about what Project A needs, then posts to Project B's lead on its own conversation context. The response flows back through the OM to Project A's lead. The OM provides framing in both directions — Project B's lead receives a request with sufficient context, not a raw message from an unknown caller. The routing function is implemented as OM mediation rather than a dedicated agent role.

## Disposition of Liaison Agents

Routing and context translation are handled by bus rules and OM mediation, without a dedicated liaison role.

The current liaison agent definitions in `orchestrator/office_manager.py` (`_make_project_liaison_def()`, `_make_configuration_liaison_def()`, `_build_liaison_agents_json()`) implement this routing function as a dedicated agent layer. This proposal supersedes that approach: the routing function moves to the bus dispatcher and the context translation function moves to the OM. The existing liaison definitions will be removed when the bus routing implementation is complete.

**Issue #332** (OM chat invocation missing liaisons): the fix is bus routing rules and OM cross-project mediation, not liaison agent definitions. The scope of #332 changes accordingly.

**Chat Experience Pattern 4** (Liaison Chat): deferred in the original proposal for licensing reasons. With this architecture, the routing function does not require a separate agent. If future multi-user scenarios require a liaison *conversation* (human-visible channel between two teams), that is a navigator UI feature, not a new agent role.

## Bus Dispatcher Location

The bus dispatcher is a component in the TeaParty orchestrator process — a Python class in `orchestrator/` that sits between the message bus transport and the agent invocation layer. It holds the routing table for the session and performs the transport-level authorization check on every incoming post. The `Send` MCP tool calls it synchronously before writing to the bus; direct bus writes go through the dispatcher's transport-level intercept. The dispatcher is not a separate server or process.

## Routing Rule Storage

Routing rules are derived from roster compositions. The workgroup YAML and participant config are the inputs; the roster map entries are the intermediate representation; the routing table is the output.

Changes to workgroup membership take effect at the start of the next session — roster compositions are computed at spawn time using the configuration as it stands when the session begins. Adding an agent to a workgroup causes it to appear in the appropriate rosters at next spawn; removing it causes it to disappear. No separate routing configuration to maintain.

## Implementation Status

The following are implemented in `orchestrator/bus_dispatcher.py` (Issue #351):

- The routing table (`RoutingTable` class — set of `(sender_agent_id, recipient_agent_id)` pairs, built at session start via `RoutingTable.from_workgroups()`)
- The bus dispatcher class (`BusDispatcher` — transport-level authorization check; raises `RoutingError` for unauthorized pairs)
- The `RoutingError` raised when a message violates routing policy

Not yet implemented:

- The `agent_id` derivation algorithm from workgroup YAML (routing table is currently built from explicit workgroup dicts; full YAML-driven derivation is a follow-on)
- The routing table recovery procedure (rebuilds from bus context records on restart)
- `Send`'s client-side `UnknownMemberError` pre-check (the `BusDispatcher` transport check is the active enforcement layer)

Until both the `Send` pre-check and the bus dispatcher transport check are fully wired into the MCP tool layer, routing enforcement is implemented at the class level but not yet active at runtime for all call paths. The cross-project isolation guarantee stated in this document is a design intent that the dispatcher enforces when called.
