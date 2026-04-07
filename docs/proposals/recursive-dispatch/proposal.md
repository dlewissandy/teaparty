# Recursive Bus Dispatch

Supersedes:
- The child-Orchestrator dispatch model in `orchestrator/dispatch_cli.py`
- The liaison generation system in `orchestrator/office_manager.py`
- The `uber-team.json` project-lead role (converges with `.claude/agents/` definitions)

---

## Problem

TeaParty's design docs describe arbitrary tree-structured team hierarchies, but the code has two disconnected dispatch mechanisms that each support only one level:

**Path A (Office Manager):** `office_manager.py` runs the OM as a conversational `claude -p` agent with dynamically-built liaison agents via `--agents`. No CfA, no bus, no worktree isolation. The OM cannot start a CfA session or dispatch work that flows through the project-to-workgroup chain.

**Path B (CfA Orchestrator):** `dispatch_cli.py` creates child Orchestrator instances in isolated worktrees. Each child runs a full CfA state machine, but the Orchestrator is the fixed root. There is no management tier above it, and the child Orchestrators cannot dispatch further children because the `BusEventListener` only runs at the top level.

Neither path supports arbitrary depth. A project-lead can `Send` to a workgroup-lead, but the workgroup-lead cannot `Send` to its own agents because it has no bus listener. The hierarchy stops at two tiers.

---

## Design

Every agent that can dispatch to sub-agents gets its own `BusEventListener`. The listener is started by the spawning infrastructure before the agent's `claude -p` process launches, and its socket paths are passed via environment variables. When the agent calls `Send`, its listener spawns the recipient, which may itself get a listener if it has its own roster. The tree grows as deep as the configuration tree defines (currently three levels: OM, project lead, workgroup lead).

This design applies the well-established recursive process tree pattern (as in Erlang/OTP supervision trees) to TeaParty's existing IPC mechanism. The transport primitives are preserved; the orchestration layer is rebuilt on top of them.

The transport primitives that survive unchanged:
- `BusEventListener` handles Send/Reply IPC, spawn, resume, fan-in via `pending_count`, and per-agent re-invocation locks. Each instance is self-contained with instance-scoped socket paths (via `tempfile.mkdtemp`), independent `_reinvoke_locks`, and no shared mutable state. Multiple instances coexist in the same process tree.
- `AgentSpawner` composes worktrees (CLAUDE.md, agents, skills, settings) and launches `claude -p --bare`.
- `RoutingTable.from_workgroups()` derives permitted communication pairs from workgroup membership. In the recursive model, each child listener gets its own `BusDispatcher` built from its own scope for routing enforcement.
- `Send`/`Reply` MCP tools build composite Task/Context envelopes with scratch file flush.

