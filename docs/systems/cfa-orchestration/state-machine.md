# CfA State Machine

The CfA state machine (`teaparty/cfa/statemachine/cfa_state.py`) implements the three-phase Conversation for Action protocol introduced in [the CfA overview](index.md). It is integrated with the CfA engine — `teaparty/cfa/engine.py` takes `CfaState` as a core parameter, and `teaparty/cfa/actors.py` routes to the appropriate actor based on CfA state.

---

## Design Choices

**JSON transition table as single source of truth.** The transition table is loaded from `cfa-state-machine.json`, not hardcoded. This file is shared between the state machine code and the conceptual design documentation. Changes to the protocol happen in one place.

**Immutable state transitions.** `transition(cfa, action)` returns a new `CfaState` — it never mutates the input. This makes backtrack safe: the orchestrator can hold previous states without defensive copying, and history is append-only.

**JSON file persistence.** CfA state is persisted as `.cfa-state.json` in the session's infrastructure directory. JSON was chosen over a database because each session runs in an isolated worktree with its own filesystem — file persistence aligns with the isolation model and requires no shared infrastructure.

**Children acknowledge inherited intent quickly.** `make_child_state(parent, team_id)` enters at the INTENT state, not IDEA, because intent has already been approved at the parent level. The child acknowledges the inherited `INTENT.md` rather than re-deriving it, and advances into planning. `phase` matches `phase_for_state(state)` throughout — so the child is briefly in the intent phase (at state INTENT) before its first transition moves it into planning. Future work: consider intent re-validation at narrower scope. A child subteam working on a narrower task could legitimately ask "Is this task part of your original intent?"

---

## State Representation

```python
class CfaState:
    phase: str              # 'intent' | 'planning' | 'execution'
    state: str              # e.g., 'PROPOSAL', 'DRAFT', 'WORK_IN_PROGRESS'
    actor: str              # who should act next
    history: list           # [{state, action, actor, timestamp}, ...]
    backtrack_count: int    # cross-phase backtracks
    task_id: str            # optional, for execution phase
    parent_id: str          # parent task ID for nested CfA
    team_id: str            # team slug
    depth: int              # nesting depth: 0=uber, 1+=subteam
```

---

## Key Functions

- `make_initial_state(task_id, team_id)` — creates root CfA at IDEA state
- `make_child_state(parent, team_id, task_id)` — creates child CfA for dispatch
- `transition(cfa, action)` — validates action against table, returns new CfaState
- `available_actions(state)` — lists valid `(action, actor)` pairs from current state
- `is_backtrack(from_state, action)` — detects cross-phase boundary crossings
- `save_state(cfa, path)` / `load_state(path)` — JSON persistence

---

## Error Handling and Failure Modes

The state machine does not prescribe failure recovery — it transitions based on valid actions from the current state. At the orchestrator level, `engine.py` handles failures:

- **Infrastructure failure during execution:** On catastrophic failures (subprocess crash, unrecoverable CLI error), the engine publishes `INPUT_REQUESTED` with state `INFRASTRUCTURE_FAILURE`, asks the human to choose between `retry`, `backtrack`, or `withdraw`, and routes the response through `teaparty.scripts.classify_review.classify('FAILURE', …)` to resolve the action (`engine.py:_handle_infrastructure_failure`). Each branch then drives a normal `transition(state, action)` from the current CfA state.
- **Escalation during execution:** Escalation is a valid action from most states and transitions to an ESCALATE state for human review.
- **Approval gate rejection:** At ASSERT states, if the human rejects, the state machine provides a corrective action (e.g., `PLAN_ASSERT --correct→ PLANNING_RESPONSE`) that feeds the feedback back into the appropriate phase.

There is no dedicated `on_agent_failure()` method — the engine routes all failures through either the `INFRASTRUCTURE_FAILURE` dialog above or the normal escalation/backtrack paths exposed by `available_actions()`. No built-in timeout or retry — those are orchestrator responsibilities.

---

## No task-level state machine

The execution phase keeps one non-gate non-terminal state: `WORK_IN_PROGRESS`. The project-lead runs normal agent turns inside it, dispatching workgroups over the message bus via `Send` and synthesizing their replies at the turn boundary. Subteam coordination — questions, escalations, retries, revisions — flows through the bus and the proxy escalation chain, not through state-machine edges.

The framework does not model task-level substates. A single scalar state cannot coherently represent concurrent dispatches anyway, and encoding delegation patterns in the graph is prescriptive orchestration — agents are agents, and the framework's job is to give the project-lead the right tools and stay out of its way. Fan-in of parallel worker replies happens at the engine turn boundary (driven by open bus contexts), not via `send-and-wait` / `resume` edges.

Every gate the state machine still carries is project-level: `INTENT_ASSERT`, `PLAN_ASSERT`, `WORK_ASSERT`. All three can escalate to the human when the proxy is not confident, so proxy learning is driven entirely by project-level differentials.
