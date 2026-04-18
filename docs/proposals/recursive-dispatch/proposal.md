# Recursive Bus Dispatch

> *Scope narrowed 2026-04-18: the bus transport and single-level dispatch described in earlier revisions are implemented. This proposal covers only the remaining recursive-spawn work.*

---

## Problem

TeaParty has a working bus transport and single-level dispatch: the top-level `BusEventListener` (in `teaparty/messaging/listener.py`) handles Send/Reply IPC, spawn, resume, and fan-in for one tier of dispatch. A lead can `Send` to its direct roster members and resume when they `Reply`.

What does not yet exist is **recursive dispatch**. A dispatched lead cannot itself dispatch further: the child agent is launched as `claude -p` with no bus listener, so when it calls `Send` the call has nowhere to go. The hierarchy stops at two tiers (caller + recipient), even though the configuration tree describes three (OM -> project-lead -> workgroup-lead -> worker).

A project-lead can `Send` to a workgroup-lead, but the workgroup-lead cannot `Send` to its own agents because it has no listener. This proposal closes that gap.

---

## Design

Every dispatched agent that has its own sub-roster gets its own `BusEventListener`. The listener is started by the spawning infrastructure before the agent's `claude -p` process launches, and its socket paths are passed via environment variables. When the dispatched agent calls `Send`, its listener spawns the recipient, which may itself get a listener if it has its own roster. The tree grows as deep as the configuration tree defines (currently three levels: OM, project lead, workgroup lead).

This applies the recursive process-tree pattern (as in Erlang/OTP supervision trees) to TeaParty's existing IPC mechanism. The transport primitives are preserved; only the spawn path is extended to construct nested listeners.

The transport primitives that survive unchanged:
- `BusEventListener` handles Send/Reply IPC, spawn, resume, fan-in via `pending_count`, and per-agent re-invocation locks. Each instance is self-contained with instance-scoped socket paths (via `tempfile.mkdtemp`), independent `_reinvoke_locks`, and no shared mutable state. Multiple instances already coexist safely in the same process tree.
- `AgentSpawner` composes worktrees (CLAUDE.md, agents, skills, settings) and launches `claude -p --bare`.
- `RoutingTable.from_workgroups()` derives permitted communication pairs from workgroup membership. In the recursive model, each child listener gets its own `BusDispatcher` built from its own scope for routing enforcement.
- `Send`/`Reply` MCP tools build composite Task/Context envelopes with scratch file flush.

What is added: the orchestration layer that decides, at spawn time, whether the recipient needs its own listener and, if so, constructs one with child-scoped closures for spawn/resume/reinvoke.

---

## The Recursive Spawn

When an agent calls `Send(member, message)`:

1. The agent's `BusEventListener` receives the request on its `SEND_SOCKET`.
2. The listener looks up `member` in the agent's roster to determine the recipient's identity and whether the recipient has its own sub-roster.
3. If the recipient has a sub-roster (it's a lead with agents under it):
   - Start a new `BusEventListener` for the recipient.
   - Derive the recipient's roster from the config tree.
   - Compose the recipient's worktree with its roster as `--agents`.
   - Construct an MCP config for the recipient with `SEND_SOCKET`/`REPLY_SOCKET`/`CLOSE_CONV_SOCKET` pointing to the new listener's socket paths.
   - Launch `claude -p` via `AgentSpawner.spawn(mcp_config=child_mcp_config, extra_env={CONTEXT_ID, AGENT_ID})`.
4. If the recipient has no sub-roster (it's a leaf worker):
   - Launch `claude -p` without a listener or MCP Send config. The leaf worker can only `Reply`, not `Send`. This is the current single-level behavior.
5. The recipient does its work and calls `Reply`.
6. The listener handles fan-in, re-invocation, and lifecycle cleanup.

### Child Listener Construction

The parent's spawn path constructs the child's `BusEventListener` with child-scoped pluggable functions:

```python
async def make_child_listener(
    child_agent_id: str,
    child_context_id: str,
    bus_db_path: Path,          # same SQLite DB as parent
    child_roster: dict,
    config_tree: ConfigTree,
    project_workdir: Path,
) -> BusEventListener:
    """Construct a BusEventListener for a dispatched agent that has its own sub-roster."""

    spawner = AgentSpawner(project_workdir=project_workdir, ...)

    async def child_spawn_fn(agent_name, task, context_id, agent_id):
        # Recursive: may itself call make_child_listener if the
        # grandchild has a sub-roster
        ...

    async def child_resume_fn(agent_name, replies, context_id, agent_id):
        # Calls claude -p --resume with the child's session ID
        ...

    async def child_reinvoke_fn(agent_name, context_id, agent_id):
        # Calls claude -p --resume to restart the child with injected replies
        ...

    return BusEventListener(
        bus_db_path=bus_db_path,
        spawn_fn=child_spawn_fn,
        resume_fn=child_resume_fn,
        reinvoke_fn=child_reinvoke_fn,
        cleanup_fn=lambda aid: spawner.cleanup(aid),
        current_context_id=child_context_id,
        initiator_agent_id=child_agent_id,
        dispatcher=build_child_dispatcher(child_roster, config_tree),
    )
```

The pluggable functions (`spawn_fn`, `resume_fn`, `reinvoke_fn`) are closures scoped to the child, not methods on a parent Orchestrator. Each closure captures the child's `project_workdir`, `AgentSpawner` instance, and config context. This avoids coupling child listeners to any particular parent's `self`.

All listeners share the same `messages.db` (the `bus_db_path` is passed from the root). Write serialization is acceptable: bus operations are low-frequency (one write per Send, one per Reply), and Python's async model serializes coroutine execution within the event loop. Cross-tier `pending_count` tracking requires a shared database.

### Child Listener Lifecycle

When a child's `claude -p` process exits, the spawn function that launched it returns. The spawn function is responsible for stopping the child's listener in a `finally` block:

```python
child_listener = await make_child_listener(...)
await child_listener.start()
try:
    await loop.run_in_executor(None, run_claude_p, child_args)
finally:
    await child_listener.stop()
```

Shutdown order is bottom-up by construction: a child's `claude -p` process completes only after all its own spawned agents have replied (fan-in), which means grandchild listeners are already stopped before the child listener stops. This mirrors the existing pattern where the top-level listener is stopped in a `finally` block at the end of a session.

### Failure Handling

If a spawned `claude -p` process exits with non-zero status or dies unexpectedly:

1. The spawn function's `finally` block stops the child's listener (preventing orphaned sockets).
2. The spawn function synthesizes an error Reply on behalf of the failed agent, decrementing the parent's `pending_count`.
3. The parent agent is re-invoked with the error Reply in its history, allowing it to handle the failure (retry, skip, or escalate).

This closes the "dead agent cannot Reply, leaving `pending_count` stuck" gap at every level. If a subtree fails repeatedly, error Replies propagate upward through each level's fan-in until the root can decide how to respond.

### Concurrency Limits

Tree depth is bounded by the configuration tree, not by runtime decisions. In the current TeaParty config, the maximum depth is 3 (OM -> project-lead -> workgroup-lead -> worker). Agents cannot spawn arbitrarily; they can only Send to roster members derived from the finite config tree.

Each listener enforces a maximum number of simultaneous spawns (configurable, default matching the roster size). This prevents a single agent from overwhelming the system through rapid fan-out. The limit is per-listener, not global, because each listener's fan-out is independently bounded by its roster.

The recursive structure means a management-level dispatch can flow through multiple levels:

```
OM (listener-0)
  -> Send("teaparty-lead", "implement feature X")
    teaparty-lead (listener-1)
      -> Send("coding-lead", "build the backend")
        coding-lead (listener-2)
          -> Send("developer", "write the module")
            developer (no listener, leaf)
            -> Reply("done, see files A, B, C")
          -> Send("reviewer", "review the module")
            reviewer (no listener, leaf)
            -> Reply("looks good, one nit")
        <- Reply("backend complete")
      -> Send("research-lead", "survey prior art")
        ...
    <- Reply("feature X complete")
```

---

## Roster Derivation

Each dispatched agent's roster is derived from the configuration tree at spawn time. The derivation follows the chain of command:

- **OM's roster:** project leads from `members.projects` in `teaparty.yaml`, plus management-level agents from `members.agents`.
- **Project lead's roster:** workgroup leads from `members.workgroups` in `project.yaml`.
- **Workgroup lead's roster:** agents from `members.agents` in the workgroup YAML.

The roster is materialized as the `--agents` JSON passed to `claude -p`. Each entry includes a description (from the workgroup or agent definition) that the lead uses for dispatch decisions.

Roster derivation lives in a new module: `teaparty/messaging/roster.py` (or the equivalent location in the current layout). It depends on the config loader for YAML and on `bus_dispatcher.py` for the `RoutingTable` agent ID format. See [references/roster-derivation.md](references/roster-derivation.md) for function signatures, examples, and the sub-roster detection algorithm.

The sub-roster detection algorithm is what the recursive spawn path consults in step 2 above to decide whether the recipient needs its own listener.

---

## Routing Enforcement

Each listener's `BusDispatcher` enforces that agents only Send to roster members. At the project and workgroup levels, `RoutingTable.from_workgroups()` provides the routing table as it does today. At the OM level, a new routing constructor is needed: `RoutingTable.from_management_roster()`, which maps the OM to its project leads and management agents. This is a thin addition to `bus_dispatcher.py` that mirrors `from_workgroups()` but operates on the management-level config.

---

## CfA as a Per-Agent Wrapper

With recursive spawn in place, the CfA state machine (intent, plan, execute, with approval gates) becomes a wrapper that any dispatched lead can run under, not a fixed property of a single top-level Orchestrator.

For agents configured with `cfa: true` in their workgroup or agent definition, the spawner wraps them in a `CfaPhaseRunner` that drives the intent/plan/execute loop, handles backtracks, and manages approval gates. The runner receives the child's `BusEventListener` (for the agent's dispatch capability) and an optional `BridgeClient` (for approval gate UI). It does not own the listener or the spawner; it uses them.

Leaf agents (workers doing a specific task) run as plain `claude -p` with no CfA overhead, as they do today.

Approval gates for child CfA instances route through the bridge to the human, the same as the top-level Orchestrator's gates today. Each CfA-wrapped child has its own approval flow. Nested CfA instances (a CfA-wrapped lead dispatching to another CfA-wrapped lead) operate independently; the inner state machine does not block the outer. The outer lead's Send blocks on the inner lead's Reply, and the inner lead runs its own CfA phases before replying.

---

## members.projects in Config

The OM's roster derivation requires knowing which projects the OM can dispatch to. The `members.projects` key already exists in `teaparty.yaml` but is currently ignored by the `ManagementTeam` dataclass. Issue #379 deliberately removed `members_projects` from `ManagementTeam` during a refactor, with test assertions (`test_issue_251.py`, `test_issue_362.py`, `test_issue_373.py`) enforcing its absence. The rationale was that all registered projects are active, so a separate membership list is redundant.

Recursive dispatch changes this calculus. The `projects:` registry lists all known projects, but the OM should only dispatch to projects that are staffed and ready for work. `members.projects` provides this scoping: the OM dispatches to `[TeaParty]`, not to every registered project. The field must be reintroduced to `ManagementTeam`, and the three test files updated with rationale for why the #379 removal no longer applies.

```python
@dataclass
class ManagementTeam:
    ...
    members_projects: list[str] = field(default_factory=list)
```

---

## Lateral Communication

The recursive model enforces strict hierarchical communication: agents Send to roster members (downward) and Reply to their caller (upward). Cross-cutting concerns route through the management hierarchy. A developer needing to consult a different workgroup's surveyor sends a Reply to its workgroup lead, which escalates to the project lead, which dispatches to the other workgroup. Each boundary compresses context through the Task/Context envelope.

This is a deliberate tradeoff. Hierarchical compaction (documented in `docs/conceptual-design/hierarchical-teams.md`) controls context explosion in deep hierarchies by forcing each boundary to compress. Allowing lateral communication between arbitrary agents would bypass context compaction and require every agent to understand every other agent's domain.

The existing `RoutingTable.from_workgroups()` cross-workgroup pairs provide a foundation for future lateral routing if the tradeoff needs revisiting. For now, the proposal targets task delegation (the primary use case), where routing through leads is acceptable.

---

## Acceptance Criteria

1. An OM dispatch flows through three tiers: OM -> project-lead -> workgroup-lead -> worker. Each tier runs as an independent `claude -p` process with its own bus listener (except leaf workers).
2. Fan-in works at every level: a workgroup-lead that `Send`s to 3 workers resumes only when all 3 `Reply`. A project-lead that `Send`s to 2 workgroup-leads resumes only when both `Reply`.
3. Worktree isolation holds at every level: each spawned agent gets a composed worktree with only the agents, skills, and settings appropriate to its role.
4. CfA phases (plan/execute with approval gates) can be applied at any tier, controlled by config.
5. The existing single-level bus tests (bus_event_listener, bus_dispatcher, agent_spawner, Send/Reply handlers) continue to pass unchanged.
6. A failed `claude -p` process at any tier produces an error Reply that propagates to its parent, preventing orphaned `pending_count`.

---

## Prerequisites

- Single-level bus dispatch (implemented in `teaparty/messaging/listener.py`). This proposal extends it to arbitrary depth.
- [Workgroup Model](../../reference/team-configuration.md) -- the configuration tree that roster derivation reads from.
- [Messaging](../../systems/messaging/index.md) -- durable bus store with agent context records, pending_count, two-record atomicity.

---

## Relationship to Other Proposals

- [Context Budget](../../systems/cfa-orchestration/context-budget.md) -- scratch file composition at every Send boundary. Each recursive spawn compresses context through the Task/Context envelope.
- [CfA Extensions](../../systems/cfa-orchestration/state-machine.md) -- INTERVENE/WITHDRAW propagation through the bus conversation hierarchy. Recursive listeners provide the structural depth that escalation routing requires.
- [Team Configuration](../../reference/team-configuration.md) -- workgroup membership is the input to roster derivation. `members.projects` and `members.workgroups` drive who can dispatch to whom.