What is rebuilt: the orchestration layer that decides how dispatch happens, how teams are configured, how the OM interacts with project leads, and how CfA wrapping is applied. This is a significant architectural change. The components listed in the retirement table (dispatch_cli.py's dispatch model, liaison generation, team JSON files, phase-config team rosters) are replaced by the recursive spawn path described below.

### The Recursive Spawn

When an agent calls `Send(member, message)`:

1. The agent's `BusEventListener` receives the request on its `SEND_SOCKET`
2. The listener looks up `member` in the agent's roster to determine the recipient's identity and whether the recipient has its own sub-roster
3. If the recipient has a sub-roster (it's a lead with agents under it):
   - Start a new `BusEventListener` for the recipient
   - Derive the recipient's roster from the config tree
   - Compose the recipient's worktree with its roster as `--agents`
   - Construct an MCP config for the recipient with `SEND_SOCKET`/`REPLY_SOCKET`/`CLOSE_CONV_SOCKET` pointing to the new listener's socket paths
   - Launch `claude -p` via `AgentSpawner.spawn(mcp_config=child_mcp_config, extra_env={CONTEXT_ID, AGENT_ID})`
4. If the recipient has no sub-roster (it's a leaf worker):
   - Launch `claude -p` without a listener or MCP Send config. The leaf worker can only `Reply`, not `Send`.
5. The recipient does its work and calls `Reply`
6. The listener handles fan-in, re-invocation, and lifecycle cleanup

#### Child Listener Construction

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

The pluggable functions (`spawn_fn`, `resume_fn`, `reinvoke_fn`) are closures scoped to the child, not methods on the parent Orchestrator. Each closure captures the child's `project_workdir`, `AgentSpawner` instance, and config context. This avoids coupling child listeners to the parent's `self`.

All listeners share the same `messages.db` (the `bus_db_path` is passed from the root). Write serialization is acceptable: bus operations are low-frequency (one write per Send, one per Reply), and Python's async model serializes coroutine execution within the event loop. Cross-tier `pending_count` tracking requires a shared database.

#### Child Listener Lifecycle

When a child's `claude -p` process exits, the spawn function that launched it returns. The spawn function is responsible for stopping the child's listener in a `finally` block:

```python
child_listener = await make_child_listener(...)
await child_listener.start()
try:
    await loop.run_in_executor(None, run_claude_p, child_args)
finally:
    await child_listener.stop()
```

Shutdown order is bottom-up by construction: a child's `claude -p` process completes only after all its own spawned agents have replied (fan-in), which means grandchild listeners are already stopped before the child listener stops. This mirrors the existing pattern in `engine.py:330` where the top-level listener is stopped in a `finally` block.

#### Failure Handling

If a spawned `claude -p` process exits with non-zero status or dies unexpectedly:

1. The spawn function's `finally` block stops the child's listener (preventing orphaned sockets)
2. The spawn function synthesizes an error Reply on behalf of the failed agent, decrementing the parent's `pending_count`
3. The parent agent is re-invoked with the error Reply in its history, allowing it to handle the failure (retry, skip, or escalate)

This is the same failure mode that exists in the current flat dispatch (a dead agent cannot Reply, leaving `pending_count` stuck). The error-Reply synthesis closes this gap at every level. If a subtree fails repeatedly, error Replies propagate upward through each level's fan-in until the root can decide how to respond.

#### Concurrency Limits

The tree depth is bounded by the configuration tree, not by runtime decisions. In the current TeaParty config, the maximum depth is 3 (OM to project-lead to workgroup-lead to worker). Agents cannot spawn arbitrarily; they can only Send to roster members derived from the finite config tree.

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

### Roster Derivation

Each agent's roster is derived from the configuration tree at spawn time. The derivation follows the chain of command:

- **OM's roster:** project leads from `members.projects` in `teaparty.yaml`, plus management-level agents from `members.agents`
- **Project lead's roster:** workgroup leads from `members.workgroups` in `project.yaml`
- **Workgroup lead's roster:** agents from `members.agents` in the workgroup YAML

The roster is materialized as the `--agents` JSON passed to `claude -p`. Each entry includes a description (from the workgroup or agent definition) that the lead uses for dispatch decisions.

Roster derivation lives in a new module, `orchestrator/roster.py`. It depends on `config_reader.py` for YAML loading and on `bus_dispatcher.py` for the `RoutingTable` agent ID format. See [references/roster-derivation.md](references/roster-derivation.md) for function signatures, examples, and the sub-roster detection algorithm.

### Routing Enforcement

Each listener's `BusDispatcher` enforces that agents only Send to roster members. At the project and workgroup levels, `RoutingTable.from_workgroups()` provides the routing table as it does today. At the OM level, a new routing constructor is needed: `RoutingTable.from_management_roster()`, which maps the OM to its project leads and management agents. This is a thin addition to `bus_dispatcher.py` that mirrors `from_workgroups()` but operates on the management-level config.

### CfA as a Per-Agent Wrapper

The CfA state machine (intent, plan, execute, with approval gates) is preserved. It becomes a wrapper that any dispatched agent can run under, not a fixed property of the top-level Orchestrator.

The `Orchestrator` class is refactored into two concerns:

1. **CfA phase runner** -- a standalone component that drives the intent/plan/execute loop, handles backtracks, and manages approval gates. Extracted from the existing `Orchestrator._run_phase()` loop. Its interface:

```python
class CfaPhaseRunner:
    def __init__(self, cfa_machine: CfaMachine, session_id: str,
                 bus_event_listener: BusEventListener, bridge: BridgeClient | None):
        ...

    async def run(self, task: str, history_path: Path) -> PhaseResult:
        """Drive the agent through intent -> plan -> execute with approval gates."""
        ...
```

The `CfaPhaseRunner` receives a `BusEventListener` (for the agent's dispatch capability) and an optional `BridgeClient` (for approval gate UI). It does not own the listener or the spawner; it uses them.

2. **Bus dispatch runtime** -- starts the `BusEventListener`, manages agent lifecycle, handles fan-in. This is the existing bus integration in `engine.py` lines 265-500+.

For agents configured with `cfa: true` in their workgroup or agent definition, the spawner wraps them in the `CfaPhaseRunner`. The spawner constructs a `CfaMachine` instance for the child, starts the child's listener, and hands both to the runner. Leaf agents (workers doing a specific task) run as plain `claude -p` with no CfA overhead.

Approval gates for child CfA instances route through the bridge to the human, the same as the top-level Orchestrator's gates today. Each CfA-wrapped child has its own approval flow. Nested CfA instances (a CfA-wrapped lead dispatching to another CfA-wrapped lead) operate independently; the inner state machine does not block the outer. The outer lead's Send blocks on the inner lead's Reply, and the inner lead runs its own CfA phases before replying.

### OM on the Bus

`OfficeManagerSession.invoke()` is refactored to use the bus model. A `BusEventListener` is started for the OM, its roster is derived from `members.projects` (project leads) and `members.agents` (management agents), its worktree is composed with its roster, and `claude -p` launches with the bus sockets. The OM uses `Send`/`Reply` to dispatch work to project leads.

The OM's multi-turn conversation model is preserved through `--resume` with session ID tracking. The change is that dispatch goes through `Send` on the bus instead of through Claude's native `--agents` team mechanism. Replies arrive via history injection (`_bus_inject_reply`), which writes to the session's `.jsonl` file and resumes with `--resume`. This injection model works for the Orchestrator's phase-based flow today. The OM's conversational pattern (multi-turn human dialogue interleaved with dispatch) is a different interaction pattern that needs validation; the injection model has not been tested with conversational agents.

The dynamically-built liaison agents (`_build_liaison_agents_json()`, `_make_project_liaison_def()`, `_make_configuration_liaison_def()`) are retired. The OM talks directly to project leads via `Send`. Project leads are real agents with their own worktrees and bus listeners, not lightweight representatives in the OM's context.

### members.projects in Config

The OM's roster derivation requires knowing which projects the OM can dispatch to. The `members.projects` key already exists in `teaparty.yaml` but is currently ignored by the `ManagementTeam` dataclass. Issue #379 deliberately removed `members_projects` from `ManagementTeam` during a refactor, with test assertions (`test_issue_251.py`, `test_issue_362.py`, `test_issue_373.py`) enforcing its absence. The rationale was that all registered projects are active, so a separate membership list is redundant.

Recursive dispatch changes this calculus. The `projects:` registry lists all known projects (currently four: TeaParty, pybayes, Jainai, comics), but the OM should only dispatch to projects that are staffed and ready for work. `members.projects` provides this scoping: the OM dispatches to `[TeaParty]`, not to every registered project. The field must be reintroduced to `ManagementTeam`, and the three test files updated with rationale for why the #379 removal no longer applies.

```python
@dataclass
class ManagementTeam:
    ...
    members_projects: list[str] = field(default_factory=list)
```

The membership guard logic currently in `dispatch_cli.py:163-193` (checking workgroup registration vs. active membership before dispatch) migrates to the roster derivation module. The guard concept survives; `dispatch_cli.py` does not. The OM can only dispatch to projects listed in `members.projects`.

---

## What Gets Retired

| Component | Disposition |
|-----------|------------|
| `dispatch_cli.py` child Orchestrator model | Replaced by recursive bus listeners. See behavior disposition below. |
| `office_manager.py` liaison generation | `_build_liaison_agents_json()`, `_make_project_liaison_def()`, `_make_configuration_liaison_def()` are removed. OM uses bus Send/Reply. |
| `uber-team.json` project-lead | Converged with `.claude/agents/teaparty-lead.md`. One identity per project lead. |
| `agents/*.json` team files | Retired (#385). Workgroup agent definitions now live in `.teaparty/project/agents/` (markdown) and `.teaparty/project/workgroups/` (YAML). |
| `phase-config.json` teams section | Team listings move to project.yaml `members.workgroups`. The phase-config retains phase definitions (intent, planning, execution) but not team rosters. |

### dispatch_cli.py Behavior Disposition

The 583-line `dispatch_cli.py` module contains several behaviors beyond its core dispatch function. Their disposition under the recursive bus model:

| Behavior | Lines | Disposition |
|----------|-------|------------|
| `dispatch()` function | 122+ | Replaced by the recursive spawn path in the bus listener |
| Worktree creation | within dispatch | Preserved, moved to `AgentSpawner` (already handles worktree composition) |
| Squash-merge of results | via `merge.py` | Preserved. Each listener's cleanup function calls squash-merge when a child's worktree work is complete. |
| Retry budget | within dispatch | Dropped. Failed spawns produce error Replies that propagate to the parent, which decides whether to retry. Retry is a parent-agent decision, not infrastructure. |
| Heartbeat registration | within dispatch | Migrated to the bus listener lifecycle. The listener registers heartbeats for its spawned agents. |
| Progress tracking | within dispatch | Migrated to the bus listener, which tracks spawn/reply status per agent. |
| Dispatch membership guard | 163-193 | Migrated to roster derivation. Membership checking happens at roster construction time, not dispatch time. |
| Direct execution model | 203+ | Dropped. All spawns use worktree isolation. Direct execution (running in the session worktree without isolation) is incompatible with recursive dispatch where multiple agents may operate concurrently. |

---

## Lateral Communication

The recursive model enforces strict hierarchical communication: agents Send to roster members (downward) and Reply to their caller (upward). Cross-cutting concerns route through the management hierarchy. A developer needing to consult a different workgroup's surveyor sends a Reply to its workgroup lead, which escalates to the project lead, which dispatches to the other workgroup. Each boundary compresses context through the Task/Context envelope.

This is a deliberate tradeoff, not an unacknowledged limitation. Hierarchical compaction (documented in `docs/conceptual-design/hierarchical-teams.md`) controls context explosion in deep hierarchies by forcing each boundary to compress. Allowing lateral communication between arbitrary agents would bypass context compaction and require every agent to understand every other agent's domain.

The existing `RoutingTable.from_workgroups()` cross-workgroup pairs provide a foundation for future lateral routing if the tradeoff needs revisiting. For now, the proposal targets task delegation (the primary use case), where routing through leads is acceptable.

---

## Doc Reconciliation

| Document | Change |
|----------|--------|
| `docs/conceptual-design/hierarchical-teams.md` | Update to describe bus-based dispatch instead of liaison-based. The conceptual model (context isolation at boundaries, hierarchical compaction) is unchanged; only the mechanism changes. |
| `docs/proposals/office-manager/proposal.md` | Remove liaison references. OM dispatches to project leads via Send. |
| `docs/proposals/team-configuration/references/liaisons-and-instances.md` | Retire. The liaison/instance distinction is replaced by recursive spawn. |
| `docs/proposals/agent-dispatch/proposal.md` | Update implementation status. The "disposition of liaison agents" section is now realized. |
| `docs/proposals/agent-dispatch/references/routing.md` | Update implementation status for agent_id derivation and roster composition. |

---

## Acceptance Criteria

1. An OM dispatch flows through three tiers: OM -> project-lead -> workgroup-lead -> worker. Each tier runs as an independent `claude -p` process with its own bus listener (except leaf workers).
2. Fan-in works at every level: a workgroup-lead that `Send`s to 3 workers resumes only when all 3 `Reply`. A project-lead that `Send`s to 2 workgroup-leads resumes only when both `Reply`.
3. Worktree isolation holds at every level: each spawned agent gets a composed worktree with only the agents, skills, and settings appropriate to its role.
4. CfA phases (plan/execute with approval gates) can be applied at any tier, controlled by config.
5. The existing test suite passes: bus_event_listener, bus_dispatcher, agent_spawner, and Send/Reply handler tests continue to work.
6. A failed `claude -p` process at any tier produces an error Reply that propagates to its parent, preventing orphaned `pending_count`.

---

## Prerequisites

- [Agent Dispatch](../agent-dispatch/proposal.md) -- bus transport, Send/Reply, routing rules. This proposal extends Agent Dispatch's single-level bus model to arbitrary depth.
- [Workgroup Model](../workgroup-model/proposal.md) -- the configuration tree that roster derivation reads from.
- [Messaging](../messaging/proposal.md) -- durable bus store with agent context records, pending_count, two-record atomicity.

---

## Relationship to Other Proposals

- [Context Budget](../context-budget/proposal.md) -- scratch file composition at every Send boundary. Each recursive spawn compresses context through the Task/Context envelope.
- [CfA Extensions](../cfa-extensions/proposal.md) -- INTERVENE/WITHDRAW propagation through the bus conversation hierarchy. Recursive listeners provide the structural depth that escalation routing requires.
- [Team Configuration](../team-configuration/proposal.md) -- workgroup membership is the input to roster derivation. `members.projects` and `members.workgroups` drive who can dispatch to whom.
