# CfA State Machine

The CfA state machine (`projects/POC/scripts/cfa_state.py`) implements the three-phase Conversation for Action protocol described in [conceptual-design/cfa-state-machine.md](../conceptual-design/cfa-state-machine.md). It is integrated with the orchestrator — `engine.py` takes `CfaState` as a core parameter, and `actors.py` routes to the appropriate actor (AgentRunner or ApprovalGate) based on CfA state.

---

## Design Choices

**JSON transition table as single source of truth.** The transition table is loaded from `cfa-state-machine.json`, not hardcoded. This file is shared between the state machine code and the conceptual design documentation. Changes to the protocol happen in one place.

**Immutable state transitions.** `transition(cfa, action)` returns a new `CfaState` — it never mutates the input. This makes backtrack safe: the orchestrator can hold previous states without defensive copying, and history is append-only.

**JSON file persistence.** CfA state is persisted as `.cfa-state.json` in the session's infrastructure directory. JSON was chosen over a database because each session runs in an isolated worktree with its own filesystem — file persistence aligns with the isolation model and requires no shared infrastructure.

**Child states skip intent.** `make_child_state(parent, team_id)` enters at INTENT (the planning phase entry point), not IDEA, because intent has already been approved at the parent level. This avoids redundant intent gathering at every hierarchy level. Future work: consider intent re-validation at narrower scope. A child subteam working on a narrower task could legitimately ask "Is this task part of your original intent?"

---

## State Representation

```python
class CfaState:
    phase: str              # 'intent' | 'planning' | 'execution'
    state: str              # e.g., 'PROPOSAL', 'DRAFT', 'TASK_IN_PROGRESS'
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

- **Agent failure during execution:** Orchestrator calls `engine.on_agent_failure()`, which validates whether a backtrack is legal (CfA allows it) and executes the transition.
- **Escalation during execution:** Escalation is a valid action from most states and transitions to an ESCALATE state for human review.
- **Approval gate rejection:** At ASSERT states, if the human rejects, the state machine provides a corrective action (e.g., PLAN_ASSERT → PLAN_CORRECTION) that feeds the feedback back into the appropriate phase.

No built-in timeout or retry — those are orchestrator responsibilities.

---

## Never-Escalate Design Pattern and Learning Tradeoff

The orchestrator marks certain states (TASK_ASSERT, TASK_ESCALATE) as **never-escalate** in the approval gate configuration. This means:

1. The state machine allows transition through these states legally.
2. The approval gate is invoked but suppresses human escalation if confidence is low.
3. The proxy's best guess is used instead, even if uncertain.

**Consequence for learning:** When the proxy's guess is wrong at a never-escalate state, no human sees the decision, so no differential is recorded. This silence means high-value learning signals are lost at the task level. The proxy can only learn from escalations at ASSERT states (intent, plan, work).

This is a deliberate tradeoff: uninterrupted execution (goal) vs. task-level learning (cost). See [approval-gate.md](approval-gate.md) for the full discussion of never-escalate states.

---

## Remaining Gaps

- [#92](https://github.com/dlewissandy/teaparty/issues/92): Replace bespoke state management with `python-statemachine` library (would give formal guard conditions, event hooks, and visualization)
- [#46–#57](https://github.com/dlewissandy/teaparty/issues/46): GAP A3.* — plan file detection, permission block gates, backtrack feedback injection, escalation exit codes
- [#38–#45](https://github.com/dlewissandy/teaparty/issues/38): GAP A2.* — intent phase gaps (stale INTENT.md, version bumping, relocation)
